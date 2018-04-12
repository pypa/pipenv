import os

from pipenv.project import Project

import pytest


# This module is run only on Windows.
pytestmark = pytest.mark.skipif(os.name != 'nt', reason="only relevant on windows")


@pytest.mark.project
def test_case_changes_windows(PipenvInstance, pypi):
    """Test project matching for case changes on Windows.
    """
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        c = p.pipenv('install pytz')
        assert c.return_code == 0

        virtualenv_location = Project().virtualenv_location
        target = p.path.upper()
        if target == p.path:
            target = p.path.lower()
        os.chdir('..')
        os.chdir(target)
        assert os.path.abspath(os.curdir) != p.path

        venv = p.pipenv('--venv').out
        assert venv.strip().lower() == virtualenv_location.lower()
