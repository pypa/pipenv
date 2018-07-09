import collections
import shlex
import subprocess
import sys


Process = collections.namedtuple('Process', 'args pid ppid')


def get_process_mapping():
    """Try to look up the process tree via the output of `ps`.
    """
    output = subprocess.check_output([
        'ps', '-ww', '-o', 'pid=', '-o', 'ppid=', '-o', 'args=',
    ])
    if not isinstance(output, str):
        output = output.decode(sys.stdout.encoding)
    processes = {}
    for line in output.split('\n'):
        try:
            pid, ppid, args = line.strip().split(None, 2)
        except ValueError:
            continue
        processes[pid] = Process(
            args=tuple(shlex.split(args)), pid=pid, ppid=ppid,
        )
    return processes
