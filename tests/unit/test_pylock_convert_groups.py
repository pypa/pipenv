"""Converting a pylock.toml back to Pipfile.lock keeps dev groups and the Python requirement."""

import pytest

from pipenv.utils.pylock import PylockFile


def _convert(tmp_path, content, environment=None):
    path = tmp_path / "pylock.toml"
    path.write_text(content)
    return PylockFile.from_path(path).convert_to_pipenv_lockfile(environment)


PYLOCK = """
lock-version = '1.0'
requires-python = '{requires}'
created-by = 'pipenv'
dependency-groups = ['lint']
default-groups = ['default']

[[packages]]
name = 'requests'
version = '2.28.1'

[[packages]]
name = 'ruff'
version = '0.5.0'
marker = "'lint' in dependency_groups"
"""


def test_packages_of_a_custom_dev_group_go_to_develop(tmp_path):
    lockfile = _convert(tmp_path, PYLOCK.format(requires=">=3.12"))

    assert "requests" in lockfile["default"]
    assert "ruff" in lockfile["develop"]
    assert "ruff" not in lockfile["default"]


@pytest.mark.parametrize(
    "requires, expected",
    [
        (">=3.12", {"python_version": "3.12"}),
        (">=3.9", {"python_version": "3.9"}),
        ("==3.12.1", {"python_full_version": "3.12.1"}),
    ],
)
def test_requires_python_becomes_pipfile_lock_requires(tmp_path, requires, expected):
    lockfile = _convert(tmp_path, PYLOCK.format(requires=requires))

    assert lockfile["_meta"]["requires"] == expected


def test_complex_requires_python_is_kept_as_is(tmp_path):
    lockfile = _convert(tmp_path, PYLOCK.format(requires=">=3.9,<3.13"))

    assert lockfile["_meta"]["requires"] == {"python_version": ">=3.9,<3.13"}


SHARED_PYLOCK = """
lock-version = '1.0'
requires-python = '>=3.9'
created-by = 'pipenv'
dependency-groups = ['lint']
default-groups = ['default']

[[packages]]
name = 'tomli'
version = '2.0.1'
marker = "(python_version < '3.11') or ('lint' in dependency_groups)"
"""


def test_shared_package_with_a_narrower_default_marker_stays_in_default(tmp_path):
    lockfile = _convert(tmp_path, SHARED_PYLOCK, {"python_version": "3.10"})

    # It installs without the lint group on 3.10, so production needs it
    assert "tomli" in lockfile["default"]
    assert "tomli" in lockfile["develop"]


def test_shared_package_only_the_lint_group_installs_goes_to_develop(tmp_path):
    lockfile = _convert(tmp_path, SHARED_PYLOCK, {"python_version": "3.12"})

    assert "tomli" not in lockfile["default"]
    assert "tomli" in lockfile["develop"]


def test_package_excluded_by_the_environment_keeps_its_group_section(tmp_path):
    content = SHARED_PYLOCK.replace(
        "(python_version < '3.11') or ('lint' in dependency_groups)",
        "python_version < '3.8'",
    )
    lockfile = _convert(tmp_path, content, {"python_version": "3.12"})

    assert "tomli" in lockfile["default"]
    assert "tomli" not in lockfile["develop"]
