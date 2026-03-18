from pipenv.patched.pip._vendor.packaging.version import Version
from pipenv.routines.outdated import _get_lockfile_entry_version


def test_get_lockfile_entry_version_uses_version_key():
    assert _get_lockfile_entry_version({"version": "==1.2.3"}) == Version("1.2.3")


def test_get_lockfile_entry_version_parses_wheel_file_path():
    lockfile_entry = {
        "file": "/tmp/wheels/ibm_db_sa_py3-0.3.1.post1-py3-none-any.whl"
    }
    assert _get_lockfile_entry_version(lockfile_entry) == Version("0.3.1.post1")


def test_get_lockfile_entry_version_parses_sdist_file_path():
    lockfile_entry = {"file": "/tmp/packages/ibm-db-sa-py3-0.3.1.post1.tar.gz"}
    assert _get_lockfile_entry_version(lockfile_entry) == Version("0.3.1.post1")


def test_get_lockfile_entry_version_returns_none_without_resolved_version():
    assert _get_lockfile_entry_version({"file": "/tmp/packages/local-package"}) is None
