import os
import re

from ._core import Process


STAT_PPID = 3
STAT_TTY = 6

STAT_PATTERN = re.compile(r'\(.+\)|\S+')


def detect_proc():
    """Detect /proc filesystem style.

    This checks the /proc/{pid} directory for possible formats. Returns one of
    the followings as str:

    * `stat`: Linux-style, i.e. ``/proc/{pid}/stat``.
    * `status`: BSD-style, i.e. ``/proc/{pid}/status``.
    """
    pid = os.getpid()
    for name in ('stat', 'status'):
        if os.path.exists(os.path.join('/proc', str(pid), name)):
            return name
    raise ProcFormatError('unsupported proc format')


def _get_stat(pid, name):
    with open(os.path.join('/proc', str(pid), name)) as f:
        parts = STAT_PATTERN.findall(f.read())
        return parts[STAT_TTY], parts[STAT_PPID]


def _get_cmdline(pid):
    with open(os.path.join('/proc', str(pid), 'cmdline')) as f:
        return tuple(f.read().split('\0')[:-1])


class ProcFormatError(EnvironmentError):
    pass


def get_process_mapping():
    """Try to look up the process tree via the /proc interface.
    """
    stat_name = detect_proc()
    self_tty = _get_stat(os.getpid(), stat_name)[0]
    processes = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            tty, ppid = _get_stat(pid, stat_name)
            if tty != self_tty:
                continue
            args = _get_cmdline(pid)
            processes[pid] = Process(args=args, pid=pid, ppid=ppid)
        except IOError:
            # Process has disappeared - just ignore it.
            continue
    return processes
