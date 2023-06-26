"""A collection for utilities for working with files and paths."""
import atexit
import io
import os
import posixpath
import sys
import warnings
from contextlib import closing, contextmanager
from http.client import HTTPResponse as Urllib_HTTPResponse
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO, Any, ContextManager, Iterator, Optional, Text, TypeVar, Union
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib.parse import quote, urlparse

from pipenv.patched.pip._vendor.requests import Session
from pipenv.patched.pip._vendor.urllib3.response import HTTPResponse as Urllib3_HTTPResponse

_T = TypeVar("_T")


@contextmanager
def cd(path):
    # type: () -> Iterator[None]
    """Context manager to temporarily change working directories.

    :param str path: The directory to move into
    >>> print(os.path.abspath(os.curdir))
    '/home/user/code/myrepo'
    >>> with cd("/home/user/code/otherdir/subdir"):
    ...     print("Changed directory: %s" % os.path.abspath(os.curdir))
    Changed directory: /home/user/code/otherdir/subdir
    >>> print(os.path.abspath(os.curdir))
    '/home/user/code/myrepo'
    """
    if not path:
        return
    prev_cwd = Path.cwd().as_posix()
    if isinstance(path, Path):
        path = path.as_posix()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(prev_cwd)


def is_file_url(url: Any) -> bool:
    """Returns true if the given url is a file url."""
    if not url:
        return False
    if not isinstance(url, str):
        try:
            url = url.url
        except AttributeError:
            raise ValueError("Cannot parse url from unknown type: {!r}".format(url))
    return urllib_parse.urlparse(url.lower()).scheme == "file"


def is_valid_url(url: str) -> bool:
    """Checks if a given string is an url."""
    pieces = urlparse(url)
    return all([pieces.scheme, pieces.netloc])


def url_to_path(url: str) -> str:
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


if os.name == "nt":
    # from click _winconsole.py
    from ctypes import create_unicode_buffer, windll

    def get_long_path(short_path: Text) -> Text:
        BUFFER_SIZE = 500
        buffer = create_unicode_buffer(BUFFER_SIZE)
        get_long_path_name = windll.kernel32.GetLongPathNameW
        get_long_path_name(short_path, buffer, BUFFER_SIZE)
        return buffer.value


def normalize_path(path: str) -> str:
    """Return a case-normalized absolute variable-expanded path."""
    return os.path.expandvars(
        os.path.expanduser(os.path.normcase(os.path.normpath(os.path.abspath(str(path)))))
    )


def normalize_drive(path):
    """Normalize drive in path so they stay consistent.

    This currently only affects local drives on Windows, which can be
    identified with either upper or lower cased drive names. The case is
    always converted to uppercase because it seems to be preferred.
    """
    if os.name != "nt" or not isinstance(path, str):
        return path

    drive, tail = os.path.splitdrive(path)
    # Only match (lower cased) local drives (e.g. 'c:'), not UNC mounts.
    if drive.islower() and len(drive) == 2 and drive[1] == ":":
        return f"{drive.upper()}{tail}"

    return path


def path_to_url(path):
    """Convert the supplied local path to a file uri.

    :param str path: A string pointing to or representing a local path
    :return: A `file://` uri for the same location
    :rtype: str
    >>> path_to_url("/home/user/code/myrepo/myfile.zip")
    'file:///home/user/code/myrepo/myfile.zip'
    """

    if not path:
        return path  # type: ignore
    normalized_path = Path(normalize_drive(os.path.abspath(path))).as_posix()
    if os.name == "nt" and normalized_path[1] == ":":
        drive, _, path = normalized_path.partition(":")
        # XXX: This enables us to handle half-surrogates that were never
        # XXX: actually part of a surrogate pair, but were just incidentally
        # XXX: passed in as a piece of a filename
        quoted_path = quote(path, errors="backslashreplace")
        return "file:///{}:{}".format(drive, quoted_path)
    # XXX: This is also here to help deal with incidental dangling surrogates
    # XXX: on linux, by making sure they are preserved during encoding so that
    # XXX: we can urlencode the backslash correctly
    # bytes_path = to_bytes(normalized_path, errors="backslashreplace")
    return "file://{}".format(quote(path, errors="backslashreplace"))


@contextmanager
def open_file(
    link: Union[_T, str], session: Optional[Session] = None, stream: bool = True
) -> ContextManager[Union[IO[bytes], Urllib3_HTTPResponse, Urllib_HTTPResponse]]:
    """Open local or remote file for reading.

    :param pipenv.patched.pip._internal.index.Link link: A link object from resolving dependencies with
        pip, or else a URL.
    :param Optional[Session] session: A :class:`~requests.Session` instance
    :param bool stream: Whether to stream the content if remote, default True
    :raises ValueError: If link points to a local directory.
    :return: a context manager to the opened file-like object
    """
    if not isinstance(link, str):
        try:
            link = link.url_without_fragment
        except AttributeError:
            raise ValueError("Cannot parse url from unknown type: {0!r}".format(link))

    if not is_valid_url(link) and os.path.exists(link):
        link = path_to_url(link)

    if is_file_url(link):
        # Local URL
        local_path = url_to_path(link)
        if os.path.isdir(local_path):
            raise ValueError("Cannot open directory for read: {}".format(link))
        else:
            with io.open(local_path, "rb") as local_file:
                yield local_file
    else:
        # Remote URL
        headers = {"Accept-Encoding": "identity"}
        if not session:
            try:
                from pipenv.patched.pip._vendor.requests import Session  # noqa
            except ImportError:
                session = None
            else:
                session = Session()
        if session is None:
            with closing(urllib_request.urlopen(link)) as f:
                yield f
        else:
            with session.get(link, headers=headers, stream=stream) as resp:
                try:
                    raw = getattr(resp, "raw", None)
                    result = raw if raw else resp
                    yield result
                finally:
                    if raw:
                        conn = raw._connection
                        if conn is not None:
                            conn.close()
                    result.close()


@contextmanager
def temp_path():
    # type: () -> Iterator[None]
    """A context manager which allows the ability to set sys.path temporarily.

    >>> path_from_virtualenv = load_path("/path/to/venv/bin/python")
    >>> print(sys.path)
    [
        '/home/user/.pyenv/versions/3.7.0/bin',
        '/home/user/.pyenv/versions/3.7.0/lib/python37.zip',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/lib-dynload',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/site-packages'
    ]
    >>> with temp_path():
            sys.path = path_from_virtualenv
            # Running in the context of the path above
            run(["pip", "install", "stuff"])
    >>> print(sys.path)
    [
        '/home/user/.pyenv/versions/3.7.0/bin',
        '/home/user/.pyenv/versions/3.7.0/lib/python37.zip',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/lib-dynload',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/site-packages'
    ]
    """
    path = [p for p in sys.path]
    try:
        yield
    finally:
        sys.path = [p for p in path]


TRACKED_TEMPORARY_DIRECTORIES = []


def create_tracked_tempdir(*args: Any, **kwargs: Any) -> str:
    """Create a tracked temporary directory.

    This uses `TemporaryDirectory`, but does not remove the directory
    when the return value goes out of scope, instead registers a handler
    to cleanup on program exit. The return value is the path to the
    created directory.
    """
    tempdir = TemporaryDirectory(*args, **kwargs)
    TRACKED_TEMPORARY_DIRECTORIES.append(tempdir)
    atexit.register(tempdir.cleanup)
    warnings.simplefilter("ignore", ResourceWarning)
    return tempdir.name


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
        relative_to = os.getcwd()

    start_path = Path(str(relative_to))
    try:
        start = start_path.resolve()
    except OSError:
        start = start_path.absolute()

    # check if there is a drive letter or mount point
    # if it is a mountpoint use the original absolute path
    # instead of the unc path
    if check_for_unc_path(start):
        start = start_path.absolute()

    path = start.joinpath(str(path)).relative_to(start)

    # check and see if the path that was passed into the function is a UNC path
    # and raise value error if it is not.
    if check_for_unc_path(path):
        raise ValueError("The path argument does not currently accept UNC paths")

    relpath_s = posixpath.normpath(path.as_posix())
    if not (relpath_s == "." or relpath_s.startswith("./")):
        relpath_s = posixpath.join(".", relpath_s)
    return relpath_s
