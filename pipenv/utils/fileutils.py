"""A collection for utilities for working with files and paths."""

import atexit
import io
import os
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
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


def url_to_path(url: str) -> Path:
    """Convert a valid file url to a local filesystem path.

    Follows logic taken from pip's equivalent function
    """
    assert is_file_url(url), "Only file: urls can be converted to local paths"
    _, netloc, path, _, _ = urllib_parse.urlsplit(url)
    # Netlocs are UNC paths
    if netloc:
        netloc = "\\\\" + netloc

    path_str = urllib_request.url2pathname(netloc + path)
    return Path(urllib_parse.unquote(path_str))


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
    # Convert to string if it's a Path object
    path_str = str(path)

    # Expand user directory and environment variables
    # (pathlib doesn't have expandvars equivalent)
    expanded_path = os.path.expandvars(Path(path_str).expanduser())

    # Create Path object, resolve to absolute path, and return as string
    return str(Path(expanded_path).resolve())


def normalize_drive(path):
    """Normalize drive in path so they stay consistent.

    This currently only affects local drives on Windows, which can be
    identified with either upper or lower cased drive names. The case is
    always converted to uppercase because it seems to be preferred.
    """
    if os.name != "nt":
        return path

    # Handle Path objects
    if isinstance(path, Path):
        path_str = str(path)
        result = normalize_drive(path_str)
        return Path(result) if result != path_str else path

    # Handle strings
    if isinstance(path, str):
        # Use PureWindowsPath to handle Windows-specific path operations
        win_path = PureWindowsPath(path)
        drive = win_path.drive

        # Only match (lower cased) local drives (e.g. 'c:'), not UNC mounts
        if drive.islower() and len(drive) == 2 and drive[1] == ":":
            # Replace just the drive part with its uppercase version
            return f"{drive.upper()}{path[2:]}"

    # Return unchanged for non-string, non-Path objects or paths without lowercase drives
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

    # Create an absolute path
    abs_path = Path(path).resolve()

    # Normalize drive letter on Windows
    normalized_path = normalize_drive(str(abs_path))

    # Convert to POSIX path format
    posix_path = Path(normalized_path).as_posix()

    if os.name == "nt" and posix_path[1] == ":":
        drive, _, remainder = posix_path.partition(":")
        # Handle half-surrogates that were never actually part of a surrogate pair
        quoted_path = quote(remainder, errors="backslashreplace")
        return f"file:///{drive}:{quoted_path}"

    # Handle dangling surrogates on Linux
    quoted_path = quote(posix_path, errors="backslashreplace")
    return f"file://{quoted_path}"


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

    # Check if the link is a local path that exists
    if not is_valid_url(link):
        path_obj = Path(link)
        if path_obj.exists():
            link = path_to_url(path_obj)

    if is_file_url(link):
        # Local URL
        local_path = Path(url_to_path(link))
        if local_path.is_dir():
            raise ValueError(f"Cannot open directory for read: {link}")
        else:
            with local_path.open("rb") as local_file:
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


def create_tracked_tempdir(*args: Any, **kwargs: Any) -> Path:
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
    return Path(tempdir.name)


def check_for_unc_path(path):
    # type: (Path) -> bool
    """Checks to see if a pathlib `Path` object is a unc path or not."""
    return bool(
        os.name == "nt"
        and len(path.drive) > 2
        and not path.drive[0].isalpha()
        and path.drive[1] != ":"
    )
