import os

import mock
import pytest

from pipenv._compat import TemporaryDirectory
from pipenv.core import load_dot_env, warn_in_virtualenv
from pipenv.utils import temp_environ


@mock.patch('pipenv.environments.PIPENV_VIRTUALENV', 'totallyrealenv')
@mock.patch('pipenv.environments.PIPENV_VERBOSITY', -1)
@pytest.mark.core
def test_suppress_nested_venv_warning(capsys):
    # Capture the stderr of warn_in_virtualenv to test for the presence of the
    # courtesy notice.
    warn_in_virtualenv()
    output, err = capsys.readouterr()
    assert 'Courtesy Notice' not in err


@pytest.mark.core
def test_load_dot_env_from_environment_variable_location(monkeypatch, capsys):
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
        if os.name == "nt":
            import click
            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir.name, 'test.env')
        key, val = 'SOME_KEY', 'some_value'
        with open(dotenv_path, 'w') as f:
            f.write('{}={}'.format(key, val))

        m.setenv("PIPENV_DOTENV_LOCATION", str(dotenv_path))
        m.setattr("pipenv.environments.PIPENV_DOTENV_LOCATION", str(dotenv_path))
        load_dot_env()
        assert os.environ[key] == val


@pytest.mark.core
def test_doesnt_load_dot_env_if_disabled(monkeypatch, capsys):
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
        if os.name == "nt":
            import click
            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir.name, 'test.env')
        key, val = 'SOME_KEY', 'some_value'
        with open(dotenv_path, 'w') as f:
            f.write('{}={}'.format(key, val))

        m.setenv("PIPENV_DOTENV_LOCATION", str(dotenv_path))
        m.setattr("pipenv.environments.PIPENV_DOTENV_LOCATION", str(dotenv_path))
        m.setattr("pipenv.environments.PIPENV_DONT_LOAD_ENV", True)
        load_dot_env()
        assert key not in os.environ
        m.setattr("pipenv.environments.PIPENV_DONT_LOAD_ENV", False)
        load_dot_env()
        assert key in os.environ


@pytest.mark.core
def test_load_dot_env_warns_if_file_doesnt_exist(monkeypatch, capsys):
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
        if os.name == "nt":
            import click
            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir.name, 'does-not-exist.env')
        m.setenv("PIPENV_DOTENV_LOCATION", str(dotenv_path))
        m.setattr("pipenv.environments.PIPENV_DOTENV_LOCATION", str(dotenv_path))
        load_dot_env()
        output, err = capsys.readouterr()
        assert 'Warning' in err
