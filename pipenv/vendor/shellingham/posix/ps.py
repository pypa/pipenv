import errno
import shlex
import subprocess
import sys

from ._core import Process


class PsNotAvailable(EnvironmentError):
    pass


def get_process_mapping():
    """Try to look up the process tree via the output of `ps`.
    """
    try:
        output = subprocess.check_output([
            'ps', '-ww', '-o', 'pid=', '-o', 'ppid=', '-o', 'args=',
        ])
    except OSError as e:    # Python 2-compatible FileNotFoundError.
        if e.errno != errno.ENOENT:
            raise
        raise PsNotAvailable('ps not found')
    except subprocess.CalledProcessError as e:
        # `ps` can return 1 if the process list is completely empty.
        # (sarugaku/shellingham#15)
        if not e.output.strip():
            return {}
        raise
    if not isinstance(output, str):
        encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()
        output = output.decode(encoding)
    processes = {}
    for line in output.split('\n'):
        try:
            pid, ppid, args = line.strip().split(None, 2)
            processes[pid] = Process(
                args=tuple(shlex.split(args)), pid=pid, ppid=ppid,
            )
        except ValueError:
            continue
    return processes
