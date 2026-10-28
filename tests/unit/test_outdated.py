from types import SimpleNamespace
from unittest import mock

import pytest

from pipenv.patched.pip._vendor.packaging.version import Version
from pipenv.routines.outdated import _get_lockfile_entry_version, do_outdated


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


def test_skipped_update_message_names_the_required_version():
    project = mock.MagicMock()
    project.environment.get_installed_packages.return_value = [
        SimpleNamespace(name="requests", version="2.0.0")
    ]
    project.environment.get_outdated_packages.return_value = [
        SimpleNamespace(name="requests", version="2.0.0", latest_version="3.0.0")
    ]
    project.environment.reverse_dependencies.return_value = {
        "requests": {"required": ">=1.0,<3"}
    }
    project.pipfile.get_package_categories.return_value = ["default"]
    project.pipfile.get_package_name.return_value = "requests"
    project.pipfile.get_section.return_value = {"requests": "==2.0.0"}
    lockfile = {"default": {"requests": {"version": "==2.0.0"}}}

    with mock.patch(
        "pipenv.routines.outdated.do_lock", return_value=lockfile
    ), mock.patch("pipenv.routines.outdated.err") as err, mock.patch(
        "pipenv.routines.outdated.console"
    ):
        with pytest.raises(SystemExit):
            do_outdated(project)

    message = err.print.call_args.args[0]
    assert ">=1.0,<3 required" in message
    assert "{rdeps" not in message
