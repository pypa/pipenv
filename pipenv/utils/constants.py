# List of version control systems we support.
VCS_LIST = ("git", "svn", "hg", "bzr")
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")
FALSE_VALUES = ("0", "false", "no", "off")
TRUE_VALUES = ("1", "true", "yes", "on")


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


MYPY_RUNNING = is_type_checking()
