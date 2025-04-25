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
