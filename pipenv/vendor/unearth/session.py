from __future__ import annotations

import email.utils
import io
import ipaddress
import logging
import mimetypes
import os
import warnings
from pathlib import Path
from typing import Any, Iterable, cast

from pipenv.patched.pip._vendor.requests import adapters
import pipenv.patched.pip._vendor.urllib3 as urllib3
from pipenv.patched.pip._vendor.requests import Session
from pipenv.patched.pip._vendor.requests.models import PreparedRequest, Response

from pipenv.vendor.unearth.auth import MultiDomainBasicAuth
from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.utils import build_url_from_netloc, parse_netloc

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 5
DEFAULT_SECURE_ORIGINS = [
    ("https", "*", "*"),
    ("wss", "*", "*"),
    ("*", "localhost", "*"),
    ("*", "127.0.0.0/8", "*"),
    ("*", "::1/128", "*"),
    ("file", "*", "*"),
]


def _compare_origin_part(allowed: str, actual: str) -> bool:
    return allowed == "*" or allowed == actual


class InsecureMixin:
    def cert_verify(self, conn, url, verify, cert):
        return super().cert_verify(conn, url, verify=False, cert=cert)

    def send(self, request, *args, **kwargs):
        with warnings.catch_warnings():
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            return super().send(request, *args, **kwargs)


class InsecureHTTPAdapter(InsecureMixin, adapters.HTTPAdapter):
    pass


class LocalFSAdapter(adapters.BaseAdapter):
    def send(self, request: PreparedRequest, *args: Any, **kwargs: Any) -> Response:
        link = Link(cast(str, request.url))
        path = link.file_path
        resp = Response()
        resp.status_code = 200
        resp.url = cast(str, request.url)
        resp.request = request

        try:
            stats = os.stat(path)
        except OSError as exc:
            # format the exception raised as a io.BytesIO object,
            # to return a better error message:
            resp.status_code = 404
            resp.reason = type(exc).__name__
            resp.raw = io.BytesIO(f"{resp.reason}: {exc}".encode("utf8"))
        else:
            modified = email.utils.formatdate(stats.st_mtime, usegmt=True)
            content_type = mimetypes.guess_type(path)[0] or "text/plain"
            resp.headers.update(
                {
                    "Content-Type": content_type,
                    "Content-Length": str(stats.st_size),
                    "Last-Modified": modified,
                }
            )

            resp.raw = open(path, "rb")
            resp.close = resp.raw.close  # type: ignore

        return resp

    def close(self) -> None:
        pass


class PyPISession(Session):
    """
    A session with caching enabled and specific hosts trusted.

    Args:
        index_urls: The PyPI index URLs to use.
        retries: The number of retries to attempt.
        trusted_hosts: The hosts to trust.
        ca_certificates: The path to a file where the certificates for
            CAs reside. These are used when verifying the host
            certificates of the index servers. When left unset, the
            default certificates of the requests library will be used.
    """

    #: The adapter class to use for secure connections.
    secure_adapter_cls = adapters.HTTPAdapter
    #: The adapter class to use for insecure connections.
    insecure_adapter_cls = InsecureHTTPAdapter

    def __init__(
        self,
        *,
        index_urls: Iterable[str] = (),
        retries: int = DEFAULT_MAX_RETRIES,
        trusted_hosts: Iterable[str] = (),
        ca_certificates: Path | None = None,
    ) -> None:
        super().__init__()

        retry = urllib3.Retry(
            total=retries,
            # A 500 may indicate transient error in Amazon S3
            # A 520 or 527 - may indicate transient error in CloudFlare
            status_forcelist=[500, 503, 520, 527],
            backoff_factor=0.25,
        )
        self._insecure_adapter = self.insecure_adapter_cls(max_retries=retry)
        secure_adapter = self.secure_adapter_cls(max_retries=retry)

        self.mount("https://", secure_adapter)
        self.mount("http://", self._insecure_adapter)
        self.mount("file://", LocalFSAdapter())

        self._trusted_host_ports: set[tuple[str, int | None]] = set()

        for host in trusted_hosts:
            self.add_trusted_host(host)
        self.auth = MultiDomainBasicAuth(index_urls=index_urls)

        if ca_certificates is not None:
            self.set_ca_certificates(ca_certificates)

    def set_ca_certificates(self, cert_file: Path):
        """
        Set one or multiple certificate authorities which sign the
        server's certs.
        """
        self.verify = str(cert_file)

    def add_trusted_host(self, host: str) -> None:
        """Trust the given host by not verifying the SSL certificate."""
        hostname, port = parse_netloc(host)
        self._trusted_host_ports.add((hostname, port))
        for scheme in ("https", "http"):
            url = build_url_from_netloc(host, scheme=scheme)
            self.mount(url + "/", self._insecure_adapter)
            if port is None:
                # Allow all ports for this host
                self.mount(url + ":", self._insecure_adapter)

    def iter_secure_origins(self) -> Iterable[tuple[str, str, str]]:
        yield from DEFAULT_SECURE_ORIGINS
        for host, port in self._trusted_host_ports:
            yield ("*", host, "*" if port is None else str(port))

    def is_secure_origin(self, location: Link) -> bool:
        """
        Determine if the origin is a trusted host.

        Args:
            location (Link): The location to check.
        """
        _, _, scheme = location.parsed.scheme.rpartition("+")
        host, port = location.parsed.hostname or "", location.parsed.port
        for secure_scheme, secure_host, secure_port in self.iter_secure_origins():
            if not _compare_origin_part(secure_scheme, scheme):
                continue
            try:
                addr = ipaddress.ip_address(host)
                network = ipaddress.ip_network(secure_host)
            except ValueError:
                # Either addr or network is invalid
                if not _compare_origin_part(secure_host, host):
                    continue
            else:
                if addr not in network:
                    continue

            if not _compare_origin_part(
                secure_port, "*" if port is None else str(port)
            ):
                continue
            # We've got here, so all the parts match
            return True

        logger.warning(
            "Skipping %s for not being trusted, please add it to `trusted_hosts` list",
            location.redacted,
        )
        return False
