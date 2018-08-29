import os

import pytest
import mock

from pipenv._compat import TemporaryDirectory
from pipenv.core import warn_in_virtualenv, load_dot_env
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
def test_load_dot_env_from_environment_variable_location(capsys):
    with temp_environ(), TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
        dotenv_path = os.path.join(tempdir.name, 'test.env')
        key, val = 'SOME_KEY', 'some_value'
        with open(dotenv_path, 'w') as f:
            f.write('{}={}'.format(key, val))

        with mock.patch('pipenv.environments.PIPENV_DOTENV_LOCATION', dotenv_path):
            load_dot_env()
        assert os.environ[key] == val


@pytest.mark.core
def test_doesnt_load_dot_env_if_disabled(capsys):
    with temp_environ(), TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
        dotenv_path = os.path.join(tempdir.name, 'test.env')
        key, val = 'SOME_KEY', 'some_value'
        with open(dotenv_path, 'w') as f:
            f.write('{}={}'.format(key, val))

        with mock.patch('pipenv.environments.PIPENV_DOTENV_LOCATION', dotenv_path):
            with mock.patch('pipenv.environments.PIPENV_DONT_LOAD_ENV', '1'):
                load_dot_env()
            assert key not in os.environ

            load_dot_env()
            assert key in os.environ


@pytest.mark.core
def test_load_dot_env_warns_if_file_doesnt_exist(capsys):
    with temp_environ(), TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
        dotenv_path = os.path.join(tempdir.name, 'does-not-exist.env')
        with mock.patch('pipenv.environments.PIPENV_DOTENV_LOCATION', dotenv_path):
            load_dot_env()
        output, err = capsys.readouterr()
        assert 'Warning' in err
