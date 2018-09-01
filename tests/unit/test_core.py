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
def test_load_dot_env_local_from_environment_variable_location_overrides(capsys):
    key_one, key_two, key_three = 'KEY_ONE', 'KEY_TWO', 'KEY_THREE'

    with temp_environ(), TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
        dotenv_path = os.path.join(tempdir.name, 'test.env')
        environs = {
            key_one: 'value_one',
            key_two: 'value_two',
        }
        with open(dotenv_path, 'w') as f:
            f.write('\n'.join('{}={}'.format(k, v) for k, v in environs.items()))

        dotenv_local_path = os.path.join(tempdir.name, 'test.env.local')
        environs_local = {
            key_two: 'value_two_local',
            key_three: 'value_three_local',
        }
        with open(dotenv_local_path, 'w') as f:
            f.write('\n'.join('{}={}'.format(k, v) for k, v in environs_local.items()))

        dotenv_paths = os.pathsep.join([dotenv_local_path, dotenv_path])

        with mock.patch('pipenv.environments.PIPENV_DOTENV_LOCATION', dotenv_paths):
            load_dot_env()

        assert os.environ[key_one] == environs[key_one]
        assert os.environ[key_two] == environs_local[key_two]
        assert os.environ[key_three] == environs_local[key_three]


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
