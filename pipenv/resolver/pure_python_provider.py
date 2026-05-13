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
from pipenv.vendor.packaging.requirements import Requirement as PackagingRequirement
from pipenv.vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
from pipenv.vendor.packaging.utils import canonicalize_name
from pipenv.vendor.packaging.version import InvalidVersion, Version

__all__ = ["PurePythonProvider", "_SdistEncountered", "_drive_resolver"]


class _SdistEncountered(Exception):
    """Internal signal raised when a non-wheel candidate must be expanded.

    Per Initiative G Phase 3 Q-A (sign-off 2026-05-12): the pure-Python
    backend deliberately does NOT build sdists.  When the resolver tries
    to expand a candidate whose only artifact is an sdist, the provider
    raises this exception; T9's :class:`PurePythonBackend.resolve`
    catches it and translates it into a structured
    :class:`InternalError` response so the user can decide whether to
    pin a wheel-bearing version or fall back via
    ``pipenv lock --backend pip``.

    The exception carries the offending :class:`Candidate` (via
    :attr:`candidate`) so T9 can populate the error message with the
    package name, version, and filename — enough for the user to find
    the bad transitive without re-running the resolve.

    See also: design §5.3 (sdist handling), design §7 Q-A
    (rationale: fail-loud over silent fallback), plan T7 +
    T9 (validation matrices).
    """

    def __init__(self, candidate: Any) -> None:
        # Stored as attribute so T9's catch site can read it back
        # without parsing the exception message.
        self.candidate = candidate
        # Message shape mirrors the design §7 Q-A example: name +
        # version is the minimum context a user needs to find the
        # offending Pipfile entry / transitive parent chain.
        name = getattr(candidate, "name", "<unknown>")
        version = getattr(candidate, "version", "<unknown>")
        super().__init__(
            f"sdist-only candidate {name} {version!r}"
        )


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
    # T5 — get_preference (Q-C strict mirror of pip's tuple shape)
    # ------------------------------------------------------------------

    def get_preference(
        self,
        identifier: Identifier,
        resolutions: Mapping[Identifier, Any],
        candidates: Mapping[Identifier, Iterable[Any]],
        information: Mapping[Identifier, Iterable[Any]],
        backtrack_causes: Sequence[Any],
    ) -> tuple:
        """Return a sort key driving ``resolvelib``'s ordering — strict
        mirror of pip's ``get_preference`` per Initiative G Phase 3 Q-C.

        Source (side-by-side audit reference)
        -------------------------------------
        pip's canonical implementation lives at
        ``pipenv/patched/pip/_internal/resolution/resolvelib/provider.py``
        in ``PipProvider.get_preference`` (around line 176 — the line
        number drifts with pip-vendor updates).  The pip tuple in
        ``return``-order at the time of writing (low = preferred):

        1. ``not conflict_promoted`` — identifiers that have repeatedly
           caused conflicts get promoted to the front via the separate
           ``narrow_requirement_selection`` callback.
        2. ``not direct`` — ``ExplicitRequirement`` (URL-direct) entries.
        3. ``not pinned`` — ``==<version>`` with no wildcard.
        4. ``not upper_bounded`` — ``<``, ``<=``, ``~=``, ``==<ver>.*``.
        5. ``requested_order`` — integer rank of the identifier in
           ``_user_requested`` (``math.inf`` when not user-requested).
        6. ``not unfree`` — has at least one operator.
        7. ``identifier`` — lexicographic tie-breaker.

        Our mirror — Q-C and the design §5.3 summary
        --------------------------------------------
        We render the four leading axes called out in the plan T5
        validation matrix.  See the parity-divergence bullet on the
        T5 plan entry for the components we deliberately do NOT
        mirror today (and why):

        * ``not conflict_promoted`` — derived directly from
          ``backtrack_causes`` here, NOT from a separate promoted-set
          maintained by ``narrow_requirement_selection``.  We don't
          ship ``narrow_requirement_selection`` in Phase 3, so the
          backtrack count is the closest signal available.
        * ``not direct`` — pip's "direct" is ``ExplicitRequirement``
          (URL-direct).  Our :class:`Requirement` doesn't model
          URL-direct yet (T1's ``source`` is one of
          ``{"pipfile", "transitive", "constraint"}``); we render
          the closest analog by treating ``source == "pipfile"`` as
          Pipfile-direct.  Same ordering intent: user-declared beats
          transitive.
        * ``not upper_bounded`` — kept (matches pip's slot).
        * ``requested_order`` — pip's ``_user_requested`` map isn't
          available to us; omitted.  Lockfile parity is still gated
          on T15 / T_PARITY_REAL which will surface any user-visible
          divergence.

        Tuple shape this method returns (low = preferred):

            (backtrack_count,            # 0 best; ≥1 worse
             not is_pipfile,             # False (pipfile) first
             not is_pinned,              # False (pinned) first
             not is_upper_bounded,       # False (has <,<=,~=,==*) first
             not is_unfree,              # False (has any op) first
             identifier_name)            # alphabetical tie-break

        See ``docs/dev/initiative-g-phase3-design.md`` §5.3 and
        ``initiative-g-phase3-plan.md`` T5 for rationale.
        """
        # Step 1: collect the ``RequirementInformation`` rows for this
        # identifier.  Mirrors pip's ``has_information`` guard at
        # ``provider.py`` lines 207-227: information may be absent
        # transiently between state transitions and we must not blow
        # up on that.
        info_rows = list(information.get(identifier, []))

        # Step 2: source-flag — ``source == "pipfile"`` is our analog
        # of pip's ``direct``.  See divergence note above.
        is_pipfile = any(
            getattr(row.requirement, "source", None) == "pipfile"
            for row in info_rows
        )

        # Step 3: walk every ``SpecifierSet`` attached to any of the
        # requirement rows and break it into a list of ``(operator,
        # version)`` tuples — mirrors pip's ``operators`` comprehension
        # at provider.py lines 230-234.
        operators: list[tuple[str, str]] = []
        for row in info_rows:
            spec_set = getattr(row.requirement, "specifier", None)
            if spec_set is None:
                continue
            operators.extend(
                (spec.operator, spec.version) for spec in spec_set
            )

        # Step 4: derive pinned / upper-bounded / unfree from the
        # operator list — mirrors provider.py lines 236-241 verbatim.
        # ``op[:2] == "=="`` covers both ``==`` and ``===`` (the latter
        # is pip's arbitrary-equality, also pin-shaped).
        is_pinned = any(
            (op[:2] == "==") and ("*" not in ver)
            for op, ver in operators
        )
        is_upper_bounded = any(
            (op in ("<", "<=", "~=")) or (op == "==" and "*" in ver)
            for op, ver in operators
        )
        is_unfree = bool(operators)

        # Step 5: backtrack-cause count for this identifier.  Pip
        # routes this through ``narrow_requirement_selection`` +
        # ``_conflict_promoted`` (see divergence note above); we render
        # the raw count here, lower = better.  Match on the identifier
        # tuple via ``self.identify`` so a ``RequirementInformation``
        # whose requirement has the same ``(name, extras)`` counts.
        backtrack_count = 0
        for row in backtrack_causes:
            req = getattr(row, "requirement", None)
            if req is None:
                continue
            try:
                row_id = self.identify(req)
            except Exception:
                # Defensive: a malformed requirement in the backtrack
                # list shouldn't crash preference computation — skip
                # it and let resolution proceed.  ``resolvelib``
                # invariants say this can't happen, but pip applies
                # the same defensiveness around ``ireqs`` parsing.
                continue
            if row_id == identifier:
                backtrack_count += 1

        # Step 6: identifier name for the lexicographic tie-break.  Our
        # identifier is a ``(name, frozenset(extras))`` tuple — we sort
        # on ``name`` first then ``sorted(extras)`` so the order is
        # deterministic across runs.  Same intent as pip's trailing
        # ``identifier`` slot.
        name, extras = identifier
        identifier_key = (name, tuple(sorted(extras)))

        return (
            backtrack_count,
            not is_pipfile,
            not is_pinned,
            not is_upper_bounded,
            not is_unfree,
            identifier_key,
        )

    # ------------------------------------------------------------------
    # T6 — is_satisfied_by (final-acceptance predicate)
    # ------------------------------------------------------------------

    def is_satisfied_by(
        self,
        requirement: Requirement,
        candidate: Any,
    ) -> bool:
        """Return ``True`` iff ``candidate`` satisfies ``requirement``.

        This is the predicate ``resolvelib.AbstractProvider`` calls when
        a candidate has been chosen for a requirement and the resolver
        needs final confirmation it's a valid pick.  Signature from
        ``pipenv/patched/pip/_vendor/resolvelib/providers.py:127``::

            def is_satisfied_by(self, requirement, candidate) -> bool: ...

        Three checks (per design §5.3 / plan T6):

        1. **Version**: ``candidate.version in requirement.specifier``
           via :meth:`SpecifierSet.contains`.  Prerelease policy mirrors
           T4's :meth:`find_matches` (admit when either the specifier
           opts in or :attr:`_allow_prereleases` is set).

        2. **Extras compatibility**: every extra in
           ``requirement.extras`` must be a subset of
           ``candidate.extras`` (which models
           ``provides_extras``) — BUT when the candidate's
           ``extras`` is empty we treat it as "metadata not yet loaded"
           and admit the candidate.  This mirrors pip's
           :meth:`SpecifierRequirement.is_satisfied_by` at
           ``pipenv/patched/pip/_internal/resolution/resolvelib/requirements.py:111``
           which checks ONLY the specifier — pip relies on the
           ``(name, extras)`` identifier grouping (see
           :meth:`identify`) to prevent ``django`` candidates from
           ever being matched against ``django[argon2]`` requirements.
           In Phase 3 we keep the same lazy-metadata stance: the
           METADATA file is only fetched by T7's
           :meth:`get_dependencies` (the expensive path), so at the
           point ``is_satisfied_by`` runs, ``provides_extras`` is
           typically unknown.  Once a future caller does populate the
           field, this method strict-checks.  See parity-divergence
           note recorded on the T6 plan entry.

        3. **Marker**: when ``requirement.marker`` is not ``None``,
           evaluate it against the resolver's :attr:`_target_env`
           (overriding :func:`pipenv.vendor.packaging.markers.default_environment`).
           ``marker is None`` passes unconditionally.

        Pip source reference for the audit trail
        ----------------------------------------
        Pip's ``PipProvider.is_satisfied_by``
        (``pipenv/patched/pip/_internal/resolution/resolvelib/provider.py:300``)
        is a one-liner ``return requirement.is_satisfied_by(candidate)``
        delegating to the concrete ``Requirement`` subclass — for
        ``SpecifierRequirement`` (the common case) that's just the
        specifier check at ``requirements.py:111``.  Pip does NOT
        evaluate markers here either: marker filtering happens upstream
        when ``iter_dependencies`` builds the requirement list.  Our
        :class:`Requirement` doesn't pre-filter by marker (T7 will when
        building transitive requirements), so we evaluate the marker
        defensively at the predicate.  Records as a parity-divergence
        candidate for T_PARITY_MATRIX — strictly more conservative than
        pip's behaviour (admits a strict subset of what pip admits).
        """
        # ------------ Check 1: version ------------
        try:
            version_obj = Version(candidate.version)
        except InvalidVersion:
            # Same loud-failure stance as T4: an unparseable version in
            # the cache is an upstream bug, and silently admitting it
            # here would mask it.
            return False

        spec = requirement.specifier
        # Prerelease policy at the predicate: mirror pip's
        # :meth:`SpecifierRequirement.is_satisfied_by` at
        # ``pipenv/patched/pip/_internal/resolution/resolvelib/requirements.py:121``
        # — pass ``prereleases=True`` unconditionally.  Pip's rationale
        # (paraphrased from the comment there): ``PackageFinder``
        # filtered prereleases out upstream, so by the time the
        # predicate runs, an arriving prerelease candidate was already
        # admitted by the prerelease policy.  Our :meth:`find_matches`
        # plays the ``PackageFinder`` role here (T4 already filters
        # prereleases via :attr:`_allow_prereleases` + each specifier's
        # ``prereleases`` flag), so this method should not re-apply the
        # policy and silently reject a candidate :meth:`find_matches`
        # legitimately handed back.
        if not spec.contains(version_obj, prereleases=True):
            return False

        # ------------ Check 2: extras compatibility ------------
        # ``candidate.extras`` is the closest analog to METADATA's
        # ``Provides-Extra``.  Empty frozenset → metadata not loaded;
        # admit per the lazy-metadata clause above.  Non-empty →
        # strict subset check.
        candidate_extras = getattr(candidate, "extras", frozenset())
        if candidate_extras and not requirement.extras <= candidate_extras:
            return False

        # ------------ Check 3: marker ------------
        marker = requirement.marker
        if marker is not None:
            env = self._marker_environment()
            try:
                if not marker.evaluate(env):
                    return False
            except Exception:
                # A malformed marker shouldn't crash resolution — pip
                # surfaces this as a warning and treats the marker as
                # "doesn't apply".  We adopt the same defensive
                # stance: treat unevaluable markers as not-satisfied
                # so the candidate is rejected rather than crashing.
                return False

        return True

    def _marker_environment(self) -> dict[str, Any]:
        """Build the environment dict used to evaluate
        :class:`Marker` instances on requirements.

        Starts from :func:`pipenv.vendor.packaging.markers.default_environment`
        (running-Python defaults) and overlays
        ``self._target_env`` so the resolver evaluates markers against
        the *target* Python rather than the running Python.  This is
        what lets a CI host running Python 3.13 resolve a lockfile
        targeting 3.10.

        Only used by :meth:`is_satisfied_by` today; T7's
        :meth:`get_dependencies` will reuse it to filter transitive
        requirements by marker.
        """
        from pipenv.vendor.packaging.markers import default_environment

        env: dict[str, Any] = dict(default_environment())
        if isinstance(self._target_env, Mapping):
            env.update(self._target_env)
        return env

    # ------------------------------------------------------------------
    # T7 — get_dependencies (transitive requirement expansion)
    # ------------------------------------------------------------------

    def get_dependencies(self, candidate: Any) -> list[Requirement]:
        """Return the candidate's transitive :class:`Requirement` set.

        Signature contract — :class:`AbstractProvider` from
        ``pipenv/patched/pip/_vendor/resolvelib/providers.py:138``::

            def get_dependencies(self, candidate) -> Iterable[Requirement]: ...

        Algorithm (per design §5.3 + plan T7):

        1. **Q-A fail-loud gate**: if ``candidate.is_wheel`` is ``False``
           (i.e. the artifact is an sdist), raise
           :class:`_SdistEncountered` carrying the candidate.  T9
           translates this into a structured ``InternalError`` response.
           Detection uses :attr:`Candidate.is_wheel` directly — T1
           already derives the boolean from the filename suffix
           (``pipenv/resolver/candidate.py:171``), so this method does
           not need its own ``endswith('.whl')`` check.
        2. **Wheel path**: invoke ``self._metadata_fetcher(candidate)``
           — a caller-supplied callable that returns a
           :class:`pipenv.resolver.pure_python_metadata.CoreMetadata`.
           T9 wires the production stack so that this callable is a
           thin closure around :func:`fetch_metadata` with the session
           + cache bound in advance.  Tests supply a stub mapping
           ``candidate.url`` → ``CoreMetadata``.
        3. **Parse + filter** each entry in ``metadata.requires_dist``:
           - Parse via :class:`pipenv.vendor.packaging.requirements.Requirement`
             — that's the packaging parser (NOT this module's T1
             :class:`Requirement` dataclass; the parser yields
             ``name / extras / specifier / marker`` which we then
             translate INTO our T1 model).
           - Skip the entry if its marker is non-``None`` and evaluates
             False under the candidate's extras (see below).
           - Otherwise build a new :class:`Requirement` with
             ``source="transitive"`` and
             ``parent=<canonicalised candidate name>``.
        4. **Return** as a list.  ``resolvelib`` accepts any iterable;
           list is cheapest to consume and avoids accidental
           single-pass-iterator bugs in downstream callers.

        Marker semantics (parent-extras context)
        ----------------------------------------
        We mirror pip's three-branch logic at
        ``pipenv/patched/pip/_internal/metadata/importlib/_dists.py:224``::

            if not req.marker:
                yield req
            elif not extras and req.marker.evaluate({"extra": ""}):
                yield req
            elif any(req.marker.evaluate({"extra": e}) for e in extras):
                yield req

        i.e. the requirement's marker is evaluated against a marker
        environment that includes ``extra``: when the parent candidate
        requested no extras, ``extra=""`` is the context; when it
        requested ``[dev]``, ``extra="dev"`` is the context.  This is
        what makes ``Requires-Dist: pytest; extra=='dev'`` correctly
        survive only when the parent was ``django[dev]``.

        Non-extra markers (e.g. ``python_version < '3.8'``) are
        evaluated against the same overlay; pip and we both rely on
        the marker's ``extra=`` clause being a top-level conjunct, so
        an env with ``extra=""`` doesn't accidentally satisfy a
        ``python_version`` marker that's actually False.

        Parity-divergence note for T_PARITY_MATRIX
        ------------------------------------------
        Pip ALSO synthesises a "depends on the exact base" requirement
        (``factory.make_requirement_from_candidate(self.base)`` at
        ``candidates.py:533``) when expanding an
        :class:`ExtrasCandidate`.  We don't model :class:`ExtrasCandidate`
        as a separate node yet (T1's :class:`Requirement` carries
        ``extras`` directly and our :meth:`identify` partitions on
        ``(name, extras)``); the equivalent constraint emerges from the
        ``(name, frozenset())`` identifier sharing candidates with
        ``(name, frozenset({"dev"}))`` via the cache.  Records as a
        candidate divergence for the T_PARITY_MATRIX doc; lockfile
        byte-identity in T15 / T_PARITY_REAL is the gate.

        Pip ALSO swallows malformed ``Requires-Dist`` lines at
        ``_dists.py:224`` (the ``get_requirement`` call raises
        :class:`InvalidRequirement`; pip doesn't catch).  We propagate
        the same exception — a malformed METADATA body is a wheel-side
        bug worth surfacing rather than silently dropping a real dep.
        """
        # --------------- Q-A fail-loud (sdist gate) ----------------
        # is_wheel is the authoritative bool — T1 derives it from the
        # filename suffix at construction time, so we don't re-check
        # ``.endswith('.whl')`` here.  ``getattr`` defaults to ``False``
        # so a duck-typed Candidate without the field is treated as an
        # sdist (safer than treating it as a wheel and silently
        # producing wrong metadata).
        if not getattr(candidate, "is_wheel", False):
            raise _SdistEncountered(candidate)

        # --------------- Wheel: fetch + parse ----------------------
        # ``self._metadata_fetcher`` is a callable (see __init__
        # docstring).  T9 binds a session + cache around T2's
        # :func:`fetch_metadata`; tests pass a dict-backed stub.
        metadata = self._metadata_fetcher(candidate)

        # Canonicalise the parent name once — multiple Requires-Dist
        # entries will share it.  Mirrors T1's
        # :meth:`Requirement.from_pipfile_entry` behaviour
        # (canonicalisation at construction time so resolvelib's
        # ``(name, extras)`` identifier groups by canonical name).
        parent_name = canonicalize_name(getattr(candidate, "name", ""))

        # Marker environment: the SAME overlay used by T6's
        # :meth:`is_satisfied_by` (built from
        # :func:`packaging.markers.default_environment` overlaid with
        # ``self._target_env``).  The ``extra=`` slot is added per
        # requirement below.
        base_env = self._marker_environment()

        # Parent extras (frozenset) — drives the marker-context fork.
        # Empty frozenset → use ``extra=""`` context (single iteration).
        parent_extras: frozenset[str] = getattr(
            candidate, "extras", frozenset()
        )

        deps: list[Requirement] = []
        for raw_spec in metadata.requires_dist:
            # ``packaging.requirements.Requirement`` parses the line.
            # We pre-strip leading/trailing whitespace defensively;
            # CoreMetadata already does this on construction
            # (pure_python_metadata.py:592-596), but a stray empty
            # line in a hand-crafted test fixture shouldn't crash the
            # parser.
            raw_spec = raw_spec.strip()
            if not raw_spec:
                continue
            parsed = PackagingRequirement(raw_spec)

            # Marker filter — mirror pip's _dists.py:230-235.
            if parsed.marker is not None:
                if not self._marker_active_for_extras(
                    parsed.marker, base_env, parent_extras
                ):
                    continue

            # Translate parser-side fields into our T1 dataclass.
            # ``packaging``'s ``.extras`` is a ``set`` (mutable); freeze
            # so the dataclass's ``__hash__`` is well-defined.
            #
            # Dual-marker note (Initiative G Phase 3b, T_M2):
            # We populate BOTH ``marker`` and ``introducing_marker``
            # with the parser's ``.marker`` because the two fields play
            # different roles downstream:
            #   * ``marker`` — the constraint-side marker used by T6's
            #     :meth:`is_satisfied_by` when evaluating a candidate
            #     against this transitive.  The legacy T7 test contract
            #     (``test_extra_marker_kept_when_parent_requested_that_extra``)
            #     pins this to the parser's marker on transitives.
            #   * ``introducing_marker`` — the Requires-Dist-side marker
            #     read by T_M3's ``_translate_mapping`` to emit a
            #     ``markers="..."`` clause on the lockfile entry so the
            #     pure-python lockfile output matches pip.
            # The two fields could in principle be unified, but keeping
            # them distinct preserves the existing T7 contract while
            # letting T_M3 evolve marker-canonicalisation independently
            # of the resolver's evaluator semantics.
            deps.append(
                Requirement(
                    name=canonicalize_name(parsed.name),
                    specifier=parsed.specifier,
                    extras=frozenset(parsed.extras),
                    marker=parsed.marker,
                    source="transitive",
                    parent=parent_name,
                    introducing_marker=parsed.marker,
                )
            )

        return deps

    def _marker_active_for_extras(
        self,
        marker: Any,
        base_env: Mapping[str, Any],
        parent_extras: frozenset[str],
    ) -> bool:
        """Return ``True`` iff ``marker`` evaluates True for the parent's
        extras context (mirrors pip's _dists.py:230-235).

        Branch logic:

        * **No parent extras** (``parent_extras == frozenset()``):
          evaluate once under ``{"extra": ""}``.  This is what makes a
          plain ``Requires-Dist: foo; python_version<'3.8'`` survive
          (the marker has no ``extra==`` clause and ``extra=""`` is
          irrelevant to it) while a ``Requires-Dist: foo; extra=='dev'``
          is filtered out (the marker's ``extra=='dev'`` is False under
          ``extra=""``).
        * **Parent has extras**: evaluate the marker once per extra,
          ORing the results.  Pip uses ``any(...)`` over
          ``[{"extra": e} for e in extras]``; we match exactly.

        Defensive: a malformed marker (e.g. references an unknown
        marker variable) is treated as inactive — same loud-failure
        stance as T6's :meth:`is_satisfied_by` (better to surface the
        issue via "this dep didn't apply" than to crash mid-resolve).
        Pip silently ignores the same shape per
        :meth:`Marker.evaluate`'s "missing key" path.
        """
        # Build a fresh environment per evaluation so we don't mutate
        # the caller's ``base_env`` (which is shared across all
        # Requires-Dist lines in a single get_dependencies call).
        if not parent_extras:
            env = dict(base_env)
            env["extra"] = ""
            try:
                return bool(marker.evaluate(env))
            except Exception:  # noqa: BLE001
                return False

        for extra in parent_extras:
            env = dict(base_env)
            env["extra"] = extra
            try:
                if marker.evaluate(env):
                    return True
            except Exception:  # noqa: BLE001
                # Continue trying other extras — a marker that's
                # malformed under one extra context may still evaluate
                # successfully under another (rare but possible).
                continue
        return False


# ---------------------------------------------------------------------------
# T8 — _drive_resolver: thin wrapper around resolvelib.Resolver
# ---------------------------------------------------------------------------


def _drive_resolver(
    requirements: Iterable[Requirement],
    provider: PurePythonProvider,
    *,
    reporter: Any = None,
    max_rounds: int = 100,
) -> Any:
    """Convenience wrapper around :class:`resolvelib.Resolver` for
    unit and integration tests.

    Production code (T9's :class:`PurePythonBackend`) calls this helper
    too, so the wiring of provider → reporter → :meth:`Resolver.resolve`
    lives in exactly one place.  Translation of
    :class:`ResolutionImpossible` / :class:`_SdistEncountered` into the
    backend's :class:`ResolverResponse` shape is T9's concern — this
    helper deliberately does not catch either exception.

    Parameters
    ----------
    requirements:
        Iterable of top-level :class:`Requirement` instances (typically
        the parsed Pipfile entries).  Consumed eagerly inside resolvelib;
        no need to re-yield.
    provider:
        Configured :class:`PurePythonProvider`.  All five
        ``AbstractProvider`` methods (T3–T7) must be functional —
        :func:`_drive_resolver` does not patch around half-implemented
        providers.
    reporter:
        Optional :class:`resolvelib.BaseReporter` subclass (or
        compatible duck-type).  Defaults to a freshly-instantiated
        :class:`BaseReporter` (no-op callbacks) when ``None`` is passed.
        T9 may pass a logging reporter; tests use the default.
    max_rounds:
        Forwarded verbatim to :meth:`Resolver.resolve`.  Resolvelib's
        own default is 100; we mirror it so callers see the same
        behaviour without re-reading the resolvelib source.  Raise
        only if a real lock genuinely needs more rounds — bumping
        usually masks a circular-dep bug upstream.

    Returns
    -------
    A :class:`resolvelib.resolvers.abstract.Result` namedtuple with
    ``.mapping`` (resolved candidates keyed on the provider's
    identifier tuple), ``.graph`` (dep DAG), and ``.criteria``
    (per-identifier resolution metadata).  Callers typically only need
    ``.mapping``.

    Raises
    ------
    :class:`resolvelib.ResolutionImpossible`
        Propagated from :meth:`Resolver.resolve` when no satisfying
        assignment exists.  T9 catches and translates.
    :class:`_SdistEncountered`
        Propagated from :meth:`PurePythonProvider.get_dependencies`
        when the resolver tries to expand an sdist-only candidate.
        T9 catches and translates per the Q-A fail-loud policy.
    """
    from pipenv.patched.pip._vendor.resolvelib import BaseReporter, Resolver

    if reporter is None:
        reporter = BaseReporter()
    return Resolver(provider, reporter).resolve(
        requirements, max_rounds=max_rounds
    )
