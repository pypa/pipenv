"""Unit tests for the ``pipenv.utils.lockfile.Lockfile`` subsystem.

These tests pin the behaviour of the ``Lockfile`` subsystem that was
extracted from ``pipenv.project.Project`` in task T_D.5. They cover the
constructor, the ``@cached_property`` accessor on ``Project``, the
existence/location properties (``exists``, ``location``, ``any_exists``,
``pylock_exists``, ``pylock_location``, ``pylock_output_path``), the
content/meta/hash accessors (``content``, ``meta``, ``hash``,
``package_names``), the ``as_dict()`` shape (was ``Project.lockfile()``),
and the read/write methods (``load``, ``write``).

Per T_D.1 §8.1 maintainer sign-off pylock.toml support is NOT folded
into this extraction; the new ``Lockfile`` subsystem handles only the
legacy ``Pipfile.lock`` format. The pylock seams in ``content``,
``as_dict``, ``write`` and the ``any_exists`` / ``pylock_*`` accessors
are tagged ``# TODO(pylock):`` so they remain greppable for the 2027
follow-up.
"""

from __future__ import annotations

import json

import pytest

from pipenv.project import Project
from pipenv.utils.lockfile import Lockfile

PIPFILE_BARE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
"""

LOCKFILE_CONTENT = {
    "_meta": {
        "hash": {"sha256": "abc123"},
        "pipfile-spec": 6,
        "requires": {},
        "sources": [
            {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
        ],
    },
    "default": {
        "requests": {"version": "==2.28.1"},
    },
    "develop": {
        "pytest": {"version": "==7.0.0"},
    },
}


@pytest.fixture
def project_bare(tmp_path, monkeypatch):
    """Project with a Pipfile but no Pipfile.lock or pylock.toml."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_BARE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    return Project(chdir=False)


@pytest.fixture
def project_with_lock(tmp_path, monkeypatch):
    """Project with both a Pipfile and a Pipfile.lock."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_BARE)
    lockfile_path = tmp_path / "Pipfile.lock"
    lockfile_path.write_text(json.dumps(LOCKFILE_CONTENT))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    return Project(chdir=False)


@pytest.mark.utils
def test_lockfile_constructor_takes_project(project_bare):
    """``Lockfile(project)`` accepts a ``Project`` back-reference."""
    lf = Lockfile(project_bare)
    assert lf is not None
    assert lf._project is project_bare


@pytest.mark.utils
def test_project_lockfile_returns_lockfile_subsystem(project_bare):
    """``project.lockfile`` returns a ``Lockfile`` subsystem instance,
    cached for the project lifetime."""
    assert isinstance(project_bare.lockfile, Lockfile)
    # Cached: two accesses return the same instance.
    assert project_bare.lockfile is project_bare.lockfile


@pytest.mark.utils
def test_lockfile_location_is_pipfile_plus_lock(project_bare, tmp_path):
    """``project.lockfile.location`` is ``Pipfile.lock`` next to the Pipfile."""
    assert project_bare.lockfile.location == f"{tmp_path}/Pipfile.lock"


@pytest.mark.utils
def test_lockfile_exists_false_when_absent(project_bare):
    """``project.lockfile.exists`` is False when no Pipfile.lock exists."""
    assert project_bare.lockfile.exists is False


@pytest.mark.utils
def test_lockfile_exists_true_when_present(project_with_lock):
    """``project.lockfile.exists`` is True when Pipfile.lock exists."""
    assert project_with_lock.lockfile.exists is True


@pytest.mark.utils
def test_lockfile_any_exists_false_when_neither(project_bare):
    """``project.lockfile.any_exists`` is False when neither legacy lock
    nor pylock exists."""
    assert project_bare.lockfile.any_exists is False


@pytest.mark.utils
def test_lockfile_any_exists_true_with_pipfile_lock(project_with_lock):
    """``project.lockfile.any_exists`` is True when Pipfile.lock exists
    (even if pylock.toml is absent)."""
    assert project_with_lock.lockfile.any_exists is True
    assert project_with_lock.lockfile.pylock_exists is False


@pytest.mark.utils
def test_lockfile_pylock_location_none_when_absent(project_bare):
    """``project.lockfile.pylock_location`` is None when no pylock exists."""
    assert project_bare.lockfile.pylock_location is None
    assert project_bare.lockfile.pylock_exists is False


@pytest.mark.utils
def test_lockfile_pylock_output_path_default(project_bare, tmp_path):
    """``project.lockfile.pylock_output_path`` defaults to ``pylock.toml``
    in the project directory."""
    assert project_bare.lockfile.pylock_output_path == str(tmp_path / "pylock.toml")


@pytest.mark.utils
def test_lockfile_load_returns_dict_with_meta(project_with_lock):
    """``project.lockfile.load()`` returns the parsed lockfile dict."""
    loaded = project_with_lock.lockfile.load(expand_env_vars=False)
    assert "_meta" in loaded
    assert "default" in loaded
    assert loaded["_meta"]["hash"]["sha256"] == "abc123"


@pytest.mark.utils
def test_lockfile_content_returns_loaded_lockfile(project_with_lock):
    """``project.lockfile.content`` returns the loaded Pipfile.lock dict
    when neither pylock nor settings.use_pylock are active."""
    content = project_with_lock.lockfile.content
    assert "_meta" in content
    assert "default" in content
    assert "requests" in content["default"]


@pytest.mark.utils
def test_lockfile_hash_reads_meta_sha256(project_with_lock):
    """``project.lockfile.hash`` returns the ``_meta.hash.sha256`` field."""
    assert project_with_lock.lockfile.hash() == "abc123"


@pytest.mark.utils
def test_lockfile_hash_returns_none_when_absent(project_bare):
    """``project.lockfile.hash`` returns None when no lockfile exists."""
    assert project_bare.lockfile.hash() is None


@pytest.mark.utils
def test_lockfile_meta_includes_pipfile_hash(project_bare):
    """``project.lockfile.meta()`` includes the canonical Pipfile hash."""
    meta = project_bare.lockfile.meta()
    assert "hash" in meta
    assert "sha256" in meta["hash"]
    assert meta["hash"]["sha256"] == project_bare.calculate_pipfile_hash()
    assert "pipfile-spec" in meta
    assert "sources" in meta


@pytest.mark.utils
def test_lockfile_package_names_combined(project_with_lock):
    """``project.lockfile.package_names`` collects canonicalized names
    per category plus a ``combined`` aggregate."""
    names = project_with_lock.lockfile.package_names
    assert "combined" in names
    assert "default" in names
    assert "develop" in names
    assert "requests" in names["combined"]
    assert "pytest" in names["combined"]


@pytest.mark.utils
def test_lockfile_as_dict_returns_categories(project_with_lock):
    """``project.lockfile.as_dict()`` returns the lockfile data dict.

    Was ``project.lockfile(categories=...)`` before T_D.5.
    """
    data = project_with_lock.lockfile.as_dict()
    assert "default" in data
    assert "develop" in data
    assert "requests" in data["default"]


@pytest.mark.utils
def test_lockfile_write_persists_to_disk(project_bare, tmp_path):
    """``project.lockfile.write(content)`` writes a JSON Pipfile.lock to
    disk at the configured location."""
    content = {
        "_meta": {
            "hash": {"sha256": "deadbeef"},
            "pipfile-spec": 6,
            "requires": {},
            "sources": [],
        },
        "default": {},
        "develop": {},
    }
    project_bare.lockfile.write(content)
    lockfile_path = tmp_path / "Pipfile.lock"
    assert lockfile_path.exists()
    written = json.loads(lockfile_path.read_text())
    assert written["_meta"]["hash"]["sha256"] == "deadbeef"
