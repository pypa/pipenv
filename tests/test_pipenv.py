import os

import pytest
import delegator
import toml

from pipenv.cli import (parse_download_fname, ensure_proper_casing,
    parse_install_output)

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
        """Ensure proper casing for package names"""
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

        assert 'django' in p['packages']
        assert 'DjAnGO' not in p['packages']

        assert 'pytest' in p['dev-packages']
        assert 'PyTEST' not in p['dev-packages']

        assert changed is True

    def test_ensure_proper_casing_no_change(self):
        """Ensure changed flag is false with no changes"""
        pfile_test = ("[packages]\n"
                      "flask = \"==0.11\"\n"
                      "\n\n"
                      "[dev-packages]\n"
                      "pytest = \"*\"\n")

        # Load test Pipfile.
        p = toml.loads(pfile_test)
        changed = ensure_proper_casing(p)

        assert 'flask' in p['packages']
        assert 'pytest' in p['dev-packages']
        assert changed is False

    def test_parse_install_output(self):
        install_output = ("Collecting requests\n"
                          "Using cached requests-2.13.0-py2.py3-none-any.whl\n"
                          "Successfully downloaded requests-2.13.0\n"
                          "Collecting honcho\n"
                          "Using cached honcho-0.7.1.tar.gz\n"
                          "Successfully downloaded honcho-0.7.1\n"
                          "Collecting foursquare\n"
                          "Downloading foursquare-1%212015.4.7.tar.gz\n"
                          "Saved ./foursquare-1%212015.4.7.tar.gz\n"
                          "Successfully downloaded click\n")

        names_map = dict(parse_install_output(install_output))
        assert 'requests-2.13.0-py2.py3-none-any.whl' in names_map
        assert names_map['requests-2.13.0-py2.py3-none-any.whl'] == 'requests'
        assert 'foursquare-1!2015.4.7.tar.gz' in names_map
