"""Markers that mention ``dependency_groups`` lose only the group conditions before pip sees them."""

import pytest

from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.utils.locking import Lockfile


def _normalized(marker):
    return str(Marker(marker)) if marker else marker


@pytest.mark.parametrize(
    "marker, expected",
    [
        # Written by pipenv itself (PylockFile.from_lockfile)
        ("'dev' in dependency_groups", None),
        ("('dev' in dependency_groups) and (python_version >= '3.10')", 'python_version >= "3.10"'),
        # Written by `pdm export -f pylock` and other tools
        ('sys_platform == "win32" and "dev" in dependency_groups', 'sys_platform == "win32"'),
        ('python_version < "3.11" and "dev" in dependency_groups', 'python_version < "3.11"'),
        ('"default" in dependency_groups', None),
        (
            'sys_platform == "linux" and ("default" in dependency_groups or "dev" in dependency_groups)',
            'sys_platform == "linux"',
        ),
        (
            "'dev' in dependency_groups and python_version >= '3.10' and sys_platform == 'linux'",
            'python_version >= "3.10" and sys_platform == "linux"',
        ),
        # No group condition: unchanged
        ("python_version < '3.11'", "python_version < '3.11'"),
    ],
)
def test_pip_marker_strips_only_dependency_group_conditions(marker, expected):
    assert _normalized(Lockfile._pip_marker(marker)) == _normalized(expected)
