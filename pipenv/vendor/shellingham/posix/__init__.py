import os

from .._consts import SHELL_NAMES


def _get_process_mapping():
    """Select a way to obtain process information from the system.

    * `/proc` is used if supported.
    * The system `ps` utility is used as a fallback option.
    """
    if os.path.isdir('/proc') and os.listdir('/proc'):
        # Need to check if /proc contains stuff. It might not be mounted.
        from . import _proc as impl
    else:
        from . import _ps as impl
    return impl.get_process_mapping()


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
