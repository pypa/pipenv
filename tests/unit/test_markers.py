import pytest

from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.utils.markers import (
    marker_from_specifier,
    merge_markers,
    normalize_marker_str,
)


def _evaluate(marker, python_version, python_full_version=None):
    return Marker(str(marker)).evaluate(
        {
            "python_version": python_version,
            "python_full_version": python_full_version or f"{python_version}.0",
        }
    )


@pytest.mark.utils
def test_requires_python_exclusions_do_not_use_string_containment():
    # colorama 0.4.6 Requires-Python (#6727)
    marker = marker_from_specifier(
        "!=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*, !=3.6.*, >=2.7"
    )
    marker_str = str(marker)
    assert " in " not in marker_str
    assert marker_str == (
        'python_version >= "2.7" and python_version != "3.0" and '
        'python_version != "3.1" and python_version != "3.2" and '
        'python_version != "3.3" and python_version != "3.4" and '
        'python_version != "3.5" and python_version != "3.6"'
    )
    assert _evaluate(marker, "2.7")
    assert not _evaluate(marker, "3.1")
    assert _evaluate(marker, "3.10")
    assert _evaluate(marker, "3.11")


@pytest.mark.utils
def test_requires_python_exclusions_sort_by_version():
    marker = marker_from_specifier("!=3.10.*, !=3.9.*, !=3.2.*, >=2.7")
    assert str(marker) == (
        'python_version >= "2.7" and python_version != "3.2" and '
        'python_version != "3.9" and python_version != "3.10"'
    )
    assert not _evaluate(marker, "3.10")
    assert _evaluate(marker, "3.1")


@pytest.mark.utils
def test_normalize_legacy_not_in_marker():
    marker_str = normalize_marker_str(
        "python_version not in '3.0, 3.1' and python_version >= '2.7'"
    )
    assert marker_str == (
        "python_version >= '2.7' and python_version != '3.0' and "
        "python_version != '3.1'"
    )
    assert not _evaluate(marker_str, "3.1")
    assert _evaluate(marker_str, "3.2")
    assert _evaluate(marker_str, "3.10")


@pytest.mark.utils
def test_normalize_multiple_equals_uses_or_group():
    marker_str = normalize_marker_str("python_version in '3.6, 3.7'")
    assert marker_str == "(python_version == '3.6' or python_version == '3.7')"
    assert _evaluate(marker_str, "3.7")
    assert not _evaluate(marker_str, "3.8")


@pytest.mark.utils
def test_normalize_multiple_equals_sorts_by_version():
    marker_str = normalize_marker_str("python_version in '3.10, 3.9'")
    assert marker_str == "(python_version == '3.9' or python_version == '3.10')"


@pytest.mark.utils
def test_merge_markers_keeps_individual_exclusions():
    merged = merge_markers(
        "python_version >= '3.7'",
        "python_version != '3.8' and sys_platform == 'linux'",
    )
    assert str(merged) == (
        'python_version >= "3.7" and python_version != "3.8" and '
        'sys_platform == "linux"'
    )
