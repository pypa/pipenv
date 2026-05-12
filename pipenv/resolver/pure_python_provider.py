"""Pure-Python ``resolvelib.AbstractProvider`` adapter for the
in-tree resolver backend (Initiative G phase 3).

This module is the third leg of the Phase 3 trio:

* :mod:`pipenv.resolver.pure_python_requirement` — typed
  :class:`Requirement` (T1, shipped at commit ``a5ac1eff``).
* :mod:`pipenv.resolver.pure_python_metadata` — :class:`MetadataFetcher`
  (T2, shipped at commit ``93bc3f74``).
* **This module** — :class:`PurePythonProvider` that consumes both and
  drives ``resolvelib.Resolver`` directly, replacing pip's
  ``PipProvider`` / ``LinkEvaluator`` / ``Wheel`` pipeline.

The class is built up across T3–T7:

* **T3 (this commit)** — :meth:`PurePythonProvider.__init__` +
  :meth:`PurePythonProvider.identify`.
* **T4** — :meth:`PurePythonProvider.find_matches`.
* **T5** — :meth:`PurePythonProvider.get_preference`.
* **T6** — :meth:`PurePythonProvider.is_satisfied_by`.
* **T7** — :meth:`PurePythonProvider.get_dependencies`.

The four un-implemented hot-path methods raise :class:`NotImplementedError`
with the task label (``"T4"`` etc.) so the eventual integration tests
fail loud with a clear pointer at which follow-up task is missing,
rather than silently returning ``None``.

Critical constraint (enforced by Phase 1's pre-commit grep gate):
**this module must not import from patched-pip's internal package.**
The base class :class:`AbstractProvider` comes from
:mod:`pipenv.patched.pip._vendor.resolvelib.providers` — that path is
``_vendor`` (a third-party-vendored dependency of patched pip), not
``_internal`` (pip's own modules), so the gate is satisfied.

See ``docs/dev/initiative-g-phase3-design.md`` §5.3 for the design
brief and ``initiative-g-phase3-plan.md`` T3 for the validation
matrix.
"""

from __future__ import annotations

from typing import Any

from pipenv.patched.pip._vendor.resolvelib.providers import AbstractProvider
from pipenv.resolver.pure_python_requirement import Requirement

__all__ = ["PurePythonProvider"]


# Identifier shape — matches the design §5.3 contract: a 2-tuple of
# ``(canonical_name, frozenset(extras))``.  Pinned here as a documented
# alias so T4 / T5 (which consume the identifier from
# ``resolvelib.Resolver`` callbacks) reference the same shape without
# re-declaring it.
Identifier = tuple[str, frozenset[str]]


class PurePythonProvider(AbstractProvider):
    """``resolvelib.AbstractProvider`` over :class:`Requirement` +
    :class:`pipenv.resolver.candidate.Candidate`.

    Phase 3 design §5.3.  The constructor takes the four collaborators
    the hot-path methods (T4–T7) need:

    * ``cache`` — :class:`pipenv.resolver.manifest_cache.ParsedManifestCache`
      (or any object exposing the same ``.get(index_url, name)`` shape).
      T4's :meth:`find_matches` reads candidate lists from here.
    * ``fetcher`` — :class:`pipenv.resolver.fetcher.ParallelFetcher`.
      T4 calls ``.populate([(index_url, name)])`` on cache miss.
    * ``metadata_fetcher`` — :class:`pipenv.resolver.pure_python_metadata.MetadataFetcher`.
      T7's :meth:`get_dependencies` invokes ``.fetch_metadata(candidate)``
      to retrieve ``Requires-Dist`` for wheel candidates.
    * ``target_env`` — a mapping of marker-variable → value (e.g.
      ``{"python_version": "3.12", "sys_platform": "linux"}``).  T6 +
      T7 use this to evaluate :class:`Marker` objects.

    All four are stored verbatim; this class does not own their
    lifecycle.  Tests pass plain sentinels for the cache / fetcher /
    metadata_fetcher when only T3's behaviour is under test.

    Why kwargs-only
    ---------------
    The ``__init__`` signature is ``*, cache, fetcher, metadata_fetcher,
    target_env`` — keyword-only — so that adding a new collaborator in
    Phase 4 (e.g. an ``index_url`` resolver) doesn't break the call
    sites in T8's smoke test and T9's backend.  All four call sites
    pass the args by name today.
    """

    def __init__(
        self,
        *,
        cache: Any,
        fetcher: Any,
        metadata_fetcher: Any,
        target_env: Any,
    ) -> None:
        # ``Any`` rather than concrete types so unit tests can pass
        # plain object sentinels for the fields T3 doesn't touch.  T4–T7
        # tighten types as they consume each collaborator — at which
        # point a static checker will catch a wrong shape at that call
        # site, not here.
        self._cache = cache
        self._fetcher = fetcher
        self._metadata_fetcher = metadata_fetcher
        self._target_env = target_env

    # ------------------------------------------------------------------
    # T3 — identify
    # ------------------------------------------------------------------

    def identify(self, requirement_or_candidate: Any) -> Identifier:
        """Group-key for ``resolvelib``: ``(canonical_name, frozenset(extras))``.

        Accepts both :class:`Requirement` and
        :class:`pipenv.resolver.candidate.Candidate` instances.  Two
        graph elements with the same identifier are merged into the
        same group by ``resolvelib`` — different extras are different
        groups by design (e.g. ``django`` vs ``django[argon2]``).

        Implementation note
        -------------------
        We branch on ``isinstance(req_or_cand, Requirement)`` for the
        :class:`Requirement` path so static checkers see the type
        narrowing on ``.extras``.  The :class:`Candidate` path uses
        ``getattr(..., "extras", frozenset())`` — duck-typing over
        ``.name`` and ``.extras`` rather than importing ``Candidate``
        directly.  That keeps this module's import graph one node
        smaller and dodges any future circular if T9's backend wants
        to hand the provider a :class:`Candidate` subclass.

        Both branches return a 2-tuple whose second element is a
        :class:`frozenset` — never ``None``, never a ``list`` — so
        ``hash(identifier)`` works unconditionally and the
        ``resolvelib`` invariant "identifiers are hashable" holds.

        The ``name`` field is already PEP-503-canonical on
        :class:`Requirement` (T1's ``from_pipfile_entry`` runs
        ``canonicalize_name``).  :class:`Candidate.name` is documented
        as canonical too (caller's responsibility, see the
        ``Candidate`` field docstring) — we don't re-canonicalise.
        """
        if isinstance(requirement_or_candidate, Requirement):
            return (
                requirement_or_candidate.name,
                requirement_or_candidate.extras,
            )

        # Candidate (or any duck-type with ``.name`` / ``.extras``).
        # ``.extras`` defaults to ``frozenset()`` if missing — survives
        # against pre-T3 ``Candidate`` instances that pre-date the
        # field addition (defensive: ``Candidate`` itself defaults to
        # ``frozenset()`` via ``field(default_factory=frozenset)`` so
        # this fallback should never fire in practice).
        name: str = requirement_or_candidate.name
        extras: frozenset[str] = getattr(
            requirement_or_candidate, "extras", frozenset()
        )
        return (name, extras)

    # ------------------------------------------------------------------
    # T4 — find_matches (NOT YET IMPLEMENTED)
    # ------------------------------------------------------------------

    def find_matches(self, identifier, requirements, incompatibilities):
        """Return an iterator of compatible :class:`Candidate`s ordered
        highest-version-first.

        Owned by T4.  Lands in a subsequent commit on this same module.
        """
        raise NotImplementedError("T4: PurePythonProvider.find_matches")

    # ------------------------------------------------------------------
    # T5 — get_preference (NOT YET IMPLEMENTED)
    # ------------------------------------------------------------------

    def get_preference(
        self,
        identifier,
        resolutions,
        candidates,
        information,
        backtrack_causes,
    ):
        """Return a sort key driving ``resolvelib``'s ordering — strict
        mirror of pip's ``get_preference`` per Q-C.

        Owned by T5.  Lands in a subsequent commit on this same module.
        """
        raise NotImplementedError("T5: PurePythonProvider.get_preference")

    # ------------------------------------------------------------------
    # T6 — is_satisfied_by (NOT YET IMPLEMENTED)
    # ------------------------------------------------------------------

    def is_satisfied_by(self, requirement, candidate):
        """Return True iff the candidate's version satisfies the
        requirement's specifier AND markers evaluate True AND extras
        are compatible.

        Owned by T6.  Lands in a subsequent commit on this same module.
        """
        raise NotImplementedError("T6: PurePythonProvider.is_satisfied_by")

    # ------------------------------------------------------------------
    # T7 — get_dependencies (NOT YET IMPLEMENTED)
    # ------------------------------------------------------------------

    def get_dependencies(self, candidate):
        """Return an iterable of :class:`Requirement` instances for the
        candidate's ``Requires-Dist`` — fetches metadata via the
        :class:`MetadataFetcher`.  Raises ``_SdistEncountered`` for
        sdist-only candidates (Q-A fail-loud path).

        Owned by T7.  Lands in a subsequent commit on this same module.
        """
        raise NotImplementedError("T7: PurePythonProvider.get_dependencies")
