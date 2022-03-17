import errno
import os
import re
import shutil
import stat
import sys
import warnings
from contextlib import contextmanager
from urllib.parse import urlparse

import parse
from urllib3 import util as urllib3_util
from vistir.compat import ResourceWarning


requests_session = None  # type: ignore


def _get_requests_session(max_retries=1):
    """Load requests lazily."""
    global requests_session
    if requests_session is not None:
        return requests_session
    import requests

    requests_session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=max_retries)
    requests_session.mount("https://pypi.org/pypi", adapter)
    return requests_session


def is_valid_url(url):
    """Checks if a given string is an url"""
    pieces = urlparse(url)
    return all([pieces.scheme, pieces.netloc])


def is_pypi_url(url):
    return bool(re.match(r"^http[s]?:\/\/pypi(?:\.python)?\.org\/simple[\/]?$", url))


def replace_pypi_sources(sources, pypi_replacement_source):
    return [pypi_replacement_source] + [
        source for source in sources if not is_pypi_url(source["url"])
    ]


def create_mirror_source(url):
    return {
        "url": url,
        "verify_ssl": url.startswith("https://"),
        "name": urlparse(url).hostname,
    }


def download_file(url, filename, max_retries=1):
    """Downloads file from url to a path with filename"""
    r = _get_requests_session(max_retries).get(url, stream=True)
    if not r.ok:
        raise OSError("Unable to download file")

    with open(filename, "wb") as f:
        f.write(r.content)


@contextmanager
def temp_path():
    """Allow the ability to set os.environ temporarily"""
    path = [p for p in sys.path]
    try:
        yield
    finally:
        sys.path = [p for p in path]


def normalize_drive(path):
    """Normalize drive in path so they stay consistent.

    This currently only affects local drives on Windows, which can be
    identified with either upper or lower cased drive names. The case is
    always converted to uppercase because it seems to be preferred.

    See: <https://github.com/pypa/pipenv/issues/1218>
    """
    if os.name != "nt" or not isinstance(path, str):
        return path

    drive, tail = os.path.splitdrive(path)
    # Only match (lower cased) local drives (e.g. 'c:'), not UNC mounts.
    if drive.islower() and len(drive) == 2 and drive[1] == ":":
        return f"{drive.upper()}{tail}"

    return path


def is_readonly_path(fn):
    """Check if a provided path exists and is readonly.

    Permissions check is `bool(path.stat & stat.S_IREAD)` or `not os.access(path, os.W_OK)`
    """
    if os.path.exists(fn):
        return (os.stat(fn).st_mode & stat.S_IREAD) or not os.access(fn, os.W_OK)

    return False


def set_write_bit(fn):
    if isinstance(fn, str) and not os.path.exists(fn):
        return
    os.chmod(fn, stat.S_IWRITE | stat.S_IWUSR | stat.S_IRUSR)
    return


def rmtree(directory, ignore_errors=False):
    shutil.rmtree(
        directory, ignore_errors=ignore_errors, onerror=handle_remove_readonly
    )


def handle_remove_readonly(func, path, exc):
    """Error handler for shutil.rmtree.

    Windows source repo folders are read-only by default, so this error handler
    attempts to set them as writeable and then proceed with deletion."""
    # Check for read-only attribute
    default_warning_message = (
        "Unable to remove file due to permissions restriction: {!r}"
    )
    # split the initial exception out into its type, exception, and traceback
    exc_type, exc_exception, exc_tb = exc
    if is_readonly_path(path):
        # Apply write permission and call original function
        set_write_bit(path)
        try:
            func(path)
        except OSError as e:
            if e.errno in [errno.EACCES, errno.EPERM]:
                warnings.warn(default_warning_message.format(path), ResourceWarning)
                return

    if exc_exception.errno in [errno.EACCES, errno.EPERM]:
        warnings.warn(default_warning_message.format(path), ResourceWarning)
        return

    raise exc


def get_host_and_port(url):
    """Get the host, or the host:port pair if port is explicitly included, for the given URL.

    Examples:
    >>> get_host_and_port('example.com')
    'example.com'
    >>> get_host_and_port('example.com:443')
    'example.com:443'
    >>> get_host_and_port('http://example.com')
    'example.com'
    >>> get_host_and_port('https://example.com/')
    'example.com'
    >>> get_host_and_port('https://example.com:8081')
    'example.com:8081'
    >>> get_host_and_port('ssh://example.com')
    'example.com'

    :param url: the URL string to parse
    :return: a string with the host:port pair if the URL includes port number explicitly; otherwise, returns host only
    """
    url = urllib3_util.parse_url(url)
    return '{}:{}'.format(url.host, url.port) if url.port else url.host


def get_url_name(url):
    if not isinstance(url, str):
        return
    return urllib3_util.parse_url(url).host


def is_url_equal(url, other_url):
    # type: (str, str) -> bool
    """
    Compare two urls by scheme, host, and path, ignoring auth

    :param str url: The initial URL to compare
    :param str url: Second url to compare to the first
    :return: Whether the URLs are equal without **auth**, **query**, and **fragment**
    :rtype: bool

    >>> is_url_equal("https://user:pass@mydomain.com/some/path?some_query",
                     "https://user2:pass2@mydomain.com/some/path")
    True

    >>> is_url_equal("https://user:pass@mydomain.com/some/path?some_query",
                 "https://mydomain.com/some?some_query")
    False
    """
    if not isinstance(url, str):
        raise TypeError(f"Expected string for url, received {url!r}")
    if not isinstance(other_url, str):
        raise TypeError(f"Expected string for url, received {other_url!r}")
    parsed_url = urllib3_util.parse_url(url)
    parsed_other_url = urllib3_util.parse_url(other_url)
    unparsed = parsed_url._replace(auth=None, query=None, fragment=None).url
    unparsed_other = parsed_other_url._replace(auth=None, query=None, fragment=None).url
    return unparsed == unparsed_other


def proper_case(package_name):
    """Properly case project name from pypi.org."""
    # Hit the simple API.
    r = _get_requests_session().get(
        f"https://pypi.org/pypi/{package_name}/json", timeout=0.3, stream=True
    )
    if not r.ok:
        raise OSError(
            f"Unable to find package {package_name} in PyPI repository."
        )

    r = parse.parse("https://pypi.org/pypi/{name}/json", r.url)
    good_name = r["name"]
    return good_name
