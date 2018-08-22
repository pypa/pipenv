import os

from pipenv._compat import TemporaryDirectory, Path
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
@pytest.mark.parametrize('venv_name', ('test-venv', os.path.join('foo', 'test-venv')))
def test_venv_file(venv_name, PipenvInstance, pypi):
    """Tests virtualenv creation when a .venv file exists at the project root
    and contains a venv name.
    """
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        file_path = os.path.join(p.path, '.venv')
        with open(file_path, 'w') as f:
            f.write(venv_name)

        with temp_environ(), TemporaryDirectory(
            prefix='pipenv-', suffix='temp_workon_home'
        ) as workon_home:
            os.environ['WORKON_HOME'] = workon_home.name
            if 'PIPENV_VENV_IN_PROJECT' in os.environ:
                del os.environ['PIPENV_VENV_IN_PROJECT']

            c = p.pipenv('install')
            assert c.return_code == 0

            c = p.pipenv('--venv')
            assert c.return_code == 0
            venv_loc = Path(c.out.strip()).absolute()
            assert venv_loc.exists()
            assert venv_loc.joinpath('.project').exists()
            venv_path = venv_loc.as_posix()
            if os.path.sep in venv_name:
                venv_expected_path = Path(p.path).joinpath(venv_name).absolute().as_posix()
            else:
                venv_expected_path = Path(workon_home.name).joinpath(venv_name).absolute().as_posix()
            assert venv_path == venv_expected_path


@pytest.mark.dotvenv
def test_venv_file_with_path(PipenvInstance, pypi):
    """Tests virtualenv creation when a .venv file exists at the project root
    and contains an absolute path.
    """
    with temp_environ(), PipenvInstance(chdir=True, pypi=pypi) as p:
        with TemporaryDirectory(
            prefix='pipenv-', suffix='-test_venv'
        ) as venv_path:
            if 'PIPENV_VENV_IN_PROJECT' in os.environ:
                del os.environ['PIPENV_VENV_IN_PROJECT']

            file_path = os.path.join(p.path, '.venv')
            with open(file_path, 'w') as f:
                f.write(venv_path.name)

            c = p.pipenv('install')
            assert c.return_code == 0
            c = p.pipenv('--venv')
            assert c.return_code == 0
            venv_loc = Path(c.out.strip())

            assert venv_loc.joinpath('.project').exists()
            assert venv_loc == Path(venv_path.name)
