import json
import os
import warnings

import pytest

from pipenv._compat import TemporaryDirectory, Path
from pipenv.vendor import delegator
from pipenv.vendor import requests
from pipenv.vendor import six
from pipenv.vendor import toml

if six.PY2:
    class ResourceWarning(Warning):
        pass


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


WE_HAVE_INTERNET = check_internet()

TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pytest_runtest_setup(item):
    if item.get_marker('needs_internet') is not None and not WE_HAVE_INTERNET:
        pytest.skip('requires internet')


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
        os.environ['PYPI_VENDOR_DIR'] = os.path.join(TESTS_ROOT, 'pypi')
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
