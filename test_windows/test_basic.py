import os

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

        assert delegator.run('echo $null >> Pipfile').return_code == 0

        assert delegator.run('pipenv --python python').return_code == 0
        assert delegator.run('pipenv install Werkzeug').return_code == 0
        assert delegator.run('pipenv install pytest --dev').return_code == 0
        assert delegator.run('pipenv install git+https://github.com/requests/requests.git@v2.18.4#egg=requests').return_code == 0
        assert delegator.run('pipenv lock').return_code == 0

        # Test uninstalling a package after locking.
        assert delegator.run('pipenv uninstall Werkzeug').return_code == 0

        pipfile_output = delegator.run('cat Pipfile').out
        lockfile_output = delegator.run('cat Pipfile.lock').out

    # def test_install(self):
    #     c = delegator.run('pipenv install')
    #     assert c.return_code == 0

    # def test_lock(self):
    #     c = delegator.run('pipenv lock')
    #     assert c.return_code == 0
