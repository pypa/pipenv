"""Wheel ``METADATA`` fetcher for the pure-Python resolver backend
(Initiative G Phase 3, T2).

Two-tier strategy per design §5.2:

1. **PEP 658 fast path** — when the index advertises ``core-metadata``
   on a candidate, GET ``<wheel_url>.metadata`` (or the explicit
   advertised URL), verify the advertised hash, and parse via stdlib
   :mod:`email.parser`.  Cost: one small HTTP GET per wheel (~3–5 kB
   typical).

2. **Wheel-head fallback** — for indexes that don't advertise PEP 658
   or for candidates whose ``.metadata`` file is missing, HTTP ``HEAD``
   the wheel URL to read ``Content-Length``, then issue a range GET
   for the last ~64 kB to capture the zip central directory.  Parse
   the directory via :mod:`zipfile`, locate ``<dist-info>/METADATA``,
   then issue a second range covering just that entry, decompress, and
   parse.

   When the server rejects ``HEAD`` (some private indexes return 405 /
   403) the fetcher probes with a tiny range ``GET`` and reads the
   length out of ``Content-Range`` instead.

A small on-disk :class:`MetadataCache` keyed by ``sha256(wheel_url)``
short-circuits both paths on repeat resolves.  Wheels are immutable on
PyPI so cache entries are valid forever; corruption is silently
treated as a miss (caller refetches and overwrites — same contract as
:class:`pipenv.resolver.manifest_cache.ParsedManifestCache`).

Critical constraint (enforced by the T17 pre-commit gate):
**this module must not import from patched-pip's internal package.**
Vendored ``packaging`` and patched-pip's vendored ``urllib3`` /
``requests`` are permitted; ``pip._internal`` is not.  The HTTP layer
is a duck-typed ``session`` parameter — production hands us the same
session shape as the PEP 691 client uses; tests pass a
:class:`unittest.mock.MagicMock`.

The :class:`Candidate` shape (Phase 1) does not yet carry PEP 658
advertisement.  T2 therefore accepts ``metadata_url`` and
``metadata_hash`` as keyword parameters to :func:`fetch_metadata`;
T3 / T7 are free to widen :class:`Candidate` later and pass the values
through transparently.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass
from email import policy as email_policy
from email.parser import HeaderParser
from pathlib import Path
from typing import Any

from pipenv.resolver.candidate import Candidate
from pipenv.vendor.packaging.utils import canonicalize_name

__all__ = [
    "CoreMetadata",
    "MetadataCache",
    "MetadataFetchError",
    "fetch_metadata",
]

_LOGGER = logging.getLogger(__name__)

# How many bytes from the wheel's tail we ask for on the first range
# GET when probing the central directory.  64 kB covers the directory
# of every PyPI wheel surveyed in design §5.2; if the central
# directory is larger, :class:`_PartialFile` re-issues with a bigger
# window.
_CENTRAL_DIRECTORY_PROBE_BYTES = 65_536

# Cap on the wheel-tail window before we give up and treat the wheel
# as unsupported by the range-fetch path.  1 MB is well past any real
# central-directory size; beyond this we fall through to a
# :class:`MetadataFetchError` so the backend can surface the issue
# instead of looping on ever-larger ranges.
_MAX_CENTRAL_DIRECTORY_WINDOW = 1_048_576

# Timeout budget for one HTTP call.  Mirrors the simple-API client's
# defaults (see pep691.py); metadata fetches are part of resolve and
# must fail fast on a flaky mirror.
_DEFAULT_CONNECT_TIMEOUT = 10.0
_DEFAULT_READ_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Public dataclass surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoreMetadata:
    """Parsed core metadata for one wheel candidate.

    Fields mirror PEP 643 + PEP 658's METADATA subset that drives
    dependency resolution.  All fields except ``name`` and ``version``
    are best-effort: a wheel with a malformed Requires-Python header,
    for example, populates the rest of the dataclass and leaves
    ``requires_python = None`` so the resolver can still make progress.
    """

    name: str
    """PEP 503-canonical package name (lowercase, ``-`` separators)."""

    version: str
    """PEP 440 version string as it appears in METADATA."""

    requires_python: str | None
    """Raw ``Requires-Python`` specifier, or ``None`` if absent."""

    requires_dist: tuple[str, ...]
    """Each ``Requires-Dist`` header as a raw string, in source order."""

    provides_extras: frozenset[str]
    """Set of ``Provides-Extra`` names declared by the wheel."""

    summary: str | None
    """One-line ``Summary`` header value, for diagnostics."""


class MetadataFetchError(Exception):
    """Raised when metadata cannot be fetched / verified.

    Carries a human-readable message; callers (T9 backend) translate
    into ``ResolverResponse.result = InternalError(...)`` so the user
    sees the wheel URL and the failure mode.
    """


# ---------------------------------------------------------------------------
# On-disk cache
# ---------------------------------------------------------------------------


_CACHE_SCHEMA_VERSION = 1


class MetadataCache:
    """Filesystem-backed cache of parsed :class:`CoreMetadata`.

    Layout::

        <root>/<sha256(wheel_url)>.json

    The wheel URL is the cache key because wheels are content-addressed
    on PyPI: same URL → same bytes → same metadata, forever.  Atomic
    writes go through ``tempfile`` + ``os.replace`` exactly the same
    way :class:`pipenv.resolver.manifest_cache.ParsedManifestCache`
    does, so a crashed write never leaves a partial file at the target.

    Corruption (missing keys, wrong schema_version, unreadable JSON)
    is silently treated as a miss; the caller refetches and overwrites
    on the next ``put``.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def get(self, wheel_url: str) -> CoreMetadata | None:
        """Return cached metadata for ``wheel_url`` or ``None`` on miss.

        ``None`` is returned for any failure mode (file missing,
        ``OSError`` on read, malformed JSON, wrong schema version,
        missing required keys).  We never raise on a cache miss — a
        corrupt entry must not block a resolve, only force a refetch.
        """
        target = self._path_for(wheel_url)
        try:
            raw = target.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return None

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
            return None

        try:
            return CoreMetadata(
                name=payload["name"],
                version=payload["version"],
                requires_python=payload.get("requires_python"),
                requires_dist=tuple(payload.get("requires_dist") or ()),
                provides_extras=frozenset(payload.get("provides_extras") or ()),
                summary=payload.get("summary"),
            )
        except (KeyError, TypeError):
            return None

    def put(self, wheel_url: str, metadata: CoreMetadata) -> None:
        """Atomically write ``metadata`` to disk under ``wheel_url``'s key.

        Same temp-file + ``os.replace`` pattern as
        :class:`ParsedManifestCache.put`: a crash mid-write leaves the
        previous payload (if any) intact; the only possible litter is
        a ``<target>.<rand>.tmp`` file that the next successful write
        will leave alone.
        """
        target = self._path_for(wheel_url)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "name": metadata.name,
            "version": metadata.version,
            "requires_python": metadata.requires_python,
            "requires_dist": list(metadata.requires_dist),
            # Sort so repeated put() of the same metadata produces
            # bit-identical files (useful for cache-corruption
            # debugging — diffing two cache files highlights the real
            # delta, not set ordering).
            "provides_extras": sorted(metadata.provides_extras),
            "summary": metadata.summary,
        }

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        tmp = tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(parent),
            prefix=target.name + ".",
            suffix=".tmp",
        )
        try:
            try:
                tmp.write(body)
                tmp.flush()
                os.fsync(tmp.fileno())
            finally:
                tmp.close()
            os.replace(tmp.name, str(target))
        except BaseException:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise

    def _path_for(self, wheel_url: str) -> Path:
        """Map ``wheel_url`` → on-disk filename.

        Full sha256 (64 chars) to avoid prefix-collision between two
        distinct wheel URLs that happen to share a 64-char prefix —
        same rationale as :meth:`ParsedManifestCache._path_for`.
        """
        digest = hashlib.sha256(wheel_url.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.json"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_metadata(
    candidate: Candidate,
    session: Any,
    *,
    cache: MetadataCache | None = None,
    metadata_url: str | None = None,
    metadata_hash: dict[str, str] | None = None,
) -> CoreMetadata:
    """Return parsed :class:`CoreMetadata` for ``candidate``.

    Algorithm:

    1. If ``cache`` is supplied and has an entry for ``candidate.url``,
       return it (no network).
    2. If ``metadata_url`` is supplied (PEP 658 fast path), GET it,
       verify against ``metadata_hash`` if non-empty, parse.
    3. Otherwise: HEAD the wheel URL to read ``Content-Length`` (fall
       back to a tiny range GET if HEAD is rejected), then range-GET
       the last 64 kB of the wheel to capture the zip central
       directory, locate the ``METADATA`` entry, range-GET its
       compressed bytes, decompress, parse.
    4. Populate the cache (if supplied) before returning.

    Raises :class:`MetadataFetchError` on any unrecoverable failure —
    hash mismatch, malformed METADATA body, missing METADATA in the
    zip, an HTTP-level failure that the simpler probe + range fetch
    could not work around, etc.

    Parameters
    ----------
    candidate:
        The :class:`Candidate` whose metadata we need.
    session:
        Duck-typed HTTP session whose ``request(method, url, *,
        headers=...)`` returns an object with ``.status``, ``.data``,
        ``.headers``.  Same shape the rest of ``pipenv.resolver`` uses
        — production hands us a configured ``urllib3.PoolManager``;
        tests use :class:`unittest.mock.MagicMock`.
    cache:
        Optional :class:`MetadataCache` for read-through caching.
    metadata_url:
        Optional explicit URL for the PEP 658 ``.metadata`` companion
        file.  When ``None`` and ``metadata_hash`` is also ``None``,
        the wheel-head fallback is used directly.
    metadata_hash:
        Optional ``{algo: hexvalue}`` mapping advertised by the index
        for the metadata body.  Only ``sha256`` is honoured; other
        algos are ignored.  When the dict is empty or absent on the
        PEP 658 path, the hash check is skipped (some indexes
        advertise the URL but not the hash).

    Sdist branch (Initiative G Phase 3b, T_S2)
    -----------------------------------------
    When ``candidate.is_wheel`` is ``False`` we delegate entirely to
    :func:`pipenv.resolver.pure_python_sdist.extract_metadata_from_sdist`,
    which honours / populates the same :class:`MetadataCache`.  The
    branch sits **after** the local cache short-circuit so a populated
    cache entry skips both the sdist build and the import of the
    heavier ``pyproject_hooks`` + ``tarfile`` machinery.  The
    consequence is a one-extra ``cache.get`` on a cold sdist (T_S1
    will call ``cache.get`` again internally), but that's a cheap
    file-stat / read + parse vs. an entire archive download + build —
    negligible.  The local import in the sdist branch keeps the
    wheel-only resolves (the 99 % common case) free of the
    ``pyproject_hooks`` + ``tarfile`` + ``zipfile`` import cost.
    """
    if cache is not None:
        cached = cache.get(candidate.url)
        if cached is not None:
            return cached

    # T_S2: sdist candidates take a fundamentally different path
    # (download + PEP 517 build + parse).  Delegate to T_S1's
    # extractor, forwarding the same cache instance so the on-disk
    # ``sha256(candidate.url)`` key is shared with the wheel side.
    if not getattr(candidate, "is_wheel", True):
        # Local import: pyproject_hooks + tarfile machinery is heavy
        # and not needed for wheel-only resolves.  Cold-import cost
        # only paid the first time a sdist candidate appears in a
        # resolve.
        from pipenv.resolver.pure_python_sdist import (
            extract_metadata_from_sdist,
        )
        return extract_metadata_from_sdist(candidate, session, cache=cache)

    if metadata_url is not None:
        metadata = _fetch_pep658(session, metadata_url, metadata_hash)
    else:
        metadata = _fetch_via_wheel_head(session, candidate.url)

    if cache is not None:
        try:
            cache.put(candidate.url, metadata)
        except OSError as exc:
            # Cache write failure is non-fatal — we have the metadata
            # in hand and can return it.  Log at debug so cache-disk-full
            # scenarios surface in --verbose without poisoning normal runs.
            _LOGGER.debug(
                "metadata cache write failed for %s: %s",
                candidate.url,
                exc,
            )

    return metadata


# ---------------------------------------------------------------------------
# PEP 658 fast path
# ---------------------------------------------------------------------------


def _fetch_pep658(
    session: Any,
    metadata_url: str,
    metadata_hash: dict[str, str] | None,
) -> CoreMetadata:
    """GET ``metadata_url``, verify the advertised hash, return parsed body."""
    body = _http_get(session, metadata_url)
    _verify_hash(body, metadata_hash, where=metadata_url)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        # METADATA is RFC 822-ish ASCII / UTF-8 in practice; a non-UTF-8
        # body is almost certainly a captive-portal HTML response or
        # similar.  Surface it explicitly rather than silently
        # producing a half-parsed dataclass.
        raise MetadataFetchError(
            f"metadata body at {metadata_url} is not UTF-8: {exc}"
        ) from exc
    return _parse_metadata_text(text)


def _verify_hash(
    body: bytes,
    metadata_hash: dict[str, str] | None,
    *,
    where: str,
) -> None:
    """Verify ``body`` matches ``metadata_hash[sha256]`` if advertised.

    PEP 658 specifies ``sha256`` as the algo in the simple-API
    ``core-metadata`` field's dict form.  Empty / missing dict skips
    the check (some indexes advertise the URL but not the hash;
    refusing to fetch them would be worse than trusting the body).
    """
    if not metadata_hash:
        return
    advertised = metadata_hash.get("sha256")
    if not advertised:
        # No sha256 specifically advertised; nothing we can verify.
        return
    actual = hashlib.sha256(body).hexdigest()
    if actual != advertised:
        raise MetadataFetchError(
            f"sha256 mismatch on PEP 658 metadata at {where}: "
            f"advertised {advertised!r}, computed {actual!r}"
        )


# ---------------------------------------------------------------------------
# Wheel-head fallback
# ---------------------------------------------------------------------------


def _fetch_via_wheel_head(session: Any, wheel_url: str) -> CoreMetadata:
    """Range-fetch the wheel's central directory + METADATA entry, parse.

    Two-step fetch:

    1. Discover ``Content-Length`` via ``HEAD``.  On 405 / 403 / any
       non-200 we fall back to a tiny range ``GET`` (``bytes=0-1``) and
       read the length from the ``Content-Range`` header.
    2. Range-``GET`` the last ``_CENTRAL_DIRECTORY_PROBE_BYTES`` bytes
       — typically 64 kB is enough to cover the entire zip central
       directory.  If :class:`_PartialFile`'s open call complains the
       directory isn't there, widen the window and retry once.
    3. Locate ``<dist-info>/METADATA`` in the directory.  Issue a
       second range ``GET`` for just that entry's bytes, decompress,
       parse.
    """
    total_length = _discover_wheel_length(session, wheel_url)
    if total_length <= 0:
        raise MetadataFetchError(
            f"could not determine wheel length for {wheel_url}"
        )

    # Walk the central directory, possibly widening the tail window.
    window = min(_CENTRAL_DIRECTORY_PROBE_BYTES, total_length)
    while True:
        tail_start = max(0, total_length - window)
        tail_bytes = _http_get_range(
            session, wheel_url, tail_start, total_length - 1
        )
        partial = _PartialFile(
            tail_bytes,
            offset=tail_start,
            total_length=total_length,
            session=session,
            url=wheel_url,
        )
        try:
            zf = zipfile.ZipFile(partial)
        except zipfile.BadZipFile:
            if window >= total_length or window >= _MAX_CENTRAL_DIRECTORY_WINDOW:
                raise MetadataFetchError(
                    f"could not read central directory of {wheel_url} "
                    f"after sampling {window} bytes"
                )
            # Double the window and retry.
            window = min(window * 2, total_length, _MAX_CENTRAL_DIRECTORY_WINDOW)
            continue
        break

    try:
        info = _find_metadata_member(zf)
    finally:
        zf.close()

    if info is None:
        raise MetadataFetchError(
            f"no <dist-info>/METADATA member found in {wheel_url}"
        )

    # Re-open with the same _PartialFile to extract the METADATA body.
    # Re-using ``partial`` is safe — it transparently re-issues range
    # GETs for any byte range outside its in-memory window.
    partial.seek(0)
    zf = zipfile.ZipFile(partial)
    try:
        with zf.open(info, "r") as fh:
            raw = fh.read()
    finally:
        zf.close()

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MetadataFetchError(
            f"METADATA body in {wheel_url} is not UTF-8: {exc}"
        ) from exc

    return _parse_metadata_text(text)


def _discover_wheel_length(session: Any, wheel_url: str) -> int:
    """Return the wheel's total byte length via HEAD or a probing GET.

    First tries ``HEAD``: on a 200 with a ``Content-Length`` header we
    return it directly.  If ``HEAD`` is rejected (405 / 403, some
    private indexes don't allow it) or doesn't advertise the length,
    we fall through to a tiny range ``GET`` and read the length from
    ``Content-Range`` (``bytes 0-1/<TOTAL>``).
    """
    head_response = _http_request(session, "HEAD", wheel_url)
    if head_response is not None:
        status = _response_status(head_response)
        if status == 200:
            length = _content_length(head_response)
            if length > 0:
                return length

    # Fall back to a probing GET with a tiny range.
    probe_response = _http_request(
        session, "GET", wheel_url, headers={"Range": "bytes=0-1"}
    )
    if probe_response is None:
        raise MetadataFetchError(
            f"HEAD and probing GET both failed for {wheel_url}"
        )
    status = _response_status(probe_response)
    if status not in (200, 206):
        raise MetadataFetchError(
            f"probing GET for {wheel_url} returned HTTP {status}"
        )
    content_range = _get_header(probe_response.headers, "Content-Range")
    if content_range:
        # ``bytes 0-1/<TOTAL>``.  Split on ``/`` and take the tail.
        total_part = content_range.rsplit("/", 1)[-1].strip()
        if total_part and total_part != "*":
            try:
                return int(total_part)
            except ValueError:
                pass
    # Last resort: Content-Length on the probe.  This will be 2, not
    # the full wheel length, but some misbehaving mirrors set it
    # anyway.  Better to give up cleanly than spin.
    raise MetadataFetchError(
        f"could not parse Content-Range from probe GET on {wheel_url}: "
        f"{content_range!r}"
    )


def _content_length(response: Any) -> int:
    """Return ``Content-Length`` from ``response`` or ``-1`` on failure."""
    raw = _get_header(response.headers, "Content-Length")
    if not raw:
        return -1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def _find_metadata_member(zf: zipfile.ZipFile) -> zipfile.ZipInfo | None:
    """Find the ``<dist>-<version>.dist-info/METADATA`` member.

    Wheel layout (PEP 427): exactly one ``*.dist-info/`` directory at
    the archive root.  The METADATA file lives at
    ``<dist-info>/METADATA``.
    """
    for info in zf.infolist():
        name = info.filename
        if name.endswith(".dist-info/METADATA"):
            return info
        # Some wheels emit Windows-style separators — accept both.
        if name.endswith(".dist-info\\METADATA"):
            return info
    return None


# ---------------------------------------------------------------------------
# Email parser
# ---------------------------------------------------------------------------


def _parse_metadata_text(raw: str) -> CoreMetadata:
    """Parse a METADATA text body into a :class:`CoreMetadata`.

    Uses :class:`email.parser.HeaderParser` with
    :data:`email.policy.compat32` — that's the policy setuptools uses
    when *writing* METADATA, so reading with the same policy avoids
    folding / re-wrapping surprises on long Requires-Dist headers.

    ``Requires-Dist`` is repeated; we collect every line in source
    order via :meth:`Message.get_all`.  ``Provides-Extra`` is also
    repeated and goes into a :class:`frozenset` (extras are unordered
    by spec).
    """
    parser = HeaderParser(policy=email_policy.compat32)
    msg = parser.parsestr(raw)

    raw_name = msg.get("Name") or ""
    raw_version = msg.get("Version") or ""
    # canonicalize_name is forgiving on weird casing / separators;
    # the rest of the resolver expects PEP 503 canonical names.
    name = canonicalize_name(raw_name) if raw_name else ""
    version = raw_version.strip()

    requires_python = msg.get("Requires-Python")
    if requires_python is not None:
        requires_python = requires_python.strip() or None

    requires_dist = tuple(
        line.strip()
        for line in (msg.get_all("Requires-Dist") or [])
        if line and line.strip()
    )

    provides_extras = frozenset(
        line.strip()
        for line in (msg.get_all("Provides-Extra") or [])
        if line and line.strip()
    )

    summary = msg.get("Summary")
    if summary is not None:
        summary = summary.strip() or None

    return CoreMetadata(
        name=name,
        version=version,
        requires_python=requires_python,
        requires_dist=requires_dist,
        provides_extras=provides_extras,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_request(
    session: Any,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> Any:
    """Issue a single HTTP request via ``session.request``.

    Returns the response or ``None`` if the session raised — the
    fallback path will surface a typed :class:`MetadataFetchError`.
    Mirrors :class:`PEP691Client`'s timeout shape so production
    behaviour is consistent across resolver HTTP hops.
    """
    try:
        return session.request(
            method,
            url,
            headers=headers or {},
            timeout=(_DEFAULT_CONNECT_TIMEOUT, _DEFAULT_READ_TIMEOUT),
        )
    except Exception as exc:  # noqa: BLE001 - logged + swallowed
        _LOGGER.debug("HTTP %s failed for %s: %s", method, url, exc)
        return None


def _response_status(response: Any) -> int:
    """Status int from urllib3-style (``.status``) or requests-style
    (``.status_code``) responses.  Production uses
    :class:`PipSession` (requests); the Phase 1+2 unit tests use a
    urllib3-style mock — pick by attribute *presence* so explicit
    ``None`` values on a urllib3-style mock aren't silently re-interpreted
    as a requests response."""
    if hasattr(response, "status"):
        status = response.status
    elif hasattr(response, "status_code"):
        status = response.status_code
    else:
        status = None
    return int(status) if status is not None else 0


def _response_body(response: Any) -> bytes | None:
    """Body bytes from urllib3-style (``.data``) or requests-style
    (``.content``) responses.  Pick by attribute *presence* so an
    explicit ``None`` on a urllib3-style mock isn't silently re-read
    as ``.content``."""
    if hasattr(response, "data"):
        return response.data
    if hasattr(response, "content"):
        return response.content
    return None


def _http_get(session: Any, url: str) -> bytes:
    """GET ``url`` and return the body bytes, or raise ``MetadataFetchError``."""
    response = _http_request(session, "GET", url)
    if response is None:
        raise MetadataFetchError(f"GET {url} failed (no response)")
    status = _response_status(response)
    if status not in (200, 206):
        raise MetadataFetchError(f"GET {url} returned HTTP {status}")
    data = _response_body(response)
    if data is None:
        raise MetadataFetchError(f"GET {url} returned no body")
    return bytes(data)


def _http_get_range(
    session: Any,
    url: str,
    start: int,
    end_inclusive: int,
) -> bytes:
    """Range-GET ``url`` for bytes ``[start, end_inclusive]``.

    Accepts both 206 (the typical case) and 200 (some mirrors ignore
    the ``Range`` header but still return the full body — we trim
    locally in :class:`_PartialFile`'s consumer).  Raises
    :class:`MetadataFetchError` on any other status.
    """
    headers = {"Range": f"bytes={start}-{end_inclusive}"}
    response = _http_request(session, "GET", url, headers=headers)
    if response is None:
        raise MetadataFetchError(f"range GET {url} failed (no response)")
    status = _response_status(response)
    if status not in (200, 206):
        raise MetadataFetchError(
            f"range GET {url} returned HTTP {status}"
        )
    data = _response_body(response)
    if data is None:
        raise MetadataFetchError(f"range GET {url} returned no body")
    return bytes(data)


def _get_header(headers: Any, name: str) -> str | None:
    """Case-insensitively fetch a header value or ``None``.

    Mirrors :func:`pipenv.resolver.pep691._get_header` so tests can
    pass plain ``dict`` headers and production-shaped
    ``HTTPHeaderDict`` interchangeably.
    """
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:  # noqa: BLE001
        value = None
    if value is not None:
        return value
    try:
        items = headers.items()
    except Exception:  # noqa: BLE001
        return None
    name_lower = name.lower()
    for key, val in items:
        if isinstance(key, str) and key.lower() == name_lower:
            return val
    return None


# ---------------------------------------------------------------------------
# Partial-zipfile adapter
# ---------------------------------------------------------------------------


class _PartialFile(io.RawIOBase):
    """File-like view over a wheel-tail buffer that re-fetches on demand.

    :class:`zipfile.ZipFile` does a single seek-to-the-end-and-walk
    pass to discover the central directory, then random-reads each
    member's local file header + compressed body.  When we hand it a
    buffer covering just the last 64 kB of the wheel, the central-
    directory walk succeeds locally but a subsequent ``zf.open(...)``
    on a member earlier in the archive needs bytes we don't have.

    This shim implements just enough of the file interface that
    :class:`ZipFile` is happy:

    * ``seekable() / readable()`` → ``True``.
    * ``seek(offset, whence)`` → tracks position; supports SEEK_SET,
      SEEK_CUR, SEEK_END.
    * ``tell()`` → current absolute offset within the wheel.
    * ``read(size)`` → returns ``size`` bytes, re-fetching via a range
      GET if the request falls outside the in-memory window.

    The in-memory window starts as the tail buffer (``offset`` =
    ``total_length - len(buffer)`` to ``total_length - 1``).  When the
    consumer reads outside that range, we issue a range GET for the
    missing bytes — expanding the window so subsequent reads in the
    same neighbourhood don't re-fetch.

    Memory bound: in the worst case the window grows to the full
    wheel length, which matches a direct GET of the wheel and is the
    fundamental cost ceiling.  In practice a single ``METADATA`` read
    expands the window by at most ~ a few kB beyond the directory.
    """

    def __init__(
        self,
        tail_buffer: bytes,
        *,
        offset: int,
        total_length: int,
        session: Any,
        url: str,
    ) -> None:
        super().__init__()
        # Buffer holds bytes ``[buffer_start, buffer_end)`` of the wheel.
        self._buffer = bytearray(tail_buffer)
        self._buffer_start = offset
        self._total_length = total_length
        self._session = session
        self._url = url
        self._position = 0

    # ---- io.RawIOBase contract ---------------------------------------

    def seekable(self) -> bool:  # noqa: D401 - one-liner
        return True

    def readable(self) -> bool:  # noqa: D401 - one-liner
        return True

    def writable(self) -> bool:  # noqa: D401 - one-liner
        return False

    def tell(self) -> int:  # noqa: D401 - one-liner
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            new = offset
        elif whence == io.SEEK_CUR:
            new = self._position + offset
        elif whence == io.SEEK_END:
            new = self._total_length + offset
        else:
            raise ValueError(f"unsupported whence: {whence}")
        if new < 0:
            raise ValueError(f"negative seek position {new}")
        self._position = new
        return new

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._total_length - self._position
        if size <= 0 or self._position >= self._total_length:
            return b""
        end = min(self._position + size, self._total_length)
        self._ensure_range(self._position, end)
        start_in_buf = self._position - self._buffer_start
        end_in_buf = end - self._buffer_start
        data = bytes(self._buffer[start_in_buf:end_in_buf])
        self._position = end
        return data

    # ---- internals ---------------------------------------------------

    def _buffer_end(self) -> int:
        """Exclusive end offset of the in-memory window."""
        return self._buffer_start + len(self._buffer)

    def _ensure_range(self, start: int, end: int) -> None:
        """Ensure bytes ``[start, end)`` are covered by the buffer.

        Grows the buffer at the low end and/or the high end as
        necessary by issuing range GETs.  No-op when the buffer
        already covers the request.
        """
        if start < self._buffer_start:
            # Need a prefix fetch.  Pull ``[start, buffer_start)``.
            prefix = _http_get_range(
                self._session,
                self._url,
                start,
                self._buffer_start - 1,
            )
            # If the server ignored Range and returned the whole file,
            # ``prefix`` may be longer than the requested span.  Trim.
            wanted = self._buffer_start - start
            if len(prefix) > wanted:
                prefix = prefix[:wanted]
            elif len(prefix) < wanted:
                # Short read on a range GET is rare but possible on a
                # mirror that capped the response.  Surface it.
                raise MetadataFetchError(
                    f"short range read on {self._url}: "
                    f"asked {wanted} bytes got {len(prefix)}"
                )
            self._buffer = bytearray(prefix) + self._buffer
            self._buffer_start = start
        if end > self._buffer_end():
            # Need a suffix fetch.  Pull
            # ``[buffer_end, end)`` (inclusive end_inclusive = end-1).
            current_end = self._buffer_end()
            suffix = _http_get_range(
                self._session,
                self._url,
                current_end,
                end - 1,
            )
            wanted = end - current_end
            if len(suffix) > wanted:
                # Trim oversized response from a Range-ignoring mirror.
                suffix = suffix[:wanted]
            elif len(suffix) < wanted:
                raise MetadataFetchError(
                    f"short range read on {self._url}: "
                    f"asked {wanted} bytes got {len(suffix)}"
                )
            self._buffer.extend(suffix)
