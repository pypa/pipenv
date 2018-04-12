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


@pytest.mark.dotvenv
@pytest.mark.install
@pytest.mark.complex
@pytest.mark.shell
@pytest.mark.windows
@pytest.mark.pew
@pytest.mark.skip('Not mocking this.')
def test_shell_nested_venv_in_project(PipenvInstance, pypi):
    import subprocess
    with temp_environ():
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_IGNORE_VIRTUALENVS'] = '1'
        with PipenvInstance(chdir=True, pypi=pypi) as p:
            # Signal to pew to look in the project directory for the environment
            os.environ['WORKON_HOME'] = p.path
            c = p.pipenv('install requests')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'requests' in p.lockfile['default']
            # Check that .venv now shows in pew's managed list
            pew_list = delegator.run('pewtwo ls')
            assert '.venv' in pew_list.out
            # Check for the venv directory
            c = delegator.run('pewtwo dir .venv')
            # Compare pew's virtualenv path to what we expect
            venv_path = get_windows_path(Project().project_directory, '.venv')
            # os.path.normpath will normalize slashes
            assert venv_path == normalize_drive(os.path.normpath(c.out.strip()))
            # Have pew run 'pip freeze' in the virtualenv
            # This is functionally the same as spawning a subshell
            # If we can do this we can theoretically make a subshell
            # This test doesn't work on *nix
            if os.name == 'nt':
                process = subprocess.Popen(
                    'pewtwo in .venv pip freeze',
                    shell=True,
                    universal_newlines=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                out, _ = process.communicate()
                assert any(req.startswith('requests') for req in out.splitlines()) is True
