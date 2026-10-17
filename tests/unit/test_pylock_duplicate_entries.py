import pytest

from pipenv.utils.pylock import PylockFile, PylockFormatError

PY310 = {"python_version": "3.10", "python_full_version": "3.10.20"}
PY312 = {"python_version": "3.12", "python_full_version": "3.12.4"}

NUMPY_OLD = """
[[packages]]
name = 'numpy'
version = '1.26.4'
marker = "python_version < '3.12'"
"""
NUMPY_NEW = """
[[packages]]
name = 'numpy'
version = '2.3.0'
marker = "python_version >= '3.12'"
"""


def _write_pylock(tmp_path, content):
    path = tmp_path / "pylock.toml"
    path.write_text("lock-version = '1.0'\ncreated-by = 'test-tool'\n" + content)
    return PylockFile.from_path(path)


@pytest.mark.parametrize("content", [NUMPY_OLD + NUMPY_NEW, NUMPY_NEW + NUMPY_OLD])
@pytest.mark.parametrize(
    "environment, version", [(PY310, "==1.26.4"), (PY312, "==2.3.0")]
)
def test_convert_picks_the_entry_matching_the_environment(
    tmp_path, content, environment, version
):
    pylock = _write_pylock(tmp_path, content)

    lockfile = pylock.convert_to_pipenv_lockfile(environment=environment)

    assert lockfile["default"]["numpy"]["version"] == version


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "environment, version", [(PY310, "==1.26.4"), (PY312, "==2.3.0")]
)
def test_environment_check_and_conversion_select_the_same_entry(
    tmp_path, reverse, environment, version
):
    entries = [
        NUMPY_OLD + "requires-python = '<3.12'\n",
        NUMPY_NEW + "requires-python = '>=3.12'\n",
    ]
    if reverse:
        entries.reverse()
    pylock = _write_pylock(tmp_path, "".join(entries))

    pylock.check_environment(environment=environment)
    lockfile = pylock.convert_to_pipenv_lockfile(environment=environment)

    assert lockfile["default"]["numpy"]["version"] == version


def test_convert_keeps_an_excluded_entry_when_none_matches(tmp_path):
    pylock = _write_pylock(
        tmp_path,
        NUMPY_OLD + NUMPY_OLD.replace("1.26.4", "1.26.3").replace("'3.12'", "'3.11'"),
    )

    lockfile = pylock.convert_to_pipenv_lockfile(environment=PY312)

    assert lockfile["default"]["numpy"]["version"] == "==1.26.4"
    assert lockfile["default"]["numpy"]["markers"] == "python_version < '3.12'"


def test_convert_rejects_entries_that_dont_narrow_to_one(tmp_path):
    pylock = _write_pylock(tmp_path, NUMPY_NEW + NUMPY_NEW.replace("2.3.0", "2.3.1"))

    with pytest.raises(PylockFormatError, match="'numpy' has 2 entries"):
        pylock.convert_to_pipenv_lockfile(environment=PY312)


def test_convert_keeps_the_order_of_first_entries(tmp_path):
    pylock = _write_pylock(
        tmp_path,
        NUMPY_OLD + "\n[[packages]]\nname = 'click'\nversion = '8.5.0'\n" + NUMPY_NEW,
    )

    lockfile = pylock.convert_to_pipenv_lockfile(environment=PY312)

    assert list(lockfile["default"]) == ["numpy", "click"]
