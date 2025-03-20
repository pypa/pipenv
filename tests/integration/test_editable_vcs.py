import os
import shutil
from pathlib import Path

import pytest

from pipenv.utils.processes import subprocess_run


@pytest.mark.integration
@pytest.mark.install
@pytest.mark.editable
@pytest.mark.vcs
def test_editable_vcs_reinstall(pipenv_instance_private_pypi):
    """Test that editable VCS dependencies are reinstalled when the source checkout is missing."""
    with pipenv_instance_private_pypi() as p:
        # Create a Pipfile with an editable VCS dependency
        with open(p.pipfile_path, "w") as f:
            f.write("""
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
gunicorn = {git = "https://github.com/benoitc/gunicorn", ref = "23.0.0", editable = true}
            """.strip())

        # Install the dependency
        c = p.pipenv("install")
        assert c.returncode == 0, f"Failed to install: {c.stderr}"

        # Verify the src directory was created
        # The src directory could be in the project directory or in the virtualenv directory
        src_dir_project = Path(p.path) / "src"
        src_dir_venv = Path(p.virtualenv_location) / "src"
        
        # Check if either src directory exists
        src_dir = src_dir_project if src_dir_project.exists() else src_dir_venv
        assert src_dir.exists(), f"src directory was not created in either {src_dir_project} or {src_dir_venv}"
        assert any(src_dir.iterdir()), "src directory is empty"

        # Import the package to verify it's installed correctly
        c = p.pipenv("run python -c 'import gunicorn'")
        assert c.returncode == 0, f"Failed to import gunicorn: {c.stderr}"

        # Remove the src directory to simulate the issue
        shutil.rmtree(src_dir)
        assert not src_dir.exists(), "Failed to remove src directory"

        # Run pipenv install again to see if it reinstalls the dependency
        c = p.pipenv("install")
        assert c.returncode == 0, f"Failed to reinstall: {c.stderr}"

        # Verify the src directory was recreated
        # Check both possible locations again
        src_dir_project = Path(p.path) / "src"
        src_dir_venv = Path(p.virtualenv_location) / "src"
        
        # Check if either src directory exists
        src_dir = src_dir_project if src_dir_project.exists() else src_dir_venv
        assert src_dir.exists(), f"src directory was not recreated in either {src_dir_project} or {src_dir_venv}"
        assert any(src_dir.iterdir()), "recreated src directory is empty"

        # Import the package again to verify it's reinstalled correctly
        c = p.pipenv("run python -c 'import gunicorn'")
        assert c.returncode == 0, f"Failed to import gunicorn after reinstall: {c.stderr}"
