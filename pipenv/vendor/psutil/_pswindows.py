# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Windows platform implementation."""

import contextlib
import errno
import functools
import os
import sys
from collections import namedtuple

from . import _common
try:
    from . import _psutil_windows as cext
except ImportError as err:
    if str(err).lower().startswith("dll load failed") and \
            sys.getwindowsversion()[0] < 6:
        # We may get here if:
        # 1) we are on an old Windows version
        # 2) psutil was installed via pip + wheel
        # See: https://github.com/giampaolo/psutil/issues/811
        # It must be noted that psutil can still (kind of) work
        # on outdated systems if compiled / installed from sources,
        # but if we get here it means this this was a wheel (or exe).
        msg = "this Windows version is too old (< Windows Vista); "
        msg += "psutil 3.4.2 is the latest version which supports Windows "
        msg += "2000, XP and 2003 server"
        raise RuntimeError(msg)
    else:
        raise

from ._common import conn_tmap
from ._common import isfile_strict
from ._common import parse_environ_block
from ._common import sockfam_to_enum
from ._common import socktype_to_enum
from ._common import usage_percent
from ._common import memoize_when_activated
from ._compat import long
from ._compat import lru_cache
from ._compat import PY3
from ._compat import xrange
from ._psutil_windows import ABOVE_NORMAL_PRIORITY_CLASS
from ._psutil_windows import BELOW_NORMAL_PRIORITY_CLASS
from ._psutil_windows import HIGH_PRIORITY_CLASS
from ._psutil_windows import IDLE_PRIORITY_CLASS
from ._psutil_windows import NORMAL_PRIORITY_CLASS
from ._psutil_windows import REALTIME_PRIORITY_CLASS

if sys.version_info >= (3, 4):
    import enum
else:
    enum = None

# process priority constants, import from __init__.py:
# http://msdn.microsoft.com/en-us/library/ms686219(v=vs.85).aspx
__extra__all__ = [
    "win_service_iter", "win_service_get",
    "ABOVE_NORMAL_PRIORITY_CLASS", "BELOW_NORMAL_PRIORITY_CLASS",
    "HIGH_PRIORITY_CLASS", "IDLE_PRIORITY_CLASS",
    "NORMAL_PRIORITY_CLASS", "REALTIME_PRIORITY_CLASS",
    "CONN_DELETE_TCB",
    "AF_LINK",
]


# =====================================================================
# --- globals
# =====================================================================


CONN_DELETE_TCB = "DELETE_TCB"
WAIT_TIMEOUT = 0x00000102  # 258 in decimal
ACCESS_DENIED_SET = frozenset([errno.EPERM, errno.EACCES,
                               cext.ERROR_ACCESS_DENIED])

if enum is None:
    AF_LINK = -1
else:
    AddressFamily = enum.IntEnum('AddressFamily', {'AF_LINK': -1})
    AF_LINK = AddressFamily.AF_LINK

TCP_STATUSES = {
    cext.MIB_TCP_STATE_ESTAB: _common.CONN_ESTABLISHED,
    cext.MIB_TCP_STATE_SYN_SENT: _common.CONN_SYN_SENT,
    cext.MIB_TCP_STATE_SYN_RCVD: _common.CONN_SYN_RECV,
    cext.MIB_TCP_STATE_FIN_WAIT1: _common.CONN_FIN_WAIT1,
    cext.MIB_TCP_STATE_FIN_WAIT2: _common.CONN_FIN_WAIT2,
    cext.MIB_TCP_STATE_TIME_WAIT: _common.CONN_TIME_WAIT,
    cext.MIB_TCP_STATE_CLOSED: _common.CONN_CLOSE,
    cext.MIB_TCP_STATE_CLOSE_WAIT: _common.CONN_CLOSE_WAIT,
    cext.MIB_TCP_STATE_LAST_ACK: _common.CONN_LAST_ACK,
    cext.MIB_TCP_STATE_LISTEN: _common.CONN_LISTEN,
    cext.MIB_TCP_STATE_CLOSING: _common.CONN_CLOSING,
    cext.MIB_TCP_STATE_DELETE_TCB: CONN_DELETE_TCB,
    cext.PSUTIL_CONN_NONE: _common.CONN_NONE,
}

if enum is not None:
    class Priority(enum.IntEnum):
        ABOVE_NORMAL_PRIORITY_CLASS = ABOVE_NORMAL_PRIORITY_CLASS
        BELOW_NORMAL_PRIORITY_CLASS = BELOW_NORMAL_PRIORITY_CLASS
        HIGH_PRIORITY_CLASS = HIGH_PRIORITY_CLASS
        IDLE_PRIORITY_CLASS = IDLE_PRIORITY_CLASS
        NORMAL_PRIORITY_CLASS = NORMAL_PRIORITY_CLASS
        REALTIME_PRIORITY_CLASS = REALTIME_PRIORITY_CLASS

    globals().update(Priority.__members__)

pinfo_map = dict(
    num_handles=0,
    ctx_switches=1,
    user_time=2,
    kernel_time=3,
    create_time=4,
    num_threads=5,
    io_rcount=6,
    io_wcount=7,
    io_rbytes=8,
    io_wbytes=9,
    io_count_others=10,
    io_bytes_others=11,
    num_page_faults=12,
    peak_wset=13,
    wset=14,
    peak_paged_pool=15,
    paged_pool=16,
    peak_non_paged_pool=17,
    non_paged_pool=18,
    pagefile=19,
    peak_pagefile=20,
    mem_private=21,
)

# these get overwritten on "import psutil" from the __init__.py file
NoSuchProcess = None
AccessDenied = None
TimeoutExpired = None


# =====================================================================
# --- named tuples
# =====================================================================


# psutil.cpu_times()
scputimes = namedtuple('scputimes',
                       ['user', 'system', 'idle', 'interrupt', 'dpc'])
# psutil.virtual_memory()
svmem = namedtuple('svmem', ['total', 'available', 'percent', 'used', 'free'])
# psutil.Process.memory_info()
pmem = namedtuple(
    'pmem', ['rss', 'vms',
             'num_page_faults', 'peak_wset', 'wset', 'peak_paged_pool',
             'paged_pool', 'peak_nonpaged_pool', 'nonpaged_pool',
             'pagefile', 'peak_pagefile', 'private'])
# psutil.Process.memory_full_info()
pfullmem = namedtuple('pfullmem', pmem._fields + ('uss', ))
# psutil.Process.memory_maps(grouped=True)
pmmap_grouped = namedtuple('pmmap_grouped', ['path', 'rss'])
# psutil.Process.memory_maps(grouped=False)
pmmap_ext = namedtuple(
    'pmmap_ext', 'addr perms ' + ' '.join(pmmap_grouped._fields))
# psutil.Process.io_counters()
pio = namedtuple('pio', ['read_count', 'write_count',
                         'read_bytes', 'write_bytes',
                         'other_count', 'other_bytes'])


# =====================================================================
# --- utils
# =====================================================================


@lru_cache(maxsize=512)
def convert_dos_path(s):
    """Convert paths using native DOS format like:
        "\Device\HarddiskVolume1\Windows\systemew\file.txt"
    into:
        "C:\Windows\systemew\file.txt"
    """
    if PY3 and not isinstance(s, str):
        s = s.decode('utf8')
    rawdrive = '\\'.join(s.split('\\')[:3])
    driveletter = cext.win32_QueryDosDevice(rawdrive)
    return os.path.join(driveletter, s[len(rawdrive):])


def py2_strencode(s, encoding=sys.getfilesystemencoding()):
    """Encode a string in the given encoding. Falls back on returning
    the string as is if it can't be encoded.
    """
    if PY3 or isinstance(s, str):
        return s
    else:
        try:
            return s.encode(encoding)
        except UnicodeEncodeError:
            # Filesystem codec failed, return the plain unicode
            # string (this should never happen).
            return s


# =====================================================================
# --- memory
# =====================================================================


def virtual_memory():
    """System virtual memory as a namedtuple."""
    mem = cext.virtual_mem()
    totphys, availphys, totpagef, availpagef, totvirt, freevirt = mem
    #
    total = totphys
    avail = availphys
    free = availphys
    used = total - avail
    percent = usage_percent((total - avail), total, _round=1)
    return svmem(total, avail, percent, used, free)


def swap_memory():
    """Swap system memory as a (total, used, free, sin, sout) tuple."""
    mem = cext.virtual_mem()
    total = mem[2]
    free = mem[3]
    used = total - free
    percent = usage_percent(used, total, _round=1)
    return _common.sswap(total, used, free, percent, 0, 0)


# =====================================================================
# --- disk
# =====================================================================


disk_io_counters = cext.disk_io_counters


def disk_usage(path):
    """Return disk usage associated with path."""
    try:
        total, free = cext.disk_usage(path)
    except WindowsError:
        if not os.path.exists(path):
            msg = "No such file or directory: '%s'" % path
            raise OSError(errno.ENOENT, msg)
        raise
    used = total - free
    percent = usage_percent(used, total, _round=1)
    return _common.sdiskusage(total, used, free, percent)


def disk_partitions(all):
    """Return disk partitions."""
    rawlist = cext.disk_partitions(all)
    return [_common.sdiskpart(*x) for x in rawlist]


# =====================================================================
# --- CPU
# =====================================================================


def cpu_times():
    """Return system CPU times as a named tuple."""
    user, system, idle = cext.cpu_times()
    # Internally, GetSystemTimes() is used, and it doesn't return
    # interrupt and dpc times. cext.per_cpu_times() does, so we
    # rely on it to get those only.
    percpu_summed = scputimes(*[sum(n) for n in zip(*cext.per_cpu_times())])
    return scputimes(user, system, idle,
                     percpu_summed.interrupt, percpu_summed.dpc)


def per_cpu_times():
    """Return system per-CPU times as a list of named tuples."""
    ret = []
    for user, system, idle, interrupt, dpc in cext.per_cpu_times():
        item = scputimes(user, system, idle, interrupt, dpc)
        ret.append(item)
    return ret


def cpu_count_logical():
    """Return the number of logical CPUs in the system."""
    return cext.cpu_count_logical()


def cpu_count_physical():
    """Return the number of physical CPUs in the system."""
    return cext.cpu_count_phys()


def cpu_stats():
    """Return CPU statistics."""
    ctx_switches, interrupts, dpcs, syscalls = cext.cpu_stats()
    soft_interrupts = 0
    return _common.scpustats(ctx_switches, interrupts, soft_interrupts,
                             syscalls)


def cpu_freq():
    """Return CPU frequency.
    On Windows per-cpu frequency is not supported.
    """
    curr, max_ = cext.cpu_freq()
    min_ = 0.0
    return [_common.scpufreq(float(curr), min_, float(max_))]


# =====================================================================
# --- network
# =====================================================================


def net_connections(kind, _pid=-1):
    """Return socket connections.  If pid == -1 return system-wide
    connections (as opposed to connections opened by one process only).
    """
    if kind not in conn_tmap:
        raise ValueError("invalid %r kind argument; choose between %s"
                         % (kind, ', '.join([repr(x) for x in conn_tmap])))
    families, types = conn_tmap[kind]
    rawlist = cext.net_connections(_pid, families, types)
    ret = set()
    for item in rawlist:
        fd, fam, type, laddr, raddr, status, pid = item
        status = TCP_STATUSES[status]
        fam = sockfam_to_enum(fam)
        type = socktype_to_enum(type)
        if _pid == -1:
            nt = _common.sconn(fd, fam, type, laddr, raddr, status, pid)
        else:
            nt = _common.pconn(fd, fam, type, laddr, raddr, status)
        ret.add(nt)
    return list(ret)


def net_if_stats():
    """Get NIC stats (isup, duplex, speed, mtu)."""
    ret = cext.net_if_stats()
    for name, items in ret.items():
        name = py2_strencode(name)
        isup, duplex, speed, mtu = items
        if hasattr(_common, 'NicDuplex'):
            duplex = _common.NicDuplex(duplex)
        ret[name] = _common.snicstats(isup, duplex, speed, mtu)
    return ret


def net_io_counters():
    """Return network I/O statistics for every network interface
    installed on the system as a dict of raw tuples.
    """
    ret = cext.net_io_counters()
    return dict([(py2_strencode(k), v) for k, v in ret.items()])


def net_if_addrs():
    """Return the addresses associated to each NIC."""
    ret = []
    for items in cext.net_if_addrs():
        items = list(items)
        items[0] = py2_strencode(items[0])
        ret.append(items)
    return ret


# =====================================================================
# --- sensors
# =====================================================================


def sensors_battery():
    """Return battery information."""
    # For constants meaning see:
    # https://msdn.microsoft.com/en-us/library/windows/desktop/
    #     aa373232(v=vs.85).aspx
    acline_status, flags, percent, secsleft = cext.sensors_battery()
    power_plugged = acline_status == 1
    no_battery = bool(flags & 128)
    charging = bool(flags & 8)

    if no_battery:
        return None
    if power_plugged or charging:
        secsleft = _common.POWER_TIME_UNLIMITED
    elif secsleft == -1:
        secsleft = _common.POWER_TIME_UNKNOWN

    return _common.sbattery(percent, secsleft, power_plugged)


# =====================================================================
# --- other system functions
# =====================================================================


def boot_time():
    """The system boot time expressed in seconds since the epoch."""
    return cext.boot_time()


def users():
    """Return currently connected users as a list of namedtuples."""
    retlist = []
    rawlist = cext.users()
    for item in rawlist:
        user, hostname, tstamp = item
        user = py2_strencode(user)
        nt = _common.suser(user, None, hostname, tstamp)
        retlist.append(nt)
    return retlist


# =====================================================================
# --- Windows services
# =====================================================================


def win_service_iter():
    """Return a list of WindowsService instances."""
    for name, display_name in cext.winservice_enumerate():
        yield WindowsService(name, display_name)


def win_service_get(name):
    """Open a Windows service and return it as a WindowsService instance."""
    service = WindowsService(name, None)
    service._display_name = service._query_config()['display_name']
    return service


class WindowsService(object):
    """Represents an installed Windows service."""

    def __init__(self, name, display_name):
        self._name = name
        self._display_name = display_name

    def __str__(self):
        details = "(name=%r, display_name=%r)" % (
            self._name, self._display_name)
        return "%s%s" % (self.__class__.__name__, details)

    def __repr__(self):
        return "<%s at %s>" % (self.__str__(), id(self))

    def __eq__(self, other):
        # Test for equality with another WindosService object based
        # on name.
        if not isinstance(other, WindowsService):
            return NotImplemented
        return self._name == other._name

    def __ne__(self, other):
        return not self == other

    def _query_config(self):
        with self._wrap_exceptions():
            display_name, binpath, username, start_type = \
                cext.winservice_query_config(self._name)
        # XXX - update _self.display_name?
        return dict(
            display_name=display_name,
            binpath=binpath,
            username=username,
            start_type=start_type)

    def _query_status(self):
        with self._wrap_exceptions():
            status, pid = cext.winservice_query_status(self._name)
        if pid == 0:
            pid = None
        return dict(status=status, pid=pid)

    @contextlib.contextmanager
    def _wrap_exceptions(self):
        """Ctx manager which translates bare OSError and WindowsError
        exceptions into NoSuchProcess and AccessDenied.
        """
        try:
            yield
        except WindowsError as err:
            NO_SUCH_SERVICE_SET = (cext.ERROR_INVALID_NAME,
                                   cext.ERROR_SERVICE_DOES_NOT_EXIST)
            if err.errno in ACCESS_DENIED_SET:
                raise AccessDenied(
                    pid=None, name=self._name,
                    msg="service %r is not querable (not enough privileges)" %
                        self._name)
            elif err.errno in NO_SUCH_SERVICE_SET or \
                    err.winerror in NO_SUCH_SERVICE_SET:
                raise NoSuchProcess(
                    pid=None, name=self._name,
                    msg="service %r does not exist)" % self._name)
            else:
                raise

    # config query

    def name(self):
        """The service name. This string is how a service is referenced
        and can be passed to win_service_get() to get a new
        WindowsService instance.
        """
        return self._name

    def display_name(self):
        """The service display name. The value is cached when this class
        is instantiated.
        """
        return self._display_name

    def binpath(self):
        """The fully qualified path to the service binary/exe file as
        a string, including command line arguments.
        """
        return self._query_config()['binpath']

    def username(self):
        """The name of the user that owns this service."""
        return self._query_config()['username']

    def start_type(self):
        """A string which can either be "automatic", "manual" or
        "disabled".
        """
        return self._query_config()['start_type']

    # status query

    def pid(self):
        """The process PID, if any, else None. This can be passed
        to Process class to control the service's process.
        """
        return self._query_status()['pid']

    def status(self):
        """Service status as a string."""
        return self._query_status()['status']

    def description(self):
        """Service long description."""
        return cext.winservice_query_descr(self.name())

    # utils

    def as_dict(self):
        """Utility method retrieving all the information above as a
        dictionary.
        """
        d = self._query_config()
        d.update(self._query_status())
        d['name'] = self.name()
        d['display_name'] = self.display_name()
        d['description'] = self.description()
        return d

    # actions
    # XXX: the necessary C bindings for start() and stop() are
    # implemented but for now I prefer not to expose them.
    # I may change my mind in the future. Reasons:
    # - they require Administrator privileges
    # - can't implement a timeout for stop() (unless by using a thread,
    #   which sucks)
    # - would require adding ServiceAlreadyStarted and
    #   ServiceAlreadyStopped exceptions, adding two new APIs.
    # - we might also want to have modify(), which would basically mean
    #   rewriting win32serviceutil.ChangeServiceConfig, which involves a
    #   lot of stuff (and API constants which would pollute the API), see:
    #   http://pyxr.sourceforge.net/PyXR/c/python24/lib/site-packages/
    #       win32/lib/win32serviceutil.py.html#0175
    # - psutil is typically about "read only" monitoring stuff;
    #   win_service_* APIs should only be used to retrieve a service and
    #   check whether it's running

    # def start(self, timeout=None):
    #     with self._wrap_exceptions():
    #         cext.winservice_start(self.name())
    #         if timeout:
    #             giveup_at = time.time() + timeout
    #             while True:
    #                 if self.status() == "running":
    #                     return
    #                 else:
    #                     if time.time() > giveup_at:
    #                         raise TimeoutExpired(timeout)
    #                     else:
    #                         time.sleep(.1)

    # def stop(self):
    #     # Note: timeout is not implemented because it's just not
    #     # possible, see:
    #     # http://stackoverflow.com/questions/11973228/
    #     with self._wrap_exceptions():
    #         return cext.winservice_stop(self.name())


# =====================================================================
# --- processes
# =====================================================================


pids = cext.pids
pid_exists = cext.pid_exists
ppid_map = cext.ppid_map  # used internally by Process.children()


def wrap_exceptions(fun):
    """Decorator which translates bare OSError and WindowsError
    exceptions into NoSuchProcess and AccessDenied.
    """
    @functools.wraps(fun)
    def wrapper(self, *args, **kwargs):
        try:
            return fun(self, *args, **kwargs)
        except OSError as err:
            if err.errno in ACCESS_DENIED_SET:
                raise AccessDenied(self.pid, self._name)
            if err.errno == errno.ESRCH:
                raise NoSuchProcess(self.pid, self._name)
            raise
    return wrapper


class Process(object):
    """Wrapper class around underlying C implementation."""

    __slots__ = ["pid", "_name", "_ppid"]

    def __init__(self, pid):
        self.pid = pid
        self._name = None
        self._ppid = None

    # --- oneshot() stuff

    def oneshot_enter(self):
        self.oneshot_info.cache_activate()

    def oneshot_exit(self):
        self.oneshot_info.cache_deactivate()

    @memoize_when_activated
    def oneshot_info(self):
        """Return multiple information about this process as a
        raw tuple.
        """
        ret = cext.proc_info(self.pid)
        assert len(ret) == len(pinfo_map)
        return ret

    @wrap_exceptions
    def name(self):
        """Return process name, which on Windows is always the final
        part of the executable.
        """
        # This is how PIDs 0 and 4 are always represented in taskmgr
        # and process-hacker.
        if self.pid == 0:
            return "System Idle Process"
        elif self.pid == 4:
            return "System"
        else:
            try:
                # Note: this will fail with AD for most PIDs owned
                # by another user but it's faster.
                return py2_strencode(os.path.basename(self.exe()))
            except AccessDenied:
                return py2_strencode(cext.proc_name(self.pid))

    @wrap_exceptions
    def exe(self):
        # Note: os.path.exists(path) may return False even if the file
        # is there, see:
        # http://stackoverflow.com/questions/3112546/os-path-exists-lies

        # see https://github.com/giampaolo/psutil/issues/414
        # see https://github.com/giampaolo/psutil/issues/528
        if self.pid in (0, 4):
            raise AccessDenied(self.pid, self._name)
        return py2_strencode(convert_dos_path(cext.proc_exe(self.pid)))

    @wrap_exceptions
    def cmdline(self):
        ret = cext.proc_cmdline(self.pid)
        if PY3:
            return ret
        else:
            return [py2_strencode(s) for s in ret]

    @wrap_exceptions
    def environ(self):
        return parse_environ_block(cext.proc_environ(self.pid))

    def ppid(self):
        try:
            return ppid_map()[self.pid]
        except KeyError:
            raise NoSuchProcess(self.pid, self._name)

    def _get_raw_meminfo(self):
        try:
            return cext.proc_memory_info(self.pid)
        except OSError as err:
            if err.errno in ACCESS_DENIED_SET:
                # TODO: the C ext can probably be refactored in order
                # to get this from cext.proc_info()
                info = self.oneshot_info()
                return (
                    info[pinfo_map['num_page_faults']],
                    info[pinfo_map['peak_wset']],
                    info[pinfo_map['wset']],
                    info[pinfo_map['peak_paged_pool']],
                    info[pinfo_map['paged_pool']],
                    info[pinfo_map['peak_non_paged_pool']],
                    info[pinfo_map['non_paged_pool']],
                    info[pinfo_map['pagefile']],
                    info[pinfo_map['peak_pagefile']],
                    info[pinfo_map['mem_private']],
                )
            raise

    @wrap_exceptions
    def memory_info(self):
        # on Windows RSS == WorkingSetSize and VSM == PagefileUsage.
        # Underlying C function returns fields of PROCESS_MEMORY_COUNTERS
        # struct.
        t = self._get_raw_meminfo()
        rss = t[2]  # wset
        vms = t[7]  # pagefile
        return pmem(*(rss, vms, ) + t)

    @wrap_exceptions
    def memory_full_info(self):
        basic_mem = self.memory_info()
        uss = cext.proc_memory_uss(self.pid)
        return pfullmem(*basic_mem + (uss, ))

    def memory_maps(self):
        try:
            raw = cext.proc_memory_maps(self.pid)
        except OSError as err:
            # XXX - can't use wrap_exceptions decorator as we're
            # returning a generator; probably needs refactoring.
            if err.errno in ACCESS_DENIED_SET:
                raise AccessDenied(self.pid, self._name)
            if err.errno == errno.ESRCH:
                raise NoSuchProcess(self.pid, self._name)
            raise
        else:
            for addr, perm, path, rss in raw:
                path = convert_dos_path(path)
                addr = hex(addr)
                yield (addr, perm, path, rss)

    @wrap_exceptions
    def kill(self):
        return cext.proc_kill(self.pid)

    @wrap_exceptions
    def send_signal(self, sig):
        os.kill(self.pid, sig)

    @wrap_exceptions
    def wait(self, timeout=None):
        if timeout is None:
            cext_timeout = cext.INFINITE
        else:
            # WaitForSingleObject() expects time in milliseconds
            cext_timeout = int(timeout * 1000)
        ret = cext.proc_wait(self.pid, cext_timeout)
        if ret == WAIT_TIMEOUT:
            raise TimeoutExpired(timeout, self.pid, self._name)
        return ret

    @wrap_exceptions
    def username(self):
        if self.pid in (0, 4):
            return 'NT AUTHORITY\\SYSTEM'
        return cext.proc_username(self.pid)

    @wrap_exceptions
    def create_time(self):
        # special case for kernel process PIDs; return system boot time
        if self.pid in (0, 4):
            return boot_time()
        try:
            return cext.proc_create_time(self.pid)
        except OSError as err:
            if err.errno in ACCESS_DENIED_SET:
                return self.oneshot_info()[pinfo_map['create_time']]
            raise

    @wrap_exceptions
    def num_threads(self):
        return self.oneshot_info()[pinfo_map['num_threads']]

    @wrap_exceptions
    def threads(self):
        rawlist = cext.proc_threads(self.pid)
        retlist = []
        for thread_id, utime, stime in rawlist:
            ntuple = _common.pthread(thread_id, utime, stime)
            retlist.append(ntuple)
        return retlist

    @wrap_exceptions
    def cpu_times(self):
        try:
            user, system = cext.proc_cpu_times(self.pid)
        except OSError as err:
            if err.errno in ACCESS_DENIED_SET:
                info = self.oneshot_info()
                user = info[pinfo_map['user_time']]
                system = info[pinfo_map['kernel_time']]
            else:
                raise
        # Children user/system times are not retrievable (set to 0).
        return _common.pcputimes(user, system, 0, 0)

    @wrap_exceptions
    def suspend(self):
        return cext.proc_suspend(self.pid)

    @wrap_exceptions
    def resume(self):
        return cext.proc_resume(self.pid)

    @wrap_exceptions
    def cwd(self):
        if self.pid in (0, 4):
            raise AccessDenied(self.pid, self._name)
        # return a normalized pathname since the native C function appends
        # "\\" at the and of the path
        path = cext.proc_cwd(self.pid)
        return py2_strencode(os.path.normpath(path))

    @wrap_exceptions
    def open_files(self):
        if self.pid in (0, 4):
            return []
        ret = set()
        # Filenames come in in native format like:
        # "\Device\HarddiskVolume1\Windows\systemew\file.txt"
        # Convert the first part in the corresponding drive letter
        # (e.g. "C:\") by using Windows's QueryDosDevice()
        raw_file_names = cext.proc_open_files(self.pid)
        for _file in raw_file_names:
            _file = convert_dos_path(_file)
            if isfile_strict(_file):
                if not PY3:
                    _file = py2_strencode(_file)
                ntuple = _common.popenfile(_file, -1)
                ret.add(ntuple)
        return list(ret)

    @wrap_exceptions
    def connections(self, kind='inet'):
        return net_connections(kind, _pid=self.pid)

    @wrap_exceptions
    def nice_get(self):
        value = cext.proc_priority_get(self.pid)
        if enum is not None:
            value = Priority(value)
        return value

    @wrap_exceptions
    def nice_set(self, value):
        return cext.proc_priority_set(self.pid, value)

    # available on Windows >= Vista
    if hasattr(cext, "proc_io_priority_get"):
        @wrap_exceptions
        def ionice_get(self):
            return cext.proc_io_priority_get(self.pid)

        @wrap_exceptions
        def ionice_set(self, value, _):
            if _:
                raise TypeError("set_proc_ionice() on Windows takes only "
                                "1 argument (2 given)")
            if value not in (2, 1, 0):
                raise ValueError("value must be 2 (normal), 1 (low) or 0 "
                                 "(very low); got %r" % value)
            return cext.proc_io_priority_set(self.pid, value)

    @wrap_exceptions
    def io_counters(self):
        try:
            ret = cext.proc_io_counters(self.pid)
        except OSError as err:
            if err.errno in ACCESS_DENIED_SET:
                info = self.oneshot_info()
                ret = (
                    info[pinfo_map['io_rcount']],
                    info[pinfo_map['io_wcount']],
                    info[pinfo_map['io_rbytes']],
                    info[pinfo_map['io_wbytes']],
                    info[pinfo_map['io_count_others']],
                    info[pinfo_map['io_bytes_others']],
                )
            else:
                raise
        return pio(*ret)

    @wrap_exceptions
    def status(self):
        suspended = cext.proc_is_suspended(self.pid)
        if suspended:
            return _common.STATUS_STOPPED
        else:
            return _common.STATUS_RUNNING

    @wrap_exceptions
    def cpu_affinity_get(self):
        def from_bitmask(x):
            return [i for i in xrange(64) if (1 << i) & x]
        bitmask = cext.proc_cpu_affinity_get(self.pid)
        return from_bitmask(bitmask)

    @wrap_exceptions
    def cpu_affinity_set(self, value):
        def to_bitmask(l):
            if not l:
                raise ValueError("invalid argument %r" % l)
            out = 0
            for b in l:
                out |= 2 ** b
            return out

        # SetProcessAffinityMask() states that ERROR_INVALID_PARAMETER
        # is returned for an invalid CPU but this seems not to be true,
        # therefore we check CPUs validy beforehand.
        allcpus = list(range(len(per_cpu_times())))
        for cpu in value:
            if cpu not in allcpus:
                if not isinstance(cpu, (int, long)):
                    raise TypeError(
                        "invalid CPU %r; an integer is required" % cpu)
                else:
                    raise ValueError("invalid CPU %r" % cpu)

        bitmask = to_bitmask(value)
        cext.proc_cpu_affinity_set(self.pid, bitmask)

    @wrap_exceptions
    def num_handles(self):
        try:
            return cext.proc_num_handles(self.pid)
        except OSError as err:
            if err.errno in ACCESS_DENIED_SET:
                return self.oneshot_info()[pinfo_map['num_handles']]
            raise

    @wrap_exceptions
    def num_ctx_switches(self):
        ctx_switches = self.oneshot_info()[pinfo_map['ctx_switches']]
        # only voluntary ctx switches are supported
        return _common.pctxsw(ctx_switches, 0)
