import os

from pipenv.project import Project
from pipenv.utils import temp_environ, normalize_drive, get_windows_path
from pipenv.vendor import delegator

import pytest


@pytest.mark.dotvenv
def test_venv_in_project(PipenvInstance, pypi):
    with temp_environ():
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        with PipenvInstance(pypi=pypi) as p:
            c = p.pipenv('install requests')
            assert c.return_code == 0
            assert normalize_drive(p.path) in p.pipenv('--venv').out


@pytest.mark.dotvenv
def test_venv_at_project_root(PipenvInstance):
    with temp_environ():
        with PipenvInstance(chdir=True) as p:
            os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
            c = p.pipenv('install')
            assert c.return_code == 0
            assert normalize_drive(p.path) in p.pipenv('--venv').out
            del os.environ['PIPENV_VENV_IN_PROJECT']
            os.mkdir('subdir')
            os.chdir('subdir')
            # should still detect installed
            assert normalize_drive(p.path) in p.pipenv('--venv').out


@pytest.mark.dotvenv
def test_reuse_previous_venv(PipenvInstance, pypi):
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        os.mkdir('.venv')
        c = p.pipenv('install requests')
        assert c.return_code == 0
        assert normalize_drive(p.path) in p.pipenv('--venv').out
