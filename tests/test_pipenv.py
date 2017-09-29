import os
import tempfile
import shutil
import json

import pytest

from pipenv.cli import activate_virtualenv
from pipenv.vendor import toml
from pipenv.vendor import delegator
from pipenv.project import Project

os.environ['PIPENV_DONT_USE_PYENV'] = '1'

class PipenvInstance():
    """An instance of a Pipenv Project..."""
    def __init__(self, pipfile=True, chdir=False):
        self.original_dir = os.path.abspath(os.curdir)
        self.path = tempfile.mkdtemp(suffix='project', prefix='pipenv')
        self.pipfile_path = None
        self.chdir = chdir

        if pipfile:
            p_path = os.sep.join([self.path, 'Pipfile'])
            with open(p_path, 'a'):
                os.utime(p_path, None)

            self.chdir = False or chdir
            self.pipfile_path = p_path

    def __enter__(self):
        if self.chdir:
            os.chdir(self.path)
        return self

    def __exit__(self, *args):
        if self.chdir:
            os.chdir(self.original_dir)

        shutil.rmtree(self.path)

    def pipenv(self, cmd, block=True):
        if self.pipfile_path:
            os.environ['PIPENV_PIPFILE'] = self.pipfile_path

        c = delegator.run('pipenv {0}'.format(cmd), block=block)

        if 'PIPENV_PIPFILE' in os.environ:
            del os.environ['PIPENV_PIPFILE']

        # Pretty output for failing tests.
        if block:
            print('$ pipenv {0}'.format(cmd))
            print(c.out)
            print(c.err)

        # Where the action happens.
        return c

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

    @pytest.mark.cli
    def test_pipenv_where(self):
        with PipenvInstance() as p:
            assert p.path in p.pipenv('--where').out

    @pytest.mark.cli
    def test_pipenv_venv(self):
        with PipenvInstance() as p:
            p.pipenv('--python python')
            assert p.pipenv('--venv').out

    @pytest.mark.cli
    def test_pipenv_py(self):
        with PipenvInstance() as p:
            p.pipenv('--python python')
            assert p.pipenv('--py').out

    @pytest.mark.cli
    def test_pipenv_rm(self):
        with PipenvInstance() as p:
            p.pipenv('--python python')
            venv_path = p.pipenv('--venv').out

            assert p.pipenv('--rm').out
            assert not os.path.isdir(venv_path)

    @pytest.mark.cli
    def test_pipenv_graph(self):
        with PipenvInstance() as p:
            p.pipenv('install requests')
            assert 'requests' in p.pipenv('graph').out
            assert 'requests' in p.pipenv('graph --json').out

    @pytest.mark.cli
    def test_pipenv_check(self):
        with PipenvInstance() as p:
            p.pipenv('install requests==1.0.0')
            assert 'requests' in p.pipenv('check').out

    @pytest.mark.cli
    def test_venv_envs(self):
        with PipenvInstance() as p:
            assert p.pipenv('--envs').out

    @pytest.mark.cli
    def test_venv_jumbotron(self):
        with PipenvInstance() as p:
            assert p.pipenv('--jumbotron').out

    @pytest.mark.cli
    def test_bare_output(self):
        with PipenvInstance() as p:
            assert p.pipenv('').out

    @pytest.mark.cli
    def test_help(self):
        with PipenvInstance() as p:
            assert p.pipenv('--help').out

    @pytest.mark.cli
    def test_completion(self):
        with PipenvInstance() as p:
            assert p.pipenv('--completion').out

    @pytest.mark.cli
    def test_man(self):
        with PipenvInstance() as p:
            c = p.pipenv('--man')
            assert c.return_code == 0 or c.err

    @pytest.mark.install
    @pytest.mark.setup
    @pytest.mark.skip(reason="this doesn't work on travis")
    def test_basic_setup(self):
        with PipenvInstance() as p:
            with PipenvInstance(pipfile=False) as p:
                c = p.pipenv('install requests')
                assert c.return_code == 0

                assert 'requests' in p.pipfile['packages']
                assert 'requests' in p.lockfile['default']
                assert 'chardet' in p.lockfile['default']
                assert 'idna' in p.lockfile['default']
                assert 'urllib3' in p.lockfile['default']
                assert 'certifi' in p.lockfile['default']

    @pytest.mark.spelling
    @pytest.mark.skip(reason="this is slightly non-deterministic")
    def test_spell_checking(self):
        with PipenvInstance() as p:
            c = p.pipenv('install flaskcors', block=False)
            c.expect(u'[Y//n]:')
            c.send('y')
            c.block()

            assert c.return_code == 0
            assert 'flask-cors' in p.pipfile['packages']
            assert 'flask' in p.lockfile['default']

    @pytest.mark.install
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

    @pytest.mark.dev
    @pytest.mark.run
    @pytest.mark.install
    def test_basic_dev_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install requests --dev')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['dev-packages']
            assert 'requests' in p.lockfile['develop']
            assert 'chardet' in p.lockfile['develop']
            assert 'idna' in p.lockfile['develop']
            assert 'urllib3' in p.lockfile['develop']
            assert 'certifi' in p.lockfile['develop']

            c = p.pipenv('run python -m requests.help')
            assert c.return_code == 0

    @pytest.mark.run
    @pytest.mark.uninstall
    def test_uninstall(self):
        with PipenvInstance() as p:
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

    @pytest.mark.extras
    @pytest.mark.install
    def test_extras_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install requests[socks]')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'extras' in p.pipfile['packages']['requests']

            assert 'requests' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'pysocks' in p.lockfile['default']

    @pytest.mark.vcs
    @pytest.mark.install
    def test_basic_vcs_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install git+https://github.com/requests/requests.git#egg=requests')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'git' in p.pipfile['packages']['requests']
            assert p.lockfile['default']['requests'] == {"git": "https://github.com/requests/requests.git"}

    @pytest.mark.e
    @pytest.mark.vcs
    @pytest.mark.install
    def test_editable_vcs_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install -e git+https://github.com/requests/requests.git#egg=requests')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'git' in p.pipfile['packages']['requests']
            assert 'editable' in p.pipfile['packages']['requests']
            assert 'editable' in p.lockfile['default']['requests']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']

    @pytest.mark.run
    @pytest.mark.install
    def test_multiprocess_bug_and_install(self):
        os.environ['PIPENV_MAX_SUBPROCESS'] = '2'

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "*"
records = "*"
tpfd = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'requests' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']
            assert 'records' in p.lockfile['default']
            assert 'tpfd' in p.lockfile['default']
            assert 'parse' in p.lockfile['default']

            c = p.pipenv('run python -c "import requests; import idna; import certifi; import records; import tpfd; import parse;"')
            assert c.return_code == 0

            del os.environ['PIPENV_MAX_SUBPROCESS']

    @pytest.mark.sequential
    @pytest.mark.install
    def test_sequential_mode(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "*"
records = "*"
tpfd = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('install --sequential')
            assert c.return_code == 0

            assert 'requests' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']
            assert 'records' in p.lockfile['default']
            assert 'tpfd' in p.lockfile['default']
            assert 'parse' in p.lockfile['default']

            c = p.pipenv('run python -c "import requests; import idna; import certifi; import records; import tpfd; import parse;"')
            assert c.return_code == 0

    @pytest.mark.run
    @pytest.mark.markers
    @pytest.mark.install
    def test_package_environment_markers(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = {version = "*", markers="os_name=='splashwear'"}
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'Ignoring' in c.out
            assert 'markers' in p.lockfile['default']['requests']

            c = p.pipenv('run python -c "import requests;"')
            assert c.return_code == 1

    @pytest.mark.run
    @pytest.mark.alt
    @pytest.mark.install
    def test_specific_package_environment_markers(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = {version = "*", os_name = "== 'splashwear'"}
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'Ignoring' in c.out
            assert 'markers' in p.lockfile['default']['requests']

            c = p.pipenv('run python -c "import requests;"')
            assert c.return_code == 1

    @pytest.mark.run
    @pytest.mark.alt
    @pytest.mark.install
    def test_alternative_version_specifier(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = {version = "*"}
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'requests' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']

            c = p.pipenv('run python -c "import requests; import idna; import certifi;"')
            assert c.return_code == 0

    @pytest.mark.bad
    @pytest.mark.install
    def test_bad_packages(self):

        with PipenvInstance() as p:
            c = p.pipenv('install NotAPackage')
            assert c.return_code > 0

    @pytest.mark.dotvenv
    def test_venv_in_project(self):

        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        with PipenvInstance() as p:
            c = p.pipenv('install requests')
            assert c.return_code == 0

            assert p.path in p.pipenv('--venv').out

        del os.environ['PIPENV_VENV_IN_PROJECT']

    @pytest.mark.run
    @pytest.mark.dotenv
    def test_env(self):

        with PipenvInstance(pipfile=False) as p:
            with open('.env', 'w') as f:
                f.write('HELLO=WORLD')

            c = p.pipenv('run python -c "import os; print(os.environ[\'HELLO\'])"')
            assert c.return_code == 0
            assert 'WORLD' in c.out

    @pytest.mark.e
    @pytest.mark.install
    @pytest.mark.skip(reason="this doesn't work on windows")
    def test_e_dot(self):

        with PipenvInstance() as p:
            path = os.path.abspath(os.path.sep.join([os.path.dirname(__file__), '..']))
            c = p.pipenv('install -e \'{0}\' --dev'.format(path))

            assert c.return_code == 0

            key = [k for k in p.pipfile['dev-packages'].keys()][0]
            assert 'path' in p.pipfile['dev-packages'][key]
            assert 'requests' in p.lockfile['develop']


    @pytest.mark.code
    @pytest.mark.install
    def test_code_import_manual(self):

        with PipenvInstance() as p:

            with PipenvInstance(chdir=True) as p:
                with open('t.py', 'w') as f:
                    f.write('import requests')

                p.pipenv('install -c .')
                assert 'requests' in p.pipfile['packages']

    @pytest.mark.code
    @pytest.mark.check
    @pytest.mark.unused
    def test_check_unused(self):

        with PipenvInstance() as p:

            with PipenvInstance(chdir=True) as p:

                p.pipenv('install requests')
                p.pipenv('install tablib')

                assert 'requests' in p.pipfile['packages']

                c = p.pipenv('check --unused .')
                assert 'tablib' in c.out

    @pytest.mark.check
    @pytest.mark.style
    def test_flake8(self):

        with PipenvInstance() as p:

            with PipenvInstance(chdir=True) as p:
                with open('t.py', 'w') as f:
                    f.write('import requests')

                c = p.pipenv('check --style .')
                assert 'requests' in c.out

    @pytest.mark.extras
    @pytest.mark.install
    @pytest.mark.requirements
    def test_requirements_to_pipfile(self):

        with PipenvInstance(pipfile=False, chdir=True) as p:

            # Write a requirements file
            with open('requirements.txt', 'w') as f:
                f.write('requests[socks]==2.18.1\n')

            c = p.pipenv('install')
            assert c.return_code == 0
            print(c.out)
            print(c.err)
            print(delegator.run('ls -l').out)

            # assert stuff in pipfile
            assert 'requests' in p.pipfile['packages']
            assert 'extras' in p.pipfile['packages']['requests']

            # assert stuff in lockfile
            assert 'requests' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'pysocks' in p.lockfile['default']

    @pytest.mark.code
    @pytest.mark.virtualenv
    def test_activate_virtualenv_no_source(self):
        command = activate_virtualenv(source=False)
        venv = Project().virtualenv_location

        assert command == '{0}/bin/activate'.format(venv)

    @pytest.mark.lock
    @pytest.mark.requirements
    def test_lock_requirements_file(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "==2.14.0"
flask = "==0.12.2"
[dev-packages]
pytest = "==3.1.1"
                """.strip()
                f.write(contents)

            req_list = ("requests==2.14.0", "flask==0.12.2", "pytest==3.1.1")

            c = p.pipenv('lock -r')
            assert c.return_code == 0
            for req in req_list:
                assert req in c.out


    @pytest.mark.lock
    @pytest.mark.requirements
    @pytest.mark.complex
    @pytest.mark.maya
    def test_complex_deps_lock_and_install_properly(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
maya = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('lock')
            assert c.return_code == 0

            c = p.pipenv('install')
            assert c.return_code == 0

    @pytest.mark.lock
    @pytest.mark.deploy
    def test_deploy_works(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "==2.14.0"
flask = "==0.12.2"
[dev-packages]
pytest = "==3.1.1"
                """.strip()
                f.write(contents)

            p.pipenv('lock')

            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "==2.14.0"
                """.strip()
                f.write(contents)

            c = p.pipenv('install --deploy')
            assert c.return_code > 0

    @pytest.mark.install
    @pytest.mark.files
    @pytest.mark.urls
    def test_urls_work(self):

        with PipenvInstance() as p:

            p.pipenv('install https://github.com/divio/django-cms/archive/release/3.4.x.zip')
            # TODO: Improve this.
            assert p.exit_code == 1
