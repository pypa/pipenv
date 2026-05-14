"""Pure-Python ``Candidate`` model for the in-tree resolver backend
(Initiative G phase 1, T1).

See:

* ``docs/dev/initiative-g-pure-python-design.md`` §5.1 — the authoritative
  definition of the :class:`Candidate` shape.
* ``initiative-g-phase1-2-plan.md`` T1 — this task.

Critical constraint (enforced by the T17 pre-commit gate when it ships):
**this module must not import from patched-pip's internal package.**
The whole point of Initiative G is to replace pip-internal data shapes
with a pipenv-owned typed model, so a regression here defeats the
initiative.  The wheel-tag derivation uses
:mod:`pipenv.vendor.packaging.tags` (vendored ``packaging``, not patched
pip), which is permitted.

Phase-1 scope: data-only.  No I/O, no parsing of remote responses (T4 /
T5 own that), no caching (T7 owns that).  The :meth:`Candidate.from_filename`
helper does a single string-shape derivation (is-wheel + wheel-tag
parsing); everything else is supplied by the caller via ``**kwargs``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from pipenv.vendor.packaging.tags import Tag, parse_tag


class Hash(NamedTuple):
    """``(algo, value)`` pair for a single artifact hash.

    NamedTuple is the right tool here: it's hashable (via tuple), supports
    structural equality out of the box, and survives :class:`frozenset`
    membership without an explicit ``__hash__`` definition.  Phase 1 only
    cares about ``sha256`` in practice but the schema accepts any algo
    name the index returns.
    """

    algo: str
    value: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """One installable artifact (wheel or sdist) for a single package version.

    Mirrors design §5.1.  All fields are immutable (``frozen=True``) and
    laid out compactly (``slots=True``) — a typical phase-3 lock pulls
    thousands of candidates across hundreds of packages, so the memory
    footprint matters.

    Field semantics
    ---------------
    name:
        PEP 503 canonical (lowercase, ``-`` separators).  Caller is
        responsible for canonicalisation — this dataclass does no
        normalisation at construction time so two callers passing
        already-canonical names don't pay the cost twice.
    version:
        PEP 440 string (e.g. ``"1.26.0"``, ``"2.0.0a1"``).  Parsing into
        a :class:`packaging.version.Version` is deferred to the caller —
        candidates from the same simple-API page typically share a
        version field many times over and we don't want to re-parse it.
    url:
        Absolute URL, already URL-quoted.  Parse-time resolution against
        the simple-API page URL (replacing pip's per-evaluation
        ``_ensure_quoted_url`` hot path) is done by the T4/T5 parsers.
    filename:
        The artifact filename (``<dist>-<version>-...whl`` or
        ``<dist>-<version>.tar.gz``).  Used by :meth:`from_filename` to
        derive wheel-vs-sdist + wheel tags.
    hashes:
        ``frozenset[Hash]`` of all hashes the index advertised for this
        artifact.  Frozenset (not list/tuple) so set-intersection with a
        Pipfile-pinned hash list is O(1).
    requires_python:
        PEP 440 specifier-set string (e.g. ``">=3.9,<4"``) or ``None`` if
        the index didn't supply one.  Caller parses/evaluates.
    yanked:
        ``True`` iff the artifact was yanked.  Both PEP 691 forms
        (boolean ``true`` and "reason string" form) flatten to ``True``
        here; the reason string (if any) goes in :attr:`yanked_reason`.
    yanked_reason:
        Free-text reason supplied by the index when yanking carried a
        message, else ``None``.  Even with ``yanked=True``,
        ``yanked_reason`` may legitimately be ``None`` (the index can
        yank without a reason).
    upload_time:
        Per-artifact upload timestamp from the index, or ``None`` if not
        supplied.  Naive vs aware is whatever the index returned;
        consumers should not assume.
    is_wheel:
        ``True`` iff :attr:`filename` ends with ``.whl``.  Derived once
        at parse time so downstream filtering doesn't re-check.
    wheel_tags:
        ``frozenset[Tag]`` parsed from the wheel filename, or ``None``
        for sdists.  Tags come from
        :func:`pipenv.vendor.packaging.tags.parse_tag` so a compatibility
        check is a frozenset intersection (vs pip's
        ``Wheel.supported(tags)`` linear scan).
    """

    name: str
    version: str
    url: str
    filename: str
    hashes: frozenset[Hash]
    requires_python: str | None
    yanked: bool
    yanked_reason: str | None
    upload_time: datetime | None
    is_wheel: bool
    wheel_tags: frozenset[Tag] | None

    @classmethod
    def from_filename(cls, __filename: str, /, **kwargs: Any) -> Candidate:
        """Build a :class:`Candidate`, deriving ``is_wheel`` + ``wheel_tags``
        from the artifact filename.

        The first parameter is positional-only (``/`` marker) so callers
        may also pass ``filename=<...>`` as a keyword without colliding
        with the positional — both the plan's acceptance-criteria
        one-liner and downstream parsers do exactly that for clarity.
        If ``filename`` appears in ``kwargs``, it is preferred for the
        stored field but the positional is what drives wheel-tag
        derivation (they should match in practice).

        Every other field is supplied by the caller via ``kwargs``.  The
        method is deliberately thin — its only job is to keep the
        wheel-vs-sdist branching co-located with the rest of the
        :class:`Candidate` definition so callers (T4/T5 parsers, T7
        cache deserialisation) all derive these two fields the same way.

        Wheel tag derivation
        --------------------
        Wheel filenames follow ``<dist>-<version>-<python>-<abi>-<platform>.whl``
        (PEP 427).  Optional build-tag (``-<build>-``) sits between
        ``<version>`` and ``<python>``.  We slice off the ``.whl``
        suffix, split on ``-`` from the right, and feed the last three
        components — ``<python>-<abi>-<platform>`` — to
        :func:`packaging.tags.parse_tag`, which returns a
        ``frozenset[Tag]`` already-expanded (e.g. ``py2.py3-none-any``
        expands to two tags).

        Malformed wheel filenames (fewer than the required components)
        raise :class:`ValueError`: a malformed wheel is a parser-side
        bug (T4/T5 must filter these before reaching here), and
        silently producing a tag-less wheel candidate would hide that
        bug downstream.
        """
        filename = __filename
        is_wheel = filename.endswith(".whl")
        wheel_tags: frozenset[Tag] | None
        if is_wheel:
            # Strip ``.whl``, then split.  PEP 427 grammar:
            #     {distribution}-{version}(-{build tag})?-{python tag}-
            #     {abi tag}-{platform tag}.whl
            # The last three hyphen-separated pieces are always the
            # tag triple, regardless of whether a build tag is present.
            stem = filename[:-4]
            parts = stem.rsplit("-", 3)
            if len(parts) < 4:
                # Fewer than 3 hyphens after ``-`` rsplit means the
                # filename lacks the tag triple.  Surface this as an
                # error rather than producing a half-populated Candidate.
                raise ValueError(
                    f"malformed wheel filename {filename!r}: "
                    f"expected at least 3 hyphen-separated tag components"
                )
            tag_string = "-".join(parts[-3:])
            wheel_tags = parse_tag(tag_string)
        else:
            wheel_tags = None

        # Caller-supplied ``filename`` kwarg wins if present (must match
        # the positional in practice — we don't enforce equality, because
        # any disagreement is a caller bug, not a model invariant).
        stored_filename = kwargs.pop("filename", filename)
        return cls(
            filename=stored_filename,
            is_wheel=is_wheel,
            wheel_tags=wheel_tags,
            **kwargs,
        )


__all__ = ["Candidate", "Hash"]
