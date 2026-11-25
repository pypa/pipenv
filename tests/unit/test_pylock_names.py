import json

import pytest

from pipenv.patched.pip._vendor.packaging.pylock import Pylock
from pipenv.utils.pylock import PylockFile


def _from_lockfile(tmp_path, **categories):
    path = tmp_path / "Pipfile.lock"
    path.write_text(json.dumps({"_meta": {}, **categories}))
    return PylockFile.from_lockfile(path)


@pytest.mark.parametrize(
    "name, normalized",
    [("jaraco.classes", "jaraco-classes"), ("Zope__Interface", "zope-interface")],
)
def test_package_names_are_normalized(tmp_path, name, normalized):
    pylock = _from_lockfile(tmp_path, default={name: {"path": "./pkg"}})

    assert [package["name"] for package in pylock.packages] == [normalized]


def test_spellings_of_one_name_share_an_entry_across_categories(tmp_path):
    pylock = _from_lockfile(
        tmp_path,
        default={"jaraco.classes": {"path": "./pkg"}},
        develop={"jaraco-classes": {"path": "./pkg"}},
    )

    assert [package["name"] for package in pylock.packages] == ["jaraco-classes"]
    lockfile = pylock.convert_to_pipenv_lockfile()
    assert "jaraco-classes" in lockfile["default"]
    assert "jaraco-classes" in lockfile["develop"]
