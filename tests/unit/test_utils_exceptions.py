from pipenv.utils.exceptions import (
    LockfileCorruptException,
    PipfileCorruptException,
)
from pipenv.utils.locking import Lockfile


def test_lockfile_corrupt_exception_preserves_specific_message(capsys, tmp_path):
    path = tmp_path / "Pipfile.lock"
    backup_path = tmp_path / "Pipfile.lock.bak"

    error = LockfileCorruptException(path, backup_path=backup_path)
    error.show()

    assert "Failed to load lockfile" in error.message
    assert str(path) in error.message
    assert str(backup_path) in error.message
    assert error.message in capsys.readouterr().err


def test_pipfile_corrupt_exception_preserves_specific_message(capsys, tmp_path):
    path = tmp_path / "Pipfile"

    error = PipfileCorruptException(path)
    error.show()

    assert "Failed to load Pipfile" in error.message
    assert str(path) in error.message
    assert error.message in capsys.readouterr().err


def test_lockfile_load_returns_recovered_lockfile(capsys, tmp_path):
    pipfile_path = tmp_path / "Pipfile"
    lockfile_path = tmp_path / "Pipfile.lock"
    backup_path = tmp_path / "Pipfile.lock.bak"
    pipfile_path.write_text("[packages]\n")
    lockfile_path.write_text("{corrupted}")

    recovered = Lockfile.load(str(lockfile_path))

    assert recovered.path == lockfile_path
    assert backup_path.read_text() == "{corrupted}"
    assert "Your lockfile is corrupt" in capsys.readouterr().err
