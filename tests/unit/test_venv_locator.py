"""Unit tests for the ``pipenv.utils.venv_locator.VenvLocator`` subsystem.

These tests pin the behaviour of the ``VenvLocator`` subsystem that was
extracted from ``pipenv.project.Project`` in task T_D.4. They cover the
constructor, the ``@cached_property`` accessor on ``Project``, the
venv-in-project precedence logic, the lazy ``location`` cache, the
``src_location`` / ``download_location`` / ``proper_names_db_path``
mkdir-on-access semantics, the ``name`` hash-suffix construction, and
the executable-lookup methods (``which``, ``_which``).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from pipenv.project import Project
from pipenv.utils.venv_locator import VenvLocator

PIPFILE_BARE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
"""

PIPFILE_VENV_IN_PROJECT_TRUE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[pipenv]
venv_in_project = true

[packages]

[dev-packages]
"""

PIPFILE_VENV_IN_PROJECT_FALSE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[pipenv]
venv_in_project = false

[packages]

[dev-packages]
"""


@pytest.fixture
def project_bare(tmp_path, monkeypatch):
    """Project pointing at a Pipfile with no ``[pipenv]`` section."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_BARE)
    monkeypatch.chdir(tmp_path)
    # Make sure no inherited VIRTUAL_ENV / PIPENV_VENV_IN_PROJECT envs leak
    # into the test.
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("PIPENV_ACTIVE", raising=False)
    monkeypatch.delenv("PIPENV_VENV_IN_PROJECT", raising=False)
    monkeypatch.delenv("PIPENV_CUSTOM_VENV_NAME", raising=False)
    monkeypatch.delenv("PIPENV_PYTHON", raising=False)
    return Project(chdir=False)


@pytest.mark.utils
def test_venv_locator_constructor_takes_project(project_bare):
    """``VenvLocator(project)`` accepts a ``Project`` reference and
    initialises the three lazy-cache attributes to ``None``."""
    vl = VenvLocator(project_bare)
    assert vl._project is project_bare
    assert vl._location is None
    assert vl._download_location is None
    assert vl._proper_names_db_path is None


@pytest.mark.utils
def test_project_venv_locator_returns_venv_locator_subsystem(project_bare):
    """``project.venv_locator`` returns a ``VenvLocator`` subsystem
    instance, cached for the project lifetime via ``@cached_property``."""
    assert isinstance(project_bare.venv_locator, VenvLocator)
    # Cached: two accesses return the same instance.
    assert project_bare.venv_locator is project_bare.venv_locator


@pytest.mark.utils
def test_is_venv_in_project_env_var_true_overrides_pipfile(tmp_path, monkeypatch):
    """``PIPENV_VENV_IN_PROJECT=1`` env var beats Pipfile ``false``."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_VENV_IN_PROJECT_FALSE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PIPENV_VENV_IN_PROJECT", "1")
    project = Project(chdir=False)
    assert project.venv_locator.is_venv_in_project() is True


@pytest.mark.utils
def test_is_venv_in_project_env_var_false_overrides_pipfile(tmp_path, monkeypatch):
    """``PIPENV_VENV_IN_PROJECT=0`` env var beats Pipfile ``true``."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_VENV_IN_PROJECT_TRUE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PIPENV_VENV_IN_PROJECT", "0")
    project = Project(chdir=False)
    assert project.venv_locator.is_venv_in_project() is False


@pytest.mark.utils
def test_is_venv_in_project_reads_pipfile_when_env_unset(tmp_path, monkeypatch):
    """With env var unset, the Pipfile ``[pipenv]`` setting controls
    ``is_venv_in_project``."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_VENV_IN_PROJECT_TRUE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_VENV_IN_PROJECT", raising=False)
    project = Project(chdir=False)
    assert project.venv_locator._pipfile_venv_in_project() is True
    assert project.venv_locator.is_venv_in_project() is True


@pytest.mark.utils
def test_is_venv_in_project_autodetects_dot_venv_directory(project_bare, tmp_path):
    """With no Pipfile setting and no env var, the presence of a ``.venv``
    directory makes ``is_venv_in_project`` return True."""
    # Make sure .venv exists as a directory.
    (tmp_path / ".venv").mkdir()
    assert project_bare.venv_locator.is_venv_in_project() is True


@pytest.mark.utils
def test_is_venv_in_project_default_false_without_dot_venv(project_bare):
    """No env var, no Pipfile setting, no ``.venv`` directory ⇒ False."""
    assert project_bare.venv_locator.is_venv_in_project() is False


@pytest.mark.utils
def test_pipfile_venv_in_project_returns_none_when_not_set(project_bare):
    """``_pipfile_venv_in_project`` returns ``None`` (not False) when the
    ``[pipenv] venv_in_project`` key is absent from the Pipfile."""
    assert project_bare.venv_locator._pipfile_venv_in_project() is None


@pytest.mark.utils
def test_location_honours_virtual_env_env_var(project_bare, monkeypatch):
    """If ``VIRTUAL_ENV`` is set and ``PIPENV_ACTIVE`` isn't and the
    ``PIPENV_IGNORE_VIRTUALENVS`` setting is unset, the location is taken
    directly from the ``VIRTUAL_ENV`` env var."""
    monkeypatch.setenv("VIRTUAL_ENV", "/some/external/venv")
    monkeypatch.delenv("PIPENV_ACTIVE", raising=False)
    assert project_bare.venv_locator.location == Path("/some/external/venv")


@pytest.mark.utils
def test_location_caches_after_first_access(tmp_path, monkeypatch):
    """The resolved location is cached on the ``VenvLocator`` instance
    after first access."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_VENV_IN_PROJECT_TRUE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("PIPENV_ACTIVE", raising=False)
    project = Project(chdir=False)
    first = project.venv_locator.location
    # Cache populated.
    assert project.venv_locator._location == first
    second = project.venv_locator.location
    assert first == second


@pytest.mark.utils
def test_src_location_is_created_on_access(tmp_path, monkeypatch):
    """``venv_locator.src_location`` creates the ``<venv>/src`` directory
    on access."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_VENV_IN_PROJECT_TRUE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("PIPENV_ACTIVE", raising=False)
    project = Project(chdir=False)
    src = project.venv_locator.src_location
    assert src.is_dir()
    assert src.name == "src"


@pytest.mark.utils
def test_download_location_is_created_on_access(tmp_path, monkeypatch):
    """``venv_locator.download_location`` creates the ``<venv>/downloads``
    directory on access and caches the path."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_VENV_IN_PROJECT_TRUE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("PIPENV_ACTIVE", raising=False)
    project = Project(chdir=False)
    dl = project.venv_locator.download_location
    assert dl.is_dir()
    assert dl.name == "downloads"
    # Cache populated.
    assert project.venv_locator._download_location == dl


@pytest.mark.utils
def test_proper_names_db_path_creates_file(tmp_path, monkeypatch):
    """``proper_names_db_path`` creates an empty ``pipenv-proper-names.txt``
    on first access."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_VENV_IN_PROJECT_TRUE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("PIPENV_ACTIVE", raising=False)
    project = Project(chdir=False)
    p = project.venv_locator.proper_names_db_path
    assert p.is_file()
    assert p.name == "pipenv-proper-names.txt"
    # Cache populated.
    assert project.venv_locator._proper_names_db_path == p


@pytest.mark.utils
def test_name_honours_custom_venv_name_setting(project_bare, monkeypatch):
    """``PIPENV_CUSTOM_VENV_NAME`` short-circuits the slug+hash logic and
    returns the custom name verbatim."""
    monkeypatch.setenv("PIPENV_CUSTOM_VENV_NAME", "my-handpicked-venv")
    # Re-build the Setting() inside project.s by recreating the project,
    # since Settings reads env at construction time.
    project = Project(chdir=False)
    assert project.venv_locator.name == "my-handpicked-venv"


@pytest.mark.utils
def test_name_includes_python_suffix_when_set(project_bare, monkeypatch):
    """When ``PIPENV_PYTHON`` is set, ``venv_locator.name`` appends a
    ``-<python-name>`` suffix to the slug+hash."""
    monkeypatch.delenv("PIPENV_CUSTOM_VENV_NAME", raising=False)
    monkeypatch.setenv("PIPENV_PYTHON", "3.13")
    project = Project(chdir=False)
    name = project.venv_locator.name
    assert name.endswith("-3.13"), name


@pytest.mark.utils
def test_which_falls_back_to_underscored_which_when_finders_empty(project_bare):
    """``venv_locator.which`` falls back to ``_which`` when the
    pythonfinder ``Finder`` list returns ``None`` for the search."""
    vl = project_bare.venv_locator
    with mock.patch.object(VenvLocator, "finders", new=[]):
        with mock.patch.object(vl, "_which", return_value=Path("/fake/python")) as m:
            result = vl.which("python")
            assert result == Path("/fake/python")
            m.assert_called_once_with("python")


@pytest.mark.utils
def test_underscored_which_raises_when_no_location_and_no_global(project_bare, monkeypatch):
    """``venv_locator._which`` raises ``RuntimeError`` when no venv exists,
    no ``VIRTUAL_ENV`` is set, and ``allow_global=False``."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    # Force exists=False so the fallback `location = os.environ.get('VIRTUAL_ENV')`
    # path is taken.
    with mock.patch.object(
        VenvLocator, "exists", new_callable=mock.PropertyMock, return_value=False
    ):
        with pytest.raises(RuntimeError, match="location not created"):
            project_bare.venv_locator._which("python")
