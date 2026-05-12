"""PEP 691 simple-API JSON parser for the in-tree resolver backend
(Initiative G phase 1, T4).

See:

* ``docs/dev/initiative-g-pure-python-design.md`` §5.1 — the authoritative
  design of the pure-Python simple-API client.
* ``initiative-g-phase1-2-plan.md`` T4 — this task.

Phase-1 scope for *this* file is **just the JSON parser**.  T5 lands the
PEP 503 HTML parser in the same module; T8 adds the ``PEP691Client``
class that orchestrates HTTP + parsing.  Keeping the parser as a
module-level private function (rather than a method on a not-yet-written
class) lets T8 wire it up without a class-hierarchy refactor.

Critical constraint (enforced by the T17 pre-commit gate when it ships):
**this module must not import from patched-pip's internal package.**  The
whole point of Initiative G is to replace pip-internal data shapes with a
pipenv-owned typed model.  Only stdlib + :mod:`pipenv.resolver.candidate`
+ :mod:`pipenv.vendor.packaging` are permitted.

Design highlights
-----------------
* Relative file URLs are resolved against ``page_url`` **once at parse
  time** via :func:`urllib.parse.urljoin`.  This replaces patched-pip's
  per-evaluation ``_ensure_quoted_url`` cost; downstream consumers see
  already-absolute URLs.
* ``meta.api-version`` is validated to start with ``"1."``.  Unknown
  *minor* versions parse successfully (forward-compat: PEP 691 itself
  promises 1.x additions are non-breaking).  Unknown *major* versions
  cause us to fall through and best-effort parse anyway — we never raise
  on the metadata block.  The plan brief defers verbose-mode logging to
  the client layer (T8), so this function emits nothing on its own.
* Per-file entries that cannot be turned into a :class:`Candidate`
  (missing required keys, malformed wheel filename, etc.) are silently
  skipped: this is a best-effort parser, and partial results are more
  useful than a hard failure on a single bad entry.
* The function raises only when the response body is not decodable JSON
  at all — the caller (T8 client) needs that signal to map a 200 with a
  malformed body to a ``FetchError("transient", ...)``.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from pipenv.resolver.candidate import Candidate, Hash

# ``meta.api-version`` validation: PEP 691 §3 commits to 1.x being
# additive-only, so any minor revision is safe to parse opportunistically.
# We don't raise on unknown majors — a Phase-3 audit will revisit if 2.x
# ships with breaking field renames.
_SUPPORTED_API_MAJOR = "1."


def _parse_upload_time(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 → :class:`datetime` conversion.

    Returns ``None`` on any failure or missing input.  The PyPI form is
    ``"2024-01-15T12:34:56.789012Z"``.  Python 3.11+ accepts the trailing
    ``Z`` in :meth:`datetime.fromisoformat` directly; pipenv supports
    3.9+, so we patch the older form by replacing ``Z`` with ``+00:00``
    before retrying.

    We deliberately swallow :class:`ValueError` and :class:`TypeError` to
    keep the parser best-effort — a single artifact with an exotic
    timestamp must not poison the entire page.
    """
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # Older Pythons reject the ``Z`` suffix; normalise to ``+00:00``.
        if value.endswith("Z"):
            try:
                return datetime.fromisoformat(value[:-1] + "+00:00")
            except ValueError:
                return None
        return None


def _normalize_yanked(raw: Any) -> tuple[bool, str | None]:
    """Flatten PEP 691's polymorphic ``yanked`` field to ``(bool, reason)``.

    The spec allows three forms:

    * ``false`` (or missing) → not yanked.
    * ``true`` → yanked, no reason supplied.
    * a non-empty string → yanked, reason carried verbatim.

    Anything else (e.g., empty string, non-bool/non-string truthy value)
    is treated as not-yanked.  Empty-string-yanked is a spec ambiguity;
    we resolve it conservatively as "not yanked" so a misbehaving index
    cannot accidentally mark every release as yanked via a stray ``""``.
    """
    if raw is True:
        return True, None
    if isinstance(raw, str) and raw:
        return True, raw
    return False, None


def _normalize_hashes(raw: Any) -> frozenset[Hash]:
    """Convert PEP 691's ``hashes`` mapping to a :class:`frozenset` of
    :class:`Hash`.

    PEP 691 §3 specifies the algo name should be lower-cased; we enforce
    that here so downstream set-intersection with Pipfile-pinned hashes
    is case-stable.  A missing or non-dict ``hashes`` field yields an
    empty frozenset (some PyPI mirrors strip this field entirely; the
    plan's ``missing-hash`` synthetic fixture exercises that path).
    """
    if not isinstance(raw, dict):
        return frozenset()
    return frozenset(
        Hash(algo.lower(), value)
        for algo, value in raw.items()
        if isinstance(algo, str) and isinstance(value, str)
    )


def _strip_archive_suffix(filename: str) -> str:
    """Return the archive stem after removing a known sdist/wheel suffix.

    Order matters: ``.tar.gz`` / ``.tar.bz2`` must be checked before the
    single-segment ``.gz`` / ``.bz2`` fallbacks would, so we hard-code the
    PyPI-canonical set.  Anything else returns the filename unchanged —
    the caller's downstream parse will fail gracefully and the entry
    will be skipped.
    """
    for suffix in (".tar.gz", ".tar.bz2", ".whl", ".zip", ".tgz"):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def _extract_version(filename: str, canonical_name: str) -> str | None:
    """Extract the PEP 440 version string from an artifact filename.

    Strategy: strip the archive suffix, then strip the leading
    ``<dist>-`` prefix.  ``<dist>`` may differ from ``canonical_name`` in
    case (``Django`` vs ``django``) and in separator (``-`` vs ``_``,
    e.g. ``python_dateutil-2.8.0...whl`` for canonical ``python-dateutil``).
    After the prefix is stripped:

    * For wheels: the remainder is ``<version>(-<build>)?-<py>-<abi>-<plat>``,
      so the version is the first ``-``-separated chunk.
    * For sdists: the remainder is just ``<version>``.

    Returns ``None`` if the filename doesn't match the expected shape
    (e.g. the prefix isn't a recognisable variant of ``canonical_name``);
    the caller then skips the entry.
    """
    stem = _strip_archive_suffix(filename)
    if stem == filename:
        # Unknown suffix — caller will skip.
        return None

    # Build the set of plausible dist-name forms.  PEP 503 + PEP 427
    # normalisation: lower-case, ``_`` ↔ ``-`` equivalence, runs of either
    # collapsed to one ``_`` for wheels (we accept the relaxed form too).
    lowered_stem = stem.lower()
    name_variants = {
        canonical_name,
        canonical_name.replace("-", "_"),
        canonical_name.replace("_", "-"),
    }

    matched_prefix: str | None = None
    for variant in name_variants:
        candidate_prefix = variant.lower() + "-"
        if lowered_stem.startswith(candidate_prefix):
            matched_prefix = candidate_prefix
            break

    if matched_prefix is None:
        return None

    remainder = stem[len(matched_prefix):]
    if not remainder:
        return None

    # Wheel filenames carry trailing ``<py>-<abi>-<plat>``; sdists don't.
    # ``rsplit("-", 1)[0]`` won't help (build tag is optional); take the
    # first ``-``-separated chunk and that's the version for both forms.
    return remainder.split("-", 1)[0]


def _build_candidate(
    entry: dict,
    *,
    canonical_name: str,
    page_url: str,
) -> Candidate | None:
    """Convert one PEP 691 file entry to a :class:`Candidate`.

    Returns ``None`` on any failure (missing required key, malformed
    filename, etc.).  Never raises — the caller iterates over many entries
    and expects best-effort partial results.
    """
    filename = entry.get("filename")
    raw_url = entry.get("url")
    if not isinstance(filename, str) or not isinstance(raw_url, str):
        return None
    if not filename or not raw_url:
        return None

    version = _extract_version(filename, canonical_name)
    if version is None:
        return None

    # Absolute URLs pass through urljoin unchanged; relatives are resolved
    # against ``page_url``.  This pays the urlsplit/urlunsplit cost once
    # per artifact instead of pip's per-evaluation cost.
    absolute_url = urljoin(page_url, raw_url)

    yanked, yanked_reason = _normalize_yanked(entry.get("yanked", False))

    raw_requires_python = entry.get("requires-python")
    requires_python: str | None
    if isinstance(raw_requires_python, str) and raw_requires_python:
        requires_python = raw_requires_python
    else:
        requires_python = None

    try:
        return Candidate.from_filename(
            filename,
            name=canonical_name,
            version=version,
            url=absolute_url,
            hashes=_normalize_hashes(entry.get("hashes")),
            requires_python=requires_python,
            yanked=yanked,
            yanked_reason=yanked_reason,
            upload_time=_parse_upload_time(entry.get("upload-time")),
        )
    except (ValueError, TypeError):
        # ``Candidate.from_filename`` raises ``ValueError`` on a wheel
        # filename whose tag triple won't parse (T11 pinned this
        # contract).  Skip the offender; let the rest of the page through.
        return None


def _parse_pep691_json(body: bytes, page_url: str) -> tuple[Candidate, ...]:
    """Parse a PEP 691 (``application/vnd.pypi.simple.v1+json``) response
    body into a tuple of :class:`Candidate`.

    Resolves relative file URLs against ``page_url`` once at parse time
    (no later urlsplit per evaluate — replaces patched-pip's
    ``_ensure_quoted_url``-per-link cost).

    Validates ``meta.api-version`` starts with ``"1."``; does not raise
    on unknown majors (forward-compat — verbose logging deferred to T8
    client).

    Skips file entries that fail to construct a :class:`Candidate` (e.g.
    missing required keys, malformed wheel filename) — best-effort,
    returns the partial tuple.  Does not raise on malformed individual
    entries; only raises on a body that isn't decodable JSON at all
    (so the T8 client can map that to a ``FetchError("transient", ...)``).
    """
    # ``json.loads`` accepts bytes directly on 3.9+; UTF-8 is the assumed
    # encoding per RFC 8259 and PEP 691 §3.
    payload = json.loads(body)
    if not isinstance(payload, dict):
        # A JSON literal/array at top level is not a PEP 691 page; no
        # candidates we can extract.
        return ()

    meta = payload.get("meta")
    if isinstance(meta, dict):
        api_version = meta.get("api-version")
        if isinstance(api_version, str) and not api_version.startswith(
            _SUPPORTED_API_MAJOR
        ):
            # Unknown major — fall through and best-effort parse.  T8 may
            # emit a verbose-mode warning at the client layer.
            pass

    canonical_name = payload.get("name")
    if not isinstance(canonical_name, str) or not canonical_name:
        return ()

    files = payload.get("files")
    if not isinstance(files, list):
        return ()

    results: list[Candidate] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        candidate = _build_candidate(
            entry, canonical_name=canonical_name, page_url=page_url
        )
        if candidate is not None:
            results.append(candidate)
    return tuple(results)


__all__ = ["_parse_pep691_json"]
