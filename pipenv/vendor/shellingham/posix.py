import collections
import os
import shlex
import subprocess
import sys

from ._consts import SHELL_NAMES


Process = collections.namedtuple('Process', 'args pid ppid')


def _get_process_mapping():
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


def get_shell(pid=None, max_depth=6):
    """Get the shell that the supplied pid or os.getpid() is running in.
    """
    pid = str(pid or os.getpid())
    mapping = _get_process_mapping()
    login_shell = os.environ.get('SHELL', '')
    for _ in range(max_depth):
        try:
            proc = mapping[pid]
        except KeyError:
            break
        name = os.path.basename(proc.args[0]).lower()
        if name in SHELL_NAMES:
            return (name, proc.args[0])
        elif proc.args[0].startswith('-'):
            # This is the login shell. Use the SHELL environ if possible
            # because it provides better information.
            if login_shell:
                name = login_shell.lower()
            else:
                name = proc.args[0][1:].lower()
            return (os.path.basename(name), name)
        pid = proc.ppid     # Go up one level.
    return None
