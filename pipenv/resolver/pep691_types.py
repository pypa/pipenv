"""Response and error types for the pure-Python PEP 691 simple-API client
(Initiative G phase 1, T3).

See:

* ``docs/dev/initiative-g-pure-python-design.md`` §5.1 — the authoritative
  definitions of :class:`SimplePageResponse` and :class:`FetchError`.
* ``initiative-g-phase1-2-plan.md`` T3 — this task.

This module deliberately lives **alongside** ``pep691.py`` (which holds
the parser + client landing in T4 / T5 / T8) rather than inside it.
Keeping the pure-data types in their own module:

1. lets T9 (``ParallelFetcher``) and T7 (``ParsedManifestCache``) import
   :class:`FetchError` / :class:`SimplePageResponse` without dragging in
   the parser or the urllib3 client; and
2. keeps ``pep691.py`` focused on parsing and HTTP semantics.

Critical constraint (enforced by the T17 pre-commit gate when it ships):
**this module must not import from patched-pip's internal package.**
Initiative G's whole purpose is to replace pip-internal data shapes with
a pipenv-owned typed model, so any regression here defeats the
initiative.

Phase-1 scope: data-only.  No I/O, no parsing logic, no HTTP code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pipenv.resolver.candidate import Candidate

#: Outcome label for a simple-API fetch that did not fail outright.
#:
#: * ``"fresh"`` — the server returned a 200 with a response body the
#:   parser successfully turned into candidates.
#: * ``"not-modified"`` — the server returned a 304 in response to our
#:   conditional GET (``If-None-Match``); the caller should keep using
#:   the candidates it already has cached.
#: * ``"missing"`` — the server returned a 404 for this package.  Not an
#:   error per se (the package may legitimately not exist on this index),
#:   so it rides on :class:`SimplePageResponse` rather than
#:   :class:`FetchError`.
SimplePageStatus = Literal["fresh", "not-modified", "missing"]

#: Classification of a hard simple-API fetch failure.
#:
#: * ``"missing"`` — the index returned a definitive "no such package"
#:   signal.  Distinct from :data:`SimplePageStatus` ``"missing"`` only
#:   in that the fetcher (T9) may promote a 404 to a :class:`FetchError`
#:   when *every* configured index for a package returned 404.
#: * ``"transient"`` — network error, 5xx, timeout, or any other condition
#:   a retry might recover from.  T9's retry policy keys off this label.
#: * ``"auth"`` — 401 or 403.  Caller surfaces credentials guidance to the
#:   user; we do not retry these.
FetchErrorKind = Literal["missing", "transient", "auth"]


@dataclass(frozen=True, slots=True)
class SimplePageResponse:
    """Result of a successful (non-error) simple-API fetch.

    Mirrors design §5.1 exactly.  Frozen + slotted to match the rest of
    the resolver's data layer (see :class:`pipenv.resolver.candidate.Candidate`).

    Field semantics
    ---------------
    candidates:
        Parsed artifacts for the requested package, in the order the
        index returned them.  Empty tuple for ``status == "not-modified"``
        (caller already has the candidates) and ``status == "missing"``
        (package not on this index).
    etag:
        ETag header value from the response, suitable for a subsequent
        conditional GET via ``If-None-Match``.  ``None`` when the server
        did not supply one.
    last_modified:
        ``Last-Modified`` header value, kept for completeness.  Phase 1
        does not use it for conditional GETs (we rely on ETag), but it
        rides along so downstream phases can opt in without a schema
        change.
    raw_meta:
        Raw ``meta`` block parsed from PEP 691 JSON (api-version, plus
        any forward-compat fields PyPI may add later).  ``dict`` rather
        than ``dict[str, Any]`` so future PyPI additions land in this
        bucket without a type-check failure.  Empty dict for PEP 503 HTML
        responses (HTML has no ``meta`` block).
    status:
        See :data:`SimplePageStatus`.
    """

    candidates: tuple[Candidate, ...]
    etag: str | None
    last_modified: str | None
    raw_meta: dict
    status: SimplePageStatus


@dataclass(frozen=True, slots=True)
class FetchError:
    """A hard failure from the simple-API client.

    Returned by :class:`pipenv.resolver.pep691.PEP691Client` (T8) when a
    fetch cannot be turned into a :class:`SimplePageResponse`.  T9's
    :class:`pipenv.resolver.fetcher.ParallelFetcher` records these in its
    result dict so per-target failures do not stop other workers.

    Field semantics
    ---------------
    kind:
        See :data:`FetchErrorKind`.  Drives retry policy in T9.
    url:
        The URL that was being fetched, with credentials already stripped
        (T6's :func:`extract_url_credentials` is applied before this
        object is constructed — we never store credentials anywhere).
    message:
        Human-readable summary suitable for user-facing log output.
        Should not contain URL credentials, secrets, or stack traces.
    original:
        The underlying exception, if any, for debugging.  ``None`` when
        the failure was indicated by HTTP status alone (e.g., a clean 404
        / 401 with no Python-level exception).  Kept off the user-facing
        log path: only the resolver-debug log surfaces this field.
    """

    kind: FetchErrorKind
    url: str
    message: str
    original: BaseException | None = None


__all__ = [
    "FetchError",
    "FetchErrorKind",
    "SimplePageResponse",
    "SimplePageStatus",
]
