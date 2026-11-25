"""``pipenv requirements --no-lock`` keeps every shorthand marker key."""

import pytest

from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.utils.dependencies import requirement_from_pipfile


@pytest.mark.parametrize(
    "key,value",
    [
        ("platform_machine", "== 'arm64'"),
        ("platform_system", "== 'Linux'"),
        ("python_version", ">= '3.10'"),
        ("os_name", "== 'nt'"),
    ],
)
def test_shorthand_marker_kept_without_lock(key, value):
    spec = {"version": "*", key: value}
    assert requirement_from_pipfile("pkg", spec) == f"pkg; {key} {value}"


def test_or_marker_is_grouped_before_combining_with_shorthand():
    spec = {
        "version": "==1.0",
        "markers": "sys_platform == 'linux' or sys_platform == 'darwin'",
        "platform_machine": "== 'arm64'",
    }
    assert requirement_from_pipfile("pkg", spec) == (
        "pkg==1.0; (sys_platform == 'linux' or sys_platform == 'darwin') "
        "and platform_machine == 'arm64'"
    )


@pytest.mark.parametrize("separator", [" or ", "\tor\t"])
def test_or_marker_does_not_bypass_shorthand_restriction(separator):
    explicit = separator.join(["sys_platform == 'linux'", "sys_platform == 'darwin'"])
    spec = {"version": "*", "markers": explicit, "platform_machine": "== 'arm64'"}
    marker = Marker(requirement_from_pipfile("pkg", spec).split(";", 1)[1].strip())
    env = {"sys_platform": "linux", "platform_machine": "x86_64"}
    assert not marker.evaluate(env)
    assert marker.evaluate({**env, "platform_machine": "arm64"})


def test_shorthand_marker_omitted_when_markers_excluded():
    spec = {"version": "*", "platform_machine": "== 'arm64'"}
    assert requirement_from_pipfile("pkg", spec, include_markers=False) == "pkg"
