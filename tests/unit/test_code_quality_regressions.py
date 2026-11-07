import pytest

from pipenv.exceptions import RequirementError, UninstallError
from pipenv.utils.locking import Lockfile


def test_requirement_error_without_req():
    error = RequirementError()
    assert "Failed creating requirement instance None" in error.message


def test_uninstall_error_formats_package_name():
    error = UninstallError("requests", "pip uninstall requests", "", 1)
    assert "requests!s" not in error.message
    assert "[bold yellow]requests[/bold yellow]" in error.message


def test_lockfile_from_data_missing_project_dir(tmp_path):
    missing = tmp_path / "does-not-exist" / "Pipfile.lock"
    with pytest.raises(FileNotFoundError, match="No project directory"):
        Lockfile.from_data(str(missing), {}, meta_from_project=False)
