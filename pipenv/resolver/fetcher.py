"""Parallel simple-API fetch driver for the pure-Python resolver
(Initiative G phase 1, T9).

See:

* ``docs/dev/initiative-g-pure-python-design.md`` §5.3 — authoritative
  spec for the concurrency model and error-handling matrix.
* ``initiative-g-phase1-2-plan.md`` T9 — this task.

The :class:`ParallelFetcher` ties together T7's
:class:`pipenv.resolver.manifest_cache.ParsedManifestCache` and T8's
:class:`pipenv.resolver.pep691.PEP691Client`.  Given a list of
``(index_url, package_name)`` targets, it concurrently populates the
cache via a :class:`concurrent.futures.ThreadPoolExecutor`, tolerating
per-target failures so one bad target cannot stop the others.

Concurrency model
-----------------

* :class:`concurrent.futures.ThreadPoolExecutor` with at most 16
  workers — matches urllib3's default connection-pool size; beyond
  that the pool emits ``"Connection pool is full, discarding
  connection"`` warnings (verified empirically in phase-5).  Callers
  who pass ``max_workers > 16`` are clamped to 16 with an INFO log
  line so the cap is observable.
* Workers never share mutable state inside :class:`ParallelFetcher`
  itself.  Cache writes go through :meth:`ParsedManifestCache.put`,
  which uses atomic ``os.replace`` per the T7 contract — concurrent
  writers to the same ``(index_url, package_name)`` are
  last-rename-wins, no corruption.

304 / not-modified handling
---------------------------

When the client returns ``status="not-modified"`` we currently keep
the existing cached payload and **re-`put` it** so that ``expires_at``
is refreshed to ``now + default_ttl``.  T7's cache has no public
"bump expires_at" method, so option (a) from the T9 brief (full
re-put with the existing candidates + a fresh ``cached_at``) is the
simplest correct behaviour — it avoids the alternative cliff where a
warm-but-server-confirmed-unchanged manifest would re-expire on the
next call and force another (also-conditional) round-trip.

Stale-but-present etag handling
-------------------------------

T7's :meth:`ParsedManifestCache.get` returns ``None`` past expiry —
the on-disk file is still there but the cache layer hides it.
Phase-3 follow-up FU1 added :meth:`ParsedManifestCache.peek_etag`,
which reads the on-disk etag regardless of expiry.  This module's
:meth:`ParallelFetcher.populate` now consults it on every cache miss:

* fresh cache hit (``cache.get`` returns a :class:`CachedManifest`) →
  no fetch, warm-cache fast path.
* stale-but-present (``cache.get`` returns ``None`` but
  ``cache.peek_etag`` returns an etag string) → conditional GET with
  ``If-None-Match: <etag>``.  A 304 from the server hits the
  ``status="not-modified"`` branch of :meth:`_dispatch_fetch_result`
  and the existing candidates get their TTL refreshed via T9's
  option-a re-put.
* truly missing or corrupt cache (``peek_etag`` returns ``None``) →
  full GET with ``if_none_match=None``.

Per-target failures
-------------------

Every worker call to :meth:`PEP691Client.fetch` is wrapped in a
top-level ``try`` so a programming bug in the client (or a
caller-supplied mock that raises) cannot kill the worker.  The result
dict surfaces such a failure as
``FetchError(kind="transient", ...)``.

The whole class is thread-safe by design — no shared mutable state on
the instance; ``self._client`` and ``self._cache`` are read-only after
construction.

Critical constraint (enforced by the T17 pre-commit gate):
**this module must not import from patched-pip's internal package.**
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Sequence

from pipenv.resolver.candidate import Candidate
from pipenv.resolver.manifest_cache import CachedManifest, ParsedManifestCache
from pipenv.resolver.pep691 import PEP691Client
from pipenv.resolver.pep691_types import FetchError, SimplePageResponse

_LOGGER = logging.getLogger(__name__)

#: Hard ceiling on worker count — matches urllib3's default
#: ``PoolManager(num_pools=10, maxsize=10)`` derivative we use in the
#: resolver (we override to 16 pools / 16 maxsize in T18; beyond 16 the
#: pool starts emitting "Connection pool is full" warnings).
_MAX_WORKERS_CEILING = 16


class ParallelFetcher:
    """Concurrent simple-API fetcher driving PEP691Client + ParsedManifestCache.

    Per-target failures do not stop other workers.  Returns a dict
    keyed by ``package_name`` (last-fetch-wins when the same name
    appears across multiple sources — non-deterministic with parallel
    workers, tests cover this).

    Workers are capped at 16 — matches urllib3's default
    connection-pool size; beyond that the pool emits ``"Connection
    pool is full, discarding connection"`` warnings (verified
    empirically in phase-5).  Callers passing a larger ``max_workers``
    are clamped to 16 with an INFO log line.
    """

    def __init__(
        self,
        client: PEP691Client,
        cache: ParsedManifestCache,
        *,
        max_workers: int = _MAX_WORKERS_CEILING,
        default_ttl: int = 600,
    ) -> None:
        if max_workers < 1:
            raise ValueError(
                f"max_workers must be >= 1, got {max_workers!r}"
            )
        if max_workers > _MAX_WORKERS_CEILING:
            _LOGGER.info(
                "ParallelFetcher: clamping max_workers from %d to %d "
                "(urllib3 connection-pool ceiling)",
                max_workers,
                _MAX_WORKERS_CEILING,
            )
            max_workers = _MAX_WORKERS_CEILING
        self._client = client
        self._cache = cache
        self._max_workers = max_workers
        self._default_ttl = default_ttl

    def populate(
        self,
        targets: Sequence[tuple[str, str]],
    ) -> dict[str, CachedManifest | FetchError]:
        """Populate the cache for ``targets`` concurrently.

        Algorithm (per T9 brief, updated with FU1):

        1. For each ``(index_url, package_name)``, check the cache.
           A fresh hit records the existing :class:`CachedManifest` in
           the result dict and **does NOT** dispatch a fetch (warm-cache
           fast path).
        2. For an expired-or-missing entry, recover any stale etag via
           :meth:`ParsedManifestCache.peek_etag` and dispatch a fetch
           via :class:`concurrent.futures.ThreadPoolExecutor`.  The
           stale etag (if any) becomes the ``If-None-Match`` header so
           a server-side unchanged manifest collapses into a 304 and
           the existing candidates get their TTL refreshed instead of
           re-downloading the full body (FU1, see module docstring).
        3. Post-fetch dispatch:

           * ``status="fresh"`` → ``cache.put(...)``; re-``cache.get``
             to surface a :class:`CachedManifest` in the result dict
             (consistent value-type with the warm-cache path).
           * ``status="not-modified"`` → re-``cache.put`` with the
             previously-cached candidates so ``expires_at`` slides
             forward by ``default_ttl``.  Option (a) from the T9
             brief — see module docstring for the rationale.
           * ``status="missing"`` → record a
             ``FetchError(kind="missing", ...)`` in the result dict.
           * :class:`FetchError` → record directly; do not touch the
             cache.

        4. ``_fetch_one`` (worker function) catches every exception so
           a single bad worker cannot crash the executor.  ``populate``
           itself never raises on a per-target failure.

        Returns
        -------
        ``dict`` keyed by ``package_name``.  When a name appears in
        multiple ``(index_url, package_name)`` targets, the value is
        whichever worker completed last (non-deterministic with
        parallel workers).
        """
        # Empty targets list: skip the executor altogether so we don't
        # pay its thread-startup cost for a no-op.
        if not targets:
            return {}

        result: dict[str, CachedManifest | FetchError] = {}

        # Step 1 + 2: classify targets into "warm-cache hit" vs
        # "needs-fetch".  Warm hits land in `result` directly; misses
        # go to the executor.  For misses, recover any stale-but-present
        # etag via ``peek_etag`` so the worker can send
        # ``If-None-Match`` and collapse an unchanged manifest into a
        # 304 (FU1).
        to_fetch: list[tuple[str, str, str | None]] = []
        for index_url, package_name in targets:
            existing = self._cache.get(index_url, package_name)
            if existing is not None:
                # Warm-cache fast path — no network.  Last-write-wins
                # if the same package_name appears twice (deterministic
                # here because we iterate `targets` in order).
                result[package_name] = existing
                continue
            # Miss — see if we have a stale etag we can revalidate with.
            stale_etag = self._cache.peek_etag(index_url, package_name)
            to_fetch.append((index_url, package_name, stale_etag))

        if not to_fetch:
            return result

        # Step 3: dispatch the misses on the executor.  `max_workers`
        # is min(self._max_workers, len(to_fetch)) so we don't spin up
        # idle threads when the work queue is shallow.
        workers = min(self._max_workers, len(to_fetch))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="pipenv-fetch",
        ) as ex:
            futures = {
                ex.submit(
                    self._fetch_one, idx_url, pkg, if_none_match
                ): (idx_url, pkg)
                for (idx_url, pkg, if_none_match) in to_fetch
            }
            for future in concurrent.futures.as_completed(futures):
                idx_url, package_name = futures[future]
                # `_fetch_one` catches everything, but defend against a
                # FutureCancelled or executor-internal failure anyway.
                try:
                    fetch_result = future.result()
                except BaseException as exc:  # noqa: BLE001
                    _LOGGER.debug(
                        "executor surfaced unexpected exception for %s "
                        "package=%r: %r",
                        idx_url,
                        package_name,
                        exc,
                    )
                    result[package_name] = FetchError(
                        kind="transient",
                        url=idx_url,
                        message=str(exc),
                        original=exc if isinstance(exc, BaseException) else None,
                    )
                    continue

                result[package_name] = self._dispatch_fetch_result(
                    idx_url, package_name, fetch_result
                )

        return result

    # ---- worker + dispatch helpers ----------------------------------

    def _fetch_one(
        self,
        index_url: str,
        package_name: str,
        if_none_match: str | None,
    ) -> SimplePageResponse | FetchError:
        """Run on a worker thread.  Never raises.

        :meth:`PEP691Client.fetch` is already documented as
        non-raising, but a programming bug (or a test mock that
        raises) shouldn't crash the worker — so we wrap defensively
        and map any escapee to a transient :class:`FetchError`.
        """
        try:
            return self._client.fetch(
                index_url, package_name, if_none_match=if_none_match
            )
        except BaseException as exc:  # noqa: BLE001
            _LOGGER.debug(
                "client.fetch raised (should not happen) for %s package=%r: %r",
                index_url,
                package_name,
                exc,
            )
            return FetchError(
                kind="transient",
                url=index_url,
                message=str(exc),
                original=exc if isinstance(exc, BaseException) else None,
            )

    def _dispatch_fetch_result(
        self,
        index_url: str,
        package_name: str,
        fetch_result: SimplePageResponse | FetchError,
    ) -> CachedManifest | FetchError:
        """Map a :class:`SimplePageResponse` / :class:`FetchError` to
        the dict value, with cache side-effects per the T9 brief.
        """
        if isinstance(fetch_result, FetchError):
            return fetch_result

        if fetch_result.status == "fresh":
            return self._store_fresh(index_url, package_name, fetch_result)

        if fetch_result.status == "not-modified":
            return self._refresh_not_modified(index_url, package_name, fetch_result)

        if fetch_result.status == "missing":
            return FetchError(
                kind="missing",
                url=index_url,
                message="404",
                original=None,
            )

        # Defensive: an unknown status is treated as transient.  Should
        # be unreachable given SimplePageStatus is a Literal.
        _LOGGER.debug(
            "unknown SimplePageResponse.status=%r for %s package=%r",
            fetch_result.status,
            index_url,
            package_name,
        )
        return FetchError(
            kind="transient",
            url=index_url,
            message=f"unknown status: {fetch_result.status!r}",
            original=None,
        )

    def _store_fresh(
        self,
        index_url: str,
        package_name: str,
        response: SimplePageResponse,
    ) -> CachedManifest | FetchError:
        """Persist a ``status="fresh"`` response, re-read for consistency."""
        try:
            self._cache.put(
                index_url,
                package_name,
                response.candidates,
                etag=response.etag,
                ttl_seconds=self._default_ttl,
            )
        except OSError as exc:
            _LOGGER.debug(
                "cache.put failed for %s package=%r: %r",
                index_url,
                package_name,
                exc,
            )
            return FetchError(
                kind="transient",
                url=index_url,
                message=f"cache write failed: {exc}",
                original=exc,
            )

        # Re-read so the dict value is a CachedManifest (matches the
        # warm-cache fast-path's value type).  In the rare case the
        # put-then-get-immediately-expired race fires (ttl_seconds == 0),
        # synthesize a CachedManifest in-process to keep the contract.
        cached = self._cache.get(index_url, package_name)
        if cached is not None:
            return cached
        # ttl_seconds=0 → already-expired by the time we re-`get`.
        # Build the equivalent CachedManifest in-process; this is a
        # tests-and-edge-cases path, not a normal-flow one.
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        return CachedManifest(
            candidates=tuple(response.candidates),
            etag=response.etag,
            cached_at=now,
            expires_at=now + timedelta(seconds=self._default_ttl),
        )

    def _refresh_not_modified(
        self,
        index_url: str,
        package_name: str,
        response: SimplePageResponse,
    ) -> CachedManifest | FetchError:
        """Handle a ``status="not-modified"`` response.

        Option (a) from the T9 brief: re-``put`` the existing
        candidates with the same etag so ``expires_at`` slides forward.

        We reach this branch when:

        * the cache had a fresh entry but the server still emitted
          304 (unusual — a well-behaved fetcher wouldn't send
          ``If-None-Match`` for a fresh entry, but tests / odd
          servers can hit this); or
        * (after FU1) the cache had a stale-but-extant entry that
          :meth:`populate` sent through with ``If-None-Match``, and the
          server confirmed it's still current.  This is the common
          phase-3 path.

        Source of "existing" candidates: prefer the fresh cache (cheap,
        in-process), fall back to the stale on-disk payload via
        :meth:`ParsedManifestCache._load_manifest` so the FU1
        stale-cache short-circuit can actually refresh the entry's
        TTL instead of bailing out as a transient.
        """
        existing = self._cache.get(index_url, package_name)
        if existing is None:
            # Fresh-cache miss — peek at the (possibly expired) on-disk
            # payload.  FU1: this is how the stale-cache short-circuit
            # recovers the previously-stored candidates so option-a
            # TTL refresh actually does something useful.
            existing = self._cache._load_manifest(index_url, package_name)

        candidates: Sequence[Candidate]
        etag = response.etag

        if existing is not None:
            candidates = existing.candidates
            if etag is None:
                etag = existing.etag
        else:
            # 304 without any prior cache entry — unusual but well-defined.
            # We have no candidates to refresh; record a transient so the
            # caller can decide to retry without `If-None-Match` next time.
            _LOGGER.debug(
                "304 not-modified without prior cache entry for %s package=%r",
                index_url,
                package_name,
            )
            return FetchError(
                kind="transient",
                url=index_url,
                message="304 not-modified without prior cache entry",
                original=None,
            )

        try:
            self._cache.put(
                index_url,
                package_name,
                candidates,
                etag=etag,
                ttl_seconds=self._default_ttl,
            )
        except OSError as exc:
            _LOGGER.debug(
                "cache.put (TTL refresh) failed for %s package=%r: %r",
                index_url,
                package_name,
                exc,
            )
            # Soft-fail: we still have the in-memory `existing` payload.
            return existing

        refreshed = self._cache.get(index_url, package_name)
        return refreshed if refreshed is not None else existing


__all__ = ["ParallelFetcher"]
