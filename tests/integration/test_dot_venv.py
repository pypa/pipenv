# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from pipenv.utils.constants import FALSE_VALUES, TRUE_VALUES
from pipenv.utils.shell import normalize_drive, temp_environ


@pytest.mark.dotvenv
@pytest.mark.parametrize("true_value", TRUE_VALUES)
def test_venv_in_project(true_value, PipenvInstance):
    with temp_environ():
        os.environ['PIPENV_VENV_IN_PROJECT'] = true_value
        with PipenvInstance() as p:
            c = p.pipenv('install dataclasses-json')
            assert c.returncode == 0
            assert normalize_drive(p.path) in p.pipenv('--venv').stdout


@pytest.mark.dotvenv
@pytest.mark.parametrize("false_value", FALSE_VALUES)
def test_venv_in_project_disabled_ignores_venv(false_value, PipenvInstance):
    venv_name = "my_project"
    with temp_environ():
        os.environ['PIPENV_VENV_IN_PROJECT'] = false_value
        with PipenvInstance() as p:
            file_path = os.path.join(p.path, '.venv')
            with open(file_path, 'w') as f:
                f.write(venv_name)

            with temp_environ(), TemporaryDirectory(
                prefix='pipenv-', suffix='temp_workon_home'
            ) as workon_home:
                os.environ['WORKON_HOME'] = workon_home
                c = p.pipenv('install dataclasses-json')
                assert c.returncode == 0
                c = p.pipenv('--venv')
                assert c.returncode == 0
                venv_loc = Path(c.stdout.strip()).absolute()
                assert venv_loc.exists()
                assert venv_loc.joinpath('.project').exists()
                venv_path = normalize_drive(venv_loc.as_posix())
                venv_expected_path = Path(workon_home).joinpath(venv_name).absolute().as_posix()
                assert venv_path == normalize_drive(venv_expected_path)


@pytest.mark.dotvenv
@pytest.mark.parametrize("true_value", TRUE_VALUES)
def test_venv_at_project_root(true_value, PipenvInstance):
    with temp_environ():
        with PipenvInstance(chdir=True) as p:
            os.environ['PIPENV_VENV_IN_PROJECT'] = true_value
            c = p.pipenv('install')
            assert c.returncode == 0
            assert normalize_drive(p.path) in p.pipenv('--venv').stdout
            del os.environ['PIPENV_VENV_IN_PROJECT']
            os.mkdir('subdir')
            os.chdir('subdir')
            # should still detect installed
            assert normalize_drive(p.path) in p.pipenv('--venv').stdout


@pytest.mark.dotvenv
def test_reuse_previous_venv(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        os.mkdir('.venv')
        c = p.pipenv('install dataclasses-json')
        assert c.returncode == 0
        assert normalize_drive(p.path) in p.pipenv('--venv').stdout


@pytest.mark.dotvenv
@pytest.mark.parametrize('venv_name', ('test-venv', os.path.join('foo', 'test-venv')))
def test_venv_file(venv_name, PipenvInstance):
    """Tests virtualenv creation when a .venv file exists at the project root
    and contains a venv name.
    """
    with PipenvInstance(chdir=True) as p:
        file_path = os.path.join(p.path, '.venv')
        with open(file_path, 'w') as f:
            f.write(venv_name)

        with temp_environ(), TemporaryDirectory(
            prefix='pipenv-', suffix='temp_workon_home'
        ) as workon_home:
            os.environ['WORKON_HOME'] = workon_home
            if 'PIPENV_VENV_IN_PROJECT' in os.environ:
                del os.environ['PIPENV_VENV_IN_PROJECT']

            c = p.pipenv('install')
            assert c.returncode == 0

            c = p.pipenv('--venv')
            assert c.returncode == 0
            venv_loc = Path(c.stdout.strip()).absolute()
            assert venv_loc.exists()
            assert venv_loc.joinpath('.project').exists()
            venv_path = normalize_drive(venv_loc.as_posix())
            if os.path.sep in venv_name:
                venv_expected_path = Path(p.path).joinpath(venv_name).absolute().as_posix()
            else:
                venv_expected_path = Path(workon_home).joinpath(venv_name).absolute().as_posix()
            assert venv_path == normalize_drive(venv_expected_path)


@pytest.mark.dotvenv
def test_empty_venv_file(PipenvInstance):
    """Tests virtualenv creation when an empty .venv file exists at the project root
    """
    with PipenvInstance(chdir=True) as p:
        file_path = os.path.join(p.path, '.venv')
        with open(file_path, 'w'):
            pass

        with temp_environ(), TemporaryDirectory(
            prefix='pipenv-', suffix='temp_workon_home'
        ) as workon_home:
            os.environ['WORKON_HOME'] = workon_home
            if 'PIPENV_VENV_IN_PROJECT' in os.environ:
                del os.environ['PIPENV_VENV_IN_PROJECT']

            c = p.pipenv('install')
            assert c.returncode == 0

            c = p.pipenv('--venv')
            assert c.returncode == 0
            venv_loc = Path(c.stdout.strip()).absolute()
            assert venv_loc.exists()
            assert venv_loc.joinpath('.project').exists()
            from pathlib import PurePosixPath
            venv_path = normalize_drive(venv_loc.as_posix())
            venv_path_parent = str(PurePosixPath(venv_path).parent)
            assert venv_path_parent == Path(workon_home).absolute().as_posix()


@pytest.mark.dotvenv
def test_venv_in_project_default_when_venv_exists(PipenvInstance):
    """Tests virtualenv creation when a .venv file exists at the project root.
    """
    with temp_environ(), PipenvInstance(chdir=True) as p:
        with TemporaryDirectory(
            prefix='pipenv-', suffix='-test_venv'
        ) as venv_path:
            if 'PIPENV_VENV_IN_PROJECT' in os.environ:
                del os.environ['PIPENV_VENV_IN_PROJECT']

            file_path = os.path.join(p.path, '.venv')
            with open(file_path, 'w') as f:
                f.write(venv_path)

            c = p.pipenv('install')
            assert c.returncode == 0
            c = p.pipenv('--venv')
            assert c.returncode == 0
            venv_loc = Path(c.stdout.strip())

            assert venv_loc.joinpath('.project').exists()
            assert venv_loc == Path(venv_path)


@pytest.mark.dotenv
def test_venv_name_accepts_custom_name_environment_variable(PipenvInstance):
    """Tests that virtualenv reads PIPENV_CUSTOM_VENV_NAME and accepts it as a name
    """
    with PipenvInstance(chdir=True, venv_in_project=False) as p:
        test_name = "sensible_custom_venv_name"
        with temp_environ():
            os.environ['PIPENV_CUSTOM_VENV_NAME'] = test_name
            c = p.pipenv('install')
            assert c.returncode == 0
            c = p.pipenv('--venv')
            assert c.returncode == 0
            venv_path = c.stdout.strip()
            assert test_name == Path(venv_path).parts[-1]
