import os
from unittest import mock

import pytest

from pipenv.project import Project

PIPFILE_CONTENT = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"

[dev-packages]

[requires]
python_version = "3.11"
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_CONTENT)
    monkeypatch.chdir(tmp_path)
    return Project(chdir=False)


@pytest.mark.utils
def test_parsed_pipfile_caches_between_accesses(project):
    with mock.patch.object(Project, "_parse_pipfile", wraps=project._parse_pipfile) as spy:
        first = project.parsed_pipfile
        second = project.parsed_pipfile
    assert first is second
    assert spy.call_count == 1


@pytest.mark.utils
def test_parsed_pipfile_reparses_when_file_changes(project, tmp_path):
    assert project.parsed_pipfile is not None  # prime cache

    pipfile = tmp_path / "Pipfile"
    updated = PIPFILE_CONTENT.replace('requests = "*"', 'flask = "*"')
    # Bump mtime deterministically so the cache invalidates even on filesystems
    # with coarse mtime resolution.
    stat = pipfile.stat()
    pipfile.write_text(updated)
    os.utime(pipfile, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    with mock.patch.object(Project, "_parse_pipfile", wraps=project._parse_pipfile) as spy:
        reparsed = project.parsed_pipfile
    assert spy.call_count == 1
    assert "flask" in reparsed.get("packages", {})


@pytest.mark.utils
def test_write_toml_invalidates_pipfile_cache(project):
    doc = project.parsed_pipfile
    doc["packages"]["newpkg"] = "*"
    project.write_toml(doc)

    with mock.patch.object(Project, "_parse_pipfile", wraps=project._parse_pipfile) as spy:
        reloaded = project.parsed_pipfile
    assert spy.call_count == 1
    assert "newpkg" in reloaded.get("packages", {})


@pytest.mark.utils
def test_rapid_sequential_writes_are_each_visible(project):
    """Back-to-back write_toml calls on the same mtime tick must still
    produce fresh reads on subsequent parsed_pipfile accesses."""
    for i in range(3):
        doc = project.parsed_pipfile
        doc["packages"][f"pkg_{i}"] = "*"
        project.write_toml(doc)
        refreshed = project.parsed_pipfile
        assert f"pkg_{i}" in refreshed.get("packages", {})


@pytest.mark.utils
def test_in_place_mutation_then_write_yields_persisted_state(project, tmp_path):
    """Mirrors the ensure_proper_casing / write_toml pattern where the cached
    document is mutated in place before being written back."""
    doc = project.parsed_pipfile
    doc["packages"]["Pre-Cased-Pkg"] = "*"
    # Mutating the cached doc before writing is the intended flow.
    project.write_toml(doc)

    on_disk = (tmp_path / "Pipfile").read_text()
    assert "Pre-Cased-Pkg" in on_disk

    reloaded = project.parsed_pipfile
    assert "Pre-Cased-Pkg" in reloaded.get("packages", {})


@pytest.mark.utils
def test_write_toml_to_other_path_does_not_invalidate_pipfile_cache(
    project, tmp_path
):
    """Writing a TOML blob to an unrelated path (e.g. an intermediate buffer)
    must not drop the Pipfile cache."""
    doc = project.parsed_pipfile
    other = tmp_path / "snapshot.toml"
    project.write_toml(doc, path=str(other))

    with mock.patch.object(Project, "_parse_pipfile", wraps=project._parse_pipfile) as spy:
        again = project.parsed_pipfile
    assert spy.call_count == 0
    assert again is doc
