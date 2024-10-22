import os
import sys
from pathlib import Path

import pytest

from pipenv.utils.processes import subprocess_run

# This module is run only on Windows.
pytestmark = pytest.mark.skipif(os.name != "nt", reason="only relevant on windows")


@pytest.mark.project
def test_case_changes_windows(pipenv_instance_pypi):
    """Test project matching for case changes on Windows."""
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install pytz")
        assert c.returncode == 0

        # Canonical venv location.
        c = p.pipenv("--venv")
        assert c.returncode == 0
        virtualenv_location = c.stdout.strip()

        # Dance around to change the casing of the project directory.
        target = p.path.upper()
        if target == p.path:
            target = p.path.lower()
        os.chdir("..")
        os.chdir(target)
        assert os.path.abspath(os.curdir) != p.path

        # Ensure the incorrectly-cased project can find the correct venv.
        c = p.pipenv("--venv")
        assert c.returncode == 0
        assert c.stdout.strip().lower() == virtualenv_location.lower()


@pytest.mark.files
@pytest.mark.local
def test_local_path_windows(pipenv_instance_pypi):
    whl = Path(__file__).parent.parent.joinpath(
        "pypi", "six", "six-1.11.0-py2.py3-none-any.whl"
    )
    try:
        whl = whl.resolve()
    except OSError:
        whl = whl.absolute()
    with pipenv_instance_pypi() as p:
        c = p.pipenv(f'install "{whl}" -v')
        assert c.returncode == 0


@pytest.mark.local
@pytest.mark.files
def test_local_path_windows_forward_slash(pipenv_instance_pypi):
    whl = Path(__file__).parent.parent.joinpath(
        "pypi", "six", "six-1.11.0-py2.py3-none-any.whl"
    )
    try:
        whl = whl.resolve()
    except OSError:
        whl = whl.absolute()
    with pipenv_instance_pypi() as p:
        c = p.pipenv(f'install "{whl.as_posix()}" -v')
        assert c.returncode == 0


@pytest.mark.skipif(
    os.name == "nt" and sys.version_info[:2] == (3, 8),
    reason="Seems to work on 3.8 but not via the CI",
)
@pytest.mark.cli
def test_pipenv_clean_windows(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install dataclasses-json")
        assert c.returncode == 0
        c = p.pipenv(f"run pip install -i {p.index_url} click")
        assert c.returncode == 0

        c = p.pipenv("clean --dry-run")
        assert c.returncode == 0
        assert "click" in c.stdout.strip()


@pytest.mark.cli
def test_pipenv_run_with_special_chars_windows(pipenv_instance_pypi):
    with pipenv_instance_pypi():
        c = subprocess_run(["pipenv", "run", "echo", "[3-1]"])
        assert c.returncode == 0, c.stderr
