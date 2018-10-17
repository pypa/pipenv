import os
import re

from ._default import Process


STAT_PPID = 3
STAT_TTY = 6


def get_process_mapping():
    """Try to look up the process tree via the /proc interface.
    """
    with open('/proc/{0}/stat'.format(os.getpid())) as f:
        self_tty = f.read().split()[STAT_TTY]
    processes = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            stat = '/proc/{0}/stat'.format(pid)
            cmdline = '/proc/{0}/cmdline'.format(pid)
            with open(stat) as fstat, open(cmdline) as fcmdline:
                stat = re.findall(r'\(.+\)|\S+', fstat.read())
                cmd = fcmdline.read().split('\x00')[:-1]
            ppid = stat[STAT_PPID]
            tty = stat[STAT_TTY]
            if tty == self_tty:
                processes[pid] = Process(
                    args=tuple(cmd), pid=pid, ppid=ppid,
                )
        except IOError:
            # Process has disappeared - just ignore it.
            continue
    return processes
