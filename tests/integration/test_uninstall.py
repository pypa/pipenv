import os
import shutil

import pytest


@pytest.mark.run
@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('install requests')
        assert c.return_code == 0
        assert 'requests' in p.pipfile['packages']
        assert 'requests' in p.lockfile['default']
        assert 'chardet' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'urllib3' in p.lockfile['default']
        assert 'certifi' in p.lockfile['default']

        c = p.pipenv('uninstall requests')
        assert c.return_code == 0
        assert 'requests' not in p.pipfile['dev-packages']
        assert 'requests' not in p.lockfile['develop']
        assert 'chardet' not in p.lockfile['develop']
        assert 'idna' not in p.lockfile['develop']
        assert 'urllib3' not in p.lockfile['develop']
        assert 'certifi' not in p.lockfile['develop']

        c = p.pipenv('run python -m requests.help')
        assert c.return_code > 0


@pytest.mark.files
@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall_all_local_files(PipenvInstance, testsroot):
    file_name = 'tablib-0.12.1.tar.gz'
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, 'test_artifacts', file_name))

    with PipenvInstance() as p:
        shutil.copy(source_path, os.path.join(p.path, file_name))
        os.mkdir(os.path.join(p.path, "tablib"))
        c = p.pipenv('install {}'.format(file_name))
        assert c.return_code == 0
        c = p.pipenv('uninstall --all')
        assert c.return_code == 0
        assert 'tablib' in c.out
        assert 'tablib' not in p.pipfile['packages']


@pytest.mark.run
@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall_all_dev(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('install --dev requests six')
        assert c.return_code == 0

        c = p.pipenv('install pytz')
        assert c.return_code == 0

        assert 'pytz' in p.pipfile['packages']
        assert 'requests' in p.pipfile['dev-packages']
        assert 'six' in p.pipfile['dev-packages']
        assert 'pytz' in p.lockfile['default']
        assert 'requests' in p.lockfile['develop']
        assert 'six' in p.lockfile['develop']

        c = p.pipenv('uninstall --all-dev')
        assert c.return_code == 0
        assert 'requests' not in p.pipfile['dev-packages']
        assert 'six' not in p.pipfile['dev-packages']
        assert 'requests' not in p.lockfile['develop']
        assert 'six' not in p.lockfile['develop']
        assert 'pytz' in p.pipfile['packages']
        assert 'pytz' in p.lockfile['default']

        c = p.pipenv('run python -m requests.help')
        assert c.return_code > 0

        c = p.pipenv('run python -c "import pytz"')
        assert c.return_code == 0


@pytest.mark.uninstall
@pytest.mark.run
def test_normalize_name_uninstall(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
# Pre comment
[packages]
Requests = "*"
python_DateUtil = "*"   # Inline comment
"""
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0

        c = p.pipenv('uninstall python_dateutil')
        assert 'Requests' in p.pipfile['packages']
        assert 'python_DateUtil' not in p.pipfile['packages']
        contents = open(p.pipfile_path).read()
        assert '# Pre comment' in contents
        assert '# Inline comment' in contents
