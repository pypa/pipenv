# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import atexit
import errno
import functools
import os
import posixpath
import shutil
import stat
import sys
import time
import unicodedata
import warnings

import pipenv.vendor.six as six
from pipenv.vendor.six.moves import urllib_parse
from pipenv.vendor.six.moves.urllib import request as urllib_request

from .backports.tempfile import _TemporaryFileWrapper
from .compat import (
    IS_TYPE_CHECKING,
    FileNotFoundError,
    Path,
    PermissionError,
    ResourceWarning,
    TemporaryDirectory,
    _fs_encoding,
    _NamedTemporaryFile,
    finalize,
    fs_decode,
    fs_encode,
)

# fmt: off
if six.PY3:
    from urllib.parse import quote_from_bytes as quote
else:
    from urllib import quote
# fmt: on


if IS_TYPE_CHECKING:
    from types import TracebackType
    from typing import (
        Any,
        AnyStr,
        ByteString,
        Callable,
        Generator,
        Iterator,
        List,
        Optional,
        Text,
        Tuple,
        Type,
        Union,
    )

    if six.PY3:
        TPath = os.PathLike
    else:
        TPath = Union[str, bytes]
    TFunc = Callable[..., Any]

__all__ = [
    "check_for_unc_path",
    "get_converted_relative_path",
    "handle_remove_readonly",
    "normalize_path",
    "is_in_path",
    "is_file_url",
    "is_readonly_path",
    "is_valid_url",
    "mkdir_p",
    "ensure_mkdir_p",
    "create_tracked_tempdir",
    "create_tracked_tempfile",
    "path_to_url",
    "rmtree",
    "safe_expandvars",
    "set_write_bit",
    "url_to_path",
    "walk_up",
]


if os.name == "nt":
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message="The Windows bytes API has been deprecated.*",
    )


def unicode_path(path):
    # type: (TPath) -> Text
    # Paths are supposed to be represented as unicode here
    if six.PY2 and isinstance(path, six.binary_type):
        return path.decode(_fs_encoding)
    return path


def native_path(path):
    # type: (TPath) -> str
    if six.PY2 and isinstance(path, six.text_type):
        return path.encode(_fs_encoding)
    return str(path)


# once again thank you django...
# https://github.com/django/django/blob/fc6b90b/django/utils/_os.py
if six.PY3 or os.name == "nt":
    abspathu = os.path.abspath
else:

    def abspathu(path):
        # type: (TPath) -> Text
        """Version of os.path.abspath that uses the unicode representation of
        the current working directory, thus avoiding a UnicodeDecodeError in
        join when the cwd has non-ASCII characters."""
        if not os.path.isabs(path):
            path = os.path.join(os.getcwdu(), path)
        return os.path.normpath(path)


def normalize_path(path):
    # type: (TPath) -> Text
    """Return a case-normalized absolute variable-expanded path.

    :param str path: The non-normalized path
    :return: A normalized, expanded, case-normalized path
    :rtype: str
    """

    path = os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))
    if os.name == "nt" and os.path.exists(path):
        from ._winconsole import get_long_path

        path = get_long_path(path)

    return os.path.normpath(os.path.normcase(path))


def is_in_path(path, parent):
    # type: (TPath, TPath) -> bool
    """Determine if the provided full path is in the given parent root.

    :param str path: The full path to check the location of.
    :param str parent: The parent path to check for membership in
    :return: Whether the full path is a member of the provided parent.
    :rtype: bool
    """

    return normalize_path(path).startswith(normalize_path(parent))


def normalize_drive(path):
    # type: (TPath) -> Text
    """Normalize drive in path so they stay consistent.

    This currently only affects local drives on Windows, which can be
    identified with either upper or lower cased drive names. The case is
    always converted to uppercase because it seems to be preferred.
    """
    from .misc import to_text

    if os.name != "nt" or not (
        isinstance(path, six.string_types) or getattr(path, "__fspath__", None)
    ):
        return path  # type: ignore

    drive, tail = os.path.splitdrive(path)
    # Only match (lower cased) local drives (e.g. 'c:'), not UNC mounts.
    if drive.islower() and len(drive) == 2 and drive[1] == ":":
        return "{}{}".format(drive.upper(), tail)

    return to_text(path, encoding="utf-8")


def path_to_url(path):
    # type: (TPath) -> Text
    """Convert the supplied local path to a file uri.

    :param str path: A string pointing to or representing a local path
    :return: A `file://` uri for the same location
    :rtype: str

    >>> path_to_url("/home/user/code/myrepo/myfile.zip")
    'file:///home/user/code/myrepo/myfile.zip'
    """
    from .misc import to_bytes

    if not path:
        return path  # type: ignore
    normalized_path = Path(normalize_drive(os.path.abspath(path))).as_posix()
    if os.name == "nt" and normalized_path[1] == ":":
        drive, _, path = normalized_path.partition(":")
        # XXX: This enables us to handle half-surrogates that were never
        # XXX: actually part of a surrogate pair, but were just incidentally
        # XXX: passed in as a piece of a filename
        quoted_path = quote(fs_encode(path))
        return fs_decode("file:///{}:{}".format(drive, quoted_path))
    # XXX: This is also here to help deal with incidental dangling surrogates
    # XXX: on linux, by making sure they are preserved during encoding so that
    # XXX: we can urlencode the backslash correctly
    bytes_path = to_bytes(normalized_path, errors="backslashreplace")
    return fs_decode("file://{}".format(quote(bytes_path)))


def url_to_path(url):
    # type: (str) -> str
    """Convert a valid file url to a local filesystem path.

    Follows logic taken from pip's equivalent function
    """

    assert is_file_url(url), "Only file: urls can be converted to local paths"
    _, netloc, path, _, _ = urllib_parse.urlsplit(url)
    # Netlocs are UNC paths
    if netloc:
        netloc = "\\\\" + netloc

    path = urllib_request.url2pathname(netloc + path)
    return urllib_parse.unquote(path)


def is_valid_url(url):
    # type: (Union[str, bytes]) -> bool
    """Checks if a given string is an url."""
    from .misc import to_text

    if not url:
        return url  # type: ignore
    pieces = urllib_parse.urlparse(to_text(url))
    return all([pieces.scheme, pieces.netloc])


def is_file_url(url):
    # type: (Any) -> bool
    """Returns true if the given url is a file url."""
    from .misc import to_text

    if not url:
        return False
    if not isinstance(url, six.string_types):
        try:
            url = url.url
        except AttributeError:
            raise ValueError("Cannot parse url from unknown type: {!r}".format(url))
    url = to_text(url, encoding="utf-8")
    return urllib_parse.urlparse(url.lower()).scheme == "file"


def is_readonly_path(fn):
    # type: (TPath) -> bool
    """Check if a provided path exists and is readonly.

    Permissions check is `bool(path.stat & stat.S_IREAD)` or `not
    os.access(path, os.W_OK)`
    """

    fn = fs_decode(fs_encode(fn))
    if os.path.exists(fn):
        file_stat = os.stat(fn).st_mode
        return not bool(file_stat & stat.S_IWRITE) or not os.access(fn, os.W_OK)
    return False


def mkdir_p(newdir, mode=0o777):
    # type: (TPath, int) -> None
    """Recursively creates the target directory and all of its parents if they
    do not already exist.  Fails silently if they do.

    :param str newdir: The directory path to ensure
    :raises: OSError if a file is encountered along the way
    """
    newdir = fs_decode(fs_encode(newdir))
    if os.path.exists(newdir):
        if not os.path.isdir(newdir):
            raise OSError(
                "a file with the same name as the desired dir, '{}', already exists.".format(
                    fs_decode(newdir)
                )
            )
        return None
    os.makedirs(newdir, mode)


def ensure_mkdir_p(mode=0o777):
    # type: (int) -> Callable[Callable[..., Any], Callable[..., Any]]
    """Decorator to ensure `mkdir_p` is called to the function's return
    value."""

    def decorator(f):
        # type: (Callable[..., Any]) -> Callable[..., Any]
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            # type: () -> str
            path = f(*args, **kwargs)
            mkdir_p(path, mode=mode)
            return path

        return decorated

    return decorator


TRACKED_TEMPORARY_DIRECTORIES = []


def create_tracked_tempdir(*args, **kwargs):
    # type: (Any, Any) -> str
    """Create a tracked temporary directory.

    This uses `TemporaryDirectory`, but does not remove the directory when
    the return value goes out of scope, instead registers a handler to cleanup
    on program exit.

    The return value is the path to the created directory.
    """

    tempdir = TemporaryDirectory(*args, **kwargs)
    TRACKED_TEMPORARY_DIRECTORIES.append(tempdir)
    atexit.register(tempdir.cleanup)
    warnings.simplefilter("ignore", ResourceWarning)
    return tempdir.name


def create_tracked_tempfile(*args, **kwargs):
    # type: (Any, Any) -> str
    """Create a tracked temporary file.

    This uses the `NamedTemporaryFile` construct, but does not remove the file
    until the interpreter exits.

    The return value is the file object.
    """

    kwargs["wrapper_class_override"] = _TrackedTempfileWrapper
    return _NamedTemporaryFile(*args, **kwargs)


def _find_icacls_exe():
    # type: () -> Optional[Text]
    if os.name == "nt":
        paths = [
            os.path.expandvars(r"%windir%\{0}").format(subdir)
            for subdir in ("system32", "SysWOW64")
        ]
        for path in paths:
            icacls_path = next(
                iter(fn for fn in os.listdir(path) if fn.lower() == "icacls.exe"), None
            )
            if icacls_path is not None:
                icacls_path = os.path.join(path, icacls_path)
                return icacls_path
    return None


def set_write_bit(fn):
    # type: (str) -> None
    """Set read-write permissions for the current user on the target path. Fail
    silently if the path doesn't exist.

    :param str fn: The target filename or path
    :return: None
    """

    fn = fs_decode(fs_encode(fn))
    if not os.path.exists(fn):
        return
    file_stat = os.stat(fn).st_mode
    os.chmod(fn, file_stat | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    if os.name == "nt":
        from ._winconsole import get_current_user

        user_sid = get_current_user()
        icacls_exe = _find_icacls_exe() or "icacls"
        from .misc import run

        if user_sid:
            c = run(
                [
                    icacls_exe,
                    "''{}''".format(fn),
                    "/grant",
                    "{}:WD".format(user_sid),
                    "/T",
                    "/C",
                    "/Q",
                ],
                nospin=True,
                return_object=True,
            )
            if not c.err and c.returncode == 0:
                return

    if not os.path.isdir(fn):
        for path in [fn, os.path.dirname(fn)]:
            try:
                os.chflags(path, 0)
            except AttributeError:
                pass
        return None
    for root, dirs, files in os.walk(fn, topdown=False):
        for dir_ in [os.path.join(root, d) for d in dirs]:
            set_write_bit(dir_)
        for file_ in [os.path.join(root, f) for f in files]:
            set_write_bit(file_)


def rmtree(directory, ignore_errors=False, onerror=None):
    # type: (str, bool, Optional[Callable]) -> None
    """Stand-in for :func:`~shutil.rmtree` with additional error-handling.

    This version of `rmtree` handles read-only paths, especially in the case of index
    files written by certain source control systems.

    :param str directory: The target directory to remove
    :param bool ignore_errors: Whether to ignore errors, defaults to False
    :param func onerror: An error handling function, defaults to :func:`handle_remove_readonly`

    .. note::

       Setting `ignore_errors=True` may cause this to silently fail to delete the path
    """

    directory = fs_decode(fs_encode(directory))
    if onerror is None:
        onerror = handle_remove_readonly
    try:
        shutil.rmtree(directory, ignore_errors=ignore_errors, onerror=onerror)
    except (IOError, OSError, FileNotFoundError, PermissionError) as exc:  # noqa:B014
        # Ignore removal failures where the file doesn't exist
        if exc.errno != errno.ENOENT:
            raise


def _wait_for_files(path):  # pragma: no cover
    # type: (Union[str, TPath]) -> Optional[List[TPath]]
    """Retry with backoff up to 1 second to delete files from a directory.

    :param str path: The path to crawl to delete files from
    :return: A list of remaining paths or None
    :rtype: Optional[List[str]]
    """
    timeout = 0.001
    remaining = []
    while timeout < 1.0:
        remaining = []
        if os.path.isdir(path):
            L = os.listdir(path)
            for target in L:
                _remaining = _wait_for_files(target)
                if _remaining:
                    remaining.extend(_remaining)
            continue
        try:
            os.unlink(path)
        except FileNotFoundError as e:
            if e.errno == errno.ENOENT:
                return
        except (OSError, IOError, PermissionError):  # noqa:B014
            time.sleep(timeout)
            timeout *= 2
            remaining.append(path)
        else:
            return
    return remaining


def handle_remove_readonly(func, path, exc):
    # type: (Callable[..., str], TPath, Tuple[Type[OSError], OSError, TracebackType]) -> None
    """Error handler for shutil.rmtree.

    Windows source repo folders are read-only by default, so this error handler
    attempts to set them as writeable and then proceed with deletion.

    :param function func: The caller function
    :param str path: The target path for removal
    :param Exception exc: The raised exception

    This function will call check :func:`is_readonly_path` before attempting to call
    :func:`set_write_bit` on the target path and try again.
    """
    # Check for read-only attribute
    from .compat import ResourceWarning, FileNotFoundError, PermissionError

    PERM_ERRORS = (errno.EACCES, errno.EPERM, errno.ENOENT)
    default_warning_message = "Unable to remove file due to permissions restriction: {!r}"
    # split the initial exception out into its type, exception, and traceback
    exc_type, exc_exception, exc_tb = exc
    if is_readonly_path(path):
        # Apply write permission and call original function
        set_write_bit(path)
        try:
            func(path)
        except (  # noqa:B014
            OSError,
            IOError,
            FileNotFoundError,
            PermissionError,
        ) as e:  # pragma: no cover
            if e.errno in PERM_ERRORS:
                if e.errno == errno.ENOENT:
                    return
                remaining = None
                if os.path.isdir(path):
                    remaining = _wait_for_files(path)
                if remaining:
                    warnings.warn(default_warning_message.format(path), ResourceWarning)
                else:
                    func(path, ignore_errors=True)
                return

    if exc_exception.errno in PERM_ERRORS:
        set_write_bit(path)
        remaining = _wait_for_files(path)
        try:
            func(path)
        except (OSError, IOError, FileNotFoundError, PermissionError) as e:  # noqa:B014
            if e.errno in PERM_ERRORS:
                if e.errno != errno.ENOENT:  # File still exists
                    warnings.warn(default_warning_message.format(path), ResourceWarning)
            return
    else:
        raise exc_exception


def walk_up(bottom):
    # type: (Union[TPath, str]) -> Generator[Tuple[str, List[str], List[str]], None, None]
    """Mimic os.walk, but walk 'up' instead of down the directory tree.

    From: https://gist.github.com/zdavkeos/1098474
    """
    bottom = os.path.realpath(str(bottom))
    # Get files in current dir.
    try:
        names = os.listdir(bottom)
    except Exception:
        return

    dirs, nondirs = [], []
    for name in names:
        if os.path.isdir(os.path.join(bottom, name)):
            dirs.append(name)
        else:
            nondirs.append(name)
    yield bottom, dirs, nondirs

    new_path = os.path.realpath(os.path.join(bottom, ".."))
    # See if we are at the top.
    if new_path == bottom:
        return

    for x in walk_up(new_path):
        yield x


def check_for_unc_path(path):
    # type: (Path) -> bool
    """Checks to see if a pathlib `Path` object is a unc path or not."""
    if (
        os.name == "nt"
        and len(path.drive) > 2
        and not path.drive[0].isalpha()
        and path.drive[1] != ":"
    ):
        return True
    else:
        return False


def get_converted_relative_path(path, relative_to=None):
    # type: (TPath, Optional[TPath]) -> str
    """Convert `path` to be relative.

    Given a vague relative path, return the path relative to the given
    location.

    :param str path: The location of a target path
    :param str relative_to: The starting path to build against, optional
    :returns: A relative posix-style path with a leading `./`

    This performs additional conversion to ensure the result is of POSIX form,
    and starts with `./`, or is precisely `.`.

    >>> os.chdir('/home/user/code/myrepo/myfolder')
    >>> vistir.path.get_converted_relative_path('/home/user/code/file.zip')
    './../../file.zip'
    >>> vistir.path.get_converted_relative_path('/home/user/code/myrepo/myfolder/mysubfolder')
    './mysubfolder'
    >>> vistir.path.get_converted_relative_path('/home/user/code/myrepo/myfolder')
    '.'
    """
    from .misc import to_text, to_bytes  # noqa

    if not relative_to:
        relative_to = os.getcwdu() if six.PY2 else os.getcwd()
    if six.PY2:
        path = to_bytes(path, encoding="utf-8")
    else:
        path = to_text(path, encoding="utf-8")
    relative_to = to_text(relative_to, encoding="utf-8")
    start_path = Path(relative_to)
    try:
        start = start_path.resolve()
    except OSError:
        start = start_path.absolute()

    # check if there is a drive letter or mount point
    # if it is a mountpoint use the original absolute path
    # instead of the unc path
    if check_for_unc_path(start):
        start = start_path.absolute()

    path = start.joinpath(path).relative_to(start)

    # check and see if the path that was passed into the function is a UNC path
    # and raise value error if it is not.
    if check_for_unc_path(path):
        raise ValueError("The path argument does not currently accept UNC paths")

    relpath_s = to_text(posixpath.normpath(path.as_posix()))
    if not (relpath_s == "." or relpath_s.startswith("./")):
        relpath_s = posixpath.join(".", relpath_s)
    return relpath_s


def safe_expandvars(value):
    # type: (TPath) -> str
    """Call os.path.expandvars if value is a string, otherwise do nothing."""
    if isinstance(value, six.string_types):
        return os.path.expandvars(value)
    return value  # type: ignore


class _TrackedTempfileWrapper(_TemporaryFileWrapper, object):
    def __init__(self, *args, **kwargs):
        super(_TrackedTempfileWrapper, self).__init__(*args, **kwargs)
        self._finalizer = finalize(self, self.cleanup)

    @classmethod
    def _cleanup(cls, fileobj):
        try:
            fileobj.close()
        finally:
            os.unlink(fileobj.name)

    def cleanup(self):
        if self._finalizer.detach():
            try:
                self.close()
            finally:
                os.unlink(self.name)
        else:
            try:
                self.close()
            except OSError:
                pass
