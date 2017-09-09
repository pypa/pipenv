import os
import shutil

from mock import patch, Mock, PropertyMock

import pytest
import delegator
import toml

from pipenv.cli import (ensure_proper_casing,
    parse_download_fname, parse_install_output, pip_install, pip_download)


class TestPipenvWindows():

    def test_existience(self):
        assert True

    @pytest.mark.parametrize('fname, name, expected', [
        ('functools32-3.2.3-2.zip', 'functools32', '3.2.3'),
        ('functools32-3.2.3-blah.zip', 'functools32', '3.2.3-blah'),
        ('functools32-3.2.3.zip', 'functools32', '3.2.3'),
        ('colorama-0.3.7-py2.py3-none-any.whl', 'colorama', '0.3.7'),
        ('colorama-0.3.7-2-py2.py3-none-any.whl', 'colorama', '0.3.7'),
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

        assert delegator.run('copy /y nul Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 0
        assert delegator.run('pipenv install Werkzeug').return_code == 0
        assert delegator.run('pipenv install pytest --dev').return_code == 0
        assert delegator.run('pipenv install git+https://github.com/requests/requests.git@v2.18.4#egg=requests').return_code == 0
        assert delegator.run('pipenv lock').return_code == 0

        # Test uninstalling a package after locking.
        assert delegator.run('pipenv uninstall Werkzeug').return_code == 0

        pipfile_output = delegator.run('type Pipfile').out
        lockfile_output = delegator.run('type Pipfile.lock').out

        # Ensure uninstall works.
        assert 'Werkzeug' not in pipfile_output
        assert 'werkzeug' not in lockfile_output

        # Ensure dev-packages work.
        assert 'pytest' in pipfile_output
        assert 'pytest' in lockfile_output

        # Ensure vcs dependencies work.
        assert 'requests' in pipfile_output
        assert '"git": "https://github.com/requests/requests.git"' in lockfile_output

        os.chdir('..')
        shutil.rmtree('test_project')

    def test_requirements_to_pipfile(self):
        delegator.run('mkdir test_requirements_to_pip')
        os.chdir('test_requirements_to_pip')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_MAX_DEPTH'] = '1'

        with open('requirements.txt', 'w') as f:
            f.write('requests[socks]==2.18.1\n'
                    'git+https://github.com/kennethreitz/records.git@v0.5.0#egg=records\n'
                    '-e git+https://github.com/kennethreitz/tablib.git@v0.11.5#egg=tablib\n'
                    'six==1.10.0\n')

        c = delegator.run('pipenv --python python')
        print(c.err)
        assert c.return_code == 0

        print(delegator.run('pipenv lock').err)
        assert delegator.run('pipenv lock').return_code == 0

        pipfile_output = delegator.run('type Pipfile').out
        lockfile_output = delegator.run('type Pipfile.lock').out

        # Ensure extras work.
        assert 'extras = [ "socks",]' in pipfile_output
        assert 'pysocks' in lockfile_output

        # Ensure vcs dependencies work.
        assert 'packages.records' in pipfile_output
        assert '"git": "https://github.com/kennethreitz/records.git"' in lockfile_output

        # Ensure editable packages work.
        assert 'ref = "v0.11.5"' in pipfile_output
        assert '"editable": true' in lockfile_output

        # Ensure BAD_PACKAGES aren't copied into Pipfile from requirements.txt.
        assert 'six = "==1.10.0"' not in pipfile_output

        os.chdir('..')
        shutil.rmtree('test_requirements_to_pip')
        del os.environ['PIPENV_MAX_DEPTH']

    def test_timeout_long(self):
        delegator.run('mkdir test_timeout_long')
        os.chdir('test_timeout_long')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_TIMEOUT'] = '60'

        assert delegator.run('copy /y nul Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 0

        os.chdir('..')
        shutil.rmtree('test_timeout_long')
        del os.environ['PIPENV_TIMEOUT']

    def test_timeout_short(self):
        delegator.run('mkdir test_timeout_short')
        os.chdir('test_timeout_short')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_TIMEOUT'] = '0'

        assert delegator.run('copy /y nul Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 1

        os.chdir('..')
        shutil.rmtree('test_timeout_short')
        del os.environ['PIPENV_TIMEOUT']

    def test_pipenv_uninstall(self):
        delegator.run('mkdir test_pipenv_uninstall')
        os.chdir('test_pipenv_uninstall')

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        assert delegator.run('copy /y nul Pipfile').return_code == 0
        assert delegator.run('pipenv --python python').return_code == 0

        # Add entries to Pipfile.
        assert delegator.run('pipenv install Werkzeug').return_code == 0
        assert delegator.run('pipenv install pytest --dev').return_code == 0

        pipfile_output = delegator.run('type Pipfile').out
        pipfile_list = pipfile_output.split('\n')

        assert 'werkzeug = "*"' in pipfile_list
        assert 'pytest = "*"' in pipfile_list
        assert '[packages]' in pipfile_list
        assert '[dev-packages]' in pipfile_list

        # Uninstall from dev-packages, removing TOML section.
        assert delegator.run('pipenv uninstall pytest').return_code == 0

        # Test uninstalling non-existant dependency.
        c = delegator.run('pipenv uninstall NotAPackage')
        assert c.return_code == 0
        assert 'No package NotAPackage to remove from Pipfile.' in c.out

        pipfile_output = delegator.run('type Pipfile').out
        pipfile_list = pipfile_output.split('\n')

        assert 'Werkzeug = "*"' in pipfile_list
        assert 'pytest = "*"' not in pipfile_list
        assert '[packages]' in pipfile_list
        assert '[dev-packages]' not in pipfile_list

        os.chdir('..')
        shutil.rmtree('test_pipenv_uninstall')

    def test_pipenv_run(self):
        working_dir = 'test_pipenv_run'
        delegator.run('mkdir {0}'.format(working_dir))
        os.chdir(working_dir)

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        assert delegator.run('copy /y nul Pipfile').return_code == 0
        assert delegator.run('pipenv --python python').return_code == 0

        # Install packages for test.
        assert delegator.run('pipenv install pep8').return_code == 0
        assert delegator.run('pipenv install pytest').return_code == 0

        # Run test commands.
        assert delegator.run('pipenv run python -c \'print("test")\'').return_code == 0
        assert delegator.run('pipenv run pep8 --version').return_code == 0
        assert delegator.run('pipenv run pytest --version').return_code == 0

        os.chdir('..')
        shutil.rmtree(working_dir)

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

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'

        assert delegator.run('copy /y nul Pipfile').return_code == 0
        assert delegator.run('pipenv --python python').return_code == 0
        assert delegator.run('pipenv install requests==2.14.0').return_code == 0
        assert delegator.run('pipenv install flask==0.12.2').return_code == 0
        assert delegator.run('pipenv install --dev pytest==3.1.1').return_code == 0

        req_list = ("requests==2.14.0", "flask==0.12.2", "pytest==3.1.1")

        # Validate requirements.txt.
        c = delegator.run('pipenv lock -r')
        assert c.return_code == 0
        for req in req_list:
            assert req in c.out

        # Cleanup.
        os.chdir('..')
        shutil.rmtree('test_pipenv_requirements')
