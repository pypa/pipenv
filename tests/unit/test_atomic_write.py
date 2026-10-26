from pathlib import Path

import pytest

from pipenv.utils.locking import atomic_open_for_write
from pipenv.utils.pylock import PylockFile


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_atomic_write_replaces_target(tmp_path, binary, existing):
    target = tmp_path / "Pipfile.lock"
    if existing:
        target.write_bytes(b"old lock")

    with atomic_open_for_write(target, binary=binary) as stream:
        stream.write(b"new lock" if binary else "new lock")
        assert target.exists() is existing
        if existing:
            assert target.read_bytes() == b"old lock"

    assert target.read_bytes() == b"new lock"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("binary", [False, True])
def test_atomic_write_preserves_target_on_replace_error(tmp_path, monkeypatch, binary):
    target = tmp_path / "Pipfile.lock"
    target.write_bytes(b"old lock")

    def fail_replace(*args, **kwargs):
        raise PermissionError("cannot replace lock")

    monkeypatch.setattr(Path, "rename", fail_replace)
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError, match="cannot replace lock"):
        with atomic_open_for_write(target, binary=binary) as stream:
            stream.write(b"new lock" if binary else "new lock")

    assert target.exists()
    assert target.read_bytes() == b"old lock"


@pytest.mark.parametrize("binary", [False, True])
def test_atomic_write_preserves_target_on_write_error(tmp_path, binary):
    target = tmp_path / "Pipfile.lock"
    target.write_bytes(b"old lock")

    with pytest.raises(ValueError, match="cannot write lock"):
        with atomic_open_for_write(target, binary=binary) as stream:
            stream.write(b"new lock" if binary else "new lock")
            raise ValueError("cannot write lock")

    assert target.read_bytes() == b"old lock"
    assert list(tmp_path.iterdir()) == [target]


def test_pylock_write_preserves_target_on_replace_error(tmp_path, monkeypatch):
    target = tmp_path / "pylock.toml"
    original = b"lock-version = '1.0'\ncreated-by = 'original'\n"
    target.write_bytes(original)
    pylock = PylockFile(target, {"lock-version": "1.0", "created-by": "pipenv"})

    def fail_replace(*args, **kwargs):
        raise PermissionError("cannot replace lock")

    monkeypatch.setattr(Path, "rename", fail_replace)
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="cannot replace lock"):
        pylock.write()

    assert target.exists()
    assert target.read_bytes() == original
