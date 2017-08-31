# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Linux platform implementation."""

from __future__ import division

import base64
import collections
import errno
import functools
import glob
import os
import re
import socket
import struct
import sys
import traceback
import warnings
from collections import defaultdict
from collections import namedtuple

from . import _common
from . import _psposix
from . import _psutil_linux as cext
from . import _psutil_posix as cext_posix
from ._common import isfile_strict
from ._common import memoize
from ._common import memoize_when_activated
from ._common import parse_environ_block
from ._common import NIC_DUPLEX_FULL
from ._common import NIC_DUPLEX_HALF
from ._common import NIC_DUPLEX_UNKNOWN
from ._common import path_exists_strict
from ._common import supports_ipv6
from ._common import usage_percent
from ._compat import b
from ._compat import basestring
from ._compat import long
from ._compat import PY3

if sys.version_info >= (3, 4):
    import enum
else:
    enum = None


__extra__all__ = [
    #
    'PROCFS_PATH',
    # io prio constants
    "IOPRIO_CLASS_NONE", "IOPRIO_CLASS_RT", "IOPRIO_CLASS_BE",
    "IOPRIO_CLASS_IDLE",
    # connection status constants
    "CONN_ESTABLISHED", "CONN_SYN_SENT", "CONN_SYN_RECV", "CONN_FIN_WAIT1",
    "CONN_FIN_WAIT2", "CONN_TIME_WAIT", "CONN_CLOSE", "CONN_CLOSE_WAIT",
    "CONN_LAST_ACK", "CONN_LISTEN", "CONN_CLOSING", ]


# =====================================================================
# --- globals
# =====================================================================


POWER_SUPPLY_PATH = "/sys/class/power_supply"
HAS_SMAPS = os.path.exists('/proc/%s/smaps' % os.getpid())
HAS_PRLIMIT = hasattr(cext, "linux_prlimit")
_DEFAULT = object()

# RLIMIT_* constants, not guaranteed to be present on all kernels
if HAS_PRLIMIT:
    for name in dir(cext):
        if name.startswith('RLIM'):
            __extra__all__.append(name)

# Number of clock ticks per second
CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
PAGESIZE = os.sysconf("SC_PAGE_SIZE")
BOOT_TIME = None  # set later
# Used when reading "big" files, namely /proc/{pid}/smaps and /proc/net/*.
# On Python 2, using a buffer with open() for such files may result in a
# speedup, see: https://github.com/giampaolo/psutil/issues/708
BIGGER_FILE_BUFFERING = -1 if PY3 else 8192
LITTLE_ENDIAN = sys.byteorder == 'little'
if PY3:
    FS_ENCODING = sys.getfilesystemencoding()
    ENCODING_ERRORS_HANDLER = 'surrogateescape'
if enum is None:
    AF_LINK = socket.AF_PACKET
else:
    AddressFamily = enum.IntEnum('AddressFamily',
                                 {'AF_LINK': int(socket.AF_PACKET)})
    AF_LINK = AddressFamily.AF_LINK

# ioprio_* constants http://linux.die.net/man/2/ioprio_get
if enum is None:
    IOPRIO_CLASS_NONE = 0
    IOPRIO_CLASS_RT = 1
    IOPRIO_CLASS_BE = 2
    IOPRIO_CLASS_IDLE = 3
else:
    class IOPriority(enum.IntEnum):
        IOPRIO_CLASS_NONE = 0
        IOPRIO_CLASS_RT = 1
        IOPRIO_CLASS_BE = 2
        IOPRIO_CLASS_IDLE = 3

    globals().update(IOPriority.__members__)

# taken from /fs/proc/array.c
PROC_STATUSES = {
    "R": _common.STATUS_RUNNING,
    "S": _common.STATUS_SLEEPING,
    "D": _common.STATUS_DISK_SLEEP,
    "T": _common.STATUS_STOPPED,
    "t": _common.STATUS_TRACING_STOP,
    "Z": _common.STATUS_ZOMBIE,
    "X": _common.STATUS_DEAD,
    "x": _common.STATUS_DEAD,
    "K": _common.STATUS_WAKE_KILL,
    "W": _common.STATUS_WAKING
}

# http://students.mimuw.edu.pl/lxr/source/include/net/tcp_states.h
TCP_STATUSES = {
    "01": _common.CONN_ESTABLISHED,
    "02": _common.CONN_SYN_SENT,
    "03": _common.CONN_SYN_RECV,
    "04": _common.CONN_FIN_WAIT1,
    "05": _common.CONN_FIN_WAIT2,
    "06": _common.CONN_TIME_WAIT,
    "07": _common.CONN_CLOSE,
    "08": _common.CONN_CLOSE_WAIT,
    "09": _common.CONN_LAST_ACK,
    "0A": _common.CONN_LISTEN,
    "0B": _common.CONN_CLOSING
}

# these get overwritten on "import psutil" from the __init__.py file
NoSuchProcess = None
ZombieProcess = None
AccessDenied = None
TimeoutExpired = None


# =====================================================================
# --- named tuples
# =====================================================================


# psutil.virtual_memory()
svmem = namedtuple(
    'svmem', ['total', 'available', 'percent', 'used', 'free',
              'active', 'inactive', 'buffers', 'cached', 'shared'])
# psutil.disk_io_counters()
sdiskio = namedtuple(
    'sdiskio', ['read_count', 'write_count',
                'read_bytes', 'write_bytes',
                'read_time', 'write_time',
                'read_merged_count', 'write_merged_count',
                'busy_time'])
# psutil.Process().open_files()
popenfile = namedtuple(
    'popenfile', ['path', 'fd', 'position', 'mode', 'flags'])
# psutil.Process().memory_info()
pmem = namedtuple('pmem', 'rss vms shared text lib data dirty')
# psutil.Process().memory_full_info()
pfullmem = namedtuple('pfullmem', pmem._fields + ('uss', 'pss', 'swap'))
# psutil.Process().memory_maps(grouped=True)
pmmap_grouped = namedtuple(
    'pmmap_grouped',
    ['path', 'rss', 'size', 'pss', 'shared_clean', 'shared_dirty',
     'private_clean', 'private_dirty', 'referenced', 'anonymous', 'swap'])
# psutil.Process().memory_maps(grouped=False)
pmmap_ext = namedtuple(
    'pmmap_ext', 'addr perms ' + ' '.join(pmmap_grouped._fields))
# psutil.Process.io_counters()
pio = namedtuple('pio', ['read_count', 'write_count',
                         'read_bytes', 'write_bytes',
                         'read_chars', 'write_chars'])


# =====================================================================
# --- utils
# =====================================================================


def open_binary(fname, **kwargs):
    return open(fname, "rb", **kwargs)


def open_text(fname, **kwargs):
    """On Python 3 opens a file in text mode by using fs encoding and
    a proper en/decoding errors handler.
    On Python 2 this is just an alias for open(name, 'rt').
    """
    if PY3:
        # See:
        # https://github.com/giampaolo/psutil/issues/675
        # https://github.com/giampaolo/psutil/pull/733
        kwargs.setdefault('encoding', FS_ENCODING)
        kwargs.setdefault('errors', ENCODING_ERRORS_HANDLER)
    return open(fname, "rt", **kwargs)


if PY3:
    def decode(s):
        return s.decode(encoding=FS_ENCODING, errors=ENCODING_ERRORS_HANDLER)
else:
    def decode(s):
        return s


def get_procfs_path():
    """Return updated psutil.PROCFS_PATH constant."""
    return sys.modules['psutil'].PROCFS_PATH


def readlink(path):
    """Wrapper around os.readlink()."""
    assert isinstance(path, basestring), path
    path = os.readlink(path)
    # readlink() might return paths containing null bytes ('\x00')
    # resulting in "TypeError: must be encoded string without NULL
    # bytes, not str" errors when the string is passed to other
    # fs-related functions (os.*, open(), ...).
    # Apparently everything after '\x00' is garbage (we can have
    # ' (deleted)', 'new' and possibly others), see:
    # https://github.com/giampaolo/psutil/issues/717
    path = path.split('\x00')[0]
    # Certain paths have ' (deleted)' appended. Usually this is
    # bogus as the file actually exists. Even if it doesn't we
    # don't care.
    if path.endswith(' (deleted)') and not path_exists_strict(path):
        path = path[:-10]
    return path


def file_flags_to_mode(flags):
    """Convert file's open() flags into a readable string.
    Used by Process.open_files().
    """
    modes_map = {os.O_RDONLY: 'r', os.O_WRONLY: 'w', os.O_RDWR: 'w+'}
    mode = modes_map[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]
    if flags & os.O_APPEND:
        mode = mode.replace('w', 'a', 1)
    mode = mode.replace('w+', 'r+')
    # possible values: r, w, a, r+, a+
    return mode


def get_sector_size(partition):
    """Return the sector size of a partition.
    Used by disk_io_counters().
    """
    try:
        with open("/sys/block/%s/queue/hw_sector_size" % partition, "rt") as f:
            return int(f.read())
    except (IOError, ValueError):
        # man iostat states that sectors are equivalent with blocks and
        # have a size of 512 bytes since 2.4 kernels.
        return 512


@memoize
def set_scputimes_ntuple(procfs_path):
    """Set a namedtuple of variable fields depending on the CPU times
    available on this Linux kernel version which may be:
    (user, nice, system, idle, iowait, irq, softirq, [steal, [guest,
     [guest_nice]]])
    Used by cpu_times() function.
    """
    global scputimes
    with open_binary('%s/stat' % procfs_path) as f:
        values = f.readline().split()[1:]
    fields = ['user', 'nice', 'system', 'idle', 'iowait', 'irq', 'softirq']
    vlen = len(values)
    if vlen >= 8:
        # Linux >= 2.6.11
        fields.append('steal')
    if vlen >= 9:
        # Linux >= 2.6.24
        fields.append('guest')
    if vlen >= 10:
        # Linux >= 3.2.0
        fields.append('guest_nice')
    scputimes = namedtuple('scputimes', fields)


def cat(fname, fallback=_DEFAULT, binary=True):
    """Return file content.
    fallback: the value returned in case the file does not exist or
              cannot be read
    binary: whether to open the file in binary or text mode.
    """
    try:
        with open_binary(fname) if binary else open_text(fname) as f:
            return f.read().strip()
    except IOError:
        if fallback != _DEFAULT:
            return fallback
        raise


try:
    set_scputimes_ntuple("/proc")
except Exception:
    # Don't want to crash at import time.
    traceback.print_exc()
    scputimes = namedtuple('scputimes', 'user system idle')(0.0, 0.0, 0.0)


# =====================================================================
# --- system memory
# =====================================================================


def calculate_avail_vmem(mems):
    """Fallback for kernels < 3.14 where /proc/meminfo does not provide
    "MemAvailable:" column (see: https://blog.famzah.net/2014/09/24/).
    This code reimplements the algorithm outlined here:
    https://git.kernel.org/cgit/linux/kernel/git/torvalds/linux.git/
        commit/?id=34e431b0ae398fc54ea69ff85ec700722c9da773

    XXX: on recent kernels this calculation differs by ~1.5% than
    "MemAvailable:" as it's calculated slightly differently, see:
    https://gitlab.com/procps-ng/procps/issues/42
    https://github.com/famzah/linux-memavailable-procfs/issues/2
    It is still way more realistic than doing (free + cached) though.
    """
    # Fallback for very old distros. According to
    # https://git.kernel.org/cgit/linux/kernel/git/torvalds/linux.git/
    #     commit/?id=34e431b0ae398fc54ea69ff85ec700722c9da773
    # ...long ago "avail" was calculated as (free + cached).
    # We might fallback in such cases:
    # "Active(file)" not available: 2.6.28 / Dec 2008
    # "Inactive(file)" not available: 2.6.28 / Dec 2008
    # "SReclaimable:" not available: 2.6.19 / Nov 2006
    # /proc/zoneinfo not available: 2.6.13 / Aug 2005
    free = mems[b'MemFree:']
    fallback = free + mems.get(b"Cached:", 0)
    try:
        lru_active_file = mems[b'Active(file):']
        lru_inactive_file = mems[b'Inactive(file):']
        slab_reclaimable = mems[b'SReclaimable:']
    except KeyError:
        return fallback
    try:
        f = open_binary('%s/zoneinfo' % get_procfs_path())
    except IOError:
        return fallback  # kernel 2.6.13

    watermark_low = 0
    with f:
        for line in f:
            line = line.strip()
            if line.startswith(b'low'):
                watermark_low += int(line.split()[1])
    watermark_low *= PAGESIZE
    watermark_low = watermark_low

    avail = free - watermark_low
    pagecache = lru_active_file + lru_inactive_file
    pagecache -= min(pagecache / 2, watermark_low)
    avail += pagecache
    avail += slab_reclaimable - min(slab_reclaimable / 2.0, watermark_low)
    return int(avail)


def virtual_memory():
    """Report virtual memory stats.
    This implementation matches "free" and "vmstat -s" cmdline
    utility values and procps-ng-3.3.12 source was used as a reference
    (2016-09-18):
    https://gitlab.com/procps-ng/procps/blob/
        24fd2605c51fccc375ab0287cec33aa767f06718/proc/sysinfo.c
    For reference, procps-ng-3.3.10 is the version available on Ubuntu
    16.04.

    Note about "available" memory: up until psutil 4.3 it was
    calculated as "avail = (free + buffers + cached)". Now
    "MemAvailable:" column (kernel 3.14) from /proc/meminfo is used as
    it's more accurate.
    That matches "available" column in newer versions of "free".
    """
    missing_fields = []
    mems = {}
    with open_binary('%s/meminfo' % get_procfs_path()) as f:
        for line in f:
            fields = line.split()
            mems[fields[0]] = int(fields[1]) * 1024

    # /proc doc states that the available fields in /proc/meminfo vary
    # by architecture and compile options, but these 3 values are also
    # returned by sysinfo(2); as such we assume they are always there.
    total = mems[b'MemTotal:']
    free = mems[b'MemFree:']
    buffers = mems[b'Buffers:']

    try:
        cached = mems[b"Cached:"]
    except KeyError:
        cached = 0
        missing_fields.append('cached')
    else:
        # "free" cmdline utility sums reclaimable to cached.
        # Older versions of procps used to add slab memory instead.
        # This got changed in:
        # https://gitlab.com/procps-ng/procps/commit/
        #     05d751c4f076a2f0118b914c5e51cfbb4762ad8e
        cached += mems.get(b"SReclaimable:", 0)  # since kernel 2.6.19

    try:
        shared = mems[b'Shmem:']  # since kernel 2.6.32
    except KeyError:
        try:
            shared = mems[b'MemShared:']  # kernels 2.4
        except KeyError:
            shared = 0
            missing_fields.append('shared')

    try:
        active = mems[b"Active:"]
    except KeyError:
        active = 0
        missing_fields.append('active')

    try:
        inactive = mems[b"Inactive:"]
    except KeyError:
        try:
            inactive = \
                mems[b"Inact_dirty:"] + \
                mems[b"Inact_clean:"] + \
                mems[b"Inact_laundry:"]
        except KeyError:
            inactive = 0
            missing_fields.append('inactive')

    used = total - free - cached - buffers
    if used < 0:
        # May be symptomatic of running within a LCX container where such
        # values will be dramatically distorted over those of the host.
        used = total - free

    # - starting from 4.4.0 we match free's "available" column.
    #   Before 4.4.0 we calculated it as (free + buffers + cached)
    #   which matched htop.
    # - free and htop available memory differs as per:
    #   http://askubuntu.com/a/369589
    #   http://unix.stackexchange.com/a/65852/168884
    # - MemAvailable has been introduced in kernel 3.14
    try:
        avail = mems[b'MemAvailable:']
    except KeyError:
        avail = calculate_avail_vmem(mems)

    if avail < 0:
        avail = 0
        missing_fields.append('available')

    # If avail is greater than total or our calculation overflows,
    # that's symptomatic of running within a LCX container where such
    # values will be dramatically distorted over those of the host.
    # https://gitlab.com/procps-ng/procps/blob/
    #     24fd2605c51fccc375ab0287cec33aa767f06718/proc/sysinfo.c#L764
    if avail > total:
        avail = free

    percent = usage_percent((total - avail), total, _round=1)

    # Warn about missing metrics which are set to 0.
    if missing_fields:
        msg = "%s memory stats couldn't be determined and %s set to 0" % (
            ", ".join(missing_fields),
            "was" if len(missing_fields) == 1 else "were")
        warnings.warn(msg, RuntimeWarning)

    return svmem(total, avail, percent, used, free,
                 active, inactive, buffers, cached, shared)


def swap_memory():
    """Return swap memory metrics."""
    _, _, _, _, total, free, unit_multiplier = cext.linux_sysinfo()
    total *= unit_multiplier
    free *= unit_multiplier
    used = total - free
    percent = usage_percent(used, total, _round=1)
    # get pgin/pgouts
    try:
        f = open_binary("%s/vmstat" % get_procfs_path())
    except IOError as err:
        # see https://github.com/giampaolo/psutil/issues/722
        msg = "'sin' and 'sout' swap memory stats couldn't " \
              "be determined and were set to 0 (%s)" % str(err)
        warnings.warn(msg, RuntimeWarning)
        sin = sout = 0
    else:
        with f:
            sin = sout = None
            for line in f:
                # values are expressed in 4 kilo bytes, we want
                # bytes instead
                if line.startswith(b'pswpin'):
                    sin = int(line.split(b' ')[1]) * 4 * 1024
                elif line.startswith(b'pswpout'):
                    sout = int(line.split(b' ')[1]) * 4 * 1024
                if sin is not None and sout is not None:
                    break
            else:
                # we might get here when dealing with exotic Linux
                # flavors, see:
                # https://github.com/giampaolo/psutil/issues/313
                msg = "'sin' and 'sout' swap memory stats couldn't " \
                      "be determined and were set to 0"
                warnings.warn(msg, RuntimeWarning)
                sin = sout = 0
    return _common.sswap(total, used, free, percent, sin, sout)


# =====================================================================
# --- CPU
# =====================================================================


def cpu_times():
    """Return a named tuple representing the following system-wide
    CPU times:
    (user, nice, system, idle, iowait, irq, softirq [steal, [guest,
     [guest_nice]]])
    Last 3 fields may not be available on all Linux kernel versions.
    """
    procfs_path = get_procfs_path()
    set_scputimes_ntuple(procfs_path)
    with open_binary('%s/stat' % procfs_path) as f:
        values = f.readline().split()
    fields = values[1:len(scputimes._fields) + 1]
    fields = [float(x) / CLOCK_TICKS for x in fields]
    return scputimes(*fields)


def per_cpu_times():
    """Return a list of namedtuple representing the CPU times
    for every CPU available on the system.
    """
    procfs_path = get_procfs_path()
    set_scputimes_ntuple(procfs_path)
    cpus = []
    with open_binary('%s/stat' % procfs_path) as f:
        # get rid of the first line which refers to system wide CPU stats
        f.readline()
        for line in f:
            if line.startswith(b'cpu'):
                values = line.split()
                fields = values[1:len(scputimes._fields) + 1]
                fields = [float(x) / CLOCK_TICKS for x in fields]
                entry = scputimes(*fields)
                cpus.append(entry)
        return cpus


def cpu_count_logical():
    """Return the number of logical CPUs in the system."""
    try:
        return os.sysconf("SC_NPROCESSORS_ONLN")
    except ValueError:
        # as a second fallback we try to parse /proc/cpuinfo
        num = 0
        with open_binary('%s/cpuinfo' % get_procfs_path()) as f:
            for line in f:
                if line.lower().startswith(b'processor'):
                    num += 1

        # unknown format (e.g. amrel/sparc architectures), see:
        # https://github.com/giampaolo/psutil/issues/200
        # try to parse /proc/stat as a last resort
        if num == 0:
            search = re.compile('cpu\d')
            with open_text('%s/stat' % get_procfs_path()) as f:
                for line in f:
                    line = line.split(' ')[0]
                    if search.match(line):
                        num += 1

        if num == 0:
            # mimic os.cpu_count()
            return None
        return num


def cpu_count_physical():
    """Return the number of physical cores in the system."""
    mapping = {}
    current_info = {}
    with open_binary('%s/cpuinfo' % get_procfs_path()) as f:
        for line in f:
            line = line.strip().lower()
            if not line:
                # new section
                if (b'physical id' in current_info and
                        b'cpu cores' in current_info):
                    mapping[current_info[b'physical id']] = \
                        current_info[b'cpu cores']
                current_info = {}
            else:
                # ongoing section
                if (line.startswith(b'physical id') or
                        line.startswith(b'cpu cores')):
                    key, value = line.split(b'\t:', 1)
                    current_info[key] = int(value)

    # mimic os.cpu_count()
    return sum(mapping.values()) or None


def cpu_stats():
    """Return various CPU stats as a named tuple."""
    with open_binary('%s/stat' % get_procfs_path()) as f:
        ctx_switches = None
        interrupts = None
        soft_interrupts = None
        for line in f:
            if line.startswith(b'ctxt'):
                ctx_switches = int(line.split()[1])
            elif line.startswith(b'intr'):
                interrupts = int(line.split()[1])
            elif line.startswith(b'softirq'):
                soft_interrupts = int(line.split()[1])
            if ctx_switches is not None and soft_interrupts is not None \
                    and interrupts is not None:
                break
    syscalls = 0
    return _common.scpustats(
        ctx_switches, interrupts, soft_interrupts, syscalls)


if os.path.exists("/sys/devices/system/cpu/cpufreq"):

    def cpu_freq():
        """Return frequency metrics for all CPUs.
        Contrarily to other OSes, Linux updates these values in
        real-time.
        """
        # scaling_* files seem preferable to cpuinfo_*, see:
        # http://unix.stackexchange.com/a/87537/168884
        ret = []
        ls = glob.glob("/sys/devices/system/cpu/cpufreq/policy*")
        # Sort the list so that '10' comes after '2'. This should
        # ensure the CPU order is consistent with other CPU functions
        # having a 'percpu' argument and returning results for multiple
        # CPUs (cpu_times(), cpu_percent(), cpu_times_percent()).
        ls.sort(key=lambda x: int(os.path.basename(x)[6:]))
        for path in ls:
            curr = int(cat(os.path.join(path, "scaling_cur_freq"))) / 1000
            max_ = int(cat(os.path.join(path, "scaling_max_freq"))) / 1000
            min_ = int(cat(os.path.join(path, "scaling_min_freq"))) / 1000
            ret.append(_common.scpufreq(curr, min_, max_))
        return ret


# =====================================================================
# --- network
# =====================================================================


net_if_addrs = cext_posix.net_if_addrs


class _Ipv6UnsupportedError(Exception):
    pass


class Connections:
    """A wrapper on top of /proc/net/* files, retrieving per-process
    and system-wide open connections (TCP, UDP, UNIX) similarly to
    "netstat -an".

    Note: in case of UNIX sockets we're only able to determine the
    local endpoint/path, not the one it's connected to.
    According to [1] it would be possible but not easily.

    [1] http://serverfault.com/a/417946
    """

    def __init__(self):
        tcp4 = ("tcp", socket.AF_INET, socket.SOCK_STREAM)
        tcp6 = ("tcp6", socket.AF_INET6, socket.SOCK_STREAM)
        udp4 = ("udp", socket.AF_INET, socket.SOCK_DGRAM)
        udp6 = ("udp6", socket.AF_INET6, socket.SOCK_DGRAM)
        unix = ("unix", socket.AF_UNIX, None)
        self.tmap = {
            "all": (tcp4, tcp6, udp4, udp6, unix),
            "tcp": (tcp4, tcp6),
            "tcp4": (tcp4,),
            "tcp6": (tcp6,),
            "udp": (udp4, udp6),
            "udp4": (udp4,),
            "udp6": (udp6,),
            "unix": (unix,),
            "inet": (tcp4, tcp6, udp4, udp6),
            "inet4": (tcp4, udp4),
            "inet6": (tcp6, udp6),
        }
        self._procfs_path = None

    def get_proc_inodes(self, pid):
        inodes = defaultdict(list)
        for fd in os.listdir("%s/%s/fd" % (self._procfs_path, pid)):
            try:
                inode = readlink("%s/%s/fd/%s" % (self._procfs_path, pid, fd))
            except OSError as err:
                # ENOENT == file which is gone in the meantime;
                # os.stat('/proc/%s' % self.pid) will be done later
                # to force NSP (if it's the case)
                if err.errno in (errno.ENOENT, errno.ESRCH):
                    continue
                elif err.errno == errno.EINVAL:
                    # not a link
                    continue
                else:
                    raise
            else:
                if inode.startswith('socket:['):
                    # the process is using a socket
                    inode = inode[8:][:-1]
                    inodes[inode].append((pid, int(fd)))
        return inodes

    def get_all_inodes(self):
        inodes = {}
        for pid in pids():
            try:
                inodes.update(self.get_proc_inodes(pid))
            except OSError as err:
                # os.listdir() is gonna raise a lot of access denied
                # exceptions in case of unprivileged user; that's fine
                # as we'll just end up returning a connection with PID
                # and fd set to None anyway.
                # Both netstat -an and lsof does the same so it's
                # unlikely we can do any better.
                # ENOENT just means a PID disappeared on us.
                if err.errno not in (
                        errno.ENOENT, errno.ESRCH, errno.EPERM, errno.EACCES):
                    raise
        return inodes

    @staticmethod
    def decode_address(addr, family):
        """Accept an "ip:port" address as displayed in /proc/net/*
        and convert it into a human readable form, like:

        "0500000A:0016" -> ("10.0.0.5", 22)
        "0000000000000000FFFF00000100007F:9E49" -> ("::ffff:127.0.0.1", 40521)

        The IP address portion is a little or big endian four-byte
        hexadecimal number; that is, the least significant byte is listed
        first, so we need to reverse the order of the bytes to convert it
        to an IP address.
        The port is represented as a two-byte hexadecimal number.

        Reference:
        http://linuxdevcenter.com/pub/a/linux/2000/11/16/LinuxAdmin.html
        """
        ip, port = addr.split(':')
        port = int(port, 16)
        # this usually refers to a local socket in listen mode with
        # no end-points connected
        if not port:
            return ()
        if PY3:
            ip = ip.encode('ascii')
        if family == socket.AF_INET:
            # see: https://github.com/giampaolo/psutil/issues/201
            if LITTLE_ENDIAN:
                ip = socket.inet_ntop(family, base64.b16decode(ip)[::-1])
            else:
                ip = socket.inet_ntop(family, base64.b16decode(ip))
        else:  # IPv6
            # old version - let's keep it, just in case...
            # ip = ip.decode('hex')
            # return socket.inet_ntop(socket.AF_INET6,
            #          ''.join(ip[i:i+4][::-1] for i in xrange(0, 16, 4)))
            ip = base64.b16decode(ip)
            try:
                # see: https://github.com/giampaolo/psutil/issues/201
                if LITTLE_ENDIAN:
                    ip = socket.inet_ntop(
                        socket.AF_INET6,
                        struct.pack('>4I', *struct.unpack('<4I', ip)))
                else:
                    ip = socket.inet_ntop(
                        socket.AF_INET6,
                        struct.pack('<4I', *struct.unpack('<4I', ip)))
            except ValueError:
                # see: https://github.com/giampaolo/psutil/issues/623
                if not supports_ipv6():
                    raise _Ipv6UnsupportedError
                else:
                    raise
        return (ip, port)

    @staticmethod
    def process_inet(file, family, type_, inodes, filter_pid=None):
        """Parse /proc/net/tcp* and /proc/net/udp* files."""
        if file.endswith('6') and not os.path.exists(file):
            # IPv6 not supported
            return
        with open_text(file, buffering=BIGGER_FILE_BUFFERING) as f:
            f.readline()  # skip the first line
            for lineno, line in enumerate(f, 1):
                try:
                    _, laddr, raddr, status, _, _, _, _, _, inode = \
                        line.split()[:10]
                except ValueError:
                    raise RuntimeError(
                        "error while parsing %s; malformed line %s %r" % (
                            file, lineno, line))
                if inode in inodes:
                    # # We assume inet sockets are unique, so we error
                    # # out if there are multiple references to the
                    # # same inode. We won't do this for UNIX sockets.
                    # if len(inodes[inode]) > 1 and family != socket.AF_UNIX:
                    #     raise ValueError("ambiguos inode with multiple "
                    #                      "PIDs references")
                    pid, fd = inodes[inode][0]
                else:
                    pid, fd = None, -1
                if filter_pid is not None and filter_pid != pid:
                    continue
                else:
                    if type_ == socket.SOCK_STREAM:
                        status = TCP_STATUSES[status]
                    else:
                        status = _common.CONN_NONE
                    try:
                        laddr = Connections.decode_address(laddr, family)
                        raddr = Connections.decode_address(raddr, family)
                    except _Ipv6UnsupportedError:
                        continue
                    yield (fd, family, type_, laddr, raddr, status, pid)

    @staticmethod
    def process_unix(file, family, inodes, filter_pid=None):
        """Parse /proc/net/unix files."""
        with open_text(file, buffering=BIGGER_FILE_BUFFERING) as f:
            f.readline()  # skip the first line
            for line in f:
                tokens = line.split()
                try:
                    _, _, _, _, type_, _, inode = tokens[0:7]
                except ValueError:
                    if ' ' not in line:
                        # see: https://github.com/giampaolo/psutil/issues/766
                        continue
                    raise RuntimeError(
                        "error while parsing %s; malformed line %r" % (
                            file, line))
                if inode in inodes:
                    # With UNIX sockets we can have a single inode
                    # referencing many file descriptors.
                    pairs = inodes[inode]
                else:
                    pairs = [(None, -1)]
                for pid, fd in pairs:
                    if filter_pid is not None and filter_pid != pid:
                        continue
                    else:
                        if len(tokens) == 8:
                            path = tokens[-1]
                        else:
                            path = ""
                        type_ = int(type_)
                        raddr = None
                        status = _common.CONN_NONE
                        yield (fd, family, type_, path, raddr, status, pid)

    def retrieve(self, kind, pid=None):
        if kind not in self.tmap:
            raise ValueError("invalid %r kind argument; choose between %s"
                             % (kind, ', '.join([repr(x) for x in self.tmap])))
        self._procfs_path = get_procfs_path()
        if pid is not None:
            inodes = self.get_proc_inodes(pid)
            if not inodes:
                # no connections for this process
                return []
        else:
            inodes = self.get_all_inodes()
        ret = set()
        for f, family, type_ in self.tmap[kind]:
            if family in (socket.AF_INET, socket.AF_INET6):
                ls = self.process_inet(
                    "%s/net/%s" % (self._procfs_path, f),
                    family, type_, inodes, filter_pid=pid)
            else:
                ls = self.process_unix(
                    "%s/net/%s" % (self._procfs_path, f),
                    family, inodes, filter_pid=pid)
            for fd, family, type_, laddr, raddr, status, bound_pid in ls:
                if pid:
                    conn = _common.pconn(fd, family, type_, laddr, raddr,
                                         status)
                else:
                    conn = _common.sconn(fd, family, type_, laddr, raddr,
                                         status, bound_pid)
                ret.add(conn)
        return list(ret)


_connections = Connections()


def net_connections(kind='inet'):
    """Return system-wide open connections."""
    return _connections.retrieve(kind)


def net_io_counters():
    """Return network I/O statistics for every network interface
    installed on the system as a dict of raw tuples.
    """
    with open_text("%s/net/dev" % get_procfs_path()) as f:
        lines = f.readlines()
    retdict = {}
    for line in lines[2:]:
        colon = line.rfind(':')
        assert colon > 0, repr(line)
        name = line[:colon].strip()
        fields = line[colon + 1:].strip().split()

        # in
        (bytes_recv,
         packets_recv,
         errin,
         dropin,
         fifoin,  # unused
         framein,  # unused
         compressedin,  # unused
         multicastin,  # unused
         # out
         bytes_sent,
         packets_sent,
         errout,
         dropout,
         fifoout,  # unused
         collisionsout,  # unused
         carrierout,  # unused
         compressedout) = map(int, fields)

        retdict[name] = (bytes_sent, bytes_recv, packets_sent, packets_recv,
                         errin, errout, dropin, dropout)
    return retdict


def net_if_stats():
    """Get NIC stats (isup, duplex, speed, mtu)."""
    duplex_map = {cext.DUPLEX_FULL: NIC_DUPLEX_FULL,
                  cext.DUPLEX_HALF: NIC_DUPLEX_HALF,
                  cext.DUPLEX_UNKNOWN: NIC_DUPLEX_UNKNOWN}
    names = net_io_counters().keys()
    ret = {}
    for name in names:
        mtu = cext_posix.net_if_mtu(name)
        isup = cext_posix.net_if_flags(name)
        duplex, speed = cext.net_if_duplex_speed(name)
        ret[name] = _common.snicstats(isup, duplex_map[duplex], speed, mtu)
    return ret


# =====================================================================
# --- disks
# =====================================================================


disk_usage = _psposix.disk_usage


def disk_io_counters():
    """Return disk I/O statistics for every disk installed on the
    system as a dict of raw tuples.
    """
    # determine partitions we want to look for
    def get_partitions():
        partitions = []
        with open_text("%s/partitions" % get_procfs_path()) as f:
            lines = f.readlines()[2:]
        for line in reversed(lines):
            _, _, _, name = line.split()
            if name[-1].isdigit():
                # we're dealing with a partition (e.g. 'sda1'); 'sda' will
                # also be around but we want to omit it
                partitions.append(name)
            else:
                if not partitions or not partitions[-1].startswith(name):
                    # we're dealing with a disk entity for which no
                    # partitions have been defined (e.g. 'sda' but
                    # 'sda1' was not around), see:
                    # https://github.com/giampaolo/psutil/issues/338
                    partitions.append(name)
        return partitions

    retdict = {}
    partitions = get_partitions()
    with open_text("%s/diskstats" % get_procfs_path()) as f:
        lines = f.readlines()
    for line in lines:
        # OK, this is a bit confusing. The format of /proc/diskstats can
        # have 3 variations.
        # On Linux 2.4 each line has always 15 fields, e.g.:
        # "3     0   8 hda 8 8 8 8 8 8 8 8 8 8 8"
        # On Linux 2.6+ each line *usually* has 14 fields, and the disk
        # name is in another position, like this:
        # "3    0   hda 8 8 8 8 8 8 8 8 8 8 8"
        # ...unless (Linux 2.6) the line refers to a partition instead
        # of a disk, in which case the line has less fields (7):
        # "3    1   hda1 8 8 8 8"
        # See:
        # https://www.kernel.org/doc/Documentation/iostats.txt
        # https://www.kernel.org/doc/Documentation/ABI/testing/procfs-diskstats
        fields = line.split()
        fields_len = len(fields)
        if fields_len == 15:
            # Linux 2.4
            name = fields[3]
            reads = int(fields[2])
            (reads_merged, rbytes, rtime, writes, writes_merged,
                wbytes, wtime, _, busy_time, _) = map(int, fields[4:14])
        elif fields_len == 14:
            # Linux 2.6+, line referring to a disk
            name = fields[2]
            (reads, reads_merged, rbytes, rtime, writes, writes_merged,
                wbytes, wtime, _, busy_time, _) = map(int, fields[3:14])
        elif fields_len == 7:
            # Linux 2.6+, line referring to a partition
            name = fields[2]
            reads, rbytes, writes, wbytes = map(int, fields[3:])
            rtime = wtime = reads_merged = writes_merged = busy_time = 0
        else:
            raise ValueError("not sure how to interpret line %r" % line)

        if name in partitions:
            sector_size = get_sector_size(name)
            rbytes = rbytes * sector_size
            wbytes = wbytes * sector_size
            retdict[name] = (reads, writes, rbytes, wbytes, rtime, wtime,
                             reads_merged, writes_merged, busy_time)
    return retdict


def disk_partitions(all=False):
    """Return mounted disk partitions as a list of namedtuples."""
    fstypes = set()
    with open_text("%s/filesystems" % get_procfs_path()) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("nodev"):
                fstypes.add(line.strip())
            else:
                # ignore all lines starting with "nodev" except "nodev zfs"
                fstype = line.split("\t")[1]
                if fstype == "zfs":
                    fstypes.add("zfs")

    retlist = []
    partitions = cext.disk_partitions()
    for partition in partitions:
        device, mountpoint, fstype, opts = partition
        if device == 'none':
            device = ''
        if not all:
            if device == '' or fstype not in fstypes:
                continue
        ntuple = _common.sdiskpart(device, mountpoint, fstype, opts)
        retlist.append(ntuple)
    return retlist


# =====================================================================
# --- sensors
# =====================================================================


def sensors_temperatures():
    """Return hardware (CPU and others) temperatures as a dict
    including hardware name, label, current, max and critical
    temperatures.

    Implementation notes:
    - /sys/class/hwmon looks like the most recent interface to
      retrieve this info, and this implementation relies on it
      only (old distros will probably use something else)
    - lm-sensors on Ubuntu 16.04 relies on /sys/class/hwmon
    - /sys/class/thermal/thermal_zone* is another one but it's more
      difficult to parse
    """
    ret = collections.defaultdict(list)
    basenames = glob.glob('/sys/class/hwmon/hwmon*/temp*_*')
    if not basenames:
        # CentOS has an intermediate /device directory:
        # https://github.com/giampaolo/psutil/issues/971
        basenames = glob.glob('/sys/class/hwmon/hwmon*/device/temp*_*')

    basenames = sorted(set([x.split('_')[0] for x in basenames]))
    for base in basenames:
        unit_name = cat(os.path.join(os.path.dirname(base), 'name'),
                        binary=False)
        label = cat(base + '_label', fallback='', binary=False)
        current = float(cat(base + '_input')) / 1000.0
        high = cat(base + '_max', fallback=None)
        critical = cat(base + '_crit', fallback=None)

        if high is not None:
            high = float(high) / 1000.0
        if critical is not None:
            critical = float(critical) / 1000.0

        ret[unit_name].append((label, current, high, critical))

    return ret


def sensors_fans():
    """Return hardware (CPU and others) fans as a dict
    including hardware label, current speed.

    Implementation notes:
    - /sys/class/hwmon looks like the most recent interface to
      retrieve this info, and this implementation relies on it
      only (old distros will probably use something else)
    - lm-sensors on Ubuntu 16.04 relies on /sys/class/hwmon
    """
    ret = collections.defaultdict(list)
    basenames = glob.glob('/sys/class/hwmon/hwmon*/fan*_*')
    if not basenames:
        # CentOS has an intermediate /device directory:
        # https://github.com/giampaolo/psutil/issues/971
        basenames = glob.glob('/sys/class/hwmon/hwmon*/device/fan*_*')

    basenames = sorted(set([x.split('_')[0] for x in basenames]))
    for base in basenames:
        unit_name = cat(os.path.join(os.path.dirname(base), 'name'),
                        binary=False)
        label = cat(base + '_label', fallback='', binary=False)
        current = int(cat(base + '_input'))

        ret[unit_name].append(_common.sfan(label, current))

    return dict(ret)


def sensors_battery():
    """Return battery information.
    Implementation note: it appears /sys/class/power_supply/BAT0/
    directory structure may vary and provide files with the same
    meaning but under different names, see:
    https://github.com/giampaolo/psutil/issues/966
    """
    null = object()

    def multi_cat(*paths):
        """Attempt to read the content of multiple files which may
        not exist. If none of them exist return None.
        """
        for path in paths:
            ret = cat(path, fallback=null)
            if ret != null:
                return int(ret) if ret.isdigit() else ret
        return None

    root = os.path.join(POWER_SUPPLY_PATH, "BAT0")
    if not os.path.exists(root):
        return None

    # Base metrics.
    energy_now = multi_cat(
        root + "/energy_now",
        root + "/charge_now")
    power_now = multi_cat(
        root + "/power_now",
        root + "/current_now")
    energy_full = multi_cat(
        root + "/energy_full",
        root + "/charge_full")
    if energy_now is None or power_now is None:
        return None

    # Percent. If we have energy_full the percentage will be more
    # accurate compared to reading /capacity file (float vs. int).
    if energy_full is not None:
        try:
            percent = 100.0 * energy_now / energy_full
        except ZeroDivisionError:
            percent = 0.0
    else:
        percent = int(cat(root + "/capacity", fallback=-1))
        if percent == -1:
            return None

    # Is AC power cable plugged in?
    # Note: AC0 is not always available and sometimes (e.g. CentOS7)
    # it's called "AC".
    power_plugged = None
    online = multi_cat(
        os.path.join(POWER_SUPPLY_PATH, "AC0/online"),
        os.path.join(POWER_SUPPLY_PATH, "AC/online"))
    if online is not None:
        power_plugged = online == 1
    else:
        status = cat(root + "/status", fallback="", binary=False).lower()
        if status == "discharging":
            power_plugged = False
        elif status in ("charging", "full"):
            power_plugged = True

    # Seconds left.
    # Note to self: we may also calculate the charging ETA as per:
    # https://github.com/thialfihar/dotfiles/blob/
    #     013937745fd9050c30146290e8f963d65c0179e6/bin/battery.py#L55
    if power_plugged:
        secsleft = _common.POWER_TIME_UNLIMITED
    else:
        try:
            secsleft = int(energy_now / power_now * 3600)
        except ZeroDivisionError:
            secsleft = _common.POWER_TIME_UNKNOWN

    return _common.sbattery(percent, secsleft, power_plugged)


# =====================================================================
# --- other system functions
# =====================================================================


def users():
    """Return currently connected users as a list of namedtuples."""
    retlist = []
    rawlist = cext.users()
    for item in rawlist:
        user, tty, hostname, tstamp, user_process = item
        # note: the underlying C function includes entries about
        # system boot, run level and others.  We might want
        # to use them in the future.
        if not user_process:
            continue
        if hostname == ':0.0' or hostname == ':0':
            hostname = 'localhost'
        nt = _common.suser(user, tty or None, hostname, tstamp)
        retlist.append(nt)
    return retlist


def boot_time():
    """Return the system boot time expressed in seconds since the epoch."""
    global BOOT_TIME
    with open_binary('%s/stat' % get_procfs_path()) as f:
        for line in f:
            if line.startswith(b'btime'):
                ret = float(line.strip().split()[1])
                BOOT_TIME = ret
                return ret
        raise RuntimeError(
            "line 'btime' not found in %s/stat" % get_procfs_path())


# =====================================================================
# --- processes
# =====================================================================


def pids():
    """Returns a list of PIDs currently running on the system."""
    return [int(x) for x in os.listdir(b(get_procfs_path())) if x.isdigit()]


def pid_exists(pid):
    """Check for the existence of a unix PID."""
    if not _psposix.pid_exists(pid):
        return False
    else:
        # Linux's apparently does not distinguish between PIDs and TIDs
        # (thread IDs).
        # listdir("/proc") won't show any TID (only PIDs) but
        # os.stat("/proc/{tid}") will succeed if {tid} exists.
        # os.kill() can also be passed a TID. This is quite confusing.
        # In here we want to enforce this distinction and support PIDs
        # only, see:
        # https://github.com/giampaolo/psutil/issues/687
        try:
            # Note: already checked that this is faster than using a
            # regular expr. Also (a lot) faster than doing
            # 'return pid in pids()'
            with open_binary("%s/%s/status" % (get_procfs_path(), pid)) as f:
                for line in f:
                    if line.startswith(b"Tgid:"):
                        tgid = int(line.split()[1])
                        # If tgid and pid are the same then we're
                        # dealing with a process PID.
                        return tgid == pid
                raise ValueError("'Tgid' line not found")
        except (EnvironmentError, ValueError):
            return pid in pids()


def wrap_exceptions(fun):
    """Decorator which translates bare OSError and IOError exceptions
    into NoSuchProcess and AccessDenied.
    """
    @functools.wraps(fun)
    def wrapper(self, *args, **kwargs):
        try:
            return fun(self, *args, **kwargs)
        except EnvironmentError as err:
            # ENOENT (no such file or directory) gets raised on open().
            # ESRCH (no such process) can get raised on read() if
            # process is gone in meantime.
            if err.errno in (errno.ENOENT, errno.ESRCH):
                raise NoSuchProcess(self.pid, self._name)
            if err.errno in (errno.EPERM, errno.EACCES):
                raise AccessDenied(self.pid, self._name)
            raise
    return wrapper


class Process(object):
    """Linux process implementation."""

    __slots__ = ["pid", "_name", "_ppid", "_procfs_path"]

    def __init__(self, pid):
        self.pid = pid
        self._name = None
        self._ppid = None
        self._procfs_path = get_procfs_path()

    @memoize_when_activated
    def _parse_stat_file(self):
        """Parse /proc/{pid}/stat file. Return a list of fields where
        process name is in position 0.
        Using "man proc" as a reference: where "man proc" refers to
        position N, always substract 2 (e.g starttime pos 22 in
        'man proc' == pos 20 in the list returned here).

        The return value is cached in case oneshot() ctx manager is
        in use.
        """
        with open_binary("%s/%s/stat" % (self._procfs_path, self.pid)) as f:
            data = f.read()
        # Process name is between parentheses. It can contain spaces and
        # other parentheses. This is taken into account by looking for
        # the first occurrence of "(" and the last occurence of ")".
        rpar = data.rfind(b')')
        name = data[data.find(b'(') + 1:rpar]
        fields_after_name = data[rpar + 2:].split()
        return [name] + fields_after_name

    @memoize_when_activated
    def _read_status_file(self):
        """Read /proc/{pid}/stat file and return its content.

        The return value is cached in case oneshot() ctx manager is
        in use.
        """
        with open_binary("%s/%s/status" % (self._procfs_path, self.pid)) as f:
            return f.read()

    @memoize_when_activated
    def _read_smaps_file(self):
        with open_binary("%s/%s/smaps" % (self._procfs_path, self.pid),
                         buffering=BIGGER_FILE_BUFFERING) as f:
            return f.read().strip()

    def oneshot_enter(self):
        self._parse_stat_file.cache_activate()
        self._read_status_file.cache_activate()
        self._read_smaps_file.cache_activate()

    def oneshot_exit(self):
        self._parse_stat_file.cache_deactivate()
        self._read_status_file.cache_deactivate()
        self._read_smaps_file.cache_deactivate()

    @wrap_exceptions
    def name(self):
        name = self._parse_stat_file()[0]
        if PY3:
            name = decode(name)
        # XXX - gets changed later and probably needs refactoring
        return name

    def exe(self):
        try:
            return readlink("%s/%s/exe" % (self._procfs_path, self.pid))
        except OSError as err:
            if err.errno in (errno.ENOENT, errno.ESRCH):
                # no such file error; might be raised also if the
                # path actually exists for system processes with
                # low pids (about 0-20)
                if os.path.lexists("%s/%s" % (self._procfs_path, self.pid)):
                    return ""
                else:
                    if not pid_exists(self.pid):
                        raise NoSuchProcess(self.pid, self._name)
                    else:
                        raise ZombieProcess(self.pid, self._name, self._ppid)
            if err.errno in (errno.EPERM, errno.EACCES):
                raise AccessDenied(self.pid, self._name)
            raise

    @wrap_exceptions
    def cmdline(self):
        with open_text("%s/%s/cmdline" % (self._procfs_path, self.pid)) as f:
            data = f.read()
        if not data:
            # may happen in case of zombie process
            return []
        if data.endswith('\x00'):
            data = data[:-1]
        return [x for x in data.split('\x00')]

    @wrap_exceptions
    def environ(self):
        with open_text("%s/%s/environ" % (self._procfs_path, self.pid)) as f:
            data = f.read()
        return parse_environ_block(data)

    @wrap_exceptions
    def terminal(self):
        tty_nr = int(self._parse_stat_file()[5])
        tmap = _psposix.get_terminal_map()
        try:
            return tmap[tty_nr]
        except KeyError:
            return None

    if os.path.exists('/proc/%s/io' % os.getpid()):
        @wrap_exceptions
        def io_counters(self):
            fname = "%s/%s/io" % (self._procfs_path, self.pid)
            fields = {}
            with open_binary(fname) as f:
                for line in f:
                    name, value = line.split(b': ')
                    fields[name] = int(value)
            return pio(
                fields[b'syscr'],  # read syscalls
                fields[b'syscw'],  # write syscalls
                fields[b'read_bytes'],  # read bytes
                fields[b'write_bytes'],  # write bytes
                fields[b'rchar'],  # read chars
                fields[b'wchar'],  # write chars
            )
    else:
        def io_counters(self):
            raise NotImplementedError("couldn't find /proc/%s/io (kernel "
                                      "too old?)" % self.pid)

    @wrap_exceptions
    def cpu_times(self):
        values = self._parse_stat_file()
        utime = float(values[12]) / CLOCK_TICKS
        stime = float(values[13]) / CLOCK_TICKS
        children_utime = float(values[14]) / CLOCK_TICKS
        children_stime = float(values[15]) / CLOCK_TICKS
        return _common.pcputimes(utime, stime, children_utime, children_stime)

    @wrap_exceptions
    def cpu_num(self):
        """What CPU the process is on."""
        return int(self._parse_stat_file()[37])

    @wrap_exceptions
    def wait(self, timeout=None):
        try:
            return _psposix.wait_pid(self.pid, timeout)
        except _psposix.TimeoutExpired:
            raise TimeoutExpired(timeout, self.pid, self._name)

    @wrap_exceptions
    def create_time(self):
        values = self._parse_stat_file()
        # According to documentation, starttime is in field 21 and the
        # unit is jiffies (clock ticks).
        # We first divide it for clock ticks and then add uptime returning
        # seconds since the epoch, in UTC.
        # Also use cached value if available.
        bt = BOOT_TIME or boot_time()
        return (float(values[20]) / CLOCK_TICKS) + bt

    @wrap_exceptions
    def memory_info(self):
        #  ============================================================
        # | FIELD  | DESCRIPTION                         | AKA  | TOP  |
        #  ============================================================
        # | rss    | resident set size                   |      | RES  |
        # | vms    | total program size                  | size | VIRT |
        # | shared | shared pages (from shared mappings) |      | SHR  |
        # | text   | text ('code')                       | trs  | CODE |
        # | lib    | library (unused in Linux 2.6)       | lrs  |      |
        # | data   | data + stack                        | drs  | DATA |
        # | dirty  | dirty pages (unused in Linux 2.6)   | dt   |      |
        #  ============================================================
        with open_binary("%s/%s/statm" % (self._procfs_path, self.pid)) as f:
            vms, rss, shared, text, lib, data, dirty = \
                [int(x) * PAGESIZE for x in f.readline().split()[:7]]
        return pmem(rss, vms, shared, text, lib, data, dirty)

    # /proc/pid/smaps does not exist on kernels < 2.6.14 or if
    # CONFIG_MMU kernel configuration option is not enabled.
    if HAS_SMAPS:

        @wrap_exceptions
        def memory_full_info(
                self,
                _private_re=re.compile(b"Private.*:\s+(\d+)"),
                _pss_re=re.compile(b"Pss.*:\s+(\d+)"),
                _swap_re=re.compile(b"Swap.*:\s+(\d+)")):
            basic_mem = self.memory_info()
            # Note: using 3 regexes is faster than reading the file
            # line by line.
            # XXX: on Python 3 the 2 regexes are 30% slower than on
            # Python 2 though. Figure out why.
            #
            # You might be tempted to calculate USS by subtracting
            # the "shared" value from the "resident" value in
            # /proc/<pid>/statm. But at least on Linux, statm's "shared"
            # value actually counts pages backed by files, which has
            # little to do with whether the pages are actually shared.
            # /proc/self/smaps on the other hand appears to give us the
            # correct information.
            smaps_data = self._read_smaps_file()
            # Note: smaps file can be empty for certain processes.
            # The code below will not crash though and will result to 0.
            uss = sum(map(int, _private_re.findall(smaps_data))) * 1024
            pss = sum(map(int, _pss_re.findall(smaps_data))) * 1024
            swap = sum(map(int, _swap_re.findall(smaps_data))) * 1024
            return pfullmem(*basic_mem + (uss, pss, swap))

    else:
        memory_full_info = memory_info

    if HAS_SMAPS:

        @wrap_exceptions
        def memory_maps(self):
            """Return process's mapped memory regions as a list of named
            tuples. Fields are explained in 'man proc'; here is an updated
            (Apr 2012) version: http://goo.gl/fmebo
            """
            def get_blocks(lines, current_block):
                data = {}
                for line in lines:
                    fields = line.split(None, 5)
                    if not fields[0].endswith(b':'):
                        # new block section
                        yield (current_block.pop(), data)
                        current_block.append(line)
                    else:
                        try:
                            data[fields[0]] = int(fields[1]) * 1024
                        except ValueError:
                            if fields[0].startswith(b'VmFlags:'):
                                # see issue #369
                                continue
                            else:
                                raise ValueError("don't know how to inte"
                                                 "rpret line %r" % line)
                yield (current_block.pop(), data)

            data = self._read_smaps_file()
            # Note: smaps file can be empty for certain processes.
            if not data:
                return []
            lines = data.split(b'\n')
            ls = []
            first_line = lines.pop(0)
            current_block = [first_line]
            for header, data in get_blocks(lines, current_block):
                hfields = header.split(None, 5)
                try:
                    addr, perms, offset, dev, inode, path = hfields
                except ValueError:
                    addr, perms, offset, dev, inode, path = \
                        hfields + ['']
                if not path:
                    path = '[anon]'
                else:
                    if PY3:
                        path = decode(path)
                    path = path.strip()
                    if (path.endswith(' (deleted)') and not
                            path_exists_strict(path)):
                        path = path[:-10]
                ls.append((
                    decode(addr), decode(perms), path,
                    data[b'Rss:'],
                    data.get(b'Size:', 0),
                    data.get(b'Pss:', 0),
                    data.get(b'Shared_Clean:', 0),
                    data.get(b'Shared_Dirty:', 0),
                    data.get(b'Private_Clean:', 0),
                    data.get(b'Private_Dirty:', 0),
                    data.get(b'Referenced:', 0),
                    data.get(b'Anonymous:', 0),
                    data.get(b'Swap:', 0)
                ))
            return ls

    else:
        def memory_maps(self):
            raise NotImplementedError(
                "/proc/%s/smaps does not exist on kernels < 2.6.14 or "
                "if CONFIG_MMU kernel configuration option is not "
                "enabled." % self.pid)

    @wrap_exceptions
    def cwd(self):
        try:
            return readlink("%s/%s/cwd" % (self._procfs_path, self.pid))
        except OSError as err:
            # https://github.com/giampaolo/psutil/issues/986
            if err.errno in (errno.ENOENT, errno.ESRCH):
                if not pid_exists(self.pid):
                    raise NoSuchProcess(self.pid, self._name)
                else:
                    raise ZombieProcess(self.pid, self._name, self._ppid)
            raise

    @wrap_exceptions
    def num_ctx_switches(self, _ctxsw_re=re.compile(b'ctxt_switches:\t(\d+)')):
        data = self._read_status_file()
        ctxsw = _ctxsw_re.findall(data)
        if not ctxsw:
            raise NotImplementedError(
                "'voluntary_ctxt_switches' and 'nonvoluntary_ctxt_switches'"
                "lines were not found in %s/%s/status; the kernel is "
                "probably older than 2.6.23" % (
                    self._procfs_path, self.self.pid))
        else:
            return _common.pctxsw(int(ctxsw[0]), int(ctxsw[1]))

    @wrap_exceptions
    def num_threads(self, _num_threads_re=re.compile(b'Threads:\t(\d+)')):
        # Note: on Python 3 using a re is faster than iterating over file
        # line by line. On Python 2 is the exact opposite, and iterating
        # over a file on Python 3 is slower than on Python 2.
        data = self._read_status_file()
        return int(_num_threads_re.findall(data)[0])

    @wrap_exceptions
    def threads(self):
        thread_ids = os.listdir("%s/%s/task" % (self._procfs_path, self.pid))
        thread_ids.sort()
        retlist = []
        hit_enoent = False
        for thread_id in thread_ids:
            fname = "%s/%s/task/%s/stat" % (
                self._procfs_path, self.pid, thread_id)
            try:
                with open_binary(fname) as f:
                    st = f.read().strip()
            except IOError as err:
                if err.errno == errno.ENOENT:
                    # no such file or directory; it means thread
                    # disappeared on us
                    hit_enoent = True
                    continue
                raise
            # ignore the first two values ("pid (exe)")
            st = st[st.find(b')') + 2:]
            values = st.split(b' ')
            utime = float(values[11]) / CLOCK_TICKS
            stime = float(values[12]) / CLOCK_TICKS
            ntuple = _common.pthread(int(thread_id), utime, stime)
            retlist.append(ntuple)
        if hit_enoent:
            # raise NSP if the process disappeared on us
            os.stat('%s/%s' % (self._procfs_path, self.pid))
        return retlist

    @wrap_exceptions
    def nice_get(self):
        # with open_text('%s/%s/stat' % (self._procfs_path, self.pid)) as f:
        #   data = f.read()
        #   return int(data.split()[18])

        # Use C implementation
        return cext_posix.getpriority(self.pid)

    @wrap_exceptions
    def nice_set(self, value):
        return cext_posix.setpriority(self.pid, value)

    @wrap_exceptions
    def cpu_affinity_get(self):
        return cext.proc_cpu_affinity_get(self.pid)

    def _get_eligible_cpus(
            self, _re=re.compile(b"Cpus_allowed_list:\t(\d+)-(\d+)")):
        # See: https://github.com/giampaolo/psutil/issues/956
        data = self._read_status_file()
        match = _re.findall(data)
        if match:
            return list(range(int(match[0][0]), int(match[0][1]) + 1))
        else:
            return list(range(len(per_cpu_times())))

    @wrap_exceptions
    def cpu_affinity_set(self, cpus):
        try:
            cext.proc_cpu_affinity_set(self.pid, cpus)
        except (OSError, ValueError) as err:
            if isinstance(err, ValueError) or err.errno == errno.EINVAL:
                eligible_cpus = self._get_eligible_cpus()
                all_cpus = tuple(range(len(per_cpu_times())))
                for cpu in cpus:
                    if cpu not in all_cpus:
                        raise ValueError(
                            "invalid CPU number %r; choose between %s" % (
                                cpu, eligible_cpus))
                    if cpu not in eligible_cpus:
                        raise ValueError(
                            "CPU number %r is not eligible; choose "
                            "between %s" % (cpu, eligible_cpus))
            raise

    # only starting from kernel 2.6.13
    if hasattr(cext, "proc_ioprio_get"):

        @wrap_exceptions
        def ionice_get(self):
            ioclass, value = cext.proc_ioprio_get(self.pid)
            if enum is not None:
                ioclass = IOPriority(ioclass)
            return _common.pionice(ioclass, value)

        @wrap_exceptions
        def ionice_set(self, ioclass, value):
            if value is not None:
                if not PY3 and not isinstance(value, (int, long)):
                    msg = "value argument is not an integer (gor %r)" % value
                    raise TypeError(msg)
                if not 0 <= value <= 7:
                    raise ValueError(
                        "value argument range expected is between 0 and 7")

            if ioclass in (IOPRIO_CLASS_NONE, None):
                if value:
                    msg = "can't specify value with IOPRIO_CLASS_NONE " \
                          "(got %r)" % value
                    raise ValueError(msg)
                ioclass = IOPRIO_CLASS_NONE
                value = 0
            elif ioclass == IOPRIO_CLASS_IDLE:
                if value:
                    msg = "can't specify value with IOPRIO_CLASS_IDLE " \
                          "(got %r)" % value
                    raise ValueError(msg)
                value = 0
            elif ioclass in (IOPRIO_CLASS_RT, IOPRIO_CLASS_BE):
                if value is None:
                    # TODO: add comment explaining why this is 4 (?)
                    value = 4
            else:
                # otherwise we would get OSError(EVINAL)
                raise ValueError("invalid ioclass argument %r" % ioclass)

            return cext.proc_ioprio_set(self.pid, ioclass, value)

    if HAS_PRLIMIT:
        @wrap_exceptions
        def rlimit(self, resource, limits=None):
            # If pid is 0 prlimit() applies to the calling process and
            # we don't want that. We should never get here though as
            # PID 0 is not supported on Linux.
            if self.pid == 0:
                raise ValueError("can't use prlimit() against PID 0 process")
            try:
                if limits is None:
                    # get
                    return cext.linux_prlimit(self.pid, resource)
                else:
                    # set
                    if len(limits) != 2:
                        raise ValueError(
                            "second argument must be a (soft, hard) tuple, "
                            "got %s" % repr(limits))
                    soft, hard = limits
                    cext.linux_prlimit(self.pid, resource, soft, hard)
            except OSError as err:
                if err.errno == errno.ENOSYS and pid_exists(self.pid):
                    # I saw this happening on Travis:
                    # https://travis-ci.org/giampaolo/psutil/jobs/51368273
                    raise ZombieProcess(self.pid, self._name, self._ppid)
                else:
                    raise

    @wrap_exceptions
    def status(self):
        letter = self._parse_stat_file()[1]
        if PY3:
            letter = letter.decode()
        # XXX is '?' legit? (we're not supposed to return it anyway)
        return PROC_STATUSES.get(letter, '?')

    @wrap_exceptions
    def open_files(self):
        retlist = []
        files = os.listdir("%s/%s/fd" % (self._procfs_path, self.pid))
        hit_enoent = False
        for fd in files:
            file = "%s/%s/fd/%s" % (self._procfs_path, self.pid, fd)
            try:
                path = readlink(file)
            except OSError as err:
                # ENOENT == file which is gone in the meantime
                if err.errno in (errno.ENOENT, errno.ESRCH):
                    hit_enoent = True
                    continue
                elif err.errno == errno.EINVAL:
                    # not a link
                    continue
                else:
                    raise
            else:
                # If path is not an absolute there's no way to tell
                # whether it's a regular file or not, so we skip it.
                # A regular file is always supposed to be have an
                # absolute path though.
                if path.startswith('/') and isfile_strict(path):
                    # Get file position and flags.
                    file = "%s/%s/fdinfo/%s" % (
                        self._procfs_path, self.pid, fd)
                    with open_binary(file) as f:
                        pos = int(f.readline().split()[1])
                        flags = int(f.readline().split()[1], 8)
                    mode = file_flags_to_mode(flags)
                    ntuple = popenfile(path, int(fd), int(pos), mode, flags)
                    retlist.append(ntuple)
        if hit_enoent:
            # raise NSP if the process disappeared on us
            os.stat('%s/%s' % (self._procfs_path, self.pid))
        return retlist

    @wrap_exceptions
    def connections(self, kind='inet'):
        ret = _connections.retrieve(kind, self.pid)
        # raise NSP if the process disappeared on us
        os.stat('%s/%s' % (self._procfs_path, self.pid))
        return ret

    @wrap_exceptions
    def num_fds(self):
        return len(os.listdir("%s/%s/fd" % (self._procfs_path, self.pid)))

    @wrap_exceptions
    def ppid(self):
        return int(self._parse_stat_file()[2])

    @wrap_exceptions
    def uids(self, _uids_re=re.compile(b'Uid:\t(\d+)\t(\d+)\t(\d+)')):
        data = self._read_status_file()
        real, effective, saved = _uids_re.findall(data)[0]
        return _common.puids(int(real), int(effective), int(saved))

    @wrap_exceptions
    def gids(self, _gids_re=re.compile(b'Gid:\t(\d+)\t(\d+)\t(\d+)')):
        data = self._read_status_file()
        real, effective, saved = _gids_re.findall(data)[0]
        return _common.pgids(int(real), int(effective), int(saved))
