# -*- coding: utf-8 -*-

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Test utilities.
"""

from __future__ import print_function
import atexit
import contextlib
import errno
import functools
import ipaddress  # python >= 3.3 / requires "pip install ipaddress"
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import warnings
from socket import AF_INET
from socket import SOCK_DGRAM
from socket import SOCK_STREAM

try:
    from unittest import mock  # py3
except ImportError:
    import mock  # NOQA - requires "pip install mock"

import psutil
from psutil import LINUX
from psutil import POSIX
from psutil import WINDOWS
from psutil._compat import PY3
from psutil._compat import unicode
from psutil._compat import which

if sys.version_info < (2, 7):
    import unittest2 as unittest  # requires "pip install unittest2"
else:
    import unittest
if sys.version_info >= (3, 4):
    import enum
else:
    enum = None

if PY3:
    import importlib
    # python <=3.3
    if not hasattr(importlib, 'reload'):
        import imp as importlib
else:
    import imp as importlib


__all__ = [
    # constants
    'APPVEYOR', 'DEVNULL', 'GLOBAL_TIMEOUT', 'MEMORY_TOLERANCE', 'NO_RETRIES',
    'PYPY', 'PYTHON', 'RLIMIT_SUPPORT', 'ROOT_DIR', 'SCRIPTS_DIR',
    'TESTFILE_PREFIX', 'TESTFN', 'TESTFN_UNICODE', 'TOX', 'TRAVIS',
    'VALID_PROC_STATUSES', 'VERBOSITY',
    # classes
    'ThreadTask'
    # test utils
    'check_connection_ntuple', 'check_net_address', 'unittest', 'cleanup',
    'skip_on_access_denied', 'skip_on_not_implemented', 'retry_before_failing',
    'run_test_module_by_name',
    # fs utils
    'chdir', 'safe_rmpath', 'create_exe',
    # subprocesses
    'pyrun', 'reap_children', 'get_test_subprocess',
    # os
    'get_winver', 'get_kernel_version',
    # sync primitives
    'call_until', 'wait_for_pid', 'wait_for_file',
    # others
    'warn', 'decode_path', 'encode_path',
]


# ===================================================================
# --- constants
# ===================================================================


# conf for retry_before_failing() decorator
NO_RETRIES = 10
# bytes tolerance for OS memory related tests
MEMORY_TOLERANCE = 500 * 1024  # 500KB
# the timeout used in functions which have to wait
GLOBAL_TIMEOUT = 3

AF_INET6 = getattr(socket, "AF_INET6")
AF_UNIX = getattr(socket, "AF_UNIX", None)
PYTHON = os.path.realpath(sys.executable)
DEVNULL = open(os.devnull, 'r+')

TESTFILE_PREFIX = '$testfn'
TESTFN = os.path.join(os.path.realpath(os.getcwd()), TESTFILE_PREFIX)
_TESTFN = TESTFN + '-internal'
TESTFN_UNICODE = TESTFN + "-ƒőő"
if not PY3:
    try:
        TESTFN_UNICODE = unicode(TESTFN, sys.getfilesystemencoding())
    except UnicodeDecodeError:
        TESTFN_UNICODE = TESTFN + "-???"

TOX = os.getenv('TOX') or '' in ('1', 'true')
PYPY = '__pypy__' in sys.builtin_module_names

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        '..', '..'))
SCRIPTS_DIR = os.path.join(ROOT_DIR, 'scripts')

WIN_VISTA = (6, 0, 0) if WINDOWS else None
VALID_PROC_STATUSES = [getattr(psutil, x) for x in dir(psutil)
                       if x.startswith('STATUS_')]
# whether we're running this test suite on Travis (https://travis-ci.org/)
TRAVIS = bool(os.environ.get('TRAVIS'))
# whether we're running this test suite on Appveyor for Windows
# (http://www.appveyor.com/)
APPVEYOR = bool(os.environ.get('APPVEYOR'))

if TRAVIS or APPVEYOR:
    GLOBAL_TIMEOUT = GLOBAL_TIMEOUT * 4
VERBOSITY = 1 if os.getenv('SILENT') or TOX else 2

# assertRaisesRegexp renamed to assertRaisesRegex in 3.3; add support
# for the new name
if not hasattr(unittest.TestCase, 'assertRaisesRegex'):
    unittest.TestCase.assertRaisesRegex = unittest.TestCase.assertRaisesRegexp


# ===================================================================
# --- classes
# ===================================================================


class ThreadTask(threading.Thread):
    """A thread object used for running process thread tests."""

    def __init__(self):
        threading.Thread.__init__(self)
        self._running = False
        self._interval = None
        self._flag = threading.Event()

    def __repr__(self):
        name = self.__class__.__name__
        return '<%s running=%s at %#x>' % (name, self._running, id(self))

    def start(self, interval=0.001):
        """Start thread and keep it running until an explicit
        stop() request. Polls for shutdown every 'timeout' seconds.
        """
        if self._running:
            raise ValueError("already started")
        self._interval = interval
        threading.Thread.start(self)
        self._flag.wait()

    def run(self):
        self._running = True
        self._flag.set()
        while self._running:
            time.sleep(self._interval)

    def stop(self):
        """Stop thread execution and and waits until it is stopped."""
        if not self._running:
            raise ValueError("already stopped")
        self._running = False
        self.join()


# ===================================================================
# --- subprocesses
# ===================================================================


_subprocesses_started = set()


def get_test_subprocess(cmd=None, **kwds):
    """Return a subprocess.Popen object to use in tests.
    By default stdout and stderr are redirected to /dev/null and the
    python interpreter is used as test process.
    It also attemps to make sure the process is in a reasonably
    initialized state.
    """
    kwds.setdefault("stdin", DEVNULL)
    kwds.setdefault("stdout", DEVNULL)
    if cmd is None:
        safe_rmpath(_TESTFN)
        pyline = "from time import sleep;"
        pyline += "open(r'%s', 'w').close();" % _TESTFN
        pyline += "sleep(60)"
        cmd = [PYTHON, "-c", pyline]
        sproc = subprocess.Popen(cmd, **kwds)
        wait_for_file(_TESTFN, delete_file=True, empty=True)
    else:
        sproc = subprocess.Popen(cmd, **kwds)
        wait_for_pid(sproc.pid)
    _subprocesses_started.add(sproc)
    return sproc


_testfiles = []


def pyrun(src):
    """Run python 'src' code in a separate interpreter.
    Return interpreter subprocess.
    """
    if PY3:
        src = bytes(src, 'ascii')
    with tempfile.NamedTemporaryFile(
            prefix=TESTFILE_PREFIX, delete=False) as f:
        _testfiles.append(f.name)
        f.write(src)
        f.flush()
        subp = get_test_subprocess([PYTHON, f.name], stdout=None,
                                   stderr=None)
        wait_for_pid(subp.pid)
        return subp


def sh(cmdline, stdout=subprocess.PIPE, stderr=subprocess.PIPE):
    """run cmd in a subprocess and return its output.
    raises RuntimeError on error.
    """
    p = subprocess.Popen(cmdline, shell=True, stdout=stdout, stderr=stderr)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(stderr)
    if stderr:
        if PY3:
            stderr = str(stderr, sys.stderr.encoding or
                         sys.getfilesystemencoding())
        warn(stderr)
    if PY3:
        stdout = str(stdout, sys.stdout.encoding or
                     sys.getfilesystemencoding())
    return stdout.strip()


def reap_children(recursive=False):
    """Terminate and wait() any subprocess started by this test suite
    and ensure that no zombies stick around to hog resources and
    create problems  when looking for refleaks.

    If resursive is True it also tries to terminate and wait()
    all grandchildren started by this process.
    """
    # Get the children here, before terminating the children sub
    # processes as we don't want to lose the intermediate reference
    # in case of grandchildren.
    if recursive:
        children = psutil.Process().children(recursive=True)
    else:
        children = []

    # Terminate subprocess.Popen instances "cleanly" by closing their
    # fds and wiat()ing for them in order to avoid zombies.
    subprocs = _subprocesses_started.copy()
    _subprocesses_started.clear()
    for subp in subprocs:
        try:
            subp.terminate()
        except OSError as err:
            if err.errno != errno.ESRCH:
                raise
        if subp.stdout:
            subp.stdout.close()
        if subp.stderr:
            subp.stderr.close()
        try:
            # Flushing a BufferedWriter may raise an error.
            if subp.stdin:
                subp.stdin.close()
        finally:
            # Wait for the process to terminate, to avoid zombies.
            try:
                subp.wait()
            except OSError as err:
                if err.errno != errno.ECHILD:
                    raise

    # Terminates grandchildren.
    if children:
        for p in children:
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                pass
        gone, alive = psutil.wait_procs(children, timeout=GLOBAL_TIMEOUT)
        for p in alive:
            warn("couldn't terminate process %r; attempting kill()" % p)
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(alive, timeout=GLOBAL_TIMEOUT)
        if alive:
            for p in alive:
                warn("process %r survived kill()" % p)


# ===================================================================
# --- OS
# ===================================================================


if not POSIX:
    def get_kernel_version():
        return ()
else:
    def get_kernel_version():
        """Return a tuple such as (2, 6, 36)."""
        s = ""
        uname = os.uname()[2]
        for c in uname:
            if c.isdigit() or c == '.':
                s += c
            else:
                break
        if not s:
            raise ValueError("can't parse %r" % uname)
        minor = 0
        micro = 0
        nums = s.split('.')
        major = int(nums[0])
        if len(nums) >= 2:
            minor = int(nums[1])
        if len(nums) >= 3:
            micro = int(nums[2])
        return (major, minor, micro)


if LINUX:
    RLIMIT_SUPPORT = get_kernel_version() >= (2, 6, 36)
else:
    RLIMIT_SUPPORT = False


if not WINDOWS:
    def get_winver():
        raise NotImplementedError("not a Windows OS")
else:
    def get_winver():
        wv = sys.getwindowsversion()
        if hasattr(wv, 'service_pack_major'):  # python >= 2.7
            sp = wv.service_pack_major or 0
        else:
            r = re.search("\s\d$", wv[4])
            if r:
                sp = int(r.group(0))
            else:
                sp = 0
        return (wv[0], wv[1], sp)


# ===================================================================
# --- sync primitives
# ===================================================================


class retry(object):
    """A retry decorator."""

    def __init__(self,
                 exception=Exception,
                 timeout=None,
                 retries=None,
                 interval=0.001,
                 logfun=lambda s: print(s, file=sys.stderr),
                 ):
        if timeout and retries:
            raise ValueError("timeout and retries args are mutually exclusive")
        self.exception = exception
        self.timeout = timeout
        self.retries = retries
        self.interval = interval
        self.logfun = logfun

    def __iter__(self):
        if self.timeout:
            stop_at = time.time() + self.timeout
            while time.time() < stop_at:
                yield
        elif self.retries:
            for _ in range(self.retries):
                yield
        else:
            while True:
                yield

    def sleep(self):
        if self.interval is not None:
            time.sleep(self.interval)

    def __call__(self, fun):
        @functools.wraps(fun)
        def wrapper(*args, **kwargs):
            exc = None
            for _ in self:
                try:
                    return fun(*args, **kwargs)
                except self.exception as _:
                    exc = _
                    if self.logfun is not None:
                        self.logfun(exc)
                    self.sleep()
            else:
                if PY3:
                    raise exc
                else:
                    raise

        # This way the user of the decorated function can change config
        # parameters.
        wrapper.decorator = self
        return wrapper


@retry(exception=psutil.NoSuchProcess, logfun=None, timeout=GLOBAL_TIMEOUT,
       interval=0.001)
def wait_for_pid(pid):
    """Wait for pid to show up in the process list then return.
    Used in the test suite to give time the sub process to initialize.
    """
    psutil.Process(pid)
    if WINDOWS:
        # give it some more time to allow better initialization
        time.sleep(0.01)


@retry(exception=(EnvironmentError, AssertionError), logfun=None,
       timeout=GLOBAL_TIMEOUT, interval=0.001)
def wait_for_file(fname, delete_file=True, empty=False):
    """Wait for a file to be written on disk with some content."""
    with open(fname, "rb") as f:
        data = f.read()
    if not empty:
        assert data
    if delete_file:
        os.remove(fname)
    return data


@retry(exception=AssertionError, logfun=None, timeout=GLOBAL_TIMEOUT,
       interval=0.001)
def call_until(fun, expr):
    """Keep calling function for timeout secs and exit if eval()
    expression is True.
    """
    ret = fun()
    assert eval(expr)
    return ret


# ===================================================================
# --- fs
# ===================================================================


def safe_rmpath(path):
    "Convenience function for removing temporary test files or dirs"
    try:
        st = os.stat(path)
        if stat.S_ISDIR(st.st_mode):
            os.rmdir(path)
        else:
            os.remove(path)
    except OSError as err:
        if err.errno != errno.ENOENT:
            raise


def safe_mkdir(dir):
    "Convenience function for creating a directory"
    try:
        os.mkdir(dir)
    except OSError as err:
        if err.errno != errno.EEXIST:
            raise


@contextlib.contextmanager
def chdir(dirname):
    "Context manager which temporarily changes the current directory."
    curdir = os.getcwd()
    try:
        os.chdir(dirname)
        yield
    finally:
        os.chdir(curdir)


def create_exe(outpath, c_code=None):
    """Creates an executable file in the given location."""
    assert not os.path.exists(outpath), outpath
    if which("gcc"):
        if c_code is None:
            c_code = textwrap.dedent(
                """
                #include <unistd.h>
                int main() {
                    pause();
                    return 1;
                }
                """)
        with tempfile.NamedTemporaryFile(
                suffix='.c', delete=False, mode='wt') as f:
            f.write(c_code)
        try:
            subprocess.check_call(["gcc", f.name, "-o", outpath])
        finally:
            safe_rmpath(f.name)
    else:
        # fallback - use python's executable
        if c_code is not None:
            raise ValueError(
                "can't specify c_code arg as gcc is not installed")
        shutil.copyfile(sys.executable, outpath)
        if POSIX:
            st = os.stat(outpath)
            os.chmod(outpath, st.st_mode | stat.S_IEXEC)


# ===================================================================
# --- testing
# ===================================================================


class TestCase(unittest.TestCase):

    def __str__(self):
        return "%s.%s.%s" % (
            self.__class__.__module__, self.__class__.__name__,
            self._testMethodName)


# Hack that overrides default unittest.TestCase in order to print
# a full path representation of the single unit tests being run.
unittest.TestCase = TestCase


def retry_before_failing(retries=NO_RETRIES):
    """Decorator which runs a test function and retries N times before
    actually failing.
    """
    return retry(exception=AssertionError, timeout=None, retries=retries)


def run_test_module_by_name(name):
    # testmodules = [os.path.splitext(x)[0] for x in os.listdir(HERE)
    #                if x.endswith('.py') and x.startswith('test_')]
    name = os.path.splitext(os.path.basename(name))[0]
    suite = unittest.TestSuite()
    suite.addTest(unittest.defaultTestLoader.loadTestsFromName(name))
    result = unittest.TextTestRunner(verbosity=VERBOSITY).run(suite)
    success = result.wasSuccessful()
    sys.exit(0 if success else 1)


def skip_on_access_denied(only_if=None):
    """Decorator to Ignore AccessDenied exceptions."""
    def decorator(fun):
        @functools.wraps(fun)
        def wrapper(*args, **kwargs):
            try:
                return fun(*args, **kwargs)
            except psutil.AccessDenied:
                if only_if is not None:
                    if not only_if:
                        raise
                msg = "%r was skipped because it raised AccessDenied" \
                      % fun.__name__
                raise unittest.SkipTest(msg)
        return wrapper
    return decorator


def skip_on_not_implemented(only_if=None):
    """Decorator to Ignore NotImplementedError exceptions."""
    def decorator(fun):
        @functools.wraps(fun)
        def wrapper(*args, **kwargs):
            try:
                return fun(*args, **kwargs)
            except NotImplementedError:
                if only_if is not None:
                    if not only_if:
                        raise
                msg = "%r was skipped because it raised NotImplementedError" \
                      % fun.__name__
                raise unittest.SkipTest(msg)
        return wrapper
    return decorator


def check_net_address(addr, family):
    """Check a net address validity. Supported families are IPv4,
    IPv6 and MAC addresses.
    """
    if enum and PY3:
        assert isinstance(family, enum.IntEnum), family
    if family == AF_INET:
        octs = [int(x) for x in addr.split('.')]
        assert len(octs) == 4, addr
        for num in octs:
            assert 0 <= num <= 255, addr
        if not PY3:
            addr = unicode(addr)
        ipaddress.IPv4Address(addr)
    elif family == AF_INET6:
        assert isinstance(addr, str), addr
        if not PY3:
            addr = unicode(addr)
        ipaddress.IPv6Address(addr)
    elif family == psutil.AF_LINK:
        assert re.match('([a-fA-F0-9]{2}[:|\-]?){6}', addr) is not None, addr
    else:
        raise ValueError("unknown family %r", family)


def check_connection_ntuple(conn):
    """Check validity of a connection namedtuple."""
    valid_conn_states = [getattr(psutil, x) for x in dir(psutil) if
                         x.startswith('CONN_')]
    assert conn[0] == conn.fd
    assert conn[1] == conn.family
    assert conn[2] == conn.type
    assert conn[3] == conn.laddr
    assert conn[4] == conn.raddr
    assert conn[5] == conn.status
    assert conn.type in (SOCK_STREAM, SOCK_DGRAM), repr(conn.type)
    assert conn.family in (AF_INET, AF_INET6, AF_UNIX), repr(conn.family)
    assert conn.status in valid_conn_states, conn.status

    # check IP address and port sanity
    for addr in (conn.laddr, conn.raddr):
        if not addr:
            continue
        if conn.family in (AF_INET, AF_INET6):
            assert isinstance(addr, tuple), addr
            ip, port = addr
            assert isinstance(port, int), port
            assert 0 <= port <= 65535, port
            check_net_address(ip, conn.family)
        elif conn.family == AF_UNIX:
            assert isinstance(addr, (str, None)), addr
        else:
            raise ValueError("unknown family %r", conn.family)

    if conn.family in (AF_INET, AF_INET6):
        # actually try to bind the local socket; ignore IPv6
        # sockets as their address might be represented as
        # an IPv4-mapped-address (e.g. "::127.0.0.1")
        # and that's rejected by bind()
        if conn.family == AF_INET:
            s = socket.socket(conn.family, conn.type)
            with contextlib.closing(s):
                try:
                    s.bind((conn.laddr[0], 0))
                except socket.error as err:
                    if err.errno != errno.EADDRNOTAVAIL:
                        raise
    elif conn.family == AF_UNIX:
        assert not conn.raddr, repr(conn.raddr)
        assert conn.status == psutil.CONN_NONE, conn.status

    if getattr(conn, 'fd', -1) != -1:
        assert conn.fd > 0, conn
        if hasattr(socket, 'fromfd') and not WINDOWS:
            try:
                dupsock = socket.fromfd(conn.fd, conn.family, conn.type)
            except (socket.error, OSError) as err:
                if err.args[0] != errno.EBADF:
                    raise
            else:
                with contextlib.closing(dupsock):
                    assert dupsock.family == conn.family
                    assert dupsock.type == conn.type


def cleanup():
    for name in os.listdir('.'):
        if name.startswith(TESTFILE_PREFIX):
            try:
                safe_rmpath(name)
            except UnicodeEncodeError as exc:
                warn(exc)
    for path in _testfiles:
        safe_rmpath(path)


atexit.register(cleanup)
atexit.register(lambda: DEVNULL.close())


# ===================================================================
# --- others
# ===================================================================


def warn(msg):
    """Raise a warning msg."""
    warnings.warn(msg, UserWarning)


# In Python 3 paths are unicode objects by default.  Surrogate escapes
# are used to handle non-character data.
def encode_path(path):
    if PY3:
        return path.encode(sys.getfilesystemencoding(),
                           errors="surrogateescape")
    else:
        return path


def decode_path(path):
    if PY3:
        return path.decode(sys.getfilesystemencoding(),
                           errors="surrogateescape")
    else:
        return path
