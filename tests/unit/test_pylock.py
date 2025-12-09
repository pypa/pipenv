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
marker = "'dev' in dependency_groups or 'test' in dependency_groups"
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
    assert pylock.packages[1]["marker"] == "'dev' in dependency_groups or 'test' in dependency_groups"


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
    assert lockfile["develop"]["pytest"]["markers"] == "'dev' in dependency_groups or 'test' in dependency_groups"


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


def test_wildcard_version_handling(tmp_path):
    """Test that wildcard versions are handled correctly.

    When converting from Pipfile.lock to pylock.toml, wildcard versions should be skipped.
    When converting back, packages without versions should get wildcard version.
    """
    # Create a Pipfile.lock with a wildcard version
    lockfile_content = """
{
    "_meta": {
        "hash": {"sha256": "test"},
        "pipfile-spec": 6,
        "requires": {"python_version": "3.10"},
        "sources": []
    },
    "default": {
        "legacy-cgi": {
            "markers": "python_version >= '3.13'",
            "version": "*"
        },
        "requests": {
            "version": "==2.28.1"
        }
    },
    "develop": {}
}
"""
    lockfile_path = tmp_path / "Pipfile.lock"
    pylock_path = tmp_path / "pylock.toml"

    with open(lockfile_path, "w") as f:
        f.write(lockfile_content)

    # Create a PylockFile from the Pipfile.lock
    pylock = PylockFile.from_lockfile(lockfile_path, pylock_path)

    # Check that legacy-cgi has no version (wildcard was skipped)
    legacy_cgi_pkg = next((p for p in pylock.packages if p["name"] == "legacy-cgi"), None)
    assert legacy_cgi_pkg is not None
    assert "version" not in legacy_cgi_pkg  # Wildcard version should not be stored

    # Check that requests has a version
    requests_pkg = next((p for p in pylock.packages if p["name"] == "requests"), None)
    assert requests_pkg is not None
    assert requests_pkg["version"] == "2.28.1"

    # Now write and reload the pylock.toml
    pylock.write()
    loaded_pylock = PylockFile.from_path(pylock_path)

    # Convert back to Pipfile.lock format
    converted_lockfile = loaded_pylock.convert_to_pipenv_lockfile()

    # Check that legacy-cgi gets wildcard version back
    assert "legacy-cgi" in converted_lockfile["default"]
    assert converted_lockfile["default"]["legacy-cgi"]["version"] == "*"

    # Check that requests keeps its pinned version
    assert "requests" in converted_lockfile["default"]
    assert converted_lockfile["default"]["requests"]["version"] == "==2.28.1"


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


def test_get_packages_for_environment_marker_evaluation(tmp_path):
    """Test that get_packages_for_environment correctly evaluates markers.

    This test verifies that:
    - Packages without markers are always included
    - Packages with dependency_groups markers are filtered based on provided groups
    - Packages with extras markers are filtered based on provided extras

    Note: PEP 751 marker syntax uses 'value' in marker_variable, e.g.:
    - 'dev' in dependency_groups
    - 'crypto' in extras
    """
    # Create a pylock file with various markers using PEP 751 syntax
    pylock_content = """
lock-version = '1.0'
created-by = 'test-tool'

[[packages]]
name = 'requests'
version = '2.28.1'

[[packages]]
name = 'pytest'
version = '7.0.0'
marker = "'dev' in dependency_groups or 'test' in dependency_groups"

[[packages]]
name = 'sphinx'
version = '6.0.0'
marker = "'docs' in dependency_groups"

[[packages]]
name = 'cryptography'
version = '41.0.0'
marker = "'crypto' in extras"

[[packages]]
name = 'validators'
version = '0.22.0'
marker = "'validation' in extras"

[[packages]]
name = 'dev-only-tool'
version = '1.0.0'
marker = "'dev' in dependency_groups"
"""
    pylock_path = tmp_path / "pylock.toml"
    with open(pylock_path, "w") as f:
        f.write(pylock_content)

    pylock = PylockFile.from_path(pylock_path)

    # Test 1: No extras, no dependency_groups - only packages without markers
    packages = pylock.get_packages_for_environment(extras=set(), dependency_groups=set())
    package_names = [p["name"] for p in packages]
    assert "requests" in package_names
    assert "pytest" not in package_names
    assert "sphinx" not in package_names
    assert "cryptography" not in package_names
    assert "validators" not in package_names
    assert "dev-only-tool" not in package_names

    # Test 2: With 'dev' dependency_group
    packages = pylock.get_packages_for_environment(extras=set(), dependency_groups={"dev"})
    package_names = [p["name"] for p in packages]
    assert "requests" in package_names
    assert "pytest" in package_names  # 'dev' in dependency_groups evaluates to True
    assert "sphinx" not in package_names  # 'docs' not provided
    assert "dev-only-tool" in package_names  # 'dev' in dependency_groups evaluates to True
    assert "cryptography" not in package_names

    # Test 3: With 'docs' dependency_group
    packages = pylock.get_packages_for_environment(extras=set(), dependency_groups={"docs"})
    package_names = [p["name"] for p in packages]
    assert "requests" in package_names
    assert "pytest" not in package_names
    assert "sphinx" in package_names  # 'docs' in dependency_groups evaluates to True
    assert "dev-only-tool" not in package_names

    # Test 4: With 'crypto' extra
    packages = pylock.get_packages_for_environment(extras={"crypto"}, dependency_groups=set())
    package_names = [p["name"] for p in packages]
    assert "requests" in package_names
    assert "cryptography" in package_names  # 'crypto' in extras evaluates to True
    assert "validators" not in package_names  # 'validation' not provided
    assert "pytest" not in package_names

    # Test 5: With multiple dependency_groups and extras
    packages = pylock.get_packages_for_environment(
        extras={"crypto", "validation"},
        dependency_groups={"dev", "docs"}
    )
    package_names = [p["name"] for p in packages]
    assert "requests" in package_names
    assert "pytest" in package_names
    assert "sphinx" in package_names
    assert "cryptography" in package_names
    assert "validators" in package_names
    assert "dev-only-tool" in package_names


def test_from_lockfile_with_custom_dev_groups(tmp_path):
    """Test from_lockfile with custom dev_groups parameter."""
    lockfile_content = {
        "_meta": {
            "sources": [
                {"name": "pypi", "url": "https://pypi.org/simple/", "verify_ssl": True}
            ],
            "requires": {"python_version": "3.10"},
        },
        "default": {
            "requests": {"version": "==2.28.1", "hashes": ["sha256:abc123"]},
        },
        "develop": {
            "pytest": {"version": "==7.0.0", "hashes": ["sha256:def456"]},
        },
    }

    lockfile_path = tmp_path / "Pipfile.lock"
    import json
    with open(lockfile_path, "w") as f:
        json.dump(lockfile_content, f)

    # Test with custom dev groups
    pylock = PylockFile.from_lockfile(
        lockfile_path, dev_groups=["testing", "development"]
    )

    # Check that the dependency-groups includes our custom groups
    assert "testing" in pylock.dependency_groups
    assert "development" in pylock.dependency_groups

    # Check that the marker for develop packages uses the custom groups
    pytest_pkg = next(p for p in pylock.packages if p["name"] == "pytest")
    assert "'testing' in dependency_groups" in pytest_pkg["marker"]
    assert "'development' in dependency_groups" in pytest_pkg["marker"]


def test_from_lockfile_adds_package_index(tmp_path):
    """Test that from_lockfile adds packages.index field (PEP 751)."""
    lockfile_content = {
        "_meta": {
            "sources": [
                {"name": "pypi", "url": "https://pypi.org/simple/", "verify_ssl": True}
            ],
            "requires": {"python_version": "3.10"},
        },
        "default": {
            "requests": {"version": "==2.28.1", "hashes": ["sha256:abc123"]},
        },
        "develop": {},
    }

    lockfile_path = tmp_path / "Pipfile.lock"
    import json
    with open(lockfile_path, "w") as f:
        json.dump(lockfile_content, f)

    pylock = PylockFile.from_lockfile(lockfile_path)

    # Check that packages have index field
    requests_pkg = next(p for p in pylock.packages if p["name"] == "requests")
    assert "index" in requests_pkg
    assert requests_pkg["index"] == "https://pypi.org/simple/"


def test_from_pyproject(tmp_path):
    """Test creating a PylockFile from pyproject.toml."""
    pyproject_content = '''
[project]
name = "my-project"
version = "1.0.0"
requires-python = ">=3.9"
dependencies = [
    "requests>=2.28.0",
    "click>=8.0.0",
]

[project.optional-dependencies]
crypto = [
    "cryptography>=40.0.0",
]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
    "black>=23.0.0",
]
'''
    pyproject_path = tmp_path / "pyproject.toml"
    with open(pyproject_path, "w") as f:
        f.write(pyproject_content)

    pylock = PylockFile.from_pyproject(pyproject_path)

    # Check basic metadata
    assert pylock.lock_version == "1.0"
    assert pylock.created_by == "pipenv"
    assert pylock.requires_python == ">=3.9"

    # Check extras
    assert "crypto" in pylock.extras

    # Check dependency groups
    assert "dev" in pylock.dependency_groups

    # Check packages
    package_names = [p["name"] for p in pylock.packages]
    assert "requests" in package_names
    assert "click" in package_names
    assert "cryptography" in package_names
    assert "pytest" in package_names
    assert "black" in package_names

    # Check markers for extras
    crypto_pkg = next(p for p in pylock.packages if p["name"] == "cryptography")
    assert "'crypto' in extras" in crypto_pkg["marker"]

    # Check markers for dependency groups
    pytest_pkg = next(p for p in pylock.packages if p["name"] == "pytest")
    assert "'dev' in dependency_groups" in pytest_pkg["marker"]


def test_from_pyproject_missing_file(tmp_path):
    """Test from_pyproject raises error for missing file."""
    pyproject_path = tmp_path / "pyproject.toml"

    with pytest.raises(FileNotFoundError):
        PylockFile.from_pyproject(pyproject_path)
