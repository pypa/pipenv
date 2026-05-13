"""``pure-python`` resolver backend (Initiative G Phase 3, T9).

Implements the Initiative F ``Backend`` protocol over the
:class:`pipenv.resolver.pure_python_provider.PurePythonProvider` (T3-T8)
+ :func:`pipenv.resolver.pure_python_metadata.fetch_metadata` (T2) +
:class:`pipenv.resolver.pure_python_requirement.Requirement` (T1)
chain.

Flow inside :meth:`PurePythonBackend.resolve`:

1. **Pre-fetch** top-level package candidates via
   :meth:`ParallelFetcher.populate` (Q-B).
2. **Top-level emptiness pre-check** (Phase 3b T_S4): scan cached
   candidates for each top-level package; abort with a structured
   :class:`ResolutionError` if any top-level has ZERO candidates
   across every configured index.  Catches typos, yanked-only
   releases, and cold-cache + total-fetch-failure cases at startup
   instead of 30 s into a doomed resolve.  Phase 3a's older
   wheel-availability variant of this gate (which fired on
   sdist-only top-levels) is gone — T_S2/T_S3 build sdists
   transparently so sdist-only top-levels resolve normally.
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

        # T_M4 (Initiative G Phase 3b): URL→name map for the lockfile
        # ``index`` field.  Pip writes ``index=<source-name>`` (e.g.
        # ``"pypi"``) per the Pipfile ``[[source]]`` block, NOT the raw
        # URL.  We build the map here so the translator can look up the
        # source name for each resolved candidate.  Empty when
        # ``request.sources`` is empty (no mapping possible — the
        # translator falls back to emitting the URL verbatim).
        url_to_name: dict[str, str] = {
            s.url: s.name for s in request.sources
        }

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
            # but continue — let ``find_matches`` retry on miss.  The
            # top-level emptiness pre-check below catches the case
            # where pre-fetch *and* every lazy retry leave the cache
            # empty for some top-level (typo / yanked-only / total
            # network blackout); resolvelib's own error path covers
            # the "candidates exist but none satisfy" case.
            pass

        # ---- Step 2: top-level emptiness pre-check (T_S4) --------------
        # For each top-level package, scan cached candidates across
        # configured indexes.  If a top-level has ZERO candidates on
        # *every* configured index → fail loud BEFORE driving
        # resolvelib.  This catches typos, yanked-only releases, and
        # cold-cache + every-fetch-failed cases with a clear message
        # instead of letting resolvelib raise its own opaque
        # "no candidates available" error 30 s later.
        #
        # NB Phase 3a fired this gate on sdist-only top-levels too;
        # T_S2 (sdists build via PEP 517) and T_S3 (no fail-loud on
        # sdist encounter) made that branch obsolete and it was
        # removed in T_S4 — sdist-only top-levels now resolve
        # normally.
        empty_top_level: list[str] = []
        for name in top_level_names:
            saw_any = False
            for idx in request_index_urls:
                manifest = self._cache.get(idx, name)
                if manifest is None:
                    continue
                if any(True for _ in getattr(manifest, "candidates", ())):
                    saw_any = True
                    break
            if not saw_any:
                empty_top_level.append(name)

        if empty_top_level:
            names = sorted(empty_top_level)
            index_plural = "es" if len(request_index_urls) > 1 else ""
            pip_message = (
                f"Pure-python backend cannot resolve {names!r}: no candidates "
                f"found in the configured index{index_plural}.  "
                f"Check the package name (typo?), confirm releases on the index, "
                f"or retry with `pipenv lock --backend pip` if the package is "
                f"available through pip's resolver but not the simple-API."
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
        # T_M4 (Initiative G Phase 3b): thread the URL→name map so the
        # translator can emit the source NAME for the ``index`` field
        # instead of the URL (pip-parity).
        locked = self._translate_mapping(
            result, request_index_urls, url_to_name
        )
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

        The wire format is a full pip argument string like
        ``"requests==2.31.0"``, ``"urllib3[brotli]>=2 -i https://…"``,
        ``"psycopg[binary]"``, or just the package name (``"requests"``
        ⇒ "any version").  Pip flags (``-i``, ``--index-url``,
        ``--trusted-host``, etc.) appear after a whitespace separator;
        the backend handles index URLs via
        ``request.options.indexes``, so we drop everything past the
        first whitespace token before extracting the specifier.

        Return shape: a plain specifier string when the wire-shape
        carries no extras (preserves backwards compatibility with the
        existing test contract), or a dict with ``version`` + ``extras``
        keys when ``name[extra1,extra2]`` is present.  The Pipfile
        parser at :meth:`Requirement.from_pipfile_entry` accepts both
        shapes — dict-form is how it normally consumes
        ``pkg = { version = "*", extras = [...] }`` from a TOML file.

        T_PARITY_REAL bench trigger (project 01 — ``psycopg[binary]``):
        before this fix, the wire-shape ``"psycopg[binary]"`` returned
        ``"*"`` outright (the bracketed extras section contains no
        specifier-marker character, so the loop fell through), which
        silently dropped the extras from the resulting
        :class:`Requirement` and made the resolvelib identifier
        ``("psycopg", frozenset())`` rather than
        ``("psycopg", frozenset({"binary"}))``.  Without the right
        identifier, T7's :meth:`get_dependencies` evaluated
        ``Requires-Dist`` markers under ``extra=""`` and the
        ``psycopg-binary; extra == "binary"`` transitive disappeared.
        """
        line = (spec_value or "").strip()
        if not line:
            return "*"
        # First whitespace-separated token is the
        # ``name[extras]<specifier>`` part; everything after is pip
        # CLI flags which the backend doesn't consume here.
        first_token = line.split(None, 1)[0]
        # Strip ``[extras]`` from the name segment (if present) BEFORE
        # scanning for specifier markers; otherwise the inner bracket
        # contents (e.g. ``security,brotli``) can confuse the scan and
        # we'd lose the extras anyway.
        extras: list[str] = []
        bracket_open = first_token.find("[")
        if bracket_open != -1:
            bracket_close = first_token.find("]", bracket_open + 1)
            if bracket_close != -1:
                extras = [
                    e.strip()
                    for e in first_token[bracket_open + 1 : bracket_close].split(",")
                    if e.strip()
                ]
                # Rejoin around the bracket span so the specifier scan
                # below works on a flat ``name<specifier>`` shape.
                first_token = (
                    first_token[:bracket_open] + first_token[bracket_close + 1 :]
                )
        specifier = "*"
        for marker_char in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            idx = first_token.find(marker_char)
            if idx != -1:
                specifier = first_token[idx:]
                break
        if extras:
            return {"version": specifier, "extras": extras}
        return specifier

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
        internals.
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
        url_to_name: dict[str, str] | None = None,
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
        * ``hashes``     ← ``tuple(sorted("<algo>:<value>"))`` unioned
          from every cache sibling whose ``version`` matches the
          resolved candidate's, across every configured index URL
          (T_S5 — pip-parity: lockfile lists hashes for ALL distfiles
          of the resolved version, not just the chosen candidate).
          Falls back to ``candidate.hashes`` alone when the cache has
          no siblings (cold-cache / test-fixture-injected workflows).
        * ``index``      ← source NAME (e.g. ``"pypi"``) when
          ``default_index`` (the first URL in ``index_urls``) appears
          in ``url_to_name``; otherwise the URL is emitted verbatim as
          a defensive fallback (Phase 3b simplification — Phase 4 will
          track which configured source actually served each candidate
          via per-Candidate provenance).

        Backward-compat: callers that hand us a bare ``.mapping`` dict
        (older test fixtures pre-T_M3 used ``_FakeResult(mapping=...)``
        without criteria) get ``criteria = {}`` and markers fall back
        to the Requires-Python contribution only.  Callers that hand
        us a plain ``dict`` (no ``.mapping`` attribute) are also
        supported — we treat it as the mapping directly.  Callers that
        omit ``url_to_name`` get an empty map ⇒ all candidates fall
        through to the URL-verbatim fallback (back-compat for legacy
        fixtures from before T_M4 introduced the third parameter).
        """
        # Default index for the lockfile entries — Phase 3 takes the
        # first configured URL.
        default_index = index_urls[0] if index_urls else None
        # T_M4: empty mapping when callers omit ``url_to_name`` (older
        # test fixtures and the pre-T_M4 signature).  An empty map ⇒
        # ``dict.get`` always falls back to the URL verbatim, preserving
        # the pre-T_M4 behaviour for those callers.
        url_to_name = url_to_name or {}

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

            # Hash translation (T_S5 — Initiative G Phase 3b):
            # mirror pip's lockfile convention by emitting hashes for
            # EVERY distfile of the resolved version (wheel + sdist +
            # any cross-platform wheel variants), not just the chosen
            # candidate's single hash.  Walk every configured index and
            # union the ``hashes`` frozensets of cache siblings whose
            # ``version`` matches the resolved one.
            #
            # Dedup is set-driven: identical ``(algo, value)`` pairs
            # served by multiple indexes collapse to one entry.
            #
            # Fallback (defensive): when no sibling-candidate scan
            # turned up anything (cold cache / a test fixture that
            # injects candidates straight into the result without
            # populating the cache), fall back to the resolved
            # candidate's own ``hashes``.  Preserves Phase 3a
            # fixture-injected-only workflows.
            hashes_iter: set[str] = set()
            for idx in index_urls:
                manifest = self._cache.get(idx, cand_name)
                if manifest is None:
                    continue
                for sibling in getattr(manifest, "candidates", ()) or ():
                    if getattr(sibling, "version", None) != cand_version:
                        continue
                    for h in getattr(sibling, "hashes", frozenset()) or ():
                        algo = getattr(h, "algo", None)
                        value = getattr(h, "value", None)
                        if algo and value:
                            hashes_iter.add(f"{algo}:{value}")
            if not hashes_iter:
                for h in getattr(candidate, "hashes", frozenset()) or ():
                    algo = getattr(h, "algo", None)
                    value = getattr(h, "value", None)
                    if algo and value:
                        hashes_iter.add(f"{algo}:{value}")
            hashes_tuple = tuple(sorted(hashes_iter))

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

            # T_M4: emit source NAME when the URL maps to a configured
            # source; fall back to the URL verbatim if no source matches
            # (defensive — the Phase 3 Candidate doesn't track WHICH
            # configured source served it, so this lookup is approximate.
            # Phase 4 will track per-candidate index provenance for
            # exact attribution across multi-source resolutions).
            index_value = (
                url_to_name.get(default_index, default_index)
                if default_index is not None
                else None
            )

            locked.append(
                LockedRequirement(
                    name=cand_name,
                    version=f"=={cand_version}",
                    extras=extras_tuple,
                    markers=marker_string,
                    hashes=hashes_tuple,
                    index=index_value,
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
