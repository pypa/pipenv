import os

import pytest
import delegator
import toml

from pipenv.cli import parse_download_fname, ensure_proper_casing

class TestPipenv():

    @pytest.mark.parametrize('fname, expected', [
        ('functools32-3.2.3-2.zip', '3.2.3-2'),
        ('functools32-3.2.3-blah.zip', '3.2.3-blah'),
        ('functools32-3.2.3.zip', '3.2.3'),
        ('colorama-0.3.7-py2.py3-none-any.whl', '0.3.7'),
        ('colorama-0.3.7-2-py2.py3-none-any.whl', '0.3.7-2'),
        ('click-completion-0.2.1.tar.gz', '0.2.1'),
        ('Twisted-16.5.0.tar.bz2', '16.5.0'),
        ('Twisted-16.1.1-cp27-none-win_amd64.whl', '16.1.1')
    ])
    def test_parse_download_fname(self, fname, expected):
        version = parse_download_fname(fname)
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
