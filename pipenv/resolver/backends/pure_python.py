"""``pure-python`` resolver backend (Initiative G Phase 3, T9).

Implements the Initiative F ``Backend`` protocol over the
:class:`pipenv.resolver.pure_python_provider.PurePythonProvider` (T3-T8)
+ :func:`pipenv.resolver.pure_python_metadata.fetch_metadata` (T2) +
:class:`pipenv.resolver.pure_python_requirement.Requirement` (T1)
chain.

Flow inside :meth:`PurePythonBackend.resolve`:

1. **Pre-fetch** top-level package candidates via
   :meth:`ParallelFetcher.populate` (Q-B).
2. **Q-F top-level wheel-availability pre-check**: scan cached
   candidates for each top-level package; abort with a structured
   :class:`ResolutionError` if any top-level has candidates but ZERO
   are wheels.  Catches the common sdist-only-toplevel case at startup
   instead of 30 s into a doomed resolve.  (T_S4 will repurpose this
   gate now that T_S3 makes sdists resolvable.)
3. Build :class:`Requirement` set from ``request.packages.specs``.
4. Drive :class:`resolvelib.Resolver` via
   :func:`pipenv.resolver.pure_python_provider._drive_resolver`; any
   sdist METADATA needed during expansion is built transparently via
   T_S2's :meth:`MetadataFetcher.fetch_metadata` routing (Phase 3b
   T_S3 removed the Phase 3a ``_SdistEncountered`` handler — sdists
   no longer reach an error path).
5. :class:`resolvelib.ResolutionImpossible` →
   :class:`ResolutionError`; any other exception →
   :class:`InternalError`; otherwise translate the resolved candidate
   mapping into a tuple of :class:`LockedRequirement` and return
   :class:`ResolverSuccess`.

See ``docs/dev/initiative-g-phase3-design.md`` §5.4 and
``initiative-g-phase3-plan.md`` T9.

NOTE: this module imports only from ``pipenv.patched.pip._vendor.resolvelib``
(vendor, not internal — that's the resolvelib exception type lookup
inside :meth:`resolve`).  The pipenv pure-Python backend deliberately
sits on the typed schema surface, not on patched-pip internals.
"""
from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Any, Sequence

from pipenv.resolver.pure_python_metadata import (
    MetadataCache,
    fetch_metadata,
)
from pipenv.resolver.pure_python_provider import (
    PurePythonProvider,
    _drive_resolver,
)
from pipenv.resolver.pure_python_requirement import Requirement
from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    Diagnostics,
    InternalError,
    LockedRequirement,
    ResolutionError,
    ResolverRequest,
    ResolverResponse,
    ResolverSuccess,
)
from pipenv.vendor.packaging.specifiers import (
    InvalidSpecifier,
    SpecifierSet,
)


class PurePythonBackend:
    """Resolver backend that drives the pure-Python resolvelib provider.

    Attributes
    ----------
    cache:
        :class:`pipenv.resolver.manifest_cache.ParsedManifestCache` (or
        compatible) — the candidate-listing store the provider's
        :meth:`find_matches` reads.
    fetcher:
        :class:`pipenv.resolver.fetcher.ParallelFetcher` (or compatible)
        — used to populate the cache for the top-level package set
        before resolution starts.
    session:
        Duck-typed HTTP session passed verbatim to
        :func:`fetch_metadata`.  Production hands us a configured
        ``urllib3.PoolManager``; tests pass a :class:`mock.MagicMock`.
    metadata_cache:
        :class:`MetadataCache` used as the read-through cache for
        wheel-METADATA bodies.
    target_env:
        Optional mapping of marker-environment variables (``python_version``,
        ``sys_platform``, etc.).  Defaults to a snapshot of the running
        interpreter's :func:`packaging.markers.default_environment`
        (added lazily on first use).
    index_urls:
        Tuple of simple-API index URLs to consult for candidates.
    """

    name: str = "pure-python"

    def __init__(
        self,
        *,
        cache: Any = None,
        fetcher: Any = None,
        session: Any = None,
        metadata_cache: MetadataCache | Any = None,
        target_env: dict | None = None,
        index_urls: Sequence[str] = ("https://pypi.org/simple",),
    ) -> None:
        # All collaborators default to ``None`` so the class is
        # zero-arg-constructible — the Initiative F registry's
        # :func:`pipenv.resolver.backends.get_backend` helper invokes
        # ``cls()`` for class-shaped registry entries (see T10).  A
        # backend created without collaborators answers ``.name`` and
        # ``.is_available()`` correctly; ``.resolve()`` requires the
        # dispatcher to inject collaborators (production wiring lives
        # in the Phase 4 dispatcher work).  Tests pass collaborators
        # explicitly via keyword args.
        self._cache = cache
        self._fetcher = fetcher
        self._session = session
        self._metadata_cache = metadata_cache
        self._target_env = target_env
        self._index_urls: tuple[str, ...] = tuple(index_urls)

    # ------------------------------------------------------------------
    # Backend protocol
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """The pure-python backend is always available — it ships
        in-tree as part of ``pipenv.resolver``; there is no external
        binary or optional dependency to probe for.
        """
        return True

    def resolve(self, request: ResolverRequest) -> ResolverResponse:
        """Run resolution against the typed request envelope.

        Returns a typed :class:`ResolverResponse`.  Failure modes are
        translated to structured ``result`` variants rather than raised
        out of the backend (per the Initiative F ``Backend`` contract).
        """
        # Bootstrap collaborators from the request when not pre-injected
        # (T9b, 2026-05-12).  Production code arrives here via the
        # Initiative F registry's ``get_backend("pure-python")`` helper
        # which calls ``cls()`` with no args (T10) — so the four
        # collaborators are ``None`` on ``self``.  Unit tests still
        # inject them via ``__init__`` kwargs; the bootstrap is
        # idempotent and only fills fields that are currently ``None``.
        self._bootstrap_from_request(request)

        # --- index URLs from request.sources ----------------------------
        # request.sources is the post-mirror-substitution source list;
        # if empty (subprocess fixtures sometimes omit it) fall through
        # to the backend's configured default.
        request_index_urls = tuple(s.url for s in request.sources) or self._index_urls

        # Top-level names per the typed schema:
        # ``request.packages.specs`` is a Mapping[str, str].
        top_level_names = tuple(sorted(request.packages.specs.keys()))

        # ---- Step 1: pre-fetch (Q-B) -----------------------------------
        targets = [
            (idx, name)
            for idx in request_index_urls
            for name in top_level_names
        ]
        try:
            self._fetcher.populate(targets)
        except Exception:  # noqa: BLE001
            # Pre-fetch failures are non-fatal in production (Q-B says
            # the provider falls through to lazy ``populate`` on cache
            # miss).  Surface the error to diagnostics-style behaviour
            # but continue — let ``find_matches`` retry on miss.
            # (We do NOT abort; that's what the Q-F pre-check below
            # is for, and resolvelib's own error path handles "no
            # candidates available".)
            pass

        # ---- Step 2: Q-F top-level wheel-availability pre-check --------
        # For each top-level package, scan cached candidates across
        # configured indexes.  If candidates exist AND none are wheels
        # → fail loud BEFORE driving resolvelib.
        sdist_only_top: list[str] = []
        for name in top_level_names:
            saw_any = False
            saw_wheel = False
            for idx in request_index_urls:
                manifest = self._cache.get(idx, name)
                if manifest is None:
                    continue
                for cand in getattr(manifest, "candidates", ()):
                    saw_any = True
                    if getattr(cand, "is_wheel", False):
                        saw_wheel = True
                        break
                if saw_wheel:
                    break
            if saw_any and not saw_wheel:
                sdist_only_top.append(name)

        if sdist_only_top:
            names = sorted(sdist_only_top)
            target_python = self._describe_target_python(request)
            target_platform = self._describe_target_platform()
            pip_message = (
                f"Pure-python backend cannot resolve {names!r}: no wheel available "
                f"for Python {target_python} on {target_platform}.  "
                f"Pin to a version with wheels, or retry with "
                f"`pipenv lock --backend pip`."
            )
            return ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=ResolutionError(
                    kind="resolution_error",
                    conflicts=(),
                    pip_message=pip_message,
                ),
                diagnostics=Diagnostics(),
            )

        # ---- Step 3: build Requirement set -----------------------------
        requirements: list[Requirement] = []
        for name, spec_value in request.packages.specs.items():
            # The wire-shape ``spec_value`` is a pip-install argument
            # line (e.g. ``"requests==2.31.0"``).  Pipfile entries flow
            # through here too — Requirement.from_pipfile_entry accepts
            # str values (parsed as a SpecifierSet directly) and dict
            # values.  Handle both shapes.
            requirements.append(
                Requirement.from_pipfile_entry(
                    name,
                    self._spec_value_to_pipfile_entry(name, spec_value),
                )
            )

        # ---- Step 4: construct provider --------------------------------
        # Bind a metadata-fetcher closure around T2's fetch_metadata so
        # the provider's get_dependencies (T7) receives a callable that
        # only takes a Candidate.
        session = self._session
        metadata_cache = self._metadata_cache

        def _metadata_fetcher(candidate: Any):
            return fetch_metadata(candidate, session, cache=metadata_cache)

        provider = PurePythonProvider(
            cache=self._cache,
            fetcher=self._fetcher,
            metadata_fetcher=_metadata_fetcher,
            target_env=self._resolved_target_env(),
            index_urls=request_index_urls,
            allow_prereleases=bool(request.options.pre),
        )

        # ---- Step 5: drive resolvelib ----------------------------------
        # Local import to avoid module-load-time cost for callers who
        # never select this backend.
        from pipenv.patched.pip._vendor.resolvelib import ResolutionImpossible

        try:
            result = _drive_resolver(requirements, provider)
        except ResolutionImpossible as exc:
            pip_message = self._format_resolution_impossible(exc)
            return ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=ResolutionError(
                    kind="resolution_error",
                    # ConflictRecord has fields {package, version,
                    # requires} — these are pip-style English-table
                    # rows, not resolvelib's RequirementInformation
                    # shape.  We leave this empty (the pip_message
                    # carries the same information in a free-text
                    # form) rather than synthesise an awkward
                    # translation that would diverge from the pip
                    # backend's format.
                    conflicts=(),
                    pip_message=pip_message,
                ),
                diagnostics=Diagnostics(),
            )
        except Exception as exc:  # noqa: BLE001
            return ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=InternalError(
                    kind="internal_error",
                    message=str(exc),
                    traceback=traceback.format_exc(),
                ),
                diagnostics=Diagnostics(),
            )

        # ---- Step 6: translate resolved mapping ------------------------
        # T_M3 (Initiative G Phase 3b): the translator now reads the
        # ``criteria`` side-channel from the resolvelib ``Result`` to
        # emit ``markers`` clauses, so we hand it the full Result rather
        # than just ``.mapping``.
        locked = self._translate_mapping(result, request_index_urls)
        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=ResolverSuccess(kind="success", locked=locked),
            diagnostics=Diagnostics(),
        )

    # ------------------------------------------------------------------
    # Bootstrap (T9b — 2026-05-12)
    # ------------------------------------------------------------------

    def _bootstrap_from_request(self, request: ResolverRequest) -> None:
        """Populate missing collaborators from the request envelope.

        Idempotent: only fills fields that are currently ``None`` on
        ``self``.  Tests that pass collaborators via ``__init__``
        kwargs are unaffected — their pre-injected values short-circuit
        every branch below.

        Production wiring (the Initiative F registry path) lands here
        with all four fields at ``None`` because
        :func:`pipenv.resolver.backends.get_backend` invokes ``cls()``
        with no args (T10).  Constructor signatures are pinned to the
        existing modules:

        * :class:`pipenv.resolver.pep691.PEP691Client` — ``(session,
          *, netrc_path, cert, verify)``.
        * :class:`pipenv.resolver.fetcher.ParallelFetcher` — ``(client,
          cache, *, max_workers, default_ttl)``.
        * :class:`pipenv.resolver.manifest_cache.ParsedManifestCache` —
          ``(root, schema_version)``.
        * :class:`pipenv.resolver.pure_python_metadata.MetadataCache` —
          ``(root)``.

        Cache-dir resolution mirrors the production prefetch path at
        ``pipenv/routines/lock.py::_prefetch_index_manifests_if_enabled``:
        ``$PIPENV_CACHE_DIR / "pipenv-manifests"`` for the manifest
        cache root.  ``ResolverRequest`` carries no ``cache_dir`` field
        of its own (see ``pipenv/resolver/schema.py``), so we fall back
        to the environment variable with a user-cache default — this
        matches the convention :class:`pipenv.environments.Setting`
        uses to resolve :attr:`PIPENV_CACHE_DIR` on the parent side.

        ``verify_ssl`` is taken from the *first* source on the request
        (Phase 3 single-policy simplification).  Multi-policy fan-out
        across heterogeneous source sets is the lock-route's
        responsibility — when the dispatcher constructs the backend
        with collaborators pre-built, the FU2 per-policy fan-out at
        ``lock.py`` applies and this branch is skipped entirely.
        """
        # Session: a urllib3 PoolManager (production) or a duck-typed
        # mock (tests).  We follow ``pipenv.utils.internet.get_requests_session``
        # — the same factory the production prefetch path uses — so
        # cert/verify/cache-dir wiring is shared between the prefetcher
        # and this backend.  Failure here is *not* fatal: if pip's
        # internals aren't importable for any reason (e.g. a sandboxed
        # test path), fall back to a bare PoolManager and surface the
        # error downstream via the fetcher's own error envelope.
        if self._session is None:
            verify = bool(request.sources[0].verify_ssl) if request.sources else True
            try:
                from pipenv.utils.internet import get_requests_session

                self._session = get_requests_session(verify_ssl=verify)
            except Exception:  # noqa: BLE001 — last-resort fallback.
                from pipenv.patched.pip._vendor.urllib3 import PoolManager

                self._session = PoolManager()

        # Manifest cache: filesystem-backed, rooted under PIPENV_CACHE_DIR.
        if self._cache is None:
            from pipenv.resolver.manifest_cache import ParsedManifestCache

            cache_root = self._cache_dir_from_request(request) / "pipenv-manifests"
            self._cache = ParsedManifestCache(cache_root)

        # Parallel fetcher: needs a PEP691Client wrapping the session +
        # the manifest cache built above.  ``verify`` is sourced from
        # the first request source (Phase 3 single-policy default).
        if self._fetcher is None:
            from pipenv.resolver.fetcher import ParallelFetcher
            from pipenv.resolver.pep691 import PEP691Client

            verify = bool(request.sources[0].verify_ssl) if request.sources else True
            client = PEP691Client(self._session, verify=verify)
            self._fetcher = ParallelFetcher(client, self._cache)

        # Metadata cache: separate filesystem cache (different on-disk
        # schema vs. manifest cache, so a sibling directory rather than
        # nesting under ``pipenv-manifests``).
        if self._metadata_cache is None:
            metadata_root = (
                self._cache_dir_from_request(request)
                / "pipenv-manifests"
                / "metadata-v1"
            )
            self._metadata_cache = MetadataCache(metadata_root)

    @staticmethod
    def _cache_dir_from_request(request: ResolverRequest) -> Path:
        """Resolve the on-disk cache root.

        ``ResolverRequest`` does not carry a ``cache_dir`` field today;
        we mirror the parent-side default chain used by
        :class:`pipenv.environments.Setting`::

            $PIPENV_CACHE_DIR
              → pip's USER_CACHE_DIR (fallback to ~/.cache/pipenv on
                POSIX, %LOCALAPPDATA%/pipenv/Cache on Windows)

        We deliberately do NOT import pip-internal locations here —
        that's the coupling Initiative G exists to break.  The
        ``~/.cache/pipenv`` fallback is the Linux default of pip's
        USER_CACHE_DIR and is good enough for the bootstrap path;
        production runs always have ``PIPENV_CACHE_DIR`` set by the
        parent.
        """
        env_value = os.environ.get("PIPENV_CACHE_DIR")
        if env_value:
            return Path(env_value)
        return Path.home() / ".cache" / "pipenv"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _spec_value_to_pipfile_entry(name: str, spec_value: str) -> Any:
        """Translate a wire-shape pip-install line into a value that
        :meth:`Requirement.from_pipfile_entry` understands.

        The wire format is a pip argument string like
        ``"requests==2.31.0"`` or ``"requests>=2,<3"`` — sometimes just
        the package name (``"requests"`` ⇒ "any version").  We strip
        the leading package name (if present) and pass the remainder
        as the specifier string; bare names map to ``"*"``.
        """
        line = (spec_value or "").strip()
        if not line:
            return "*"
        # Pip-install lines that lead with the package name followed
        # by a specifier: split on the first specifier-introducing
        # char.  We do this conservatively — if no specifier char is
        # present, treat the whole line as either "name only" (⇒ "*")
        # or a bare specifier.
        for marker_char in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            idx = line.find(marker_char)
            if idx != -1:
                # Everything from the marker onward is the specifier.
                return line[idx:]
        # No specifier chars — either the bare package name or some
        # other shape (URL, VCS).  Bare names ⇒ "*"; anything else
        # we forward verbatim and let the parser raise.
        if line.lower() == name.lower():
            return "*"
        return "*"

    @staticmethod
    def _describe_target_python(request: ResolverRequest) -> str:
        """Best-effort label for the target Python version, for the
        Q-F error message only.  Defaults to the running interpreter
        when no marker override is set.
        """
        if request.python_marker_override:
            return request.python_marker_override
        import sys

        return f"{sys.version_info.major}.{sys.version_info.minor}"

    @staticmethod
    def _describe_target_platform() -> str:
        import sys

        return sys.platform

    def _resolved_target_env(self) -> dict:
        """Return a marker-environment dict for the provider.

        Computed lazily so test fixtures that pass an explicit
        ``target_env`` win, and production paths get the running
        interpreter's defaults without paying the cost on every
        ``resolve`` call from a long-lived process.
        """
        if self._target_env is not None:
            return self._target_env
        # Default to the running interpreter's marker environment.
        # ``packaging.markers.default_environment`` is the canonical
        # PEP 508 source; we route through the vendored copy so this
        # module avoids any patched-pip-internal coupling.
        from pipenv.vendor.packaging.markers import default_environment

        env = dict(default_environment())
        self._target_env = env
        return env

    @staticmethod
    def _format_resolution_impossible(exc: Any) -> str:
        """Render a :class:`ResolutionImpossible` as a multi-line
        ``pip_message`` body.

        Each cause is rendered as ``"  - <parent> requires <name><spec>"``
        so the user can locate the conflict without parsing resolvelib
        internals.  Mirrors the design's Q-F formatting.
        """
        lines = ["Resolution impossible — conflicting constraints:"]
        causes = getattr(exc, "causes", None) or ()
        for info in causes:
            req = getattr(info, "requirement", None)
            parent = getattr(info, "parent", None)
            parent_label: str
            if parent is None:
                parent_label = "<root>"
            else:
                p_name = getattr(parent, "name", None)
                p_version = getattr(parent, "version", None)
                if p_name and p_version:
                    parent_label = f"{p_name} {p_version}"
                else:
                    parent_label = str(parent)
            req_name = getattr(req, "name", "<unknown>")
            req_spec = getattr(req, "specifier", "")
            lines.append(f"  - {parent_label} requires {req_name}{req_spec}")
        return "\n".join(lines)

    def _translate_mapping(
        self,
        result: Any,
        index_urls: Sequence[str],
    ) -> tuple[LockedRequirement, ...]:
        """Translate the resolvelib ``Result`` into typed
        :class:`LockedRequirement` entries.

        ``result`` is the :class:`resolvelib.resolvers.abstract.Result`
        namedtuple ``(mapping, graph, criteria)``.  Today we read
        ``mapping`` (resolved candidates) and ``criteria`` (per-identifier
        :class:`Criterion` whose ``.information`` is the list of
        :class:`RequirementInformation` rows that selected each candidate).

        Field mapping (per :class:`LockedRequirement` in
        ``pipenv/resolver/schema.py``):

        * ``name``       ← ``candidate.name``
        * ``version``    ← ``"==" + candidate.version`` (matches the
          existing pip-backend lockfile shape — see
          ``Entry.get_cleaned_dict`` / ``_clean_version``).
        * ``extras``     ← ``tuple(sorted(candidate.extras))``
        * ``markers``    ← ``and``-join of:
            - the Requires-Python marker derived from
              ``candidate.requires_python`` (T_M3), and
            - the ``or``-join of every ``Requirement.introducing_marker``
              attached to the criterion's ``information`` rows (T_M2 +
              T_M3).
          ``None`` when neither source contributes.  See
          :func:`_requires_python_to_marker` and
          :func:`_introducing_marker_for` for the per-source rules.
        * ``hashes``     ← ``tuple(sorted("<algo>:<value>"))`` from
          ``candidate.hashes`` (frozenset of :class:`Hash`
          NamedTuples).
        * ``index``      ← first URL in ``index_urls`` (Phase 3
          single-index simplification; T_M4 will swap to source-name
          lookup).

        Backward-compat: callers that hand us a bare ``.mapping`` dict
        (older test fixtures pre-T_M3 used ``_FakeResult(mapping=...)``
        without criteria) get ``criteria = {}`` and markers fall back
        to the Requires-Python contribution only.  Callers that hand
        us a plain ``dict`` (no ``.mapping`` attribute) are also
        supported — we treat it as the mapping directly.
        """
        # Default index for the lockfile entries — Phase 3 takes the
        # first configured URL.  T_M4 follow-up: map URL→source-name.
        default_index = index_urls[0] if index_urls else None

        # Tolerate both the resolvelib ``Result`` shape (with ``.mapping``
        # and ``.criteria``) and a bare-dict mapping (pre-T_M3 tests).
        mapping = getattr(result, "mapping", result)
        criteria = getattr(result, "criteria", {}) or {}

        locked: list[LockedRequirement] = []
        for identifier, candidate in mapping.items():
            # identifier is (name, frozenset(extras)) per T3.
            try:
                _name, extras_set = identifier
            except (TypeError, ValueError):
                _name = getattr(candidate, "name", str(identifier))
                extras_set = frozenset()

            cand_name = getattr(candidate, "name", _name)
            cand_version = getattr(candidate, "version", None)
            if cand_version is None:
                # Skip non-versioned candidates defensively — resolvelib
                # should never produce one but a malformed test fixture
                # would otherwise crash the LockedRequirement constructor.
                continue

            # Hash translation: Candidate.hashes is frozenset[Hash]
            # where Hash = NamedTuple(algo, value).  The lockfile wire
            # shape is a sorted tuple of "<algo>:<value>" strings —
            # mirrors ``Entry.get_cleaned_dict`` output.
            hashes_iter = []
            for h in getattr(candidate, "hashes", frozenset()) or ():
                algo = getattr(h, "algo", None)
                value = getattr(h, "value", None)
                if algo and value:
                    hashes_iter.append(f"{algo}:{value}")
            hashes_tuple = tuple(sorted(set(hashes_iter)))

            extras_tuple = tuple(sorted(extras_set or frozenset()))

            # T_M3 — marker emission.
            requires_python_marker = _requires_python_to_marker(
                getattr(candidate, "requires_python", None)
            )
            criterion = criteria.get(identifier)
            criterion_information = (
                getattr(criterion, "information", ()) if criterion is not None else ()
            )
            introducing_marker = _introducing_marker_for(criterion_information)
            marker_string = _combine_markers(
                [requires_python_marker, introducing_marker]
            )

            locked.append(
                LockedRequirement(
                    name=cand_name,
                    version=f"=={cand_version}",
                    extras=extras_tuple,
                    markers=marker_string,
                    hashes=hashes_tuple,
                    index=default_index,
                )
            )

        return tuple(locked)


# ---------------------------------------------------------------------------
# T_M3 — marker translation helpers (Initiative G Phase 3b)
# ---------------------------------------------------------------------------


def _requires_python_to_marker(requires_python: str | None) -> str | None:
    """Translate a ``Requires-Python`` specifier-set string into a
    canonical marker string.

    Examples::

        ">=3.10"     → "python_version >= '3.10'"
        ">=3.8,<4"   → "python_version < '4' and python_version >= '3.8'"
        None / ""    → None
        unparseable  → None  (defensive — mirrors T4's behaviour for
                              malformed ``Requires-Python`` strings on
                              index manifests)

    Specs are joined in sorted lexicographic order so the emitted
    marker string is stable across runs (resolvelib doesn't guarantee
    spec-set iteration order — :class:`SpecifierSet` is backed by a
    ``frozenset``).
    """
    if not requires_python:
        return None
    try:
        spec_set = SpecifierSet(requires_python)
    except (InvalidSpecifier, ValueError):
        return None
    parts: list[str] = []
    for spec in spec_set:
        op = spec.operator  # one of '==', '!=', '<=', '>=', '<', '>', '~=', '==='
        ver = spec.version
        parts.append(f"python_version {op} {ver!r}")
    if not parts:
        return None
    # Stable order across runs: ``SpecifierSet`` iterates a frozenset
    # under the hood, so iteration order is unspecified.  Sort here so
    # the lockfile output is byte-identical on every invocation.
    parts.sort()
    return " and ".join(parts)


def _introducing_marker_for(criterion_information: Any) -> str | None:
    """OR-combine ``introducing_marker`` strings from every requirement
    that selected the candidate (T_M2 populates the slot on each
    transitive :class:`Requirement`).

    Rationale for the OR-join (with parentheses on each clause):
    a candidate is admitted to the lockfile because *every* introducing
    requirement was active in the resolver's environment.  At install
    time, the candidate is needed if ANY of those requirements is
    active.  The lockfile's ``markers`` clause therefore encodes the
    union of preconditions — a logical ``or``.  Parentheses preserve
    precedence when a downstream consumer AND-merges this with another
    marker clause (e.g. the Requires-Python contribution combined in
    :meth:`_translate_mapping`).

    Empty / all-None ``information`` → returns ``None`` (no
    contribution).  Single non-None marker → its string verbatim (no
    parens — readability over uniformity, matches what pip emits).
    Duplicates (same marker string from multiple parents) are
    deduplicated, preserving insertion order so the output is
    fixture-stable.
    """
    markers_seen: list[str] = []
    for info in criterion_information or ():
        req = getattr(info, "requirement", None)
        intro = getattr(req, "introducing_marker", None)
        if intro is None:
            continue
        text = str(intro).strip()
        if not text:
            continue
        if text in markers_seen:
            continue
        markers_seen.append(text)
    if not markers_seen:
        return None
    if len(markers_seen) == 1:
        return markers_seen[0]
    return " or ".join(f"({m})" for m in markers_seen)


def _combine_markers(parts: Sequence[str | None]) -> str | None:
    """AND-join non-None marker strings.  Returns ``None`` when every
    contribution is ``None`` / empty.

    Single non-None part → that part verbatim (no surrounding
    parens — keeps the simple ``python_version >= '3.10'`` form for the
    common "Requires-Python only" case).  Multiple parts → joined with
    ``" and "`` in the supplied order (caller controls ordering; the
    translator passes Requires-Python first then introducing markers).
    """
    non_none = [p for p in parts if p]
    if not non_none:
        return None
    if len(non_none) == 1:
        return non_none[0]
    return " and ".join(non_none)


__all__ = ["PurePythonBackend"]
