#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for psutil.Process class."""

import collections
import contextlib
import errno
import os
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
import types
from socket import AF_INET
from socket import SOCK_DGRAM
from socket import SOCK_STREAM

import psutil

from psutil import BSD
from psutil import FREEBSD
from psutil import LINUX
from psutil import NETBSD
from psutil import OPENBSD
from psutil import OSX
from psutil import POSIX
from psutil import SUNOS
from psutil import WINDOWS
from psutil._common import supports_ipv6
from psutil._compat import callable
from psutil._compat import long
from psutil._compat import PY3
from psutil._compat import unicode
from psutil.tests import AF_INET6
from psutil.tests import AF_UNIX
from psutil.tests import APPVEYOR
from psutil.tests import call_until
from psutil.tests import chdir
from psutil.tests import check_connection_ntuple
from psutil.tests import create_exe
from psutil.tests import enum
from psutil.tests import get_test_subprocess
from psutil.tests import get_winver
from psutil.tests import GLOBAL_TIMEOUT
from psutil.tests import mock
from psutil.tests import PYPY
from psutil.tests import pyrun
from psutil.tests import PYTHON
from psutil.tests import reap_children
from psutil.tests import retry_before_failing
from psutil.tests import RLIMIT_SUPPORT
from psutil.tests import run_test_module_by_name
from psutil.tests import safe_rmpath
from psutil.tests import sh
from psutil.tests import skip_on_access_denied
from psutil.tests import skip_on_not_implemented
from psutil.tests import TESTFILE_PREFIX
from psutil.tests import TESTFN
from psutil.tests import ThreadTask
from psutil.tests import TOX
from psutil.tests import TRAVIS
from psutil.tests import unittest
from psutil.tests import VALID_PROC_STATUSES
from psutil.tests import wait_for_file
from psutil.tests import wait_for_pid
from psutil.tests import warn
from psutil.tests import WIN_VISTA


# ===================================================================
# --- psutil.Process class tests
# ===================================================================

class TestProcess(unittest.TestCase):
    """Tests for psutil.Process class."""

    def setUp(self):
        safe_rmpath(TESTFN)

    def tearDown(self):
        reap_children()

    def test_pid(self):
        p = psutil.Process()
        self.assertEqual(p.pid, os.getpid())
        sproc = get_test_subprocess()
        self.assertEqual(psutil.Process(sproc.pid).pid, sproc.pid)
        with self.assertRaises(AttributeError):
            p.pid = 33

    def test_kill(self):
        sproc = get_test_subprocess()
        test_pid = sproc.pid
        p = psutil.Process(test_pid)
        p.kill()
        sig = p.wait()
        self.assertFalse(psutil.pid_exists(test_pid))
        if POSIX:
            self.assertEqual(sig, -signal.SIGKILL)

    def test_terminate(self):
        sproc = get_test_subprocess()
        test_pid = sproc.pid
        p = psutil.Process(test_pid)
        p.terminate()
        sig = p.wait()
        self.assertFalse(psutil.pid_exists(test_pid))
        if POSIX:
            self.assertEqual(sig, -signal.SIGTERM)

    def test_send_signal(self):
        sig = signal.SIGKILL if POSIX else signal.SIGTERM
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        p.send_signal(sig)
        exit_sig = p.wait()
        self.assertFalse(psutil.pid_exists(p.pid))
        if POSIX:
            self.assertEqual(exit_sig, -sig)
            #
            sproc = get_test_subprocess()
            p = psutil.Process(sproc.pid)
            p.send_signal(sig)
            with mock.patch('psutil.os.kill',
                            side_effect=OSError(errno.ESRCH, "")):
                with self.assertRaises(psutil.NoSuchProcess):
                    p.send_signal(sig)
            #
            sproc = get_test_subprocess()
            p = psutil.Process(sproc.pid)
            p.send_signal(sig)
            with mock.patch('psutil.os.kill',
                            side_effect=OSError(errno.EPERM, "")):
                with self.assertRaises(psutil.AccessDenied):
                    psutil.Process().send_signal(sig)
            # Sending a signal to process with PID 0 is not allowed as
            # it would affect every process in the process group of
            # the calling process (os.getpid()) instead of PID 0").
            if 0 in psutil.pids():
                p = psutil.Process(0)
                self.assertRaises(ValueError, p.send_signal, signal.SIGTERM)

    def test_wait(self):
        # check exit code signal
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        p.kill()
        code = p.wait()
        if POSIX:
            self.assertEqual(code, -signal.SIGKILL)
        else:
            self.assertEqual(code, 0)
        self.assertFalse(p.is_running())

        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        p.terminate()
        code = p.wait()
        if POSIX:
            self.assertEqual(code, -signal.SIGTERM)
        else:
            self.assertEqual(code, 0)
        self.assertFalse(p.is_running())

        # check sys.exit() code
        code = "import time, sys; time.sleep(0.01); sys.exit(5);"
        sproc = get_test_subprocess([PYTHON, "-c", code])
        p = psutil.Process(sproc.pid)
        self.assertEqual(p.wait(), 5)
        self.assertFalse(p.is_running())

        # Test wait() issued twice.
        # It is not supposed to raise NSP when the process is gone.
        # On UNIX this should return None, on Windows it should keep
        # returning the exit code.
        sproc = get_test_subprocess([PYTHON, "-c", code])
        p = psutil.Process(sproc.pid)
        self.assertEqual(p.wait(), 5)
        self.assertIn(p.wait(), (5, None))

        # test timeout
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        p.name()
        self.assertRaises(psutil.TimeoutExpired, p.wait, 0.01)

        # timeout < 0 not allowed
        self.assertRaises(ValueError, p.wait, -1)

    # XXX why is this skipped on Windows?
    @unittest.skipUnless(POSIX, 'skipped on Windows')
    def test_wait_non_children(self):
        # test wait() against processes which are not our children
        code = "import sys;"
        code += "from subprocess import Popen, PIPE;"
        code += "cmd = ['%s', '-c', 'import time; time.sleep(60)'];" % PYTHON
        code += "sp = Popen(cmd, stdout=PIPE);"
        code += "sys.stdout.write(str(sp.pid));"
        sproc = get_test_subprocess([PYTHON, "-c", code],
                                    stdout=subprocess.PIPE)
        grandson_pid = int(sproc.stdout.read())
        grandson_proc = psutil.Process(grandson_pid)
        try:
            self.assertRaises(psutil.TimeoutExpired, grandson_proc.wait, 0.01)
            grandson_proc.kill()
            ret = grandson_proc.wait()
            self.assertEqual(ret, None)
        finally:
            reap_children(recursive=True)

    def test_wait_timeout_0(self):
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        self.assertRaises(psutil.TimeoutExpired, p.wait, 0)
        p.kill()
        stop_at = time.time() + 2
        while True:
            try:
                code = p.wait(0)
            except psutil.TimeoutExpired:
                if time.time() >= stop_at:
                    raise
            else:
                break
        if POSIX:
            self.assertEqual(code, -signal.SIGKILL)
        else:
            self.assertEqual(code, 0)
        self.assertFalse(p.is_running())

    def test_cpu_percent(self):
        p = psutil.Process()
        p.cpu_percent(interval=0.001)
        p.cpu_percent(interval=0.001)
        for x in range(100):
            percent = p.cpu_percent(interval=None)
            self.assertIsInstance(percent, float)
            self.assertGreaterEqual(percent, 0.0)
            if not POSIX:
                self.assertLessEqual(percent, 100.0)
            else:
                self.assertGreaterEqual(percent, 0.0)
        with self.assertRaises(ValueError):
            p.cpu_percent(interval=-1)

    def test_cpu_times(self):
        times = psutil.Process().cpu_times()
        assert (times.user > 0.0) or (times.system > 0.0), times
        assert (times.children_user >= 0.0), times
        assert (times.children_system >= 0.0), times
        # make sure returned values can be pretty printed with strftime
        for name in times._fields:
            time.strftime("%H:%M:%S", time.localtime(getattr(times, name)))

    # Test Process.cpu_times() against os.times()
    # os.times() is broken on Python 2.6
    # http://bugs.python.org/issue1040026
    # XXX fails on OSX: not sure if it's for os.times(). We should
    # try this with Python 2.7 and re-enable the test.

    @unittest.skipUnless(sys.version_info > (2, 6, 1) and not OSX,
                         'os.times() broken on OSX + PY2.6.1')
    def test_cpu_times_2(self):
        user_time, kernel_time = psutil.Process().cpu_times()[:2]
        utime, ktime = os.times()[:2]

        # Use os.times()[:2] as base values to compare our results
        # using a tolerance  of +/- 0.1 seconds.
        # It will fail if the difference between the values is > 0.1s.
        if (max([user_time, utime]) - min([user_time, utime])) > 0.1:
            self.fail("expected: %s, found: %s" % (utime, user_time))

        if (max([kernel_time, ktime]) - min([kernel_time, ktime])) > 0.1:
            self.fail("expected: %s, found: %s" % (ktime, kernel_time))

    @unittest.skipUnless(hasattr(psutil.Process, "cpu_num"),
                         "platform not supported")
    def test_cpu_num(self):
        p = psutil.Process()
        num = p.cpu_num()
        self.assertGreaterEqual(num, 0)
        if psutil.cpu_count() == 1:
            self.assertEqual(num, 0)
        self.assertIn(p.cpu_num(), range(psutil.cpu_count()))

    def test_create_time(self):
        sproc = get_test_subprocess()
        now = time.time()
        p = psutil.Process(sproc.pid)
        create_time = p.create_time()

        # Use time.time() as base value to compare our result using a
        # tolerance of +/- 1 second.
        # It will fail if the difference between the values is > 2s.
        difference = abs(create_time - now)
        if difference > 2:
            self.fail("expected: %s, found: %s, difference: %s"
                      % (now, create_time, difference))

        # make sure returned value can be pretty printed with strftime
        time.strftime("%Y %m %d %H:%M:%S", time.localtime(p.create_time()))

    @unittest.skipUnless(POSIX, 'POSIX only')
    @unittest.skipIf(TRAVIS, 'not reliable on TRAVIS')
    def test_terminal(self):
        terminal = psutil.Process().terminal()
        if sys.stdin.isatty() or sys.stdout.isatty():
            tty = os.path.realpath(sh('tty'))
            self.assertEqual(terminal, tty)
        else:
            self.assertIsNone(terminal)

    @unittest.skipUnless(LINUX or BSD or WINDOWS,
                         'platform not supported')
    @skip_on_not_implemented(only_if=LINUX)
    def test_io_counters(self):
        p = psutil.Process()

        # test reads
        io1 = p.io_counters()
        with open(PYTHON, 'rb') as f:
            f.read()
        io2 = p.io_counters()
        if not BSD:
            self.assertGreater(io2.read_count, io1.read_count)
            self.assertEqual(io2.write_count, io1.write_count)
            if LINUX:
                self.assertGreater(io2.read_chars, io1.read_chars)
                self.assertEqual(io2.write_chars, io1.write_chars)
        else:
            self.assertGreaterEqual(io2.read_bytes, io1.read_bytes)
            self.assertGreaterEqual(io2.write_bytes, io1.write_bytes)

        # test writes
        io1 = p.io_counters()
        with tempfile.TemporaryFile(prefix=TESTFILE_PREFIX) as f:
            if PY3:
                f.write(bytes("x" * 1000000, 'ascii'))
            else:
                f.write("x" * 1000000)
        io2 = p.io_counters()
        self.assertGreaterEqual(io2.write_count, io1.write_count)
        self.assertGreaterEqual(io2.write_bytes, io1.write_bytes)
        self.assertGreaterEqual(io2.read_count, io1.read_count)
        self.assertGreaterEqual(io2.read_bytes, io1.read_bytes)
        if LINUX:
            self.assertGreater(io2.write_chars, io1.write_chars)
            self.assertGreaterEqual(io2.read_chars, io1.read_chars)

        # sanity check
        for i in range(len(io2)):
            self.assertGreaterEqual(io2[i], 0)
            self.assertGreaterEqual(io2[i], 0)

    @unittest.skipUnless(LINUX or (WINDOWS and get_winver() >= WIN_VISTA),
                         'platform not supported')
    @unittest.skipIf(LINUX and TRAVIS, "unknown failure on travis")
    def test_ionice(self):
        if LINUX:
            from psutil import (IOPRIO_CLASS_NONE, IOPRIO_CLASS_RT,
                                IOPRIO_CLASS_BE, IOPRIO_CLASS_IDLE)
            self.assertEqual(IOPRIO_CLASS_NONE, 0)
            self.assertEqual(IOPRIO_CLASS_RT, 1)
            self.assertEqual(IOPRIO_CLASS_BE, 2)
            self.assertEqual(IOPRIO_CLASS_IDLE, 3)
            p = psutil.Process()
            try:
                p.ionice(2)
                ioclass, value = p.ionice()
                if enum is not None:
                    self.assertIsInstance(ioclass, enum.IntEnum)
                self.assertEqual(ioclass, 2)
                self.assertEqual(value, 4)
                #
                p.ionice(3)
                ioclass, value = p.ionice()
                self.assertEqual(ioclass, 3)
                self.assertEqual(value, 0)
                #
                p.ionice(2, 0)
                ioclass, value = p.ionice()
                self.assertEqual(ioclass, 2)
                self.assertEqual(value, 0)
                p.ionice(2, 7)
                ioclass, value = p.ionice()
                self.assertEqual(ioclass, 2)
                self.assertEqual(value, 7)
                #
                self.assertRaises(ValueError, p.ionice, 2, 10)
                self.assertRaises(ValueError, p.ionice, 2, -1)
                self.assertRaises(ValueError, p.ionice, 4)
                self.assertRaises(TypeError, p.ionice, 2, "foo")
                self.assertRaisesRegex(
                    ValueError, "can't specify value with IOPRIO_CLASS_NONE",
                    p.ionice, psutil.IOPRIO_CLASS_NONE, 1)
                self.assertRaisesRegex(
                    ValueError, "can't specify value with IOPRIO_CLASS_IDLE",
                    p.ionice, psutil.IOPRIO_CLASS_IDLE, 1)
                self.assertRaisesRegex(
                    ValueError, "'ioclass' argument must be specified",
                    p.ionice, value=1)
            finally:
                p.ionice(IOPRIO_CLASS_NONE)
        else:
            p = psutil.Process()
            original = p.ionice()
            self.assertIsInstance(original, int)
            try:
                value = 0  # very low
                if original == value:
                    value = 1  # low
                p.ionice(value)
                self.assertEqual(p.ionice(), value)
            finally:
                p.ionice(original)
            #
            self.assertRaises(ValueError, p.ionice, 3)
            self.assertRaises(TypeError, p.ionice, 2, 1)

    @unittest.skipUnless(LINUX and RLIMIT_SUPPORT, "LINUX >= 2.6.36 only")
    def test_rlimit_get(self):
        import resource
        p = psutil.Process(os.getpid())
        names = [x for x in dir(psutil) if x.startswith('RLIMIT')]
        assert names, names
        for name in names:
            value = getattr(psutil, name)
            self.assertGreaterEqual(value, 0)
            if name in dir(resource):
                self.assertEqual(value, getattr(resource, name))
                # XXX - On PyPy RLIMIT_INFINITY returned by
                # resource.getrlimit() is reported as a very big long
                # number instead of -1. It looks like a bug with PyPy.
                if PYPY:
                    continue
                self.assertEqual(p.rlimit(value), resource.getrlimit(value))
            else:
                ret = p.rlimit(value)
                self.assertEqual(len(ret), 2)
                self.assertGreaterEqual(ret[0], -1)
                self.assertGreaterEqual(ret[1], -1)

    @unittest.skipUnless(LINUX and RLIMIT_SUPPORT, "LINUX >= 2.6.36 only")
    def test_rlimit_set(self):
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        p.rlimit(psutil.RLIMIT_NOFILE, (5, 5))
        self.assertEqual(p.rlimit(psutil.RLIMIT_NOFILE), (5, 5))
        # If pid is 0 prlimit() applies to the calling process and
        # we don't want that.
        with self.assertRaises(ValueError):
            psutil._psplatform.Process(0).rlimit(0)
        with self.assertRaises(ValueError):
            p.rlimit(psutil.RLIMIT_NOFILE, (5, 5, 5))

    @unittest.skipUnless(LINUX and RLIMIT_SUPPORT, "LINUX >= 2.6.36 only")
    def test_rlimit(self):
        p = psutil.Process()
        soft, hard = p.rlimit(psutil.RLIMIT_FSIZE)
        try:
            p.rlimit(psutil.RLIMIT_FSIZE, (1024, hard))
            with open(TESTFN, "wb") as f:
                f.write(b"X" * 1024)
            # write() or flush() doesn't always cause the exception
            # but close() will.
            with self.assertRaises(IOError) as exc:
                with open(TESTFN, "wb") as f:
                    f.write(b"X" * 1025)
            self.assertEqual(exc.exception.errno if PY3 else exc.exception[0],
                             errno.EFBIG)
        finally:
            p.rlimit(psutil.RLIMIT_FSIZE, (soft, hard))
            self.assertEqual(p.rlimit(psutil.RLIMIT_FSIZE), (soft, hard))

    @unittest.skipUnless(LINUX and RLIMIT_SUPPORT, "LINUX >= 2.6.36 only")
    def test_rlimit_infinity(self):
        # First set a limit, then re-set it by specifying INFINITY
        # and assume we overridden the previous limit.
        p = psutil.Process()
        soft, hard = p.rlimit(psutil.RLIMIT_FSIZE)
        try:
            p.rlimit(psutil.RLIMIT_FSIZE, (1024, hard))
            p.rlimit(psutil.RLIMIT_FSIZE, (psutil.RLIM_INFINITY, hard))
            with open(TESTFN, "wb") as f:
                f.write(b"X" * 2048)
        finally:
            p.rlimit(psutil.RLIMIT_FSIZE, (soft, hard))
            self.assertEqual(p.rlimit(psutil.RLIMIT_FSIZE), (soft, hard))

    @unittest.skipUnless(LINUX and RLIMIT_SUPPORT, "LINUX >= 2.6.36 only")
    def test_rlimit_infinity_value(self):
        # RLIMIT_FSIZE should be RLIM_INFINITY, which will be a really
        # big number on a platform with large file support.  On these
        # platforms we need to test that the get/setrlimit functions
        # properly convert the number to a C long long and that the
        # conversion doesn't raise an error.
        p = psutil.Process()
        soft, hard = p.rlimit(psutil.RLIMIT_FSIZE)
        self.assertEqual(psutil.RLIM_INFINITY, hard)
        p.rlimit(psutil.RLIMIT_FSIZE, (soft, hard))

    def test_num_threads(self):
        # on certain platforms such as Linux we might test for exact
        # thread number, since we always have with 1 thread per process,
        # but this does not apply across all platforms (OSX, Windows)
        p = psutil.Process()
        if OPENBSD:
            try:
                step1 = p.num_threads()
            except psutil.AccessDenied:
                raise unittest.SkipTest("on OpenBSD this requires root access")
        else:
            step1 = p.num_threads()

        thread = ThreadTask()
        thread.start()
        try:
            step2 = p.num_threads()
            self.assertEqual(step2, step1 + 1)
        finally:
            thread.stop()

    @unittest.skipUnless(WINDOWS, 'WINDOWS only')
    def test_num_handles(self):
        # a better test is done later into test/_windows.py
        p = psutil.Process()
        self.assertGreater(p.num_handles(), 0)

    def test_threads(self):
        p = psutil.Process()
        if OPENBSD:
            try:
                step1 = p.threads()
            except psutil.AccessDenied:
                raise unittest.SkipTest("on OpenBSD this requires root access")
        else:
            step1 = p.threads()

        thread = ThreadTask()
        thread.start()
        try:
            step2 = p.threads()
            self.assertEqual(len(step2), len(step1) + 1)
            # on Linux, first thread id is supposed to be this process
            if LINUX:
                self.assertEqual(step2[0].id, os.getpid())
            athread = step2[0]
            # test named tuple
            self.assertEqual(athread.id, athread[0])
            self.assertEqual(athread.user_time, athread[1])
            self.assertEqual(athread.system_time, athread[2])
        finally:
            thread.stop()

    @retry_before_failing()
    # see: https://travis-ci.org/giampaolo/psutil/jobs/111842553
    @unittest.skipIf(OSX and TRAVIS, "fails on TRAVIS + OSX")
    @skip_on_access_denied(only_if=OSX)
    def test_threads_2(self):
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        if OPENBSD:
            try:
                p.threads()
            except psutil.AccessDenied:
                raise unittest.SkipTest(
                    "on OpenBSD this requires root access")
        self.assertAlmostEqual(
            p.cpu_times().user,
            sum([x.user_time for x in p.threads()]), delta=0.1)
        self.assertAlmostEqual(
            p.cpu_times().system,
            sum([x.system_time for x in p.threads()]), delta=0.1)

    def test_memory_info(self):
        p = psutil.Process()

        # step 1 - get a base value to compare our results
        rss1, vms1 = p.memory_info()[:2]
        percent1 = p.memory_percent()
        self.assertGreater(rss1, 0)
        self.assertGreater(vms1, 0)

        # step 2 - allocate some memory
        memarr = [None] * 1500000

        rss2, vms2 = p.memory_info()[:2]
        percent2 = p.memory_percent()

        # step 3 - make sure that the memory usage bumped up
        self.assertGreater(rss2, rss1)
        self.assertGreaterEqual(vms2, vms1)  # vms might be equal
        self.assertGreater(percent2, percent1)
        del memarr

        if WINDOWS:
            mem = p.memory_info()
            self.assertEqual(mem.rss, mem.wset)
            self.assertEqual(mem.vms, mem.pagefile)

        mem = p.memory_info()
        for name in mem._fields:
            self.assertGreaterEqual(getattr(mem, name), 0)

    def test_memory_full_info(self):
        total = psutil.virtual_memory().total
        mem = psutil.Process().memory_full_info()
        for name in mem._fields:
            value = getattr(mem, name)
            self.assertGreaterEqual(value, 0, msg=(name, value))
            self.assertLessEqual(value, total, msg=(name, value, total))
        if LINUX or WINDOWS or OSX:
            mem.uss
        if LINUX:
            mem.pss
            self.assertGreater(mem.pss, mem.uss)

    @unittest.skipIf(OPENBSD or NETBSD, "platfform not supported")
    def test_memory_maps(self):
        p = psutil.Process()
        maps = p.memory_maps()
        paths = [x for x in maps]
        self.assertEqual(len(paths), len(set(paths)))
        ext_maps = p.memory_maps(grouped=False)

        for nt in maps:
            if not nt.path.startswith('['):
                assert os.path.isabs(nt.path), nt.path
                if POSIX:
                    try:
                        assert os.path.exists(nt.path) or \
                            os.path.islink(nt.path), nt.path
                    except AssertionError:
                        if not LINUX:
                            raise
                        else:
                            # https://github.com/giampaolo/psutil/issues/759
                            with open('/proc/self/smaps') as f:
                                data = f.read()
                            if "%s (deleted)" % nt.path not in data:
                                raise
                else:
                    # XXX - On Windows we have this strange behavior with
                    # 64 bit dlls: they are visible via explorer but cannot
                    # be accessed via os.stat() (wtf?).
                    if '64' not in os.path.basename(nt.path):
                        assert os.path.exists(nt.path), nt.path
        for nt in ext_maps:
            for fname in nt._fields:
                value = getattr(nt, fname)
                if fname == 'path':
                    continue
                elif fname in ('addr', 'perms'):
                    assert value, value
                else:
                    self.assertIsInstance(value, (int, long))
                    assert value >= 0, value

    def test_memory_percent(self):
        p = psutil.Process()
        ret = p.memory_percent()
        assert 0 <= ret <= 100, ret
        ret = p.memory_percent(memtype='vms')
        assert 0 <= ret <= 100, ret
        assert 0 <= ret <= 100, ret
        self.assertRaises(ValueError, p.memory_percent, memtype="?!?")
        if LINUX or OSX or WINDOWS:
            ret = p.memory_percent(memtype='uss')
            assert 0 <= ret <= 100, ret
            assert 0 <= ret <= 100, ret

    def test_is_running(self):
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        assert p.is_running()
        assert p.is_running()
        p.kill()
        p.wait()
        assert not p.is_running()
        assert not p.is_running()

    def test_exe(self):
        sproc = get_test_subprocess()
        exe = psutil.Process(sproc.pid).exe()
        try:
            self.assertEqual(exe, PYTHON)
        except AssertionError:
            if WINDOWS and len(exe) == len(PYTHON):
                # on Windows we don't care about case sensitivity
                normcase = os.path.normcase
                self.assertEqual(normcase(exe), normcase(PYTHON))
            else:
                # certain platforms such as BSD are more accurate returning:
                # "/usr/local/bin/python2.7"
                # ...instead of:
                # "/usr/local/bin/python"
                # We do not want to consider this difference in accuracy
                # an error.
                ver = "%s.%s" % (sys.version_info[0], sys.version_info[1])
                try:
                    self.assertEqual(exe.replace(ver, ''),
                                     PYTHON.replace(ver, ''))
                except AssertionError:
                    # Tipically OSX. Really not sure what to do here.
                    pass

        subp = subprocess.Popen([exe, '-c', 'import os; print("hey")'],
                                stdout=subprocess.PIPE)
        out, _ = subp.communicate()
        self.assertEqual(out.strip(), b'hey')

    def test_cmdline(self):
        cmdline = [PYTHON, "-c", "import time; time.sleep(60)"]
        sproc = get_test_subprocess(cmdline)
        try:
            self.assertEqual(' '.join(psutil.Process(sproc.pid).cmdline()),
                             ' '.join(cmdline))
        except AssertionError:
            # XXX - most of the times the underlying sysctl() call on Net
            # and Open BSD returns a truncated string.
            # Also /proc/pid/cmdline behaves the same so it looks
            # like this is a kernel bug.
            if NETBSD or OPENBSD:
                self.assertEqual(
                    psutil.Process(sproc.pid).cmdline()[0], PYTHON)
            else:
                raise

    def test_name(self):
        sproc = get_test_subprocess(PYTHON)
        name = psutil.Process(sproc.pid).name().lower()
        pyexe = os.path.basename(os.path.realpath(sys.executable)).lower()
        assert pyexe.startswith(name), (pyexe, name)

    # XXX
    @unittest.skipIf(SUNOS, "broken on SUNOS")
    def test_prog_w_funky_name(self):
        # Test that name(), exe() and cmdline() correctly handle programs
        # with funky chars such as spaces and ")", see:
        # https://github.com/giampaolo/psutil/issues/628
        funky_path = TESTFN + 'foo bar )'
        create_exe(funky_path)
        self.addCleanup(safe_rmpath, funky_path)
        cmdline = [funky_path, "-c",
                   "import time; [time.sleep(0.01) for x in range(3000)];"
                   "arg1", "arg2", "", "arg3", ""]
        sproc = get_test_subprocess(cmdline)
        p = psutil.Process(sproc.pid)
        # ...in order to try to prevent occasional failures on travis
        if TRAVIS:
            wait_for_pid(p.pid)
        self.assertEqual(p.cmdline(), cmdline)
        self.assertEqual(p.name(), os.path.basename(funky_path))
        self.assertEqual(os.path.normcase(p.exe()),
                         os.path.normcase(funky_path))

    @unittest.skipUnless(POSIX, 'POSIX only')
    def test_uids(self):
        p = psutil.Process()
        real, effective, saved = p.uids()
        # os.getuid() refers to "real" uid
        self.assertEqual(real, os.getuid())
        # os.geteuid() refers to "effective" uid
        self.assertEqual(effective, os.geteuid())
        # No such thing as os.getsuid() ("saved" uid), but starting
        # from python 2.7 we have os.getresuid() which returns all
        # of them.
        if hasattr(os, "getresuid"):
            self.assertEqual(os.getresuid(), p.uids())

    @unittest.skipUnless(POSIX, 'POSIX only')
    def test_gids(self):
        p = psutil.Process()
        real, effective, saved = p.gids()
        # os.getuid() refers to "real" uid
        self.assertEqual(real, os.getgid())
        # os.geteuid() refers to "effective" uid
        self.assertEqual(effective, os.getegid())
        # No such thing as os.getsgid() ("saved" gid), but starting
        # from python 2.7 we have os.getresgid() which returns all
        # of them.
        if hasattr(os, "getresuid"):
            self.assertEqual(os.getresgid(), p.gids())

    def test_nice(self):
        p = psutil.Process()
        self.assertRaises(TypeError, p.nice, "str")
        if WINDOWS:
            try:
                init = p.nice()
                if sys.version_info > (3, 4):
                    self.assertIsInstance(init, enum.IntEnum)
                else:
                    self.assertIsInstance(init, int)
                self.assertEqual(init, psutil.NORMAL_PRIORITY_CLASS)
                p.nice(psutil.HIGH_PRIORITY_CLASS)
                self.assertEqual(p.nice(), psutil.HIGH_PRIORITY_CLASS)
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
                self.assertEqual(p.nice(), psutil.NORMAL_PRIORITY_CLASS)
            finally:
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
        else:
            first_nice = p.nice()
            try:
                if hasattr(os, "getpriority"):
                    self.assertEqual(
                        os.getpriority(os.PRIO_PROCESS, os.getpid()), p.nice())
                p.nice(1)
                self.assertEqual(p.nice(), 1)
                if hasattr(os, "getpriority"):
                    self.assertEqual(
                        os.getpriority(os.PRIO_PROCESS, os.getpid()), p.nice())
                # XXX - going back to previous nice value raises
                # AccessDenied on OSX
                if not OSX:
                    p.nice(0)
                    self.assertEqual(p.nice(), 0)
            except psutil.AccessDenied:
                pass
            finally:
                try:
                    p.nice(first_nice)
                except psutil.AccessDenied:
                    pass

    def test_status(self):
        p = psutil.Process()
        self.assertEqual(p.status(), psutil.STATUS_RUNNING)

    def test_username(self):
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        if POSIX:
            import pwd
            self.assertEqual(p.username(), pwd.getpwuid(os.getuid()).pw_name)
            with mock.patch("psutil.pwd.getpwuid",
                            side_effect=KeyError) as fun:
                p.username() == str(p.uids().real)
                assert fun.called

        elif WINDOWS and 'USERNAME' in os.environ:
            expected_username = os.environ['USERNAME']
            expected_domain = os.environ['USERDOMAIN']
            domain, username = p.username().split('\\')
            self.assertEqual(domain, expected_domain)
            self.assertEqual(username, expected_username)
        else:
            p.username()

    def test_cwd(self):
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        self.assertEqual(p.cwd(), os.getcwd())

    def test_cwd_2(self):
        cmd = [PYTHON, "-c", "import os, time; os.chdir('..'); time.sleep(60)"]
        sproc = get_test_subprocess(cmd)
        p = psutil.Process(sproc.pid)
        call_until(p.cwd, "ret == os.path.dirname(os.getcwd())")

    @unittest.skipUnless(WINDOWS or LINUX or FREEBSD, 'platform not supported')
    @unittest.skipIf(LINUX and TRAVIS, "unreliable on TRAVIS")
    def test_cpu_affinity(self):
        p = psutil.Process()
        initial = p.cpu_affinity()
        assert initial, initial
        self.addCleanup(p.cpu_affinity, initial)

        if hasattr(os, "sched_getaffinity"):
            self.assertEqual(initial, list(os.sched_getaffinity(p.pid)))
        self.assertEqual(len(initial), len(set(initial)))

        all_cpus = list(range(len(psutil.cpu_percent(percpu=True))))
        # setting on travis doesn't seem to work (always return all
        # CPUs on get):
        # AssertionError: Lists differ: [0, 1, 2, 3, 4, 5, 6, ... != [0]
        for n in all_cpus:
            p.cpu_affinity([n])
            self.assertEqual(p.cpu_affinity(), [n])
            if hasattr(os, "sched_getaffinity"):
                self.assertEqual(p.cpu_affinity(),
                                 list(os.sched_getaffinity(p.pid)))
            # also test num_cpu()
            if hasattr(p, "num_cpu"):
                self.assertEqual(p.cpu_affinity()[0], p.num_cpu())

        # [] is an alias for "all eligible CPUs"; on Linux this may
        # not be equal to all available CPUs, see:
        # https://github.com/giampaolo/psutil/issues/956
        p.cpu_affinity([])
        if LINUX:
            self.assertEqual(p.cpu_affinity(), p._proc._get_eligible_cpus())
        else:
            self.assertEqual(p.cpu_affinity(), all_cpus)
        if hasattr(os, "sched_getaffinity"):
            self.assertEqual(p.cpu_affinity(),
                             list(os.sched_getaffinity(p.pid)))
        #
        self.assertRaises(TypeError, p.cpu_affinity, 1)
        p.cpu_affinity(initial)
        # it should work with all iterables, not only lists
        p.cpu_affinity(set(all_cpus))
        p.cpu_affinity(tuple(all_cpus))
        invalid_cpu = [len(psutil.cpu_times(percpu=True)) + 10]
        self.assertRaises(ValueError, p.cpu_affinity, invalid_cpu)
        self.assertRaises(ValueError, p.cpu_affinity, range(10000, 11000))
        self.assertRaises(TypeError, p.cpu_affinity, [0, "1"])
        self.assertRaises(ValueError, p.cpu_affinity, [0, -1])

    # TODO: #595
    @unittest.skipIf(BSD, "broken on BSD")
    # can't find any process file on Appveyor
    @unittest.skipIf(APPVEYOR, "unreliable on APPVEYOR")
    def test_open_files(self):
        # current process
        p = psutil.Process()
        files = p.open_files()
        self.assertFalse(TESTFN in files)
        with open(TESTFN, 'wb') as f:
            f.write(b'x' * 1024)
            f.flush()
            # give the kernel some time to see the new file
            files = call_until(p.open_files, "len(ret) != %i" % len(files))
            for file in files:
                if file.path == TESTFN:
                    if LINUX:
                        self.assertEqual(file.position, 1024)
                    break
            else:
                self.fail("no file found; files=%s" % repr(files))
        for file in files:
            assert os.path.isfile(file.path), file

        # another process
        cmdline = "import time; f = open(r'%s', 'r'); time.sleep(60);" % TESTFN
        sproc = get_test_subprocess([PYTHON, "-c", cmdline])
        p = psutil.Process(sproc.pid)

        for x in range(100):
            filenames = [x.path for x in p.open_files()]
            if TESTFN in filenames:
                break
            time.sleep(.01)
        else:
            self.assertIn(TESTFN, filenames)
        for file in filenames:
            assert os.path.isfile(file), file

    # TODO: #595
    @unittest.skipIf(BSD, "broken on BSD")
    # can't find any process file on Appveyor
    @unittest.skipIf(APPVEYOR, "unreliable on APPVEYOR")
    def test_open_files_2(self):
        # test fd and path fields
        with open(TESTFN, 'w') as fileobj:
            p = psutil.Process()
            for file in p.open_files():
                if file.path == fileobj.name or file.fd == fileobj.fileno():
                    break
            else:
                self.fail("no file found; files=%s" % repr(p.open_files()))
            self.assertEqual(file.path, fileobj.name)
            if WINDOWS:
                self.assertEqual(file.fd, -1)
            else:
                self.assertEqual(file.fd, fileobj.fileno())
            # test positions
            ntuple = p.open_files()[0]
            self.assertEqual(ntuple[0], ntuple.path)
            self.assertEqual(ntuple[1], ntuple.fd)
            # test file is gone
            self.assertTrue(fileobj.name not in p.open_files())

    def compare_proc_sys_cons(self, pid, proc_cons):
        from psutil._common import pconn
        sys_cons = [c[:-1] for c in psutil.net_connections(kind='all')
                    if c.pid == pid]
        if FREEBSD:
            # on FreeBSD all fds are set to -1
            proc_cons = [pconn(*[-1] + list(x[1:])) for x in proc_cons]
        self.assertEqual(sorted(proc_cons), sorted(sys_cons))

    @skip_on_access_denied(only_if=OSX)
    def test_connections(self):
        def check_conn(proc, conn, family, type, laddr, raddr, status, kinds):
            all_kinds = ("all", "inet", "inet4", "inet6", "tcp", "tcp4",
                         "tcp6", "udp", "udp4", "udp6")
            check_connection_ntuple(conn)
            self.assertEqual(conn.family, family)
            self.assertEqual(conn.type, type)
            self.assertEqual(conn.laddr, laddr)
            self.assertEqual(conn.raddr, raddr)
            self.assertEqual(conn.status, status)
            for kind in all_kinds:
                cons = proc.connections(kind=kind)
                if kind in kinds:
                    self.assertNotEqual(cons, [])
                else:
                    self.assertEqual(cons, [])
            # compare against system-wide connections
            # XXX Solaris can't retrieve system-wide UNIX
            # sockets.
            if not SUNOS:
                self.compare_proc_sys_cons(proc.pid, [conn])

        tcp_template = textwrap.dedent("""
            import socket, time
            s = socket.socket($family, socket.SOCK_STREAM)
            s.bind(('$addr', 0))
            s.listen(1)
            with open('$testfn', 'w') as f:
                f.write(str(s.getsockname()[:2]))
            time.sleep(60)
        """)

        udp_template = textwrap.dedent("""
            import socket, time
            s = socket.socket($family, socket.SOCK_DGRAM)
            s.bind(('$addr', 0))
            with open('$testfn', 'w') as f:
                f.write(str(s.getsockname()[:2]))
            time.sleep(60)
        """)

        from string import Template
        testfile = os.path.basename(TESTFN)
        tcp4_template = Template(tcp_template).substitute(
            family=int(AF_INET), addr="127.0.0.1", testfn=testfile)
        udp4_template = Template(udp_template).substitute(
            family=int(AF_INET), addr="127.0.0.1", testfn=testfile)
        tcp6_template = Template(tcp_template).substitute(
            family=int(AF_INET6), addr="::1", testfn=testfile)
        udp6_template = Template(udp_template).substitute(
            family=int(AF_INET6), addr="::1", testfn=testfile)

        # launch various subprocess instantiating a socket of various
        # families and types to enrich psutil results
        tcp4_proc = pyrun(tcp4_template)
        tcp4_addr = eval(wait_for_file(testfile))
        udp4_proc = pyrun(udp4_template)
        udp4_addr = eval(wait_for_file(testfile))
        if supports_ipv6():
            tcp6_proc = pyrun(tcp6_template)
            tcp6_addr = eval(wait_for_file(testfile))
            udp6_proc = pyrun(udp6_template)
            udp6_addr = eval(wait_for_file(testfile))
        else:
            tcp6_proc = None
            udp6_proc = None
            tcp6_addr = None
            udp6_addr = None

        for p in psutil.Process().children():
            cons = p.connections()
            self.assertEqual(len(cons), 1)
            for conn in cons:
                # TCP v4
                if p.pid == tcp4_proc.pid:
                    check_conn(p, conn, AF_INET, SOCK_STREAM, tcp4_addr, (),
                               psutil.CONN_LISTEN,
                               ("all", "inet", "inet4", "tcp", "tcp4"))
                # UDP v4
                elif p.pid == udp4_proc.pid:
                    check_conn(p, conn, AF_INET, SOCK_DGRAM, udp4_addr, (),
                               psutil.CONN_NONE,
                               ("all", "inet", "inet4", "udp", "udp4"))
                # TCP v6
                elif p.pid == getattr(tcp6_proc, "pid", None):
                    check_conn(p, conn, AF_INET6, SOCK_STREAM, tcp6_addr, (),
                               psutil.CONN_LISTEN,
                               ("all", "inet", "inet6", "tcp", "tcp6"))
                # UDP v6
                elif p.pid == getattr(udp6_proc, "pid", None):
                    check_conn(p, conn, AF_INET6, SOCK_DGRAM, udp6_addr, (),
                               psutil.CONN_NONE,
                               ("all", "inet", "inet6", "udp", "udp6"))

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'AF_UNIX not supported')
    @skip_on_access_denied(only_if=OSX)
    def test_connections_unix(self):
        def check(type):
            safe_rmpath(TESTFN)
            tfile = tempfile.mktemp(prefix=TESTFILE_PREFIX) if OSX else TESTFN
            sock = socket.socket(AF_UNIX, type)
            with contextlib.closing(sock):
                sock.bind(tfile)
                cons = psutil.Process().connections(kind='unix')
                conn = cons[0]
                check_connection_ntuple(conn)
                if conn.fd != -1:  # != sunos and windows
                    self.assertEqual(conn.fd, sock.fileno())
                self.assertEqual(conn.family, AF_UNIX)
                self.assertEqual(conn.type, type)
                self.assertEqual(conn.laddr, tfile)
                if not SUNOS:
                    # XXX Solaris can't retrieve system-wide UNIX
                    # sockets.
                    self.compare_proc_sys_cons(os.getpid(), cons)

        check(SOCK_STREAM)
        check(SOCK_DGRAM)

    @unittest.skipUnless(hasattr(socket, "fromfd"),
                         'socket.fromfd() not supported')
    @unittest.skipIf(WINDOWS or SUNOS,
                     'connection fd not available on this platform')
    def test_connection_fromfd(self):
        with contextlib.closing(socket.socket()) as sock:
            sock.bind(('localhost', 0))
            sock.listen(1)
            p = psutil.Process()
            for conn in p.connections():
                if conn.fd == sock.fileno():
                    break
            else:
                self.fail("couldn't find socket fd")
            dupsock = socket.fromfd(conn.fd, conn.family, conn.type)
            with contextlib.closing(dupsock):
                self.assertEqual(dupsock.getsockname(), conn.laddr)
                self.assertNotEqual(sock.fileno(), dupsock.fileno())

    def test_connection_constants(self):
        ints = []
        strs = []
        for name in dir(psutil):
            if name.startswith('CONN_'):
                num = getattr(psutil, name)
                str_ = str(num)
                assert str_.isupper(), str_
                assert str_ not in strs, str_
                assert num not in ints, num
                ints.append(num)
                strs.append(str_)
        if SUNOS:
            psutil.CONN_IDLE
            psutil.CONN_BOUND
        if WINDOWS:
            psutil.CONN_DELETE_TCB

    @unittest.skipUnless(POSIX, 'POSIX only')
    def test_num_fds(self):
        p = psutil.Process()
        start = p.num_fds()
        file = open(TESTFN, 'w')
        self.addCleanup(file.close)
        self.assertEqual(p.num_fds(), start + 1)
        sock = socket.socket()
        self.addCleanup(sock.close)
        self.assertEqual(p.num_fds(), start + 2)
        file.close()
        sock.close()
        self.assertEqual(p.num_fds(), start)

    @skip_on_not_implemented(only_if=LINUX)
    @unittest.skipIf(OPENBSD or NETBSD, "not reliable on OPENBSD & NETBSD")
    def test_num_ctx_switches(self):
        p = psutil.Process()
        before = sum(p.num_ctx_switches())
        for x in range(500000):
            after = sum(p.num_ctx_switches())
            if after > before:
                return
        self.fail("num ctx switches still the same after 50.000 iterations")

    def test_ppid(self):
        if hasattr(os, 'getppid'):
            self.assertEqual(psutil.Process().ppid(), os.getppid())
        this_parent = os.getpid()
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        self.assertEqual(p.ppid(), this_parent)
        self.assertEqual(p.parent().pid, this_parent)
        # no other process is supposed to have us as parent
        reap_children(recursive=True)
        if APPVEYOR:
            # Occasional failures, see:
            # https://ci.appveyor.com/project/giampaolo/psutil/build/
            #     job/0hs623nenj7w4m33
            return
        for p in psutil.process_iter():
            if p.pid == sproc.pid:
                continue
            # XXX: sometimes this fails on Windows; not sure why.
            self.assertNotEqual(p.ppid(), this_parent, msg=p)

    def test_children(self):
        p = psutil.Process()
        self.assertEqual(p.children(), [])
        self.assertEqual(p.children(recursive=True), [])
        sproc = get_test_subprocess()
        children1 = p.children()
        children2 = p.children(recursive=True)
        for children in (children1, children2):
            self.assertEqual(len(children), 1)
            self.assertEqual(children[0].pid, sproc.pid)
            self.assertEqual(children[0].ppid(), os.getpid())

    def test_children_recursive(self):
        # here we create a subprocess which creates another one as in:
        # A (parent) -> B (child) -> C (grandchild)
        s = "import subprocess, os, sys, time;"
        s += "PYTHON = os.path.realpath(sys.executable);"
        s += "cmd = [PYTHON, '-c', 'import time; time.sleep(60);'];"
        s += "subprocess.Popen(cmd);"
        s += "time.sleep(60);"
        get_test_subprocess(cmd=[PYTHON, "-c", s])
        p = psutil.Process()
        self.assertEqual(len(p.children(recursive=False)), 1)
        # give the grandchild some time to start
        stop_at = time.time() + GLOBAL_TIMEOUT
        while time.time() < stop_at:
            children = p.children(recursive=True)
            if len(children) > 1:
                break
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0].ppid(), os.getpid())
        self.assertEqual(children[1].ppid(), children[0].pid)

    def test_children_duplicates(self):
        # find the process which has the highest number of children
        table = collections.defaultdict(int)
        for p in psutil.process_iter():
            try:
                table[p.ppid()] += 1
            except psutil.Error:
                pass
        # this is the one, now let's make sure there are no duplicates
        pid = sorted(table.items(), key=lambda x: x[1])[-1][0]
        p = psutil.Process(pid)
        try:
            c = p.children(recursive=True)
        except psutil.AccessDenied:  # windows
            pass
        else:
            self.assertEqual(len(c), len(set(c)))

    def test_suspend_resume(self):
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        p.suspend()
        for x in range(100):
            if p.status() == psutil.STATUS_STOPPED:
                break
            time.sleep(0.01)
        p.resume()
        self.assertNotEqual(p.status(), psutil.STATUS_STOPPED)

    def test_invalid_pid(self):
        self.assertRaises(TypeError, psutil.Process, "1")
        self.assertRaises(ValueError, psutil.Process, -1)

    def test_as_dict(self):
        p = psutil.Process()
        d = p.as_dict(attrs=['exe', 'name'])
        self.assertEqual(sorted(d.keys()), ['exe', 'name'])

        p = psutil.Process(min(psutil.pids()))
        d = p.as_dict(attrs=['connections'], ad_value='foo')
        if not isinstance(d['connections'], list):
            self.assertEqual(d['connections'], 'foo')

        # Test ad_value is set on AccessDenied.
        with mock.patch('psutil.Process.nice', create=True,
                        side_effect=psutil.AccessDenied):
            self.assertEqual(
                p.as_dict(attrs=["nice"], ad_value=1), {"nice": 1})

        # Test that NoSuchProcess bubbles up.
        with mock.patch('psutil.Process.nice', create=True,
                        side_effect=psutil.NoSuchProcess(p.pid, "name")):
            self.assertRaises(
                psutil.NoSuchProcess, p.as_dict, attrs=["nice"])

        # Test that ZombieProcess is swallowed.
        with mock.patch('psutil.Process.nice', create=True,
                        side_effect=psutil.ZombieProcess(p.pid, "name")):
            self.assertEqual(
                p.as_dict(attrs=["nice"], ad_value="foo"), {"nice": "foo"})

        # By default APIs raising NotImplementedError are
        # supposed to be skipped.
        with mock.patch('psutil.Process.nice', create=True,
                        side_effect=NotImplementedError):
            d = p.as_dict()
            self.assertNotIn('nice', list(d.keys()))
            # ...unless the user explicitly asked for some attr.
            with self.assertRaises(NotImplementedError):
                p.as_dict(attrs=["nice"])

        # errors
        with self.assertRaises(TypeError):
            p.as_dict('name')
        with self.assertRaises(ValueError):
            p.as_dict(['foo'])
        with self.assertRaises(ValueError):
            p.as_dict(['foo', 'bar'])

    def test_oneshot(self):
        with mock.patch("psutil._psplatform.Process.cpu_times") as m:
            p = psutil.Process()
            with p.oneshot():
                p.cpu_times()
                p.cpu_times()
            self.assertEqual(m.call_count, 1)

        with mock.patch("psutil._psplatform.Process.cpu_times") as m:
            p.cpu_times()
            p.cpu_times()
        self.assertEqual(m.call_count, 2)

    def test_oneshot_twice(self):
        # Test the case where the ctx manager is __enter__ed twice.
        # The second __enter__ is supposed to resut in a NOOP.
        with mock.patch("psutil._psplatform.Process.cpu_times") as m1:
            with mock.patch("psutil._psplatform.Process.oneshot_enter") as m2:
                p = psutil.Process()
                with p.oneshot():
                    p.cpu_times()
                    p.cpu_times()
                    with p.oneshot():
                        p.cpu_times()
                        p.cpu_times()
                self.assertEqual(m1.call_count, 1)
                self.assertEqual(m2.call_count, 1)

        with mock.patch("psutil._psplatform.Process.cpu_times") as m:
            p.cpu_times()
            p.cpu_times()
        self.assertEqual(m.call_count, 2)

    def test_halfway_terminated_process(self):
        # Test that NoSuchProcess exception gets raised in case the
        # process dies after we create the Process object.
        # Example:
        #  >>> proc = Process(1234)
        # >>> time.sleep(2)  # time-consuming task, process dies in meantime
        #  >>> proc.name()
        # Refers to Issue #15
        sproc = get_test_subprocess()
        p = psutil.Process(sproc.pid)
        p.terminate()
        p.wait()
        if WINDOWS:
            call_until(psutil.pids, "%s not in ret" % p.pid)
        self.assertFalse(p.is_running())
        # self.assertFalse(p.pid in psutil.pids(), msg="retcode = %s" %
        #   retcode)

        excluded_names = ['pid', 'is_running', 'wait', 'create_time',
                          'oneshot', 'memory_info_ex']
        if LINUX and not RLIMIT_SUPPORT:
            excluded_names.append('rlimit')
        for name in dir(p):
            if (name.startswith('_') or
                    name in excluded_names):
                continue
            try:
                meth = getattr(p, name)
                # get/set methods
                if name == 'nice':
                    if POSIX:
                        ret = meth(1)
                    else:
                        ret = meth(psutil.NORMAL_PRIORITY_CLASS)
                elif name == 'ionice':
                    ret = meth()
                    ret = meth(2)
                elif name == 'rlimit':
                    ret = meth(psutil.RLIMIT_NOFILE)
                    ret = meth(psutil.RLIMIT_NOFILE, (5, 5))
                elif name == 'cpu_affinity':
                    ret = meth()
                    ret = meth([0])
                elif name == 'send_signal':
                    ret = meth(signal.SIGTERM)
                else:
                    ret = meth()
            except psutil.ZombieProcess:
                self.fail("ZombieProcess for %r was not supposed to happen" %
                          name)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                if OPENBSD and name in ('threads', 'num_threads'):
                    pass
                else:
                    raise
            except NotImplementedError:
                pass
            else:
                self.fail(
                    "NoSuchProcess exception not raised for %r, retval=%s" % (
                        name, ret))

    @unittest.skipUnless(POSIX, 'POSIX only')
    def test_zombie_process(self):
        def succeed_or_zombie_p_exc(fun, *args, **kwargs):
            try:
                return fun(*args, **kwargs)
            except (psutil.ZombieProcess, psutil.AccessDenied):
                pass

        # Note: in this test we'll be creating two sub processes.
        # Both of them are supposed to be freed / killed by
        # reap_children() as they are attributable to 'us'
        # (os.getpid()) via children(recursive=True).
        unix_file = tempfile.mktemp(prefix=TESTFILE_PREFIX) if OSX else TESTFN
        src = textwrap.dedent("""\
        import os, sys, time, socket, contextlib
        child_pid = os.fork()
        if child_pid > 0:
            time.sleep(3000)
        else:
            # this is the zombie process
            s = socket.socket(socket.AF_UNIX)
            with contextlib.closing(s):
                s.connect('%s')
                if sys.version_info < (3, ):
                    pid = str(os.getpid())
                else:
                    pid = bytes(str(os.getpid()), 'ascii')
                s.sendall(pid)
        """ % unix_file)
        with contextlib.closing(socket.socket(socket.AF_UNIX)) as sock:
            try:
                sock.settimeout(GLOBAL_TIMEOUT)
                sock.bind(unix_file)
                sock.listen(1)
                pyrun(src)
                conn, _ = sock.accept()
                self.addCleanup(conn.close)
                select.select([conn.fileno()], [], [], GLOBAL_TIMEOUT)
                zpid = int(conn.recv(1024))
                zproc = psutil.Process(zpid)
                call_until(lambda: zproc.status(),
                           "ret == psutil.STATUS_ZOMBIE")
                # A zombie process should always be instantiable
                zproc = psutil.Process(zpid)
                # ...and at least its status always be querable
                self.assertEqual(zproc.status(), psutil.STATUS_ZOMBIE)
                # ...and it should be considered 'running'
                self.assertTrue(zproc.is_running())
                # ...and as_dict() shouldn't crash
                zproc.as_dict()
                # if cmdline succeeds it should be an empty list
                ret = succeed_or_zombie_p_exc(zproc.suspend)
                if ret is not None:
                    self.assertEqual(ret, [])

                if hasattr(zproc, "rlimit"):
                    succeed_or_zombie_p_exc(zproc.rlimit, psutil.RLIMIT_NOFILE)
                    succeed_or_zombie_p_exc(zproc.rlimit, psutil.RLIMIT_NOFILE,
                                            (5, 5))
                # set methods
                succeed_or_zombie_p_exc(zproc.parent)
                if hasattr(zproc, 'cpu_affinity'):
                    succeed_or_zombie_p_exc(zproc.cpu_affinity, [0])
                succeed_or_zombie_p_exc(zproc.nice, 0)
                if hasattr(zproc, 'ionice'):
                    if LINUX:
                        succeed_or_zombie_p_exc(zproc.ionice, 2, 0)
                    else:
                        succeed_or_zombie_p_exc(zproc.ionice, 0)  # Windows
                if hasattr(zproc, 'rlimit'):
                    succeed_or_zombie_p_exc(zproc.rlimit,
                                            psutil.RLIMIT_NOFILE, (5, 5))
                succeed_or_zombie_p_exc(zproc.suspend)
                succeed_or_zombie_p_exc(zproc.resume)
                succeed_or_zombie_p_exc(zproc.terminate)
                succeed_or_zombie_p_exc(zproc.kill)

                # ...its parent should 'see' it
                # edit: not true on BSD and OSX
                # descendants = [x.pid for x in psutil.Process().children(
                #                recursive=True)]
                # self.assertIn(zpid, descendants)
                # XXX should we also assume ppid be usable?  Note: this
                # would be an important use case as the only way to get
                # rid of a zombie is to kill its parent.
                # self.assertEqual(zpid.ppid(), os.getpid())
                # ...and all other APIs should be able to deal with it
                self.assertTrue(psutil.pid_exists(zpid))
                self.assertIn(zpid, psutil.pids())
                self.assertIn(zpid, [x.pid for x in psutil.process_iter()])
                psutil._pmap = {}
                self.assertIn(zpid, [x.pid for x in psutil.process_iter()])
            finally:
                reap_children(recursive=True)

    def test_pid_0(self):
        # Process(0) is supposed to work on all platforms except Linux
        if 0 not in psutil.pids():
            self.assertRaises(psutil.NoSuchProcess, psutil.Process, 0)
            return

        # test all methods
        p = psutil.Process(0)
        for name in psutil._as_dict_attrnames:
            if name == 'pid':
                continue
            meth = getattr(p, name)
            try:
                ret = meth()
            except psutil.AccessDenied:
                pass
            else:
                if name in ("uids", "gids"):
                    self.assertEqual(ret.real, 0)
                elif name == "username":
                    if POSIX:
                        self.assertEqual(p.username(), 'root')
                    elif WINDOWS:
                        self.assertEqual(p.username(), 'NT AUTHORITY\\SYSTEM')
                elif name == "name":
                    assert name, name

        if hasattr(p, 'rlimit'):
            try:
                p.rlimit(psutil.RLIMIT_FSIZE)
            except psutil.AccessDenied:
                pass

        p.as_dict()

        if not OPENBSD:
            self.assertIn(0, psutil.pids())
            self.assertTrue(psutil.pid_exists(0))

    def test_Popen(self):
        # XXX this test causes a ResourceWarning on Python 3 because
        # psutil.__subproc instance doesn't get propertly freed.
        # Not sure what to do though.
        cmd = [PYTHON, "-c", "import time; time.sleep(60);"]
        proc = psutil.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
        try:
            proc.name()
            proc.cpu_times()
            proc.stdin
            self.assertTrue(dir(proc))
            self.assertRaises(AttributeError, getattr, proc, 'foo')
        finally:
            proc.kill()
            proc.wait()

    def test_Popen_ctx_manager(self):
        with psutil.Popen([PYTHON, "-V"],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,
                          stdin=subprocess.PIPE) as proc:
            pass
        assert proc.stdout.closed
        assert proc.stderr.closed
        assert proc.stdin.closed

    @unittest.skipUnless(hasattr(psutil.Process, "environ"),
                         "platform not supported")
    def test_environ(self):
        self.maxDiff = None
        p = psutil.Process()
        d = p.environ()
        d2 = os.environ.copy()

        removes = []
        if OSX:
            removes.extend([
                "__CF_USER_TEXT_ENCODING",
                "VERSIONER_PYTHON_PREFER_32_BIT",
                "VERSIONER_PYTHON_VERSION"])
        if LINUX or OSX:
            removes.extend(['PLAT'])
        if TOX:
            removes.extend(['HOME'])
        for key in removes:
            d.pop(key, None)
            d2.pop(key, None)

        self.assertEqual(d, d2)

    @unittest.skipUnless(hasattr(psutil.Process, "environ"),
                         "platform not supported")
    @unittest.skipUnless(POSIX, "posix only")
    def test_weird_environ(self):
        # environment variables can contain values without an equals sign
        code = textwrap.dedent("""
        #include <unistd.h>
        #include <fcntl.h>
        char * const argv[] = {"cat", 0};
        char * const envp[] = {"A=1", "X", "C=3", 0};
        int main(void) {
            /* Close stderr on exec so parent can wait for the execve to
             * finish. */
            if (fcntl(2, F_SETFD, FD_CLOEXEC) != 0)
                return 0;
            return execve("/bin/cat", argv, envp);
        }
        """)
        path = TESTFN
        create_exe(path, c_code=code)
        self.addCleanup(safe_rmpath, path)
        sproc = get_test_subprocess([path],
                                    stdin=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        p = psutil.Process(sproc.pid)
        wait_for_pid(p.pid)
        self.assertTrue(p.is_running())
        # Wait for process to exec or exit.
        self.assertEqual(sproc.stderr.read(), b"")
        self.assertEqual(p.environ(), {"A": "1", "C": "3"})
        sproc.communicate()
        self.assertEqual(sproc.returncode, 0)


# ===================================================================
# --- Featch all processes test
# ===================================================================

class TestFetchAllProcesses(unittest.TestCase):
    """Test which iterates over all running processes and performs
    some sanity checks against Process API's returned values.
    """

    def setUp(self):
        if POSIX:
            import pwd
            import grp
            users = pwd.getpwall()
            groups = grp.getgrall()
            self.all_uids = set([x.pw_uid for x in users])
            self.all_usernames = set([x.pw_name for x in users])
            self.all_gids = set([x.gr_gid for x in groups])

    def test_fetch_all(self):
        valid_procs = 0
        excluded_names = set([
            'send_signal', 'suspend', 'resume', 'terminate', 'kill', 'wait',
            'as_dict', 'cpu_percent', 'parent', 'children', 'pid',
            'memory_info_ex', 'oneshot',
        ])
        if LINUX and not RLIMIT_SUPPORT:
            excluded_names.add('rlimit')
        attrs = []
        for name in dir(psutil.Process):
            if name.startswith("_"):
                continue
            if name in excluded_names:
                continue
            attrs.append(name)

        default = object()
        failures = []
        for p in psutil.process_iter():
            with p.oneshot():
                for name in attrs:
                    ret = default
                    try:
                        args = ()
                        attr = getattr(p, name, None)
                        if attr is not None and callable(attr):
                            if name == 'rlimit':
                                args = (psutil.RLIMIT_NOFILE,)
                            ret = attr(*args)
                        else:
                            ret = attr
                        valid_procs += 1
                    except NotImplementedError:
                        msg = "%r was skipped because not implemented" % (
                            self.__class__.__name__ + '.test_' + name)
                        warn(msg)
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as err:
                        self.assertEqual(err.pid, p.pid)
                        if err.name:
                            # make sure exception's name attr is set
                            # with the actual process name
                            self.assertEqual(err.name, p.name())
                        self.assertTrue(str(err))
                        self.assertTrue(err.msg)
                    except Exception as err:
                        s = '\n' + '=' * 70 + '\n'
                        s += "FAIL: test_%s (proc=%s" % (name, p)
                        if ret != default:
                            s += ", ret=%s)" % repr(ret)
                        s += ')\n'
                        s += '-' * 70
                        s += "\n%s" % traceback.format_exc()
                        s = "\n".join((" " * 4) + i for i in s.splitlines())
                        s += '\n'
                        failures.append(s)
                        break
                    else:
                        if ret not in (0, 0.0, [], None, '', {}):
                            assert ret, ret
                        meth = getattr(self, name)
                        meth(ret, p)

        if failures:
            self.fail(''.join(failures))

        # we should always have a non-empty list, not including PID 0 etc.
        # special cases.
        self.assertTrue(valid_procs > 0)

    def cmdline(self, ret, proc):
        pass

    def exe(self, ret, proc):
        if not ret:
            self.assertEqual(ret, '')
        else:
            assert os.path.isabs(ret), ret
            # Note: os.stat() may return False even if the file is there
            # hence we skip the test, see:
            # http://stackoverflow.com/questions/3112546/os-path-exists-lies
            if POSIX and os.path.isfile(ret):
                if hasattr(os, 'access') and hasattr(os, "X_OK"):
                    # XXX may fail on OSX
                    self.assertTrue(os.access(ret, os.X_OK))

    def ppid(self, ret, proc):
        self.assertTrue(ret >= 0)

    def name(self, ret, proc):
        self.assertIsInstance(ret, (str, unicode))
        self.assertTrue(ret)

    def create_time(self, ret, proc):
        try:
            self.assertGreaterEqual(ret, 0)
        except AssertionError:
            if OPENBSD and proc.status == psutil.STATUS_ZOMBIE:
                pass
            else:
                raise
        # this can't be taken for granted on all platforms
        # self.assertGreaterEqual(ret, psutil.boot_time())
        # make sure returned value can be pretty printed
        # with strftime
        time.strftime("%Y %m %d %H:%M:%S", time.localtime(ret))

    def uids(self, ret, proc):
        for uid in ret:
            self.assertGreaterEqual(uid, 0)
            self.assertIn(uid, self.all_uids)

    def gids(self, ret, proc):
        # note: testing all gids as above seems not to be reliable for
        # gid == 30 (nodoby); not sure why.
        for gid in ret:
            if not OSX and not NETBSD:
                self.assertGreaterEqual(gid, 0)
                self.assertIn(gid, self.all_gids)

    def username(self, ret, proc):
        self.assertTrue(ret)
        if POSIX:
            self.assertIn(ret, self.all_usernames)

    def status(self, ret, proc):
        self.assertTrue(ret != "")
        self.assertTrue(ret != '?')
        self.assertIn(ret, VALID_PROC_STATUSES)

    def io_counters(self, ret, proc):
        for field in ret:
            if field != -1:
                self.assertTrue(field >= 0)

    def ionice(self, ret, proc):
        if LINUX:
            self.assertTrue(ret.ioclass >= 0)
            self.assertTrue(ret.value >= 0)
        else:
            self.assertTrue(ret >= 0)
            self.assertIn(ret, (0, 1, 2))

    def num_threads(self, ret, proc):
        self.assertTrue(ret >= 1)

    def threads(self, ret, proc):
        for t in ret:
            self.assertTrue(t.id >= 0)
            self.assertTrue(t.user_time >= 0)
            self.assertTrue(t.system_time >= 0)

    def cpu_times(self, ret, proc):
        self.assertTrue(ret.user >= 0)
        self.assertTrue(ret.system >= 0)

    def cpu_num(self, ret, proc):
        self.assertGreaterEqual(ret, 0)
        if psutil.cpu_count() == 1:
            self.assertEqual(ret, 0)
        self.assertIn(ret, range(psutil.cpu_count()))

    def memory_info(self, ret, proc):
        for name in ret._fields:
            self.assertGreaterEqual(getattr(ret, name), 0)
        if POSIX and ret.vms != 0:
            # VMS is always supposed to be the highest
            for name in ret._fields:
                if name != 'vms':
                    value = getattr(ret, name)
                    assert ret.vms > value, ret
        elif WINDOWS:
            assert ret.peak_wset >= ret.wset, ret
            assert ret.peak_paged_pool >= ret.paged_pool, ret
            assert ret.peak_nonpaged_pool >= ret.nonpaged_pool, ret
            assert ret.peak_pagefile >= ret.pagefile, ret

    def memory_full_info(self, ret, proc):
        total = psutil.virtual_memory().total
        for name in ret._fields:
            value = getattr(ret, name)
            self.assertGreaterEqual(value, 0, msg=(name, value))
            self.assertLessEqual(value, total, msg=(name, value, total))

        if LINUX:
            self.assertGreaterEqual(ret.pss, ret.uss)

    def open_files(self, ret, proc):
        for f in ret:
            if WINDOWS:
                assert f.fd == -1, f
            else:
                self.assertIsInstance(f.fd, int)
            if LINUX:
                self.assertIsInstance(f.position, int)
                self.assertGreaterEqual(f.position, 0)
                self.assertIn(f.mode, ('r', 'w', 'a', 'r+', 'a+'))
                self.assertGreater(f.flags, 0)
            if BSD and not f.path:
                # XXX see: https://github.com/giampaolo/psutil/issues/595
                continue
            assert os.path.isabs(f.path), f
            assert os.path.isfile(f.path), f

    def num_fds(self, ret, proc):
        self.assertTrue(ret >= 0)

    def connections(self, ret, proc):
        self.assertEqual(len(ret), len(set(ret)))
        for conn in ret:
            check_connection_ntuple(conn)

    def cwd(self, ret, proc):
        if ret is not None:  # BSD may return None
            assert os.path.isabs(ret), ret
            try:
                st = os.stat(ret)
            except OSError as err:
                if WINDOWS and err.errno in \
                        psutil._psplatform.ACCESS_DENIED_SET:
                    pass
                # directory has been removed in mean time
                elif err.errno != errno.ENOENT:
                    raise
            else:
                self.assertTrue(stat.S_ISDIR(st.st_mode))

    def memory_percent(self, ret, proc):
        assert 0 <= ret <= 100, ret

    def is_running(self, ret, proc):
        self.assertTrue(ret)

    def cpu_affinity(self, ret, proc):
        assert ret != [], ret
        cpus = range(psutil.cpu_count())
        for n in ret:
            self.assertIn(n, cpus)

    def terminal(self, ret, proc):
        if ret is not None:
            assert os.path.isabs(ret), ret
            assert os.path.exists(ret), ret

    def memory_maps(self, ret, proc):
        for nt in ret:
            for fname in nt._fields:
                value = getattr(nt, fname)
                if fname == 'path':
                    if not value.startswith('['):
                        assert os.path.isabs(nt.path), nt.path
                        # commented as on Linux we might get
                        # '/foo/bar (deleted)'
                        # assert os.path.exists(nt.path), nt.path
                elif fname in ('addr', 'perms'):
                    self.assertTrue(value)
                else:
                    self.assertIsInstance(value, (int, long))
                    assert value >= 0, value

    def num_handles(self, ret, proc):
        if WINDOWS:
            self.assertGreaterEqual(ret, 0)
        else:
            self.assertGreaterEqual(ret, 0)

    def nice(self, ret, proc):
        if POSIX:
            assert -20 <= ret <= 20, ret
        else:
            priorities = [getattr(psutil, x) for x in dir(psutil)
                          if x.endswith('_PRIORITY_CLASS')]
            self.assertIn(ret, priorities)

    def num_ctx_switches(self, ret, proc):
        self.assertGreaterEqual(ret.voluntary, 0)
        self.assertGreaterEqual(ret.involuntary, 0)

    def rlimit(self, ret, proc):
        self.assertEqual(len(ret), 2)
        self.assertGreaterEqual(ret[0], -1)
        self.assertGreaterEqual(ret[1], -1)

    def environ(self, ret, proc):
        self.assertIsInstance(ret, dict)


# ===================================================================
# --- Limited user tests
# ===================================================================


if POSIX and os.getuid() == 0:
    class LimitedUserTestCase(TestProcess):
        """Repeat the previous tests by using a limited user.
        Executed only on UNIX and only if the user who run the test script
        is root.
        """
        # the uid/gid the test suite runs under
        if hasattr(os, 'getuid'):
            PROCESS_UID = os.getuid()
            PROCESS_GID = os.getgid()

        def __init__(self, *args, **kwargs):
            TestProcess.__init__(self, *args, **kwargs)
            # re-define all existent test methods in order to
            # ignore AccessDenied exceptions
            for attr in [x for x in dir(self) if x.startswith('test')]:
                meth = getattr(self, attr)

                def test_(self):
                    try:
                        meth()
                    except psutil.AccessDenied:
                        pass
                setattr(self, attr, types.MethodType(test_, self))

        def setUp(self):
            safe_rmpath(TESTFN)
            TestProcess.setUp(self)
            os.setegid(1000)
            os.seteuid(1000)

        def tearDown(self):
            os.setegid(self.PROCESS_UID)
            os.seteuid(self.PROCESS_GID)
            TestProcess.tearDown(self)

        def test_nice(self):
            try:
                psutil.Process().nice(-1)
            except psutil.AccessDenied:
                pass
            else:
                self.fail("exception not raised")

        def test_zombie_process(self):
            # causes problems if test test suite is run as root
            pass


# ===================================================================
# --- Unicode tests
# ===================================================================


class TestUnicode(unittest.TestCase):
    """
    Make sure that APIs returning a string are able to handle unicode,
    see: https://github.com/giampaolo/psutil/issues/655
    """
    uexe = TESTFN + 'èfile'
    udir = TESTFN + 'èdir'

    @classmethod
    def setUpClass(cls):
        safe_rmpath(cls.uexe)
        safe_rmpath(cls.udir)
        create_exe(cls.uexe)
        os.mkdir(cls.udir)

    @classmethod
    def tearDownClass(cls):
        if not APPVEYOR:
            safe_rmpath(cls.uexe)
            safe_rmpath(cls.udir)

    def setUp(self):
        reap_children()

    tearDown = setUp

    def test_proc_exe(self):
        subp = get_test_subprocess(cmd=[self.uexe])
        p = psutil.Process(subp.pid)
        self.assertIsInstance(p.name(), str)
        if not OSX and TRAVIS:
            self.assertEqual(p.exe(), self.uexe)
        else:
            p.exe()

    def test_proc_name(self):
        subp = get_test_subprocess(cmd=[self.uexe])
        if WINDOWS:
            # XXX: why is this like this?
            from psutil._pswindows import py2_strencode
            name = py2_strencode(psutil._psplatform.cext.proc_name(subp.pid))
        else:
            name = psutil.Process(subp.pid).name()
        if not OSX and TRAVIS:
            self.assertEqual(name, os.path.basename(self.uexe))

    def test_proc_cmdline(self):
        subp = get_test_subprocess(cmd=[self.uexe])
        p = psutil.Process(subp.pid)
        self.assertIsInstance("".join(p.cmdline()), str)
        if not OSX and TRAVIS:
            self.assertEqual(p.cmdline(), [self.uexe])
        else:
            p.cmdline()

    def test_proc_cwd(self):
        with chdir(self.udir):
            p = psutil.Process()
            self.assertIsInstance(p.cwd(), str)
            if not OSX and TRAVIS:
                self.assertEqual(p.cwd(), self.udir)
            else:
                p.cwd()

    # @unittest.skipIf(APPVEYOR, "unreliable on APPVEYOR")
    def test_proc_open_files(self):
        p = psutil.Process()
        start = set(p.open_files())
        with open(self.uexe, 'rb'):
            new = set(p.open_files())
        path = (new - start).pop().path
        if BSD and not path:
            # XXX
            # see https://github.com/giampaolo/psutil/issues/595
            self.skipTest("open_files on BSD is broken")
        self.assertIsInstance(path, str)
        if not OSX and TRAVIS:
            self.assertEqual(os.path.normcase(path),
                             os.path.normcase(self.uexe))

    @unittest.skipUnless(hasattr(psutil.Process, "environ"),
                         "platform not supported")
    def test_proc_environ(self):
        env = os.environ.copy()
        env['FUNNY_ARG'] = self.uexe
        sproc = get_test_subprocess(env=env)
        p = psutil.Process(sproc.pid)
        if WINDOWS and not PY3:
            uexe = self.uexe.decode(sys.getfilesystemencoding())
        else:
            uexe = self.uexe
        if not OSX and TRAVIS:
            self.assertEqual(p.environ()['FUNNY_ARG'], uexe)
        else:
            p.environ()

    def test_disk_usage(self):
        psutil.disk_usage(self.udir)


class TestInvalidUnicode(TestUnicode):
    """Test handling of invalid utf8 data."""
    if PY3:
        uexe = (TESTFN.encode('utf8') + b"f\xc0\x80").decode(
            'utf8', 'surrogateescape')
        udir = (TESTFN.encode('utf8') + b"d\xc0\x80").decode(
            'utf8', 'surrogateescape')
    else:
        uexe = TESTFN + b"f\xc0\x80"
        udir = TESTFN + b"d\xc0\x80"


if __name__ == '__main__':
    run_test_module_by_name(__file__)
