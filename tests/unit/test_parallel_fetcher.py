"""Full-coverage tests for :class:`pipenv.resolver.fetcher.ParallelFetcher`
(Initiative G phase 1, T15).

Scope: every public + private code path of ``ParallelFetcher``:

* Basic dispatch — empty targets fast-path; cold-cache spawn; warm-cache
  fast-path (zero ``client.fetch`` calls); mixed-state partial dispatch.
* Status branches — ``status="fresh"`` (cache write + re-`get`), ``status=
  "not-modified"`` with prior cache (option-a TTL refresh), ``status=
  "not-modified"`` without prior cache (transient), ``status="missing"``
  (FetchError(missing), no cache write).
* Exception isolation — a worker raising an arbitrary exception becomes
  ``FetchError(kind="transient", original=<exc>)``; sibling workers
  complete; the executor never deadlocks.
* Result keying — duplicate ``(index_url, package_name)`` entries produce
  one key in the result dict (last-write-wins).
* Config plumbing — ``max_workers`` clamping > 16 (INFO log), ``max_workers
  < 1`` raises ``ValueError``, constructor defaults are 16 / 600s.
* Cache integration — ``cache.get`` called once per target, ``cache.put``
  called with ``ttl_seconds=default_ttl``; custom ``default_ttl`` honored;
  ``cache.put`` ``OSError`` becomes a ``FetchError(kind="transient")``
  for ``fresh`` and a soft-fall-back to the existing payload for the
  ``not-modified`` refresh branch.
* Concurrency — dispatch-order instrumentation (threading.Event) proves
  the executor dispatches up to ``max_workers`` concurrently; NO wall-time
  assertions.
* Edge cases — ``ttl_seconds=0`` synthesises an in-process
  ``CachedManifest`` (because the post-put re-`get` returns ``None``);
  unknown ``status`` values map to transient; ``BaseException`` (here,
  ``KeyboardInterrupt``) raised inside ``_fetch_one`` is caught and
  becomes a transient.

T9 contract notes folded in:

* ``cache.get`` is called once per target during step-1 classification;
  ``cache.put``-then-``cache.get`` happens again after dispatch for the
  ``fresh`` and ``not-modified`` cases so the value type in the result
  dict matches the warm-cache fast-path's value type.
* Duplicate targets are NOT deduplicated upstream: warm hits land in
  ``result`` directly (step 1 last-write-wins among warm hits), and any
  misses among duplicates are appended to ``to_fetch`` and may both run.
  The result dict is keyed by ``package_name`` so the second-completer
  among parallel duplicates wins (non-deterministic; the test asserts
  one of the two completion outcomes is present, not both).
* Empty-string ``index_url`` is permitted by T9 — the cache layer hashes
  it like any other string and the client mock receives it unchanged.
* ``BaseException`` (not just :class:`Exception`) is caught in
  ``_fetch_one`` — verified with a ``KeyboardInterrupt`` instance.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipenv.resolver.candidate import Candidate, Hash
from pipenv.resolver.fetcher import ParallelFetcher, _MAX_WORKERS_CEILING
from pipenv.resolver.manifest_cache import CachedManifest, ParsedManifestCache
from pipenv.resolver.pep691_types import FetchError, SimplePageResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    name: str = "numpy",
    version: str = "1.26.0",
    *,
    filename: str | None = None,
) -> Candidate:
    """Build a wheel ``Candidate``."""
    fn = filename or f"{name}-{version}-py3-none-any.whl"
    return Candidate.from_filename(
        fn,
        name=name,
        version=version,
        url=f"https://example.org/simple/{name}/{fn}",
        hashes=frozenset({Hash(algo="sha256", value="deadbeef" * 8)}),
        requires_python=">=3.9",
        yanked=False,
        yanked_reason=None,
        upload_time=None,
    )


def _make_response(
    *,
    status: str = "fresh",
    candidates: tuple[Candidate, ...] | None = None,
    etag: str | None = "etag-v1",
    last_modified: str | None = None,
    raw_meta: dict | None = None,
) -> SimplePageResponse:
    return SimplePageResponse(
        candidates=candidates if candidates is not None else (_make_candidate(),),
        etag=etag,
        last_modified=last_modified,
        raw_meta=raw_meta if raw_meta is not None else {},
        status=status,  # type: ignore[arg-type]
    )


def _make_client(
    return_value: Any = None, side_effect: Any = None
) -> MagicMock:
    """Build a PEP691Client-shaped mock with a ``.fetch`` method."""
    client = MagicMock()
    if side_effect is not None:
        client.fetch.side_effect = side_effect
    else:
        client.fetch.return_value = (
            return_value if return_value is not None else _make_response()
        )
    return client


# ---------------------------------------------------------------------------
# Constructor / config
# ---------------------------------------------------------------------------


class TestConstructor:
    """``ParallelFetcher.__init__`` config + clamping."""

    def test_defaults(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        f = ParallelFetcher(client, cache)
        assert f._max_workers == _MAX_WORKERS_CEILING == 16
        assert f._default_ttl == 600

    def test_custom_workers_below_ceiling(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        f = ParallelFetcher(client, cache, max_workers=4)
        assert f._max_workers == 4

    def test_workers_clamped_at_ceiling(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        with caplog.at_level(logging.INFO, logger="pipenv.resolver.fetcher"):
            f = ParallelFetcher(client, cache, max_workers=64)
        assert f._max_workers == _MAX_WORKERS_CEILING == 16
        assert any(
            "clamping max_workers from 64 to 16" in rec.message
            for rec in caplog.records
        ), [rec.message for rec in caplog.records]

    def test_workers_at_ceiling_no_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        with caplog.at_level(logging.INFO, logger="pipenv.resolver.fetcher"):
            f = ParallelFetcher(client, cache, max_workers=16)
        assert f._max_workers == 16
        # Exactly == ceiling does NOT trigger the clamp log.
        assert not any(
            "clamping" in rec.message for rec in caplog.records
        )

    def test_workers_zero_raises(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        with pytest.raises(ValueError, match="max_workers must be >= 1"):
            ParallelFetcher(client, cache, max_workers=0)

    def test_workers_negative_raises(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        with pytest.raises(ValueError, match="max_workers must be >= 1"):
            ParallelFetcher(client, cache, max_workers=-3)

    def test_custom_default_ttl(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        f = ParallelFetcher(client, cache, default_ttl=60)
        assert f._default_ttl == 60


# ---------------------------------------------------------------------------
# Basic dispatch — cold cache, warm cache, mixed
# ---------------------------------------------------------------------------


class TestBasicDispatch:
    """Cache hits / misses across simple target lists."""

    def test_empty_targets_returns_empty_dict(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        f = ParallelFetcher(client, cache)

        result = f.populate([])

        assert result == {}
        # Empty list fast-path: never touches the cache or client.
        assert client.fetch.call_count == 0

    def test_five_cold_targets_all_dispatch(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        names = ["pkg-a", "pkg-b", "pkg-c", "pkg-d", "pkg-e"]
        # Distinct response per package so we can assert all dispatched.
        def fake_fetch(index_url: str, package_name: str, *, if_none_match: str | None) -> SimplePageResponse:
            return _make_response(
                candidates=(_make_candidate(name=package_name, version="1.0.0"),),
                etag=f"etag-{package_name}",
            )

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache)

        result = f.populate([("https://idx.test/simple", n) for n in names])

        assert client.fetch.call_count == 5
        assert set(result) == set(names)
        for name in names:
            assert isinstance(result[name], CachedManifest)

    def test_warm_cache_zero_dispatch(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        names = ["pkg-a", "pkg-b", "pkg-c", "pkg-d", "pkg-e"]

        def fake_fetch(index_url: str, package_name: str, *, if_none_match: str | None) -> SimplePageResponse:
            return _make_response(
                candidates=(_make_candidate(name=package_name, version="1.0.0"),),
                etag=f"etag-{package_name}",
            )

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache, default_ttl=600)

        targets = [("https://idx.test/simple", n) for n in names]
        first = f.populate(targets)
        assert client.fetch.call_count == 5
        assert len(first) == 5

        # Second run: cache is warm, no further dispatches.
        client.fetch.reset_mock()
        second = f.populate(targets)
        assert client.fetch.call_count == 0
        assert len(second) == 5
        for name in names:
            assert isinstance(second[name], CachedManifest)

    def test_partial_warm_cache_dispatches_only_misses(
        self, tmp_path: Path
    ) -> None:
        cache = ParsedManifestCache(tmp_path)

        # Pre-populate the cache for 3 packages.
        warm_names = ["warm-a", "warm-b", "warm-c"]
        for name in warm_names:
            cache.put(
                "https://idx.test/simple",
                name,
                [_make_candidate(name=name)],
                etag=f"etag-{name}",
                ttl_seconds=600,
            )

        cold_names = ["cold-a", "cold-b"]

        def fake_fetch(index_url: str, package_name: str, *, if_none_match: str | None) -> SimplePageResponse:
            return _make_response(
                candidates=(_make_candidate(name=package_name),),
                etag=f"etag-{package_name}",
            )

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache)

        all_targets = [
            ("https://idx.test/simple", n) for n in warm_names + cold_names
        ]
        result = f.populate(all_targets)

        # Only the 2 cold targets should have dispatched.
        assert client.fetch.call_count == 2
        called_names = {
            call.args[1] for call in client.fetch.call_args_list
        }
        assert called_names == set(cold_names)
        # All 5 land in the result.
        assert set(result) == set(warm_names + cold_names)
        for name in warm_names + cold_names:
            assert isinstance(result[name], CachedManifest)


# ---------------------------------------------------------------------------
# Status branches — fresh / not-modified / missing
# ---------------------------------------------------------------------------


class TestStatusBranches:
    """Per-status dispatch of ``SimplePageResponse``."""

    def test_fresh_writes_cache_with_etag(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        cand = _make_candidate(name="numpy")
        client = _make_client(
            return_value=_make_response(
                candidates=(cand,), etag="strong-etag-v1"
            )
        )
        f = ParallelFetcher(client, cache, default_ttl=600)

        result = f.populate([("https://idx.test/simple", "numpy")])

        assert isinstance(result["numpy"], CachedManifest)
        # The on-disk cache holds the etag we passed through.
        on_disk = cache.get("https://idx.test/simple", "numpy")
        assert on_disk is not None
        assert on_disk.etag == "strong-etag-v1"
        assert on_disk.candidates == (cand,)

    def test_fresh_with_none_etag(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)
        cand = _make_candidate(name="numpy")
        client = _make_client(
            return_value=_make_response(candidates=(cand,), etag=None)
        )
        f = ParallelFetcher(client, cache)

        result = f.populate([("https://idx.test/simple", "numpy")])

        cm = result["numpy"]
        assert isinstance(cm, CachedManifest)
        assert cm.etag is None

    def test_missing_status_returns_FetchError_no_cache(
        self, tmp_path: Path
    ) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client(
            return_value=_make_response(
                status="missing", candidates=(), etag=None
            )
        )
        f = ParallelFetcher(client, cache)

        result = f.populate([("https://idx.test/simple", "nope")])

        err = result["nope"]
        assert isinstance(err, FetchError)
        assert err.kind == "missing"
        # No cache entry created.
        assert cache.get("https://idx.test/simple", "nope") is None

    def test_not_modified_with_prior_cache_refreshes_ttl(
        self, tmp_path: Path
    ) -> None:
        cache = ParsedManifestCache(tmp_path)
        prior_cand = _make_candidate(name="numpy", version="1.0.0")
        cache.put(
            "https://idx.test/simple",
            "numpy",
            [prior_cand],
            etag="cached-etag",
            ttl_seconds=600,
        )
        prior_before = cache.get("https://idx.test/simple", "numpy")
        assert prior_before is not None

        # populate() will see the warm hit in step-1 and short-circuit
        # WITHOUT dispatching.  To exercise the not-modified branch we
        # invalidate first, but that loses the prior `existing` value
        # inside _refresh_not_modified.  Instead, populate `to_fetch`
        # by deliberately bypassing step-1: do that by clearing the
        # populated entry but pre-seeding the cache with a (silently)
        # expired one — but ParsedManifestCache.get returns None for
        # expired.  So invoke _dispatch_fetch_result directly to test
        # the 304+prior-cache branch.  We re-prime the cache fresh
        # FIRST so _refresh_not_modified's call to cache.get finds it.
        client = _make_client(
            return_value=_make_response(
                status="not-modified", candidates=(), etag=None
            )
        )
        f = ParallelFetcher(client, cache, default_ttl=900)

        # The cache is warm (so step-1 would short-circuit).  Drive the
        # 304 branch directly via the helper.
        out = f._dispatch_fetch_result(
            "https://idx.test/simple",
            "numpy",
            _make_response(status="not-modified", candidates=(), etag=None),
        )
        assert isinstance(out, CachedManifest)
        assert out.candidates == (prior_cand,)
        # cached etag is preserved (response.etag is None → re-use existing).
        assert out.etag == "cached-etag"

    def test_not_modified_with_response_etag_overrides(
        self, tmp_path: Path
    ) -> None:
        cache = ParsedManifestCache(tmp_path)
        prior_cand = _make_candidate(name="numpy")
        cache.put(
            "https://idx.test/simple",
            "numpy",
            [prior_cand],
            etag="cached-etag",
            ttl_seconds=600,
        )
        client = _make_client()
        f = ParallelFetcher(client, cache, default_ttl=900)

        # Response carries an explicit new etag.
        out = f._dispatch_fetch_result(
            "https://idx.test/simple",
            "numpy",
            _make_response(
                status="not-modified", candidates=(), etag="server-etag-v2"
            ),
        )
        assert isinstance(out, CachedManifest)
        assert out.etag == "server-etag-v2"
        assert out.candidates == (prior_cand,)

    def test_not_modified_without_prior_cache_is_transient(
        self, tmp_path: Path
    ) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        f = ParallelFetcher(client, cache)

        out = f._dispatch_fetch_result(
            "https://idx.test/simple",
            "ghost",
            _make_response(status="not-modified", candidates=(), etag=None),
        )
        assert isinstance(out, FetchError)
        assert out.kind == "transient"
        assert "304 not-modified without prior cache entry" in out.message

    def test_unknown_status_is_transient(self, tmp_path: Path) -> None:
        """Defensive branch — Literal type makes this near-unreachable,
        but the code handles it and we want it covered."""
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        f = ParallelFetcher(client, cache)

        # Construct a SimplePageResponse with a bogus status via
        # __setattr__ (frozen dataclass — use object.__setattr__).
        resp = _make_response(status="fresh")
        object.__setattr__(resp, "status", "weird-future-status")

        out = f._dispatch_fetch_result(
            "https://idx.test/simple", "pkg", resp
        )
        assert isinstance(out, FetchError)
        assert out.kind == "transient"
        assert "unknown status" in out.message

    def test_fetch_error_returned_directly(self, tmp_path: Path) -> None:
        """A ``FetchError`` from the client passes through unchanged."""
        cache = ParsedManifestCache(tmp_path)
        err = FetchError(
            kind="auth", url="https://idx.test/simple", message="401"
        )
        client = _make_client(return_value=err)
        f = ParallelFetcher(client, cache)

        result = f.populate([("https://idx.test/simple", "pkg")])

        assert result["pkg"] is err
        # No cache entry created.
        assert cache.get("https://idx.test/simple", "pkg") is None


# ---------------------------------------------------------------------------
# Mixed outcomes
# ---------------------------------------------------------------------------


class TestMixedOutcomes:
    """End-to-end populate() with mixed per-target outcomes."""

    def test_three_fresh_one_missing_one_transient(
        self, tmp_path: Path
    ) -> None:
        cache = ParsedManifestCache(tmp_path)

        def fake_fetch(index_url: str, package_name: str, *, if_none_match: str | None):
            if package_name in {"a", "b", "c"}:
                return _make_response(
                    candidates=(_make_candidate(name=package_name),),
                    etag=f"etag-{package_name}",
                )
            if package_name == "ghost":
                return _make_response(
                    status="missing", candidates=(), etag=None
                )
            # "boom"
            return FetchError(
                kind="transient",
                url=index_url,
                message="5xx",
                original=None,
            )

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache, max_workers=4)

        result = f.populate(
            [("https://idx.test/simple", n) for n in ["a", "b", "c", "ghost", "boom"]]
        )

        assert set(result) == {"a", "b", "c", "ghost", "boom"}
        for n in ["a", "b", "c"]:
            assert isinstance(result[n], CachedManifest), result[n]
        assert isinstance(result["ghost"], FetchError)
        assert result["ghost"].kind == "missing"
        assert isinstance(result["boom"], FetchError)
        assert result["boom"].kind == "transient"

    def test_worker_exception_isolated(self, tmp_path: Path) -> None:
        cache = ParsedManifestCache(tmp_path)

        def fake_fetch(index_url: str, package_name: str, *, if_none_match: str | None):
            if package_name == "bad":
                raise RuntimeError("kaboom")
            return _make_response(
                candidates=(_make_candidate(name=package_name),),
                etag=f"etag-{package_name}",
            )

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache, max_workers=4)

        result = f.populate(
            [("https://idx.test/simple", n) for n in ["ok-1", "bad", "ok-2"]]
        )

        # All three keys present; pool didn't crash.
        assert set(result) == {"ok-1", "bad", "ok-2"}
        assert isinstance(result["ok-1"], CachedManifest)
        assert isinstance(result["ok-2"], CachedManifest)
        bad = result["bad"]
        assert isinstance(bad, FetchError)
        assert bad.kind == "transient"
        # original is preserved.
        assert isinstance(bad.original, RuntimeError)
        assert "kaboom" in str(bad.original)

    def test_base_exception_in_worker_is_transient(
        self, tmp_path: Path
    ) -> None:
        """``BaseException`` (not just ``Exception``) is caught."""
        cache = ParsedManifestCache(tmp_path)

        def fake_fetch(index_url: str, package_name: str, *, if_none_match: str | None):
            # KeyboardInterrupt is a BaseException (not Exception).
            raise KeyboardInterrupt("user cancelled")

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache, max_workers=2)

        result = f.populate([("https://idx.test/simple", "x")])

        x = result["x"]
        assert isinstance(x, FetchError)
        assert x.kind == "transient"
        assert isinstance(x.original, KeyboardInterrupt)

    def test_duplicate_package_name_across_indexes_one_wins(
        self, tmp_path: Path
    ) -> None:
        """Same ``package_name`` from two indices → one entry in the result.

        Last-completer wins; we assert the dict has exactly one entry
        (and that the one value is well-formed) — not which one.
        """
        cache = ParsedManifestCache(tmp_path)

        def fake_fetch(index_url: str, package_name: str, *, if_none_match: str | None):
            return _make_response(
                candidates=(
                    _make_candidate(
                        name=package_name, version=f"1.0.0+{index_url[-1]}"
                    ),
                ),
                etag=f"etag-{index_url}",
            )

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache, max_workers=2)

        result = f.populate(
            [
                ("https://idx-1.test/simple", "shared"),
                ("https://idx-2.test/simple", "shared"),
            ]
        )

        # Exactly one key, regardless of which worker landed last.
        assert list(result) == ["shared"]
        assert isinstance(result["shared"], CachedManifest)
        # Both fetches dispatched.
        assert client.fetch.call_count == 2


# ---------------------------------------------------------------------------
# Cache integration — get/put call counts and arg shapes
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Cache get/put plumbing on the dispatch paths."""

    def test_cache_get_called_once_per_target(self, tmp_path: Path) -> None:
        cache_mock = MagicMock()
        cache_mock.get.return_value = None
        cand = _make_candidate()
        # After put, simulate the cache returning a CachedManifest.
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cached = CachedManifest(
            candidates=(cand,),
            etag="e",
            cached_at=now,
            expires_at=now + timedelta(seconds=600),
        )
        # First get returns None (miss), subsequent ones return the manifest.
        cache_mock.get.side_effect = [None, None, None, cached, cached, cached]
        client = _make_client(return_value=_make_response(candidates=(cand,)))
        f = ParallelFetcher(client, cache_mock)

        f.populate(
            [("https://idx.test/simple", n) for n in ["a", "b", "c"]]
        )

        # 3 step-1 lookups + 3 post-put re-reads = 6.
        assert cache_mock.get.call_count == 6
        # 3 puts, one per fresh response.
        assert cache_mock.put.call_count == 3

    def test_cache_put_passes_default_ttl(self, tmp_path: Path) -> None:
        cache_mock = MagicMock()
        cache_mock.get.return_value = None
        cand = _make_candidate()
        client = _make_client(return_value=_make_response(candidates=(cand,)))
        f = ParallelFetcher(client, cache_mock, default_ttl=42)

        f.populate([("https://idx.test/simple", "numpy")])

        # Find the put call.
        put_args = cache_mock.put.call_args
        # signature: cache.put(index_url, package_name, candidates, etag=..., ttl_seconds=...)
        assert put_args.args[0] == "https://idx.test/simple"
        assert put_args.args[1] == "numpy"
        assert tuple(put_args.args[2]) == (cand,)
        assert put_args.kwargs["etag"] == "etag-v1"
        assert put_args.kwargs["ttl_seconds"] == 42

    def test_cache_put_raises_oserror_returns_transient(
        self, tmp_path: Path
    ) -> None:
        cache_mock = MagicMock()
        cache_mock.get.return_value = None
        cache_mock.put.side_effect = OSError("disk full")
        client = _make_client(return_value=_make_response())
        f = ParallelFetcher(client, cache_mock)

        result = f.populate([("https://idx.test/simple", "numpy")])

        err = result["numpy"]
        assert isinstance(err, FetchError)
        assert err.kind == "transient"
        assert "cache write failed" in err.message
        assert isinstance(err.original, OSError)

    def test_not_modified_cache_put_oserror_falls_back_to_existing(
        self, tmp_path: Path
    ) -> None:
        """``_refresh_not_modified`` soft-fails to the existing payload."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        existing = CachedManifest(
            candidates=(_make_candidate(name="numpy"),),
            etag="cached-etag",
            cached_at=now,
            expires_at=now + timedelta(seconds=600),
        )
        cache_mock = MagicMock()
        cache_mock.get.return_value = existing
        cache_mock.put.side_effect = OSError("read-only fs")
        client = _make_client()
        f = ParallelFetcher(client, cache_mock)

        out = f._dispatch_fetch_result(
            "https://idx.test/simple",
            "numpy",
            _make_response(status="not-modified", candidates=(), etag=None),
        )
        # Soft-fail: returns the in-memory ``existing`` payload.
        assert out is existing

    def test_not_modified_post_put_get_returns_none_falls_back(
        self, tmp_path: Path
    ) -> None:
        """If the re-`get` after the TTL refresh returns ``None`` (e.g.
        race / TTL=0), fall back to the in-memory ``existing``."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        existing = CachedManifest(
            candidates=(_make_candidate(name="numpy"),),
            etag="cached-etag",
            cached_at=now,
            expires_at=now + timedelta(seconds=600),
        )
        cache_mock = MagicMock()
        # First call: step-1 / _refresh_not_modified existing lookup.
        # Second call: post-put re-read returns None (the race path).
        cache_mock.get.side_effect = [existing, None]
        cache_mock.put.return_value = None
        client = _make_client()
        f = ParallelFetcher(client, cache_mock)

        out = f._dispatch_fetch_result(
            "https://idx.test/simple",
            "numpy",
            _make_response(status="not-modified", candidates=(), etag=None),
        )
        assert out is existing

    def test_ttl_zero_synthesises_in_process_manifest(
        self, tmp_path: Path
    ) -> None:
        """``ttl_seconds=0`` → re-`get` returns None (already expired);
        ``_store_fresh`` builds an in-process ``CachedManifest``."""
        # Use a real cache so the put-then-immediately-expired behaviour
        # is exercised end-to-end (ParsedManifestCache.put with
        # ``ttl_seconds=0`` writes a payload whose ``expires_at == cached_at``,
        # which ``get()`` then treats as a miss).
        cache = ParsedManifestCache(tmp_path)
        cand = _make_candidate()
        client = _make_client(
            return_value=_make_response(
                candidates=(cand,), etag="e-zero"
            )
        )
        f = ParallelFetcher(client, cache, default_ttl=0)

        result = f.populate([("https://idx.test/simple", "numpy")])

        cm = result["numpy"]
        assert isinstance(cm, CachedManifest)
        assert cm.candidates == (cand,)
        assert cm.etag == "e-zero"
        # ``expires_at == cached_at + 0`` → not in the future.
        assert cm.expires_at == cm.cached_at


# ---------------------------------------------------------------------------
# Stale-etag short-circuit (Initiative G phase-3 follow-up FU1)
# ---------------------------------------------------------------------------


class TestStaleEtagShortCircuit:
    """``ParallelFetcher.populate`` calls ``cache.peek_etag`` for misses
    so stale-but-present cache entries get a conditional GET
    (``If-None-Match: <etag>``) instead of a full re-download.

    Before FU1, T9's :meth:`_dispatch_fetch_result` handled
    ``status="not-modified"`` correctly but the branch was dead code:
    nothing in :meth:`populate` ever sent ``If-None-Match`` because
    :meth:`ParsedManifestCache.get` returned ``None`` past expiry and
    didn't expose the on-disk etag.  FU1 adds
    :meth:`ParsedManifestCache.peek_etag` (T7) and wires it in here.
    """

    def test_expired_cache_sends_if_none_match(self, tmp_path: Path) -> None:
        """Stale-but-present cache entry → ``If-None-Match: <etag>``."""
        cache = ParsedManifestCache(tmp_path)
        # Seed an immediately-expired entry with an etag.
        prior_cand = _make_candidate(name="numpy", version="0.9.0")
        cache.put(
            "https://idx.test/simple",
            "numpy",
            [prior_cand],
            etag='W/"abc"',
            ttl_seconds=0,  # expired by the time we read it
        )
        # Sanity: ``get`` hides it (so populate will treat as a miss),
        # but ``peek_etag`` recovers the etag.
        assert cache.get("https://idx.test/simple", "numpy") is None
        assert cache.peek_etag("https://idx.test/simple", "numpy") == 'W/"abc"'

        fresh_cand = _make_candidate(name="numpy", version="1.0.0")
        client = _make_client(
            return_value=_make_response(
                candidates=(fresh_cand,), etag='W/"new"'
            )
        )
        f = ParallelFetcher(client, cache)

        f.populate([("https://idx.test/simple", "numpy")])

        # The client received the stale etag as If-None-Match.
        assert client.fetch.call_count == 1
        call = client.fetch.call_args
        assert call.kwargs["if_none_match"] == 'W/"abc"'

    def test_cold_cache_sends_if_none_match_none(self, tmp_path: Path) -> None:
        """No prior cache entry → ``if_none_match=None`` (full fetch)."""
        cache = ParsedManifestCache(tmp_path)
        client = _make_client()
        f = ParallelFetcher(client, cache)

        f.populate([("https://idx.test/simple", "numpy")])

        assert client.fetch.call_count == 1
        call = client.fetch.call_args
        assert call.kwargs["if_none_match"] is None

    def test_corrupted_cache_falls_back_to_full_fetch(
        self, tmp_path: Path
    ) -> None:
        """Cache file is unreadable/corrupt → ``peek_etag`` returns
        ``None`` → fetcher dispatches a full GET (``if_none_match=None``).
        """
        cache = ParsedManifestCache(tmp_path)
        # Seed an entry, then nuke its contents (raw bytes — not JSON).
        cache.put(
            "https://idx.test/simple",
            "numpy",
            [_make_candidate(name="numpy")],
            etag="ignored",
            ttl_seconds=0,
        )
        target = cache._path_for("https://idx.test/simple", "numpy")
        target.write_bytes(b"not json")
        # Sanity: both ``get`` and ``peek_etag`` return None on corruption.
        assert cache.get("https://idx.test/simple", "numpy") is None
        assert cache.peek_etag("https://idx.test/simple", "numpy") is None

        client = _make_client()
        f = ParallelFetcher(client, cache)

        f.populate([("https://idx.test/simple", "numpy")])

        call = client.fetch.call_args
        assert call.kwargs["if_none_match"] is None

    def test_not_modified_response_refreshes_cache_with_prior_candidates(
        self, tmp_path: Path
    ) -> None:
        """End-to-end FU1 flow: expired cache → conditional GET →
        server returns 304 → cache's TTL is refreshed with the prior
        candidates.

        This was the dead-code branch before FU1 — ``populate`` never
        sent ``If-None-Match`` so the 304 path was unreachable from
        real traffic.  Now that ``peek_etag`` exists and the fetcher
        consults it, a 304 from the server refreshes the existing
        cache entry's TTL.
        """
        cache = ParsedManifestCache(tmp_path)
        prior_cand = _make_candidate(name="numpy", version="0.9.0")
        cache.put(
            "https://idx.test/simple",
            "numpy",
            [prior_cand],
            etag='W/"abc"',
            ttl_seconds=0,  # expired
        )
        # Sanity: expired.
        assert cache.get("https://idx.test/simple", "numpy") is None

        # Server returns 304 not-modified with the same etag.
        client = _make_client(
            return_value=_make_response(
                status="not-modified", candidates=(), etag='W/"abc"'
            )
        )
        f = ParallelFetcher(client, cache, default_ttl=600)

        result = f.populate([("https://idx.test/simple", "numpy")])

        # Conditional GET was sent.
        assert client.fetch.call_args.kwargs["if_none_match"] == 'W/"abc"'

        cm = result["numpy"]
        assert isinstance(cm, CachedManifest)
        # Refreshed with the prior candidates (T9's option-a contract).
        assert cm.candidates == (prior_cand,)
        assert cm.etag == 'W/"abc"'

        # And the on-disk cache is now fresh again.
        refreshed = cache.get("https://idx.test/simple", "numpy")
        assert refreshed is not None
        assert refreshed.candidates == (prior_cand,)
        assert refreshed.etag == 'W/"abc"'

    def test_peek_etag_called_only_on_miss(self, tmp_path: Path) -> None:
        """Warm-cache fast-path: no ``peek_etag`` call when ``get`` hits.

        The whole point of ``peek_etag`` is to recover from a ``get``
        miss; calling it for a hit would be pointless work.
        """
        cache_mock = MagicMock()
        # Warm hit on the first call.
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cached = CachedManifest(
            candidates=(_make_candidate(name="numpy"),),
            etag="e",
            cached_at=now,
            expires_at=now + timedelta(seconds=600),
        )
        cache_mock.get.return_value = cached
        client = _make_client()
        f = ParallelFetcher(client, cache_mock)

        f.populate([("https://idx.test/simple", "numpy")])

        # Warm hit → no fetch, no peek_etag.
        assert client.fetch.call_count == 0
        assert cache_mock.peek_etag.call_count == 0


# ---------------------------------------------------------------------------
# Concurrency — dispatch-order instrumentation, NOT wall-time
# ---------------------------------------------------------------------------


class TestConcurrency:
    """Parallelism is proven via threading.Event order, not wall-clock."""

    def test_dispatch_order_max_workers_concurrent(
        self, tmp_path: Path
    ) -> None:
        """32 targets, ``max_workers=16``.

        Mock client blocks each call until ``release_event`` is set,
        recording ``arrive_event``s.  We wait for the executor to dispatch
        as many workers as it can, then count how many had arrived BEFORE
        any returned.  Floor: 14 (the plan's 16/32 physical ceiling
        minus a small fudge for scheduling jitter).
        """
        cache = ParsedManifestCache(tmp_path)
        n_targets = 32
        max_workers = 16

        arrive_lock = threading.Lock()
        arrive_count = 0
        # Set when at least max_workers have arrived (so the assertion
        # below doesn't race the executor's ramp-up).
        ramp_up = threading.Event()
        release = threading.Event()

        def blocking_fetch(index_url: str, package_name: str, *, if_none_match: str | None):
            nonlocal arrive_count
            with arrive_lock:
                arrive_count += 1
                if arrive_count >= max_workers:
                    ramp_up.set()
            # Block until the test signals release.
            assert release.wait(timeout=10.0), "release_event timeout"
            return _make_response(
                candidates=(_make_candidate(name=package_name),),
                etag=f"etag-{package_name}",
            )

        client = _make_client(side_effect=blocking_fetch)
        f = ParallelFetcher(client, cache, max_workers=max_workers)

        targets = [
            ("https://idx.test/simple", f"pkg-{i:03d}")
            for i in range(n_targets)
        ]

        result_holder: dict[str, dict] = {}

        def driver():
            result_holder["result"] = f.populate(targets)

        t = threading.Thread(target=driver, name="populate-driver")
        t.start()
        try:
            # Wait up to 5s for ramp-up — way more than needed in practice.
            assert ramp_up.wait(timeout=5.0), (
                f"executor failed to ramp up to {max_workers} workers "
                f"(arrive_count={arrive_count})"
            )
            # Snapshot the arrive count BEFORE any worker returns.
            with arrive_lock:
                concurrent_dispatched = arrive_count
            # Floor: 14 (gracefully tolerates a small amount of OS jitter
            # around the 16-worker ceiling; physical ceiling is 16/32).
            assert concurrent_dispatched >= 14, (
                f"expected >= 14 concurrent dispatches at max_workers=16; "
                f"got {concurrent_dispatched}"
            )
            assert concurrent_dispatched <= max_workers, (
                f"executor exceeded max_workers={max_workers}: "
                f"{concurrent_dispatched}"
            )
        finally:
            release.set()
            t.join(timeout=10.0)
            assert not t.is_alive(), "driver thread did not exit"

        result = result_holder["result"]
        assert len(result) == n_targets
        for r in result.values():
            assert isinstance(r, CachedManifest)

    def test_dispatch_caps_workers_at_to_fetch_count(
        self, tmp_path: Path
    ) -> None:
        """``max_workers=min(self._max_workers, len(to_fetch))`` — don't
        over-allocate threads for a shallow queue."""
        cache = ParsedManifestCache(tmp_path)

        # Only 2 targets; max_workers=8.  At most 2 workers should arrive.
        arrive_lock = threading.Lock()
        arrive_count = 0
        release = threading.Event()

        def blocking_fetch(index_url: str, package_name: str, *, if_none_match: str | None):
            nonlocal arrive_count
            with arrive_lock:
                arrive_count += 1
            assert release.wait(timeout=10.0), "release_event timeout"
            return _make_response(
                candidates=(_make_candidate(name=package_name),),
                etag=f"etag-{package_name}",
            )

        client = _make_client(side_effect=blocking_fetch)
        f = ParallelFetcher(client, cache, max_workers=8)

        result_holder: dict = {}

        def driver():
            result_holder["result"] = f.populate(
                [("https://idx.test/simple", "a"), ("https://idx.test/simple", "b")]
            )

        t = threading.Thread(target=driver)
        t.start()
        try:
            # Spin briefly until at least one arrived (proves dispatch began),
            # then check the count is bounded by len(to_fetch)=2.
            for _ in range(500):
                with arrive_lock:
                    if arrive_count >= 1:
                        break
                # Short event-based sleep loop is acceptable here (no
                # wall-time assertion — just polling).
                release.wait(timeout=0.01)
                if release.is_set():
                    break
            with arrive_lock:
                snapshot = arrive_count
            assert snapshot <= 2, f"executor over-allocated: {snapshot} > 2"
        finally:
            release.set()
            t.join(timeout=10.0)
            assert not t.is_alive()

        assert len(result_holder["result"]) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tail-of-the-distribution scenarios."""

    def test_empty_string_index_url_passes_through(
        self, tmp_path: Path
    ) -> None:
        """T9 does not validate ``index_url``; an empty string is
        passed through to the client and the cache layer."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_candidate()
        client = _make_client(
            return_value=_make_response(candidates=(cand,))
        )
        f = ParallelFetcher(client, cache)

        result = f.populate([("", "pkg")])

        assert isinstance(result["pkg"], CachedManifest)
        # Client received the empty-string index_url unchanged.
        call = client.fetch.call_args
        assert call.args[0] == ""

    def test_duplicate_target_same_index_url(self, tmp_path: Path) -> None:
        """Same (index, name) appears twice — last-write-wins in step 1
        (warm hits replace each other in the result dict)."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_candidate()
        client = _make_client(
            return_value=_make_response(candidates=(cand,))
        )
        f = ParallelFetcher(client, cache)

        result = f.populate(
            [
                ("https://idx.test/simple", "numpy"),
                ("https://idx.test/simple", "numpy"),
            ]
        )

        # One key.  Two dispatches (both are cold on first iteration).
        # NOTE: T9 does not deduplicate; both go to to_fetch and both
        # are submitted to the executor.  The second-completer wins.
        assert list(result) == ["numpy"]
        assert isinstance(result["numpy"], CachedManifest)
        assert client.fetch.call_count == 2

    def test_non_string_package_name_propagates_as_transient(
        self, tmp_path: Path
    ) -> None:
        """A non-string in the target tuple → blows up inside the worker
        → mapped to ``FetchError(kind="transient")`` per the T9 contract."""
        cache = ParsedManifestCache(tmp_path)

        def fake_fetch(index_url, package_name, *, if_none_match):
            # `cache.get` will have already barfed with TypeError /
            # AttributeError on canonicalize_name(None) — but if we got
            # this far, blow up.
            raise TypeError("package_name must be str")

        client = _make_client(side_effect=fake_fetch)
        f = ParallelFetcher(client, cache)

        # Pre-classify: cache.get(idx, None) will raise inside the
        # canonicalize step.  We bypass step-1 by using a MagicMock cache.
        cache_mock = MagicMock()
        cache_mock.get.return_value = None
        f2 = ParallelFetcher(client, cache_mock)
        result = f2.populate([("https://idx.test/simple", None)])  # type: ignore[list-item]

        err = result[None]  # type: ignore[index]
        assert isinstance(err, FetchError)
        assert err.kind == "transient"
        assert isinstance(err.original, TypeError)

    def test_fetch_one_returns_fetch_error_unchanged(
        self, tmp_path: Path
    ) -> None:
        """``_fetch_one`` returns a ``FetchError`` from the client
        verbatim (no wrapping)."""
        cache = ParsedManifestCache(tmp_path)
        original = FetchError(
            kind="auth", url="https://idx.test", message="401"
        )
        client = _make_client(return_value=original)
        f = ParallelFetcher(client, cache)

        out = f._fetch_one(
            "https://idx.test/simple", "pkg", None
        )
        assert out is original

    def test_fetch_one_passes_if_none_match_through(
        self, tmp_path: Path
    ) -> None:
        cache = ParsedManifestCache(tmp_path)
        client = _make_client(return_value=_make_response())
        f = ParallelFetcher(client, cache)

        f._fetch_one(
            "https://idx.test/simple", "pkg", if_none_match="strong-etag"
        )

        call = client.fetch.call_args
        assert call.kwargs["if_none_match"] == "strong-etag"

    def test_populate_all_warm_no_executor_spawned(
        self, tmp_path: Path
    ) -> None:
        """Step-1 short-circuit: if every target is a warm cache hit,
        ``populate`` returns BEFORE constructing the executor."""
        cache = ParsedManifestCache(tmp_path)
        for n in ["a", "b"]:
            cache.put(
                "https://idx.test/simple",
                n,
                [_make_candidate(name=n)],
                etag=f"e-{n}",
                ttl_seconds=600,
            )
        client = _make_client()
        f = ParallelFetcher(client, cache)

        result = f.populate(
            [("https://idx.test/simple", n) for n in ["a", "b"]]
        )

        assert client.fetch.call_count == 0
        assert len(result) == 2
        for n in ["a", "b"]:
            assert isinstance(result[n], CachedManifest)


# ---------------------------------------------------------------------------
# Defensive — executor.future.result() surfaces an exception
# ---------------------------------------------------------------------------


class TestFutureExceptionPath:
    """Defensive: future.result() raises despite ``_fetch_one`` catching."""

    def test_future_result_raises_becomes_transient(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ``future.result()`` ever raises (e.g., executor-internal
        bug, cancelled future), the outer ``except BaseException`` in
        ``populate`` catches it and records a transient."""
        cache = ParsedManifestCache(tmp_path)
        client = _make_client(return_value=_make_response())
        f = ParallelFetcher(client, cache, max_workers=1)

        # Patch Future.result on the future we get back so it raises.
        import concurrent.futures as cf

        real_submit = cf.ThreadPoolExecutor.submit

        def patched_submit(self, fn, *args, **kwargs):
            future = real_submit(self, fn, *args, **kwargs)
            # Wait for the real result, then replace future.result with
            # a method that raises.
            future.result()
            future.result = MagicMock(  # type: ignore[method-assign]
                side_effect=RuntimeError("executor-internal")
            )
            return future

        monkeypatch.setattr(
            cf.ThreadPoolExecutor, "submit", patched_submit
        )

        result = f.populate([("https://idx.test/simple", "pkg")])

        err = result["pkg"]
        assert isinstance(err, FetchError)
        assert err.kind == "transient"
        assert isinstance(err.original, RuntimeError)
        assert "executor-internal" in str(err.original)
