import json
import os
import sys
import warnings

import pytest

from pipenv._compat import TemporaryDirectory, Path
from pipenv.vendor import delegator
from pipenv.vendor import requests
from pipenv.vendor import toml
from pytest_pypi.app import prepare_packages as prepare_pypi_packages
from vistir.compat import ResourceWarning, fs_str
from vistir.path import mkdir_p


warnings.simplefilter("default", category=ResourceWarning)


HAS_WARNED_GITHUB = False


def check_internet():
    try:
        # Kenneth represents the Internet LGTM.
        resp = requests.get('http://httpbin.org/ip', timeout=1.0)
        resp.raise_for_status()
    except Exception:
        warnings.warn('Cannot connect to HTTPBin...', RuntimeWarning)
        warnings.warn('Will skip tests requiring Internet', RuntimeWarning)
        return False
    return True


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


TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPI_VENDOR_DIR = os.path.join(TESTS_ROOT, 'pypi')
prepare_pypi_packages(PYPI_VENDOR_DIR)


def pytest_runtest_setup(item):
    if item.get_marker('needs_internet') is not None and not WE_HAVE_INTERNET:
        pytest.skip('requires internet')
    if item.get_marker('needs_github_ssh') is not None and not WE_HAVE_GITHUB_SSH_KEYS:
        pytest.skip('requires github ssh')


@pytest.fixture
def pathlib_tmpdir(request, tmpdir):
    yield Path(str(tmpdir))
    try:
        tmpdir.remove(ignore_errors=True)
    except Exception:
        pass


# Borrowed from pip's test runner filesystem isolation
@pytest.fixture(autouse=True)
def isolate(pathlib_tmpdir):
    """
    Isolate our tests so that things like global configuration files and the
    like do not affect our test results.
    We use an autouse function scoped fixture because we want to ensure that
    every test has it's own isolated home directory.
    """

    # Create a directory to use as our home location.
    home_dir = os.path.join(str(pathlib_tmpdir), "home")
    os.makedirs(home_dir)
    mkdir_p(os.path.join(home_dir, ".config", "git"))
    with open(os.path.join(home_dir, ".config", "git", "config"), "wb") as fp:
        fp.write(
            b"[user]\n\tname = pipenv\n\temail = pipenv@pipenv.org\n"
        )
    os.environ["GIT_CONFIG_NOSYSTEM"] = fs_str("1")
    os.environ["GIT_AUTHOR_NAME"] = fs_str("pipenv")
    os.environ["GIT_AUTHOR_EMAIL"] = fs_str("pipenv@pipenv.org")
    mkdir_p(os.path.join(home_dir, ".virtualenvs"))
    os.environ["WORKON_HOME"] = fs_str(os.path.join(home_dir, ".virtualenvs"))


WE_HAVE_INTERNET = check_internet()
WE_HAVE_GITHUB_SSH_KEYS = check_github_ssh()


class _PipenvInstance(object):
    """An instance of a Pipenv Project..."""
    def __init__(self, pypi=None, pipfile=True, chdir=False, path=None, home_dir=None):
        self.pypi = pypi
        self.original_umask = os.umask(0o007)
        self.original_dir = os.path.abspath(os.curdir)
        os.environ["PIPENV_NOSPIN"] = fs_str("1")
        os.environ["CI"] = fs_str("1")
        warnings.simplefilter("ignore", category=ResourceWarning)
        warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed.*<ssl.SSLSocket.*>")
        path = os.environ.get("PIPENV_PROJECT_DIR", None)
        if not path:
            self._path = TemporaryDirectory(suffix='-project', prefix='pipenv-')
            path = Path(self._path.name)
            try:
                self.path = str(path.resolve())
            except OSError:
                self.path = str(path.absolute())
        else:
            self._path = None
            self.path = path
        # set file creation perms
        self.pipfile_path = None
        self.chdir = chdir

        if self.pypi:
            os.environ['PIPENV_TEST_INDEX'] = fs_str('{0}/simple'.format(self.pypi.url))

        if pipfile:
            p_path = os.sep.join([self.path, 'Pipfile'])
            with open(p_path, 'a'):
                os.utime(p_path, None)

            self.chdir = False or chdir
            self.pipfile_path = p_path

    def __enter__(self):
        os.environ['PIPENV_DONT_USE_PYENV'] = fs_str('1')
        os.environ['PIPENV_IGNORE_VIRTUALENVS'] = fs_str('1')
        os.environ['PIPENV_VENV_IN_PROJECT'] = fs_str('1')
        os.environ['PIPENV_NOSPIN'] = fs_str('1')
        if self.chdir:
            os.chdir(self.path)
        return self

    def __exit__(self, *args):
        warn_msg = 'Failed to remove resource: {!r}'
        if self.chdir:
            os.chdir(self.original_dir)
        self.path = None
        if self._path:
            try:
                self._path.cleanup()
            except OSError as e:
                _warn_msg = warn_msg.format(e)
                warnings.warn(_warn_msg, ResourceWarning)
        os.umask(self.original_umask)

    def pipenv(self, cmd, block=True):
        if self.pipfile_path:
            os.environ['PIPENV_PIPFILE'] = fs_str(self.pipfile_path)
        # a bit of a hack to make sure the virtualenv is created

        with TemporaryDirectory(prefix='pipenv-', suffix='-cache') as tempdir:
            os.environ['PIPENV_CACHE_DIR'] = fs_str(tempdir.name)
            c = delegator.run('pipenv {0}'.format(cmd), block=block)
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
    yield _PipenvInstance


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
