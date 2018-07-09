import os

from .._core import SHELL_NAMES, ShellDetectionFailure
from . import proc, ps


def _get_process_mapping():
    """Select a way to obtain process information from the system.

    * `/proc` is used if supported.
    * The system `ps` utility is used as a fallback option.
    """
    for impl in (proc, ps):
        try:
            mapping = impl.get_process_mapping()
        except EnvironmentError:
            continue
        return mapping
    raise ShellDetectionFailure('compatible proc fs or ps utility is required')


def _get_login_shell(proc_cmd):
    """Form shell information from the SHELL environment variable if possible.
    """
    login_shell = os.environ.get('SHELL', '')
    if login_shell:
        proc_cmd = login_shell
    else:
        proc_cmd = proc_cmd[1:]
    return (os.path.basename(proc_cmd).lower(), proc_cmd)


def get_shell(pid=None, max_depth=6):
    """Get the shell that the supplied pid or os.getpid() is running in.
    """
    pid = str(pid or os.getpid())
    mapping = _get_process_mapping()

    for _ in range(max_depth):
        try:
            proc = mapping[pid]
        except KeyError:
            break
        proc_cmd = proc.args[0]
        if proc_cmd.startswith('-'):    # Login shell! Let's use this.
            return _get_login_shell(proc_cmd)
        name = os.path.basename(proc_cmd).lower()
        if name in SHELL_NAMES:     # The inner-most (non-login) shell.
            return (name, proc_cmd)
        pid = proc.ppid     # Go up one level.
    return None
