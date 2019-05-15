from typing import Any, Optional
from .main import load_dotenv, get_key, set_key, unset_key, find_dotenv, dotenv_values


def load_ipython_extension(ipython):
    # type: (Any) -> None
    from .ipython import load_ipython_extension
    load_ipython_extension(ipython)


def get_cli_string(path=None, action=None, key=None, value=None, quote=None):
    # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]) -> str
    """Returns a string suitable for running as a shell script.

    Useful for converting a arguments passed to a fabric task
    to be passed to a `local` or `run` command.
    """
    command = ['dotenv']
    if quote:
        command.append('-q %s' % quote)
    if path:
        command.append('-f %s' % path)
    if action:
        command.append(action)
        if key:
            command.append(key)
            if value:
                if ' ' in value:
                    command.append('"%s"' % value)
                else:
                    command.append(value)

    return ' '.join(command).strip()


__all__ = ['get_cli_string',
           'load_dotenv',
           'dotenv_values',
           'get_key',
           'set_key',
           'unset_key',
           'find_dotenv',
           'load_ipython_extension']
