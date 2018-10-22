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
from vistir.compat import ResourceWarning


warnings.filterwarnings("default", category=ResourceWarning)


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


WE_HAVE_INTERNET = check_internet()
WE_HAVE_GITHUB_SSH_KEYS = check_github_ssh()

TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPI_VENDOR_DIR = os.path.join(TESTS_ROOT, 'pypi')
prepare_pypi_packages(PYPI_VENDOR_DIR)


def pytest_runtest_setup(item):
    if item.get_marker('needs_internet') is not None and not WE_HAVE_INTERNET:
        pytest.skip('requires internet')
    if item.get_marker('needs_github_ssh') is not None and not WE_HAVE_GITHUB_SSH_KEYS:
        pytest.skip('requires github ssh')


@pytest.yield_fixture
def pathlib_tmpdir(request, tmpdir):
    yield Path(str(tmpdir))
    tmpdir.remove(ignore_errors=True)


# Borrowed from pip's test runner filesystem isolation
@pytest.fixture(autouse=True)
def isolate(pathlib_tmpdir):
    """
    Isolate our tests so that things like global configuration files and the
    like do not affect our test results.
    We use an autouse function scoped fixture because we want to ensure that
    every test has it's own isolated home directory.
    """
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed.*<ssl.SSLSocket.*>")


    # Create a directory to use as our home location.
    home_dir = os.path.join(str(pathlib_tmpdir), "home")
    os.environ["PIPENV_NOSPIN"] = "1"
    os.makedirs(home_dir)

    # Create a directory to use as a fake root
    fake_root = os.path.join(str(pathlib_tmpdir), "fake-root")
    os.makedirs(fake_root)

    # if sys.platform == 'win32':
    #     # Note: this will only take effect in subprocesses...
    #     home_drive, home_path = os.path.splitdrive(home_dir)
    #     os.environ.update({
    #         'USERPROFILE': home_dir,
    #         'HOMEDRIVE': home_drive,
    #         'HOMEPATH': home_path,
    #     })
    #     for env_var, sub_path in (
    #         ('APPDATA', 'AppData/Roaming'),
    #         ('LOCALAPPDATA', 'AppData/Local'),
    #     ):
    #         path = os.path.join(home_dir, *sub_path.split('/'))
    #         os.environ[env_var] = path
    #         os.makedirs(path)
    # else:
    #     # Set our home directory to our temporary directory, this should force
    #     # all of our relative configuration files to be read from here instead
    #     # of the user's actual $HOME directory.
    #     os.environ["HOME"] = home_dir
    #     # Isolate ourselves from XDG directories
    #     os.environ["XDG_DATA_HOME"] = os.path.join(home_dir, ".local", "share")
    #     os.environ["XDG_CONFIG_HOME"] = os.path.join(home_dir, ".config")
    #     os.environ["XDG_CACHE_HOME"] = os.path.join(home_dir, ".cache")
    #     os.environ["XDG_RUNTIME_DIR"] = os.path.join(home_dir, ".runtime")
    #     os.environ["XDG_DATA_DIRS"] = ":".join([
    #         os.path.join(fake_root, "usr", "local", "share"),
    #         os.path.join(fake_root, "usr", "share"),
    #     ])
    #     os.environ["XDG_CONFIG_DIRS"] = os.path.join(fake_root, "etc", "xdg")

    # Configure git, because without an author name/email git will complain
    # and cause test failures.
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["GIT_AUTHOR_NAME"] = "pipenv"
    os.environ["GIT_AUTHOR_EMAIL"] = "pipenv@pipenv.org"

    # We want to disable the version check from running in the tests
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "true"
    workon_home = os.path.join(home_dir, ".virtualenvs")
    os.makedirs(workon_home)
    os.environ["WORKON_HOME"] = workon_home
    project_dir = os.path.join(home_dir, "pipenv_project")
    os.makedirs(project_dir)
    os.environ["PIPENV_PROJECT_DIR"] = project_dir
    os.environ["CI"] = "1"

    # Make sure tests don't share a requirements tracker.
    os.environ.pop('PIP_REQ_TRACKER', None)

    # FIXME: Windows...
    os.makedirs(os.path.join(home_dir, ".config", "git"))
    with open(os.path.join(home_dir, ".config", "git", "config"), "wb") as fp:
        fp.write(
            b"[user]\n\tname = pipenv\n\temail = pipenv@pipenv.org\n"
        )


class _PipenvInstance(object):
    """An instance of a Pipenv Project..."""
    def __init__(self, pypi=None, pipfile=True, chdir=False, path=None):
        self.pypi = pypi
        self.original_umask = os.umask(0o007)
        self.original_dir = os.path.abspath(os.curdir)
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
            os.environ['PIPENV_TEST_INDEX'] = '{0}/simple'.format(self.pypi.url)

        if pipfile:
            p_path = os.sep.join([self.path, 'Pipfile'])
            with open(p_path, 'a'):
                os.utime(p_path, None)

            self.chdir = False or chdir
            self.pipfile_path = p_path

    def __enter__(self):
        os.environ['PIPENV_DONT_USE_PYENV'] = '1'
        os.environ['PIPENV_IGNORE_VIRTUALENVS'] = '1'
        os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
        os.environ['PIPENV_NOSPIN'] = '1'
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
            os.environ['PIPENV_PIPFILE'] = self.pipfile_path
        # a bit of a hack to make sure the virtualenv is created

        with TemporaryDirectory(prefix='pipenv-', suffix='-cache') as tempdir:
            os.environ['PIPENV_CACHE_DIR'] = tempdir.name
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


@pytest.fixture(scope='module')
def pip_src_dir(request):
    old_src_dir = os.environ.get('PIP_SRC', '')
    new_src_dir = TemporaryDirectory(prefix='pipenv-', suffix='-testsrc')
    os.environ['PIP_SRC'] = new_src_dir.name

    def finalize():
        new_src_dir.cleanup()
        os.environ['PIP_SRC'] = old_src_dir

    request.addfinalizer(finalize)
    return request


@pytest.fixture()
def testsroot():
    return TESTS_ROOT
