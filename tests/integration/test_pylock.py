import os
import shutil
from pathlib import Path

import pytest

from pipenv.project import Project
from pipenv.utils.pylock import PylockFile, find_pylock_file


@pytest.fixture
def pylock_project(tmp_path):
    """Create a temporary project with a pylock.toml file."""
    # Copy the example pylock.toml to the temporary directory
    example_pylock = Path(__file__).parent.parent.parent / "examples" / "pylock.toml"
    tmp_pylock = tmp_path / "pylock.toml"

    # Create a simple Pipfile
    pipfile_content = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"

[dev-packages]

[requires]
python_version = "3.8"
"""

    with open(tmp_path / "Pipfile", "w") as f:
        f.write(pipfile_content)

    shutil.copy(example_pylock, tmp_pylock)

    # Change to the temporary directory
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def test_find_pylock_file(pylock_project):
    """Test that find_pylock_file correctly finds the pylock.toml file."""
    pylock_path = find_pylock_file(pylock_project)
    assert pylock_path is not None
    assert pylock_path.name == "pylock.toml"
    assert pylock_path.exists()


def test_pylock_file_loading(pylock_project):
    """Test loading a pylock.toml file."""
    pylock_path = pylock_project / "pylock.toml"
    pylock = PylockFile.from_path(pylock_path)

    assert pylock.lock_version == "1.0"
    assert pylock.created_by == "pipenv"
    assert pylock.requires_python == ">=3.8"
    assert len(pylock.packages) == 5
    assert pylock.packages[0]["name"] == "requests"
    assert pylock.packages[0]["version"] == "2.28.1"


def test_project_pylock_integration(pylock_project):
    """Test that Project class correctly detects and uses pylock.toml."""
    # Create a project instance
    project = Project(chdir=False)

    # Check that pylock.toml is detected
    assert project.pylock_exists
    assert project.pylock_location is not None
    assert Path(project.pylock_location).name == "pylock.toml"

    # Check that lockfile_content returns the converted pylock content
    lockfile_content = project.lockfile_content
    assert "_meta" in lockfile_content
    assert "default" in lockfile_content
    assert "requests" in lockfile_content["default"]
    assert "urllib3" in lockfile_content["default"]
    assert "certifi" in lockfile_content["default"]
    assert "charset-normalizer" in lockfile_content["default"]
    assert "idna" in lockfile_content["default"]

    # Check that the converted content has the correct format
    requests_entry = lockfile_content["default"]["requests"]
    assert requests_entry["version"] == "==2.28.1"
    assert "hashes" in requests_entry
    assert len(requests_entry["hashes"]) == 1
    assert requests_entry["hashes"][0].startswith("sha256:")


@pytest.fixture
def pylock_write_project(tmp_path):
    """Create a temporary project with a Pipfile that has use_pylock enabled."""
    # Create a simple Pipfile with use_pylock enabled
    pipfile_content = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"

[dev-packages]

[requires]
python_version = "3.8"

[pipenv]
use_pylock = true
"""

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
        "certifi": {
            "hashes": [
                "sha256:0d9c601124e5a6ba9712dbc60d9c53c21e34f5f641fe83002317394311bdce14"
            ],
            "version": "==2022.9.24"
        },
        "charset-normalizer": {
            "hashes": [
                "sha256:83e9a75d1911279afd89352c68b45348559d1fc0506b054b346651b5e7fee29f"
            ],
            "version": "==2.1.1"
        },
        "idna": {
            "hashes": [
                "sha256:90b77e79eaa3eba6de819a0c442c0b4ceefc341a7a2ab77d7562bf49f425c5c2"
            ],
            "version": "==3.4"
        },
        "requests": {
            "hashes": [
                "sha256:b8aa58f8cf793ffd8782d3d8cb19e66ef36f7aba4353eec859e74678b01b07a7"
            ],
            "index": "pypi",
            "version": "==2.28.1"
        },
        "urllib3": {
            "hashes": [
                "sha256:b930dd878d5a8afb066a637fbb35144fe7901e3b209d1cd4f524bd0e9deee997"
            ],
            "version": "==1.26.12"
        }
    },
    "develop": {}
}
"""

    with open(tmp_path / "Pipfile", "w") as f:
        f.write(pipfile_content)

    with open(tmp_path / "Pipfile.lock", "w") as f:
        f.write(lockfile_content)

    # Change to the temporary directory
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def test_write_pylock_file(pylock_write_project):
    """Test that Project class correctly writes pylock.toml files."""
    # Create a project instance
    project = Project(chdir=False)

    # Check that use_pylock is enabled
    assert project.use_pylock is True

    # Check that pylock_output_path is correct
    assert project.pylock_output_path == str(pylock_write_project / "pylock.toml")

    # Load the lockfile content
    lockfile_content = project.lockfile_content

    # Write the lockfile (which should also write pylock.toml)
    project.write_lockfile(lockfile_content)

    # Check that pylock.toml was created
    pylock_path = pylock_write_project / "pylock.toml"
    assert pylock_path.exists()

    # Load the pylock.toml file and verify its contents
    pylock = PylockFile.from_path(pylock_path)

    # Check basic properties
    assert pylock.lock_version == "1.0"
    assert pylock.created_by == "pipenv"

    # Check that all packages are included
    package_names = [p["name"] for p in pylock.packages]
    assert "requests" in package_names
    assert "urllib3" in package_names
    assert "certifi" in package_names
    assert "charset-normalizer" in package_names
    assert "idna" in package_names

    # Check that the tool.pipenv section exists
    assert "pipenv" in pylock.tool
    assert "generated_from" in pylock.tool["pipenv"]
    assert pylock.tool["pipenv"]["generated_from"] == "Pipfile.lock"


@pytest.fixture
def pylock_write_named_project(tmp_path):
    """Create a temporary project with a Pipfile that has use_pylock and pylock_name enabled."""
    # Create a simple Pipfile with use_pylock and pylock_name enabled
    pipfile_content = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"

[dev-packages]

[requires]
python_version = "3.8"

[pipenv]
use_pylock = true
pylock_name = "dev"
"""

    # Create a simple Pipfile.lock (same as in pylock_write_project)
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
        "certifi": {
            "hashes": [
                "sha256:0d9c601124e5a6ba9712dbc60d9c53c21e34f5f641fe83002317394311bdce14"
            ],
            "version": "==2022.9.24"
        },
        "charset-normalizer": {
            "hashes": [
                "sha256:83e9a75d1911279afd89352c68b45348559d1fc0506b054b346651b5e7fee29f"
            ],
            "version": "==2.1.1"
        },
        "idna": {
            "hashes": [
                "sha256:90b77e79eaa3eba6de819a0c442c0b4ceefc341a7a2ab77d7562bf49f425c5c2"
            ],
            "version": "==3.4"
        },
        "requests": {
            "hashes": [
                "sha256:b8aa58f8cf793ffd8782d3d8cb19e66ef36f7aba4353eec859e74678b01b07a7"
            ],
            "index": "pypi",
            "version": "==2.28.1"
        },
        "urllib3": {
            "hashes": [
                "sha256:b930dd878d5a8afb066a637fbb35144fe7901e3b209d1cd4f524bd0e9deee997"
            ],
            "version": "==1.26.12"
        }
    },
    "develop": {}
}
"""

    with open(tmp_path / "Pipfile", "w") as f:
        f.write(pipfile_content)

    with open(tmp_path / "Pipfile.lock", "w") as f:
        f.write(lockfile_content)

    # Change to the temporary directory
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def test_write_named_pylock_file(pylock_write_named_project):
    """Test that Project class correctly writes named pylock.toml files."""
    # Create a project instance
    project = Project(chdir=False)

    # Check that use_pylock is enabled
    assert project.use_pylock is True

    # Check that pylock_name is set
    assert project.settings.get("pylock_name") == "dev"

    # Check that pylock_output_path is correct
    assert project.pylock_output_path == str(pylock_write_named_project / "pylock.dev.toml")

    # Load the lockfile content
    lockfile_content = project.lockfile_content

    # Write the lockfile (which should also write pylock.dev.toml)
    project.write_lockfile(lockfile_content)

    # Check that pylock.dev.toml was created
    pylock_path = pylock_write_named_project / "pylock.dev.toml"
    assert pylock_path.exists()

    # Load the pylock.dev.toml file and verify its contents
    pylock = PylockFile.from_path(pylock_path)

    # Check basic properties
    assert pylock.lock_version == "1.0"
    assert pylock.created_by == "pipenv"

    # Check that all packages are included
    package_names = [p["name"] for p in pylock.packages]
    assert "requests" in package_names
    assert "urllib3" in package_names
    assert "certifi" in package_names
    assert "charset-normalizer" in package_names
    assert "idna" in package_names
