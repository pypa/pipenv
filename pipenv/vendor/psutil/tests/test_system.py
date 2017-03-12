#!/usr/bin/env python

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for system APIS."""

import contextlib
import datetime
import errno
import os
import pprint
import shutil
import signal
import socket
import sys
import tempfile
import time

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
from psutil._compat import long
from psutil._compat import unicode
from psutil.tests import AF_INET6
from psutil.tests import APPVEYOR
from psutil.tests import check_net_address
from psutil.tests import DEVNULL
from psutil.tests import enum
from psutil.tests import get_test_subprocess
from psutil.tests import mock
from psutil.tests import reap_children
from psutil.tests import retry_before_failing
from psutil.tests import run_test_module_by_name
from psutil.tests import safe_rmpath
from psutil.tests import skip_on_access_denied
from psutil.tests import TESTFN
from psutil.tests import TESTFN_UNICODE
from psutil.tests import TRAVIS
from psutil.tests import unittest


# ===================================================================
# --- System-related API tests
# ===================================================================


class TestSystemAPIs(unittest.TestCase):
    """Tests for system-related APIs."""

    def setUp(self):
        safe_rmpath(TESTFN)

    def tearDown(self):
        reap_children()

    def test_process_iter(self):
        self.assertIn(os.getpid(), [x.pid for x in psutil.process_iter()])
        sproc = get_test_subprocess()
        self.assertIn(sproc.pid, [x.pid for x in psutil.process_iter()])
        p = psutil.Process(sproc.pid)
        p.kill()
        p.wait()
        self.assertNotIn(sproc.pid, [x.pid for x in psutil.process_iter()])

        with mock.patch('psutil.Process',
                        side_effect=psutil.NoSuchProcess(os.getpid())):
            self.assertEqual(list(psutil.process_iter()), [])
        with mock.patch('psutil.Process',
                        side_effect=psutil.AccessDenied(os.getpid())):
            with self.assertRaises(psutil.AccessDenied):
                list(psutil.process_iter())

    def test_wait_procs(self):
        def callback(p):
            pids.append(p.pid)

        pids = []
        sproc1 = get_test_subprocess()
        sproc2 = get_test_subprocess()
        sproc3 = get_test_subprocess()
        procs = [psutil.Process(x.pid) for x in (sproc1, sproc2, sproc3)]
        self.assertRaises(ValueError, psutil.wait_procs, procs, timeout=-1)
        self.assertRaises(TypeError, psutil.wait_procs, procs, callback=1)
        t = time.time()
        gone, alive = psutil.wait_procs(procs, timeout=0.01, callback=callback)

        self.assertLess(time.time() - t, 0.5)
        self.assertEqual(gone, [])
        self.assertEqual(len(alive), 3)
        self.assertEqual(pids, [])
        for p in alive:
            self.assertFalse(hasattr(p, 'returncode'))

        @retry_before_failing(30)
        def test(procs, callback):
            gone, alive = psutil.wait_procs(procs, timeout=0.03,
                                            callback=callback)
            self.assertEqual(len(gone), 1)
            self.assertEqual(len(alive), 2)
            return gone, alive

        sproc3.terminate()
        gone, alive = test(procs, callback)
        self.assertIn(sproc3.pid, [x.pid for x in gone])
        if POSIX:
            self.assertEqual(gone.pop().returncode, -signal.SIGTERM)
        else:
            self.assertEqual(gone.pop().returncode, 1)
        self.assertEqual(pids, [sproc3.pid])
        for p in alive:
            self.assertFalse(hasattr(p, 'returncode'))

        @retry_before_failing(30)
        def test(procs, callback):
            gone, alive = psutil.wait_procs(procs, timeout=0.03,
                                            callback=callback)
            self.assertEqual(len(gone), 3)
            self.assertEqual(len(alive), 0)
            return gone, alive

        sproc1.terminate()
        sproc2.terminate()
        gone, alive = test(procs, callback)
        self.assertEqual(set(pids), set([sproc1.pid, sproc2.pid, sproc3.pid]))
        for p in gone:
            self.assertTrue(hasattr(p, 'returncode'))

    def test_wait_procs_no_timeout(self):
        sproc1 = get_test_subprocess()
        sproc2 = get_test_subprocess()
        sproc3 = get_test_subprocess()
        procs = [psutil.Process(x.pid) for x in (sproc1, sproc2, sproc3)]
        for p in procs:
            p.terminate()
        gone, alive = psutil.wait_procs(procs)

    def test_boot_time(self):
        bt = psutil.boot_time()
        self.assertIsInstance(bt, float)
        self.assertGreater(bt, 0)
        self.assertLess(bt, time.time())

    @unittest.skipUnless(POSIX, 'POSIX only')
    def test_PAGESIZE(self):
        # pagesize is used internally to perform different calculations
        # and it's determined by using SC_PAGE_SIZE; make sure
        # getpagesize() returns the same value.
        import resource
        self.assertEqual(os.sysconf("SC_PAGE_SIZE"), resource.getpagesize())

    def test_virtual_memory(self):
        mem = psutil.virtual_memory()
        assert mem.total > 0, mem
        assert mem.available > 0, mem
        assert 0 <= mem.percent <= 100, mem
        assert mem.used > 0, mem
        assert mem.free >= 0, mem
        for name in mem._fields:
            value = getattr(mem, name)
            if name != 'percent':
                self.assertIsInstance(value, (int, long))
            if name != 'total':
                if not value >= 0:
                    self.fail("%r < 0 (%s)" % (name, value))
                if value > mem.total:
                    self.fail("%r > total (total=%s, %s=%s)"
                              % (name, mem.total, name, value))

    def test_swap_memory(self):
        mem = psutil.swap_memory()
        assert mem.total >= 0, mem
        assert mem.used >= 0, mem
        if mem.total > 0:
            # likely a system with no swap partition
            assert mem.free > 0, mem
        else:
            assert mem.free == 0, mem
        assert 0 <= mem.percent <= 100, mem
        assert mem.sin >= 0, mem
        assert mem.sout >= 0, mem

    def test_pid_exists(self):
        sproc = get_test_subprocess()
        self.assertTrue(psutil.pid_exists(sproc.pid))
        p = psutil.Process(sproc.pid)
        p.kill()
        p.wait()
        self.assertFalse(psutil.pid_exists(sproc.pid))
        self.assertFalse(psutil.pid_exists(-1))
        self.assertEqual(psutil.pid_exists(0), 0 in psutil.pids())
        # pid 0
        psutil.pid_exists(0) == 0 in psutil.pids()

    def test_pid_exists_2(self):
        reap_children()
        pids = psutil.pids()
        for pid in pids:
            try:
                assert psutil.pid_exists(pid)
            except AssertionError:
                # in case the process disappeared in meantime fail only
                # if it is no longer in psutil.pids()
                time.sleep(.1)
                if pid in psutil.pids():
                    self.fail(pid)
        pids = range(max(pids) + 5000, max(pids) + 6000)
        for pid in pids:
            self.assertFalse(psutil.pid_exists(pid), msg=pid)

    def test_pids(self):
        plist = [x.pid for x in psutil.process_iter()]
        pidlist = psutil.pids()
        self.assertEqual(plist.sort(), pidlist.sort())
        # make sure every pid is unique
        self.assertEqual(len(pidlist), len(set(pidlist)))

    def test_test(self):
        # test for psutil.test() function
        stdout = sys.stdout
        sys.stdout = DEVNULL
        try:
            psutil.test()
        finally:
            sys.stdout = stdout

    def test_cpu_count(self):
        logical = psutil.cpu_count()
        self.assertEqual(logical, len(psutil.cpu_times(percpu=True)))
        self.assertGreaterEqual(logical, 1)
        #
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo") as fd:
                cpuinfo_data = fd.read()
            if "physical id" not in cpuinfo_data:
                raise unittest.SkipTest("cpuinfo doesn't include physical id")
        physical = psutil.cpu_count(logical=False)
        self.assertGreaterEqual(physical, 1)
        self.assertGreaterEqual(logical, physical)

    def test_cpu_times(self):
        # Check type, value >= 0, str().
        total = 0
        times = psutil.cpu_times()
        sum(times)
        for cp_time in times:
            self.assertIsInstance(cp_time, float)
            self.assertGreaterEqual(cp_time, 0.0)
            total += cp_time
        self.assertEqual(total, sum(times))
        str(times)
        # CPU times are always supposed to increase over time
        # or at least remain the same and that's because time
        # cannot go backwards.
        # Surprisingly sometimes this might not be the case (at
        # least on Windows and Linux), see:
        # https://github.com/giampaolo/psutil/issues/392
        # https://github.com/giampaolo/psutil/issues/645
        # if not WINDOWS:
        #     last = psutil.cpu_times()
        #     for x in range(100):
        #         new = psutil.cpu_times()
        #         for field in new._fields:
        #             new_t = getattr(new, field)
        #             last_t = getattr(last, field)
        #             self.assertGreaterEqual(new_t, last_t,
        #                                     msg="%s %s" % (new_t, last_t))
        #         last = new

    def test_cpu_times_time_increases(self):
        # Make sure time increases between calls.
        t1 = sum(psutil.cpu_times())
        time.sleep(0.1)
        t2 = sum(psutil.cpu_times())
        difference = t2 - t1
        if not difference >= 0.05:
            self.fail("difference %s" % difference)

    def test_per_cpu_times(self):
        # Check type, value >= 0, str().
        for times in psutil.cpu_times(percpu=True):
            total = 0
            sum(times)
            for cp_time in times:
                self.assertIsInstance(cp_time, float)
                self.assertGreaterEqual(cp_time, 0.0)
                total += cp_time
            self.assertEqual(total, sum(times))
            str(times)
        self.assertEqual(len(psutil.cpu_times(percpu=True)[0]),
                         len(psutil.cpu_times(percpu=False)))

        # Note: in theory CPU times are always supposed to increase over
        # time or remain the same but never go backwards. In practice
        # sometimes this is not the case.
        # This issue seemd to be afflict Windows:
        # https://github.com/giampaolo/psutil/issues/392
        # ...but it turns out also Linux (rarely) behaves the same.
        # last = psutil.cpu_times(percpu=True)
        # for x in range(100):
        #     new = psutil.cpu_times(percpu=True)
        #     for index in range(len(new)):
        #         newcpu = new[index]
        #         lastcpu = last[index]
        #         for field in newcpu._fields:
        #             new_t = getattr(newcpu, field)
        #             last_t = getattr(lastcpu, field)
        #             self.assertGreaterEqual(
        #                 new_t, last_t, msg="%s %s" % (lastcpu, newcpu))
        #     last = new

    def test_per_cpu_times_2(self):
        # Simulate some work load then make sure time have increased
        # between calls.
        tot1 = psutil.cpu_times(percpu=True)
        stop_at = time.time() + 0.1
        while True:
            if time.time() >= stop_at:
                break
        tot2 = psutil.cpu_times(percpu=True)
        for t1, t2 in zip(tot1, tot2):
            t1, t2 = sum(t1), sum(t2)
            difference = t2 - t1
            if difference >= 0.05:
                return
        self.fail()

    def test_cpu_times_comparison(self):
        # Make sure the sum of all per cpu times is almost equal to
        # base "one cpu" times.
        base = psutil.cpu_times()
        per_cpu = psutil.cpu_times(percpu=True)
        summed_values = base._make([sum(num) for num in zip(*per_cpu)])
        for field in base._fields:
            self.assertAlmostEqual(
                getattr(base, field), getattr(summed_values, field), delta=1)

    def _test_cpu_percent(self, percent, last_ret, new_ret):
        try:
            self.assertIsInstance(percent, float)
            self.assertGreaterEqual(percent, 0.0)
            self.assertIsNot(percent, -0.0)
            self.assertLessEqual(percent, 100.0 * psutil.cpu_count())
        except AssertionError as err:
            raise AssertionError("\n%s\nlast=%s\nnew=%s" % (
                err, pprint.pformat(last_ret), pprint.pformat(new_ret)))

    def test_cpu_percent(self):
        last = psutil.cpu_percent(interval=0.001)
        for x in range(100):
            new = psutil.cpu_percent(interval=None)
            self._test_cpu_percent(new, last, new)
            last = new
        with self.assertRaises(ValueError):
            psutil.cpu_percent(interval=-1)

    def test_per_cpu_percent(self):
        last = psutil.cpu_percent(interval=0.001, percpu=True)
        self.assertEqual(len(last), psutil.cpu_count())
        for x in range(100):
            new = psutil.cpu_percent(interval=None, percpu=True)
            for percent in new:
                self._test_cpu_percent(percent, last, new)
            last = new
        with self.assertRaises(ValueError):
            psutil.cpu_percent(interval=-1, percpu=True)

    def test_cpu_times_percent(self):
        last = psutil.cpu_times_percent(interval=0.001)
        for x in range(100):
            new = psutil.cpu_times_percent(interval=None)
            for percent in new:
                self._test_cpu_percent(percent, last, new)
            self._test_cpu_percent(sum(new), last, new)
            last = new

    def test_per_cpu_times_percent(self):
        last = psutil.cpu_times_percent(interval=0.001, percpu=True)
        self.assertEqual(len(last), psutil.cpu_count())
        for x in range(100):
            new = psutil.cpu_times_percent(interval=None, percpu=True)
            for cpu in new:
                for percent in cpu:
                    self._test_cpu_percent(percent, last, new)
                self._test_cpu_percent(sum(cpu), last, new)
            last = new

    def test_per_cpu_times_percent_negative(self):
        # see: https://github.com/giampaolo/psutil/issues/645
        psutil.cpu_times_percent(percpu=True)
        zero_times = [x._make([0 for x in range(len(x._fields))])
                      for x in psutil.cpu_times(percpu=True)]
        with mock.patch('psutil.cpu_times', return_value=zero_times):
            for cpu in psutil.cpu_times_percent(percpu=True):
                for percent in cpu:
                    self._test_cpu_percent(percent, None, None)

    @unittest.skipIf(POSIX and not hasattr(os, 'statvfs'),
                     "os.statvfs() not available")
    def test_disk_usage(self):
        usage = psutil.disk_usage(os.getcwd())
        assert usage.total > 0, usage
        assert usage.used > 0, usage
        assert usage.free > 0, usage
        assert usage.total > usage.used, usage
        assert usage.total > usage.free, usage
        assert 0 <= usage.percent <= 100, usage.percent
        if hasattr(shutil, 'disk_usage'):
            # py >= 3.3, see: http://bugs.python.org/issue12442
            shutil_usage = shutil.disk_usage(os.getcwd())
            tolerance = 5 * 1024 * 1024  # 5MB
            self.assertEqual(usage.total, shutil_usage.total)
            self.assertAlmostEqual(usage.free, shutil_usage.free,
                                   delta=tolerance)
            self.assertAlmostEqual(usage.used, shutil_usage.used,
                                   delta=tolerance)

        # if path does not exist OSError ENOENT is expected across
        # all platforms
        fname = tempfile.mktemp()
        try:
            psutil.disk_usage(fname)
        except OSError as err:
            if err.args[0] != errno.ENOENT:
                raise
        else:
            self.fail("OSError not raised")

    @unittest.skipIf(POSIX and not hasattr(os, 'statvfs'),
                     "os.statvfs() not available")
    def test_disk_usage_unicode(self):
        # see: https://github.com/giampaolo/psutil/issues/416
        safe_rmpath(TESTFN_UNICODE)
        self.addCleanup(safe_rmpath, TESTFN_UNICODE)
        os.mkdir(TESTFN_UNICODE)
        psutil.disk_usage(TESTFN_UNICODE)

    @unittest.skipIf(POSIX and not hasattr(os, 'statvfs'),
                     "os.statvfs() not available")
    @unittest.skipIf(LINUX and TRAVIS, "unknown failure on travis")
    def test_disk_partitions(self):
        # all = False
        ls = psutil.disk_partitions(all=False)
        # on travis we get:
        #     self.assertEqual(p.cpu_affinity(), [n])
        # AssertionError: Lists differ: [0, 1, 2, 3, 4, 5, 6, 7,... != [0]
        self.assertTrue(ls, msg=ls)
        for disk in ls:
            self.assertIsInstance(disk.device, (str, unicode))
            self.assertIsInstance(disk.mountpoint, (str, unicode))
            self.assertIsInstance(disk.fstype, (str, unicode))
            self.assertIsInstance(disk.opts, (str, unicode))
            if WINDOWS and 'cdrom' in disk.opts:
                continue
            if not POSIX:
                assert os.path.exists(disk.device), disk
            else:
                # we cannot make any assumption about this, see:
                # http://goo.gl/p9c43
                disk.device
            if SUNOS:
                # on solaris apparently mount points can also be files
                assert os.path.exists(disk.mountpoint), disk
            else:
                assert os.path.isdir(disk.mountpoint), disk
            assert disk.fstype, disk

        # all = True
        ls = psutil.disk_partitions(all=True)
        self.assertTrue(ls, msg=ls)
        for disk in psutil.disk_partitions(all=True):
            if not WINDOWS:
                try:
                    os.stat(disk.mountpoint)
                except OSError as err:
                    if TRAVIS and OSX and err.errno == errno.EIO:
                        continue
                    # http://mail.python.org/pipermail/python-dev/
                    #     2012-June/120787.html
                    if err.errno not in (errno.EPERM, errno.EACCES):
                        raise
                else:
                    if SUNOS:
                        # on solaris apparently mount points can also be files
                        assert os.path.exists(disk.mountpoint), disk
                    else:
                        assert os.path.isdir(disk.mountpoint), disk
            self.assertIsInstance(disk.fstype, str)
            self.assertIsInstance(disk.opts, str)

        def find_mount_point(path):
            path = os.path.abspath(path)
            while not os.path.ismount(path):
                path = os.path.dirname(path)
            return path.lower()

        mount = find_mount_point(__file__)
        mounts = [x.mountpoint.lower() for x in
                  psutil.disk_partitions(all=True)]
        self.assertIn(mount, mounts)
        psutil.disk_usage(mount)

    @skip_on_access_denied()
    def test_net_connections(self):
        def check(cons, families, types_):
            for conn in cons:
                self.assertIn(conn.family, families, msg=conn)
                if conn.family != getattr(socket, 'AF_UNIX', object()):
                    self.assertIn(conn.type, types_, msg=conn)
                self.assertIsInstance(conn.status, (str, unicode))

        from psutil._common import conn_tmap
        for kind, groups in conn_tmap.items():
            if SUNOS and kind == 'unix':
                continue
            families, types_ = groups
            cons = psutil.net_connections(kind)
            self.assertEqual(len(cons), len(set(cons)))
            check(cons, families, types_)

    def test_net_io_counters(self):
        def check_ntuple(nt):
            self.assertEqual(nt[0], nt.bytes_sent)
            self.assertEqual(nt[1], nt.bytes_recv)
            self.assertEqual(nt[2], nt.packets_sent)
            self.assertEqual(nt[3], nt.packets_recv)
            self.assertEqual(nt[4], nt.errin)
            self.assertEqual(nt[5], nt.errout)
            self.assertEqual(nt[6], nt.dropin)
            self.assertEqual(nt[7], nt.dropout)
            assert nt.bytes_sent >= 0, nt
            assert nt.bytes_recv >= 0, nt
            assert nt.packets_sent >= 0, nt
            assert nt.packets_recv >= 0, nt
            assert nt.errin >= 0, nt
            assert nt.errout >= 0, nt
            assert nt.dropin >= 0, nt
            assert nt.dropout >= 0, nt

        ret = psutil.net_io_counters(pernic=False)
        check_ntuple(ret)
        ret = psutil.net_io_counters(pernic=True)
        self.assertNotEqual(ret, [])
        for key in ret:
            self.assertTrue(key)
            self.assertIsInstance(key, (str, unicode))
            check_ntuple(ret[key])

    def test_net_if_addrs(self):
        nics = psutil.net_if_addrs()
        assert nics, nics

        nic_stats = psutil.net_if_stats()

        # Not reliable on all platforms (net_if_addrs() reports more
        # interfaces).
        # self.assertEqual(sorted(nics.keys()),
        #                  sorted(psutil.net_io_counters(pernic=True).keys()))

        families = set([socket.AF_INET, AF_INET6, psutil.AF_LINK])
        for nic, addrs in nics.items():
            self.assertIsInstance(nic, (str, unicode))
            self.assertEqual(len(set(addrs)), len(addrs))
            for addr in addrs:
                self.assertIsInstance(addr.family, int)
                self.assertIsInstance(addr.address, str)
                self.assertIsInstance(addr.netmask, (str, type(None)))
                self.assertIsInstance(addr.broadcast, (str, type(None)))
                self.assertIn(addr.family, families)
                if sys.version_info >= (3, 4):
                    self.assertIsInstance(addr.family, enum.IntEnum)
                if nic_stats[nic].isup:
                    # Do not test binding to addresses of interfaces
                    # that are down
                    if addr.family == socket.AF_INET:
                        s = socket.socket(addr.family)
                        with contextlib.closing(s):
                            s.bind((addr.address, 0))
                    elif addr.family == socket.AF_INET6:
                        info = socket.getaddrinfo(
                            addr.address, 0, socket.AF_INET6,
                            socket.SOCK_STREAM, 0, socket.AI_PASSIVE)[0]
                        af, socktype, proto, canonname, sa = info
                        s = socket.socket(af, socktype, proto)
                        with contextlib.closing(s):
                            s.bind(sa)
                for ip in (addr.address, addr.netmask, addr.broadcast,
                           addr.ptp):
                    if ip is not None:
                        # TODO: skip AF_INET6 for now because I get:
                        # AddressValueError: Only hex digits permitted in
                        # u'c6f3%lxcbr0' in u'fe80::c8e0:fff:fe54:c6f3%lxcbr0'
                        if addr.family != AF_INET6:
                            check_net_address(ip, addr.family)
                # broadcast and ptp addresses are mutually exclusive
                if addr.broadcast:
                    self.assertIsNone(addr.ptp)
                elif addr.ptp:
                    self.assertIsNone(addr.broadcast)

        if BSD or OSX or SUNOS:
            if hasattr(socket, "AF_LINK"):
                self.assertEqual(psutil.AF_LINK, socket.AF_LINK)
        elif LINUX:
            self.assertEqual(psutil.AF_LINK, socket.AF_PACKET)
        elif WINDOWS:
            self.assertEqual(psutil.AF_LINK, -1)

    def test_net_if_addrs_mac_null_bytes(self):
        # Simulate that the underlying C function returns an incomplete
        # MAC address. psutil is supposed to fill it with null bytes.
        # https://github.com/giampaolo/psutil/issues/786
        if POSIX:
            ret = [('em1', psutil.AF_LINK, '06:3d:29', None, None, None)]
        else:
            ret = [('em1', -1, '06-3d-29', None, None, None)]
        with mock.patch('psutil._psplatform.net_if_addrs',
                        return_value=ret) as m:
            addr = psutil.net_if_addrs()['em1'][0]
            assert m.called
            if POSIX:
                self.assertEqual(addr.address, '06:3d:29:00:00:00')
            else:
                self.assertEqual(addr.address, '06-3d-29-00-00-00')

    @unittest.skipIf(TRAVIS, "unreliable on TRAVIS")  # raises EPERM
    def test_net_if_stats(self):
        nics = psutil.net_if_stats()
        assert nics, nics
        all_duplexes = (psutil.NIC_DUPLEX_FULL,
                        psutil.NIC_DUPLEX_HALF,
                        psutil.NIC_DUPLEX_UNKNOWN)
        for nic, stats in nics.items():
            isup, duplex, speed, mtu = stats
            self.assertIsInstance(isup, bool)
            self.assertIn(duplex, all_duplexes)
            self.assertIn(duplex, all_duplexes)
            self.assertGreaterEqual(speed, 0)
            self.assertGreaterEqual(mtu, 0)

    @unittest.skipIf(LINUX and not os.path.exists('/proc/diskstats'),
                     '/proc/diskstats not available on this linux version')
    @unittest.skipIf(APPVEYOR, "unreliable on APPVEYOR")  # no visible disks
    def test_disk_io_counters(self):
        def check_ntuple(nt):
            self.assertEqual(nt[0], nt.read_count)
            self.assertEqual(nt[1], nt.write_count)
            self.assertEqual(nt[2], nt.read_bytes)
            self.assertEqual(nt[3], nt.write_bytes)
            if not (OPENBSD or NETBSD):
                self.assertEqual(nt[4], nt.read_time)
                self.assertEqual(nt[5], nt.write_time)
                if LINUX:
                    self.assertEqual(nt[6], nt.read_merged_count)
                    self.assertEqual(nt[7], nt.write_merged_count)
                    self.assertEqual(nt[8], nt.busy_time)
                elif FREEBSD:
                    self.assertEqual(nt[6], nt.busy_time)
            for name in nt._fields:
                assert getattr(nt, name) >= 0, nt

        ret = psutil.disk_io_counters(perdisk=False)
        check_ntuple(ret)
        ret = psutil.disk_io_counters(perdisk=True)
        # make sure there are no duplicates
        self.assertEqual(len(ret), len(set(ret)))
        for key in ret:
            assert key, key
            check_ntuple(ret[key])
            if LINUX and key[-1].isdigit():
                # if 'sda1' is listed 'sda' shouldn't, see:
                # https://github.com/giampaolo/psutil/issues/338
                while key[-1].isdigit():
                    key = key[:-1]
                self.assertNotIn(key, ret.keys())

    # can't find users on APPVEYOR or TRAVIS
    @unittest.skipIf(APPVEYOR or TRAVIS and not psutil.users(),
                     "unreliable on APPVEYOR or TRAVIS")
    def test_users(self):
        users = psutil.users()
        self.assertNotEqual(users, [])
        for user in users:
            assert user.name, user
            self.assertIsInstance(user.name, (str, unicode))
            self.assertIsInstance(user.terminal, (str, unicode, None))
            if user.host is not None:
                self.assertIsInstance(user.host, (str, unicode, None))
            user.terminal
            user.host
            assert user.started > 0.0, user
            datetime.datetime.fromtimestamp(user.started)

    def test_cpu_stats(self):
        # Tested more extensively in per-platform test modules.
        infos = psutil.cpu_stats()
        for name in infos._fields:
            value = getattr(infos, name)
            self.assertGreaterEqual(value, 0)
            if name in ('ctx_switches', 'interrupts'):
                self.assertGreater(value, 0)

    @unittest.skipUnless(hasattr(psutil, "cpu_freq"),
                         "platform not suported")
    def test_cpu_freq(self):
        def check_ls(ls):
            for nt in ls:
                self.assertLessEqual(nt.current, nt.max)
                for name in nt._fields:
                    value = getattr(nt, name)
                    self.assertIsInstance(value, (int, long, float))
                    self.assertGreaterEqual(value, 0)

        ls = psutil.cpu_freq(percpu=True)
        if TRAVIS and not ls:
            return

        assert ls, ls
        check_ls([psutil.cpu_freq(percpu=False)])

        if LINUX:
            self.assertEqual(len(ls), psutil.cpu_count())

    def test_os_constants(self):
        names = ["POSIX", "WINDOWS", "LINUX", "OSX", "FREEBSD", "OPENBSD",
                 "NETBSD", "BSD", "SUNOS"]
        for name in names:
            self.assertIsInstance(getattr(psutil, name), bool, msg=name)

        if os.name == 'posix':
            assert psutil.POSIX
            assert not psutil.WINDOWS
            names.remove("POSIX")
            if "linux" in sys.platform.lower():
                assert psutil.LINUX
                names.remove("LINUX")
            elif "bsd" in sys.platform.lower():
                assert psutil.BSD
                self.assertEqual([psutil.FREEBSD, psutil.OPENBSD,
                                  psutil.NETBSD].count(True), 1)
                names.remove("BSD")
                names.remove("FREEBSD")
                names.remove("OPENBSD")
                names.remove("NETBSD")
            elif "sunos" in sys.platform.lower() or \
                    "solaris" in sys.platform.lower():
                assert psutil.SUNOS
                names.remove("SUNOS")
            elif "darwin" in sys.platform.lower():
                assert psutil.OSX
                names.remove("OSX")
        else:
            assert psutil.WINDOWS
            assert not psutil.POSIX
            names.remove("WINDOWS")

        # assert all other constants are set to False
        for name in names:
            self.assertIs(getattr(psutil, name), False, msg=name)

    @unittest.skipUnless(hasattr(psutil, "sensors_temperatures"),
                         "platform not supported")
    def test_sensors_temperatures(self):
        temps = psutil.sensors_temperatures()
        for name, entries in temps.items():
            self.assertIsInstance(name, (str, unicode))
            for entry in entries:
                self.assertIsInstance(entry.label, (str, unicode))
                if entry.current is not None:
                    self.assertGreaterEqual(entry.current, 0)
                if entry.high is not None:
                    self.assertGreaterEqual(entry.high, 0)
                if entry.critical is not None:
                    self.assertGreaterEqual(entry.critical, 0)

    @unittest.skipUnless(hasattr(psutil, "sensors_battery"),
                         "platform not supported")
    def test_sensors_battery(self):
        ret = psutil.sensors_battery()
        if ret is None:
            return  # no battery
        self.assertGreaterEqual(ret.percent, 0)
        self.assertLessEqual(ret.percent, 100)
        if ret.secsleft not in (psutil.POWER_TIME_UNKNOWN,
                                psutil.POWER_TIME_UNLIMITED):
            self.assertGreaterEqual(ret.secsleft, 0)
        else:
            if ret.secsleft == psutil.POWER_TIME_UNLIMITED:
                self.assertTrue(ret.power_plugged)
        self.assertIsInstance(ret.power_plugged, bool)

    @unittest.skipUnless(hasattr(psutil, "sensors_fans"),
                         "platform not supported")
    def test_sensors_fans(self):
        fans = psutil.sensors_fans()
        for name, entries in fans.items():
            self.assertIsInstance(name, (str, unicode))
            for entry in entries:
                self.assertIsInstance(entry.label, (str, unicode))
                self.assertIsInstance(entry.current, (int, long))
                self.assertGreaterEqual(entry.current, 0)


if __name__ == '__main__':
    run_test_module_by_name(__file__)
