import pytest

from pipenv.utils import pylock as pylock_module
from pipenv.utils.pylock import PylockFile, PylockVersionError

PACKAGE = """
[[packages]]
name = 'click'
version = '8.5.0'
"""


def _write(tmp_path, lock_version):
    path = tmp_path / "pylock.toml"
    path.write_text(f"lock-version = '{lock_version}'\ncreated-by = 'test-tool'\n{PACKAGE}")
    return path


def test_newer_minor_lock_version_loads_with_a_warning(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(pylock_module.err, "print", lambda message, **kwargs: warnings.append(message))

    path = _write(tmp_path, "1.1")
    pylock = PylockFile.from_path(path)
    PylockFile.from_path(path)

    assert pylock.lock_version == "1.1"
    assert [p["name"] for p in pylock.packages] == ["click"]
    assert len(warnings) == 1
    assert "lock-version 1.1" in warnings[0]


def test_supported_lock_version_loads_without_a_warning(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(pylock_module.err, "print", lambda message, **kwargs: warnings.append(message))

    PylockFile.from_path(_write(tmp_path, "1.0"))

    assert warnings == []


@pytest.mark.parametrize(
    "lock_version, message",
    [
        ("2.0", "Unsupported lock-version"),
        ("0.9", "Unsupported lock-version"),
        ("1", "Invalid lock-version"),
        ("one.0", "Invalid lock-version"),
    ],
)
def test_unsupported_or_invalid_lock_version_raises(tmp_path, lock_version, message):
    with pytest.raises(PylockVersionError, match=message):
        PylockFile.from_path(_write(tmp_path, lock_version))
