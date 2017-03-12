#!/usr/bin/env python

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO: (FreeBSD) add test for comparing connections with 'sockstat' cmd.


"""Tests specific to all BSD platforms."""


import datetime
import os
import re
import subprocess
import sys
import time

import psutil
from psutil import BSD
from psutil import FREEBSD
from psutil import NETBSD
from psutil import OPENBSD
from psutil._compat import PY3
from psutil.tests import get_test_subprocess
from psutil.tests import MEMORY_TOLERANCE
from psutil.tests import reap_children
from psutil.tests import retry_before_failing
from psutil.tests import run_test_module_by_name
from psutil.tests import sh
from psutil.tests import unittest
from psutil.tests import which


if BSD:
    PAGESIZE = os.sysconf("SC_PAGE_SIZE")
    if os.getuid() == 0:  # muse requires root privileges
        MUSE_AVAILABLE = which('muse')
    else:
        MUSE_AVAILABLE = False
else:
    MUSE_AVAILABLE = False


def sysctl(cmdline):
    """Expects a sysctl command with an argument and parse the result
    returning only the value of interest.
    """
    result = sh("sysctl " + cmdline)
    if FREEBSD:
        result = result[result.find(": ") + 2:]
    elif OPENBSD or NETBSD:
        result = result[result.find("=") + 1:]
    try:
        return int(result)
    except ValueError:
        return result


def muse(field):
    """Thin wrapper around 'muse' cmdline utility."""
    out = sh('muse')
    for line in out.split('\n'):
        if line.startswith(field):
            break
    else:
        raise ValueError("line not found")
    return int(line.split()[1])


# =====================================================================
# --- All BSD*
# =====================================================================


@unittest.skipUnless(BSD, "BSD only")
class BSDSpecificTestCase(unittest.TestCase):
    """Generic tests common to all BSD variants."""

    @classmethod
    def setUpClass(cls):
        cls.pid = get_test_subprocess().pid

    @classmethod
    def tearDownClass(cls):
        reap_children()

    def test_process_create_time(self):
        cmdline = "ps -o lstart -p %s" % self.pid
        p = subprocess.Popen(cmdline, shell=1, stdout=subprocess.PIPE)
        output = p.communicate()[0]
        if PY3:
            output = str(output, sys.stdout.encoding)
        start_ps = output.replace('STARTED', '').strip()
        start_psutil = psutil.Process(self.pid).create_time()
        start_psutil = time.strftime("%a %b %e %H:%M:%S %Y",
                                     time.localtime(start_psutil))
        self.assertEqual(start_ps, start_psutil)

    def test_disks(self):
        # test psutil.disk_usage() and psutil.disk_partitions()
        # against "df -a"
        def df(path):
            out = sh('df -k "%s"' % path).strip()
            lines = out.split('\n')
            lines.pop(0)
            line = lines.pop(0)
            dev, total, used, free = line.split()[:4]
            if dev == 'none':
                dev = ''
            total = int(total) * 1024
            used = int(used) * 1024
            free = int(free) * 1024
            return dev, total, used, free

        for part in psutil.disk_partitions(all=False):
            usage = psutil.disk_usage(part.mountpoint)
            dev, total, used, free = df(part.mountpoint)
            self.assertEqual(part.device, dev)
            self.assertEqual(usage.total, total)
            # 10 MB tollerance
            if abs(usage.free - free) > 10 * 1024 * 1024:
                self.fail("psutil=%s, df=%s" % (usage.free, free))
            if abs(usage.used - used) > 10 * 1024 * 1024:
                self.fail("psutil=%s, df=%s" % (usage.used, used))

    @unittest.skipIf(not which('sysctl'), "sysctl cmd not available")
    def test_cpu_count_logical(self):
        syst = sysctl("hw.ncpu")
        self.assertEqual(psutil.cpu_count(logical=True), syst)

    @unittest.skipIf(not which('sysctl'), "sysctl cmd not available")
    def test_virtual_memory_total(self):
        num = sysctl('hw.physmem')
        self.assertEqual(num, psutil.virtual_memory().total)

    def test_net_if_stats(self):
        for name, stats in psutil.net_if_stats().items():
            try:
                out = sh("ifconfig %s" % name)
            except RuntimeError:
                pass
            else:
                self.assertEqual(stats.isup, 'RUNNING' in out, msg=out)
                self.assertEqual(stats.mtu,
                                 int(re.findall('mtu (\d+)', out)[0]))


# =====================================================================
# --- FreeBSD
# =====================================================================


@unittest.skipUnless(FREEBSD, "FREEBSD only")
class FreeBSDSpecificTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pid = get_test_subprocess().pid

    @classmethod
    def tearDownClass(cls):
        reap_children()

    @retry_before_failing()
    def test_proc_memory_maps(self):
        out = sh('procstat -v %s' % self.pid)
        maps = psutil.Process(self.pid).memory_maps(grouped=False)
        lines = out.split('\n')[1:]
        while lines:
            line = lines.pop()
            fields = line.split()
            _, start, stop, perms, res = fields[:5]
            map = maps.pop()
            self.assertEqual("%s-%s" % (start, stop), map.addr)
            self.assertEqual(int(res), map.rss)
            if not map.path.startswith('['):
                self.assertEqual(fields[10], map.path)

    def test_proc_exe(self):
        out = sh('procstat -b %s' % self.pid)
        self.assertEqual(psutil.Process(self.pid).exe(),
                         out.split('\n')[1].split()[-1])

    def test_proc_cmdline(self):
        out = sh('procstat -c %s' % self.pid)
        self.assertEqual(' '.join(psutil.Process(self.pid).cmdline()),
                         ' '.join(out.split('\n')[1].split()[2:]))

    def test_proc_uids_gids(self):
        out = sh('procstat -s %s' % self.pid)
        euid, ruid, suid, egid, rgid, sgid = out.split('\n')[1].split()[2:8]
        p = psutil.Process(self.pid)
        uids = p.uids()
        gids = p.gids()
        self.assertEqual(uids.real, int(ruid))
        self.assertEqual(uids.effective, int(euid))
        self.assertEqual(uids.saved, int(suid))
        self.assertEqual(gids.real, int(rgid))
        self.assertEqual(gids.effective, int(egid))
        self.assertEqual(gids.saved, int(sgid))

    @retry_before_failing()
    def test_proc_ctx_switches(self):
        tested = []
        out = sh('procstat -r %s' % self.pid)
        p = psutil.Process(self.pid)
        for line in out.split('\n'):
            line = line.lower().strip()
            if ' voluntary context' in line:
                pstat_value = int(line.split()[-1])
                psutil_value = p.num_ctx_switches().voluntary
                self.assertEqual(pstat_value, psutil_value)
                tested.append(None)
            elif ' involuntary context' in line:
                pstat_value = int(line.split()[-1])
                psutil_value = p.num_ctx_switches().involuntary
                self.assertEqual(pstat_value, psutil_value)
                tested.append(None)
        if len(tested) != 2:
            raise RuntimeError("couldn't find lines match in procstat out")

    @retry_before_failing()
    def test_proc_cpu_times(self):
        tested = []
        out = sh('procstat -r %s' % self.pid)
        p = psutil.Process(self.pid)
        for line in out.split('\n'):
            line = line.lower().strip()
            if 'user time' in line:
                pstat_value = float('0.' + line.split()[-1].split('.')[-1])
                psutil_value = p.cpu_times().user
                self.assertEqual(pstat_value, psutil_value)
                tested.append(None)
            elif 'system time' in line:
                pstat_value = float('0.' + line.split()[-1].split('.')[-1])
                psutil_value = p.cpu_times().system
                self.assertEqual(pstat_value, psutil_value)
                tested.append(None)
        if len(tested) != 2:
            raise RuntimeError("couldn't find lines match in procstat out")

    # --- virtual_memory(); tests against sysctl

    @retry_before_failing()
    def test_vmem_active(self):
        syst = sysctl("vm.stats.vm.v_active_count") * PAGESIZE
        self.assertAlmostEqual(psutil.virtual_memory().active, syst,
                               delta=MEMORY_TOLERANCE)

    @retry_before_failing()
    def test_vmem_inactive(self):
        syst = sysctl("vm.stats.vm.v_inactive_count") * PAGESIZE
        self.assertAlmostEqual(psutil.virtual_memory().inactive, syst,
                               delta=MEMORY_TOLERANCE)

    @retry_before_failing()
    def test_vmem_wired(self):
        syst = sysctl("vm.stats.vm.v_wire_count") * PAGESIZE
        self.assertAlmostEqual(psutil.virtual_memory().wired, syst,
                               delta=MEMORY_TOLERANCE)

    @retry_before_failing()
    def test_vmem_cached(self):
        syst = sysctl("vm.stats.vm.v_cache_count") * PAGESIZE
        self.assertAlmostEqual(psutil.virtual_memory().cached, syst,
                               delta=MEMORY_TOLERANCE)

    @retry_before_failing()
    def test_vmem_free(self):
        syst = sysctl("vm.stats.vm.v_free_count") * PAGESIZE
        self.assertAlmostEqual(psutil.virtual_memory().free, syst,
                               delta=MEMORY_TOLERANCE)

    @retry_before_failing()
    def test_vmem_buffers(self):
        syst = sysctl("vfs.bufspace")
        self.assertAlmostEqual(psutil.virtual_memory().buffers, syst,
                               delta=MEMORY_TOLERANCE)

    # --- virtual_memory(); tests against muse

    @unittest.skipUnless(MUSE_AVAILABLE, "muse not installed")
    def test_muse_vmem_total(self):
        num = muse('Total')
        self.assertEqual(psutil.virtual_memory().total, num)

    @unittest.skipUnless(MUSE_AVAILABLE, "muse not installed")
    @retry_before_failing()
    def test_muse_vmem_active(self):
        num = muse('Active')
        self.assertAlmostEqual(psutil.virtual_memory().active, num,
                               delta=MEMORY_TOLERANCE)

    @unittest.skipUnless(MUSE_AVAILABLE, "muse not installed")
    @retry_before_failing()
    def test_muse_vmem_inactive(self):
        num = muse('Inactive')
        self.assertAlmostEqual(psutil.virtual_memory().inactive, num,
                               delta=MEMORY_TOLERANCE)

    @unittest.skipUnless(MUSE_AVAILABLE, "muse not installed")
    @retry_before_failing()
    def test_muse_vmem_wired(self):
        num = muse('Wired')
        self.assertAlmostEqual(psutil.virtual_memory().wired, num,
                               delta=MEMORY_TOLERANCE)

    @unittest.skipUnless(MUSE_AVAILABLE, "muse not installed")
    @retry_before_failing()
    def test_muse_vmem_cached(self):
        num = muse('Cache')
        self.assertAlmostEqual(psutil.virtual_memory().cached, num,
                               delta=MEMORY_TOLERANCE)

    @unittest.skipUnless(MUSE_AVAILABLE, "muse not installed")
    @retry_before_failing()
    def test_muse_vmem_free(self):
        num = muse('Free')
        self.assertAlmostEqual(psutil.virtual_memory().free, num,
                               delta=MEMORY_TOLERANCE)

    @unittest.skipUnless(MUSE_AVAILABLE, "muse not installed")
    @retry_before_failing()
    def test_muse_vmem_buffers(self):
        num = muse('Buffer')
        self.assertAlmostEqual(psutil.virtual_memory().buffers, num,
                               delta=MEMORY_TOLERANCE)

    def test_cpu_stats_ctx_switches(self):
        self.assertAlmostEqual(psutil.cpu_stats().ctx_switches,
                               sysctl('vm.stats.sys.v_swtch'), delta=1000)

    def test_cpu_stats_interrupts(self):
        self.assertAlmostEqual(psutil.cpu_stats().interrupts,
                               sysctl('vm.stats.sys.v_intr'), delta=1000)

    def test_cpu_stats_soft_interrupts(self):
        self.assertAlmostEqual(psutil.cpu_stats().soft_interrupts,
                               sysctl('vm.stats.sys.v_soft'), delta=1000)

    def test_cpu_stats_syscalls(self):
        self.assertAlmostEqual(psutil.cpu_stats().syscalls,
                               sysctl('vm.stats.sys.v_syscall'), delta=1000)

    # def test_cpu_stats_traps(self):
    #    self.assertAlmostEqual(psutil.cpu_stats().traps,
    #                           sysctl('vm.stats.sys.v_trap'), delta=1000)

    # --- others

    def test_boot_time(self):
        s = sysctl('sysctl kern.boottime')
        s = s[s.find(" sec = ") + 7:]
        s = s[:s.find(',')]
        btime = int(s)
        self.assertEqual(btime, psutil.boot_time())

    # --- sensors_battery

    @unittest.skipUnless(
        hasattr(psutil, "sensors_battery") and psutil.sensors_battery(),
        "no battery")
    def test_sensors_battery(self):
        def secs2hours(secs):
            m, s = divmod(secs, 60)
            h, m = divmod(m, 60)
            return "%d:%02d" % (h, m)

        out = sh("acpiconf -i 0")
        fields = dict([(x.split('\t')[0], x.split('\t')[-1])
                       for x in out.split("\n")])
        metrics = psutil.sensors_battery()
        percent = int(fields['Remaining capacity:'].replace('%', ''))
        remaining_time = fields['Remaining time:']
        self.assertEqual(metrics.percent, percent)
        if remaining_time == 'unknown':
            self.assertEqual(metrics.secsleft, psutil.POWER_TIME_UNLIMITED)
        else:
            self.assertEqual(secs2hours(metrics.secsleft), remaining_time)

    def test_sensors_battery_against_sysctl(self):
        self.assertEqual(psutil.sensors_battery().percent,
                         sysctl("hw.acpi.battery.life"))
        self.assertEqual(psutil.sensors_battery().power_plugged,
                         sysctl("hw.acpi.acline") == 1)
        secsleft = psutil.sensors_battery().secsleft
        if secsleft < 0:
            self.assertEqual(sysctl("hw.acpi.battery.time"), -1)
        else:
            self.assertEqual(secsleft, sysctl("hw.acpi.battery.time") * 60)


# =====================================================================
# --- OpenBSD
# =====================================================================


@unittest.skipUnless(OPENBSD, "OPENBSD only")
class OpenBSDSpecificTestCase(unittest.TestCase):

    def test_boot_time(self):
        s = sysctl('kern.boottime')
        sys_bt = datetime.datetime.strptime(s, "%a %b %d %H:%M:%S %Y")
        psutil_bt = datetime.datetime.fromtimestamp(psutil.boot_time())
        self.assertEqual(sys_bt, psutil_bt)


# =====================================================================
# --- NetBSD
# =====================================================================


@unittest.skipUnless(NETBSD, "NETBSD only")
class NetBSDSpecificTestCase(unittest.TestCase):

    def parse_meminfo(self, look_for):
        with open('/proc/meminfo', 'rb') as f:
            for line in f:
                if line.startswith(look_for):
                    return int(line.split()[1]) * 1024
        raise ValueError("can't find %s" % look_for)

    def test_vmem_total(self):
        self.assertEqual(
            psutil.virtual_memory().total, self.parse_meminfo("MemTotal:"))

    def test_vmem_free(self):
        self.assertAlmostEqual(
            psutil.virtual_memory().free, self.parse_meminfo("MemFree:"),
            delta=MEMORY_TOLERANCE)

    def test_vmem_buffers(self):
        self.assertAlmostEqual(
            psutil.virtual_memory().buffers, self.parse_meminfo("Buffers:"),
            delta=MEMORY_TOLERANCE)

    def test_vmem_shared(self):
        self.assertAlmostEqual(
            psutil.virtual_memory().shared, self.parse_meminfo("MemShared:"),
            delta=MEMORY_TOLERANCE)

    def test_swapmem_total(self):
        self.assertAlmostEqual(
            psutil.swap_memory().total, self.parse_meminfo("SwapTotal:"),
            delta=MEMORY_TOLERANCE)

    def test_swapmem_free(self):
        self.assertAlmostEqual(
            psutil.swap_memory().free, self.parse_meminfo("SwapFree:"),
            delta=MEMORY_TOLERANCE)

    def test_swapmem_used(self):
        smem = psutil.swap_memory()
        self.assertEqual(smem.used, smem.total - smem.free)

    def test_cpu_stats_interrupts(self):
        with open('/proc/stat', 'rb') as f:
            for line in f:
                if line.startswith(b'intr'):
                    interrupts = int(line.split()[1])
                    break
            else:
                raise ValueError("couldn't find line")
        self.assertAlmostEqual(
            psutil.cpu_stats().interrupts, interrupts, delta=1000)

    def test_cpu_stats_ctx_switches(self):
        with open('/proc/stat', 'rb') as f:
            for line in f:
                if line.startswith(b'ctxt'):
                    ctx_switches = int(line.split()[1])
                    break
            else:
                raise ValueError("couldn't find line")
        self.assertAlmostEqual(
            psutil.cpu_stats().ctx_switches, ctx_switches, delta=1000)


if __name__ == '__main__':
    run_test_module_by_name(__file__)
