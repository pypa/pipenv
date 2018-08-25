# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import atexit
import errno
import functools
import os
import posixpath
import shutil
import stat
import warnings

import six

from six.moves import urllib_parse
from six.moves.urllib import request as urllib_request

from .compat import Path, _fs_encoding, TemporaryDirectory
from .misc import locale_encoding, to_bytes, to_text


__all__ = [
    "check_for_unc_path",
    "get_converted_relative_path",
    "handle_remove_readonly",
    "is_file_url",
    "is_readonly_path",
    "is_valid_url",
    "mkdir_p",
    "ensure_mkdir_p",
    "create_tracked_tempdir",
    "path_to_url",
    "rmtree",
    "safe_expandvars",
    "set_write_bit",
    "url_to_path",
    "walk_up",
]


def unicode_path(path):
    # Paths are supposed to be represented as unicode here
    if six.PY2 and not isinstance(path, six.text_type):
        return path.decode(_fs_encoding)
    return path


def native_path(path):
    if six.PY2 and not isinstance(path, bytes):
        return path.encode(_fs_encoding)
    return path


# once again thank you django...
# https://github.com/django/django/blob/fc6b90b/django/utils/_os.py
if six.PY3 or os.name == 'nt':
    abspathu = os.path.abspath
else:
    def abspathu(path):
        """
        Version of os.path.abspath that uses the unicode representation
        of the current working directory, thus avoiding a UnicodeDecodeError
        in join when the cwd has non-ASCII characters.
        """
        if not os.path.isabs(path):
            path = os.path.join(os.getcwdu(), path)
        return os.path.normpath(path)


def normalize_drive(path):
    """Normalize drive in path so they stay consistent.

    This currently only affects local drives on Windows, which can be
    identified with either upper or lower cased drive names. The case is
    always converted to uppercase because it seems to be preferred.
    """
    if os.name != "nt" or not isinstance(path, six.string_types):
        return path

    drive, tail = os.path.splitdrive(path)
    # Only match (lower cased) local drives (e.g. 'c:'), not UNC mounts.
    if drive.islower() and len(drive) == 2 and drive[1] == ":":
        return "{}{}".format(drive.upper(), tail)

    return to_text(path, encoding="utf-8")


def path_to_url(path):
    """Convert the supplied local path to a file uri.

    :param str path: A string pointing to or representing a local path
    :return: A `file://` uri for the same location
    :rtype: str

    >>> path_to_url("/home/user/code/myrepo/myfile.zip")
    'file:///home/user/code/myrepo/myfile.zip'
    """

    if not path:
        return path
    path = to_bytes(path, encoding="utf-8")
    normalized_path = to_text(normalize_drive(os.path.abspath(path)), encoding="utf-8")
    return to_text(Path(normalized_path).as_uri(), encoding="utf-8")


def url_to_path(url):
    """Convert a valid file url to a local filesystem path

    Follows logic taken from pip's equivalent function
    """
    assert is_file_url(url), "Only file: urls can be converted to local paths"
    _, netloc, path, _, _ = urllib_parse.urlsplit(url)
    # Netlocs are UNC paths
    if netloc:
        netloc = "\\\\" + netloc

    path = urllib_request.url2pathname(netloc + path)
    return to_bytes(path, encoding="utf-8")


def is_valid_url(url):
    """Checks if a given string is an url"""
    if not url:
        return url
    pieces = urllib_parse.urlparse(url)
    return all([pieces.scheme, pieces.netloc])


def is_file_url(url):
    """Returns true if the given url is a file url"""
    if not url:
        return False
    if not isinstance(url, six.string_types):
        try:
            url = getattr(url, "url")
        except AttributeError:
            raise ValueError("Cannot parse url from unknown type: {0!r}".format(url))
    url = to_text(url, encoding="utf-8")
    return urllib_parse.urlparse(url.lower()).scheme == "file"


def is_readonly_path(fn):
    """Check if a provided path exists and is readonly.

    Permissions check is `bool(path.stat & stat.S_IREAD)` or `not os.access(path, os.W_OK)`
    """
    fn = to_bytes(fn, encoding="utf-8")
    if os.path.exists(fn):
        return bool(os.stat(fn).st_mode & stat.S_IREAD) and not os.access(fn, os.W_OK)
    return False


def mkdir_p(newdir, mode=0o777):
    """Recursively creates the target directory and all of its parents if they do not
    already exist.  Fails silently if they do.

    :param str newdir: The directory path to ensure
    :raises: OSError if a file is encountered along the way
    """
    # http://code.activestate.com/recipes/82465-a-friendly-mkdir/
    newdir = abspathu(to_bytes(newdir, "utf-8"))
    if os.path.exists(newdir):
        if not os.path.isdir(newdir):
            raise OSError(
                "a file with the same name as the desired dir, '{0}', already exists.".format(
                    newdir
                )
            )
        pass
    else:
        head, tail = os.path.split(newdir)
        # Make sure the tail doesn't point to the asame place as the head
        tail_and_head_match = os.path.relpath(tail, start=os.path.basename(head)) == "."
        if tail and not tail_and_head_match and not os.path.isdir(newdir):
            target = os.path.join(head, tail)
            if os.path.exists(target) and os.path.isfile(target):
                raise OSError(
                   "A file with the same name as the desired dir, '{0}', already exists.".format(
                        newdir
                    )
                )
            os.makedirs(os.path.join(head, tail), mode)


def ensure_mkdir_p(mode=0o777):
    """Decorator to ensure `mkdir_p` is called to the function's return value.
    """
    def decorator(f):

        @functools.wraps(f)
        def decorated(*args, **kwargs):
            path = f(*args, **kwargs)
            mkdir_p(path, mode=mode)
            return path

        return decorated

    return decorator


TRACKED_TEMPORARY_DIRECTORIES = []


def create_tracked_tempdir(*args, **kwargs):
    """Create a tracked temporary directory.

    This uses `TemporaryDirectory`, but does not remove the directory when
    the return value goes out of scope, instead registers a handler to cleanup
    on program exit.

    The return value is the path to the created directory.
    """
    tempdir = TemporaryDirectory(*args, **kwargs)
    TRACKED_TEMPORARY_DIRECTORIES.append(tempdir)
    atexit.register(tempdir.cleanup)
    return tempdir.name


def set_write_bit(fn):
    """Set read-write permissions for the current user on the target path.  Fail silently
    if the path doesn't exist.

    :param str fn: The target filename or path
    """

    fn = to_bytes(fn, encoding=locale_encoding)
    if not os.path.exists(fn):
        return
    os.chmod(fn, stat.S_IWRITE | stat.S_IWUSR | stat.S_IRUSR)


def rmtree(directory, ignore_errors=False):
    """Stand-in for :func:`~shutil.rmtree` with additional error-handling.

    This version of `rmtree` handles read-only paths, especially in the case of index
    files written by certain source control systems.

    :param str directory: The target directory to remove
    :param bool ignore_errors: Whether to ignore errors, defaults to False

    .. note::

       Setting `ignore_errors=True` may cause this to silently fail to delete the path
    """

    directory = to_bytes(directory, encoding=locale_encoding)
    shutil.rmtree(
        directory, ignore_errors=ignore_errors, onerror=handle_remove_readonly
    )


def handle_remove_readonly(func, path, exc):
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
    from .compat import ResourceWarning
    default_warning_message = (
        "Unable to remove file due to permissions restriction: {!r}"
    )
    # split the initial exception out into its type, exception, and traceback
    exc_type, exc_exception, exc_tb = exc
    path = to_bytes(path)
    if is_readonly_path(path):
        # Apply write permission and call original function
        set_write_bit(path)
        try:
            func(path)
        except (OSError, IOError) as e:
            if e.errno in [errno.EACCES, errno.EPERM]:
                warnings.warn(
                    default_warning_message.format(
                        to_text(path, encoding=locale_encoding)
                    ), ResourceWarning
                )
                return

    if exc_exception.errno in [errno.EACCES, errno.EPERM]:
        warnings.warn(
            default_warning_message.format(to_text(path)),
            ResourceWarning
        )
        return

    raise


def walk_up(bottom):
    """Mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """
    bottom = os.path.realpath(bottom)
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
    """ Checks to see if a pathlib `Path` object is a unc path or not"""
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
    if not (relpath_s == u"." or relpath_s.startswith(u"./")):
        relpath_s = posixpath.join(u".", relpath_s)
    return relpath_s


def safe_expandvars(value):
    """Call os.path.expandvars if value is a string, otherwise do nothing.
    """
    if isinstance(value, six.string_types):
        return os.path.expandvars(value)
    return value
