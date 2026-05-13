"""Typed ``Requirement`` model for the pure-Python resolver backend
(Initiative G Phase 3, T1).

Represents one constraint in the resolution graph as a frozen dataclass
— replaces pip's ``InstallRequirement`` for the in-tree
``resolvelib.Provider`` path.

A :class:`Requirement` is what the provider hands to ``resolvelib`` as
a graph node alongside :class:`pipenv.resolver.candidate.Candidate`
(the matching artifact).  ``resolvelib`` groups requirements by
``(name, extras)`` via :meth:`PurePythonProvider.identify` (T3), so the
dataclass exposes ``name`` PEP-503-canonical (lowercase, ``-``
separators) and ``extras`` as a :class:`frozenset` — both hashable
and stable across construction sites.

The class is intentionally minimal: it carries the *constraints*
declared by either the Pipfile or a transitive's ``Requires-Dist`` line,
nothing else.  Candidate-side concerns (URL, hashes, wheel tags) live
on :class:`Candidate`; satisfaction checks (``is_satisfied_by``) and
candidate ordering (``find_matches``) live on :class:`PurePythonProvider`
(T4–T6).

Critical constraint (enforced by Phase 1's pre-commit grep gate):
**this module must not import from patched-pip's internal package.**
The vendored ``pipenv.vendor.packaging`` is permitted and supplies
:class:`SpecifierSet` and :class:`Marker`.

See ``docs/dev/initiative-g-phase3-design.md`` §5.1 for the design
brief and ``initiative-g-phase3-plan.md`` T1 for the validation
matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pipenv.vendor.packaging.markers import Marker
from pipenv.vendor.packaging.specifiers import SpecifierSet
from pipenv.vendor.packaging.utils import canonicalize_name

__all__ = ["Requirement"]


# Allowed ``source`` values.  Kept as a ``Literal`` on the dataclass
# field so static checkers catch typos; the runtime accepts any string
# (the dataclass is frozen but doesn't enforce ``Literal`` membership —
# pyright / mypy do).
SourceLiteral = Literal["pipfile", "transitive", "constraint"]


@dataclass(frozen=True, slots=True)
class Requirement:
    """One constraint in the resolution graph.

    Mirrors design §5.1.  All fields are immutable (``frozen=True``)
    and laid out compactly (``slots=True``) — phase-3 resolves carry
    hundreds to low-thousands of these in memory, so the footprint
    matters.

    Field semantics
    ---------------
    name:
        PEP 503 canonical (lowercase, ``-`` separators).  Use
        :meth:`from_pipfile_entry` to construct from a Pipfile shape —
        it runs ``canonicalize_name`` for you.  Direct construction
        assumes the caller already canonicalised.
    specifier:
        :class:`SpecifierSet` from ``pipenv.vendor.packaging``.  An
        empty :class:`SpecifierSet` (``SpecifierSet("")``) means "any
        version is acceptable" — this is what a Pipfile ``"*"`` entry
        flattens to.
    extras:
        :class:`frozenset` of extra names this requirement requests.
        ``resolvelib``'s identifier is ``(name, extras)`` — two
        requests for the same package with different extras are
        distinct graph nodes.  Frozenset (not list/tuple) so the
        dataclass-derived ``__hash__`` is order-independent.
    marker:
        Optional :class:`Marker` from ``pipenv.vendor.packaging``.
        ``None`` means "always applies".  Evaluation against the
        target environment happens in :meth:`PurePythonProvider.is_satisfied_by`
        (T6) and dependency-filtering inside
        :meth:`PurePythonProvider.get_dependencies` (T7).
    source:
        Where this requirement came from — a Pipfile entry, a
        transitive ``Requires-Dist``, or a constraint file.  Drives
        :meth:`PurePythonProvider.get_preference`'s tie-breaking
        (T5): Pipfile-direct beats transitive.
    parent:
        Name of the candidate that produced this transitive
        requirement (``None`` for Pipfile / constraint sources).  Used
        for diagnostics — when a conflict arises ``resolvelib`` reports
        the offending requirement and the parent chain is what the
        user needs to understand "why is this in my graph?".
    introducing_marker:
        Optional :class:`Marker` carried over from the ``Requires-Dist``
        line that introduced this transitive — for example,
        ``Requires-Dist: pytest; python_version < '3.10'`` produces a
        ``Marker("python_version < '3.10'")`` on the transitive
        :class:`Requirement` even after the existing marker-evaluator
        filter has decided to keep the entry under the target
        environment.  T_M2 populates the slot in
        :meth:`PurePythonProvider.get_dependencies`; T_M3 reads it in
        ``_translate_mapping`` to emit a ``markers="..."`` clause on
        the resulting :class:`LockedRequirement` so the pure-python
        lockfile matches pip's marker output (Initiative G Phase 3b).
        ``None`` (the default) means the introducing ``Requires-Dist``
        line carried no marker — or the requirement isn't a
        transitive at all (Pipfile / constraint sources).

        The slot is deliberately *not* exposed via
        :meth:`from_pipfile_entry` — that helper only builds top-level
        Pipfile constraints (which never carry an introducing marker
        by definition); transitives are constructed via the direct
        ``Requirement(...)`` call inside the provider.

    Hashability
    -----------
    :class:`SpecifierSet` and :class:`Marker` are both hashable in
    ``pipenv.vendor.packaging`` (specifiers.py:842, markers.py:329) —
    the dataclass-derived ``__hash__`` from ``frozen=True`` therefore
    works out of the box for every field on the class, including the
    new :attr:`introducing_marker` slot (also a :class:`Marker | None`).
    Phase-3 callers rely on ``frozenset[Requirement]`` membership, so
    this is verified explicitly by the T1 / T11 / T_M1 test suite.
    """

    name: str
    specifier: SpecifierSet
    extras: frozenset[str]
    marker: Marker | None
    source: SourceLiteral
    parent: str | None = None
    # Introduced in Initiative G Phase 3b (T_M1) — populated for
    # transitives by T_M2, read by T_M3 in ``_translate_mapping``.
    # Defaults to ``None`` so existing call sites keep working without
    # changes; ``from_pipfile_entry`` does not expose this kwarg
    # because top-level Pipfile entries never carry an introducing
    # marker.
    introducing_marker: Marker | None = None

    @classmethod
    def from_pipfile_entry(
        cls,
        name: str,
        value: Any,
        *,
        source: SourceLiteral = "pipfile",
        parent: str | None = None,
    ) -> Requirement:
        """Build a :class:`Requirement` from a Pipfile-shape entry.

        Handles the three canonical Pipfile shapes:

        * ``"*"`` (any version) → empty :class:`SpecifierSet`.
        * ``">=4.0,<6"`` (version specifier string) → parsed
          :class:`SpecifierSet`.
        * ``{"version": ">=4.0", "extras": ["argon2"],
          "markers": "python_version >= '3.10'"}`` → all three fields
          parsed.  ``"version": "*"`` also flattens to an empty
          :class:`SpecifierSet`.

        ``name`` is canonicalised via
        :func:`pipenv.vendor.packaging.utils.canonicalize_name` —
        ``"Django_Rest"`` → ``"django-rest"`` — so callers don't have
        to pre-normalise.

        Other dict keys (``editable``, ``path``, ``git``, ``index``,
        etc.) are *not* interpreted here: they belong on
        :class:`Candidate` / a separate VCS-source path, not on the
        resolution-graph constraint node.  T1's job is the constraint
        triple; richer source kinds land in later phases.

        Parameters
        ----------
        name:
            Package name as it appears in the Pipfile (any casing).
        value:
            Either a string version specifier or a dict-form Pipfile
            entry.
        source:
            ``"pipfile"`` (default), ``"transitive"``, or
            ``"constraint"``.  T5's ``get_preference`` reads this.
        parent:
            Name of the parent candidate for transitives, else
            ``None``.
        """
        canonical = canonicalize_name(name)

        if isinstance(value, str):
            spec_string = value
            extras_iter: Any = ()
            markers_string: str | None = None
        elif isinstance(value, dict):
            spec_string = value.get("version", "*")
            extras_iter = value.get("extras") or ()
            markers_string = value.get("markers")
        else:
            # Unknown shape — refuse loudly rather than producing a
            # half-populated constraint.  Pipfile parsing upstream
            # should only hand us str/dict; anything else is a bug.
            raise TypeError(
                f"unsupported Pipfile entry value for {name!r}: "
                f"{type(value).__name__}"
            )

        if spec_string in (None, "", "*"):
            specifier = SpecifierSet("")
        else:
            specifier = SpecifierSet(spec_string)

        extras = frozenset(str(e) for e in extras_iter)

        marker: Marker | None
        if markers_string:
            marker = Marker(markers_string)
        else:
            marker = None

        return cls(
            name=canonical,
            specifier=specifier,
            extras=extras,
            marker=marker,
            source=source,
            parent=parent,
        )
