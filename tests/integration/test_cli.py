# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
"""Tests to ensure `pipenv --option` works.
"""

import os
import re

import pytest

from flaky import flaky

from pipenv.utils import normalize_drive


@pytest.mark.cli
def test_pipenv_where(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("--where")
        assert c.ok
        assert normalize_drive(p.path) in c.out


@pytest.mark.cli
def test_pipenv_venv(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--python python')
        assert c.ok
        c = p.pipenv('--venv')
        assert c.ok
        venv_path = c.out.strip()
        assert os.path.isdir(venv_path)


@pytest.mark.cli
def test_pipenv_py(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--python python')
        assert c.ok
        c = p.pipenv('--py')
        assert c.ok
        python = c.out.strip()
        assert os.path.basename(python).startswith('python')


@pytest.mark.cli
def test_pipenv_site_packages(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--python python --site-packages')
        assert c.return_code == 0
        assert 'Making site-packages available' in c.err

        # no-global-site-packages.txt under stdlib dir should not exist.
        c = p.pipenv('run python -c "import sysconfig; print(sysconfig.get_path(\'stdlib\'))"')
        assert c.return_code == 0
        stdlib_path = c.out.strip()
        assert not os.path.isfile(os.path.join(stdlib_path, 'no-global-site-packages.txt'))


@pytest.mark.cli
def test_pipenv_support(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--support')
        assert c.ok
        assert c.out


@pytest.mark.cli
def test_pipenv_rm(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--python python')
        assert c.ok
        c = p.pipenv('--venv')
        assert c.ok
        venv_path = c.out.strip()
        assert os.path.isdir(venv_path)

        c = p.pipenv('--rm')
        assert c.ok
        assert c.out
        assert not os.path.isdir(venv_path)


@pytest.mark.cli
def test_pipenv_graph(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('install tablib')
        assert c.ok
        graph = p.pipenv("graph")
        assert graph.ok
        assert "tablib" in graph.out
        graph_json = p.pipenv("graph --json")
        assert graph_json.ok
        assert "tablib" in graph_json.out
        graph_json_tree = p.pipenv("graph --json-tree")
        assert graph_json_tree.ok
        assert "tablib" in graph_json_tree.out


@pytest.mark.cli
def test_pipenv_graph_reverse(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('install tablib==0.13.0')
        assert c.ok
        c = p.pipenv('graph --reverse')
        assert c.ok
        output = c.out

        c = p.pipenv('graph --reverse --json')
        assert c.return_code == 1
        assert 'Warning: Using both --reverse and --json together is not supported.' in c.err

        requests_dependency = [
            ('backports.csv', 'backports.csv'),
            ('odfpy', 'odfpy'),
            ('openpyxl', 'openpyxl>=2.4.0'),
            ('pyyaml', 'pyyaml'),
            ('xlrd', 'xlrd'),
            ('xlwt', 'xlwt'),
        ]

        for dep_name, dep_constraint in requests_dependency:
            pat = r'^[ -]*{}==[\d.]+'.format(dep_name)
            dep_match = re.search(pat, output, flags=re.MULTILINE)
            assert dep_match is not None, '{} not found in {}'.format(pat, output)

            # openpyxl should be indented
            if dep_name == 'openpyxl':
                openpyxl_dep = re.search(r'^openpyxl', output, flags=re.MULTILINE)
                assert openpyxl_dep is None, 'openpyxl should not appear at begining of lines in {}'.format(output)

                assert '  - openpyxl==2.5.4 [requires: et-xmlfile]' in output
            else:
                dep_match = re.search(r'^[ -]*{}==[\d.]+$'.format(dep_name), output, flags=re.MULTILINE)
                assert dep_match is not None, '{} not found at beginning of line in {}'.format(dep_name, output)

            dep_requests_match = re.search(r'^ +- tablib==0.13.0 \[requires: {}\]$'.format(dep_constraint), output, flags=re.MULTILINE)
            assert dep_requests_match is not None, 'constraint {} not found in {}'.format(dep_constraint, output)
            assert dep_requests_match.start() > dep_match.start()


@pytest.mark.cli
@pytest.mark.needs_internet(reason='required by check')
@flaky
def test_pipenv_check(PipenvInstance):
    with PipenvInstance() as p:
        p.pipenv('install requests==1.0.0')
        c = p.pipenv('check')
        assert c.return_code != 0
        assert 'requests' in c.out
        c = p.pipenv('uninstall requests')
        assert c.ok
        c = p.pipenv('install six')
        assert c.ok
        c = p.pipenv('check --ignore 35015')
        assert c.return_code == 0
        assert 'Ignoring' in c.err


@pytest.mark.cli
def test_pipenv_clean_pip_no_warnings(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open('setup.py', 'w') as f:
            f.write('from setuptools import setup; setup(name="empty")')
        c = p.pipenv('install -e .')
        assert c.return_code == 0
        c = p.pipenv('run pip install pytz')
        assert c.return_code == 0
        c = p.pipenv('clean')
        assert c.return_code == 0
        assert c.out, "{0} -- STDERR: {1}".format(c.out, c.err)


@pytest.mark.cli
def test_pipenv_clean_pip_warnings(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open('setup.py', 'w') as f:
            f.write('from setuptools import setup; setup(name="empty")')
        # create a fake git repo to trigger a pip freeze warning
        os.mkdir('.git')
        c = p.pipenv("run pip install -e .")
        assert c.return_code == 0
        c = p.pipenv('clean')
        assert c.return_code == 0
        assert c.err


@pytest.mark.cli
def test_venv_envs(PipenvInstance):
    with PipenvInstance() as p:
        assert p.pipenv('--envs').out


@pytest.mark.cli
def test_bare_output(PipenvInstance):
    with PipenvInstance() as p:
        assert p.pipenv('').out


@pytest.mark.cli
def test_help(PipenvInstance):
    with PipenvInstance() as p:
        assert p.pipenv('--help').out


@pytest.mark.cli
def test_man(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--man')
        assert c.return_code == 0 or c.err


@pytest.mark.cli
def test_install_parse_error(PipenvInstance):
    with PipenvInstance() as p:

        # Make sure unparseable packages don't wind up in the pipfile
        # Escape $ for shell input
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]

[dev-packages]
            """.strip()
            f.write(contents)
        c = p.pipenv('install requests u/\\/p@r\$34b13+pkg')
        assert c.return_code != 0
        assert 'u/\\/p@r$34b13+pkg' not in p.pipfile['packages']


@pytest.mark.code
@pytest.mark.check
@pytest.mark.unused
@pytest.mark.skip_osx
@pytest.mark.needs_internet(reason='required by check')
def test_check_unused(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open('__init__.py', 'w') as f:
            contents = """
import click
import records
import flask
            """.strip()
            f.write(contents)
        p.pipenv('install requests click flask')

        assert all(pkg in p.pipfile['packages'] for pkg in ['requests', 'click', 'flask']), p.pipfile["packages"]

        c = p.pipenv('check --unused .')
        assert 'click' not in c.out
        assert 'flask' not in c.out


@pytest.mark.cli
def test_pipenv_clear(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--clear')
        assert c.return_code == 0
        assert 'Clearing caches' in c.out


@pytest.mark.cli
def test_pipenv_three(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv('--three')
        assert c.return_code == 0
        assert 'Successfully created virtual environment' in c.err


@pytest.mark.outdated
def test_pipenv_outdated_prerelease(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
sqlalchemy = "<=1.2.3"
            """.strip()
            f.write(contents)
        c = p.pipenv('update --pre --outdated')
        assert c.return_code == 0
