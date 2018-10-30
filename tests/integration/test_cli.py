"""Tests to ensure `pipenv --option` works.
"""

import os
import re

import pytest
from flaky import flaky
from pipenv.utils import normalize_drive


@pytest.mark.cli
def test_pipenv_where(PipenvInstance, pypi_secure):
    with PipenvInstance(pypi=pypi_secure) as p:
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
def test_pipenv_graph(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('install requests')
        assert c.ok
        graph = p.pipenv("graph")
        assert graph.ok
        assert "requests" in graph.out
        graph_json = p.pipenv("graph --json")
        assert graph_json.ok
        assert "requests" in graph_json.out
        graph_json_tree = p.pipenv("graph --json-tree")
        assert graph_json_tree.ok
        assert "requests" in graph_json_tree.out


@pytest.mark.cli
def test_pipenv_graph_reverse(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('install requests==2.18.4')
        assert c.ok
        c = p.pipenv('graph --reverse')
        assert c.ok
        output = c.out

        requests_dependency = [
            ('certifi', 'certifi>=2017.4.17'),
            ('chardet', 'chardet(>=3.0.2,<3.1.0|<3.1.0,>=3.0.2)'),
            ('idna', 'idna(>=2.5,<2.7|<2.7,>=2.5)'),
            ('urllib3', 'urllib3(>=1.21.1,<1.23|<1.23,>=1.21.1)')
        ]

        for dep_name, dep_constraint in requests_dependency:
            dep_match = re.search(r'^{}==[\d.]+$'.format(dep_name), output, flags=re.MULTILINE)
            dep_requests_match = re.search(r'^  - requests==2.18.4 \[requires: {}\]$'.format(dep_constraint), output, flags=re.MULTILINE)
            assert dep_match is not None
            assert dep_requests_match is not None
            assert dep_requests_match.start() > dep_match.start()

        c = p.pipenv('graph --reverse --json')
        assert c.return_code == 1
        assert 'Warning: Using both --reverse and --json together is not supported.' in c.err


@pytest.mark.cli
@pytest.mark.needs_internet(reason='required by check')
@flaky
def test_pipenv_check(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
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
def test_install_parse_error(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:

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
@pytest.mark.skip(reason="non-deterministic")
def test_check_unused(PipenvInstance, pypi):
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        with open('__init__.py', 'w') as f:
            contents = """
import tablib
import records
            """.strip()
            f.write(contents)
        p.pipenv('install requests')
        p.pipenv('install tablib')
        p.pipenv('install records')

        assert all(pkg in p.pipfile['packages'] for pkg in ['requests', 'tablib', 'records'])

        c = p.pipenv('check --unused .')
        assert 'tablib' not in c.out
