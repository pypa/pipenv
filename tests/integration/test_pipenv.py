# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
"""Misc. tests that don't fit anywhere.

XXX: Try our best to reduce tests in this file.
"""

import os

import pytest

from pipenv.project import Project
from pipenv.utils import temp_environ
from pipenv.vendor import delegator


@pytest.mark.code
@pytest.mark.install
@pytest.mark.skip(reason='non deterministic')
def test_code_import_manual(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open('t.py', 'w') as f:
            f.write('import requests')
        p.pipenv('install -c .')
        assert 'requests' in p.pipfile['packages']


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
        if c.return_code != 0:
            assert c.err == '' or c.err is None
            assert c.out == ''
        assert c.return_code == 0
        c = p.pipenv('lock')
        assert c.return_code == 0
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "==2.19.1"
            """.strip()
            f.write(contents)

        c = p.pipenv('install --deploy')
        assert c.return_code > 0


@pytest.mark.update
@pytest.mark.lock
def test_update_locks(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('install jdcal==1.3')
        assert c.return_code == 0
        assert p.lockfile['default']['jdcal']['version'] == '==1.3'
        with open(p.pipfile_path, 'r') as fh:
            pipfile_contents = fh.read()
        assert '==1.3' in pipfile_contents
        pipfile_contents = pipfile_contents.replace('==1.3', '*')
        with open(p.pipfile_path, 'w') as fh:
            fh.write(pipfile_contents)
        c = p.pipenv('update jdcal')
        assert c.return_code == 0
        assert p.lockfile['default']['jdcal']['version'] == '==1.4'
        c = p.pipenv('run pip freeze')
        assert c.return_code == 0
        lines = c.out.splitlines()
        assert 'jdcal==1.4' in [l.strip() for l in lines]


@pytest.mark.project
@pytest.mark.proper_names
def test_proper_names_unamanged_virtualenv(PipenvInstance):
    with PipenvInstance(chdir=True):
        c = delegator.run('python -m virtualenv .venv')
        assert c.return_code == 0
        project = Project()
        assert project.proper_names == []


@pytest.mark.cli
def test_directory_with_leading_dash(raw_venv, PipenvInstance):
    with temp_environ():
        with PipenvInstance(chdir=True, venv_in_project=False, name="-project-with-dash") as p:
            if "PIPENV_VENV_IN_PROJECT" in os.environ:
                del os.environ['PIPENV_VENV_IN_PROJECT']
            c = p.pipenv('run pip freeze')
            assert c.return_code == 0
            c = p.pipenv('--venv')
            assert c.return_code == 0
            venv_path = c.out.strip()
            assert os.path.isdir(venv_path)
            # Manually clean up environment, since PipenvInstance assumes that
            # the virutalenv is in the project directory.
            p.pipenv('--rm')
