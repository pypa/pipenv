from __future__ import annotations

import os
import re
from functools import lru_cache
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pipenv.patched.pip._internal.locations import USER_CACHE_DIR
from pipenv.patched.pip._internal.network.download import PipSession
from pipenv.patched.pip._vendor.urllib3 import util as urllib3_util

if TYPE_CHECKING:
    from pipenv._types.pipfile2 import TSource


def get_requests_session(
    max_retries: int = 1,
    verify_ssl: bool = True,
    cache_dir: str = USER_CACHE_DIR,
    source: str | None = None,
) -> PipSession:
    """Load requests lazily."""
    pip_client_cert = os.environ.get("PIP_CLIENT_CERT")
    index_urls = [source] if source else None
    requests_session = PipSession(
        cache=cache_dir, retries=max_retries, index_urls=index_urls
    )
    if pip_client_cert:
        requests_session.cert = pip_client_cert
    if verify_ssl is False:
        requests_session.verify = False
    return requests_session


def is_valid_url(url: str | None) -> bool:
    """Checks if a given string is an url"""
    pieces = urlparse(url)
    return all([pieces.scheme, pieces.netloc])


def is_pypi_url(url: str) -> bool:
    return bool(re.match(r"^http[s]?:\/\/pypi(?:\.python)?\.org\/simple[\/]?$", url))


def replace_pypi_sources(
    sources: list[TSource], pypi_replacement_source: TSource
) -> list[TSource]:
    return [pypi_replacement_source] + [
        source for source in sources if not is_pypi_url(source["url"])
    ]


def create_mirror_source(url: str, name: str) -> TSource:
    return {
        "url": url,
        "verify_ssl": url.startswith("https://"),
        "name": name,
    }


def download_file(url: str, filename: str, max_retries: int = 1) -> None:
    """Downloads file from url to a path with filename"""
    r = get_requests_session(max_retries).get(url, stream=True)
    r.close()
    if not r.ok:
        raise OSError("Unable to download file")

    with open(filename, "wb") as f:
        f.write(r.content)


def get_host_and_port(url: str) -> str:
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
    _url = urllib3_util.parse_url(url)
    return f"{_url.host}:{_url.port}" if _url.port else _url.host


def get_url_name(url: str) -> str:
    if not isinstance(url, str):
        return
    return urllib3_util.parse_url(url).host


def is_url_equal(url: str, other_url: str) -> bool:
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


@lru_cache(maxsize=None)
def proper_case(package_name: str) -> str:
    """Properly case project name from pypi.org."""
    # Hit the simple API.
    r = get_requests_session().get(
        f"https://pypi.org/pypi/{package_name}/json", timeout=0.3, stream=True
    )
    r.close()
    if not r.ok:
        raise OSError(f"Unable to find package {package_name} in PyPI repository.")

    regex = r"https://pypi\.org/pypi/(.*)/json$"
    match = re.search(regex, r.url)
    good_name = match.group(1)  # type: ignore

    return good_name


class PackageIndexHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # If tag is an anchor
        if tag == "a":
            # find href attribute
            self.urls += [attr[1] for attr in attrs if attr[0] == "href"]
