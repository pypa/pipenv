"""``pipenv requirements`` keeps extras on file/path entries (lock and --no-lock)."""

import pytest

from pipenv.utils.dependencies import (
    requirement_from_lockfile,
    requirement_from_pipfile,
)


@pytest.mark.parametrize("key", ["path", "file"])
def test_local_path_extras_kept(key):
    spec = {key: "./pkg", "extras": ["a", "b"]}
    assert requirement_from_pipfile("pkg", spec) == "./pkg[a,b]"
    assert requirement_from_lockfile("pkg", spec) == "./pkg[a,b]"


@pytest.mark.parametrize("key", ["path", "file"])
def test_url_extras_use_direct_reference(key):
    url = "https://example.com/pkg-1.0-py3-none-any.whl"
    spec = {key: url, "extras": ["a"]}
    expected = f"pkg[a] @ {url}"
    assert requirement_from_pipfile("pkg", spec) == expected
    assert requirement_from_lockfile("pkg", spec) == expected


def test_local_path_without_extras_unchanged():
    assert requirement_from_pipfile("pkg", {"path": "./pkg"}) == "./pkg"
    assert requirement_from_lockfile("pkg", {"path": "./pkg"}) == "./pkg"
