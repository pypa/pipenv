#!/usr/bin/env python

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Tests for detecting function memory leaks (typically the ones
implemented in C). It does so by calling a function many times and
checking whether process memory usage keeps increasing between
calls or over time.
Note that this may produce false positives (especially on Windows
for some reason).
"""

import errno
import functools
import gc
import os
import socket
import threading
import time

import psutil
import psutil._common
from psutil import FREEBSD
from psutil import LINUX
from psutil import OPENBSD
from psutil import OSX
from psutil import POSIX
from psutil import SUNOS
from psutil import WINDOWS
from psutil._common import supports_ipv6
from psutil._compat import xrange
from psutil.tests import get_test_subprocess
from psutil.tests import reap_children
from psutil.tests import RLIMIT_SUPPORT
from psutil.tests import run_test_module_by_name
from psutil.tests import safe_rmpath
from psutil.tests import TESTFN
from psutil.tests import TRAVIS
from psutil.tests import unittest


LOOPS = 1000
MEMORY_TOLERANCE = 4096
RETRY_FOR = 3

SKIP_PYTHON_IMPL = True if TRAVIS else False
cext = psutil._psplatform.cext
thisproc = psutil.Process()


# ===================================================================
# utils
# ===================================================================


def skip_if_linux():
    return unittest.skipIf(LINUX and SKIP_PYTHON_IMPL,
                           "worthless on LINUX (pure python)")


def bytes2human(n):
    """
    http://code.activestate.com/recipes/578019
    >>> bytes2human(10000)
    '9.8K'
    >>> bytes2human(100001221)
    '95.4M'
    """
    symbols = ('K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
    prefix = {}
    for i, s in enumerate(symbols):
        prefix[s] = 1 << (i + 1) * 10
    for s in reversed(symbols):
        if n >= prefix[s]:
            value = float(n) / prefix[s]
            return '%.2f%s' % (value, s)
    return "%sB" % n


class TestMemLeak(unittest.TestCase):
    """Base framework class which calls a function many times and
    produces a failure if process memory usage keeps increasing
    between calls or over time.
    """
    tolerance = MEMORY_TOLERANCE
    loops = LOOPS
    retry_for = RETRY_FOR

    def setUp(self):
        gc.collect()

    def execute(self, fun, *args, **kwargs):
        """Test a callable."""
        def call_many_times():
            for x in xrange(loops):
                self._call(fun, *args, **kwargs)
            del x
            gc.collect()

        tolerance = kwargs.pop('tolerance_', None) or self.tolerance
        loops = kwargs.pop('loops_', None) or self.loops
        retry_for = kwargs.pop('retry_for_', None) or self.retry_for

        self._call(fun, *args, **kwargs)
        self.assertEqual(gc.garbage, [])
        self.assertEqual(threading.active_count(), 1)

        # Get 2 distinct memory samples, before and after having
        # called fun repeadetly.
        # step 1
        call_many_times()
        mem1 = self._get_mem()
        # step 2
        call_many_times()
        mem2 = self._get_mem()

        diff1 = mem2 - mem1
        if diff1 > tolerance:
            # This doesn't necessarily mean we have a leak yet.
            # At this point we assume that after having called the
            # function so many times the memory usage is stabilized
            # and if there are no leaks it should not increase
            # anymore.
            # Let's keep calling fun for 3 more seconds and fail if
            # we notice any difference.
            ncalls = 0
            stop_at = time.time() + retry_for
            while time.time() <= stop_at:
                self._call(fun, *args, **kwargs)
                ncalls += 1

            del stop_at
            gc.collect()
            mem3 = self._get_mem()
            diff2 = mem3 - mem2

            if mem3 > mem2:
                # failure
                self.fail("+%s after %s calls, +%s after another %s calls" % (
                    bytes2human(diff1),
                    loops,
                    bytes2human(diff2),
                    ncalls
                ))

    def execute_w_exc(self, exc, fun, *args, **kwargs):
        """Convenience function which tests a callable raising
        an exception.
        """
        def call():
            self.assertRaises(exc, fun, *args, **kwargs)

        self.execute(call)

    @staticmethod
    def _get_mem():
        # By using USS memory it seems it's less likely to bump
        # into false positives.
        if LINUX or WINDOWS or OSX:
            return thisproc.memory_full_info().uss
        else:
            return thisproc.memory_info().rss

    @staticmethod
    def _call(fun, *args, **kwargs):
        fun(*args, **kwargs)


# ===================================================================
# Process class
# ===================================================================


class TestProcessObjectLeaks(TestMemLeak):
    """Test leaks of Process class methods."""

    proc = thisproc

    def test_coverage(self):
        skip = set((
            "pid", "as_dict", "children", "cpu_affinity", "cpu_percent",
            "ionice", "is_running", "kill", "memory_info_ex", "memory_percent",
            "nice", "oneshot", "parent", "rlimit", "send_signal", "suspend",
            "terminate", "wait"))
        for name in dir(psutil.Process):
            if name.startswith('_'):
                continue
            if name in skip:
                continue
            self.assertTrue(hasattr(self, "test_" + name), msg=name)

    @skip_if_linux()
    def test_name(self):
        self.execute(self.proc.name)

    @skip_if_linux()
    def test_cmdline(self):
        self.execute(self.proc.cmdline)

    @skip_if_linux()
    def test_exe(self):
        self.execute(self.proc.exe)

    @skip_if_linux()
    def test_ppid(self):
        self.execute(self.proc.ppid)

    @unittest.skipUnless(POSIX, "POSIX only")
    @skip_if_linux()
    def test_uids(self):
        self.execute(self.proc.uids)

    @unittest.skipUnless(POSIX, "POSIX only")
    @skip_if_linux()
    def test_gids(self):
        self.execute(self.proc.gids)

    @skip_if_linux()
    def test_status(self):
        self.execute(self.proc.status)

    def test_nice_get(self):
        self.execute(self.proc.nice)

    def test_nice_set(self):
        niceness = thisproc.nice()
        self.execute(self.proc.nice, niceness)

    @unittest.skipUnless(hasattr(psutil.Process, 'ionice'),
                         "platform not supported")
    def test_ionice_get(self):
        self.execute(self.proc.ionice)

    @unittest.skipUnless(hasattr(psutil.Process, 'ionice'),
                         "platform not supported")
    def test_ionice_set(self):
        if WINDOWS:
            value = thisproc.ionice()
            self.execute(self.proc.ionice, value)
        else:
            self.execute(self.proc.ionice, psutil.IOPRIO_CLASS_NONE)
            fun = functools.partial(cext.proc_ioprio_set, os.getpid(), -1, 0)
            self.execute_w_exc(OSError, fun)

    @unittest.skipIf(OSX or SUNOS, "platform not supported")
    @skip_if_linux()
    def test_io_counters(self):
        self.execute(self.proc.io_counters)

    @unittest.skipIf(POSIX, "worthless on POSIX")
    def test_username(self):
        self.execute(self.proc.username)

    @skip_if_linux()
    def test_create_time(self):
        self.execute(self.proc.create_time)

    @skip_if_linux()
    def test_num_threads(self):
        self.execute(self.proc.num_threads)

    @unittest.skipUnless(WINDOWS, "WINDOWS only")
    def test_num_handles(self):
        self.execute(self.proc.num_handles)

    @unittest.skipUnless(POSIX, "POSIX only")
    @skip_if_linux()
    def test_num_fds(self):
        self.execute(self.proc.num_fds)

    @skip_if_linux()
    def test_num_ctx_switches(self):
        self.execute(self.proc.num_ctx_switches)

    @skip_if_linux()
    def test_threads(self):
        self.execute(self.proc.threads)

    @skip_if_linux()
    def test_cpu_times(self):
        self.execute(self.proc.cpu_times)

    @skip_if_linux()
    @unittest.skipUnless(hasattr(psutil.Process, "cpu_num"),
                         "platform not supported")
    def test_cpu_num(self):
        self.execute(self.proc.cpu_num)

    @skip_if_linux()
    def test_memory_info(self):
        self.execute(self.proc.memory_info)

    # also available on Linux but it's pure python
    @unittest.skipUnless(OSX or WINDOWS,
                         "platform not supported")
    def test_memory_full_info(self):
        self.execute(self.proc.memory_full_info)

    @unittest.skipUnless(POSIX, "POSIX only")
    @skip_if_linux()
    def test_terminal(self):
        self.execute(self.proc.terminal)

    @unittest.skipIf(POSIX and SKIP_PYTHON_IMPL,
                     "worthless on POSIX (pure python)")
    def test_resume(self):
        self.execute(self.proc.resume)

    @skip_if_linux()
    def test_cwd(self):
        self.execute(self.proc.cwd)

    @unittest.skipUnless(WINDOWS or LINUX or FREEBSD,
                         "platform not supported")
    def test_cpu_affinity_get(self):
        self.execute(self.proc.cpu_affinity)

    @unittest.skipUnless(WINDOWS or LINUX or FREEBSD,
                         "platform not supported")
    def test_cpu_affinity_set(self):
        affinity = thisproc.cpu_affinity()
        self.execute(self.proc.cpu_affinity, affinity)
        if not TRAVIS:
            self.execute_w_exc(ValueError, self.proc.cpu_affinity, [-1])

    @skip_if_linux()
    def test_open_files(self):
        safe_rmpath(TESTFN)  # needed after UNIX socket test has run
        with open(TESTFN, 'w'):
            self.execute(self.proc.open_files)

    # OSX implementation is unbelievably slow
    @unittest.skipIf(OSX, "too slow on OSX")
    @unittest.skipIf(OPENBSD, "platform not supported")
    @skip_if_linux()
    def test_memory_maps(self):
        self.execute(self.proc.memory_maps)

    @unittest.skipUnless(LINUX, "LINUX only")
    @unittest.skipUnless(LINUX and RLIMIT_SUPPORT, "LINUX >= 2.6.36 only")
    def test_rlimit_get(self):
        self.execute(self.proc.rlimit, psutil.RLIMIT_NOFILE)

    @unittest.skipUnless(LINUX, "LINUX only")
    @unittest.skipUnless(LINUX and RLIMIT_SUPPORT, "LINUX >= 2.6.36 only")
    def test_rlimit_set(self):
        limit = thisproc.rlimit(psutil.RLIMIT_NOFILE)
        self.execute(self.proc.rlimit, psutil.RLIMIT_NOFILE, limit)
        self.execute_w_exc(OSError, self.proc.rlimit, -1)

    @skip_if_linux()
    # Windows implementation is based on a single system-wide
    # function (tested later).
    @unittest.skipIf(WINDOWS, "worthless on WINDOWS")
    def test_connections(self):
        def create_socket(family, type):
            sock = socket.socket(family, type)
            sock.bind(('', 0))
            if type == socket.SOCK_STREAM:
                sock.listen(1)
            return sock

        socks = []
        socks.append(create_socket(socket.AF_INET, socket.SOCK_STREAM))
        socks.append(create_socket(socket.AF_INET, socket.SOCK_DGRAM))
        if supports_ipv6():
            socks.append(create_socket(socket.AF_INET6, socket.SOCK_STREAM))
            socks.append(create_socket(socket.AF_INET6, socket.SOCK_DGRAM))
        if hasattr(socket, 'AF_UNIX'):
            safe_rmpath(TESTFN)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(TESTFN)
            s.listen(1)
            socks.append(s)
        kind = 'all'
        # TODO: UNIX sockets are temporarily implemented by parsing
        # 'pfiles' cmd  output; we don't want that part of the code to
        # be executed.
        if SUNOS:
            kind = 'inet'
        try:
            self.execute(self.proc.connections, kind)
        finally:
            for s in socks:
                s.close()

    @unittest.skipUnless(hasattr(psutil.Process, 'environ'),
                         "platform not supported")
    def test_environ(self):
        self.execute(self.proc.environ)

    @unittest.skipUnless(WINDOWS, "WINDOWS only")
    def test_proc_info(self):
        self.execute(cext.proc_info, os.getpid())


class TestTerminatedProcessLeaks(TestProcessObjectLeaks):
    """Repeat the tests above looking for leaks occurring when dealing
    with terminated processes raising NoSuchProcess exception.
    The C functions are still invoked but will follow different code
    paths. We'll check those code paths.
    """

    @classmethod
    def setUpClass(cls):
        super(TestTerminatedProcessLeaks, cls).setUpClass()
        p = get_test_subprocess()
        cls.proc = psutil.Process(p.pid)
        cls.proc.kill()
        cls.proc.wait()

    @classmethod
    def tearDownClass(cls):
        super(TestTerminatedProcessLeaks, cls).tearDownClass()
        reap_children()

    def _call(self, fun, *args, **kwargs):
        try:
            fun(*args, **kwargs)
        except psutil.NoSuchProcess:
            pass

    if WINDOWS:

        def test_kill(self):
            self.execute(self.proc.kill)

        def test_terminate(self):
            self.execute(self.proc.terminate)

        def test_suspend(self):
            self.execute(self.proc.suspend)

        def test_resume(self):
            self.execute(self.proc.resume)

        def test_wait(self):
            self.execute(self.proc.wait)

        def test_proc_info(self):
            # test dual implementation
            def call():
                try:
                    return cext.proc_info(self.proc.pid)
                except OSError as err:
                    if err.errno != errno.ESRCH:
                        raise

            self.execute(call)


# ===================================================================
# system APIs
# ===================================================================


class TestModuleFunctionsLeaks(TestMemLeak):
    """Test leaks of psutil module functions."""

    def test_coverage(self):
        skip = set((
            "version_info", "__version__", "process_iter", "wait_procs",
            "cpu_percent", "cpu_times_percent", "cpu_count"))
        for name in psutil.__all__:
            if not name.islower():
                continue
            if name in skip:
                continue
            self.assertTrue(hasattr(self, "test_" + name), msg=name)

    # --- cpu

    @skip_if_linux()
    def test_cpu_count_logical(self):
        self.execute(psutil.cpu_count, logical=True)

    @skip_if_linux()
    def test_cpu_count_physical(self):
        self.execute(psutil.cpu_count, logical=False)

    @skip_if_linux()
    def test_cpu_times(self):
        self.execute(psutil.cpu_times)

    @skip_if_linux()
    def test_per_cpu_times(self):
        self.execute(psutil.cpu_times, percpu=True)

    def test_cpu_stats(self):
        self.execute(psutil.cpu_stats)

    @skip_if_linux()
    @unittest.skipUnless(hasattr(psutil, "cpu_freq"), "platform not supported")
    def test_cpu_freq(self):
        self.execute(psutil.cpu_freq)

    # --- mem

    def test_virtual_memory(self):
        self.execute(psutil.virtual_memory)

    # TODO: remove this skip when this gets fixed
    @unittest.skipIf(SUNOS,
                     "worthless on SUNOS (uses a subprocess)")
    def test_swap_memory(self):
        self.execute(psutil.swap_memory)

    @unittest.skipIf(POSIX and SKIP_PYTHON_IMPL,
                     "worthless on POSIX (pure python)")
    def test_pid_exists(self):
        self.execute(psutil.pid_exists, os.getpid())

    # --- disk

    @unittest.skipIf(POSIX and SKIP_PYTHON_IMPL,
                     "worthless on POSIX (pure python)")
    def test_disk_usage(self):
        self.execute(psutil.disk_usage, '.')

    def test_disk_partitions(self):
        self.execute(psutil.disk_partitions)

    @unittest.skipIf(LINUX and not os.path.exists('/proc/diskstats'),
                     '/proc/diskstats not available on this Linux version')
    @skip_if_linux()
    def test_disk_io_counters(self):
        self.execute(psutil.disk_io_counters)

    # --- proc

    @skip_if_linux()
    def test_pids(self):
        self.execute(psutil.pids)

    # --- net

    @skip_if_linux()
    def test_net_io_counters(self):
        self.execute(psutil.net_io_counters)

    @unittest.skipIf(LINUX,
                     "worthless on Linux (pure python)")
    @unittest.skipIf(OSX and os.getuid() != 0, "need root access")
    def test_net_connections(self):
        self.execute(psutil.net_connections)

    def test_net_if_addrs(self):
        # Note: verified that on Windows this was a false positive.
        self.execute(psutil.net_if_addrs,
                     tolerance_=80 * 1024 if WINDOWS else None)

    @unittest.skipIf(TRAVIS, "EPERM on travis")
    def test_net_if_stats(self):
        self.execute(psutil.net_if_stats)

    # --- sensors

    @unittest.skipUnless(hasattr(psutil, "sensors_battery"),
                         "platform not supported")
    @skip_if_linux()
    def test_sensors_battery(self):
        self.execute(psutil.sensors_battery)

    @skip_if_linux()
    @unittest.skipUnless(hasattr(psutil, "sensors_temperatures"),
                         "platform not supported")
    def test_sensors_temperatures(self):
        self.execute(psutil.sensors_temperatures)

    @unittest.skipUnless(hasattr(psutil, "sensors_fans"),
                         "platform not supported")
    @skip_if_linux()
    def test_sensors_fans(self):
        self.execute(psutil.sensors_fans)

    # --- others

    @skip_if_linux()
    def test_boot_time(self):
        self.execute(psutil.boot_time)

    # XXX - on Windows this produces a false positive
    @unittest.skipIf(WINDOWS, "XXX produces a false positive on Windows")
    def test_users(self):
        self.execute(psutil.users)

    if WINDOWS:

        # --- win services

        def test_win_service_iter(self):
            self.execute(cext.winservice_enumerate)

        def test_win_service_get_config(self):
            name = next(psutil.win_service_iter()).name()
            self.execute(cext.winservice_query_config, name)

        def test_win_service_get_status(self):
            name = next(psutil.win_service_iter()).name()
            self.execute(cext.winservice_query_status, name)

        def test_win_service_get_description(self):
            name = next(psutil.win_service_iter()).name()
            self.execute(cext.winservice_query_descr, name)


if __name__ == '__main__':
    run_test_module_by_name(__file__)
