# -*- coding=utf-8 -*-
import json
import os
import sys
import warnings

import pytest

from vistir.compat import ResourceWarning, fs_str
from vistir.contextmanagers import temp_environ
from vistir.path import mkdir_p, create_tracked_tempdir

from pipenv._compat import Path, TemporaryDirectory
from pipenv.exceptions import VirtualenvActivationException
from pipenv.vendor import delegator, requests, toml, tomlkit
from pytest_pypi.app import prepare_fixtures
from pytest_pypi.app import prepare_packages as prepare_pypi_packages


warnings.simplefilter("default", category=ResourceWarning)


HAS_WARNED_GITHUB = False


def try_internet(url="http://httpbin.org/ip", timeout=1.5):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()


def check_internet():
    has_internet = False
    for url in ("http://httpbin.org/ip", "http://clients3.google.com/generate_204"):
        try:
            try_internet(url)
        except Exception:
            warnings.warn(
                "Failed connecting to internet: {0}".format(url), RuntimeWarning
            )
        else:
            has_internet = True
            break
    return has_internet


def check_github_ssh():
    res = False
    try:
        # `ssh -T git@github.com` will return successfully with return_code==1
        # and message 'Hi <username>! You've successfully authenticated, but
        # GitHub does not provide shell access.' if ssh keys are available and
        # registered with GitHub. Otherwise, the command will fail with
        # return_code=255 and say 'Permission denied (publickey).'
        c = delegator.run('ssh -T git@github.com')
        res = True if c.return_code == 1 else False
    except Exception:
        pass
    global HAS_WARNED_GITHUB
    if not res and not HAS_WARNED_GITHUB:
        warnings.warn(
            'Cannot connect to GitHub via SSH', RuntimeWarning
        )
        warnings.warn(
            'Will skip tests requiring SSH access to GitHub', RuntimeWarning
        )
        HAS_WARNED_GITHUB = True
    return res


def check_for_mercurial():
    c = delegator.run("hg --help")
    if c.return_code != 0:
        return False
    else:
        return True


TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPI_VENDOR_DIR = os.path.join(TESTS_ROOT, 'pypi')
WE_HAVE_HG = check_for_mercurial()
prepare_pypi_packages(PYPI_VENDOR_DIR)
prepare_fixtures(os.path.join(PYPI_VENDOR_DIR, "fixtures"))


def pytest_runtest_setup(item):
    if item.get_marker('needs_internet') is not None and not WE_HAVE_INTERNET:
        pytest.skip('requires internet')
    if item.get_marker('needs_github_ssh') is not None and not WE_HAVE_GITHUB_SSH_KEYS:
        pytest.skip('requires github ssh')
    if item.get_marker('needs_hg') is not None and not WE_HAVE_HG:
        pytest.skip('requires mercurial')
    if item.get_marker('skip_py27_win') is not None and (
        sys.version_info[:2] <= (2, 7) and os.name == "nt"
    ):
        pytest.skip('must use python > 2.7 on windows')
    if item.get_marker('py3_only') is not None and (
        sys.version_info < (3, 0)
    ):
        pytest.skip('test only runs on python 3')
    if item.get_marker('lte_py36') is not None and (
        sys.version_info >= (3, 7)
    ):
        pytest.skip('test only runs on python < 3.7')


@pytest.fixture
def pathlib_tmpdir(request, tmpdir):
    yield Path(str(tmpdir))
    try:
        tmpdir.remove(ignore_errors=True)
    except Exception:
        pass


def _create_tracked_dir():
    tmp_location = os.environ.get("TEMP", os.environ.get("TMP"))
    temp_args = {"prefix": "pipenv-", "suffix": "-test"}
    if tmp_location is not None:
        temp_args["dir"] = tmp_location
    temp_path = create_tracked_tempdir(**temp_args)
    return temp_path


@pytest.fixture
def vistir_tmpdir():
    temp_path = _create_tracked_dir()
    yield Path(temp_path)


@pytest.fixture(name='create_tmpdir')
def vistir_tmpdir_factory():

    def create_tmpdir():
        return Path(_create_tracked_dir())

    yield create_tmpdir


# Borrowed from pip's test runner filesystem isolation
@pytest.fixture(autouse=True)
def isolate(create_tmpdir):
    """
    Isolate our tests so that things like global configuration files and the
    like do not affect our test results.
    We use an autouse function scoped fixture because we want to ensure that
    every test has it's own isolated home directory.
    """

    # Create a directory to use as our home location.
    home_dir = os.path.join(str(create_tmpdir()), "home")
    os.makedirs(home_dir)
    mkdir_p(os.path.join(home_dir, ".config", "git"))
    with open(os.path.join(home_dir, ".config", "git", "config"), "wb") as fp:
        fp.write(
            b"[user]\n\tname = pipenv\n\temail = pipenv@pipenv.org\n"
        )
    os.environ["GIT_CONFIG_NOSYSTEM"] = fs_str("1")
    os.environ["GIT_AUTHOR_NAME"] = fs_str("pipenv")
    os.environ["GIT_AUTHOR_EMAIL"] = fs_str("pipenv@pipenv.org")
    workon_home = create_tmpdir()
    os.environ["WORKON_HOME"] = fs_str(str(workon_home))
    os.environ["HOME"] = home_dir
    mkdir_p(os.path.join(home_dir, "projects"))
    # Ignore PIPENV_ACTIVE so that it works as under a bare environment.
    os.environ.pop("PIPENV_ACTIVE", None)
    os.environ.pop("VIRTUAL_ENV", None)
    global WE_HAVE_GITHUB_SSH_KEYS
    WE_HAVE_GITHUB_SSH_KEYS = check_github_ssh()


WE_HAVE_INTERNET = check_internet()
WE_HAVE_GITHUB_SSH_KEYS = check_github_ssh()


class _Pipfile(object):
    def __init__(self, path):
        self.path = path
        self.document = tomlkit.document()
        self.document["source"] = tomlkit.aot()
        self.document["requires"] = tomlkit.table()
        self.document["packages"] = tomlkit.table()
        self.document["dev_packages"] = tomlkit.table()

    def install(self, package, value, dev=False):
        section = "packages" if not dev else "dev_packages"
        if isinstance(value, dict):
            table = tomlkit.inline_table()
            table.update(value)
            self.document[section][package] = table
        else:
            self.document[section][package] = value
        self.write()

    def add(self, package, value, dev=False):
        self.install(package, value, dev=dev)

    def loads(self):
        self.document = tomlkit.loads(self.path.read_text())

    def dumps(self):
        source_table = tomlkit.table()
        source_table["url"] = os.environ.get("PIPENV_TEST_INDEX")
        source_table["verify_ssl"] = False
        source_table["name"] = "pipenv_test_index"
        self.document["source"].append(source_table)
        return tomlkit.dumps(self.document)

    def write(self):
        self.path.write_text(self.dumps())

    @classmethod
    def get_fixture_path(cls, path):
        return Path(__file__).absolute().parent.parent / "test_artifacts" / path

    @classmethod
    def get_url(cls, pkg=None, filename=None):
        pypi = os.environ.get("PIPENV_PYPI_URL")
        if not pkg and not filename:
            return pypi if pypi else "https://pypi.org/"
        file_path = filename
        if pkg and filename:
            file_path = os.path.join(pkg, filename)
        if filename and not pkg:
            pkg = os.path.basename(filename)
        if pypi:
            if pkg and not filename:
                url = "{0}/artifacts/{1}".format(pypi, pkg)
            else:
                url = "{0}/artifacts/{1}/{2}".format(pypi, pkg, filename)
            return url
        if pkg and not filename:
            return cls.get_fixture_path(file_path).as_uri()


class _PipenvInstance(object):
    """An instance of a Pipenv Project..."""
    def __init__(
        self, pypi=None, pipfile=True, chdir=False, path=None, home_dir=None,
        venv_root=None, ignore_virtualenvs=True, venv_in_project=True, name=None
    ):
        self.pypi = pypi
        if ignore_virtualenvs:
            os.environ["PIPENV_IGNORE_VIRTUALENVS"] = fs_str("1")
        if venv_root:
            os.environ["VIRTUAL_ENV"] = venv_root
        if venv_in_project:
            os.environ["PIPENV_VENV_IN_PROJECT"] = fs_str("1")
        else:
            os.environ.pop("PIPENV_VENV_IN_PROJECT", None)

        self.original_dir = os.path.abspath(os.curdir)
        path = path if path else os.environ.get("PIPENV_PROJECT_DIR", None)
        if name is not None:
            path = Path(os.environ["HOME"]) / "projects" / name
            path.mkdir(exist_ok=True)
        if not path:
            path = TemporaryDirectory(suffix='-project', prefix='pipenv-')
        if isinstance(path, TemporaryDirectory):
            self._path = path
            path = Path(self._path.name)
            try:
                self.path = str(path.resolve())
            except OSError:
                self.path = str(path.absolute())
        elif isinstance(path, Path):
            self._path = path
            try:
                self.path = str(path.resolve())
            except OSError:
                self.path = str(path.absolute())
        else:
            self._path = path
            self.path = path
        # set file creation perms
        self.pipfile_path = None
        self.chdir = chdir

        if self.pypi:
            os.environ['PIPENV_PYPI_URL'] = fs_str('{0}'.format(self.pypi.url))
            os.environ['PIPENV_TEST_INDEX'] = fs_str('{0}/simple'.format(self.pypi.url))

        if pipfile:
            p_path = os.sep.join([self.path, 'Pipfile'])
            with open(p_path, 'a'):
                os.utime(p_path, None)

            self.chdir = False or chdir
            self.pipfile_path = p_path
            self._pipfile = _Pipfile(Path(p_path))

    def __enter__(self):
        if self.chdir:
            os.chdir(self.path)
        return self

    def __exit__(self, *args):
        warn_msg = 'Failed to remove resource: {!r}'
        if self.chdir:
            os.chdir(self.original_dir)
        self.path = None
        if self._path and getattr(self._path, "cleanup", None):
            try:
                self._path.cleanup()
            except OSError as e:
                _warn_msg = warn_msg.format(e)
                warnings.warn(_warn_msg, ResourceWarning)

    def pipenv(self, cmd, block=True):
        if self.pipfile_path and os.path.isfile(self.pipfile_path):
            os.environ['PIPENV_PIPFILE'] = fs_str(self.pipfile_path)
        # a bit of a hack to make sure the virtualenv is created

        with TemporaryDirectory(prefix='pipenv-', suffix='-cache') as tempdir:
            os.environ['PIPENV_CACHE_DIR'] = fs_str(tempdir.name)
            c = delegator.run('pipenv {0}'.format(cmd), block=block,
                              cwd=os.path.abspath(self.path))
            if 'PIPENV_CACHE_DIR' in os.environ:
                del os.environ['PIPENV_CACHE_DIR']

        if 'PIPENV_PIPFILE' in os.environ:
            del os.environ['PIPENV_PIPFILE']

        # Pretty output for failing tests.
        if block:
            print('$ pipenv {0}'.format(cmd))
            print(c.out)
            print(c.err)
            if c.return_code != 0:
                print("Command failed...")

        # Where the action happens.
        return c

    @property
    def pipfile(self):
        p_path = os.sep.join([self.path, 'Pipfile'])
        with open(p_path, 'r') as f:
            return toml.loads(f.read())

    @property
    def lockfile(self):
        p_path = self.lockfile_path
        with open(p_path, 'r') as f:
            return json.loads(f.read())

    @property
    def lockfile_path(self):
        return os.sep.join([self.path, 'Pipfile.lock'])


@pytest.fixture()
def PipenvInstance():
    with temp_environ():
        original_umask = os.umask(0o007)
        os.environ["PIPENV_NOSPIN"] = fs_str("1")
        os.environ["CI"] = fs_str("1")
        os.environ['PIPENV_DONT_USE_PYENV'] = fs_str('1')
        warnings.simplefilter("ignore", category=ResourceWarning)
        warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed.*<ssl.SSLSocket.*>")
        try:
            yield _PipenvInstance
        finally:
            os.umask(original_umask)


@pytest.fixture(autouse=True)
def pip_src_dir(request, pathlib_tmpdir):
    old_src_dir = os.environ.get('PIP_SRC', '')
    os.environ['PIP_SRC'] = pathlib_tmpdir.as_posix()

    def finalize():
        os.environ['PIP_SRC'] = fs_str(old_src_dir)

    request.addfinalizer(finalize)
    return request


@pytest.fixture()
def testsroot():
    return TESTS_ROOT


class VirtualEnv(object):
    def __init__(self, name="venv", base_dir=None):
        if base_dir is None:
            base_dir = Path(_create_tracked_dir())
        self.base_dir = base_dir
        self.name = name
        self.path = base_dir / name

    def __enter__(self):
        self._old_environ = os.environ.copy()
        self.create()
        return self.activate()

    def __exit__(self, *args, **kwargs):
        os.environ = self._old_environ

    def create(self):
        python = Path(sys.executable).as_posix()
        cmd = "{0} -m virtualenv {1}".format(python, self.path.as_posix())
        c = delegator.run(cmd, block=True)
        assert c.return_code == 0

    def activate(self):
        script_path = "Scripts" if os.name == "nt" else "bin"
        activate_this = self.path / script_path / "activate_this.py"
        if activate_this.exists():
            with open(str(activate_this)) as f:
                code = compile(f.read(), str(activate_this), "exec")
                exec(code, dict(__file__=str(activate_this)))
            os.environ["VIRTUAL_ENV"] = str(self.path)
            return self.path
        else:
            raise VirtualenvActivationException("Can't find the activate_this.py script.")


@pytest.fixture()
def virtualenv(vistir_tmpdir):
    with temp_environ(), VirtualEnv(base_dir=vistir_tmpdir) as venv:
        yield venv


@pytest.fixture()
def raw_venv():
    yield VirtualEnv
