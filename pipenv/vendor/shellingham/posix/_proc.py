import os
import re

from ._core import Process


STAT_PPID = 3
STAT_TTY = 6

STAT_PATTERN = re.compile(r'\(.+\)|\S+')


def _get_stat(pid):
    with open(os.path.join('/proc', str(pid), 'stat')) as f:
        parts = STAT_PATTERN.findall(f.read())
        return parts[STAT_TTY], parts[STAT_PPID]


def _get_cmdline(pid):
    with open(os.path.join('/proc', str(pid), 'cmdline')) as f:
        return tuple(f.read().split('\0')[:-1])


def get_process_mapping():
    """Try to look up the process tree via the /proc interface.
    """
    self_tty = _get_stat(os.getpid())[0]
    processes = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            tty, ppid = _get_stat(pid)
            if tty != self_tty:
                continue
            args = _get_cmdline(pid)
            processes[pid] = Process(args=args, pid=pid, ppid=ppid)
        except IOError:
            # Process has disappeared - just ignore it.
            continue
    return processes
