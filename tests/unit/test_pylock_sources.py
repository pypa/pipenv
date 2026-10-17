import json

import pytest

from pipenv.utils.pylock import PylockFile

LOCAL_ENTRIES = {
    "localpkg": {"path": "./localpkg"},
    "editablepkg": {"editable": True, "path": "./editablepkg"},
    "gitpkg": {
        "git": "https://github.com/example/gitpkg.git",
        "ref": "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a4f",
    },
    "archivepkg": {
        "file": "https://example.com/archivepkg-1.0.tar.gz",
        "hashes": ["sha256:" + "a" * 64],
    },
}


def _pylock_from_lockfile(tmp_path, default):
    lockfile_path = tmp_path / "Pipfile.lock"
    lockfile_path.write_text(
        json.dumps(
            {
                "_meta": {
                    "sources": [
                        {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
                    ],
                    "requires": {},
                },
                "default": default,
                "develop": {},
            }
        )
    )
    return PylockFile.from_lockfile(lockfile_path)


def _package(pylock, name):
    return next(package for package in pylock.packages if package["name"] == name)


def test_from_lockfile_keeps_local_and_vcs_sources(tmp_path):
    pylock = _pylock_from_lockfile(tmp_path, LOCAL_ENTRIES)

    assert _package(pylock, "localpkg")["directory"] == {"path": "./localpkg"}
    assert _package(pylock, "editablepkg")["directory"] == {
        "path": "./editablepkg",
        "editable": True,
    }
    assert _package(pylock, "gitpkg")["vcs"] == {
        "type": "git",
        "url": "https://github.com/example/gitpkg.git",
        "commit-id": "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a4f",
    }
    assert _package(pylock, "archivepkg")["archive"] == {
        "url": "https://example.com/archivepkg-1.0.tar.gz",
        "hashes": {"sha256": "a" * 64},
    }
    # These packages don't come from the index, so they get no index or wheels
    for name in LOCAL_ENTRIES:
        assert "index" not in _package(pylock, name)
        assert "wheels" not in _package(pylock, name)


@pytest.mark.parametrize("name", list(LOCAL_ENTRIES))
def test_local_and_vcs_sources_round_trip_to_pipfile_lock(tmp_path, name):
    pylock = _pylock_from_lockfile(tmp_path, {name: LOCAL_ENTRIES[name]})
    pylock.write()

    lockfile = PylockFile.from_path(pylock.path).convert_to_pipenv_lockfile()

    expected = {key: value for key, value in LOCAL_ENTRIES[name].items() if key != "hashes"}
    entry = lockfile["default"][name]
    assert {key: value for key, value in entry.items() if key != "hashes"} == expected
    assert "version" not in entry


def test_convert_directory_package_from_another_tool(tmp_path):
    path = tmp_path / "pylock.toml"
    path.write_text(
        "lock-version = '1.0'\n"
        "created-by = 'test-tool'\n"
        "[[packages]]\n"
        "name = 'localpkg'\n"
        "version = '0.1.0'\n"
        "directory = { path = 'localpkg', editable = false }\n"
    )

    lockfile = PylockFile.from_path(path).convert_to_pipenv_lockfile()

    # A bare relative path would be read as a package name, so it gets "./"
    assert lockfile["default"]["localpkg"] == {"path": "./localpkg"}
