"""Disk-backed parsed-manifest cache for the pure-Python resolver
(Initiative G phase 1, T7).

See:

* ``docs/dev/initiative-g-pure-python-design.md`` §5.2 — authoritative
  spec for the cache shape, disk format, and freshness policy.
* ``initiative-g-phase1-2-plan.md`` T7 — this task.

The cache persists tuples of :class:`pipenv.resolver.candidate.Candidate`
keyed by ``(index_url, package_name)``.  It replaces patched-pip's
``CacheControl`` + JSON-re-parse hot path on the resolver candidate
read side: once a manifest has been parsed into Candidate objects, we
hold onto the parsed shape rather than re-parsing the raw HTTP body on
every resolve.

Phase-1 disk format is JSON (per design §10 Q1 — debug-friendly while
the schema is still in flux).  A ``schema_version`` field on every
payload lets us bump the format incompatibly later by changing the
class-level :attr:`ParsedManifestCache.SCHEMA_VERSION` constant — any
payload that disagrees is treated as a miss and silently replaced on
the next write.

Critical constraint (enforced by the T17 pre-commit gate when it ships):
**this module must not import from patched-pip's internal package.**
We canonicalise package names via the vendored ``packaging`` library
(``pipenv.vendor.packaging.utils.canonicalize_name``), which is
permitted.  The cache root is a caller-supplied :class:`pathlib.Path`;
the class deliberately does *not* default it to ``~/.cache/pipenv/...``
so that location choice lives with the caller (T9 / T19).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from pipenv.resolver.candidate import Candidate, Hash
from pipenv.vendor.packaging.tags import Tag, parse_tag
from pipenv.vendor.packaging.utils import canonicalize_name


@dataclass(frozen=True, slots=True)
class CachedManifest:
    """One cached parsed-manifest payload.

    Fields mirror the on-disk JSON envelope (modulo the
    ``schema_version`` field which the cache layer owns and the caller
    never sees).

    ``cached_at`` and ``expires_at`` are timezone-aware UTC datetimes;
    naïve datetimes are deliberately not supported here to avoid the
    classic "compare aware vs naïve" :class:`TypeError` when callers
    pull a manifest in one timezone and check expiry in another.
    """

    candidates: tuple[Candidate, ...]
    etag: str | None
    cached_at: datetime
    expires_at: datetime


class ParsedManifestCache:
    """Filesystem-backed cache of parsed simple-API manifests.

    Layout::

        <root>/manifests-v<schema_version>/
            <sha256(index_url)>/
                <canonical_name>.json

    Atomicity: every write goes through ``tempfile.NamedTemporaryFile``
    in the target file's parent directory followed by ``os.replace``.
    A crash mid-write leaves the previous payload (if any) intact and
    no partial file at the target path; the temp file may survive in
    the parent directory but is harmless (different name, never read).

    Concurrency: per-file granularity via :func:`os.replace`'s atomic
    rename on POSIX.  Reader-vs-writer never observes a partial file.
    Writer-vs-writer is last-rename-wins; both payloads are well-formed
    and one of them is the final state.  No locking is required for
    these guarantees — they fall out of the POSIX rename semantics that
    :func:`os.replace` documents.
    """

    SCHEMA_VERSION = 1  # bump on incompatible disk-format change

    def __init__(self, root: Path, schema_version: int = SCHEMA_VERSION) -> None:
        self._root = Path(root)
        self._schema_version = schema_version
        # Cache the versioned subdirectory once at construction time
        # so per-call ``get`` / ``put`` don't pay the f-string cost.
        self._versioned_root = self._root / f"manifests-v{schema_version}"

    # --- public API -----------------------------------------------------

    def get(self, index_url: str, package_name: str) -> CachedManifest | None:
        """Return the cached manifest for ``(index_url, package_name)``.

        Returns ``None`` when:

        * the on-disk file does not exist;
        * the file exists but its ``schema_version`` does not match this
          cache's :attr:`SCHEMA_VERSION` (silently invalidated — the
          caller will refetch and overwrite);
        * the file's ``expires_at`` is in the past (TTL expiry);
        * the file is corrupt / unparseable JSON (treated as a miss
          rather than raising — a corrupt cache entry should never
          block a resolve, only force a refetch).
        """
        target = self._path_for(index_url, package_name)
        try:
            raw = target.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            # Permission denied, etc — treat as miss rather than crash.
            return None

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Corrupt / partial / wrong-codec file.  Caller will
            # refetch and overwrite; do not raise.
            return None

        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != self._schema_version:
            # Disk format from a different schema version — silently
            # treat as a miss; refetch will overwrite on next ``put``.
            return None

        try:
            cached_at = _datetime_from_iso(payload["cached_at"])
            expires_at = _datetime_from_iso(payload["expires_at"])
        except (KeyError, ValueError, TypeError):
            return None

        if datetime.now(timezone.utc) >= expires_at:
            # TTL expired — caller will refetch (possibly with
            # ``If-None-Match`` if they remember the etag).
            return None

        try:
            candidates = tuple(
                _candidate_from_json(entry)
                for entry in payload["candidates"]
            )
        except (KeyError, TypeError, ValueError):
            return None

        etag = payload.get("etag")
        if etag is not None and not isinstance(etag, str):
            etag = None

        return CachedManifest(
            candidates=candidates,
            etag=etag,
            cached_at=cached_at,
            expires_at=expires_at,
        )

    def put(
        self,
        index_url: str,
        package_name: str,
        candidates: Sequence[Candidate],
        etag: str | None,
        ttl_seconds: int = 600,
    ) -> None:
        """Atomically write a manifest payload to disk.

        ``cached_at`` is stamped at the moment this method is called
        (UTC); ``expires_at`` is ``cached_at + ttl_seconds`` so
        ``ttl_seconds=0`` produces an immediately-expired payload
        (acceptance criterion 2).

        The write goes via :func:`tempfile.NamedTemporaryFile` in the
        target's parent directory followed by :func:`os.replace`.  If
        :func:`os.replace` raises, the previous target file (if any) is
        unchanged and no partial payload becomes visible (acceptance
        criterion 4).  The temp file may be left behind on failure — we
        do not aggressively clean it up because doing so would risk
        racing another writer's temp file in the same directory; the
        next successful ``put`` overwrites the target regardless.
        """
        cached_at = datetime.now(timezone.utc)
        expires_at = cached_at + timedelta(seconds=ttl_seconds)
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "cached_at": _datetime_to_iso(cached_at),
            "expires_at": _datetime_to_iso(expires_at),
            "etag": etag,
            "candidates": [_candidate_to_json(c) for c in candidates],
        }

        target = self._path_for(index_url, package_name)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)

        # NamedTemporaryFile in the same directory so os.replace is a
        # rename within one filesystem (atomic on POSIX).
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
            # os.replace failed (or any earlier step did).  Best-effort
            # cleanup of the temp file — if this also fails (rare), the
            # leftover is named ``<target>.<random>.tmp`` and harmless.
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise

    def invalidate(self, index_url: str, package_name: str) -> None:
        """Best-effort removal of a single cache entry.

        Missing-file is not an error.
        """
        target = self._path_for(index_url, package_name)
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Permission denied etc — best effort.
            pass

    def clear_all(self) -> None:
        """Remove the entire versioned cache subtree.

        Used by ``pipenv lock --clear`` (T17 wires this in).  Does not
        touch other schema-version subtrees if any happen to coexist
        under the same root — only the one this instance manages.
        """
        shutil.rmtree(self._versioned_root, ignore_errors=True)

    # --- internals ------------------------------------------------------

    def _path_for(self, index_url: str, package_name: str) -> Path:
        """Compute the on-disk path for one ``(index_url, name)`` pair.

        Index URL is hashed with full sha256 (not truncated) to avoid
        prefix collisions between two distinct index URLs that happen
        to share a 64-char prefix — see plan T14's URL-hashing
        collision test.
        """
        digest = hashlib.sha256(index_url.encode("utf-8")).hexdigest()
        canonical = canonicalize_name(package_name)
        return self._versioned_root / digest / f"{canonical}.json"


# --- Candidate (de)serialization helpers --------------------------------


def _candidate_to_json(c: Candidate) -> dict[str, Any]:
    """Convert a :class:`Candidate` to a JSON-serialisable ``dict``.

    Conversions:

    * ``frozenset[Hash]`` → sorted ``list[list[str, str]]`` (sorting
      keeps round-trips deterministic across runs / Python builds).
    * ``datetime | None`` → ISO 8601 string or ``None``.
    * ``frozenset[Tag] | None`` → sorted ``list[str]`` of ``str(tag)``
      or ``None``.
    """
    return {
        "name": c.name,
        "version": c.version,
        "url": c.url,
        "filename": c.filename,
        "hashes": sorted([h.algo, h.value] for h in c.hashes),
        "requires_python": c.requires_python,
        "yanked": c.yanked,
        "yanked_reason": c.yanked_reason,
        "upload_time": _datetime_to_iso(c.upload_time) if c.upload_time else None,
        "is_wheel": c.is_wheel,
        "wheel_tags": (
            sorted(str(t) for t in c.wheel_tags)
            if c.wheel_tags is not None
            else None
        ),
    }


def _candidate_from_json(data: dict[str, Any]) -> Candidate:
    """Inverse of :func:`_candidate_to_json`.

    Trust the cached ``wheel_tags`` list when present so that on-disk
    round-trips are bit-stable even if a future ``packaging`` upgrade
    changes :func:`packaging.tags.parse_tag` output for the same wheel
    filename.  Fall back to re-deriving from the filename only when
    the field is missing entirely (forward-compat shim for older
    payloads written before this field existed).
    """
    raw_hashes = data.get("hashes") or []
    hashes: frozenset[Hash] = frozenset(
        Hash(algo=str(h[0]), value=str(h[1])) for h in raw_hashes
    )

    upload_time_raw = data.get("upload_time")
    upload_time = (
        _datetime_from_iso(upload_time_raw) if upload_time_raw else None
    )

    filename = data["filename"]
    cached_wheel_tags = data.get("wheel_tags")
    cached_is_wheel = data.get("is_wheel")

    if cached_wheel_tags is not None:
        wheel_tags: frozenset[Tag] | None = frozenset(
            tag
            for tag_str in cached_wheel_tags
            for tag in parse_tag(tag_str)
        )
        is_wheel = (
            bool(cached_is_wheel)
            if cached_is_wheel is not None
            else filename.endswith(".whl")
        )
        return Candidate(
            name=data["name"],
            version=data["version"],
            url=data["url"],
            filename=filename,
            hashes=hashes,
            requires_python=data.get("requires_python"),
            yanked=bool(data.get("yanked", False)),
            yanked_reason=data.get("yanked_reason"),
            upload_time=upload_time,
            is_wheel=is_wheel,
            wheel_tags=wheel_tags,
        )

    # No cached wheel_tags — fall back to filename-derived (handles
    # any future payloads written before the field existed).
    return Candidate.from_filename(
        filename,
        name=data["name"],
        version=data["version"],
        url=data["url"],
        hashes=hashes,
        requires_python=data.get("requires_python"),
        yanked=bool(data.get("yanked", False)),
        yanked_reason=data.get("yanked_reason"),
        upload_time=upload_time,
    )


def _datetime_to_iso(dt: datetime) -> str:
    """Serialise a (preferably timezone-aware) datetime to ISO 8601.

    Naïve datetimes are tolerated for the ``upload_time`` field where
    the upstream index may have supplied a naïve timestamp; we serialise
    whatever we got and let the caller deal with it on read.
    """
    return dt.isoformat()


def _datetime_from_iso(value: str) -> datetime:
    """Inverse of :func:`_datetime_to_iso`.

    :func:`datetime.fromisoformat` accepts the ``"+00:00"`` form that
    :meth:`datetime.isoformat` produces for UTC-aware datetimes and the
    bare form for naïve ones, so a round-trip is lossless.
    """
    return datetime.fromisoformat(value)


__all__ = ["CachedManifest", "ParsedManifestCache"]
