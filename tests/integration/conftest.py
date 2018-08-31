import json
import os
import warnings

import pytest

from pipenv._compat import TemporaryDirectory, Path
from pipenv.vendor import delegator
from pipenv.vendor import requests
from pipenv.vendor import six
from pipenv.vendor import toml
from pytest_pypi.app import prepare_packages as prepare_pypi_packages

if six.PY2:
    class ResourceWarning(Warning):
        pass


HAS_WARNED_GITHUB = False


def check_internet():
    try:
        # Kenneth represents the Internet LGTM.
        resp = requests.get('http://httpbin.org/ip', timeout=1.0)
        resp.raise_for_status()
    except Exception:
        warnings.warn('Cannot connect to HTTPBin...', ResourceWarning)
        warnings.warn('Will skip tests requiring Internet', ResourceWarning)
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
            'Cannot connect to GitHub via SSH', ResourceWarning
        )
        warnings.warn(
            'Will skip tests requiring SSH access to GitHub', ResourceWarning
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


class _PipenvInstance(object):
    """An instance of a Pipenv Project..."""
    def __init__(self, pypi=None, pipfile=True, chdir=False):
        self.pypi = pypi
        self.original_umask = os.umask(0o007)
        self.original_dir = os.path.abspath(os.curdir)
        self._path = TemporaryDirectory(suffix='-project', prefix='pipenv-')
        path = Path(self._path.name)
        try:
            self.path = str(path.resolve())
        except OSError:
            self.path = str(path.absolute())
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
        if self.chdir:
            os.chdir(self.path)
        return self

    def __exit__(self, *args):
        warn_msg = 'Failed to remove resource: {!r}'
        if self.chdir:
            os.chdir(self.original_dir)
        self.path = None
        try:
            self._path.cleanup()
        except OSError as e:
            _warn_msg = warn_msg.format(e)
            warnings.warn(_warn_msg, ResourceWarning)
        finally:
            os.umask(self.original_umask)

    def pipenv(self, cmd, block=True):
        if self.pipfile_path:
            os.environ['PIPENV_PIPFILE'] = self.pipfile_path

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
    return _PipenvInstance


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
