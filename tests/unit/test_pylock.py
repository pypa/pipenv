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


def test_from_lockfile(tmp_path):
    """Test creating a PylockFile from a Pipfile.lock file."""
    # Create a simple Pipfile.lock
    lockfile_content = """
{
    "_meta": {
        "hash": {
            "sha256": "b8c2e1580c53e383cfe4254c1f16560b855d984c674dc07bcce19a8b5b28c6b2"
        },
        "pipfile-spec": 6,
        "requires": {
            "python_version": "3.8"
        },
        "sources": [
            {
                "name": "pypi",
                "url": "https://pypi.org/simple",
                "verify_ssl": true
            }
        ]
    },
    "default": {
        "requests": {
            "hashes": [
                "sha256:b8aa58f8cf793ffd8782d3d8cb19e66ef36f7aba4353eec859e74678b01b07a7"
            ],
            "index": "pypi",
            "version": "==2.28.1"
        }
    },
    "develop": {
        "pytest": {
            "hashes": [
                "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
            ],
            "version": "==7.0.0"
        }
    }
}
"""
    lockfile_path = tmp_path / "Pipfile.lock"
    pylock_path = tmp_path / "pylock.toml"

    with open(lockfile_path, "w") as f:
        f.write(lockfile_content)

    # Create a PylockFile from the Pipfile.lock
    pylock = PylockFile.from_lockfile(lockfile_path, pylock_path)

    # Check basic properties
    assert pylock.lock_version == "1.0"
    assert pylock.created_by == "pipenv"
    assert pylock.requires_python == ">=3.8"

    # Check that packages were correctly converted
    package_names = [p["name"] for p in pylock.packages]
    assert "requests" in package_names
    assert "pytest" in package_names

    # Check that the tool.pipenv section exists
    assert "pipenv" in pylock.tool
    assert "generated_from" in pylock.tool["pipenv"]
    assert pylock.tool["pipenv"]["generated_from"] == "Pipfile.lock"


def test_write_method(tmp_path):
    """Test writing a PylockFile to disk."""
    # Create a simple PylockFile
    pylock_data = {
        "lock-version": "1.0",
        "environments": ["sys_platform == 'linux'"],
        "requires-python": ">=3.8",
        "extras": [],
        "dependency-groups": [],
        "default-groups": [],
        "created-by": "test",
        "packages": [
            {
                "name": "requests",
                "version": "2.28.1",
                "wheels": [
                    {
                        "name": "requests-2.28.1-py3-none-any.whl",
                        "hashes": {"sha256": "test-hash"}
                    }
                ]
            }
        ],
        "tool": {
            "pipenv": {
                "generated_from": "test"
            }
        }
    }

    pylock_path = tmp_path / "pylock.toml"
    pylock = PylockFile(path=pylock_path, data=pylock_data)

    # Write the file
    pylock.write()

    # Check that the file was created
    assert pylock_path.exists()

    # Load the file and check its contents
    loaded_pylock = PylockFile.from_path(pylock_path)

    # Check basic properties
    assert loaded_pylock.lock_version == "1.0"
    assert loaded_pylock.created_by == "test"
    assert loaded_pylock.requires_python == ">=3.8"

    # Check that packages were correctly written
    assert len(loaded_pylock.packages) == 1
    assert loaded_pylock.packages[0]["name"] == "requests"
    assert loaded_pylock.packages[0]["version"] == "2.28.1"

    # Check that the tool.pipenv section was correctly written
    assert "pipenv" in loaded_pylock.tool
    assert loaded_pylock.tool["pipenv"]["generated_from"] == "test"
