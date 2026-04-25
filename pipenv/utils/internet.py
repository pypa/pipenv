import os
import re
from html.parser import HTMLParser
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse, urlunsplit

from pipenv.patched.pip._internal.locations import USER_CACHE_DIR
from pipenv.patched.pip._internal.network.download import PipSession
from pipenv.patched.pip._vendor.urllib3 import util as urllib3_util


def get_requests_session(
    max_retries=1, verify_ssl=True, cache_dir=USER_CACHE_DIR, source=None
):
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
    r = get_requests_session(max_retries).get(url, stream=True)
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
    return f"{url.host}:{url.port}" if url.port else url.host


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
    r = get_requests_session().get(
        f"https://pypi.org/pypi/{package_name}/json", timeout=3, stream=True
    )
    r.close()
    if not r.ok:
        raise OSError(f"Unable to find package {package_name} in PyPI repository.")

    regex = r"https://pypi\.org/pypi/(.*)/json$"
    match = re.search(regex, r.url)
    good_name = match.group(1)

    return good_name


def _strip_credentials_from_url(
    url: Optional[str],
) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    """Split userinfo (username/password) out of a URL.

    Returns ``(stripped_url, (username, password))``.  When the URL has no
    embedded credentials the second element is ``None`` and the URL is
    returned unchanged.  Username and password are URL-decoded so callers
    can hand them straight to authentication backends (e.g. netrc).

    See GHSA-8xgg-v3jj-95m2: pipenv must not propagate credentials embedded
    in source URLs to subprocess argv where they are visible via ``ps`` and
    ``/proc/<pid>/cmdline``.
    """
    if not url:
        return url, None
    parsed = urlparse(url)
    if not parsed.username and not parsed.password:
        return url, None

    netloc = parsed.netloc.rsplit("@", 1)[-1]
    stripped = urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )
    username = unquote(parsed.username) if parsed.username else ""
    password = unquote(parsed.password) if parsed.password else ""
    return stripped, (username, password)


def _read_existing_netrc_content() -> str:
    """Read the user's existing netrc file (if any) so that we can preserve
    its entries when writing a temporary netrc.  Returns an empty string when
    no netrc is configured or readable.
    """
    candidates = []
    netrc_env = os.environ.get("NETRC")
    if netrc_env:
        candidates.append(netrc_env)
    home = os.path.expanduser("~")
    if home and home != "~":
        if os.name == "nt":
            candidates.extend([os.path.join(home, "_netrc"), os.path.join(home, ".netrc")])
        else:
            candidates.append(os.path.join(home, ".netrc"))
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            continue
    return ""


def write_credentials_netrc(sources, directory) -> Optional[str]:
    """Write a netrc file containing credentials extracted from source URLs.

    Pipenv strips userinfo from index URLs before they reach pip's argv (to
    avoid leaking secrets via process listings, GHSA-8xgg-v3jj-95m2).  We
    re-introduce those credentials to pip via a temporary netrc file whose
    location is exposed through the ``NETRC`` environment variable.  Pip
    (via its vendored ``requests``) will consult this file when it needs
    HTTP basic auth for an index host.

    Existing user netrc entries are preserved by appending the contents of
    the user's netrc to the temporary file, so unrelated machines remain
    authenticatable.

    Returns the absolute path to the netrc file, or ``None`` when no
    credentialed sources were supplied.
    """
    if not sources:
        return None

    machine_blocks = []
    seen_hosts = set()
    for source in sources:
        url = source.get("url") if isinstance(source, dict) else None
        if not url:
            continue
        _, creds = _strip_credentials_from_url(url)
        if creds is None:
            continue
        username, password = creds
        host = urlparse(url).hostname
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        machine_blocks.append(
            f"machine {host}\n  login {username}\n  password {password}\n"
        )

    if not machine_blocks:
        return None

    existing = _read_existing_netrc_content().strip()
    body = "\n".join(machine_blocks)
    if existing:
        body = f"{body}\n{existing}\n"

    netrc_path = os.path.join(str(directory), "pipenv-netrc")
    # Write with restrictive permissions: netrc parsers (and pip's vendored
    # requests) refuse to read world-readable netrc files on POSIX systems.
    fd = os.open(
        netrc_path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        if not hasattr(os, "fchmod"):
            try:
                os.chmod(netrc_path, 0o600)
            except OSError:
                pass
    except Exception:
        try:
            os.unlink(netrc_path)
        except OSError:
            pass
        raise
    return netrc_path


class PackageIndexHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        # If tag is an anchor
        if tag == "a":
            # find href attribute
            self.urls += [attr[1] for attr in attrs if attr[0] == "href"]
