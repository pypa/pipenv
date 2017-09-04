import os
import shutil

#from mock import patch, Mock, PropertyMock

import pytest
import delegator
import toml

from pipenv.cli import (activate_virtualenv, ensure_proper_casing,
    parse_download_fname, parse_install_output, pip_install, pip_download)
from pipenv.project import Project


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

        assert delegator.run('pipenv --python python').return_code == 0
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

    # def test_install(self):
    #     c = delegator.run('pipenv install')
    #     assert c.return_code == 0

    # def test_lock(self):
    #     c = delegator.run('pipenv lock')
    #     assert c.return_code == 0
