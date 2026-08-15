from collections.abc import Generator
from typing import Literal, NoReturn, TypeAlias, cast
from urllib.parse import urlsplit

from pipenv.patched.pip._vendor import requests, urllib3
from pipenv.patched.pip._vendor.requests.models import Response
from pipenv.patched.pip._vendor.urllib3.exceptions import TimeoutStateError

from pipenv.patched.pip._internal.exceptions import (
    ConnectionFailedError,
    ConnectionTimeoutError,
    NetworkConnectionError,
    ProxyConnectionError,
    SSLVerificationError,
)
from pipenv.patched.pip._internal.utils.misc import redact_auth_from_url

TimeoutValue: TypeAlias = (
    float | tuple[float | None, float | None] | urllib3.util.Timeout | None
)

# The following comments and HTTP headers were originally added by
# Donald Stufft in git commit 22c562429a61bb77172039e480873fb239dd8c03.
#
# We use Accept-Encoding: identity here because requests defaults to
# accepting compressed responses. This breaks in a variety of ways
# depending on how the server is configured.
# - Some servers will notice that the file isn't a compressible file
#   and will leave the file alone and with an empty Content-Encoding
# - Some servers will notice that the file is already compressed and
#   will leave the file alone, adding a Content-Encoding: gzip header
# - Some servers won't notice anything at all and will take a file
#   that's already been compressed and compress it again, and set
#   the Content-Encoding: gzip header
# By setting this to request only the identity encoding we're hoping
# to eliminate the third case.  Hopefully there does not exist a server
# which when given a file will notice it is already compressed and that
# you're not asking for a compressed file and will then decompress it
# before sending because if that's the case I don't think it'll ever be
# possible to make this work.
HEADERS: dict[str, str] = {"Accept-Encoding": "identity"}

DOWNLOAD_CHUNK_SIZE = 256 * 1024


def raise_for_status(resp: Response) -> None:
    http_error_msg = ""
    if isinstance(resp.reason, bytes):
        # We attempt to decode utf-8 first because some servers
        # choose to localize their reason strings. If the string
        # isn't utf-8, we fall back to iso-8859-1 for all other
        # encodings.
        try:
            reason = resp.reason.decode("utf-8")
        except UnicodeDecodeError:
            reason = resp.reason.decode("iso-8859-1")
    else:
        reason = resp.reason

    if 400 <= resp.status_code < 500:
        http_error_msg = (
            f"{resp.status_code} Client Error: {reason} for url: {resp.url}"
        )

    elif 500 <= resp.status_code < 600:
        http_error_msg = (
            f"{resp.status_code} Server Error: {reason} for url: {resp.url}"
        )

    if http_error_msg:
        raise NetworkConnectionError(http_error_msg, response=resp)


def response_chunks(
    response: Response, chunk_size: int = DOWNLOAD_CHUNK_SIZE
) -> Generator[bytes, None, None]:
    """Given a requests Response, provide the data chunks."""
    try:
        # Special case for urllib3.
        for chunk in response.raw.stream(
            chunk_size,
            # We use decode_content=False here because we don't
            # want urllib3 to mess with the raw bytes we get
            # from the server. If we decompress inside of
            # urllib3 then we cannot verify the checksum
            # because the checksum will be of the compressed
            # file. This breakage will only occur if the
            # server adds a Content-Encoding header, which
            # depends on how the server was configured:
            # - Some servers will notice that the file isn't a
            #   compressible file and will leave the file alone
            #   and with an empty Content-Encoding
            # - Some servers will notice that the file is
            #   already compressed and will leave the file
            #   alone and will add a Content-Encoding: gzip
            #   header
            # - Some servers won't notice anything at all and
            #   will take a file that's already been compressed
            #   and compress it again and set the
            #   Content-Encoding: gzip header
            #
            # By setting this not to decode automatically we
            # hope to eliminate problems with the second case.
            decode_content=False,
        ):
            yield chunk
    except AttributeError:
        # Standard file-like object.
        while True:
            chunk = response.raw.read(chunk_size)
            if not chunk:
                break
            yield chunk


def _parse_timeout(timeout: TimeoutValue, kind: Literal["connect", "read"]) -> float:
    connect_timeout: float | None
    read_timeout: float | None
    if isinstance(timeout, tuple):
        connect_timeout, read_timeout = timeout
    elif isinstance(timeout, urllib3.util.Timeout):
        connect_timeout = cast(float | None, timeout.connect_timeout)
        try:
            read_timeout = timeout.read_timeout
        except TimeoutStateError:
            read_timeout = None
    else:
        connect_timeout = read_timeout = timeout

    if kind == "connect":
        assert connect_timeout is not None
        return connect_timeout
    else:
        assert read_timeout is not None
        return read_timeout


def _raise_timeout_error(
    reason: urllib3.exceptions.TimeoutError,
    url: str,
    host: str,
    timeout: TimeoutValue,
) -> NoReturn:
    if isinstance(reason, urllib3.exceptions.ConnectTimeoutError):
        raise ConnectionTimeoutError(
            url, host, kind="connect", timeout=_parse_timeout(timeout, "connect")
        )
    else:
        raise ConnectionTimeoutError(
            url, host, kind="read", timeout=_parse_timeout(timeout, "read")
        )


def raise_connection_error(
    error: requests.ConnectionError | requests.Timeout,
    *,
    url: str,
    timeout: TimeoutValue,
) -> NoReturn:
    """Raise a specific error for a given connection error, if possible.

    Note: requests.ConnectionError is the parent class of
          requests.ProxyError, requests.SSLError, and requests.ConnectTimeout
          so these errors are also handled here.
    """
    url = redact_auth_from_url(url)
    raw_hostname = urlsplit(url).hostname or urlsplit(url).netloc
    reason = error.args[0] if error.args else error

    # NewConnectionError is a subclass of TimeoutError for some reason...
    if isinstance(reason, urllib3.exceptions.TimeoutError) and not isinstance(
        reason, urllib3.exceptions.NewConnectionError
    ):
        # A bare timeout error can occur during non-streamed responses. Don't
        # ask me how.
        _raise_timeout_error(reason, url, raw_hostname, timeout)
    if isinstance(reason, urllib3.exceptions.SSLError):
        # A bare SSL error can occur during non-streamed responses, after the
        # initial connection and TLS handshake have completed.
        raise SSLVerificationError(url, raw_hostname, reason)

    # At this point, all errors should be wrapped in MaxRetryError.
    if not isinstance(reason, urllib3.exceptions.MaxRetryError):
        raise ConnectionFailedError(url, raw_hostname, reason)

    max_retry_error = reason
    assert isinstance(max_retry_error.pool, urllib3.connectionpool.HTTPConnectionPool)
    host = max_retry_error.pool.host
    proxy = max_retry_error.pool.proxy
    # Narrow the reason further to the specific error from the last retry.
    reason = max_retry_error.reason

    if isinstance(reason, urllib3.exceptions.SSLError):
        raise SSLVerificationError(url, host, reason)
    if isinstance(reason, urllib3.exceptions.TimeoutError) and not isinstance(
        reason, urllib3.exceptions.NewConnectionError
    ):
        _raise_timeout_error(reason, url, host, timeout)
    if isinstance(reason, urllib3.exceptions.ProxyError):
        assert proxy is not None
        raise ProxyConnectionError(url, redact_auth_from_url(str(proxy)), reason)

    # Unknown error, give up and raise a generic error.
    raise ConnectionFailedError(
        url, host, reason if isinstance(reason, Exception) else max_retry_error
    )
