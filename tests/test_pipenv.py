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

    def test_cli_usage(self):
        delegator.run('mkdir test_project')
        os.chdir('test_project')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'

        assert delegator.run('touch Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 0
        assert delegator.run('pipenv install Werkzeug').return_code == 0
        assert delegator.run('pipenv install pytest --dev').return_code == 0
        # assert delegator.run('pipenv install https://pypi.python.org/packages/49/df/50aa1999ab9bde74656c2919d9c0c085fd2b3775fd3eca826012bef76d8c/requests-2.18.4-py2.py3-none-any.whl#md5=eb9be71cc41fd73a51a7c9cd1adde5de').return_code == 0

        # Debug.
        print(delegator.run('pipenv install regex').err)

        assert delegator.run('pipenv install regex').return_code == 0  # failing before
        assert delegator.run('pipenv install git+https://github.com/requests/requests.git@v2.18.4#egg=requests').return_code == 0
        assert delegator.run('pipenv lock').return_code == 0
        assert delegator.run('pipenv update --dev --dry-run').return_code == 0

        # Test uninstalling a package after locking.
        assert delegator.run('pipenv uninstall Werkzeug').return_code == 0

        pipfile_output = delegator.run('cat Pipfile').out
        lockfile_output = delegator.run('cat Pipfile.lock').out

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
        delegator.run('rm -fr test_project')

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

        assert delegator.run('pipenv --python python').return_code == 0
        print(delegator.run('pipenv lock').err)
        assert delegator.run('pipenv lock').return_code == 0

        pipfile_output = delegator.run('cat Pipfile').out
        lockfile_output = delegator.run('cat Pipfile.lock').out

        # Ensure extras work.
        assert 'socks' in pipfile_output
        assert 'pysocks' in lockfile_output

        # Ensure vcs dependencies work.
        assert 'records' in pipfile_output
        assert '"git": "https://github.com/kennethreitz/records.git"' in lockfile_output

        # Ensure editable packages work.
        assert 'ref = "v0.11.5"' in pipfile_output
        assert '"editable": true' in lockfile_output

        # Ensure BAD_PACKAGES aren't copied into Pipfile from requirements.txt.
        assert 'six = "==1.10.0"' not in pipfile_output

        os.chdir('..')
        delegator.run('rm -fr test_requirements_to_pip')
        del os.environ['PIPENV_MAX_DEPTH']

    def test_timeout_long(self):
        delegator.run('mkdir test_timeout_long')
        os.chdir('test_timeout_long')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_TIMEOUT'] = '60'

        assert delegator.run('touch Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 0

        os.chdir('..')
        delegator.run('rm -fr test_timeout_long')
        del os.environ['PIPENV_TIMEOUT']

    def test_timeout_short(self):
        delegator.run('mkdir test_timeout_short')
        os.chdir('test_timeout_short')

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_TIMEOUT'] = '1'

        assert delegator.run('touch Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 1

        os.chdir('..')
        delegator.run('rm -fr test_timeout_short')
        del os.environ['PIPENV_TIMEOUT']

    def test_pipenv_uninstall(self):
        delegator.run('mkdir test_pipenv_uninstall')
        os.chdir('test_pipenv_uninstall')

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        assert delegator.run('touch Pipfile').return_code == 0
        assert delegator.run('pipenv --python python').return_code == 0

        # Add entries to Pipfile.
        assert delegator.run('pipenv install Werkzeug').return_code == 0
        assert delegator.run('pipenv install pytest --dev').return_code == 0

        pipfile_output = delegator.run('cat Pipfile').out
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

        pipfile_output = delegator.run('cat Pipfile').out
        pipfile_list = pipfile_output.split('\n')

        assert 'Werkzeug = "*"' in pipfile_list
        assert 'pytest = "*"' not in pipfile_list
        assert '[packages]' in pipfile_list
        # assert '[dev-packages]' not in pipfile_list

        os.chdir('..')
        delegator.run('rm -fr test_pipenv_uninstall')

    def test_pipenv_uninstall_dev(self):
        delegator.run('mkdir test_pipenv_uninstall_dev')
        os.chdir('test_pipenv_uninstall_dev')

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        assert delegator.run('touch Pipfile').return_code == 0
        assert delegator.run('pipenv --python python').return_code == 0

        # Add entries to Pipfile.
        assert delegator.run('pipenv install pytest --dev').return_code == 0

        pipfile_output = delegator.run('cat Pipfile').out
        pipfile_list = pipfile_output.split('\n')

        assert '[dev-packages]' in pipfile_list
        assert 'pytest = "*"' in pipfile_list

        # Uninstall from dev-packages, removing TOML section.
        assert delegator.run('pipenv uninstall -d pytest').return_code == 0

        pipfile_output = delegator.run('cat Pipfile').out
        pipfile_list = pipfile_output.split('\n')

        assert 'pytest = "*"' not in pipfile_list

        os.chdir('..')
        delegator.run('rm -fr test_pipenv_uninstall_dev')

    def test_pipenv_run(self):
        working_dir = 'test_pipenv_run'
        delegator.run('mkdir {0}'.format(working_dir))
        os.chdir(working_dir)

        # Build the environment.
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        delegator.run('touch Pipfile')

        # Install packages for test.
        # print(delegator.run('pipenv install pep8').err)
        assert delegator.run('pipenv install pep8').return_code == 0
        assert delegator.run('pipenv install pytest').return_code == 0

        # Run test commands.
        assert delegator.run('pipenv run python -c \'print("test")\'').return_code == 0
        assert delegator.run('pipenv run pep8 --version').return_code == 0
        assert delegator.run('pipenv run pytest --version').return_code == 0

        os.chdir('..')
        delegator.run('rm -fr {0}'.format(working_dir))

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
