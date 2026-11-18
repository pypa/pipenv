"""``pipenv requirements --no-lock`` keeps markers on VCS entries (as the lockfile path does)."""

import pytest

from pipenv.utils.dependencies import (
    requirement_from_lockfile,
    requirement_from_pipfile,
)

URL = "https://github.com/example/pkg.git"


@pytest.mark.parametrize("vcs", ["git", "hg"])
def test_vcs_marker_kept_without_lock(vcs):
    spec = {vcs: URL, "ref": "abc123", "markers": "sys_platform == 'linux'"}
    line = requirement_from_pipfile("pkg", spec)
    assert line == f"pkg @ {vcs}+{URL}@abc123 ; sys_platform == 'linux'"
    assert line == requirement_from_lockfile(
        "pkg", spec, include_hashes=False, include_markers=True
    )


def test_vcs_marker_omitted_when_markers_excluded():
    spec = {"git": URL, "ref": "abc123", "markers": "sys_platform == 'linux'"}
    assert requirement_from_pipfile("pkg", spec, include_markers=False) == f"pkg @ git+{URL}@abc123"


def test_vcs_without_markers_unchanged():
    assert requirement_from_pipfile("pkg", {"git": URL, "ref": "abc123"}) == f"pkg @ git+{URL}@abc123"


@pytest.mark.parametrize("key", ["path", "file"])
def test_path_sys_platform_kept_without_lock(key):
    spec = {key: "./w", "sys_platform": "== 'win32'"}
    assert requirement_from_pipfile("w", spec) == "./w ; sys_platform == 'win32'"


def test_path_markers_and_sys_platform_combined():
    spec = {"path": "./w", "markers": "python_version >= '3.9'", "sys_platform": "== 'win32'"}
    assert (
        requirement_from_pipfile("w", spec)
        == "./w ; python_version >= '3.9' and sys_platform == 'win32'"
    )


def test_path_marker_omitted_when_markers_excluded():
    spec = {"path": "./w", "sys_platform": "== 'win32'"}
    assert requirement_from_pipfile("w", spec, include_markers=False) == "./w"
