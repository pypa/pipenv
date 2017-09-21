import os
import shutil

from mock import patch, Mock, PropertyMock

from pipenv.vendor import delegator
from pipenv.patched import contoml

from pipenv.cli import (
    ensure_proper_casing,
    pip_install, pip_download, find_a_system_python
)

FULL_PYTHON_PATH = 'C:\\Python36-x64\\python.exe'

class TestPipenvWindows():

    def test_existience(self):
        assert True

    def test_cli_with_custom_python_path(self):
        delegator.run('mkdir custom_python')
        os.chdir('custom_python')

        c = delegator.run('pipenv install --python={0}'.format(FULL_PYTHON_PATH))

        # Debugging, if it fails.
        print(c.out)
        print(c.err)

        assert c.return_code == 0

    def test_cli_usage(self):
        delegator.run('mkdir test_project')
        os.chdir('test_project')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'

        assert delegator.run('copy /y nul Pipfile').return_code == 0

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
                    '-e git+https://github.com/kennethreitz/maya.git@v0.3.2#egg=maya\n'
                    'six==1.10.0\n')

        assert delegator.run('pipenv install').return_code == 0
        print(delegator.run('pipenv lock').err)
        assert delegator.run('pipenv lock').return_code == 0

        pipfile_output = delegator.run('type Pipfile').out
        lockfile_output = delegator.run('type Pipfile.lock').out

        # Ensure extras work.
        assert 'socks' in pipfile_output
        assert 'pysocks' in lockfile_output

        # Ensure vcs dependencies work.
        assert 'records' in pipfile_output
        assert '"git": "https://github.com/kennethreitz/records.git"' in lockfile_output

        # Ensure editable packages work.
        assert 'ref = "v0.3.2"' in pipfile_output
        assert '"editable": true' in lockfile_output

        # Ensure BAD_PACKAGES aren't copied into Pipfile from requirements.txt.
        assert 'six = "==1.10.0"' not in pipfile_output

        os.chdir('..')
        # shutil.rmtree('test_requirements_to_pip')
        del os.environ['PIPENV_MAX_DEPTH']

    def test_timeout_long(self):
        delegator.run('mkdir test_timeout_long')
        os.chdir('test_timeout_long')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_TIMEOUT'] = '60'

        assert delegator.run('copy /y nul Pipfile').return_code == 0

        os.chdir('..')
        shutil.rmtree('test_timeout_long')
        del os.environ['PIPENV_TIMEOUT']

    def test_timeout_short(self):
        delegator.run('mkdir test_timeout_short')
        os.chdir('test_timeout_short')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_TIMEOUT'] = '0'

        assert delegator.run('copy /y nul Pipfile').return_code == 0

        os.chdir('..')
        shutil.rmtree('test_timeout_short')
        del os.environ['PIPENV_TIMEOUT']

    def test_pipenv_uninstall(self):
        delegator.run('mkdir test_pipenv_uninstall')
        os.chdir('test_pipenv_uninstall')

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        assert delegator.run('copy /y nul Pipfile').return_code == 0
        assert delegator.run('pipenv install').return_code == 0

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
        # assert '[dev-packages]' not in pipfile_list

        os.chdir('..')
        shutil.rmtree('test_pipenv_uninstall')

    def test_pipenv_run(self):
        working_dir = 'test_pipenv_run'
        delegator.run('mkdir {0}'.format(working_dir))
        os.chdir(working_dir)

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        assert delegator.run('copy /y nul Pipfile').return_code == 0

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
        p = contoml.loads(pfile_test)

        assert 'DjAnGO' in p['packages']
        assert 'PyTEST' in p['dev-packages']

        changed = ensure_proper_casing(p)

        assert 'Django' in p['packages']
        assert 'DjAnGO' not in p['packages']

        assert 'pytest' in p['dev-packages']
        assert 'PyTEST' not in p['dev-packages']

        assert changed is True

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
