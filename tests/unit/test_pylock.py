import os
import tempfile
from pathlib import Path

import pytest

from pipenv.utils.pylock import PylockFile, PylockFormatError, PylockVersionError, find_pylock_file


@pytest.fixture
def valid_pylock_content():
    return """
lock-version = '1.0'
environments = ["sys_platform == 'win32'", "sys_platform == 'linux'"]
requires-python = '==3.12'
created-by = 'test-tool'

[[packages]]
name = 'requests'
version = '2.28.1'
requires-python = '>=3.7'

[[packages.wheels]]
name = 'requests-2.28.1-py3-none-any.whl'
upload-time = '2022-07-13T14:00:00Z'
url = 'https://files.pythonhosted.org/packages/example/requests-2.28.1-py3-none-any.whl'
size = 61000
hashes = {sha256 = 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'}

[[packages]]
name = 'pytest'
version = '7.0.0'
marker = "dependency_groups in ('dev', 'test')"
requires-python = '>=3.6'

[[packages.wheels]]
name = 'pytest-7.0.0-py3-none-any.whl'
upload-time = '2022-02-03T12:00:00Z'
url = 'https://files.pythonhosted.org/packages/example/pytest-7.0.0-py3-none-any.whl'
size = 45000
hashes = {sha256 = '1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef'}
"""


@pytest.fixture
def invalid_version_pylock_content():
    return """
lock-version = '2.0'
created-by = 'test-tool'

[[packages]]
name = 'requests'
version = '2.28.1'
"""


@pytest.fixture
def missing_version_pylock_content():
    return """
created-by = 'test-tool'

[[packages]]
name = 'requests'
version = '2.28.1'
"""


@pytest.fixture
def pylock_file(valid_pylock_content):
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.toml', delete=False) as f:
        f.write(valid_pylock_content)
        f.flush()
        path = f.name

    yield path

    # Clean up
    if os.path.exists(path):
        os.unlink(path)


def test_pylock_file_from_path(pylock_file):
    """Test loading a pylock file from a path."""
    pylock = PylockFile.from_path(pylock_file)

    assert pylock.lock_version == "1.0"
    assert pylock.created_by == "test-tool"
    assert pylock.requires_python == "==3.12"
    assert len(pylock.packages) == 2
    assert pylock.packages[0]["name"] == "requests"
    assert pylock.packages[0]["version"] == "2.28.1"
    assert pylock.packages[1]["name"] == "pytest"
    assert pylock.packages[1]["marker"] == "dependency_groups in ('dev', 'test')"


def test_pylock_file_invalid_version(invalid_version_pylock_content):
    """Test loading a pylock file with an invalid version."""
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.toml', delete=False) as f:
        f.write(invalid_version_pylock_content)
        f.flush()
        path = f.name

    try:
        with pytest.raises(PylockVersionError):
            PylockFile.from_path(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_pylock_file_missing_version(missing_version_pylock_content):
    """Test loading a pylock file with a missing version."""
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.toml', delete=False) as f:
        f.write(missing_version_pylock_content)
        f.flush()
        path = f.name

    try:
        with pytest.raises(PylockFormatError):
            PylockFile.from_path(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_find_pylock_file():
    """Test finding a pylock file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # No pylock file
        assert find_pylock_file(tmpdir) is None

        # Create pylock.toml
        pylock_path = os.path.join(tmpdir, "pylock.toml")
        with open(pylock_path, "w") as f:
            f.write("lock-version = '1.0'")

        assert find_pylock_file(tmpdir) == Path(pylock_path)

        # Create pylock.dev.toml
        os.unlink(pylock_path)  # Remove pylock.toml
        pylock_dev_path = os.path.join(tmpdir, "pylock.dev.toml")
        with open(pylock_dev_path, "w") as f:
            f.write("lock-version = '1.0'")

        assert find_pylock_file(tmpdir) == Path(pylock_dev_path)


def test_convert_to_pipenv_lockfile(pylock_file):
    """Test converting a pylock file to a Pipfile.lock format."""
    pylock = PylockFile.from_path(pylock_file)
    lockfile = pylock.convert_to_pipenv_lockfile()

    # Check structure
    assert "_meta" in lockfile
    assert "default" in lockfile
    assert "develop" in lockfile

    # Check packages
    assert "requests" in lockfile["default"]
    assert "pytest" in lockfile["develop"]

    # Check package details
    assert lockfile["default"]["requests"]["version"] == "==2.28.1"
    assert "hashes" in lockfile["default"]["requests"]
    assert lockfile["develop"]["pytest"]["version"] == "==7.0.0"
    assert lockfile["develop"]["pytest"]["markers"] == "dependency_groups in ('dev', 'test')"
