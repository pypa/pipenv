import os
import tempfile
import shutil
import json
from pipenv.vendor import toml
from pipenv.vendor import delegator

class PipenvInstance():
    """docstring for PipenvInstance"""
    def __init__(self, pipfile=True):
        self.original_dir = os.path.abspath(os.curdir)
        self.path = tempfile.mkdtemp(suffix='project', prefix='pipenv')

        if pipfile:
            p_path = os.sep.join([self.path, 'Pipfile'])
            with open(p_path, 'a'):
                os.utime(p_path, None)

    def __enter__(self):
        os.chdir(self.path)
        return self

    def __exit__(self, *args):
        shutil.rmtree(self.path)
        os.chdir(self.original_dir)

    def pipenv(self, cmd):
        return delegator.run('pipenv {0}'.format(cmd))

    @property
    def pipfile(self):
        p_path = os.sep.join([self.path, 'Pipfile'])
        with open(p_path, 'r') as f:
            return toml.loads(f.read())

    @property
    def lockfile(self):
        p_path = os.sep.join([self.path, 'Pipfile.lock'])
        with open(p_path, 'r') as f:
            return json.loads(f.read())

class TestPipenv:
    """The ultimate testing class."""

    def test_pipenv_where(self):
        with PipenvInstance() as p:
            assert p.path in p.pipenv('--where').out

    def test_pipenv_venv(self):
        with PipenvInstance() as p:
            p.pipenv('--python python')
            assert p.pipenv('--venv').out

    def test_venv_envs(self):
        with PipenvInstance() as p:
            assert p.pipenv('--envs').out

    def test_venv_jumbotron(self):
        with PipenvInstance() as p:
            assert p.pipenv('--jumbotron').out

    def test_bare_output(self):
        with PipenvInstance() as p:
            assert p.pipenv('').out

    def test_basic_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install requests')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'requests' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']

    def test_basic_vcs_install(self):
        with PipenvInstance() as p:
            p.pipenv('install git+https://github.com/requests/requests.git')
            assert p.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'chardet' in p.lockfile['packages']




