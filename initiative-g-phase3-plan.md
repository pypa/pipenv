# Plan: Initiative G — Phase 3 (Pure-Python `resolvelib.Provider` Backend)

**Generated**: 2026-05-12
**Source design doc**: [`docs/dev/initiative-g-phase3-design.md`](docs/dev/initiative-g-phase3-design.md)
**Branch**: `maintenance/code-cleanup-phase6-pure-python-resolver-2026-07` (off
`maintenance/code-cleanup-phase5-perf-2026-06` at commit `3d16ca04`).
**Scope**: Phase 3 only.  Phase 4 (promote to default + remove pip
backend) is a separate sign-off after Phase 3 ships and a release
cycle of opt-in user data lands.

---

## Overview

Phase 3 implements the in-tree `pure-python` resolver backend that
replaces pip's `PackageFinder` + `LinkEvaluator` + `InstallRequirement`
machinery with our own `Requirement` + `MetadataFetcher` +
`PurePythonProvider` chain over `resolvelib.AbstractProvider`.

The Phases 1 + 2 infrastructure already shipped (`PEP691Client`,
`ParsedManifestCache`, `ParallelFetcher`, `Candidate`, `Hash`, etc.) —
this plan picks them up unchanged.

### Acceptance criteria (from design doc §8)

**Phase 3:**
- Zero `pip._internal.*` imports in `pipenv/resolver/pure_python_*.py`
  and `pipenv/resolver/backends/pure_python.py` (enforced by Phase 1's
  pre-commit grep gate).
- Lockfile byte-identity vs pip backend on:
  - The 100-package bench fixture.
  - The 10-real-PyPI-project list defined in T_PARITY_REAL below.
  - pip versions N-1, N, N+1.
- Parity matrix doc shipped with every divergence justified.
- CI `lock-warm` ≤ 14.5 s on the 100-pkg bench (≥ 30 % off the
  pre-phase-5 baseline of 21.3 s).
- News fragment + user-facing docs for `[pipenv] resolver_backend =
  "pure-python"`.

### Decisions baked into this plan (sign-off 2026-05-12)

The design doc §7 catalogues six decisions (Q-A through Q-F).  All are
now answered; this plan reflects them load-bearingly.

- **Q-A** sdist handling → **fail loud** (transparent fallback was
  considered and rejected; behaviour must be auditable).
- **Q-B** PEP 658 pre-fetch → **top-level packages only**, transitives
  lazy.
- **Q-C** `get_preference` parity → **strict mirror with
  byte-identity gate**.
- **Q-D** keyring auth → **not in Phase 3** (netrc + URL-auth +
  `PIP_CLIENT_CERT` only).
- **Q-E** parity-real list → **10 wheel-heavy projects** (django +
  psycopg[binary], flask + gunicorn, fastapi + uvicorn, requests +
  httpx, pandas + numpy, pytest + pytest-cov, sqlalchemy + alembic,
  cryptography + pyopenssl, boto3 + botocore, click + rich).
- **Q-F** sdist UX → **backend-startup pre-check** on top-level
  packages with a clear error message; transitive sdists still fail
  loud per Q-A but rarer.

---

## Prerequisites

- Branch `maintenance/code-cleanup-phase6-pure-python-resolver-2026-07`
  exists and is checked out.
- Initiative F backend registry is at `pipenv/resolver/backends/` with
  `base.py` + `pip.py` + `__init__.py`.
- Phase 1 + 2 modules at `pipenv/resolver/` (candidate, pep691,
  pep691_types, manifest_cache, fetcher, auth) are unchanged.
- Vendored `pipenv.vendor.packaging` provides `Version`, `SpecifierSet`,
  `Marker`, `Requirement` (as a parser, not the type we'll use for
  graph nodes), `Tag`, `parse_wheel_filename`.
- Vendored `pipenv.patched.pip._vendor.resolvelib` provides
  `AbstractProvider`, `Resolver`, `ResolutionImpossible`.

---

## Dependency Graph (high-level)

```
        T1 ─┬──────────────────────────────┐
            │                              │
        T2 ─┤                              │
            │                              │
            T3 ── T4 ── T5 ── T6 ── T7 ── T8
                                          │
                                          T9 ── T10 ── T11 ── T12 ── T13
                                                                      │
                                                                     T14
```

The canonical wave breakdown is in **§ Parallel Execution Groups**
near the bottom of this document.

---

## Tasks

### T1: `Requirement` dataclass

- **depends_on**: `[]`
- **location**: `pipenv/resolver/pure_python_requirement.py` (new)
- **description**:
  Frozen `@dataclass(frozen=True, slots=True)` per design §5.1.
  Fields: `name` (PEP 503 canonical), `specifier` (`SpecifierSet`),
  `extras` (`frozenset[str]`), `marker` (`Marker | None`), `source`
  (Literal `"pipfile" | "transitive" | "constraint"`), `parent` (`str |
  None`).  Use `pipenv.vendor.packaging.specifiers.SpecifierSet` and
  `pipenv.vendor.packaging.markers.Marker`.  Add a
  `Requirement.from_pipfile_entry(name, value)` helper that handles
  the common Pipfile shapes (string version, dict with `version`/`extras`/`markers`,
  `*` for any-version).
- **validation**:
  - Round-trip: build a `Requirement` with all fields set; verify each
    attribute; verify equality + hashability (frozenset membership).
  - `from_pipfile_entry("django", "*")` → spec is empty SpecifierSet.
  - `from_pipfile_entry("django", ">=4.0,<6")` → spec parses.
  - `from_pipfile_entry("django", {"version": ">=4.0", "extras": ["argon2"]})`
    → extras populated.
  - Zero `pip._internal.*` imports.
- **status**: Completed
- **log**:
  - 2026-05-12 — Implemented per design §5.1.  Frozen
    `@dataclass(frozen=True, slots=True)` with the six fields
    enumerated in the brief (`name`, `specifier`, `extras`, `marker`,
    `source`, `parent`).  Hashability comes for free from
    `frozen=True` — both `SpecifierSet`
    (`pipenv/vendor/packaging/specifiers.py:842`) and `Marker`
    (`pipenv/vendor/packaging/markers.py:329`) are hashable in the
    vendored `packaging`, so no `__hash__` override is needed.  The
    `from_pipfile_entry` classmethod handles the four canonical
    Pipfile shapes from the design brief: bare string version,
    `"*"`, dict with `version`/`extras`/`markers`, and dict with
    `"version": "*"`.  Names are canonicalised via
    `pipenv.vendor.packaging.utils.canonicalize_name` (PEP 503).
    Unknown value types (neither str nor dict) raise `TypeError` so a
    malformed Pipfile entry surfaces loudly rather than producing a
    half-populated constraint.  RED→GREEN with
    `tests/unit/test_pure_python_requirement.py` (15 tests; all
    pass).  T11 will extend that file with the broader coverage
    matrix (negative paths, edge cases).
    `grep -n "pip\._internal" pipenv/resolver/pure_python_requirement.py`
    shows zero matches; `ruff check` clean.
- **files edited/created**:
  - `pipenv/resolver/pure_python_requirement.py` (replaced stub with
    full implementation — `Requirement` dataclass + `from_pipfile_entry`
    classmethod)
  - `tests/unit/test_pure_python_requirement.py` (new; 15 tests
    covering the four T1 acceptance criteria — round-trip /
    equality / hashability / `from_pipfile_entry` shapes — plus the
    `transitive` + `constraint` source-label and parent-propagation
    cases T3/T7 rely on; T11 extends this file)

---

### T2: `MetadataFetcher` — PEP 658 fast path + wheel-head fallback

- **depends_on**: `[]`
- **location**: `pipenv/resolver/pure_python_metadata.py` (new)
- **description**:
  Per design §5.2:
  - `fetch_metadata(candidate: Candidate, session: PipSession) -> CoreMetadata`.
  - **PEP 658 fast path**: when `candidate.metadata_url` is set (Phase
    1's `Candidate` already has `metadata_file_data`; widen if needed
    per Q-B implementation), GET `<wheel_url>.metadata`, verify the
    advertised hash, parse via stdlib `email.parser.HeaderParser`
    using `email.policy.compat32`.
  - **Wheel-head fallback**: HTTP `HEAD` to get `Content-Length`,
    then GET with `Range: bytes=-65536` (last 64 kB) to capture the
    zip central directory.  Parse the directory entries via
    `zipfile.ZipFile(io.BytesIO(...))` — Python's stdlib zipfile
    handles partial reads if the central directory is intact.  Locate
    the `<dist-info>/METADATA` entry, fetch a second range covering
    just that entry, parse.
  - **MetadataCache** on disk at `<PIPENV_CACHE_DIR>/pipenv-manifests/metadata-v1/`
    keyed by `sha256(wheel_url)`.  Cache entries are valid forever
    (wheels are immutable).  Atomic write same as `ParsedManifestCache`.
  - `CoreMetadata` dataclass: `name`, `version`, `requires_python`,
    `requires_dist` (list of strings), `provides_extras` (frozenset),
    `summary` (for diagnostics).
- **validation**:
  - PEP 658 fast path: against a real PyPI wheel that advertises
    `core-metadata` (e.g., `numpy-1.26.0-*.whl`), fetch metadata and
    assert `requires_dist` matches the known `Requires-Dist` headers.
  - Wheel-head fallback: against a synthetic test wheel (built with
    `tmp_path` + `zipfile`), fetch metadata via the range path and
    assert it matches.
  - Cache round-trip: `fetch_metadata` populates the cache; second call
    on the same wheel returns from cache without network.
  - Zero `pip._internal.*` imports.
- **status**: Completed
- **log**:
  - 2026-05-12 — Implemented per design §5.2.  RED→GREEN with
    `tests/unit/test_pure_python_metadata.py` (9 tests; all pass).
    PEP 658 fast path verifies advertised `sha256` against
    `hashlib.sha256(body).hexdigest()`; mismatch raises
    `MetadataFetchError`.  Wheel-head fallback uses an `io.RawIOBase`
    shim (`_PartialFile`) that lets `zipfile.ZipFile` see a
    seekable view over the wheel while transparently re-issuing
    HTTP range GETs for bytes outside the in-memory window — this
    handles both the central-directory walk and the subsequent
    `METADATA` extraction without buffering the whole wheel.  HEAD
    rejection (405/403) falls back to a probing `GET Range: bytes=0-1`
    that reads the total length from `Content-Range`.  Cache is keyed
    by `sha256(wheel_url)` and uses the same tempfile + `os.replace`
    atomic-write contract as `ParsedManifestCache`.  Since Phase 1's
    `Candidate` does not yet carry PEP 658 advertisement,
    `fetch_metadata` accepts optional `metadata_url` + `metadata_hash`
    keyword arguments — T3 / T7 can widen `Candidate` later and pass
    the values through without API churn.  `grep -nE
    "^[[:space:]]*(from|import)[[:space:]]+pipenv\.patched\.pip\._internal"
    pipenv/resolver/pure_python_metadata.py` shows zero matches.
    `ruff check` clean.
- **files edited/created**:
  - `pipenv/resolver/pure_python_metadata.py` (replaced stub with
    full implementation — `CoreMetadata`, `MetadataFetchError`,
    `MetadataCache`, `fetch_metadata`, `_parse_metadata_text`,
    `_PartialFile`)
  - `tests/unit/test_pure_python_metadata.py` (new; 9 tests covering
    the four T2 acceptance criteria + helper coverage; T12 will
    extend this file)

---

### T3: `PurePythonProvider.identify`

- **depends_on**: `[T1]`
- **location**: `pipenv/resolver/pure_python_provider.py` (new — start
  the file with just `identify`; subsequent tasks fill it in)
- **description**:
  Per design §5.3.  Class shell:
  ```python
  class PurePythonProvider(AbstractProvider):
      def __init__(self, *, cache, fetcher, metadata_fetcher, target_env): ...

      def identify(self, req_or_cand) -> tuple[str, frozenset[str]]:
          """Group key: (canonical_name, frozenset(extras))."""
          ...
  ```
  Accept both `Requirement` and `Candidate` instances; extract
  `name` + `extras` consistently.  `Candidate.extras` doesn't exist
  yet (Phase 1 didn't need it) — add it as part of T3 if missing.
- **validation**:
  - `identify(Requirement(name="Django", extras=frozenset({"argon2"}), ...))`
    returns `("django", frozenset({"argon2"}))`.
  - `identify(Candidate(name="django", ...))` returns
    `("django", frozenset())`.
  - Round-trip equality: two requirements with same name + extras
    have equal `identify` outputs.
- **status**: Completed
- **log**:
  - 2026-05-12 — Implemented per design §5.3.  Started
    `pipenv/resolver/pure_python_provider.py` with the
    `PurePythonProvider(AbstractProvider)` shell: keyword-only
    `__init__(*, cache, fetcher, metadata_fetcher, target_env)` stores
    all four collaborators verbatim (typed `Any` for now — T4-T7 will
    tighten as they consume each one), and `identify` returns the
    `(canonical_name, frozenset(extras))` group key from design §5.3.
    The `identify` body branches on `isinstance(_, Requirement)` for
    static-checker narrowing on the `Requirement` path, and uses
    duck-typing (`getattr(_, "extras", frozenset())`) on the
    `Candidate` path so this module doesn't import
    `pipenv.resolver.candidate` (smaller import graph; dodges any
    future circular if T9's backend hands the provider a `Candidate`
    subclass).  `AbstractProvider` in
    `pipenv/patched/pip/_vendor/resolvelib/providers.py` raises plain
    `NotImplementedError` (no `@abstractmethod`), so the four
    un-implemented hot-path methods (`find_matches`, `get_preference`,
    `is_satisfied_by`, `get_dependencies`) carry stubs that raise
    `NotImplementedError("T4: ...")` etc. — instantiation works,
    invocation fails loud with a task-label pointer.
    `Candidate` was widened with a new `extras: frozenset[str] = field(
    default_factory=frozenset)` field (appended after the existing
    fields so frozen-dataclass field-order — no-default-then-default
    — holds).  The default factory means the existing PEP 691 parser
    in `pipenv/resolver/manifest_cache.py:407` and all 31
    `test_candidate.py` tests stay non-breaking (verified: 31/31
    pass).  RED→GREEN with `tests/unit/test_pure_python_provider.py`
    (8 tests; all pass) covering the three T3 validation bullets plus
    the symmetrical cross-shape claim that a `Requirement` and a
    `Candidate` with matching `(name, extras)` produce equal
    identifiers (the load-bearing `resolvelib` invariant).  T13 will
    extend this file with per-method coverage of `find_matches`,
    `get_preference`, `is_satisfied_by`, and `get_dependencies` once
    T4-T7 land.  `grep -nE
    "^[[:space:]]*(from|import)[[:space:]]+pipenv\.patched\.pip\._internal"
    pipenv/resolver/pure_python_provider.py` shows zero matches —
    the `AbstractProvider` import goes through
    `pipenv.patched.pip._vendor.resolvelib`, which is `_vendor` (a
    third-party-vendored dep of patched pip), not `_internal` (pip's
    own code).  `ruff check` clean on the new files.
- **files edited/created**:
  - `pipenv/resolver/pure_python_provider.py` (new — class shell:
    keyword-only `__init__` storing the four collaborators + `identify`
    returning `(canonical_name, frozenset(extras))`; `find_matches`,
    `get_preference`, `is_satisfied_by`, `get_dependencies` are stubs
    raising `NotImplementedError("Tn: ...")` for T4-T7 to fill in)
  - `pipenv/resolver/candidate.py` (widened: added
    `extras: frozenset[str] = field(default_factory=frozenset)` and
    a field docstring explaining T3's use; imported `field` from
    `dataclasses`)
  - `tests/unit/test_pure_python_provider.py` (new — 8 RED→GREEN
    tests covering the three T3 validation bullets: identifier shape
    for `Requirement` with/without extras + multi-extra, identifier
    shape for `Candidate` with default + explicit-empty extras, and
    round-trip equality across same/different extras + cross-shape
    `Requirement` ↔ `Candidate`; T13 extends)

---

### T4: `PurePythonProvider.find_matches`

- **depends_on**: `[T1, T3]`
- **location**: `pipenv/resolver/pure_python_provider.py` (extend)
- **description**:
  Per design §5.3.  Hot path:
  1. Read candidates from `self._cache.get(index_url, name)` (warmed
     by `ParallelFetcher` pre-resolve).  Cache miss → call
     `self._fetcher.populate([(index_url, name)])` for that one
     package — single round-trip.
  2. Filter candidates: every `requirement.specifier.contains(version)`
     must hold; none of the `incompatibilities` candidates match;
     `target_env` marker evaluates True for the candidate's
     `requires_python`.
  3. Return iterator ordered high-version-first using
     `pipenv.vendor.packaging.version.Version`.
- **validation**:
  - Mock cache returns a list of 5 `Candidate`s for `django`;
    `find_matches` with `specifier=">=4.0"` returns only those with
    version ≥ 4.0, highest first.
  - Mock cache returns 0 candidates; `find_matches` returns empty
    iterator without raising.
  - `incompatibilities` filter: pass one of the returned candidates
    as incompatible; it's excluded from the output.
- **status**: Completed
- **log**:
  - 2026-05-12 — Implemented per design §5.3.  Hot path lives in
    :meth:`PurePythonProvider.find_matches` and three private
    helpers (`_collect_cached_candidates`,
    `_candidate_satisfies_requirements`,
    `_candidate_requires_python_ok`).  Algorithm walks every
    configured ``index_url`` (new ``__init__`` kwarg; see below),
    concatenates non-``None`` `cache.get(index_url, name)` hits,
    dispatches a single `fetcher.populate([(idx, name) for idx in
    index_urls])` on full miss, deduplicates on
    ``(name, version, filename)``, filters against the merged
    specifier intersection of every `Requirement` in
    `requirements[identifier]`, drops candidates whose identity
    tuple is in `incompatibilities[identifier]`, applies the
    candidate's own `requires_python` SpecifierSet against
    `target_env["python_version"]` (with `prereleases=True` so an
    alpha CPython target doesn't get silently dropped — mirrors
    pip's `evaluate_link`), and sorts by
    `pipenv.vendor.packaging.version.Version` descending.  Sdist
    vs wheel filtering is deliberately NOT done here per Q-A — T7
    raises `_SdistEncountered` when actually expanding deps, and
    Q-F's top-level pre-check lives in T9's backend, not on the
    provider hot path.
  - `__init__` widened with two keyword-only fields: `index_urls:
    Sequence[str] = ("https://pypi.org/simple",)` stored as a
    tuple (frozen-by-convention), and `allow_prereleases: bool =
    False` for the explicit `--pre` opt-in.  Defaults preserve
    T3's existing call sites — T3's 8 tests construct the provider
    without these kwargs and still pass.  The test helper
    `_make_provider` was extended in lockstep so both T3 and T4
    cases share the same builder.
  - Loud-failure stance on `InvalidVersion`: a candidate whose
    `version` string can't be parsed by
    `packaging.version.Version` is filtered out rather than
    sorting last.  Rationale: the PEP 691 parser in
    `pipenv/resolver/manifest_cache.py` should have rejected it
    before reaching the cache; if it slipped through, silently
    sorting it last would mask the upstream bug.  Same stance
    isn't applied to `InvalidSpecifier` on a candidate's
    `requires_python` (we accept the candidate on malformed
    `requires-python` advertisement) — that mirrors pip's
    behaviour where a bad index payload doesn't make the package
    invisible.
  - Cache-key note for T5/T6 follow-ups: `ParsedManifestCache` is
    keyed on `(index_url, name)`; the provider doesn't know which
    index served a given cached candidate.  T4's walk-every-index
    approach is correct but does N cache reads per `find_matches`
    call where N = len(index_urls).  If this becomes a hot-path
    bottleneck under a >5-index workload, the fix is to widen
    `Candidate` with an `index_url` field rather than threading
    it through here — not a refactor for T5/T6.
  - RED→GREEN: 4 new tests landed in
    `tests/unit/test_pure_python_provider.py`
    (`TestFindMatchesSpecifierFilter`,
    `TestFindMatchesEmpty`,
    `TestFindMatchesIncompatibilitiesFilter`,
    `TestFindMatchesRequiresPythonFilter`) — one per validation
    bullet plus the bonus `requires_python` filter.  Each uses
    a `_FakeCache` + `_FakeFetcher` pair (in-file stand-ins for
    `ParsedManifestCache` + `ParallelFetcher`) — no real network,
    no real disk.  Full file now 12 tests; all pass.  `grep -nE
    "^[[:space:]]*(from|import)[[:space:]]+pipenv\.patched\.pip\._internal"
    pipenv/resolver/pure_python_provider.py` shows zero matches.
    `ruff check` clean.
- **files edited/created**:
  - `pipenv/resolver/pure_python_provider.py` (extended:
    `find_matches` + three private helpers; `__init__` widened
    with `index_urls` + `allow_prereleases` keyword-only kwargs;
    new imports for `Iterable`, `Mapping`, `Sequence`,
    `InvalidSpecifier`, `SpecifierSet`, `InvalidVersion`,
    `Version`)
  - `tests/unit/test_pure_python_provider.py` (extended: 4 new
    tests for T4 + supporting `_FakeCache` / `_FakeFetcher` /
    `_cand` helpers; `_make_provider` now forwards the new
    `index_urls` + `allow_prereleases` kwargs with defaults so
    T3 tests stay unchanged)

---

### T5: `PurePythonProvider.get_preference`

- **depends_on**: `[T1, T3]`
- **location**: `pipenv/resolver/pure_python_provider.py` (extend)
- **description**:
  Per design §5.3 + Q-C (strict mirror).  Read pip's
  `pipenv/patched/pip/_internal/resolution/resolvelib/provider.py:176
  (get_preference)` end-to-end, mirror the tuple shape.  Expected
  components in order (lower = preferred):
  - `0 if pinned else 1`: pinned-version requirements first.
  - `0 if source == "pipfile" else 1`: Pipfile-direct over transitive.
  - `count(backtrack_causes for identifier)`: backtrack-causing
    identifiers later.
  - Lexicographic tie-breaker on identifier name (stable order).
- **validation**:
  - Pin vs range: pinned requirement returns a preference tuple that
    sorts before a range requirement.
  - Pipfile vs transitive: Pipfile-direct sorts before transitive.
  - Backtrack: an identifier appearing in `backtrack_causes` 3 times
    sorts after one appearing 0 times.
- **status**: Completed
- **log**:
  - Read pip's `PipProvider.get_preference` in
    `pipenv/patched/pip/_internal/resolution/resolvelib/provider.py`
    end-to-end.  pip's tuple is a 7-tuple at the time of this commit:
    `(not conflict_promoted, not direct, not pinned, not upper_bounded,
    requested_order, not unfree, identifier)`.  Three of the seven
    components depend on pip-internal state we don't carry in Phase 3
    — see parity-divergence candidates below.
  - Confirmed `resolvelib.AbstractProvider.get_preference` signature
    from `pipenv/patched/pip/_vendor/resolvelib/providers.py:33-90` and
    the `RequirementInformation = namedtuple(..., ["requirement",
    "parent"])` shape from
    `pipenv/patched/pip/_vendor/resolvelib/structs.py:27-40`.
  - Tuple shape this commit returns (low = preferred):
    `(backtrack_count, not is_pipfile, not is_pinned, not is_upper_bounded,
    not is_unfree, identifier_key)` where `identifier_key = (name,
    tuple(sorted(extras)))` for deterministic tie-breaking.  Mirrors
    the four leading axes the plan T5 validation matrix calls out
    plus the `upper_bounded` and `unfree` slots that fall out of the
    same operator scan (free win — same operator pass).
  - RED→GREEN evidence: 6 new tests landed in
    `tests/unit/test_pure_python_provider.py` covering pinned-vs-range,
    `==4.*` not-pinned, Pipfile-vs-transitive, backtrack-count,
    lexicographic tie-break, and the empty-information defensive path.
    Initial run with the stub: `NotImplementedError("T5:
    PurePythonProvider.get_preference")` on first test.  Post-impl:
    all 18 tests pass (T3's 8 + T4's 4 + T5's 6).  `ruff check` clean.
    `grep -nE "^[[:space:]]*(from|import)[[:space:]]+pipenv\.patched\.pip\._internal"
    pipenv/resolver/pure_python_provider.py` shows zero matches.
  - Parity-divergence candidates (recorded here for T_PARITY_MATRIX
    follow-up; pip-side components we deliberately do NOT mirror today):
    1. `conflict_promoted` flag — pip maintains a `_conflict_promoted`
       set populated by `narrow_requirement_selection` (provider.py
       lines 120-174); we don't ship `narrow_requirement_selection`
       in Phase 3 so we render the raw backtrack-cause count instead.
       Same ordering intent (frequently-backtracking identifiers
       deferred), different storage model.
    2. `direct` flag — pip's `direct` is `isinstance(r,
       ExplicitRequirement)` (URL-direct entries).  Our typed
       `Requirement` doesn't carry URL-direct yet; we render the
       closest analog as `source == "pipfile"`.  When the dataclass
       gains URL-direct (Phase 4 work, not scoped here), the slot
       upgrades to a strict mirror.
    3. `requested_order` integer — pip's `_user_requested` map keys
       identifiers to user-CLI-input ordering with `math.inf`
       fallback.  Initiative G doesn't track CLI-order today
       (Pipfile is the source of truth, not argv); the slot is
       omitted.  Likely doesn't affect lockfile byte-identity for
       Pipfile-only workflows; T15 / T_PARITY_REAL is the gate.
- **files edited/created**:
  - `pipenv/resolver/pure_python_provider.py` (extended:
    `get_preference` body replaces the `T5` `NotImplementedError`
    stub; method-level docstring cites pip's source file +
    function for side-by-side audit)
  - `tests/unit/test_pure_python_provider.py` (extended: 6 new
    T5 tests + an `_ri()` helper that builds the vendored
    `RequirementInformation` namedtuple; module docstring
    refreshed to call out T5 scope)
  - `initiative-g-phase3-plan.md` (this entry: status →
    Completed, log + files filled in, parity-divergence
    candidates recorded)

---

### T6: `PurePythonProvider.is_satisfied_by`

- **depends_on**: `[T1, T3]`
- **location**: `pipenv/resolver/pure_python_provider.py` (extend)
- **description**:
  Per design §5.3.  Three checks:
  - `candidate.version in requirement.specifier`.
  - Extras compatibility: every `requirement.extras` must be a subset
    of `candidate.provides_extras` (via metadata) OR — for the typical
    case where we don't have metadata yet — assume true.  Audit pip's
    behaviour and mirror.
  - `requirement.marker.evaluate(target_env)` is True or `marker is None`.
- **validation**:
  - `==4.0.1` requirement, candidate version `4.0.1` → True.
  - `==4.0.1` requirement, candidate version `4.0.2` → False.
  - `requirement.marker = Marker("python_version < '3.10'")` and
    `target_env = {"python_version": "3.12"}` → False.
- **status**: Completed
- **log**:
  - 2026-05-12 — Implemented per design §5.3.  Replaced the
    `NotImplementedError("T6: ...")` stub with the three-check
    predicate the plan calls out.  Body cites pip's source for the
    audit trail: `SpecifierRequirement.is_satisfied_by` at
    `pipenv/patched/pip/_internal/resolution/resolvelib/requirements.py:121`
    and `PipProvider.is_satisfied_by` at
    `pipenv/patched/pip/_internal/resolution/resolvelib/provider.py:300`.
  - **Check 1 (version)**: `spec.contains(Version(candidate.version),
    prereleases=True)`.  Pip-parity rationale: pip passes
    `prereleases=True` unconditionally at the predicate because
    `PackageFinder` filtered prereleases out upstream.  T4's
    `find_matches` plays the same `PackageFinder` role for us
    (applies the `allow_prereleases` + per-specifier policy), so this
    predicate must not re-filter — otherwise a candidate
    `find_matches` legitimately handed back would be silently
    rejected.  `InvalidVersion` returns `False` (same loud-failure
    stance as T4's sort step).
  - **Check 2 (extras, lazy-metadata stance)**: when
    `candidate.extras` is empty we treat it as "metadata not yet
    loaded" and admit the candidate; when non-empty we require
    `requirement.extras <= candidate.extras`.  Phase-3 audit of pip's
    `SpecifierRequirement.is_satisfied_by` shows pip itself does NOT
    check extras at the predicate — it relies on the `(name, extras)`
    identifier grouping in `identify` (T3) to prevent `django` ever
    being matched against `django[argon2]`.  Our identifier grouping
    is identical, so the lazy-metadata "admit" is the conservative
    mirror of pip; the strict check on populated `extras` is a free
    upgrade for tests / future paths that synthesise extras-bearing
    candidates.  Recorded as parity-divergence candidate #4 below for
    T_PARITY_MATRIX follow-up.
  - **Check 3 (marker)**: `marker.evaluate(self._marker_environment())`
    where `_marker_environment` overlays `self._target_env` onto
    `packaging.markers.default_environment()`.  T7 will reuse the
    same helper to filter transitive deps.  Pip-parity divergence:
    pip does NOT evaluate markers at this predicate — marker
    filtering happens upstream in `iter_dependencies`.  Our typed
    `Requirement` doesn't pre-filter (T7 will, but the predicate
    must still handle a Pipfile-direct requirement carrying a
    marker), so we evaluate defensively.  Strictly more conservative
    than pip (admits a strict subset of what pip admits) — recorded
    as parity-divergence candidate #5 below.
  - **Helper extracted**: `_marker_environment(self)` returns the
    overlay dict.  Lives on the provider so T7 reuses it instead of
    re-deriving the overlay logic.  Unevaluable markers are caught
    in a broad `except Exception:` returning `False` — same defensive
    stance pip applies around marker parsing in `req_install`.
  - RED→GREEN: 14 new tests landed in
    `tests/unit/test_pure_python_provider.py` covering the three plan
    bullets plus the extras-lazy-metadata phase-3 decision, prerelease
    pip-parity, empty-specifier, marker-true / marker-None /
    target-env override paths.  Initial RED with the stub:
    `NotImplementedError("T6: ...")` on first test.  Post-impl: all 32
    tests pass (T3's 8 + T4's 4 + T5's 6 + T6's 14).  `ruff check`
    clean.  `grep -nE
    "^[[:space:]]*(from|import)[[:space:]]+pipenv\.patched\.pip\._internal"
    pipenv/resolver/pure_python_provider.py` shows zero matches.
  - Parity-divergence candidates (additions to the T5 list for
    T_PARITY_MATRIX follow-up):
    4. Extras-at-predicate strictness — pip's
       `SpecifierRequirement.is_satisfied_by` is specifier-only; we
       admit when `candidate.extras` is empty (lazy-metadata mirror)
       AND strict-check when populated.  Same logical result on the
       common path; the strict-check is an extra safety net for
       future code that synthesises extras-bearing candidates.
    5. Marker evaluation at predicate — pip filters markers upstream
       in `iter_dependencies`; we evaluate at the predicate.  Result:
       we may reject a candidate pip would have admitted in a
       contrived case where a Pipfile-direct requirement carries an
       always-false marker.  Strictly more conservative; unlikely to
       affect lockfile parity in practice (Pipfile-direct markers are
       rare).
- **files edited/created**:
  - `pipenv/resolver/pure_python_provider.py` (extended:
    `is_satisfied_by` body replaces the `T6` stub; new
    `_marker_environment` private helper; method-level docstring
    cites pip's source files for the side-by-side audit trail; no
    new top-level imports — `default_environment` is imported lazily
    inside `_marker_environment` to avoid widening the module-import
    surface for a function that runs only when a requirement carries
    a marker)
  - `tests/unit/test_pure_python_provider.py` (extended: 14 new T6
    tests across three test classes — `TestIsSatisfiedByVersion`
    (7 tests: exact pin / range / empty spec / prerelease admit
    parity), `TestIsSatisfiedByMarker` (4 tests: marker-false /
    marker-true / marker-None / target-env override), and
    `TestIsSatisfiedByExtras` (4 tests pinning the lazy-metadata
    Phase-3 decision: unknown / superset / disjoint / no-extras-
    requested); module docstring refreshed to call out T6 scope)
  - `initiative-g-phase3-plan.md` (this entry: status → Completed;
    log + files filled in; parity-divergence #4 + #5 recorded)

---

### T7: `PurePythonProvider.get_dependencies`

- **depends_on**: `[T1, T2, T3]`
- **location**: `pipenv/resolver/pure_python_provider.py` (extend)
- **description**:
  Per design §5.3.  For wheel candidates: call
  `self._metadata_fetcher.fetch_metadata(candidate)`, parse
  `requires_dist` headers, return iterator of `Requirement` instances
  with `source="transitive", parent=candidate.name`.

  For sdist candidates: Q-A's recommendation is fall-back-to-pip.
  This task raises a typed `_SdistEncountered` internal exception
  carrying the candidate; `PurePythonBackend.resolve` (T9) catches it
  and triggers the fallback.

  Filter dependencies by marker evaluation against `target_env` — same
  as `is_satisfied_by`.
- **validation**:
  - Wheel candidate with `Requires-Dist: numpy>=1.20,<2.0` → returns a
    `Requirement(name="numpy", specifier=">=1.20,<2.0", source="transitive")`.
  - Wheel candidate with `Requires-Dist: pytest; extra=='dev'` and the
    requirement didn't request `dev` extra → marker evaluates False;
    dep filtered out.
  - sdist-only candidate → raises `_SdistEncountered(candidate)`.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T8: `PurePythonProvider` integration smoke

- **depends_on**: `[T1, T2, T3, T4, T5, T6, T7]`
- **location**: extend `pipenv/resolver/pure_python_provider.py`
  with a tiny `_drive_resolver(requirements, provider)` helper, plus
  `tests/unit/test_pure_python_provider_smoke.py` (new).
- **description**:
  End-to-end smoke: drive `resolvelib.Resolver(provider, ...)` to
  resolution against a synthetic in-memory `ParsedManifestCache` +
  `MetadataFetcher` mock that returns hand-crafted candidates +
  metadata.  Assert the resolved graph matches an expected pin set.
- **validation**:
  - Resolve `requests`+`certifi`+`urllib3` against a synthetic 3-package
    cache where each package has 2-3 versions; expected pins land.
  - Resolve a conflict scenario (`a` requires `b<2`; `c` requires
    `b>=2`); assert `resolvelib.ResolutionImpossible` raises with
    both causes listed.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T9: `PurePythonBackend` + fail-loud sdist handling + Q-F pre-check

- **depends_on**: `[T8]`
- **location**: `pipenv/resolver/backends/pure_python.py` (new)
- **description**:
  Per design §5.4 + Q-A + Q-F decisions.  Implements Initiative F's
  `Backend` protocol.

  Flow inside `resolve(request)`:

  1. **Pre-fetch** top-level package candidates + metadata (Q-B) via
     `ParallelFetcher.populate`.
  2. **Q-F top-level wheel-availability pre-check**: for every
     top-level Pipfile package in `request.packages.specs`, scan its
     cached candidates from `ParsedManifestCache`.  If ZERO candidates
     are wheels matching the target Python + platform, abort:
     `ResolverResponse.result = ResolutionError(pip_message=<clear
     error naming the offending package(s) + suggesting either pinning
     a version that has wheels or ``pipenv lock --backend pip`` for
     this resolve>, conflicts=[])`.  Catches the common
     sdist-only-toplevel case at startup, not 30 s into a doomed
     resolve.
  3. Build `Requirement` set from `request.packages.specs`.
  4. Drive `resolvelib.Resolver(PurePythonProvider(...), ...)`.
  5. **Q-A fail-loud sdist handling**: catch `_SdistEncountered` from
     `get_dependencies` (raised by T7 when a transitive's only choice
     is an sdist).  Translate into
     `ResolverResponse.result = InternalError(message=<package +
     version + "sdist-only transitive; not supported by pure-python
     backend in Phase 3.  Either pin to a version with wheels, or
     switch resolver_backend = 'pip'.">, traceback=...)`.  No silent
     fallback.
  6. **Normal failure mapping**:
     - `resolvelib.ResolutionImpossible` → `ResolutionError` with the
       conflict list translated.
     - Network/transient errors during `get_dependencies` (mid-resolve)
       → `InternalError`.
     - Other unexpected exceptions → `InternalError` with traceback.
  7. **Success** → `ResolverSuccess(locked=<typed LockedRequirement
     tuple translated from the resolved graph>)`.

- **validation**:
  - Mock `PurePythonProvider` to resolve successfully → backend returns
    `ResolverResponse(result=ResolverSuccess(locked=...))`.
  - Mock provider to raise `ResolutionImpossible` → backend returns
    `ResolverResponse(result=ResolutionError(conflicts=...))`.
  - Mock provider to raise `_SdistEncountered("foo", "1.2.3")` →
    backend returns `ResolverResponse(result=InternalError(message=...))`;
    error message contains both the package name and the version;
    NO call to pip backend.
  - Q-F pre-check: construct a mocked cache where top-level package
    `bar` has zero wheel candidates → backend returns
    `ResolverResponse(result=ResolutionError(pip_message=...))`;
    error message names `bar` AND suggests `pipenv lock --backend pip`.
    `resolvelib.Resolver` is NEVER invoked (verified via mock).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T10: Backend registration

- **depends_on**: `[T9]`
- **location**: `pipenv/resolver/backends/__init__.py` (extend the
  existing `REGISTRY` populate).
- **description**:
  Register `PurePythonBackend` under name `"pure-python"`.  `pip` stays
  the default.  Verify the `get_backend("pure-python")` lookup works
  and that `--backend pure-python` / `[pipenv] resolver_backend =
  "pure-python"` selects it.
- **validation**:
  - `python -c "from pipenv.resolver.backends import get_backend; b = get_backend('pure-python'); print(b.name, b.is_available())"` prints `pure-python True`.
  - `pipenv lock --backend pure-python` smoke-runs against the 30-pkg
    fixture (not parity-checked yet; just no crashes).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T11: Unit tests — `Requirement`

- **depends_on**: `[T1]`
- **location**: `tests/unit/test_pure_python_requirement.py` (new)
- **description**:
  Round-trip, equality, hashability, `from_pipfile_entry` across the
  shapes enumerated in T1's spec.  Coverage ≥ 95 %.
- **status**: Completed
- **log**:
  - Audited T1's 15-test seed against
    `pipenv/resolver/pure_python_requirement.py`: starting coverage was
    97.22 % (line 174 — the `TypeError` raise for unsupported value
    shapes — was the sole miss).
  - Extended the file with 20 additional tests covering the T11
    matrix: unsupported-shape rejection (int / list / None);
    dict-form keys the constraint node deliberately ignores
    (`editable`, `git`, `ref`, `index`, `path`); empty-string and
    missing-`version` dict shapes; whitespace-tolerant specifier
    parsing; combined version + extras + markers; `None` and `""`
    markers falling through to `marker is None`; name-canonicalisation
    corner cases (`Foo.Bar_Baz` → `foo-bar-baz`, `a__b--c..d` →
    `a-b-c-d`, `3M` → `3m`); and the `source` Literal escape-hatch
    audit (no runtime enforcement, by design — pinned with a
    `# T11 audit:` rationale).
  - Final coverage on `pure_python_requirement.py`: **100 % line +
    100 % branch (35 tests)**, measured with
    `pytest tests/unit/test_pure_python_requirement.py
    --cov=pipenv.resolver.pure_python_requirement
    --cov-report=term-missing --cov-branch -o addopts=""`.
  - No bugs found in T1's implementation while extending coverage —
    silent-ignore behaviour for non-constraint dict keys
    (`editable`, VCS) matches the docstring contract; documented in
    the test file rather than tightened, per T11's brief.
- **files edited/created**:
  - `tests/unit/test_pure_python_requirement.py` (extended;
    35 tests total, 100 % coverage).

---

### T12: Unit tests — `MetadataFetcher`

- **depends_on**: `[T2]`
- **location**: `tests/unit/test_pure_python_metadata.py` (new)
- **description**:
  PEP 658 fast path (with mock PEP 658 URL + body); wheel-head
  fallback (with synthetic test wheels built in `tmp_path`); cache
  round-trip; hash-mismatch behaviour; missing-METADATA inside the
  zip fallback path.  Coverage ≥ 90 %.
- **status**: Completed
- **log**:
  - 2026-05-12: Extended the T2 RED-phase test suite from 9 to 65
    tests, raising line coverage on
    `pipenv/resolver/pure_python_metadata.py` from 73 % to 97.75 %
    (well above the 90 % gate).  New test surface:
    `TestParseMetadataText` (full `CoreMetadata` field population,
    blank-`Requires-Python` normalisation), `TestCoreMetadataDataclass`
    (frozen, slots, hashable + `frozenset` membership, value equality),
    `TestPEP658Extra` (empty / `None` / non-sha256 hash dicts,
    non-UTF-8 body, HTTP 404, session raises, missing body),
    `TestWheelHeadFallbackExtra` (missing METADATA member, corrupt
    zip tail, HEAD 405 with no / `*` / garbage Content-Range, HEAD
    405 with probe 4xx, both calls session-failure, HEAD 200 with
    no Content-Length, HEAD 200 with malformed Content-Length,
    wheel using Windows `\` separator for METADATA),
    `TestMetadataCacheExtra` (malformed JSON, non-dict payload,
    wrong schema version, missing required key, generic `OSError`
    on read, `UnicodeDecodeError`, `cache.put` `OSError` is
    non-fatal + debug-logged, `os.replace` failure cleans temp
    file, URL → path determinism + uniqueness, fresh-process
    round trip), `TestHttpHelpers` (`_get_header` case-insensitive,
    raising `get` / `items`, `_http_request` exception → `None`,
    `_http_get_range` failure modes), and `TestPartialFile`
    (seekable / readable / writable, seek SET / CUR / END +
    negative + bad whence, in-buffer read, EOF read, prefix-fetch
    growth, prefix oversize trim, prefix short-read raises,
    suffix-fetch growth, suffix oversize trim, suffix short-read
    raises).  Remaining 7 uncovered lines are the
    `_MAX_CENTRAL_DIRECTORY_WINDOW`-overrun branch (would need a
    >1 MB synthetic wheel), the `total_length <= 0` guard (the
    probe path already raises before reaching it), and a couple
    of related defensive branches that aren't reachable from the
    public API surface.  No bugs found in T2's implementation.
- **files edited/created**:
  - `tests/unit/test_pure_python_metadata.py` — extended (9 → 65
    tests; +56)

---

### T13: Unit tests — `PurePythonProvider`

- **depends_on**: `[T8]`
- **location**: `tests/unit/test_pure_python_provider.py` (new)
- **description**:
  Per-method coverage of `identify`, `find_matches`, `get_preference`,
  `is_satisfied_by`, `get_dependencies`.  Use mock cache + mock
  metadata fetcher.  Edge cases per T3–T7 validation lists.  Coverage
  ≥ 90 %.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T14: Unit tests — `PurePythonBackend` + fail-loud sdist + Q-F pre-check

- **depends_on**: `[T9]`
- **location**: `tests/unit/test_pure_python_backend.py` (new)
- **description**:
  - Successful resolve → `ResolverSuccess`.
  - `ResolutionImpossible` → `ResolutionError` with conflict list.
  - `_SdistEncountered` (transitive) → `InternalError` whose message
    contains the package name + version + "sdist-only" + suggested
    workaround.  NO call to pip backend (verified via mock).
  - Q-F top-level pre-check: mocked cache returns zero wheel
    candidates for a top-level package → `ResolutionError` with a
    message naming the offending package + suggesting
    `pipenv lock --backend pip`.  `resolvelib.Resolver` never invoked.
  - Backend is registered (loadable from `get_backend("pure-python")`).
  - Coverage ≥ 90 %.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T15: Integration — backend parity on 100-pkg bench

- **depends_on**: `[T10, T14]`
- **location**: `tests/integration/test_backend_parity.py` (new)
- **description**:
  Same Pipfile, lock with both backends, compare lockfiles field-by-field:
  - `_meta.hash` byte-equal (both backends consume Pipfile content;
    same hash by construction).
  - Per-section pins byte-equal (`{name: version}` map).
  - Per-package `hashes` set-equal (order-independent).
  - Per-package `markers` string-equal (modulo whitespace
    canonicalisation).
  Divergences logged into `tests/integration/test_backend_parity_known_diffs.md`
  with justification.  Zero unjustified divergences is the gate.
- **validation**:
  - `pytest tests/integration/test_backend_parity.py -v` passes.
  - `_known_diffs.md` exists with any justified diffs (empty file is
    acceptable).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_PARITY_REAL: Integration — parity across 10 real projects

- **depends_on**: `[T15]`
- **location**:
  - `tests/integration/test_backend_parity_realworld.py` (new)
  - Pipfile fixtures at `tests/integration/fixtures/realworld/<project>/Pipfile`
- **description**:
  Curated list of 10 real-world top-PyPI projects covering wheel-heavy
  / sdist-mix / Django / data-science / async / web frameworks.
  Suggested list (to be confirmed in the design-doc PR):
  - `django` + `psycopg2-binary`
  - `flask` + `gunicorn`
  - `fastapi` + `uvicorn`
  - `requests` + `httpx`
  - `pandas` + `numpy`
  - `pytest` + `pytest-cov` + `pytest-django`
  - `celery` + `redis`
  - `sqlalchemy` + `alembic`
  - `cryptography` + `pyOpenSSL`
  - `boto3` + `botocore`
  Each fixture has a hand-pinned Pipfile.  Test runs both backends and
  asserts lockfile parity (same gate as T15).
- **validation**:
  - All 10 projects' lockfiles match across backends OR the divergence
    is justified in `_known_diffs.md`.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_MATRIX: CI matrix — parity across pip N-1 / N / N+1

- **depends_on**: `[T_PARITY_REAL]`
- **location**:
  - `.github/workflows/ci.yaml` (extend with a new matrix job)
- **description**:
  Add a CI job that runs T15 + T_PARITY_REAL against three pip
  versions (the current bundled version + the previous + the next
  if pre-release is available).  Failure on any matrix entry blocks
  Phase 3 sign-off.
- **validation**:
  - CI job appears in the workflow.
  - Matrix runs to completion on a sample PR.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_BENCH: Bench measurement under both backends

- **depends_on**: `[T10]`
- **location**:
  - `.github/workflows/ci.yaml` (extend the bench job)
  - Commit message records before/after numbers per the design doc §8 gate.
- **description**:
  Run `benchmarks/benchmark.py` once under each backend on the same
  commit:
  - **Run A**: default (pip backend).
  - **Run B**: `PIPENV_RESOLVER_BACKEND=pure-python` (or whatever env
    surface T10 exposes).
  Compare medians of 3 runs each.  Phase 3 perf gate (design §8):
  `lock-warm` under pure-python ≤ 14.5 s (≥ 30 % off the pre-phase-5
  baseline of 21.3 s).
- **validation**:
  - Both bench artifacts exist; the recorded numbers land in the PR
    description.
  - `lock-warm` median under pure-python meets the gate.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_PARITY_MATRIX: Parity-matrix doc

- **depends_on**: `[T15, T_PARITY_REAL]`
- **location**: `docs/dev/initiative-g-phase3-parity-matrix.md` (new)
- **description**:
  Enumerates every observed behavioural divergence between the pure-
  python and pip backends.  Each entry has:
  - Brief description.
  - Pip-side code reference (file + function).
  - Pure-python-side decision (mirror, accept divergence with rationale,
    or punt).
  - Test reference pinning the choice.
- **validation**:
  - Doc shipped; every justified divergence in
    `tests/integration/test_backend_parity_known_diffs.md` cross-
    references this doc.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_SHIP: Phase 3 ship-bundle

- **depends_on**: `[T_BENCH, T_PARITY_MATRIX]`
- **location**:
  - `news/initiative-g-phase3-pure-python-backend.feature.rst` (new)
  - `docs/dev/initiative-g-pure-python-design.md` (umbrella doc) —
    flip Phase 3 acceptance bullets to `[x]`.
  - `docs/pipfile.md` — entry for `[pipenv] resolver_backend` Pipfile
    setting + the `pure-python` option.
- **description**:
  Per the T17/T22 convention from Phase 1+2: news fragment, design-
  doc status update, user-facing setting documentation.
- **validation**:
  - `python -m towncrier --version` succeeds; fragment renders.
  - User docs show the new setting with semantics, defaults, and
    sdist-fallback note.
  - Umbrella design doc shows Phase 3 row checked with measured perf
    delta inline.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

## Parallel Execution Groups

| Wave | Tasks                              | Can Start When                |
| ---- | ---------------------------------- | ----------------------------- |
| 1    | T1, T2                             | Immediately (no deps)         |
| 2    | T3, T11, T12                       | T1 done (T3, T11), T2 (T12)   |
| 3    | T4, T5, T6                         | T1 + T3 done                  |
| 4    | T7                                 | T1 + T2 + T3 done             |
| 5    | T8                                 | T1–T7 done                    |
| 6    | T9, T13                            | T8 done                       |
| 7    | T10, T14                           | T9 done                       |
| 8    | T15                                | T10 + T14 done                |
| 9    | T_PARITY_REAL, T_BENCH             | T15 done                      |
| 10   | T_MATRIX                           | T_PARITY_REAL done            |
| 11   | T_PARITY_MATRIX                    | T15 + T_PARITY_REAL done      |
| 12   | T_SHIP                             | T_BENCH + T_PARITY_MATRIX done|

Max concurrency: 3 (Wave 2 — T3 + T11 + T12).  Total: 17 tasks.

---

## Testing Strategy

- **Unit tests** alongside implementation (T11–T14 pin to T1, T2,
  T8, T9 respectively).  Coverage gate via T17-of-Phase-1's
  `.github/workflows/ci.yaml:resolver-module-coverage` job — extend
  it to include the new test files + `--cov=pipenv.resolver.pure_python_*`
  + `--cov=pipenv.resolver.backends.pure_python`.
- **Integration tests** (T15, T_PARITY_REAL) gated behind real PyPI;
  marked `@pytest.mark.needs_internet`.
- **Parity gate** (T15 + T_PARITY_REAL) is the load-bearing Phase 3
  acceptance criterion.  Divergences must be justified in writing
  (T_PARITY_MATRIX).
- **CI matrix** (T_MATRIX) extends the parity gate across pip
  versions.

---

## Risks & Mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Pip's `get_preference` tie-breaking differs from our mirror in subtle ways → lockfile drift | T15 + T_PARITY_REAL are the byte-identity gates; the parity matrix doc captures every divergence; sign-off requires zero unjustified entries. |
| PEP 658 not advertised on private indexes → wheel-head fallback hit rate is high → slower than expected | T_BENCH measures the actual wheel-head latency; if it's net-harmful on private-index-heavy projects, document and ship as opt-in only.  Phase 4 can rework. |
| sdist-fallback masks real regressions (user thinks they're on pure-python but silently fell back) | T9 logs an info-level fallback message; T_SHIP documents the behaviour; `pipenv lock --verbose` will show every fallback so users can audit. |
| `resolvelib` version-bump upstream breaks our `AbstractProvider` impl | We vendor resolvelib via patched-pip; upstream bumps are caught by `tasks/vendoring`.  Add a regression test that imports our provider and asserts the abstract methods are still required. |
| `MetadataFetcher` cache corruption / poisoning | Same atomic-write contract as `ParsedManifestCache` (T7 pattern).  Wheels are content-addressed (sha256 in the index), so a bad cache entry fails hash check on read. |
| Lockfile parity gate too strict — blocks merge on cosmetic differences (whitespace, key order) | T15 explicitly canonicalises before comparison (sorted-keys JSON, frozenset hashes, normalised marker strings).  Anything still differing IS a real divergence. |
| 30 % perf gate not reachable without HTTP/2 | T_BENCH measures honestly; if we land Phase 3 at 20 % instead of 30 %, ship anyway and document.  The maintenance-cost reduction stands regardless of the perf delta. |

---

## Out of Scope (this plan only)

Explicitly **not** part of Phase 3:

- sdist resolution (falls back to pip backend per Q-A).
- Removing the pip backend (Phase 4 sign-off).
- HTTP/2 transport (separate post-Phase-3 effort).
- Replacing `resolvelib`.
- Cross-platform lockfiles.
- Keyring auth (deferred per Q-D).
- CI bench workflow changes beyond what T_BENCH adds.
