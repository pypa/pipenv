"""Misc. tests that don't fit anywhere.

XXX: Try our best to reduce tests in this file.
"""

import os

import pytest

from pipenv.project import Project
from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import temp_environ


@pytest.mark.lock
@pytest.mark.deploy
def test_deploy_works(PipenvInstance):

    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "==2.19.1"
flask = "==1.1.2"

[dev-packages]
pytest = "==4.6.9"
            """.strip()
            f.write(contents)
        c = p.pipenv('install --verbose')
        if c.returncode != 0:
            assert c.stderr == '' or c.stderr is None
            assert c.stdout == ''
        assert c.returncode == 0
        c = p.pipenv('lock')
        assert c.returncode == 0
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "==2.19.1"
            """.strip()
            f.write(contents)

        c = p.pipenv('install --deploy')
        assert c.returncode > 0


@pytest.mark.update
@pytest.mark.lock
def test_update_locks(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('install jdcal==1.3')
        assert c.returncode == 0
        assert p.lockfile['default']['jdcal']['version'] == '==1.3'
        with open(p.pipfile_path) as fh:
            pipfile_contents = fh.read()
        assert '==1.3' in pipfile_contents
        pipfile_contents = pipfile_contents.replace('==1.3', '*')
        with open(p.pipfile_path, 'w') as fh:
            fh.write(pipfile_contents)
        c = p.pipenv('update jdcal')
        assert c.returncode == 0
        assert p.lockfile['default']['jdcal']['version'] == '==1.4'
        c = p.pipenv('run pip freeze')
        assert c.returncode == 0
        lines = c.stdout.splitlines()
        assert 'jdcal==1.4' in [l.strip() for l in lines]


@pytest.mark.project
@pytest.mark.proper_names
def test_proper_names_unamanged_virtualenv(PipenvInstance):
    with PipenvInstance(chdir=True):
        c = subprocess_run(['python', '-m', 'virtualenv', '.venv'])
        assert c.returncode == 0
        project = Project()
        assert project.proper_names == []


@pytest.mark.cli
def test_directory_with_leading_dash(raw_venv, PipenvInstance):
    with temp_environ():
        with PipenvInstance(chdir=True, venv_in_project=False, name="-project-with-dash") as p:
            c = p.pipenv('run pip freeze')
            assert c.returncode == 0
            c = p.pipenv('--venv')
            assert c.returncode == 0
            venv_path = c.stdout.strip()
            assert os.path.isdir(venv_path)
