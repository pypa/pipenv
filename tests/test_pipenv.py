import os

from mock import patch, Mock, PropertyMock

import pytest
import delegator
import toml

from pipenv.cli import (activate_virtualenv, ensure_proper_casing,
    parse_download_fname, parse_install_output, pip_install, pip_download, which_pip)
from pipenv.project import Project


class TestPipenv():

    @pytest.mark.parametrize('fname, name, expected', [
        ('functools32-3.2.3-2.zip', 'functools32', '3.2.3-2'),
        ('functools32-3.2.3-blah.zip', 'functools32', '3.2.3-blah'),
        ('functools32-3.2.3.zip', 'functools32', '3.2.3'),
        ('colorama-0.3.7-py2.py3-none-any.whl', 'colorama', '0.3.7'),
        ('colorama-0.3.7-2-py2.py3-none-any.whl', 'colorama', '0.3.7-2'),
        ('click-completion-0.2.1.tar.gz', 'click-completion', '0.2.1'),
        ('Twisted-16.5.0.tar.bz2', 'Twisted', '16.5.0'),
        ('Twisted-16.1.1-cp27-none-win_amd64.whl', 'twIsteD', '16.1.1'),
        ('pdfminer.six-20140915.zip', 'pdfMiner.SIX', '20140915')
    ])
    def test_parse_download_fname(self, fname, name, expected):
        version = parse_download_fname(fname, name)
        assert version == expected

    def test_cli_usage(self):
        delegator.run('mkdir test_project')
        os.chdir('test_project')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'

        assert delegator.run('touch Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 0
        assert delegator.run('pipenv install requests').return_code == 0
        assert delegator.run('pipenv install pytest --dev').return_code == 0
        assert delegator.run('pipenv lock').return_code == 0

        assert 'pytest' in delegator.run('cat Pipfile').out
        assert 'pytest' in delegator.run('cat Pipfile.lock').out

        os.chdir('..')
        delegator.run('rm -fr test_project')

    def test_ensure_proper_casing_names(self):
        """Ensure proper casing for package names."""
        pfile_test = ("[packages]\n"
                      "DjAnGO = \"*\"\n"
                      "flask = \"==0.11\"\n"
                      "\n\n"
                      "[dev-packages]\n"
                      "PyTEST = \"*\"\n")

        # Load test Pipfile.
        p = toml.loads(pfile_test)

        assert 'DjAnGO' in p['packages']
        assert 'PyTEST' in p['dev-packages']

        changed = ensure_proper_casing(p)

        assert 'Django' in p['packages']
        assert 'DjAnGO' not in p['packages']

        assert 'pytest' in p['dev-packages']
        assert 'PyTEST' not in p['dev-packages']

        assert changed is True

    def test_ensure_proper_casing_no_change(self):
        """Ensure changed flag is false with no changes."""
        pfile_test = ("[packages]\n"
                      "Flask = \"==0.11\"\n"
                      "\n\n"
                      "[dev-packages]\n"
                      "pytest = \"*\"\n")

        # Load test Pipfile.
        p = toml.loads(pfile_test)
        changed = ensure_proper_casing(p)

        assert 'Flask' in p['packages']
        assert 'pytest' in p['dev-packages']
        assert changed is False

    def test_parse_install_output(self):
        """Ensure pip output is parsed properly."""
        install_output = ("Collecting requests\n"
                          "Using cached requests-2.13.0-py2.py3-none-any.whl\n"
                          "Successfully downloaded requests-2.13.0\n"
                          "Collecting honcho\n"
                          "Using cached honcho-0.7.1.tar.gz\n"
                          "Successfully downloaded honcho-0.7.1\n"
                          "Collecting foursquare\n"
                          "Downloading foursquare-1%212015.4.7.tar.gz\n"
                          "Saved ./foursquare-1%212015.4.7.tar.gz\n"
                          "Successfully downloaded foursquare\n"
                          "Collecting django-debug-toolbar\n"
                          "Using cached django_debug_toolbar-1.6-py2.py3-none-any.whl\n"
                          "Collecting sqlparse>=0.2.0 (from django-debug-toolbar)\n"
                          "Using cached sqlparse-0.2.2-py2.py3-none-any.whl\n")

        names_map = dict(parse_install_output(install_output))

        # Verify files are added to names map with appropriate project name.
        assert 'requests-2.13.0-py2.py3-none-any.whl' in names_map
        assert names_map['requests-2.13.0-py2.py3-none-any.whl'] == 'requests'

        # Verify percent-encoded characters are unencoded (%21 -> !).
        assert 'foursquare-1!2015.4.7.tar.gz' in names_map

        # Verify multiple dashes in name is parsed correctly.
        assert 'django_debug_toolbar-1.6-py2.py3-none-any.whl' in names_map
        assert names_map['django_debug_toolbar-1.6-py2.py3-none-any.whl'] == 'django-debug-toolbar'

    @pytest.mark.parametrize('shell, extension', [
        ('/bin/bash', ''),
        ('/bin/fish', '.fish'),
        ('/bin/csh', '.csh'),
        ('/bin/unknown', '')]
    )
    def test_activate_virtualenv(self, shell, extension):
        orig_shell = os.environ['SHELL']
        os.environ['SHELL'] = shell

        # Get standard activation command for bash
        command = activate_virtualenv()

        # Return environment to initial shell config.
        os.environ['SHELL'] = orig_shell

        venv = Project().virtualenv_location
        assert command == 'source {0}/bin/activate{1}'.format(venv, extension)

    def test_activate_virtualenv_no_source(self):
        command = activate_virtualenv(source=False)
        venv = Project().virtualenv_location

        assert command == '{0}/bin/activate'.format(venv)

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
