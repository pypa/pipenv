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

    def test_populates_all_core_metadata_fields(self):
        """``_parse_metadata_text`` populates every :class:`CoreMetadata` field.

        Covers the "full happy path" path through the email parser,
        including multiple ``Provides-Extra`` lines, multiple
        ``Requires-Dist`` lines (mixed with extras markers), a
        non-canonical ``Name``, and a stripped ``Requires-Python``.
        """
        from pipenv.resolver.pure_python_metadata import (
            _parse_metadata_text,
        )

        text = (
            "Metadata-Version: 2.1\n"
            "Name: My_Funky.Pkg\n"
            "Version: 0.2.0\n"
            "Summary:    Bench package    \n"
            "Requires-Python:   >=3.8,<4   \n"
            "Requires-Dist: a>=1\n"
            "Requires-Dist: b ; extra == 'docs'\n"
            "Requires-Dist: c ; extra == 'test'\n"
            "Provides-Extra: docs\n"
            "Provides-Extra: test\n"
            "Provides-Extra: extras-with-dash\n"
            "\n"
        )
        result = _parse_metadata_text(text)
        assert result.name == "my-funky-pkg"
        assert result.version == "0.2.0"
        assert result.summary == "Bench package"
        assert result.requires_python == ">=3.8,<4"
        assert result.requires_dist == (
            "a>=1",
            "b ; extra == 'docs'",
            "c ; extra == 'test'",
        )
        assert result.provides_extras == frozenset(
            {"docs", "test", "extras-with-dash"}
        )

    def test_blank_requires_python_normalises_to_none(self):
        from pipenv.resolver.pure_python_metadata import (
            _parse_metadata_text,
        )

        text = (
            "Metadata-Version: 2.1\n"
            "Name: blanky\n"
            "Version: 1.0\n"
            "Requires-Python:    \n"
            "Summary:   \n"
            "\n"
        )
        result = _parse_metadata_text(text)
        assert result.requires_python is None
        assert result.summary is None


# ---------------------------------------------------------------------------
# CoreMetadata dataclass behaviour (frozen + slots)
# ---------------------------------------------------------------------------


class TestCoreMetadataDataclass:
    """``CoreMetadata`` is ``frozen=True, slots=True`` — both must hold."""

    def _make(self):
        from pipenv.resolver.pure_python_metadata import CoreMetadata

        return CoreMetadata(
            name="six",
            version="1.16.0",
            requires_python=">=2.7",
            requires_dist=("attrs>=21.0",),
            provides_extras=frozenset({"test"}),
            summary="Python 2 and 3 compatibility utilities",
        )

    def test_is_frozen(self):
        from dataclasses import FrozenInstanceError

        meta = self._make()
        with pytest.raises(FrozenInstanceError):
            meta.name = "seven"  # type: ignore[misc]

    def test_uses_slots_no_dict(self):
        meta = self._make()
        # slots=True suppresses __dict__ allocation.
        assert not hasattr(meta, "__dict__")

    def test_is_hashable_and_lives_in_frozenset(self):
        meta_a = self._make()
        meta_b = self._make()
        bag = frozenset({meta_a, meta_b})
        assert len(bag) == 1
        assert meta_a in bag

    def test_equality_by_value(self):
        assert self._make() == self._make()


# ---------------------------------------------------------------------------
# PEP 658 fast path — additional coverage
# ---------------------------------------------------------------------------


class TestPEP658Extra:
    """Edge cases on the PEP 658 path that the T2 happy path missed."""

    def test_pep658_empty_hash_dict_skips_verification(self):
        """An empty ``metadata_hash`` dict must not raise; PEP 658 §6 allows it."""
        from pipenv.resolver.pure_python_metadata import fetch_metadata

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(status=200, data=body)
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        result = fetch_metadata(
            candidate,
            session,
            metadata_url=metadata_url,
            metadata_hash={},
        )
        assert result.name == "numpy"

    def test_pep658_hash_dict_without_sha256_skips_verification(self):
        """A ``metadata_hash`` with ``md5`` but no ``sha256`` is treated as no-hash."""
        from pipenv.resolver.pure_python_metadata import fetch_metadata

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(status=200, data=body)
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        # Only md5 advertised — we should NOT raise (matches T2's
        # design note: "only sha256 is honoured; other algos are
        # ignored").
        result = fetch_metadata(
            candidate,
            session,
            metadata_url=metadata_url,
            metadata_hash={"md5": "deadbeef" * 4},
        )
        assert result.name == "numpy"

    def test_pep658_none_hash_skips_verification(self):
        from pipenv.resolver.pure_python_metadata import fetch_metadata

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(status=200, data=body)
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        result = fetch_metadata(
            candidate,
            session,
            metadata_url=metadata_url,
            metadata_hash=None,
        )
        assert result.name == "numpy"

    def test_pep658_non_utf8_body_raises(self):
        """A non-UTF-8 PEP 658 body surfaces as ``MetadataFetchError``."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        # Invalid UTF-8: a lone continuation byte.
        body = b"\xff\xfe not utf-8 \x80\x81"
        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(status=200, data=body)
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        with pytest.raises(MetadataFetchError, match="not UTF-8"):
            fetch_metadata(
                candidate,
                session,
                metadata_url=metadata_url,
            )

    def test_pep658_http_error_raises(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(status=404, data=b"")
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        with pytest.raises(MetadataFetchError, match="HTTP 404"):
            fetch_metadata(
                candidate,
                session,
                metadata_url=metadata_url,
            )

    def test_pep658_session_raises_surfaces_as_metadata_fetch_error(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        session = MagicMock()
        session.request.side_effect = RuntimeError("network down")

        with pytest.raises(MetadataFetchError, match="no response"):
            fetch_metadata(
                candidate,
                session,
                metadata_url=metadata_url,
            )

    def test_pep658_response_with_no_body_raises(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        # data=None — some mocks/HTTP clients return this on a streamed body.
        response = _make_response(status=200)
        response.data = None
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        with pytest.raises(MetadataFetchError, match="no body"):
            fetch_metadata(
                candidate,
                session,
                metadata_url=metadata_url,
            )


# ---------------------------------------------------------------------------
# Wheel-head fallback — additional coverage
# ---------------------------------------------------------------------------


def _build_wheel_without_metadata(tmp_path: Path) -> bytes:
    """Build a wheel-shaped zip with NO ``<dist-info>/METADATA`` member."""
    wheel_path = tmp_path / "broken-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Has a dist-info directory but lacks the METADATA file.
        zf.writestr("broken-1.0.0.dist-info/RECORD", "")
        zf.writestr("broken/__init__.py", "")
    return wheel_path.read_bytes()


class TestWheelHeadFallbackExtra:
    """Extra branches of the wheel-tail range-fetch path."""

    def _candidate(self):
        return _make_wheel_candidate(
            name="broken",
            version="1.0.0",
            url=(
                "https://example.org/wheels/"
                "broken-1.0.0-py3-none-any.whl"
            ),
        )

    def test_missing_metadata_member_raises(self, tmp_path):
        """A wheel whose central directory has no ``METADATA`` member raises."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        wheel_bytes = _build_wheel_without_metadata(tmp_path)
        candidate = self._candidate()

        head_response = _make_response(
            status=200,
            headers={"Content-Length": str(len(wheel_bytes))},
        )
        get_response = _make_response(
            status=206,
            data=wheel_bytes,
            headers={
                "Content-Range": (
                    f"bytes 0-{len(wheel_bytes) - 1}/{len(wheel_bytes)}"
                ),
            },
        )
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, get_response),
            ],
        )

        with pytest.raises(MetadataFetchError, match="METADATA"):
            fetch_metadata(candidate, session)

    def test_corrupt_zip_tail_raises(self, tmp_path):
        """If the tail bytes can't be parsed as a zip, we surface an error."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = self._candidate()
        # Junk that is neither a zip nor anywhere near the central directory.
        junk = b"\x00" * 1024
        head_response = _make_response(
            status=200,
            headers={"Content-Length": str(len(junk))},
        )
        get_response = _make_response(
            status=206,
            data=junk,
            headers={
                "Content-Range": f"bytes 0-{len(junk) - 1}/{len(junk)}",
            },
        )
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, get_response),
            ],
        )

        with pytest.raises(MetadataFetchError, match="central directory"):
            fetch_metadata(candidate, session)

    def test_head_405_no_content_range_raises(self):
        """HEAD 405 + probing GET 206 with no Content-Range header → error."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = self._candidate()
        head_response = _make_response(status=405)
        probe_response = _make_response(
            status=206,
            data=b"ab",
            headers={"Content-Length": "2"},  # no Content-Range
        )
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, probe_response),
            ],
        )

        with pytest.raises(
            MetadataFetchError, match="could not parse Content-Range"
        ):
            fetch_metadata(candidate, session)

    def test_head_405_probe_get_4xx_raises(self):
        """HEAD 405 + probing GET 403 → error mentioning the status."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = self._candidate()
        head_response = _make_response(status=405)
        probe_response = _make_response(status=403)
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, probe_response),
            ],
        )

        with pytest.raises(MetadataFetchError, match="HTTP 403"):
            fetch_metadata(candidate, session)

    def test_head_and_probe_both_session_failure_raises(self):
        """Both HEAD and probing GET raising at the session layer → error."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = self._candidate()
        session = MagicMock()
        session.request.side_effect = RuntimeError("network gone")

        with pytest.raises(
            MetadataFetchError, match="HEAD and probing GET both failed"
        ):
            fetch_metadata(candidate, session)

    def test_head_200_no_content_length_falls_back_to_probe(self, tmp_path):
        """HEAD 200 without a ``Content-Length`` header falls through to the probe."""
        from pipenv.resolver.pure_python_metadata import fetch_metadata

        metadata_text = (
            "Metadata-Version: 2.1\n"
            "Name: tinypkg\n"
            "Version: 0.1.0\n"
            "Requires-Dist: x\n"
            "\n"
        )
        wheel_bytes = _build_synthetic_wheel(tmp_path, metadata_text)

        candidate = _make_wheel_candidate(
            name="tinypkg",
            version="0.1.0",
            url=(
                "https://example.org/wheels/"
                "tinypkg-0.1.0-py3-none-any.whl"
            ),
        )

        # HEAD: 200 with no Content-Length (forces the fallback path).
        head_response = _make_response(status=200, headers={})
        # First GET (probe with bytes=0-1) → 206 with a usable Content-Range.
        probe_response = _make_response(
            status=206,
            data=wheel_bytes[:2],
            headers={
                "Content-Range": f"bytes 0-1/{len(wheel_bytes)}",
                "Content-Length": "2",
            },
        )
        # Second GET (the real range fetch) → 206 carrying the wheel.
        full_response = _make_response(
            status=206,
            data=wheel_bytes,
            headers={
                "Content-Range": (
                    f"bytes 0-{len(wheel_bytes) - 1}/{len(wheel_bytes)}"
                ),
            },
        )

        get_calls = {"count": 0}

        def _dispatch(method, url, *, headers=None, **_kw):
            if method == "HEAD":
                return head_response
            if method == "GET":
                get_calls["count"] += 1
                if get_calls["count"] == 1:
                    return probe_response
                return full_response
            raise AssertionError(f"unexpected: {method} {url}")

        session = MagicMock()
        session.request.side_effect = _dispatch

        result = fetch_metadata(candidate, session)
        assert result.name == "tinypkg"

    def test_head_200_bad_content_length_falls_back(self, tmp_path):
        """A non-integer ``Content-Length`` on HEAD is treated as missing."""
        from pipenv.resolver.pure_python_metadata import fetch_metadata

        metadata_text = (
            "Metadata-Version: 2.1\n"
            "Name: lengthbad\n"
            "Version: 0.1.0\n"
            "Requires-Dist: y\n"
            "\n"
        )
        wheel_bytes = _build_synthetic_wheel(tmp_path, metadata_text)
        candidate = _make_wheel_candidate(
            name="lengthbad",
            version="0.1.0",
            url=(
                "https://example.org/wheels/"
                "lengthbad-0.1.0-py3-none-any.whl"
            ),
        )

        head_response = _make_response(
            status=200,
            headers={"Content-Length": "not-an-int"},
        )
        probe_response = _make_response(
            status=206,
            data=wheel_bytes[:2],
            headers={
                "Content-Range": f"bytes 0-1/{len(wheel_bytes)}",
            },
        )
        full_response = _make_response(
            status=206,
            data=wheel_bytes,
            headers={
                "Content-Range": (
                    f"bytes 0-{len(wheel_bytes) - 1}/{len(wheel_bytes)}"
                ),
            },
        )

        get_calls = {"count": 0}

        def _dispatch(method, url, *, headers=None, **_kw):
            if method == "HEAD":
                return head_response
            get_calls["count"] += 1
            if get_calls["count"] == 1:
                return probe_response
            return full_response

        session = MagicMock()
        session.request.side_effect = _dispatch

        result = fetch_metadata(candidate, session)
        assert result.name == "lengthbad"

    def test_head_405_content_range_asterisk_total_raises(self):
        """Some servers return ``bytes 0-1/*`` — unparseable → error."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = self._candidate()
        head_response = _make_response(status=405)
        probe_response = _make_response(
            status=206,
            data=b"ab",
            headers={"Content-Range": "bytes 0-1/*"},
        )
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, probe_response),
            ],
        )

        with pytest.raises(MetadataFetchError, match="could not parse Content-Range"):
            fetch_metadata(candidate, session)

    def test_head_405_unparseable_total_raises(self):
        """Garbage after the slash in ``Content-Range`` → error."""
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            fetch_metadata,
        )

        candidate = self._candidate()
        head_response = _make_response(status=405)
        probe_response = _make_response(
            status=206,
            data=b"ab",
            headers={"Content-Range": "bytes 0-1/notanumber"},
        )
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, probe_response),
            ],
        )

        with pytest.raises(MetadataFetchError, match="could not parse Content-Range"):
            fetch_metadata(candidate, session)

    def test_windows_separator_metadata_member_is_found(self, tmp_path):
        """A wheel that uses ``\\`` in entry names still resolves METADATA."""
        from pipenv.resolver.pure_python_metadata import fetch_metadata

        # zipfile uses the filename verbatim; we can write an entry with
        # a backslash and verify the fallback ``endswith`` clause hits.
        wheel_path = tmp_path / "winpkg-1.0.0-py3-none-any.whl"
        metadata_text = (
            "Metadata-Version: 2.1\n"
            "Name: winpkg\n"
            "Version: 1.0.0\n"
            "Requires-Dist: a\n"
            "\n"
        )
        with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "winpkg-1.0.0.dist-info\\METADATA",
                metadata_text,
            )
            zf.writestr("winpkg/__init__.py", "")
        wheel_bytes = wheel_path.read_bytes()

        candidate = _make_wheel_candidate(
            name="winpkg",
            version="1.0.0",
            url=(
                "https://example.org/wheels/"
                "winpkg-1.0.0-py3-none-any.whl"
            ),
        )

        head_response = _make_response(
            status=200,
            headers={"Content-Length": str(len(wheel_bytes))},
        )
        get_response = _make_response(
            status=206,
            data=wheel_bytes,
            headers={
                "Content-Range": (
                    f"bytes 0-{len(wheel_bytes) - 1}/{len(wheel_bytes)}"
                ),
            },
        )
        session = _make_session_router(
            [
                ("HEAD", candidate.url, head_response),
                ("GET", candidate.url, get_response),
            ],
        )

        result = fetch_metadata(candidate, session)
        assert result.name == "winpkg"
        assert "a" in result.requires_dist


# ---------------------------------------------------------------------------
# MetadataCache — additional coverage of failure / corruption modes
# ---------------------------------------------------------------------------


class TestMetadataCacheExtra:
    """Corrupt-cache + write-failure paths."""

    def _meta(self):
        from pipenv.resolver.pure_python_metadata import CoreMetadata

        return CoreMetadata(
            name="six",
            version="1.16.0",
            requires_python=">=2.7",
            requires_dist=("attrs>=21.0",),
            provides_extras=frozenset({"test"}),
            summary="Compat utilities",
        )

    def test_cache_get_returns_none_for_malformed_json(self, tmp_path):
        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        url = "https://example.org/wheels/foo.whl"
        target = cache._path_for(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"{not really json")
        assert cache.get(url) is None

    def test_cache_get_returns_none_for_non_dict_payload(self, tmp_path):
        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        url = "https://example.org/wheels/foo.whl"
        target = cache._path_for(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Valid JSON but not a dict.
        target.write_bytes(b'["not", "a", "dict"]')
        assert cache.get(url) is None

    def test_cache_get_returns_none_for_wrong_schema_version(self, tmp_path):
        import json as _json

        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        url = "https://example.org/wheels/foo.whl"
        target = cache._path_for(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            _json.dumps(
                {
                    "schema_version": 9999,
                    "name": "foo",
                    "version": "1.0",
                }
            ).encode("utf-8")
        )
        assert cache.get(url) is None

    def test_cache_get_returns_none_for_missing_required_key(self, tmp_path):
        """``schema_version=1`` but no ``name`` → cache treats as miss."""
        import json as _json

        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        url = "https://example.org/wheels/foo.whl"
        target = cache._path_for(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            _json.dumps(
                {
                    "schema_version": 1,
                    # no "name"
                    "version": "1.0",
                }
            ).encode("utf-8")
        )
        assert cache.get(url) is None

    def test_cache_get_returns_none_on_oserror(self, tmp_path, monkeypatch):
        """Generic ``OSError`` on read (not ``FileNotFoundError``) → miss."""
        from pathlib import Path as _Path

        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")

        def _boom(self):  # noqa: ARG001
            raise PermissionError("nope")

        monkeypatch.setattr(_Path, "read_bytes", _boom)
        assert cache.get("https://example.org/wheels/foo.whl") is None

    def test_cache_get_returns_none_when_decode_fails(self, tmp_path):
        """``UnicodeDecodeError`` inside ``json.loads`` → miss."""
        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        url = "https://example.org/wheels/foo.whl"
        target = cache._path_for(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Invalid UTF-8 → json.loads raises UnicodeDecodeError.
        target.write_bytes(b"\xff\xfe\xfd")
        assert cache.get(url) is None

    def test_cache_put_oserror_is_non_fatal(self, tmp_path, monkeypatch, caplog):
        """A failing ``cache.put`` must not poison the returned metadata."""
        import logging as _logging

        from pipenv.resolver.pure_python_metadata import (
            MetadataCache,
            fetch_metadata,
        )

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        body_hash = hashlib.sha256(body).hexdigest()
        candidate = _make_wheel_candidate()
        metadata_url = candidate.url + ".metadata"

        response = _make_response(status=200, data=body)
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        cache = MetadataCache(tmp_path / "metadata-cache")

        def _boom(self, wheel_url, metadata):  # noqa: ARG001
            raise OSError("disk full")

        monkeypatch.setattr(MetadataCache, "put", _boom)

        caplog.set_level(_logging.DEBUG, logger="pipenv.resolver.pure_python_metadata")
        result = fetch_metadata(
            candidate,
            session,
            metadata_url=metadata_url,
            metadata_hash={"sha256": body_hash},
            cache=cache,
        )
        # Metadata still returned despite write failure.
        assert result.name == "numpy"
        # Debug log emitted.
        assert any(
            "metadata cache write failed" in rec.message
            for rec in caplog.records
        )

    def test_cache_put_cleans_tempfile_on_replace_failure(
        self, tmp_path, monkeypatch
    ):
        """If ``os.replace`` raises, the temp file is unlinked."""
        import os as _os

        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        url = "https://example.org/wheels/six-1.16.0-py3-none-any.whl"

        real_replace = _os.replace

        def _boom_replace(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(_os, "replace", _boom_replace)

        with pytest.raises(OSError, match="simulated replace failure"):
            cache.put(url, self._meta())

        # No temp file should be left behind: parent directory must be
        # empty (the would-be target was never replaced and tmp was unlinked).
        parent = cache._path_for(url).parent
        leftovers = list(parent.iterdir())
        assert leftovers == [], f"unexpected leftover files: {leftovers}"

        # Restore for any later test in the class.
        monkeypatch.setattr(_os, "replace", real_replace)

    def test_cache_key_is_url_dependent(self, tmp_path):
        """Distinct URLs map to distinct paths; same URL → same path."""
        from pipenv.resolver.pure_python_metadata import MetadataCache

        cache = MetadataCache(tmp_path / "metadata-cache")
        a = "https://example.org/wheels/a-1.0-py3-none-any.whl"
        b = "https://example.org/wheels/b-1.0-py3-none-any.whl"

        path_a1 = cache._path_for(a)
        path_a2 = cache._path_for(a)
        path_b = cache._path_for(b)

        assert path_a1 == path_a2
        assert path_a1 != path_b
        # SHA256 hex length is 64 + ``.json``.
        assert path_a1.name.endswith(".json")
        assert len(path_a1.stem) == 64

    def test_cache_round_trip_via_disk_serialisation(self, tmp_path):
        """``put`` + fresh ``MetadataCache`` reads it back identically."""
        from pipenv.resolver.pure_python_metadata import MetadataCache

        meta = self._meta()
        url = "https://example.org/wheels/six.whl"

        writer = MetadataCache(tmp_path / "metadata-cache")
        writer.put(url, meta)

        reader = MetadataCache(tmp_path / "metadata-cache")
        out = reader.get(url)
        assert out == meta


# ---------------------------------------------------------------------------
# HTTP helper coverage — _get_header in particular
# ---------------------------------------------------------------------------


class TestHttpHelpers:
    def test_get_header_returns_none_for_none_headers(self):
        from pipenv.resolver.pure_python_metadata import _get_header

        assert _get_header(None, "Content-Length") is None

    def test_get_header_direct_hit(self):
        from pipenv.resolver.pure_python_metadata import _get_header

        assert _get_header({"Content-Length": "42"}, "Content-Length") == "42"

    def test_get_header_case_insensitive_fallback(self):
        from pipenv.resolver.pure_python_metadata import _get_header

        # dict.get is case-sensitive — value lives behind the
        # case-insensitive iteration fallback.  Use a dict that *only*
        # has the lowercase form, so the direct ``get`` returns None
        # and the fallback kicks in.
        class _PickyDict:
            def __init__(self, data):
                self._data = dict(data)

            def get(self, name):
                # Strict case-sensitive lookup.
                return self._data.get(name)

            def items(self):
                return self._data.items()

        headers = _PickyDict({"content-length": "99"})
        assert _get_header(headers, "Content-Length") == "99"

    def test_get_header_items_raises_returns_none(self):
        from pipenv.resolver.pure_python_metadata import _get_header

        class _Bad:
            def get(self, name):  # noqa: ARG002
                return None

            def items(self):
                raise RuntimeError("not iterable")

        assert _get_header(_Bad(), "X") is None

    def test_get_header_get_raises_falls_through_to_items(self):
        from pipenv.resolver.pure_python_metadata import _get_header

        class _Wonky:
            def get(self, name):
                raise RuntimeError("get unsupported")

            def items(self):
                return [("Content-Length", "7")]

        assert _get_header(_Wonky(), "Content-Length") == "7"

    def test_get_header_no_match_returns_none(self):
        from pipenv.resolver.pure_python_metadata import _get_header

        assert _get_header({"A": "1"}, "Z") is None

    def test_http_request_returns_none_on_exception(self):
        from pipenv.resolver.pure_python_metadata import _http_request

        session = MagicMock()
        session.request.side_effect = RuntimeError("boom")
        assert _http_request(session, "GET", "https://x") is None

    def test_http_get_range_session_raises(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            _http_get_range,
        )

        session = MagicMock()
        session.request.side_effect = RuntimeError("net down")
        with pytest.raises(MetadataFetchError, match="no response"):
            _http_get_range(session, "https://x/y.whl", 0, 10)

    def test_http_get_range_non_206_or_200(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            _http_get_range,
        )

        response = _make_response(status=416)
        session = _make_session_router([("GET", "x/y", response)])
        with pytest.raises(MetadataFetchError, match="HTTP 416"):
            _http_get_range(session, "https://x/y", 0, 10)

    def test_http_get_range_no_body(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            _http_get_range,
        )

        response = _make_response(status=206)
        response.data = None
        session = _make_session_router([("GET", "x/y", response)])
        with pytest.raises(MetadataFetchError, match="no body"):
            _http_get_range(session, "https://x/y", 0, 10)


# ---------------------------------------------------------------------------
# _PartialFile — the wheel-tail file-like adapter
# ---------------------------------------------------------------------------


class TestPartialFile:
    def _build(self, *, tail=b"abcdef", offset=10, total=16, session=None):
        from pipenv.resolver.pure_python_metadata import _PartialFile

        return _PartialFile(
            tail,
            offset=offset,
            total_length=total,
            session=session if session is not None else MagicMock(),
            url="https://example.org/x.whl",
        )

    def test_seekable_readable_writable(self):
        pf = self._build()
        assert pf.seekable() is True
        assert pf.readable() is True
        assert pf.writable() is False

    def test_seek_set_cur_end_and_tell(self):
        import io as _io

        pf = self._build()
        assert pf.seek(5, _io.SEEK_SET) == 5
        assert pf.tell() == 5
        assert pf.seek(2, _io.SEEK_CUR) == 7
        assert pf.seek(-1, _io.SEEK_END) == 15
        with pytest.raises(ValueError, match="unsupported whence"):
            pf.seek(0, 99)
        with pytest.raises(ValueError, match="negative seek"):
            pf.seek(-100, _io.SEEK_SET)

    def test_read_within_buffer(self):
        """Read entirely within the tail buffer — no network."""
        session = MagicMock()
        pf = self._build(tail=b"abcdef", offset=10, total=16, session=session)
        pf.seek(10)
        assert pf.read(3) == b"abc"
        # No range fetches.
        session.request.assert_not_called()

    def test_read_negative_size_to_eof(self):
        session = MagicMock()
        pf = self._build(tail=b"abcdef", offset=10, total=16, session=session)
        pf.seek(13)
        assert pf.read(-1) == b"def"

    def test_read_none_size_to_eof(self):
        session = MagicMock()
        pf = self._build(tail=b"abcdef", offset=10, total=16, session=session)
        pf.seek(13)
        assert pf.read(None) == b"def"  # type: ignore[arg-type]

    def test_read_at_or_past_end_returns_empty(self):
        pf = self._build()
        pf.seek(16)  # at EOF
        assert pf.read(10) == b""
        pf.seek(100)  # past EOF
        assert pf.read(10) == b""

    def test_read_size_zero_returns_empty(self):
        pf = self._build()
        pf.seek(10)
        assert pf.read(0) == b""

    def test_read_prefix_fetch_grows_buffer_low(self):
        """Reading before ``_buffer_start`` issues a prefix range GET."""
        from pipenv.resolver.pure_python_metadata import _PartialFile

        # Full wheel bytes laid out: positions 0..19 are "0123456789ABCDEFGHIJ".
        full = b"0123456789ABCDEFGHIJ"
        tail = full[10:]  # buffer covers [10, 20)

        prefix_response = _make_response(
            status=206,
            data=full[0:10],
            headers={"Content-Range": "bytes 0-9/20"},
        )
        session = _make_session_router(
            [("GET", "example.org/x.whl", prefix_response)],
        )

        pf = _PartialFile(
            tail,
            offset=10,
            total_length=20,
            session=session,
            url="https://example.org/x.whl",
        )
        pf.seek(0)
        out = pf.read(10)
        assert out == b"0123456789"
        # After the fetch the buffer covers [0, 20).
        assert pf._buffer_start == 0
        assert bytes(pf._buffer) == full

    def test_read_prefix_oversized_response_trimmed(self):
        """Mirror returns the full body on a range GET → we trim to ``wanted``."""
        from pipenv.resolver.pure_python_metadata import _PartialFile

        full = b"0123456789ABCDEFGHIJ"
        tail = full[10:]
        # Server ignores Range and returns the entire wheel.
        prefix_response = _make_response(status=200, data=full)
        session = _make_session_router(
            [("GET", "example.org/x.whl", prefix_response)],
        )

        pf = _PartialFile(
            tail,
            offset=10,
            total_length=20,
            session=session,
            url="https://example.org/x.whl",
        )
        pf.seek(0)
        out = pf.read(10)
        assert out == b"0123456789"

    def test_read_prefix_short_read_raises(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            _PartialFile,
        )

        tail = b"ABCDEFGHIJ"
        # We will request 10 bytes for the prefix but the mirror only
        # returns 3.
        prefix_response = _make_response(status=206, data=b"012")
        session = _make_session_router(
            [("GET", "example.org/x.whl", prefix_response)],
        )

        pf = _PartialFile(
            tail,
            offset=10,
            total_length=20,
            session=session,
            url="https://example.org/x.whl",
        )
        pf.seek(0)
        with pytest.raises(MetadataFetchError, match="short range read"):
            pf.read(10)

    def test_read_suffix_fetch_grows_buffer_high(self):
        from pipenv.resolver.pure_python_metadata import _PartialFile

        # Initial buffer covers [0, 10); request a read into [10, 20).
        head = b"0123456789"
        suffix_response = _make_response(
            status=206,
            data=b"ABCDEFGHIJ",
            headers={"Content-Range": "bytes 10-19/20"},
        )
        session = _make_session_router(
            [("GET", "example.org/x.whl", suffix_response)],
        )

        pf = _PartialFile(
            head,
            offset=0,
            total_length=20,
            session=session,
            url="https://example.org/x.whl",
        )
        pf.seek(10)
        out = pf.read(10)
        assert out == b"ABCDEFGHIJ"

    def test_read_suffix_oversized_response_trimmed(self):
        from pipenv.resolver.pure_python_metadata import _PartialFile

        head = b"0123456789"
        # Mirror returns way more than requested.
        suffix_response = _make_response(
            status=206, data=b"ABCDEFGHIJ_extra_junk_bytes"
        )
        session = _make_session_router(
            [("GET", "example.org/x.whl", suffix_response)],
        )

        pf = _PartialFile(
            head,
            offset=0,
            total_length=20,
            session=session,
            url="https://example.org/x.whl",
        )
        pf.seek(10)
        out = pf.read(10)
        assert out == b"ABCDEFGHIJ"

    def test_read_suffix_short_read_raises(self):
        from pipenv.resolver.pure_python_metadata import (
            MetadataFetchError,
            _PartialFile,
        )

        head = b"0123456789"
        suffix_response = _make_response(status=206, data=b"AB")
        session = _make_session_router(
            [("GET", "example.org/x.whl", suffix_response)],
        )

        pf = _PartialFile(
            head,
            offset=0,
            total_length=20,
            session=session,
            url="https://example.org/x.whl",
        )
        pf.seek(10)
        with pytest.raises(MetadataFetchError, match="short range read"):
            pf.read(10)


# ---------------------------------------------------------------------------
# T_S2 — sdist routing inside fetch_metadata
# ---------------------------------------------------------------------------


def _make_sdist_candidate(
    name: str = "examplepkg",
    version: str = "1.0.0",
    *,
    url: str = "https://example.org/sdists/examplepkg-1.0.0.tar.gz",
) -> Candidate:
    """Build a sdist :class:`Candidate` (``is_wheel == False``).

    Mirrors :func:`_make_wheel_candidate` but with a ``.tar.gz``
    filename, so :meth:`Candidate.from_filename` derives
    ``is_wheel = False`` and ``wheel_tags = None``.
    """
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


class TestFetchMetadataSdistRouting:
    """T_S2 — ``fetch_metadata`` branches on ``candidate.is_wheel``.

    Wheel candidates keep the existing PEP 658 + wheel-head fallback
    paths; sdist candidates delegate to T_S1's
    :func:`pipenv.resolver.pure_python_sdist.extract_metadata_from_sdist`.
    Cache is shared — same :class:`MetadataCache` keyed by URL sha256.
    """

    def test_sdist_candidate_routes_to_sdist_extractor(self):
        """``is_wheel=False`` candidate → extract_metadata_from_sdist invoked.

        No HTTP HEAD/GET is performed on the sdist URL: the wheel-head
        fallback machinery must not fire on a sdist candidate.  The
        session router has zero routes, so any attempted HTTP call
        would raise ``AssertionError`` — passing this test confirms the
        wheel path is bypassed entirely.
        """
        from unittest.mock import patch

        from pipenv.resolver.pure_python_metadata import (
            CoreMetadata,
            fetch_metadata,
        )

        candidate = _make_sdist_candidate()
        assert candidate.is_wheel is False  # sanity-check the helper

        session = _make_session_router([])  # no HTTP expected at all

        expected_metadata = CoreMetadata(
            name="examplepkg",
            version="1.0.0",
            requires_python=None,
            requires_dist=(),
            provides_extras=frozenset(),
            summary=None,
        )

        with patch(
            "pipenv.resolver.pure_python_sdist.extract_metadata_from_sdist",
            return_value=expected_metadata,
        ) as mock_extract:
            result = fetch_metadata(candidate, session)

        mock_extract.assert_called_once()
        # First positional arg is the candidate; second is the session.
        call_args, call_kwargs = mock_extract.call_args
        assert call_args[0] is candidate
        assert call_args[1] is session
        # cache kwarg is forwarded (None when not supplied by caller).
        assert call_kwargs.get("cache") is None
        # Result is propagated verbatim — same dataclass instance.
        assert result is expected_metadata
        # Hard guarantee: no HTTP traffic on the sdist URL.
        assert session.request.call_count == 0

    def test_wheel_candidate_does_not_route_to_sdist(self):
        """``is_wheel=True`` ⇒ wheel path; sdist extractor never invoked.

        Pin via a ``patch`` on ``extract_metadata_from_sdist`` whose
        ``side_effect`` raises if called — combined with a regular
        PEP 658 happy path, this proves the wheel branch is preserved.
        """
        from unittest.mock import patch

        from pipenv.resolver.pure_python_metadata import fetch_metadata

        body = NUMPY_METADATA_TEXT.encode("utf-8")
        body_hash = hashlib.sha256(body).hexdigest()

        candidate = _make_wheel_candidate()
        assert candidate.is_wheel is True  # sanity-check the helper

        metadata_url = candidate.url + ".metadata"
        response = _make_response(status=200, data=body)
        session = _make_session_router(
            [("GET", metadata_url, response)],
        )

        def _explode(*_args, **_kwargs):
            raise AssertionError(
                "extract_metadata_from_sdist must not be called for a wheel"
            )

        with patch(
            "pipenv.resolver.pure_python_sdist.extract_metadata_from_sdist",
            side_effect=_explode,
        ) as mock_extract:
            result = fetch_metadata(
                candidate,
                session,
                metadata_url=metadata_url,
                metadata_hash={"sha256": body_hash},
            )

        mock_extract.assert_not_called()
        # Result came from the wheel path — parsed real METADATA.
        assert result.name == "numpy"
        assert result.version == "1.26.0"

    def test_sdist_cache_passed_through(self, tmp_path):
        """``cache`` kwarg is forwarded to the sdist extractor.

        T_S1 honours / populates the shared :class:`MetadataCache`
        internally; T_S2 only needs to pass it through so the on-disk
        cache key (``sha256(candidate.url)``) is shared across wheel
        and sdist routes.  Also covers the cache short-circuit: a
        pre-populated cache entry must skip both the sdist extractor
        and any HTTP traffic.
        """
        from unittest.mock import patch

        from pipenv.resolver.pure_python_metadata import (
            CoreMetadata,
            MetadataCache,
            fetch_metadata,
        )

        candidate = _make_sdist_candidate()
        session = _make_session_router([])

        cache = MetadataCache(tmp_path / "metadata-cache")

        # --- first call: miss → extractor invoked → cache kwarg forwarded.
        expected_metadata = CoreMetadata(
            name="examplepkg",
            version="1.0.0",
            requires_python=None,
            requires_dist=(),
            provides_extras=frozenset(),
            summary=None,
        )

        with patch(
            "pipenv.resolver.pure_python_sdist.extract_metadata_from_sdist",
            return_value=expected_metadata,
        ) as mock_extract:
            result = fetch_metadata(candidate, session, cache=cache)

        mock_extract.assert_called_once()
        _, call_kwargs = mock_extract.call_args
        assert call_kwargs.get("cache") is cache
        assert result is expected_metadata

        # --- second call: pre-populated cache → extractor never invoked.
        # T_S1 owns its own cache.put; emulate that here so we can
        # exercise fetch_metadata's own cache short-circuit branch
        # without depending on the real extractor's I/O.
        cache.put(candidate.url, expected_metadata)

        with patch(
            "pipenv.resolver.pure_python_sdist.extract_metadata_from_sdist",
            side_effect=AssertionError(
                "extractor must not be called on a cache hit"
            ),
        ) as mock_extract2:
            cached_result = fetch_metadata(candidate, session, cache=cache)

        mock_extract2.assert_not_called()
        assert cached_result == expected_metadata
        # Still no HTTP traffic.
        assert session.request.call_count == 0
