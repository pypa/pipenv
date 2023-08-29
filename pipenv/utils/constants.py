# List of version control systems we support.
VCS_LIST = ("git", "svn", "hg", "bzr")
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")
FALSE_VALUES = ("0", "false", "no", "off")
TRUE_VALUES = ("1", "true", "yes", "on")
REMOTE_FILE_SCHEMES = [
    "http",
    "https",
    "ftp",
]
VCS_SCHEMES = [
    "git+http",
    "git+https",
    "git+ssh",
    "git+git",
    "hg+http",
    "hg+https",
    "hg+ssh",
    "svn+http",
    "svn+https",
    "svn+svn",
    "bzr+http",
    "bzr+https",
    "bzr+ssh",
    "bzr+sftp",
    "bzr+ftp",
    "bzr+lp",
]
REMOTE_SCHEMES = REMOTE_FILE_SCHEMES + VCS_SCHEMES

RELEVANT_PROJECT_FILES = (
    "METADATA",
    "PKG-INFO",
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
)

INSTALLABLE_EXTENSIONS = (".whl", ".zip", ".tar", ".tar.gz", ".tgz")


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


MYPY_RUNNING = is_type_checking()
