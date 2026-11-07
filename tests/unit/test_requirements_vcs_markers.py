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
