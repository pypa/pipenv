import os

from mock import patch, Mock, PropertyMock

import pytest
from pipenv.vendor import toml
from pipenv.vendor import delegator

from pipenv.cli import (
    activate_virtualenv, ensure_proper_casing, pip_install, pip_download
)
from pipenv.project import Project

# Tell pipenv to ignore activated virtualenvs.
os.environ['PIPENV_IGNORE_VIRTUALENVS'] = 'True'


class TestPipenv():

    @patch('pipenv.project.Project.sources', new_callable=PropertyMock)
    @patch('delegator.run')
    def test_pip_install_should_try_every_possible_source(self, mocked_delegator, mocked_sources):
        sources = [
            {'url': 'http://dontexistis.in.pypi/simple'},
            {'url': 'http://existis.in.pypi/simple'}
        ]
        mocked_sources.return_value = sources
        first_cmd_return = Mock()
        first_cmd_return.return_code = 1
        second_cmd_return = Mock()
        second_cmd_return.return_code = 0
        mocked_delegator.side_effect = [first_cmd_return, second_cmd_return]
        c = pip_install('package')
        assert c.return_code == 0

    @patch('pipenv.project.Project.sources', new_callable=PropertyMock)
    @patch('delegator.run')
    def test_pip_install_should_return_the_last_error_if_no_cmd_worked(self, mocked_delegator, mocked_sources):
        sources = [
            {'url': 'http://dontexistis.in.pypi/simple'},
            {'url': 'http://dontexistis.in.pypi/simple'}
        ]
        mocked_sources.return_value = sources
        first_cmd_return = Mock()
        first_cmd_return.return_code = 1
        second_cmd_return = Mock()
        second_cmd_return.return_code = 1
        mocked_delegator.side_effect = [first_cmd_return, second_cmd_return]
        c = pip_install('package')
        assert c.return_code == 1
        assert c == second_cmd_return

    @patch('pipenv.project.Project.sources', new_callable=PropertyMock)
    @patch('delegator.run')
    def test_pip_install_should_return_the_first_cmd_that_worked(self, mocked_delegator, mocked_sources):
        sources = [
            {'url': 'http://existis.in.pypi/simple'},
            {'url': 'http://existis.in.pypi/simple'}
        ]
        mocked_sources.return_value = sources
        first_cmd_return = Mock()
        first_cmd_return.return_code = 0
        second_cmd_return = Mock()
        second_cmd_return.return_code = 0
        mocked_delegator.side_effect = [first_cmd_return, second_cmd_return]
        c = pip_install('package')
        assert c.return_code == 0
        assert c == first_cmd_return

    @patch('pipenv.project.Project.sources', new_callable=PropertyMock)
    @patch('delegator.run')
    def test_pip_download_should_try_every_possible_source(self, mocked_delegator, mocked_sources):
        sources = [
            {'url': 'http://dontexistis.in.pypi/simple'},
            {'url': 'http://existis.in.pypi/simple'}
        ]
        mocked_sources.return_value = sources
        first_cmd_return = Mock()
        first_cmd_return.return_code = 1
        second_cmd_return = Mock()
        second_cmd_return.return_code = 0
        mocked_delegator.side_effect = [first_cmd_return, second_cmd_return]
        c = pip_download('package')
        assert c.return_code == 0

    @patch('pipenv.project.Project.sources', new_callable=PropertyMock)
    @patch('delegator.run')
    def test_pip_download_should_return_the_last_error_if_no_cmd_worked(self, mocked_delegator, mocked_sources):
        sources = [
            {'url': 'http://dontexistis.in.pypi/simple'},
            {'url': 'http://dontexistis.in.pypi/simple'}
        ]
        mocked_sources.return_value = sources
        first_cmd_return = Mock()
        first_cmd_return.return_code = 1
        second_cmd_return = Mock()
        second_cmd_return.return_code = 1
        mocked_delegator.side_effect = [first_cmd_return, second_cmd_return]
        c = pip_download('package')
        assert c.return_code == 1
        assert c == second_cmd_return

    @patch('pipenv.project.Project.sources', new_callable=PropertyMock)
    @patch('delegator.run')
    def test_pip_download_should_return_the_first_cmd_that_worked(self, mocked_delegator, mocked_sources):
        sources = [
            {'url': 'http://existis.in.pypi/simple'},
            {'url': 'http://existis.in.pypi/simple'}
        ]
        mocked_sources.return_value = sources
        first_cmd_return = Mock()
        first_cmd_return.return_code = 0
        second_cmd_return = Mock()
        second_cmd_return.return_code = 0
        mocked_delegator.side_effect = [first_cmd_return, second_cmd_return]
        c = pip_download('package')
        assert c.return_code == 0
        assert c == first_cmd_return

    def test_lock_requirements_file(self):
        delegator.run('mkdir test_pipenv_requirements')
        os.chdir('test_pipenv_requirements')

        pip_str = ("[packages]\n"
                   "requests = \"==2.14.0\"\n"
                   "flask = \"==0.12.2\"\n\n"
                   "[dev-packages]\n"
                   "pytest = \"==3.1.1\"\n")

        req_list = ("requests==2.14.0", "flask==0.12.2", "pytest==3.1.1")

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        assert delegator.run('echo \'{0}\' > Pipfile'.format(pip_str)).return_code == 0

        # Validate requirements.txt.
        c = delegator.run('pipenv lock -r')
        assert c.return_code == 0
        for req in req_list:
            assert req in c.out

        # Cleanup.
        os.chdir('..')
        delegator.run('rm -fr test_pipenv_requirements')
