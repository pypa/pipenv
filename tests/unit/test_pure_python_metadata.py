"""Unit tests for :mod:`pipenv.resolver.pure_python_metadata`
(Initiative G Phase 3, T2).

This file is the RED-phase test suite that pins T2's contract.  T12
extends this file later with the full coverage matrix; the minimum
acceptance gate from the plan brief is:

* PEP 658 fast path with mocked HTTP layer.
* Wheel-head fallback with a ``tmp_path``-built synthetic wheel.
* Cache round-trip.
* Hash-mismatch raises ``MetadataFetchError``.

All tests use a duck-typed session ``MagicMock`` matching the
``urllib3.PoolManager.request`` shape that the rest of
``pipenv.resolver.*`` already uses (see ``pep691.py``).  The fetcher
should call ``session.request("GET", url, headers=, ...)`` or
``session.request("HEAD", url, headers=, ...)``.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipenv.resolver.candidate import Candidate

# Real-world METADATA body (truncated to relevant headers).  Lifted from
# numpy 1.26.0's wheel METADATA.  Lines retain the LF line ending that
# email.parser expects; double-LF ends the header block.
NUMPY_METADATA_TEXT = (
    "Metadata-Version: 2.1\n"
    "Name: numpy\n"
    "Version: 1.26.0\n"
    "Summary: Fundamental package for array computing in Python\n"
    "Home-page: https://numpy.org\n"
    "Requires-Python: <3.13,>=3.9\n"
    "Provides-Extra: test\n"
    "Requires-Dist: hypothesis ; extra == 'test'\n"
    "Requires-Dist: pytest ; extra == 'test'\n"
    "Requires-Dist: pytest-cov ; extra == 'test'\n"
    "\n"
    "NumPy is the fundamental package for...\n"
)


def _make_wheel_candidate(
    name: str = "numpy",
    version: str = "1.26.0",
    *,
    url: str = "https://example.org/wheels/numpy-1.26.0-py3-none-any.whl",
) -> Candidate:
    filename = url.rsplit("/", 1)[-1]
    return Candidate.from_filename(
        filename,
        name=name,
        version=version,
        url=url,
        hashes=frozenset(),
        requires_python=">=3.9",
        yanked=False,
        yanked_reason=None,
        upload_time=None,
    )


def _make_response(
    *,
    status: int = 200,
    data: bytes = b"",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a urllib3-response-shaped mock."""
    response = MagicMock()
    response.status = status
    response.data = data
    response.headers = headers if headers is not None else {}
    response.release_conn = MagicMock(return_value=None)
    return response


def _make_session_router(routes):
    """Build a session that picks a response per (method, url) lookup.

    ``routes`` is a list of ``(method, url_substring, response)`` tuples
    consumed in order; the first matching tuple's response is returned.
    A no-match raises so tests fail loudly instead of returning an
    auto-MagicMock.
    """

    session = MagicMock()
    call_log: list[tuple[str, str, dict]] = []

    def _dispatch(method, url, *, headers=None, **_kwargs):
        call_log.append((method, url, dict(headers or {})))
        for r_method, r_substr, response in routes:
            if r_method == method and r_substr in url:
                return response
        raise AssertionError(
            f"unexpected session call: {method} {url} "
            f"(routes={[(m, s) for (m, s, _) in routes]})"
        )

    session.request.side_effect = _dispatch
    session._call_log = call_log  # type: ignore[attr-defined]
    return session


# ---------------------------------------------------------------------------
# PEP 658 fast path
# ---------------------------------------------------------------------------


class TestPEP658FastPath:
    """Fetch via ``<wheel_url>.metadata`` when the index advertises it."""

    def test_pep658_fast_path_returns_parsed_metadata(self):
        from pipenv.resolver.pure_python_metadata import (
            CoreMetadata,
            fetch_metadata,
        )

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        body_hash = hashlib.sha256(body).hexdigest()

        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "text/plain"},
        )
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        result = fetch_metadata(
            candidate,
            session,
            metadata_url=metadata_url,
            metadata_hash={"sha256": body_hash},
        )

        assert isinstance(result, CoreMetadata)
        assert result.name == "numpy"
        assert result.version == "1.26.0"
        assert result.requires_python == "<3.13,>=3.9"
        # Three Requires-Dist lines, in order.
        assert "hypothesis ; extra == 'test'" in result.requires_dist
        assert "pytest ; extra == 'test'" in result.requires_dist
        assert "pytest-cov ; extra == 'test'" in result.requires_dist
        assert len(result.requires_dist) == 3
        assert "test" in result.provides_extras
        assert result.summary == (
            "Fundamental package for array computing in Python"
        )

    def test_pep658_hash_mismatch_raises(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        # Wrong hash on purpose.
        wrong_hash = "0" * 64

        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "text/plain"},
        )
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        with pytest.raises(MetadataFetchError) as excinfo:
            fetch_metadata(
                candidate,
                session,
                metadata_url=metadata_url,
                metadata_hash={"sha256": wrong_hash},
            )

        # Surfacing should name the algo + the offender so users can
        # audit which wheel poisoned the cache.
        msg = str(excinfo.value)
        assert "sha256" in msg.lower()


# ---------------------------------------------------------------------------
# Wheel-head fallback
# ---------------------------------------------------------------------------


def _build_synthetic_wheel(tmp_path: Path, metadata_text: str) -> bytes:
    """Build a single-METADATA-member wheel bytes blob and return it."""
    wheel_path = tmp_path / "fakepkg-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fakepkg-1.0.0.dist-info/METADATA", metadata_text)
        zf.writestr("fakepkg/__init__.py", "")
    return wheel_path.read_bytes()


class TestWheelHeadFallback:
    """Range-GET on the wheel zip's central directory; parse METADATA."""

    def test_wheel_head_fallback_returns_parsed_metadata(self, tmp_path):
        from pipenv.resolver.pure_python_metadata import fetch_metadata

        metadata_text = (
            "Metadata-Version: 2.1\n"
            "Name: fakepkg\n"
            "Version: 1.0.0\n"
            "Summary: A synthetic wheel for tests\n"
            "Requires-Python: >=3.9\n"
            "Requires-Dist: requests>=2.0\n"
            "Requires-Dist: click\n"
            "\n"
        )
        wheel_bytes = _build_synthetic_wheel(tmp_path, metadata_text)

        candidate = _make_wheel_candidate(
            name="fakepkg",
            version="1.0.0",
            url=(
                "https://example.org/wheels/"
                "fakepkg-1.0.0-py3-none-any.whl"
            ),
        )

        # HEAD reveals Content-Length; GET with a range returns the
        # last 64 kB (whole wheel for a small synthetic).
        head_response = _make_response(
            status=200,
            data=b"",
            headers={"Content-Length": str(len(wheel_bytes))},
        )
        # The fetcher will issue at least one range GET; we serve the
        # whole wheel for any GET to keep the mock simple.  Real
        # behaviour serves a 206 with a slice; the fetcher should
        # accept 200 too (some mirrors don't honour Range).
        get_response = _make_response(
            status=206,
            data=wheel_bytes,
            headers={
                "Content-Range": (
                    f"bytes 0-{len(wheel_bytes) - 1}/{len(wheel_bytes)}"
                ),
                "Content-Length": str(len(wheel_bytes)),
            },
        )
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, get_response),
            ],
        )

        result = fetch_metadata(candidate, session)

        assert result.name == "fakepkg"
        assert result.version == "1.0.0"
        assert result.requires_python == ">=3.9"
        assert "requests>=2.0" in result.requires_dist
        assert "click" in result.requires_dist
        assert result.summary == "A synthetic wheel for tests"

    def test_wheel_head_405_falls_back_to_probing_get(self, tmp_path):
        """HEAD 405 → probing GET with ``Range: bytes=0-1`` for length."""

        from pipenv.resolver.pure_python_metadata import fetch_metadata

        metadata_text = (
            "Metadata-Version: 2.1\n"
            "Name: fakepkg\n"
            "Version: 1.0.0\n"
            "Requires-Dist: six\n"
            "\n"
        )
        wheel_bytes = _build_synthetic_wheel(tmp_path, metadata_text)

        candidate = _make_wheel_candidate(
            name="fakepkg",
            version="1.0.0",
            url=(
                "https://example.org/wheels/"
                "fakepkg-1.0.0-py3-none-any.whl"
            ),
        )

        # HEAD → 405 (not allowed).  GET with a small range → 206 with
        # Content-Range exposing the full length.  Subsequent range GET
        # returns the whole body.
        head_response = _make_response(status=405, data=b"", headers={})
        probe_response = _make_response(
            status=206,
            data=wheel_bytes[:2],
            headers={
                "Content-Range": f"bytes 0-1/{len(wheel_bytes)}",
                "Content-Length": "2",
            },
        )
        # We do GET twice (probe + actual range).  The router returns
        # the same response for both; the response data path is the
        # one that mattered for probing (Content-Range), then for the
        # real fetch we hand back the whole wheel as a permissive 200.
        full_response = _make_response(
            status=200,
            data=wheel_bytes,
            headers={"Content-Length": str(len(wheel_bytes))},
        )

        # Order of routes matters: first GET → probe (small body), then
        # we want a route for the real range GET that serves the full
        # wheel.  Encode that with a stateful side_effect.
        get_calls = {"count": 0}

        def _dispatch(method, url, *, headers=None, **_kw):
            if method == "HEAD":
                return head_response
            if method == "GET":
                # First GET is the probe (Range: bytes=0-1).  Subsequent
                # GETs return the full body.
                get_calls["count"] += 1
                if get_calls["count"] == 1:
                    return probe_response
                return full_response
            raise AssertionError(
                f"unexpected session call: {method} {url}"
            )

        session = MagicMock()
        session.request.side_effect = _dispatch

        result = fetch_metadata(candidate, session)

        assert result.name == "fakepkg"
        assert "six" in result.requires_dist


# ---------------------------------------------------------------------------
# On-disk cache round-trip
# ---------------------------------------------------------------------------


class TestMetadataCache:
    """A second fetch on a populated cache must not hit the network."""

    def test_cache_round_trip_skips_network_on_second_call(
        self, tmp_path
    ):
        from pipenv.resolver.pure_python_metadata import (
            MetadataCache,
            fetch_metadata,
        )

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        body_hash = hashlib.sha256(body).hexdigest()

        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(
            status=200,
            data=body,
            headers={"Content-Type": "text/plain"},
        )
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        cache = MetadataCache(tmp_path / "metadata-cache")

        result1 = fetch_metadata(
            candidate,
            session,
            metadata_url=metadata_url,
            metadata_hash={"sha256": body_hash},
            cache=cache,
        )
        assert result1.name == "numpy"
        # One network call for the PEP 658 body.
        assert session.request.call_count == 1

        # Second call: cache hit; no further network.
        result2 = fetch_metadata(
            candidate,
            session,
            metadata_url=metadata_url,
            metadata_hash={"sha256": body_hash},
            cache=cache,
        )
        assert result2.name == "numpy"
        assert result2.requires_dist == result1.requires_dist
        assert session.request.call_count == 1  # unchanged

    def test_cache_get_returns_none_when_missing(self, tmp_path):
        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        assert cache.get("https://example.org/nonexistent.whl") is None

    def test_cache_put_then_get_round_trip(self, tmp_path):
        from pipenv.resolver.pure_python_metadata import (
            CoreMetadata,
            MetadataCache,
        )

        cache = MetadataCache(tmp_path / "metadata-cache")
        meta = CoreMetadata(
            name="six",
            version="1.16.0",
            requires_python=">=2.7",
            requires_dist=("attrs>=21.0",),
            provides_extras=frozenset({"test"}),
            summary="Python 2 and 3 compatibility utilities",
        )
        url = "https://example.org/wheels/six-1.16.0-py2.py3-none-any.whl"
        cache.put(url, meta)

        out = cache.get(url)
        assert out == meta


# ---------------------------------------------------------------------------
# _parse_metadata_text — the helper unit tests
# ---------------------------------------------------------------------------


class TestParseMetadataText:
    """``_parse_metadata_text`` is the email-parser-fronted helper."""

    def test_parses_minimum_required_fields(self):
        from pipenv.resolver.pure_python_metadata import (
            _parse_metadata_text,
        )

        text = (
            "Metadata-Version: 2.1\n"
            "Name: SomePkg\n"
            "Version: 0.1.0\n"
            "\n"
        )
        result = _parse_metadata_text(text)
        # Name should be PEP 503 canonical (lower-case here it already is).
        assert result.name == "somepkg"
        assert result.version == "0.1.0"
        assert result.requires_python is None
        assert result.requires_dist == ()
        assert result.provides_extras == frozenset()

    def test_collects_repeated_requires_dist(self):
        from pipenv.resolver.pure_python_metadata import (
            _parse_metadata_text,
        )

        text = (
            "Metadata-Version: 2.1\n"
            "Name: alpha\n"
            "Version: 1.0\n"
            "Requires-Dist: a>=1\n"
            "Requires-Dist: b<2\n"
            "Requires-Dist: c\n"
            "Provides-Extra: dev\n"
            "Provides-Extra: test\n"
            "\n"
        )
        result = _parse_metadata_text(text)
        assert result.requires_dist == ("a>=1", "b<2", "c")
        assert result.provides_extras == frozenset({"dev", "test"})
