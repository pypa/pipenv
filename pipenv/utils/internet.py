import re
from urllib.parse import urlparse

from pipenv.patched.pip._vendor import requests
from pipenv.patched.pip._vendor.requests.adapters import HTTPAdapter
from pipenv.patched.pip._vendor.urllib3 import util as urllib3_util


def _get_requests_session(max_retries=1, verify_ssl=True):
    """Load requests lazily."""
    requests_session = requests.Session()
    adapter = HTTPAdapter(max_retries=max_retries)
    requests_session.mount("https://", adapter)
    if verify_ssl is False:
        requests_session.verify = False
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


def create_mirror_source(url, name):
    return {
        "url": url,
        "verify_ssl": url.startswith("https://"),
        "name": name,
    }


def download_file(url, filename, max_retries=1):
    """Downloads file from url to a path with filename"""
    r = _get_requests_session(max_retries).get(url, stream=True)
    r.close()
    if not r.ok:
        raise OSError("Unable to download file")

    with open(filename, "wb") as f:
        f.write(r.content)


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
    return "{}:{}".format(url.host, url.port) if url.port else url.host


def get_url_name(url):
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


def proper_case(package_name):
    """Properly case project name from pypi.org."""
    # Hit the simple API.
    r = _get_requests_session().get(
        f"https://pypi.org/pypi/{package_name}/json", timeout=0.3, stream=True
    )
    r.close()
    if not r.ok:
        raise OSError(f"Unable to find package {package_name} in PyPI repository.")

    regex = r"https://pypi\.org/pypi/(.*)/json$"
    match = re.search(regex, r.url)
    good_name = match.group(1)

    return good_name
