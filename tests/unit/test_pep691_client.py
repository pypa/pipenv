"""Full-coverage tests for :class:`pipenv.resolver.pep691.PEP691Client`
(Initiative G phase 1, T13).

Scope: every public + private code path of ``PEP691Client``:

* Status dispatch — 200 (JSON / HTML / unknown CT / missing CT / malformed
  JSON), 304, 404, 401, 403, 5xx, urllib3 exception, OSError.
* Auth dispatch — URL-embedded creds (raw + URL-encoded), netrc fallback,
  no creds.
* Header construction — ``Accept`` always present, ``Cache-Control``
  deliberately absent, ``If-None-Match`` only when caller supplies one.
* URL composition — credential stripping, PEP 503 canonical-name
  segment, trailing-slash idempotency, custom index hosts.
* Edge cases — ``release_conn`` exception swallowed; constructor stores
  ``cert`` / ``verify`` (Phase-3 per-request threading deferred).

The parser surface is owned by T12 (``test_pep691_parser.py``); this file
confines itself to the HTTP wrapper.

T8 contract pinning (where the brief leaves wiggle room):

* ``Cache-Control: max-age=0`` is **never** sent (deliberate divergence
  from pip — freshness is the cache layer's job).
* A 304 response carries the **caller's** ``if_none_match`` forward as
  the ``etag`` field, **not** any ``ETag`` header the server may echo
  (RFC 7232 §4.1 servers vary; the caller-supplied value is canonical).
* On a 200 with a missing / blank ``Content-Type`` header the client
  returns ``FetchError(kind="transient", ...)`` — we do NOT silently
  default to HTML.
* ``release_conn`` failures are swallowed (try/except inside the
  ``finally``) so a pool-release glitch cannot mask the parsed result.
* ``cert`` and ``verify`` are stored on the instance for forward-compat
  but the active session is the source of truth for TLS material; a
  Phase-3 ``Session`` rewrite will thread them per-request.
"""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipenv.patched.pip._vendor.urllib3 import exceptions as urllib3_exceptions
from pipenv.resolver.pep691 import PEP691Client
from pipenv.resolver.pep691_types import FetchError, SimplePageResponse

FIXTURES_JSON = Path(__file__).parent / "fixtures" / "pep691"
FIXTURES_HTML = Path(__file__).parent / "fixtures" / "pep503"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    *,
    status: int = 200,
    data: bytes = b"",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a urllib3-response-shaped mock with controllable status/data/headers."""

    response = MagicMock()
    response.status = status
    response.data = data
    response.headers = headers if headers is not None else {}
    response.release_conn = MagicMock(return_value=None)
    return response


def _make_session(response: MagicMock | None = None) -> MagicMock:
    """Build a urllib3-session-shaped mock returning ``response`` on request()."""

    session = MagicMock()
    if response is not None:
        session.request.return_value = response
    return session


def _last_call_kwargs(session: MagicMock) -> dict:
    return session.request.call_args.kwargs


def _last_call_args(session: MagicMock) -> tuple:
    return session.request.call_args.args


def _outgoing_url(session: MagicMock) -> str:
    # ``request("GET", target_url, headers=, timeout=)`` — positional[1].
    args = _last_call_args(session)
    return args[1]


def _outgoing_headers(session: MagicMock) -> dict:
    return _last_call_kwargs(session)["headers"]


# ---------------------------------------------------------------------------
# Status dispatch — happy paths
# ---------------------------------------------------------------------------


class TestStatusDispatch200JSON:
    """200 + ``application/vnd.pypi.simple.v1+json`` → JSON parser → fresh."""

    def test_200_json_six_fixture(self):
        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={
                "Content-Type": "application/vnd.pypi.simple.v1+json",
                "ETag": '"abc"',
                "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
            },
        )
        session = _make_session(response)

        client = PEP691Client(session)
        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "fresh"
        # T12 pinned: six.json yields 48 candidates.
        assert len(result.candidates) == 48
        assert result.etag == '"abc"'
        assert result.last_modified == "Wed, 01 Jan 2025 00:00:00 GMT"
        assert result.raw_meta.get("content_type") == (
            "application/vnd.pypi.simple.v1+json"
        )

    def test_200_json_with_charset_suffix(self):
        """Content-Type with a ``; charset=utf-8`` suffix is still JSON."""

        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={
                "Content-Type": (
                    "application/vnd.pypi.simple.v1+json; charset=utf-8"
                ),
            },
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "fresh"
        assert len(result.candidates) == 48

    def test_200_json_uppercase_content_type(self):
        """Content-Type matching is case-insensitive."""

        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "Application/VND.PyPI.Simple.V1+JSON"},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert len(result.candidates) == 48

    def test_200_json_no_etag_or_last_modified(self):
        """ETag / Last-Modified absent → fields are None, status still fresh."""

        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.etag is None
        assert result.last_modified is None


class TestStatusDispatch200HTML:
    """200 + HTML content-types → HTML parser → fresh."""

    def test_200_html_text_html(self):
        body = (FIXTURES_HTML / "six.html").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "fresh"
        # HTML serialisation count may differ slightly from JSON; the
        # contract is "at least a meaningful number of candidates", and
        # all carry a name/version/url.
        assert len(result.candidates) > 0
        for c in result.candidates:
            assert c.name
            assert c.version
            assert c.url.startswith("https://")

    def test_200_pep691_html_content_type(self):
        """``application/vnd.pypi.simple.v1+html`` dispatches to the HTML parser."""

        body = (FIXTURES_HTML / "six.html").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={
                "Content-Type": "application/vnd.pypi.simple.v1+html",
            },
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "fresh"
        assert len(result.candidates) > 0


class TestStatusDispatch200UnknownContentType:
    """200 with a CT we don't understand → transient FetchError."""

    def test_200_application_json_treated_as_unknown(self):
        response = _make_response(
            status=200,
            data=b'{"meta": {}, "name": "six", "files": []}',
            headers={"Content-Type": "application/json"},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert "content-type" in result.message.lower()
        assert "application/json" in result.message
        assert result.original is None

    def test_200_missing_content_type_header(self):
        """No CT header at all → unknown-CT branch; safe transient error."""

        response = _make_response(status=200, data=b"<html/>", headers={})
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert "content-type" in result.message.lower()

    def test_200_empty_content_type(self):
        """CT present but empty string → unknown-CT branch."""

        response = _make_response(
            status=200,
            data=b"",
            headers={"Content-Type": ""},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"

    def test_200_garbage_json_body_is_transient(self):
        """200 + JSON CT + non-JSON body → mirror-mid-deploy → transient."""

        response = _make_response(
            status=200,
            data=b"<<not json at all>>",
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert result.original is not None
        assert "malformed JSON" in result.message

    def test_200_json_with_none_body(self):
        """``response.data is None`` is normalised to empty bytes."""

        response = _make_response(
            status=200,
            data=None,
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        # Empty bytes → JSON parser raises ValueError → transient.
        assert isinstance(result, FetchError)
        assert result.kind == "transient"


# ---------------------------------------------------------------------------
# Status dispatch — non-200
# ---------------------------------------------------------------------------


class TestStatusDispatchNon200:
    def test_304_not_modified_carries_if_none_match(self):
        response = _make_response(
            status=304,
            data=b"",
            headers={"ETag": '"server-side-value"'},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch(
            "https://pypi.org/simple/", "six", if_none_match='"abc"'
        )

        assert isinstance(result, SimplePageResponse)
        assert result.status == "not-modified"
        # T8 contract: 304 carries the *caller's* ETag, not the server's.
        assert result.etag == '"abc"'
        assert result.candidates == ()
        assert result.last_modified is None

    def test_304_without_if_none_match_carries_none(self):
        """A 304 without a caller ETag is unusual but legal; etag becomes None."""

        response = _make_response(status=304)
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "not-modified"
        assert result.etag is None

    def test_404_missing(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "definitely-not-a-package")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "missing"
        assert result.candidates == ()
        assert result.etag is None
        assert result.last_modified is None

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failures(self, status):
        response = _make_response(status=status)
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "auth"
        assert str(status) in result.message
        assert result.original is None

    @pytest.mark.parametrize("status", [400, 408, 410, 418, 429, 500, 502, 503, 504])
    def test_transient_status_codes(self, status):
        response = _make_response(status=status)
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert str(status) in result.message
        assert result.original is None


# ---------------------------------------------------------------------------
# Network-level exceptions
# ---------------------------------------------------------------------------


class TestNetworkExceptions:
    def test_max_retry_error(self):
        session = _make_session()
        exc = urllib3_exceptions.MaxRetryError(
            pool=MagicMock(), url="https://pypi.org/simple/six/", reason=None
        )
        session.request.side_effect = exc

        client = PEP691Client(session)
        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert result.original is exc

    def test_protocol_error(self):
        session = _make_session()
        exc = urllib3_exceptions.ProtocolError("connection broken")
        session.request.side_effect = exc

        client = PEP691Client(session)
        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert result.original is exc

    def test_timeout_error(self):
        session = _make_session()
        exc = urllib3_exceptions.TimeoutError("read timed out")
        session.request.side_effect = exc

        client = PEP691Client(session)
        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert result.original is exc

    def test_ssl_error(self):
        session = _make_session()
        exc = urllib3_exceptions.SSLError("bad cert")
        session.request.side_effect = exc

        client = PEP691Client(session)
        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert result.original is exc

    def test_oserror_is_transient(self):
        """Low-level socket errors not yet wrapped by urllib3 → transient."""

        session = _make_session()
        exc = OSError("network unreachable")
        session.request.side_effect = exc

        client = PEP691Client(session)
        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "transient"
        assert result.original is exc


# ---------------------------------------------------------------------------
# Auth dispatch
# ---------------------------------------------------------------------------


class TestAuthDispatch:
    def test_url_embedded_credentials_stripped_and_basic_auth_set(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://user:pass@host.example/simple", "six")

        url = _outgoing_url(session)
        assert "user" not in url
        assert "pass" not in url
        assert url == "https://host.example/simple/six/"

        headers = _outgoing_headers(session)
        expected = "Basic " + base64.b64encode(b"user:pass").decode("ascii")
        assert headers["Authorization"] == expected

    def test_url_encoded_credentials_are_decoded_before_b64(self):
        """``%40`` → ``@``, ``%23`` → ``#`` before basic-auth encoding."""

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://u%40e:p%23ass@host.example/simple", "six")

        headers = _outgoing_headers(session)
        expected = "Basic " + base64.b64encode(b"u@e:p#ass").decode("ascii")
        assert headers["Authorization"] == expected

    def test_netrc_fallback_when_no_url_creds(self, monkeypatch):
        response = _make_response(status=404)
        session = _make_session(response)

        def fake_lookup(host, path):
            assert host == "host.example"
            return ("login", "password")

        # Patch the symbol where the module under test imported it.
        monkeypatch.setattr(
            "pipenv.resolver.pep691.lookup_netrc_auth", fake_lookup
        )

        client = PEP691Client(session)
        client.fetch("https://host.example/simple", "six")

        headers = _outgoing_headers(session)
        expected = "Basic " + base64.b64encode(b"login:password").decode("ascii")
        assert headers["Authorization"] == expected

    def test_no_url_creds_no_netrc_no_auth_header(self, monkeypatch):
        response = _make_response(status=404)
        session = _make_session(response)

        monkeypatch.setattr(
            "pipenv.resolver.pep691.lookup_netrc_auth",
            lambda host, path: None,
        )

        client = PEP691Client(session)
        client.fetch("https://host.example/simple", "six")

        headers = _outgoing_headers(session)
        assert "Authorization" not in headers

    def test_url_creds_win_over_netrc(self, monkeypatch):
        """URL-embedded creds beat netrc even when both are present."""

        response = _make_response(status=404)
        session = _make_session(response)

        # If this fires we'd see ``netrcuser`` in the header.
        monkeypatch.setattr(
            "pipenv.resolver.pep691.lookup_netrc_auth",
            lambda host, path: ("netrcuser", "netrcpw"),
        )

        client = PEP691Client(session)
        client.fetch("https://urluser:urlpw@host.example/simple", "six")

        headers = _outgoing_headers(session)
        expected = "Basic " + base64.b64encode(b"urluser:urlpw").decode("ascii")
        assert headers["Authorization"] == expected

    def test_netrc_path_threaded_through(self, monkeypatch):
        """Explicit ``netrc_path`` reaches ``lookup_netrc_auth``."""

        response = _make_response(status=404)
        session = _make_session(response)

        captured: dict = {}

        def fake_lookup(host, path):
            captured["host"] = host
            captured["path"] = path
            return None

        monkeypatch.setattr(
            "pipenv.resolver.pep691.lookup_netrc_auth", fake_lookup
        )

        client = PEP691Client(session, netrc_path="/tmp/my-netrc")
        client.fetch("https://host.example/simple", "six")

        assert captured == {"host": "host.example", "path": "/tmp/my-netrc"}


# ---------------------------------------------------------------------------
# Constructor — cert / verify / env
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_cert_arg_stored_on_instance(self):
        """``cert`` kwarg is captured for future per-request use."""

        session = _make_session()
        client = PEP691Client(session, cert=("/p/cert.pem", "/p/key.pem"))

        assert client._cert == ("/p/cert.pem", "/p/key.pem")

    def test_cert_falls_back_to_pip_client_cert_env(self, monkeypatch):
        """``cert=None`` consults ``$PIP_CLIENT_CERT`` at construction time."""

        monkeypatch.setenv("PIP_CLIENT_CERT", "/p/from-env.pem")
        session = _make_session()

        client = PEP691Client(session)

        # auth.client_cert_from_env returns (value, value) for a single path.
        assert client._cert == ("/p/from-env.pem", "/p/from-env.pem")

    def test_cert_env_unset_yields_none(self, monkeypatch):
        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)
        session = _make_session()

        client = PEP691Client(session)

        assert client._cert is None

    def test_verify_true_default(self):
        session = _make_session()
        client = PEP691Client(session)

        assert client._verify is True

    def test_verify_false_stored(self):
        session = _make_session()
        client = PEP691Client(session, verify=False)

        assert client._verify is False

    def test_session_stored(self):
        session = _make_session()
        client = PEP691Client(session)

        assert client._session is session


# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------


class TestOutgoingHeaders:
    _EXPECTED_ACCEPT = (
        "application/vnd.pypi.simple.v1+json, "
        "application/vnd.pypi.simple.v1+html; q=0.1, "
        "text/html; q=0.01"
    )

    def test_accept_header_always_set(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        headers = _outgoing_headers(session)
        assert headers["Accept"] == self._EXPECTED_ACCEPT

    def test_cache_control_never_sent(self):
        """Deliberate divergence from pip — see T8 docstring."""

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        headers = _outgoing_headers(session)
        assert "Cache-Control" not in headers
        assert "cache-control" not in headers

    def test_if_none_match_absent_when_caller_omits(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        headers = _outgoing_headers(session)
        assert "If-None-Match" not in headers

    def test_if_none_match_present_when_caller_supplies(self):
        response = _make_response(status=304)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch(
            "https://pypi.org/simple/", "six", if_none_match='"abc"'
        )

        headers = _outgoing_headers(session)
        assert headers["If-None-Match"] == '"abc"'

    def test_timeout_threaded(self):
        """``urllib3.Timeout`` with the documented connect/read values."""

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        timeout = _last_call_kwargs(session)["timeout"]
        # The exact wrapper type is urllib3.Timeout; we only assert the
        # connect/read values to keep the test resilient to internal
        # urllib3 wrapping changes.
        assert timeout.connect_timeout == 10.0
        # Read timeout exposes the value via ``read_timeout`` property
        # (constant) or ``_read`` attribute depending on version.
        read = getattr(timeout, "read_timeout", None)
        if read is None or callable(read):
            read = getattr(timeout, "_read", None)
        assert read == 30.0


# ---------------------------------------------------------------------------
# URL composition
# ---------------------------------------------------------------------------


class TestCanonicalNameAndURLComposition:
    @pytest.mark.parametrize(
        "raw_name,canonical_segment",
        [
            ("Django", "django"),
            ("python_dateutil", "python-dateutil"),
            ("Flask.ext.SQLAlchemy", "flask-ext-sqlalchemy"),
            ("SIX", "six"),
        ],
    )
    def test_canonical_name_in_outgoing_url(self, raw_name, canonical_segment):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", raw_name)

        url = _outgoing_url(session)
        assert url.endswith(f"/{canonical_segment}/")

    def test_trailing_slash_idempotent(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")
        url = _outgoing_url(session)

        assert url == "https://pypi.org/simple/six/"
        assert "//six/" not in url

    def test_no_trailing_slash_on_index_url(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple", "six")
        url = _outgoing_url(session)

        assert url == "https://pypi.org/simple/six/"

    def test_custom_index_host_preserved(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch(
            "https://nexus.example.com/repository/pypi/simple/", "six"
        )
        url = _outgoing_url(session)

        assert url == "https://nexus.example.com/repository/pypi/simple/six/"

    def test_get_method_used(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        method = _last_call_args(session)[0]
        assert method == "GET"


# ---------------------------------------------------------------------------
# Connection hygiene
# ---------------------------------------------------------------------------


class TestReleaseConn:
    def test_release_conn_invoked_on_success(self):
        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        )
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        response.release_conn.assert_called_once()

    def test_release_conn_invoked_on_404(self):
        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        response.release_conn.assert_called_once()

    def test_release_conn_failure_does_not_mask_result(self):
        """T8: a ``release_conn`` exception is swallowed; result wins."""

        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        )
        response.release_conn = MagicMock(side_effect=RuntimeError("pool gone"))
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "fresh"
        assert len(result.candidates) == 48
        response.release_conn.assert_called_once()

    def test_release_conn_missing_is_safe(self):
        """A response object without ``release_conn`` is tolerated."""

        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        )
        # ``del`` on a MagicMock attribute makes ``getattr(..., None)``
        # return ``None`` rather than auto-creating a new MagicMock.
        del response.release_conn
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "fresh"


# ---------------------------------------------------------------------------
# Header-getter edge case (covers the case-insensitive fallback path)
# ---------------------------------------------------------------------------


class TestHeaderGetterFallback:
    def test_etag_via_lowercase_key_in_plain_dict(self):
        """``_get_header`` falls back to case-folded scan for plain dicts."""

        body = (FIXTURES_JSON / "six.json").read_bytes()
        # Plain dicts are case-sensitive; the lowercase ``etag`` key
        # forces the case-folded fallback path inside ``_get_header``.
        response = _make_response(
            status=200,
            data=body,
            headers={
                "content-type": "application/vnd.pypi.simple.v1+json",
                "etag": '"weird-case"',
            },
        )
        session = _make_session(response)
        client = PEP691Client(session)

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.etag == '"weird-case"'

    def test_headers_none_safe(self):
        """A response with ``headers=None`` returns ``None`` for every lookup."""

        from pipenv.resolver.pep691 import _get_header

        assert _get_header(None, "Content-Type") is None

    def test_headers_get_raises_falls_back_to_items(self):
        """If ``headers.get`` raises, the items() scan still finds the value."""

        from pipenv.resolver.pep691 import _get_header

        class WeirdHeaders:
            def get(self, name):  # noqa: ARG002
                raise RuntimeError("boom")

            def items(self):
                return [("ETag", '"value"')]

        assert _get_header(WeirdHeaders(), "ETag") == '"value"'

    def test_headers_items_raises_returns_none(self):
        """If both ``.get`` and ``.items`` raise, fall back to None."""

        from pipenv.resolver.pep691 import _get_header

        class BadHeaders:
            def get(self, name):  # noqa: ARG002
                raise RuntimeError("boom")

            def items(self):
                raise RuntimeError("also boom")

        assert _get_header(BadHeaders(), "ETag") is None

    def test_headers_get_returns_none_then_items_finds_value(self):
        """``.get`` returns None → items() fallback finds case-folded match."""

        from pipenv.resolver.pep691 import _get_header

        class NoGetHeaders:
            def get(self, name):  # noqa: ARG002
                return None

            def items(self):
                return [("ETAG", '"val"')]

        assert _get_header(NoGetHeaders(), "ETag") == '"val"'

    def test_headers_get_returns_none_items_no_match(self):
        """``.get`` None + items has no match → returns None."""

        from pipenv.resolver.pep691 import _get_header

        class EmptyHeaders:
            def get(self, name):  # noqa: ARG002
                return None

            def items(self):
                return [("X-Other", "1")]

        assert _get_header(EmptyHeaders(), "ETag") is None


# ---------------------------------------------------------------------------
# Auth helper edge cases — LocationParseError + empty-host fallback
# ---------------------------------------------------------------------------


class TestAuthHelperEdgeCases:
    def test_unparseable_host_yields_no_auth_header(self, monkeypatch):
        """``urllib3.util.parse_url`` raising LocationParseError → no auth.

        Constructed by stubbing ``parse_url`` itself: an invalid URL would
        normally be rejected earlier in ``extract_url_credentials``, so we
        force the failure mode the defensive try/except guards against.
        """

        import pipenv.resolver.pep691 as mod

        def raise_locationparse(url):  # noqa: ARG001
            raise urllib3_exceptions.LocationParseError("nope")

        # Patch urllib3.util.parse_url as the client sees it.
        monkeypatch.setattr(mod.urllib3.util, "parse_url", raise_locationparse)
        # Make sure netrc lookup never produces auth in this scenario.
        monkeypatch.setattr(mod, "lookup_netrc_auth", lambda host, path: None)

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://host.example/simple", "six")

        headers = _outgoing_headers(session)
        assert "Authorization" not in headers

    def test_parsed_url_with_empty_host_yields_no_auth(self, monkeypatch):
        """``parse_url().host is None/""`` short-circuits before netrc lookup."""

        import pipenv.resolver.pep691 as mod

        class FakeParsed:
            host = None

        monkeypatch.setattr(
            mod.urllib3.util, "parse_url", lambda url: FakeParsed()
        )
        # ``lookup_netrc_auth`` MUST NOT be reached — if it is, this test
        # would have to also stub it; assert via call counter below.
        sentinel = MagicMock(return_value=("login", "password"))
        monkeypatch.setattr(mod, "lookup_netrc_auth", sentinel)

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://host.example/simple", "six")

        headers = _outgoing_headers(session)
        assert "Authorization" not in headers
        sentinel.assert_not_called()


# ---------------------------------------------------------------------------
# Per-request TLS material threading (FU3 — Phase-3 follow-up #3)
# ---------------------------------------------------------------------------


class TestPerRequestTLSMaterial:
    """``PEP691Client.fetch`` threads ``verify`` and ``cert`` per-request.

    T8 stored ``self._verify`` / ``self._cert`` on the instance but the
    Phase-1 ``fetch`` did not thread them into ``session.request(...)``.
    Real production sessions are :class:`PipSession` (a
    :class:`requests.Session` subclass via cachecontrol) which honours
    per-request ``verify=`` and ``cert=``; T8's docstring deferred this
    threading to a Phase-3 follow-up and this class pins the new contract.
    """

    def test_default_constructor_threads_verify_true_cert_none(self):
        """Plain ``PEP691Client(session)`` → ``verify=True, cert=None`` on call."""

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session)

        client.fetch("https://pypi.org/simple/", "six")

        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is True
        assert kwargs["cert"] is None

    def test_verify_false_threaded(self):
        """``verify=False`` propagates through to the session.request call."""

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(session, verify=False)

        client.fetch("https://pypi.org/simple/", "six")

        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is False
        assert kwargs["cert"] is None

    def test_cert_pair_threaded(self, monkeypatch):
        """``cert=(cert_path, key_path)`` propagates through verbatim."""

        # Clear the env so client_cert_from_env doesn't shadow the explicit pair.
        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(
            session, cert=("/path/to/cert.pem", "/path/to/key.pem")
        )

        client.fetch("https://pypi.org/simple/", "six")

        kwargs = _last_call_kwargs(session)
        assert kwargs["cert"] == ("/path/to/cert.pem", "/path/to/key.pem")
        assert kwargs["verify"] is True

    def test_verify_and_cert_both_threaded_simultaneously(self, monkeypatch):
        """Both knobs land on the same call."""

        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(
            session,
            verify=False,
            cert=("/a/cert.pem", "/a/key.pem"),
        )

        client.fetch("https://pypi.org/simple/", "six")

        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is False
        assert kwargs["cert"] == ("/a/cert.pem", "/a/key.pem")

    def test_tls_material_threaded_on_200_json(self, monkeypatch):
        """A 200 JSON response path still threads verify/cert through."""

        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        body = (FIXTURES_JSON / "six.json").read_bytes()
        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        )
        session = _make_session(response)
        client = PEP691Client(
            session, verify=False, cert=("/c.pem", "/k.pem")
        )

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "fresh"
        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is False
        assert kwargs["cert"] == ("/c.pem", "/k.pem")

    def test_tls_material_threaded_on_304(self, monkeypatch):
        """A 304 not-modified path still threads verify/cert through."""

        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        response = _make_response(status=304)
        session = _make_session(response)
        client = PEP691Client(
            session, verify=False, cert=("/c.pem", "/k.pem")
        )

        result = client.fetch(
            "https://pypi.org/simple/", "six", if_none_match='"abc"'
        )

        assert isinstance(result, SimplePageResponse)
        assert result.status == "not-modified"
        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is False
        assert kwargs["cert"] == ("/c.pem", "/k.pem")

    def test_tls_material_threaded_on_404(self, monkeypatch):
        """A 404 missing path still threads verify/cert through."""

        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(
            session, verify=False, cert=("/c.pem", "/k.pem")
        )

        result = client.fetch("https://pypi.org/simple/", "nope")

        assert isinstance(result, SimplePageResponse)
        assert result.status == "missing"
        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is False
        assert kwargs["cert"] == ("/c.pem", "/k.pem")

    def test_tls_material_threaded_on_401(self, monkeypatch):
        """A 401 auth-failure path still threads verify/cert through.

        Status branching is *post-request* — the call itself always
        carries TLS material regardless of status outcome.
        """

        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        response = _make_response(status=401)
        session = _make_session(response)
        client = PEP691Client(
            session, verify=False, cert=("/c.pem", "/k.pem")
        )

        result = client.fetch("https://pypi.org/simple/", "six")

        assert isinstance(result, FetchError)
        assert result.kind == "auth"
        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is False
        assert kwargs["cert"] == ("/c.pem", "/k.pem")

    def test_if_none_match_does_not_affect_tls_kwargs(self, monkeypatch):
        """``if_none_match`` and TLS kwargs are orthogonal — passing one
        does not perturb the other on the outgoing request."""

        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(
            session, verify=False, cert=("/c.pem", "/k.pem")
        )

        client.fetch(
            "https://pypi.org/simple/", "six", if_none_match='"etag-x"'
        )

        kwargs = _last_call_kwargs(session)
        # TLS knobs land independently of the conditional GET header.
        assert kwargs["verify"] is False
        assert kwargs["cert"] == ("/c.pem", "/k.pem")
        # And the conditional header is still set on the request.
        assert kwargs["headers"].get("If-None-Match") == '"etag-x"'

    def test_tls_kwargs_independent_of_if_none_match_absent(self, monkeypatch):
        """No ``if_none_match`` still threads TLS kwargs unchanged."""

        monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)

        response = _make_response(status=404)
        session = _make_session(response)
        client = PEP691Client(
            session, verify=False, cert=("/c.pem", "/k.pem")
        )

        client.fetch("https://pypi.org/simple/", "six")

        kwargs = _last_call_kwargs(session)
        assert kwargs["verify"] is False
        assert kwargs["cert"] == ("/c.pem", "/k.pem")
        # No conditional-GET header was added.
        assert "If-None-Match" not in kwargs["headers"]
