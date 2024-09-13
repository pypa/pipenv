"""A collection for utilities for working with files and paths."""

import atexit
import io
import os
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib.parse import quote, urlparse

from pipenv.patched.pip._internal.locations import USER_CACHE_DIR
from pipenv.patched.pip._internal.network.download import PipSession
from pipenv.utils import err


def is_file_url(url: Any) -> bool:
    """Returns true if the given url is a file url."""
    if not url:
        return False
    if not isinstance(url, str):
        try:
            url = url.url
        except AttributeError:
            raise ValueError(f"Cannot parse url from unknown type: {url!r}")
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

    def get_long_path(short_path: str) -> str:
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
        return f"file:///{drive}:{quoted_path}"
    # XXX: This is also here to help deal with incidental dangling surrogates
    # XXX: on linux, by making sure they are preserved during encoding so that
    # XXX: we can urlencode the backslash correctly
    # bytes_path = to_bytes(normalized_path, errors="backslashreplace")
    return "file://{}".format(quote(path, errors="backslashreplace"))


@contextmanager
def open_file(link, session: Optional[PipSession] = None, stream: bool = False):
    """Open local or remote file for reading.

    :param pipenv.patched.pip._internal.index.Link link: A link object from resolving dependencies with
        pip, or else a URL.
    :param Optional[PipSession] session: A :class:`~PipSession` instance
    :param bool stream: Whether to stream the content if remote, default True
    :raises ValueError: If link points to a local directory.
    :return: a context manager to the opened file-like object
    """
    if not isinstance(link, str):
        try:
            link = link.url_without_fragment
        except AttributeError:
            raise ValueError(f"Cannot parse url from unknown type: {link!r}")

    if not is_valid_url(link) and os.path.exists(link):
        link = path_to_url(link)

    if is_file_url(link):
        # Local URL
        local_path = url_to_path(link)
        if os.path.isdir(local_path):
            raise ValueError(f"Cannot open directory for read: {link}")
        else:
            with open(local_path, "rb") as local_file:
                yield local_file
    else:
        # Remote URL
        headers = {"Accept-Encoding": "identity"}
        if not session:
            session = PipSession(cache=USER_CACHE_DIR)
        resp = session.get(link, headers=headers, stream=stream)
        if resp.status_code != 200:
            err.print(f"HTTP error {resp.status_code} while getting {link}")
            yield None
        else:
            # Creating a buffer-like object
            buffer = io.BytesIO(resp.content)
            yield buffer


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
    path = list(sys.path)
    try:
        yield
    finally:
        sys.path = list(path)


TRACKED_TEMPORARY_DIRECTORIES = []


def create_tracked_tempdir(*args: Any, **kwargs: Any) -> str:
    """Create a tracked temporary directory.

    This uses `TemporaryDirectory`, but does not remove the directory
    when the return value goes out of scope, instead registers a handler
    to clean up on program exit. The return value is the path to the
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
    return bool(
        os.name == "nt"
        and len(path.drive) > 2
        and not path.drive[0].isalpha()
        and path.drive[1] != ":"
    )
