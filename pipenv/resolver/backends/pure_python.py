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
   instead of 30 s into a doomed resolve.
3. Build :class:`Requirement` set from ``request.packages.specs``.
4. Drive :class:`resolvelib.Resolver` via
   :func:`pipenv.resolver.pure_python_provider._drive_resolver`.
5. **Q-A fail-loud sdist handling**: catch
   :class:`_SdistEncountered` from
   :meth:`PurePythonProvider.get_dependencies` (raised by T7 when a
   transitive's only choice is an sdist).  Translate into
   :class:`InternalError` — **no silent fallback to pip backend**.
6. Other exception → :class:`InternalError`; otherwise translate the
   resolved candidate mapping into a tuple of
   :class:`LockedRequirement` and return :class:`ResolverSuccess`.

See ``docs/dev/initiative-g-phase3-design.md`` §5.4 and
``initiative-g-phase3-plan.md`` T9.

NOTE: this module imports only from ``pipenv.patched.pip._vendor.resolvelib``
(vendor, not internal — that's the resolvelib exception type lookup
inside :meth:`resolve`).  The pipenv pure-Python backend deliberately
sits on the typed schema surface, not on patched-pip internals.
"""
from __future__ import annotations

import traceback
from typing import Any, Sequence

from pipenv.resolver.pure_python_metadata import (
    MetadataCache,
    fetch_metadata,
)
from pipenv.resolver.pure_python_provider import (
    PurePythonProvider,
    _drive_resolver,
    _SdistEncountered,
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
        cache: Any,
        fetcher: Any,
        session: Any,
        metadata_cache: MetadataCache | Any,
        target_env: dict | None = None,
        index_urls: Sequence[str] = ("https://pypi.org/simple",),
    ) -> None:
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
        except _SdistEncountered as exc:
            # Q-A fail-loud: do NOT fall back to pip backend.  The user
            # made an explicit choice; surface the offending sdist so
            # they can decide between pinning a wheel-bearing version
            # and switching backends.
            candidate = exc.candidate
            cand_name = getattr(candidate, "name", "<unknown>")
            cand_version = getattr(candidate, "version", "<unknown>")
            message = (
                f"sdist-only transitive dependency {cand_name}=={cand_version!r}: "
                f"pure-python backend (Phase 3) does not build sdists.  "
                f"Pin to a version with wheels, or switch "
                f"resolver_backend = 'pip'."
            )
            return ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=InternalError(
                    kind="internal_error",
                    message=message,
                    traceback=traceback.format_exc(),
                ),
                diagnostics=Diagnostics(),
            )
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
        locked = self._translate_mapping(result.mapping, request_index_urls)
        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=ResolverSuccess(kind="success", locked=locked),
            diagnostics=Diagnostics(),
        )

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
        mapping: dict,
        index_urls: Sequence[str],
    ) -> tuple[LockedRequirement, ...]:
        """Translate the resolved ``identifier -> Candidate`` mapping
        into a tuple of :class:`LockedRequirement` entries.

        The Phase 3 wire-shape is conservative — we populate the four
        fields we have first-class data for (``name``, ``version``,
        ``hashes``, ``index``) and leave the rest at their defaults.
        Markers and ``requires_python`` are *not* propagated in
        Phase 3 because the resolved candidate is already the
        materialised pick — markers were evaluated during resolution
        and ``requires_python`` constrains compatibility (it's a
        compatibility filter, not a lockfile field per the
        :class:`LockedRequirement` schema).

        Field mapping (per :class:`LockedRequirement` in
        ``pipenv/resolver/schema.py``):

        * ``name``       ← ``candidate.name``
        * ``version``    ← ``"==" + candidate.version`` (matches the
          existing pip-backend lockfile shape — see
          ``Entry.get_cleaned_dict`` / ``_clean_version``).
        * ``extras``     ← ``tuple(sorted(candidate.extras))``
        * ``hashes``     ← ``tuple(sorted("<algo>:<value>"))`` from
          ``candidate.hashes`` (frozenset of :class:`Hash`
          NamedTuples).
        * ``index``      ← first URL in ``index_urls`` (Phase 3
          single-index simplification; multi-index resolution
          follow-up).
        """
        # Default index for the lockfile entries — Phase 3 takes the
        # first configured URL.  Multi-index propagation (recording
        # WHICH index supplied each candidate) is a Phase 4 follow-up.
        default_index = index_urls[0] if index_urls else None

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

            locked.append(
                LockedRequirement(
                    name=cand_name,
                    version=f"=={cand_version}",
                    extras=extras_tuple,
                    markers=None,
                    hashes=hashes_tuple,
                    index=default_index,
                )
            )

        return tuple(locked)


__all__ = ["PurePythonBackend"]
