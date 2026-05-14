"""Unit tests for the ``pipenv.utils.settings.Settings`` subsystem.

These tests pin the behaviour of the ``Settings`` subsystem that was
extracted from ``pipenv.project.Project`` in task T_D.3. They cover the
constructor, the ``@cached_property`` accessor on ``Project``, the
Mapping-protocol read shape that legacy callers depended on
(``.get(key, default)``, ``key in settings``, ``settings[key]``,
iteration), the writer (``Settings.update``), and the
``use_pylock`` accessor that was previously a property on ``Project``.
"""

from __future__ import annotations

import pytest

from pipenv.project import Project
from pipenv.utils.settings import Settings

PIPFILE_BARE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
"""

PIPFILE_WITH_PIPENV_SECTION = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[pipenv]
allow_prereleases = true
sort_pipfile = true
use_pylock = true

[packages]

[dev-packages]
"""


@pytest.fixture
def project_bare(tmp_path, monkeypatch):
    """Project pointing at a Pipfile with no ``[pipenv]`` section."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_BARE)
    monkeypatch.chdir(tmp_path)
    return Project(chdir=False)


@pytest.fixture
def project_with_settings(tmp_path, monkeypatch):
    """Project pointing at a Pipfile with a populated ``[pipenv]``
    section."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_WITH_PIPENV_SECTION)
    monkeypatch.chdir(tmp_path)
    return Project(chdir=False)


@pytest.mark.utils
def test_settings_constructor_takes_project(project_bare):
    """``Settings(project)`` accepts a ``Project`` reference."""
    settings = Settings(project_bare)
    assert settings is not None


@pytest.mark.utils
def test_project_settings_returns_settings_subsystem(project_bare):
    """``project.settings`` returns a ``Settings`` subsystem instance,
    cached for the project lifetime."""
    assert isinstance(project_bare.settings, Settings)
    # Cached: two accesses return the same instance.
    assert project_bare.settings is project_bare.settings


@pytest.mark.utils
def test_settings_get_returns_default_when_section_missing(project_bare):
    """``project.settings.get(key, default)`` returns the default when
    the ``[pipenv]`` section is missing entirely. This is the legacy
    call shape every external caller uses."""
    assert project_bare.settings.get("allow_prereleases", False) is False
    assert project_bare.settings.get("sort_pipfile", "no") == "no"
    assert project_bare.settings.get("missing-key") is None


@pytest.mark.utils
def test_settings_get_returns_value_when_present(project_with_settings):
    """``project.settings.get`` returns the configured value when the
    ``[pipenv]`` section has the requested key."""
    assert project_with_settings.settings.get("allow_prereleases") is True
    assert project_with_settings.settings.get("sort_pipfile") is True
    assert project_with_settings.settings.get("missing-key", "fallback") == "fallback"


@pytest.mark.utils
def test_settings_supports_mapping_protocol(project_with_settings):
    """``project.settings`` supports the Mapping protocol: ``in``,
    ``__getitem__``, iteration, ``len``."""
    settings = project_with_settings.settings
    assert "allow_prereleases" in settings
    assert "missing-key" not in settings
    assert settings["allow_prereleases"] is True
    keys = set(iter(settings))
    assert {"allow_prereleases", "sort_pipfile", "use_pylock"}.issubset(keys)
    assert len(settings) >= 3


@pytest.mark.utils
def test_settings_use_pylock_reads_pipfile(project_with_settings):
    """``project.settings.use_pylock`` exposes the ``use_pylock`` flag
    from the Pipfile."""
    assert project_with_settings.settings.use_pylock is True


@pytest.mark.utils
def test_settings_use_pylock_defaults_false(project_bare):
    """``Settings.use_pylock`` defaults to ``False`` when not set in the
    Pipfile."""
    assert project_bare.settings.use_pylock is False


@pytest.mark.utils
def test_settings_update_writes_new_keys(project_bare):
    """``project.settings.update({...})`` persists new keys into the
    Pipfile's ``[pipenv]`` section."""
    project_bare.settings.update({"allow_prereleases": True})
    # Force a fresh read of the Pipfile to confirm the write persisted.
    project_bare.pipfile._parsed_cache = None
    project_bare.pipfile._parsed_mtime_ns = None
    assert project_bare.settings.get("allow_prereleases") is True


@pytest.mark.utils
def test_settings_update_does_not_overwrite_existing(project_with_settings):
    """``Settings.update`` preserves the prior value when the key is
    already present in the ``[pipenv]`` section (matches the legacy
    ``update_settings`` semantics: only adds missing keys)."""
    project_with_settings.settings.update({"allow_prereleases": False})
    # Force a fresh read.
    project_with_settings.pipfile._parsed_cache = None
    project_with_settings.pipfile._parsed_mtime_ns = None
    # The pre-existing True value is preserved.
    assert project_with_settings.settings.get("allow_prereleases") is True


@pytest.mark.utils
def test_settings_update_noop_when_all_keys_present(project_with_settings, tmp_path):
    """``Settings.update`` is a no-op (no Pipfile rewrite) when every
    key already exists. We assert this by mtime: a no-op leaves the
    file's mtime unchanged."""
    pipfile = tmp_path / "Pipfile"
    mtime_before = pipfile.stat().st_mtime_ns
    project_with_settings.settings.update({"sort_pipfile": False})
    mtime_after = pipfile.stat().st_mtime_ns
    assert mtime_before == mtime_after


# ---------------------------------------------------------------------------
# T18 (Initiative G phase 2): [pipenv] prefetch_index_manifests
# ---------------------------------------------------------------------------

PIPFILE_WITH_PREFETCH = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[pipenv]
prefetch_index_manifests = true

[packages]

[dev-packages]
"""


@pytest.fixture
def project_with_prefetch(tmp_path, monkeypatch):
    """Project whose Pipfile enables ``prefetch_index_manifests``."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_WITH_PREFETCH)
    monkeypatch.chdir(tmp_path)
    return Project(chdir=False)


@pytest.mark.utils
def test_prefetch_index_manifests_defaults_false(project_bare, monkeypatch):
    """Acceptance #1: ``project.settings.get("prefetch_index_manifests",
    False)`` returns ``False`` by default — no Pipfile entry, no env-var
    override.
    """
    monkeypatch.delenv("PIPENV_PREFETCH_INDEX_MANIFESTS", raising=False)
    assert (
        project_bare.settings.get("prefetch_index_manifests", False) is False
    )


@pytest.mark.utils
def test_prefetch_index_manifests_reads_pipfile(project_with_prefetch, monkeypatch):
    """Acceptance #2: setting ``[pipenv] prefetch_index_manifests = true``
    in a Pipfile makes ``project.settings.get`` return ``True``."""
    monkeypatch.delenv("PIPENV_PREFETCH_INDEX_MANIFESTS", raising=False)
    assert (
        project_with_prefetch.settings.get("prefetch_index_manifests") is True
    )


@pytest.mark.utils
def test_prefetch_index_manifests_env_var_override(project_bare, monkeypatch):
    """Acceptance #3: ``PIPENV_PREFETCH_INDEX_MANIFESTS=1`` overrides the
    default and makes the read return ``True`` even when the Pipfile
    omits the key."""
    monkeypatch.setenv("PIPENV_PREFETCH_INDEX_MANIFESTS", "1")
    assert (
        project_bare.settings.get("prefetch_index_manifests", False) is True
    )


@pytest.mark.utils
def test_prefetch_index_manifests_env_var_falsy(project_with_prefetch, monkeypatch):
    """``PIPENV_PREFETCH_INDEX_MANIFESTS=0`` explicitly disables the
    feature even when the Pipfile enables it (env wins over Pipfile,
    matching the standard pipenv env-var-override convention)."""
    monkeypatch.setenv("PIPENV_PREFETCH_INDEX_MANIFESTS", "0")
    assert (
        project_with_prefetch.settings.get("prefetch_index_manifests") is False
    )
