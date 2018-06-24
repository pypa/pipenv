"""Misc. tests that don't fit anywhere.

XXX: Try our best to reduce tests in this file.
"""

from pipenv.core import activate_virtualenv
from pipenv.project import Project
from pipenv.vendor import delegator
import pytest


@pytest.mark.code
@pytest.mark.install
@pytest.mark.skip(reason='non deterministic')
def test_code_import_manual(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open('t.py', 'w') as f:
            f.write('import requests')
        p.pipenv('install -c .')
        assert 'requests' in p.pipfile['packages']


@pytest.mark.code
@pytest.mark.virtualenv
@pytest.mark.project
def test_activate_virtualenv_no_source():
    command = activate_virtualenv(source=False)
    venv = Project().virtualenv_location
    assert command == '{0}/bin/activate'.format(venv)


@pytest.mark.lock
@pytest.mark.deploy
@pytest.mark.cli
def test_deploy_works(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "==2.14.0"
flask = "==0.12.2"

[dev-packages]
pytest = "==3.1.1"
            """.strip()
            f.write(contents)
        c = p.pipenv('install --verbose')
        if c.return_code != 0:
            assert c.err == '' or c.err is None
            assert c.out == ''
        assert c.return_code == 0
        c = p.pipenv('lock')
        assert c.return_code == 0
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "==2.14.0"
            """.strip()
            f.write(contents)

        c = p.pipenv('install --deploy')
        assert c.return_code > 0


@pytest.mark.update
@pytest.mark.lock
def test_update_locks(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('install requests==2.14.0')
        assert c.return_code == 0
        with open(p.pipfile_path, 'r') as fh:
            pipfile_contents = fh.read()
        pipfile_contents = pipfile_contents.replace('==2.14.0', '*')
        with open(p.pipfile_path, 'w') as fh:
            fh.write(pipfile_contents)
        c = p.pipenv('update requests')
        assert c.return_code == 0
        assert p.lockfile['default']['requests']['version'] == '==2.19.1'
        c = p.pipenv('run pip freeze')
        assert c.return_code == 0
        lines = c.out.splitlines()
        assert 'requests==2.19.1' in [l.strip() for l in lines]


@pytest.mark.project
@pytest.mark.proper_names
def test_proper_names_unamanged_virtualenv(PipenvInstance, pypi):
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        c = delegator.run('python -m virtualenv .venv')
        assert c.return_code == 0
        project = Project()
        assert project.proper_names == []
