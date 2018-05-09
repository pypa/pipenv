import os
import sys
import locale
from codecs import getwriter
from contextlib import contextmanager
from subprocess import check_call, Popen, PIPE
from collections import namedtuple
from functools import partial, wraps
try:
    from pathlib import Path
except ImportError:
    from pipenv.vendor.pathlib2 import Path
from tempfile import NamedTemporaryFile as _ntf
try:
    from shutil import which
except ImportError:
    from shutilwhich import which

py2 = sys.version_info[0] == 2
windows = sys.platform == 'win32'

if py2 or windows:
    locale.setlocale(locale.LC_CTYPE, '')

encoding = locale.getlocale()[1] or 'ascii'

if py2:
    @wraps(_ntf)
    def NamedTemporaryFile(mode):
        return getwriter(encoding)(_ntf(mode))

    def to_unicode(x):
        return x.decode(encoding)
else:
    NamedTemporaryFile = _ntf
    to_unicode = str

def check_path():
    parent = os.path.dirname
    return parent(parent(which('python'))) == os.environ['VIRTUAL_ENV']


def resolve_path(f):
    def call(cmd, **kwargs):
        ex = cmd[0]
        ex = which(ex) or ex
        return f([ex] + list(cmd[1:]), **kwargs)  # list-conversion is required in case `cmd` is a tuple
    return call

if windows:
    check_call = resolve_path(check_call)
    Popen = resolve_path(Popen)

Result = namedtuple('Result', 'returncode out err')


# TODO: it's better to fail early, and thus I'd need to check the exit code, but it'll
# need a refactoring of a couple of tests
def invoke(*args, **kwargs):
    inp = kwargs.pop('inp', '').encode(encoding)
    popen = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE, **kwargs)
    out, err = [o.strip().decode(encoding) for o in popen.communicate(inp)]
    return Result(popen.returncode, out, err)


invoke_pew = partial(invoke, 'pew')

env_bin_dir = 'bin' if sys.platform != 'win32' else 'Scripts'


def expandpath(path):
    return Path(os.path.expanduser(os.path.expandvars(path)))


def own(path):
    if sys.platform == 'win32':
        # Even if run by an administrator, the permissions will be set
        # correctly on Windows, no need to check
        return True
    while not path.exists():
        path = path.parent
    return path.stat().st_uid == os.getuid()


@contextmanager
def temp_environ():
    environ = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(environ)
