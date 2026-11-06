"""Network-related pip exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pipenv.patched.pip._vendor.rich.markup import escape
from pipenv.patched.pip._vendor.rich.text import Text

from pipenv.patched.pip._internal.exceptions._base import DiagnosticPipError, PipError

if TYPE_CHECKING:
    from pipenv.patched.pip._vendor import urllib3
    from pipenv.patched.pip._vendor.requests.models import PreparedRequest, Request, Response

    from pipenv.patched.pip._internal.network.download import _FileDownload


class NetworkConnectionError(PipError):
    """HTTP connection error"""

    def __init__(
        self,
        error_msg: str,
        response: Response | None = None,
        request: Request | PreparedRequest | None = None,
    ) -> None:
        """
        Initialize NetworkConnectionError with  `request` and `response`
        objects.
        """
        self.response = response
        self.request = request
        self.error_msg = error_msg
        if (
            self.response is not None
            and not self.request
            and hasattr(response, "request")
        ):
            self.request = self.response.request
        super().__init__(error_msg, response, request)

    def __str__(self) -> str:
        return str(self.error_msg)


class ConnectionFailedError(DiagnosticPipError):
    reference = "connection-failed"

    def __init__(self, url: str, host: str, error: Exception) -> None:
        from http.client import RemoteDisconnected

        from pipenv.patched.pip._vendor.urllib3.exceptions import (
            NameResolutionError,
            NewConnectionError,
            ProtocolError,
        )

        details = str(error)
        if isinstance(error, NameResolutionError):
            parts = details.split("Failed to resolve ", maxsplit=1)
            if len(parts) == 2:
                details = "Failed to resolve IP address for " + parts[1]
        elif isinstance(error, NewConnectionError):
            parts = details.split("Failed to establish a new connection: ", maxsplit=1)
            if len(parts) == 2:
                _, details = parts
        elif isinstance(error, ProtocolError):
            try:
                reason = error.args[1]
            except IndexError:
                pass
            else:
                if isinstance(reason, (RemoteDisconnected, ConnectionResetError)):
                    details = (
                        "the connection was closed without a reply from the server."
                    )

        super().__init__(
            message=(
                f"Failed to connect to [magenta]{escape(host)}[/] while fetching "
                f"{escape(url)}"
            ),
            context=Text(details),
            hint_stmt=(
                "Are you connected to the Internet? If so, check whether your system "
                f"can connect to [magenta]{escape(host)}[/] before trying again. "
                "There may be a firewall or proxy that's preventing the connection."
            ),
        )


class ConnectionTimeoutError(DiagnosticPipError):
    reference = "connection-timeout"

    def __init__(
        self,
        url: str,
        host: str,
        *,
        kind: Literal["connect", "read"],
        timeout: float,
    ) -> None:
        context = Text.assemble(
            (host, "magenta"), f" didn't respond within {timeout} seconds"
        )
        if kind == "connect":
            context.append(" (while establishing a connection)")
        super().__init__(
            message=f"Unable to fetch {escape(url)}",
            context=context,
            hint_stmt=(
                "This is probably a temporary issue with the remote server or the "
                "network connection. If this error persists, check the network "
                "configuration. There may be a firewall or proxy that's preventing "
                "the connection."
            ),
        )


class SSLMissingError(DiagnosticPipError):
    reference = "ssl-missing"

    def __init__(self, url: str) -> None:
        super().__init__(
            message=f"Failed to establish a secure connection for {escape(url)}",
            context="The 'ssl' module is unavailable but required for HTTPS URLs",
            hint_stmt=None,
        )


class SSLVerificationError(DiagnosticPipError):
    reference = "ssl-verification-failed"

    def __init__(self, url: str, host: str, error: urllib3.exceptions.SSLError) -> None:
        message = (
            "Failed to establish a secure connection to "
            f"[magenta]{escape(host)}[/] while fetching {escape(url)}"
        )
        hint = "You may need to use --cert or check your proxy/firewall configuration"
        super().__init__(message=message, context=Text(str(error)), hint_stmt=hint)


class ProxyConnectionError(DiagnosticPipError):
    reference = "proxy-connection-failed"

    def __init__(
        self, url: str, proxy: str, error: urllib3.exceptions.ProxyError
    ) -> None:
        super().__init__(
            message=(
                "Failed to connect to proxy "
                f"[magenta]{escape(proxy)}[/] while fetching {escape(url)}"
            ),
            context=Text(str(error)),
            hint_stmt="This is likely a proxy configuration issue.",
        )


class IncompleteDownloadError(DiagnosticPipError):
    """Raised when the downloader receives fewer bytes than advertised
    in the Content-Length header."""

    reference = "incomplete-download"

    def __init__(self, download: _FileDownload) -> None:
        # Dodge circular import.
        from pipenv.patched.pip._internal.utils.misc import format_size

        assert download.size is not None
        download_status = (
            f"{format_size(download.bytes_received)}/{format_size(download.size)}"
        )
        if download.reattempts:
            retry_status = f"after {download.reattempts + 1} attempts "
            hint = "Use --resume-retries to configure resume attempt limit."
        else:
            # Download retrying is not enabled.
            retry_status = ""
            hint = "Consider using --resume-retries to enable download resumption."
        message = Text(
            f"Download failed {retry_status}because not enough bytes "
            f"were received ({download_status})"
        )

        super().__init__(
            message=message,
            context=f"URL: {download.link.redacted_url}",
            hint_stmt=hint,
            note_stmt="This is an issue with network connectivity, not pip.",
        )
