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
from html import unescape as _html_unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from pipenv.resolver.candidate import Candidate, Hash
from pipenv.vendor.packaging.utils import canonicalize_name

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


# ---------------------------------------------------------------------------
# PEP 503 HTML parser (T5).  Lives alongside the JSON parser so the T8
# client can dispatch on Content-Type without an extra import.  Shares
# T4's normalisation helpers (_extract_version, _strip_archive_suffix)
# wholesale — JSON and HTML must produce equivalent Candidate sets for
# the same package, and that invariant is enforced by reusing the same
# code path, not by re-implementing it.
# ---------------------------------------------------------------------------


class _AnchorCollector(HTMLParser):
    """Collect ``<a>`` tags' attributes + inner text from a PEP 503 page.

    PEP 503 §3 specifies the page is a flat list of anchor tags whose
    text content is the artifact filename and whose ``href`` points at
    the artifact (optionally with a ``#<algo>=<hex>`` hash fragment).
    Attributes ``data-requires-python`` (PEP 503), ``data-yanked`` (PEP
    592), and ``data-core-metadata`` / ``data-dist-info-metadata`` (PEP
    658) may decorate each anchor.

    We collect everything verbatim and let the higher-level loop in
    :func:`_parse_pep503_html` decide which attributes feed into the
    :class:`Candidate`.  HTMLParser doesn't unescape attribute values
    automatically for us — that has to happen at consumption time via
    :func:`html.unescape` so ``data-requires-python="&gt;=3.8"`` becomes
    ``">=3.8"``.

    Robustness notes
    ----------------
    * Nested anchors are not legal HTML5 and PyPI doesn't emit them, so
      we don't handle them.  If one appears anyway we'd silently drop the
      outer's text; that's acceptable for best-effort parsing.
    * Self-closing ``<a/>`` would skip ``handle_endtag``, which is
      vanishingly rare on simple-index pages but we'd lose the entry.
      Again, acceptable for Phase 1.
    """

    def __init__(self) -> None:
        super().__init__()
        # Each entry: (attrs dict, inner text).  We accumulate text via a
        # list-of-strings rather than string-concatenation so a chunked
        # ``handle_data`` callback (HTMLParser may split a text node into
        # multiple calls) doesn't pay O(n^2) cost.
        self.entries: list[tuple[dict[str, str], str]] = []
        self._current_attrs: dict[str, str] | None = None
        self._current_text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "a":
            # PEP 503 allows attribute values to be omitted (e.g.
            # bare ``data-yanked``); HTMLParser then returns ``None``.
            # Normalise to empty-string so consumers can distinguish
            # "attribute absent" (key not in dict) from "attribute
            # present with empty value" (key present, value "").
            self._current_attrs = {k: (v or "") for k, v in attrs}
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_attrs is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_attrs is not None:
            text = "".join(self._current_text).strip()
            self.entries.append((self._current_attrs, text))
            self._current_attrs = None
            self._current_text = []


def _split_href_hash(href: str) -> tuple[str, frozenset[Hash]]:
    """Split a PEP 503 ``href`` into ``(base_url, hash_set)``.

    PEP 503 §4 (the original spec) says the URL fragment carries the
    hash as ``#<algo>=<hexvalue>``.  Algo is lower-cased to match
    :func:`_normalize_hashes`'s JSON-side output (cross-format parity
    invariant: same artifact → same ``frozenset[Hash]`` regardless of
    which parser produced it).

    Returns the empty :class:`frozenset` if:

    * No ``#`` in href (anchor lacks a hash advertisement entirely).
    * Fragment is malformed (no ``=``).

    Both cases legitimately occur on partial mirrors and bad indexes —
    we treat them as best-effort hash data and skip the hash, not the
    candidate.  T4's JSON path has the same "missing hashes = empty
    frozenset" semantics for symmetry.
    """
    if "#" not in href:
        return href, frozenset()
    base, fragment = href.split("#", 1)
    if "=" not in fragment:
        return base, frozenset()
    algo, _, value = fragment.partition("=")
    if not algo or not value:
        return base, frozenset()
    return base, frozenset({Hash(algo.lower(), value)})


def _normalize_yanked_html(attrs: dict[str, str]) -> tuple[bool, str | None]:
    """Flatten ``data-yanked`` to ``(yanked, reason)``.

    HTML form is unambiguous (and *intentionally differs* from JSON):

    * Attribute absent (``"data-yanked" not in attrs``) → not yanked.
    * Attribute present with empty value → yanked, no reason.
    * Attribute present with non-empty value → yanked with that reason.

    Rationale for diverging from :func:`_normalize_yanked` (the JSON
    helper, which treats empty-string ``"yanked": ""`` as NOT yanked):
    in HTML the *presence* of the attribute is the unambiguous yanked
    signal (per the de-facto PEP 503 extension that aligned PEP 592 to
    the HTML serialisation), whereas in JSON ``""`` is a value that may
    be served by a misbehaving index without intent to yank.  Cross-
    format parity is asserted in T12 against the synthetic
    ``yanked-pkg.{html,json}`` fixture pair where this divergence is
    intentional.
    """
    if "data-yanked" not in attrs:
        return False, None
    raw = attrs["data-yanked"]
    if not raw:
        return True, None
    # ``data-yanked`` reason text may have HTML entities (e.g. ``&amp;``
    # in a CVE URL); unescape so the stored reason is plain text.
    return True, _html_unescape(raw)


def _package_name_from_page_url(page_url: str) -> str | None:
    """Derive the canonical package name from a PEP 503 page URL.

    The PEP 503 simple-index page sits at ``/simple/<canonical-name>/``
    — the package name is the last non-empty path segment.  We pass it
    through :func:`packaging.utils.canonicalize_name` to be safe (the
    URL *should* already be canonical, but mirrors aren't always
    rigorous).

    Returns ``None`` if the URL has no parseable path segment, which
    causes :func:`_parse_pep503_html` to return an empty tuple — the
    caller (T8 client) constructs the URL itself so this should never
    happen in practice, but we don't trust hand-crafted test inputs.
    """
    path = urlsplit(page_url).path
    # Strip trailing slash, take last segment.  ``"/simple/six/"`` →
    # ``"six"``.  ``"/simple/six"`` → ``"six"``.  ``""`` → no name.
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        return None
    raw_name = segments[-1]
    canonical = canonicalize_name(raw_name)
    return canonical or None


def _build_candidate_from_html(
    attrs: dict[str, str],
    text: str,
    *,
    canonical_name: str,
    page_url: str,
) -> Candidate | None:
    """Convert one collected anchor entry to a :class:`Candidate`.

    Mirrors :func:`_build_candidate` (T4's JSON path) field-by-field.
    Returns ``None`` on any failure — best-effort, matching the JSON
    parser's behaviour so cross-format parity holds.
    """
    href = attrs.get("href")
    if not isinstance(href, str) or not href:
        return None

    # PEP 503: anchor text is the filename.  Fall back to the URL's
    # final path segment if (somehow) the anchor had no text — robust
    # against minified HTML that elides whitespace.
    filename = text or urlsplit(href).path.rsplit("/", 1)[-1]
    if not filename:
        return None

    base_url, hashes = _split_href_hash(href)
    absolute_url = urljoin(page_url, base_url)

    version = _extract_version(filename, canonical_name)
    if version is None:
        return None

    yanked, yanked_reason = _normalize_yanked_html(attrs)

    raw_rp = attrs.get("data-requires-python")
    requires_python: str | None
    if raw_rp:
        # HTML attribute values arrive as raw text from the parser; the
        # ``&gt;=3.8`` form needs html.unescape to become ``>=3.8``.
        requires_python = _html_unescape(raw_rp)
    else:
        requires_python = None

    try:
        return Candidate.from_filename(
            filename,
            name=canonical_name,
            version=version,
            url=absolute_url,
            hashes=hashes,
            requires_python=requires_python,
            yanked=yanked,
            yanked_reason=yanked_reason,
            # PEP 503 carries no upload-time equivalent.  None matches
            # the JSON parser's behaviour on missing ``upload-time``.
            upload_time=None,
        )
    except (ValueError, TypeError):
        # Malformed wheel tag triple — same skip path as
        # ``_build_candidate`` so a single bad anchor doesn't poison
        # the rest of the page.
        return None


def _parse_pep503_html(body: bytes, page_url: str) -> tuple[Candidate, ...]:
    """Parse a PEP 503 HTML simple-index page into a tuple of
    :class:`Candidate`.

    Uses :class:`html.parser.HTMLParser` (stdlib) via the small
    :class:`_AnchorCollector` subclass.  Each anchor is converted to a
    :class:`Candidate` using the same normalisation helpers as
    :func:`_parse_pep691_json` (``_extract_version`` /
    ``_strip_archive_suffix`` / ``Candidate.from_filename``) so the two
    parsers emit equivalent candidate sets for the same package.

    Anchor attribute mapping (PEP 503 + PEP 592 extension + PEP 658
    advertisement):

    * ``href``                  — file URL (may be relative; resolved
                                  against ``page_url`` via
                                  :func:`urllib.parse.urljoin`).  May
                                  carry a ``#<algo>=<hex>`` fragment;
                                  the fragment is split off and the
                                  algo lower-cased to match JSON-side
                                  output.
    * ``data-requires-python``  — PEP 503 spec.  HTML-escaped (e.g.
                                  ``&gt;=3.8``); we run
                                  :func:`html.unescape` on the value
                                  before storing.
    * ``data-yanked``           — PEP 592, later folded into PEP 503's
                                  de-facto extension set.  See
                                  :func:`_normalize_yanked_html` for
                                  the absent / empty / non-empty
                                  semantics.  Note: HTML's empty-value
                                  case differs from JSON's empty-string
                                  case **intentionally** — pinned in
                                  T12.
    * ``data-core-metadata`` /
      ``data-dist-info-metadata`` — PEP 658 advertisement.  Phase 1
                                  scope is deferred per design §5.1;
                                  these attributes are observed by
                                  ``_AnchorCollector`` but not threaded
                                  into the :class:`Candidate`.

    Robustness invariants (mirroring the JSON parser):

    * Entries whose filename fails ``_extract_version`` are silently
      skipped (best-effort; partial results are more useful than a
      hard failure on a single bad anchor).
    * Entries whose wheel-tag triple is malformed (``Candidate.from_filename``
      raises ``ValueError``) are silently skipped.
    * The function does not raise on individual bad anchors.  It
      returns the empty tuple if the page URL is unparseable (no
      canonical package name extractable).  Unlike the JSON parser,
      a body that isn't valid HTML cannot be "decode-failed" by
      HTMLParser — the parser is lenient and will simply yield no
      anchors, which becomes an empty tuple.

    Cross-format parity (T12 invariant):

    Same artifact set, same hashes (lower-cased algo), same
    ``requires_python``, same ``yanked`` flag for entries whose JSON
    counterpart is unambiguously yanked.  HTML lacks ``upload-time``
    so that field is always ``None`` on the HTML side.
    """
    canonical_name = _package_name_from_page_url(page_url)
    if canonical_name is None:
        return ()

    collector = _AnchorCollector()
    # HTMLParser accepts ``str``; decode UTF-8 with replacement to
    # survive the (rare) mojibake byte in a real-PyPI page without
    # raising.  PEP 503 is silent on encoding but UTF-8 is the
    # universal de-facto.
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
    collector.feed(text)
    collector.close()

    results: list[Candidate] = []
    for attrs, anchor_text in collector.entries:
        candidate = _build_candidate_from_html(
            attrs,
            anchor_text,
            canonical_name=canonical_name,
            page_url=page_url,
        )
        if candidate is not None:
            results.append(candidate)
    return tuple(results)


__all__ = ["_parse_pep691_json", "_parse_pep503_html"]
