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
    # Bare schemes (no "+transport"): pip/pipenv may encounter a VCS
    # link with no explicit transport, e.g. a bare "git" URL.
    "git",
    "hg",
    "svn",
    "bzr",
    "git+http",
    "git+https",
    "git+ssh",
    "git+git",
    "git+file",
    "hg+http",
    "hg+https",
    "hg+ssh",
    "hg+static-http",
    "hg+file",
    "svn+http",
    "svn+https",
    "svn+svn",
    "svn+file",
    "bzr+http",
    "bzr+https",
    "bzr+ssh",
    "bzr+sftp",
    "bzr+ftp",
    "bzr+lp",
    "bzr+file",
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
