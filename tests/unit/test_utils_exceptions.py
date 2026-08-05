from pipenv.utils.exceptions import (
    LockfileCorruptException,
    PipfileCorruptException,
)


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
