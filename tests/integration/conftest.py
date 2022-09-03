import errno
import functools
import json
import logging
import os
import shlex
import shutil
import traceback
import sys
import warnings
from pathlib import Path
from shutil import rmtree as _rmtree
from tempfile import TemporaryDirectory

import pytest
import requests
from click.testing import CliRunner
from pytest_pypi.app import prepare_fixtures
from pytest_pypi.app import prepare_packages as prepare_pypi_packages

from pipenv.cli import cli
from pipenv.exceptions import VirtualenvActivationException
from pipenv.utils.processes import subprocess_run
from pipenv.vendor import toml, tomlkit
from pipenv.vendor.vistir.compat import fs_encode
from pipenv.vendor.vistir.contextmanagers import temp_environ
from pipenv.vendor.vistir.misc import run
from pipenv.vendor.vistir.path import (
    create_tracked_tempdir, handle_remove_readonly, mkdir_p
)


log = logging.getLogger(__name__)
warnings.simplefilter("default", category=ResourceWarning)
cli_runner = CliRunner(mix_stderr=False)


HAS_WARNED_GITHUB = False


def try_internet(url="http://httpbin.org/ip", timeout=1.5):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()


def check_internet():
    has_internet = False
    for url in ("http://httpbin.org/ip", "http://clients3.google.com/generate_204"):
        try:
            try_internet(url)
        except KeyboardInterrupt:
            warnings.warn(
                f"Skipped connecting to internet: {url}", RuntimeWarning
            )
        except Exception:
            warnings.warn(
                f"Failed connecting to internet: {url}", RuntimeWarning
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
        c = subprocess_run('ssh -o StrictHostKeyChecking=no -o CheckHostIP=no -T git@github.com', timeout=30, shell=True)
        res = True if c.returncode == 1 else False
    except KeyboardInterrupt:
        warnings.warn(
            "KeyboardInterrupt while checking GitHub ssh access", RuntimeWarning
        )
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
    c = subprocess_run("hg --help", shell=True)
    return c.returncode == 0


TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPI_VENDOR_DIR = os.path.join(TESTS_ROOT, 'pypi')
WE_HAVE_HG = check_for_mercurial()
prepare_fixtures(os.path.join(PYPI_VENDOR_DIR, "fixtures"))
prepare_pypi_packages(PYPI_VENDOR_DIR)


def pytest_runtest_setup(item):
    if item.get_closest_marker('needs_internet') is not None and not WE_HAVE_INTERNET:
        pytest.skip('requires internet')
    if item.get_closest_marker('needs_github_ssh') is not None and not WE_HAVE_GITHUB_SSH_KEYS:
        pytest.skip('requires github ssh')
    if item.get_closest_marker('needs_hg') is not None and not WE_HAVE_HG:
        pytest.skip('requires mercurial')
    if item.get_closest_marker('skip_py38') is not None and (
        sys.version_info[:2] == (3, 8)
    ):
        pytest.skip('test not applicable on python 3.8')
    if item.get_closest_marker('skip_osx') is not None and sys.platform == 'darwin':
        pytest.skip('test does not apply on OSX')
    if item.get_closest_marker('lte_py36') is not None and (
        sys.version_info >= (3, 7)
    ):
        pytest.skip('test only runs on python < 3.7')
    if item.get_closest_marker('skip_py36') is not None and (
        sys.version_info[:2] == (3, 6)
    ):
        pytest.skip('test is skipped on python 3.6')
    if item.get_closest_marker('skip_windows') is not None and (os.name == 'nt'):
        pytest.skip('test does not run on windows')


@pytest.fixture
def pathlib_tmpdir(request, tmpdir):
    yield Path(str(tmpdir))
    try:
        tmpdir.remove(ignore_errors=True)
    except Exception:
        pass


def _create_tracked_dir():
    temp_args = {"prefix": "pipenv-", "suffix": "-test"}
    temp_path = create_tracked_tempdir(**temp_args)
    return temp_path


@pytest.fixture
def vistir_tmpdir():
    temp_path = _create_tracked_dir()
    yield Path(temp_path)


@pytest.fixture()
def local_tempdir(request):
    old_temp = os.environ.get("TEMP", "")
    new_temp = Path(os.getcwd()).absolute() / "temp"
    new_temp.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = new_temp.as_posix()

    def finalize():
        os.environ['TEMP'] = old_temp
        _rmtree_func(new_temp.as_posix())

    request.addfinalizer(finalize)
    with TemporaryDirectory(dir=new_temp.as_posix()) as temp_dir:
        yield Path(temp_dir)


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
    git_config_file = os.path.join(home_dir, ".config", "git", "config")
    with open(git_config_file, "wb") as fp:
        fp.write(
            b"[user]\n\tname = pipenv\n\temail = pipenv@pipenv.org\n"
        )
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["GIT_AUTHOR_NAME"] = "pipenv"
    os.environ["GIT_AUTHOR_EMAIL"] = "pipenv@pipenv.org"
    os.environ["GIT_ASK_YESNO"] = "false"
    workon_home = create_tmpdir()
    os.environ["WORKON_HOME"] = str(workon_home)
    os.environ["HOME"] = os.path.abspath(home_dir)
    mkdir_p(os.path.join(home_dir, "projects"))
    # Ignore PIPENV_ACTIVE so that it works as under a bare environment.
    os.environ.pop("PIPENV_ACTIVE", None)
    os.environ.pop("VIRTUAL_ENV", None)


WE_HAVE_INTERNET = check_internet()
WE_HAVE_GITHUB_SSH_KEYS = False


class _Pipfile:
    def __init__(self, path):
        self.path = path
        if self.path.exists():
            self.loads()
        else:
            self.document = tomlkit.document()
        self.document["source"] = self.document.get("source", tomlkit.aot())
        self.document["requires"] = self.document.get("requires", tomlkit.table())
        self.document["packages"] = self.document.get("packages", tomlkit.table())
        self.document["dev_packages"] = self.document.get("dev_packages", tomlkit.table())
        super().__init__()

    def install(self, package, value, dev=False):
        section = "packages" if not dev else "dev_packages"
        if isinstance(value, dict):
            table = tomlkit.inline_table()
            table.update(value)
            self.document[section][package] = table
        else:
            self.document[section][package] = value
        self.write()

    def remove(self, package, dev=False):
        section = "packages" if not dev else "dev_packages"
        if not dev and package not in self.document[section]:
            if package in self.document["dev_packages"]:
                section = "dev_packages"
        del self.document[section][package]
        self.write()

    def add(self, package, value, dev=False):
        self.install(package, value, dev=dev)

    def update(self, package, value, dev=False):
        self.install(package, value, dev=dev)

    def loads(self):
        self.document = tomlkit.loads(self.path.read_text())

    def dumps(self):
        source_table = tomlkit.table()
        pypi_url = os.environ.get("PIPENV_PYPI_URL", "https://pypi.org/simple")
        source_table["url"] = os.environ.get("PIPENV_TEST_INDEX", pypi_url)
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
        fixture_pypi = os.getenv("ARTIFACT_PYPI_URL")
        if fixture_pypi:
            if pkg and not filename:
                url = f"{fixture_pypi}/artifacts/{pkg}"
            else:
                url = f"{fixture_pypi}/artifacts/{pkg}/{filename}"
            return url
        if pkg and not filename:
            return cls.get_fixture_path(file_path).as_uri()


class _PipenvInstance:
    """An instance of a Pipenv Project..."""
    def __init__(
        self, pypi=None, pipfile=True, chdir=True, path=None, capfd=None,
        venv_root=None, ignore_virtualenvs=True, venv_in_project=True, name=None
    ):
        self.index_url = os.getenv("PIPENV_TEST_INDEX")
        self.pypi = None
        self.env = {}
        self.capfd = capfd
        if pypi:
            self.pypi = pypi.url
        elif self.index_url is not None:
            self.pypi, _, _ = self.index_url.rpartition("/") if self.index_url else ""
        self.index = os.getenv("PIPENV_PYPI_INDEX")
        self.env["PYTHONWARNINGS"] = "ignore:DEPRECATION"
        if ignore_virtualenvs:
            self.env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
        if venv_root:
            self.env["VIRTUAL_ENV"] = venv_root
        if venv_in_project:
            self.env["PIPENV_VENV_IN_PROJECT"] = "1"
        else:
            self.env.pop("PIPENV_VENV_IN_PROJECT", None)

        self.original_dir = Path(__file__).parent.parent.parent
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

        if self.pypi and "PIPENV_PYPI_URL" not in os.environ:
            self.env['PIPENV_PYPI_URL'] = f'{self.pypi}'

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
        if self.pipfile_path:
            os.remove(self.pipfile_path)
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
            os.environ['PIPENV_PIPFILE'] = self.pipfile_path
        # a bit of a hack to make sure the virtualenv is created

        with TemporaryDirectory(prefix='pipenv-', suffix='-cache') as tempdir:
            cmd_args = shlex.split(cmd)
            env = {**self.env, **{'PIPENV_CACHE_DIR': tempdir}}
            self.capfd.readouterr()
            r = cli_runner.invoke(cli, cmd_args, env=env)
            r.returncode = r.exit_code
        # Pretty output for failing tests.
        out, err = self.capfd.readouterr()
        if out:
            r.stdout_bytes = r.stdout_bytes + out
        if err:
            r.stderr_bytes = r.stderr_bytes + err
        if block:
            print(f'$ pipenv {cmd}')
            print(r.stdout)
            print(r.stderr, file=sys.stderr)
            if r.exception:
                print(''.join(traceback.format_exception(*r.exc_info)), file=sys.stderr)
            if r.returncode != 0:
                print("Command failed...")

        # Where the action happens.
        return r

    @property
    def pipfile(self):
        p_path = os.sep.join([self.path, 'Pipfile'])
        with open(p_path) as f:
            return toml.loads(f.read())

    @property
    def lockfile(self):
        p_path = self.lockfile_path
        with open(p_path) as f:
            return json.loads(f.read())

    @property
    def lockfile_path(self):
        return os.sep.join([self.path, 'Pipfile.lock'])


def _rmtree_func(path, ignore_errors=True, onerror=None):
    directory = fs_encode(path)
    shutil_rmtree = _rmtree
    if onerror is None:
        onerror = handle_remove_readonly
    try:
        shutil_rmtree(directory, ignore_errors=ignore_errors, onerror=onerror)
    except (OSError, FileNotFoundError, PermissionError) as exc:
        # Ignore removal failures where the file doesn't exist
        if exc.errno != errno.ENOENT:
            raise


@pytest.fixture()
def pip_src_dir(request, vistir_tmpdir):
    old_src_dir = os.environ.get('PIP_SRC', '')
    os.environ['PIP_SRC'] = vistir_tmpdir.as_posix()

    def finalize():
        os.environ['PIP_SRC'] = old_src_dir

    request.addfinalizer(finalize)
    return request


@pytest.fixture()
def PipenvInstance(pip_src_dir, monkeypatch, pypi, capfdbinary):
    with temp_environ(), monkeypatch.context() as m:
        m.setattr(shutil, "rmtree", _rmtree_func)
        original_umask = os.umask(0o007)
        m.setenv("PIPENV_NOSPIN", "1")
        m.setenv("CI", "1")
        m.setenv('PIPENV_DONT_USE_PYENV', '1')
        m.setenv("PIPENV_TEST_INDEX", f"{pypi.url}/simple")
        m.setenv("PIPENV_PYPI_INDEX", "simple")
        m.setenv("ARTIFACT_PYPI_URL", pypi.url)
        m.setenv("PIPENV_PYPI_URL", pypi.url)
        warnings.simplefilter("ignore", category=ResourceWarning)
        warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed.*<ssl.SSLSocket.*>")
        try:
            yield functools.partial(_PipenvInstance, capfd=capfdbinary)
        finally:
            os.umask(original_umask)


@pytest.fixture()
def PipenvInstance_NoPyPI(monkeypatch, pip_src_dir, pypi, capfdbinary):
    with temp_environ(), monkeypatch.context() as m:
        m.setattr(shutil, "rmtree", _rmtree_func)
        original_umask = os.umask(0o007)
        m.setenv("PIPENV_NOSPIN", "1")
        m.setenv("CI", "1")
        m.setenv('PIPENV_DONT_USE_PYENV', '1')
        m.setenv("PIPENV_TEST_INDEX", f"{pypi.url}/simple")
        m.setenv("ARTIFACT_PYPI_URL", pypi.url)
        warnings.simplefilter("ignore", category=ResourceWarning)
        warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed.*<ssl.SSLSocket.*>")
        try:
            yield functools.partial(_PipenvInstance, capfd=capfdbinary)
        finally:
            os.umask(original_umask)


@pytest.fixture()
def testsroot():
    return TESTS_ROOT


class VirtualEnv:
    def __init__(self, name="venv", base_dir=None):
        if base_dir is None:
            base_dir = Path(_create_tracked_dir())
        self.base_dir = base_dir
        self.name = name
        self.path = (base_dir / name).resolve()

    def __enter__(self):
        self._old_environ = os.environ.copy()
        self.create()
        return self.activate()

    def __exit__(self, *args, **kwargs):
        os.environ = self._old_environ

    def create(self):
        python = Path(sys.executable).absolute().as_posix()
        cmd = [
            python, "-m", "virtualenv", self.path.absolute().as_posix()
        ]
        c = run(
            cmd, verbose=False, return_object=True, write_to_stdout=False,
            combine_stderr=False, block=True, nospin=True,
        )
        assert c.returncode == 0

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
    with VirtualEnv(base_dir=vistir_tmpdir) as venv:
        yield venv


@pytest.fixture()
def raw_venv():
    yield VirtualEnv
