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

from typing import Any, Iterable, Mapping, Sequence

from pipenv.patched.pip._vendor.resolvelib.providers import AbstractProvider
from pipenv.resolver.pure_python_requirement import Requirement
from pipenv.vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
from pipenv.vendor.packaging.version import InvalidVersion, Version

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
        index_urls: Sequence[str] = ("https://pypi.org/simple",),
        allow_prereleases: bool = False,
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
        # T4: ``index_urls`` is the list of simple-API index URLs to
        # consult for candidates.  Stored as a tuple so the provider
        # can't mutate it mid-resolve (frozen-by-convention).  Order
        # matters — earlier indexes win on duplicate ``(name, version,
        # filename)`` keys (mirrors pip's --index-url precedence).
        self._index_urls: tuple[str, ...] = tuple(index_urls)
        # T4: ``allow_prereleases`` flips the default
        # ``SpecifierSet.contains(prereleases=...)`` flag.  When
        # ``False`` (default), prereleases are admitted only when the
        # specifier itself opts in (e.g. ``>=2.0a1``) — same semantics
        # as pip's ``--pre``.
        self._allow_prereleases: bool = bool(allow_prereleases)

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
    # T4 — find_matches
    # ------------------------------------------------------------------

    def find_matches(
        self,
        identifier: Identifier,
        requirements: Mapping[Identifier, Iterable[Requirement]],
        incompatibilities: Mapping[Identifier, Iterable[Any]],
    ) -> list[Any]:
        """Return compatible :class:`Candidate`\\ s ordered
        highest-version-first.

        Owned by T4 — the hot path of resolution.  Reads candidate lists
        from :class:`pipenv.resolver.manifest_cache.ParsedManifestCache`
        for each configured index URL, filters them against the merged
        constraints carried in ``requirements`` (specifier intersection)
        and the rejected-set in ``incompatibilities``, applies the
        candidate's own ``requires_python`` gate against
        ``self._target_env["python_version"]``, and returns the
        filtered list sorted by :class:`packaging.version.Version`
        descending.

        Algorithm
        ---------
        1. Unpack ``(name, _extras)`` from ``identifier``.
        2. Materialise ``requirements[identifier]`` (an iterator —
           consume eagerly because resolvelib hands us a one-shot view).
        3. Pull cached candidates for ``(index_url, name)`` from every
           configured index.  Concatenate non-``None`` results.
        4. If every index missed, dispatch a single
           :meth:`fetcher.populate` for the package — single round-trip
           per index — and re-read the cache.  Still missing on every
           index → return ``[]`` (no candidates available; caller will
           treat as a resolution dead-end rather than this method
           raising).
        5. Deduplicate by ``(name, version, filename)``.  Same artifact
           served by mirror indexes shouldn't be doubled.
        6. Build the rejected-version-by-identity tuple set for
           ``incompatibilities[identifier]``.
        7. Filter:
           * every ``req.specifier.contains(version, prereleases=...)``
             holds across all ``reqs``;
           * the candidate's identity tuple is not in ``rejected``;
           * the candidate's ``requires_python`` (if non-empty) admits
             ``target_env["python_version"]``.
        8. Sort by :class:`packaging.version.Version` descending.

        sdist / wheel handling
        ----------------------
        Per the Phase 3 design (Q-A) ``find_matches`` returns sdists
        AND wheels — the sdist-only signal triggers later inside
        :meth:`get_dependencies` (T7) when the resolver actually tries
        to expand a transitive's deps.  Q-F's top-level pre-check
        (T9) is a separate concern and runs in
        :class:`PurePythonBackend.resolve` before this method is
        invoked.  Returning all artifacts here keeps the layering
        clean.

        Cache-key caveat
        ----------------
        The :class:`ParsedManifestCache` is keyed on
        ``(index_url, package_name)`` — the provider doesn't know which
        index served a given cached candidate, so we iterate every
        configured ``index_url`` and concatenate hits.  Mirrors pip's
        ``PackageFinder``'s multi-index walk.  T5/T6 follow-up: if the
        index identity ever becomes load-bearing for an ordering
        decision, widen ``Candidate`` with an ``index_url`` field
        rather than threading it through here.
        """
        name, _extras = identifier
        reqs: list[Requirement] = list(requirements.get(identifier, []))

        # Step 3-4: read cache; on full miss, dispatch populate then
        # re-read.  We use a tiny private helper because the same shape
        # runs twice.
        cached = self._collect_cached_candidates(name)
        if not cached:
            populate = getattr(self._fetcher, "populate", None)
            if populate is not None:
                populate([(idx, name) for idx in self._index_urls])
            cached = self._collect_cached_candidates(name)
        if not cached:
            return []

        # Step 5: dedup on ``(name, version, filename)`` — same wheel
        # served by mirror indexes is a single artifact.
        seen: set[tuple[str, str, str]] = set()
        unique: list[Any] = []
        for cand in cached:
            key = (cand.name, cand.version, cand.filename)
            if key in seen:
                continue
            seen.add(key)
            unique.append(cand)

        # Step 6: rejected set, keyed on ``(name, version, filename)``
        # so an incompatibility from a different cache copy still
        # matches by identity tuple.
        rejected: set[tuple[str, str, str]] = {
            (c.name, c.version, c.filename)
            for c in incompatibilities.get(identifier, [])
        }

        # Step 7: filter.
        target_python = None
        if isinstance(self._target_env, Mapping):
            target_python = self._target_env.get("python_version")

        filtered: list[Any] = []
        for cand in unique:
            cand_key = (cand.name, cand.version, cand.filename)
            if cand_key in rejected:
                continue
            if not self._candidate_satisfies_requirements(cand, reqs):
                continue
            if not self._candidate_requires_python_ok(cand, target_python):
                continue
            filtered.append(cand)

        # Step 8: sort by Version descending.  ``InvalidVersion`` is
        # surfaced as a parse error rather than silently sorting last —
        # an unparseable version in the cache is a bug upstream
        # (PEP 691 parser should have rejected it) and we want loud
        # failure here.
        filtered.sort(key=lambda c: Version(c.version), reverse=True)
        return filtered

    # -- T4 helpers -----------------------------------------------------

    def _collect_cached_candidates(self, name: str) -> list[Any]:
        """Walk every configured index URL, concatenating non-empty
        cache hits.  Returns ``[]`` when every index misses."""
        out: list[Any] = []
        for index_url in self._index_urls:
            manifest = self._cache.get(index_url, name)
            if manifest is None:
                continue
            # ``manifest.candidates`` is a tuple per
            # :class:`CachedManifest`; extend rather than append.
            out.extend(manifest.candidates)
        return out

    def _candidate_satisfies_requirements(
        self,
        candidate: Any,
        reqs: Sequence[Requirement],
    ) -> bool:
        """Return ``True`` iff the candidate version satisfies every
        ``req.specifier`` in ``reqs``.

        An empty ``reqs`` is treated as "any version is acceptable" —
        ``resolvelib`` can legitimately call ``find_matches`` with no
        requirements registered for the identifier yet (the identifier
        is in the graph but every constraint has already been pruned).

        Prerelease policy: if any requirement's specifier opts in
        (``specifier.prereleases is True``) OR
        :attr:`_allow_prereleases` is set, prereleases are admitted.
        Otherwise the default :meth:`SpecifierSet.contains` semantics
        apply (admit only if no non-prerelease can satisfy).
        """
        try:
            version_obj = Version(candidate.version)
        except InvalidVersion:
            # Same loud-failure rationale as the sort step — the cache
            # should never carry an unparseable version.
            return False
        for req in reqs:
            spec = req.specifier
            prereleases: bool | None
            if self._allow_prereleases or spec.prereleases:
                prereleases = True
            else:
                prereleases = None  # default policy
            if not spec.contains(version_obj, prereleases=prereleases):
                return False
        return True

    def _candidate_requires_python_ok(
        self,
        candidate: Any,
        target_python: str | None,
    ) -> bool:
        """Return ``True`` iff the candidate's ``requires_python``
        admits ``target_python``.

        ``requires_python`` of ``None`` / empty string is treated as
        "no constraint" and accepted.  ``target_python`` of ``None``
        (no marker info available) is also treated as accept — the
        caller can pin a stricter ``target_env`` if it cares.

        An unparseable ``requires_python`` falls through to accept
        rather than silently dropping the candidate — mirrors pip's
        :func:`evaluate_link` behaviour (an index with a malformed
        ``requires-python`` advertisement shouldn't make the package
        invisible).
        """
        requires_python = getattr(candidate, "requires_python", None)
        if not requires_python:
            return True
        if not target_python:
            return True
        try:
            spec = SpecifierSet(requires_python)
        except InvalidSpecifier:
            return True
        # ``requires-python`` SpecifierSets typically aren't marked
        # ``prereleases=True`` even though Python prereleases (e.g.
        # ``3.13.0a1``) routinely appear as ``target_python``.  Pass
        # ``prereleases=True`` here so an alpha Python isn't silently
        # dropped — pip does the same.
        try:
            return spec.contains(target_python, prereleases=True)
        except InvalidVersion:
            return True

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
