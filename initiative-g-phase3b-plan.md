# Plan: Initiative G — Phase 3b (Sdists + Markers + CI dogfood)

**Generated**: 2026-05-12
**Source design doc**: [`docs/dev/initiative-g-phase3-design.md`](docs/dev/initiative-g-phase3-design.md)
**Branch**: `maintenance/code-cleanup-phase6-pure-python-resolver-2026-07` (continues from Phase 3a).
**Scope**: Phase 3b only — fills the gaps Phase 3a punted on so the pipenv test suite can run end-to-end through the pure-python backend.

---

## Overview

Phase 3a (T1–T14 + T9b + T_PLUMBING, commits `a5ac1eff..8b24acee`) shipped a
working pure-python resolver backend: registered, CLI-dispatched,
end-to-end functional. Smoke test confirms a single-package lock
produces a byte-equal `_meta.hash` vs pip.

Phase 3a deliberately punted on:

1. **Sdists**: Q-A "fail loud" was the Phase 3a decision. Phase 3b
   inverts it — we now build sdist METADATA on the fly via
   `pyproject_hooks` (PEP 517 frontend), so the pure-python backend
   handles any package pip would.
2. **Markers**: Phase 3a's `_translate_mapping` emitted no
   `markers` field on `LockedRequirement`. Phase 3b emits both
   the `Requires-Python` → `python_version >= 'X.Y'` translation
   AND propagates the `Requires-Dist` marker that introduced each
   transitive.
3. **Lockfile parity finish**: `index` field today writes the URL;
   pip writes the source name. Phase 3b looks up source name from
   `request.sources`. Hashes today are only the chosen file's
   hash; pip emits hashes for all distfiles of the resolved
   version. Phase 3b collects them all.

The Phase 3b acceptance gate is **the existing pipenv test suite
passes under `PIPENV_RESOLVER_BACKEND=pure-python`** — a stronger
signal than T15's 100-pkg parity bench. A non-blocking CI matrix
job surfaces divergences as they appear.

### Decisions baked into this plan (sign-off 2026-05-12)

- **Sdist build**: direct PEP 517 via vendored `pyproject_hooks`'
  `BuildBackendHookCaller.prepare_metadata_for_build_wheel(...)`.
  No new vendoring; no subprocess to `pip wheel`.
- **Marker propagation**: full — `Requires-Python` AND the
  `Requires-Dist`-line marker that introduced each transitive.
- **CI matrix**: add the `PIPENV_RESOLVER_BACKEND=pure-python` job
  to `.github/workflows/ci.yaml` immediately, `continue-on-error: true`.
  Promote to required in a follow-up after it goes green.

---

## Dependency Graph (high-level)

```
        T_M1 ─┬─ T_M3 ─┐
              │        │
        T_M2 ─┘        ├─ T_M4 ─ T_M5
                       │
        T_S1 ─ T_S2 ─ T_S3 ─ T_S4 ─ T_S5 ─ T_S6
                                        │
                                        T_CI1 ─ T_CI2
```

Markers track (T_M*) and sdists track (T_S*) are independent and
parallel-safe up to their respective convergence points. CI hookup
waits on both.

---

## Tasks

### T_M1: Marker propagation — extend Candidate + Requirement

- **depends_on**: `[]`
- **location**:
  - `pipenv/resolver/candidate.py` (extend)
  - `pipenv/resolver/pure_python_requirement.py` (extend)
- **description**:
  - `Candidate`: confirm `requires_python` is preserved end-to-end
    from PEP 691 parse → cache → resolver. It already is (verified
    via smoke). No code change needed; pin via test.
  - `Requirement`: add an optional `introducing_marker:
    Marker | None = None` field. When `Requirement.from_pipfile_entry`
    builds a transitive via T_M2, this slot carries the
    `Requires-Dist` line's marker (e.g. `extra == 'dev'`,
    `sys_platform == 'darwin'`).
  - Keep the dataclass frozen; rebuild via `dataclasses.replace`
    when the resolver needs a marker-aware variant.
- **validation**:
  - `Requirement(name="x", ..., introducing_marker=Marker("python_version<'3.10'"))`
    constructs, equals itself, hashes.
  - `Requirement.from_pipfile_entry` accepts an optional
    `introducing_marker` kwarg.
- **status**: Completed
- **log**:
  - Added `introducing_marker: Marker | None = None` to the
    `Requirement` frozen dataclass after the existing `parent`
    field, preserving `__init__` argument order for all existing
    callers (the new field is defaulted, so positional construction
    sites continue to work unchanged).
  - `from_pipfile_entry` was deliberately NOT widened — the helper
    only constructs top-level Pipfile constraints, which never
    carry an introducing marker. Transitives are built via the
    direct `Requirement(...)` call in
    `PurePythonProvider.get_dependencies` (T_M2's job).
  - `Marker` is hashable out of the box in `pipenv.vendor.packaging`
    (`markers.py:329`) — no `__hash__` override needed; the
    frozen-dataclass derived `__hash__` continues to work for
    `frozenset[Requirement]` membership with the new field.
  - Added a new `TestRequirementIntroducingMarker` test class (9
    tests) to `tests/unit/test_pure_python_requirement.py`
    covering: default-to-None on `from_pipfile_entry`, default-to-None
    on direct construction without the kwarg, round-trip with the
    kwarg, equality / inequality / hash semantics across same /
    different / None markers, `frozenset` membership, the
    `dataclasses.replace` round-trip pattern T_M2 will use, and the
    pin that `from_pipfile_entry` rejects the kwarg.
  - Added a new `TestRequiresPythonPreservation` test class (2
    tests) to `tests/unit/test_candidate.py` pinning that
    `Candidate.requires_python` survives end-to-end from the PEP 691
    JSON parse (`_parse_pep691_json`) verbatim — both the
    populated (`">=3.10"`) and `None` paths. This is the
    dependency that T_M3's marker emission relies on.
  - Coverage on `pipenv/resolver/pure_python_requirement.py` is
    100 % (37 / 37 statements); the grep gate
    `grep -n "pip\._internal" ...` returns 0 matches.
  - All 44 tests in `test_pure_python_requirement.py` (35 existing
    + 9 new) and all 33 tests in `test_candidate.py` (31 existing
    + 2 new) pass.
- **files edited/created**:
  - `pipenv/resolver/pure_python_requirement.py` (added
    `introducing_marker` field and docstring section)
  - `tests/unit/test_pure_python_requirement.py` (added
    `TestRequirementIntroducingMarker`)
  - `tests/unit/test_candidate.py` (added
    `TestRequiresPythonPreservation`)
  - `initiative-g-phase3b-plan.md` (this entry)

---

### T_M2: Provider records introducing-marker on transitives

- **depends_on**: `[T_M1]`
- **location**: `pipenv/resolver/pure_python_provider.py` (extend
  `get_dependencies`).
- **description**:
  Today `get_dependencies` parses each `Requires-Dist` line and
  builds a `Requirement(source="transitive", parent=<name>)`. Phase 3b
  also captures the marker from the parsed line — the
  `packaging.requirements.Requirement` parser already exposes
  `.marker`. Pass that through to the new `introducing_marker`
  slot from T_M1.
  - The marker-extras-active filter logic stays — it already
    short-circuits transitives whose marker evaluates False under
    the parent's extras.
  - For transitives that DO pass the marker filter, the
    `introducing_marker` carries the original marker text so
    `_translate_mapping` can emit it on the lockfile entry.
- **validation**:
  - Mock `Requires-Dist: pytest; python_version < '3.10'`,
    parent extras = `{}`, target_env `python_version='3.9'` →
    transitive's `introducing_marker` equals the parsed marker.
  - Mock `Requires-Dist: numpy>=1.20` (no marker) → transitive's
    `introducing_marker is None`.
- **status**: Completed
- **log**:
  - 2026-05-12: Threaded `parsed.marker` into the new
    `introducing_marker` slot when `get_dependencies` constructs a
    transitive `Requirement`. The legacy `marker` field stays
    populated with `parsed.marker` too — the existing T7 contract
    (`TestGetDependenciesMarkerFilter::test_extra_marker_kept_when_parent_requested_that_extra`)
    pins it; the two fields coexist for Phase 3b so T_M3 can read
    `introducing_marker` for lockfile emission without disturbing
    T6's `is_satisfied_by` evaluator path. Added a dual-marker
    comment block at the construction site documenting the split.
    RED→GREEN via 4 new tests in
    `TestGetDependenciesIntroducingMarker`; 62/62 unit tests pass;
    module coverage 97% (floor 90%); zero `pip._internal` imports.
- **files edited/created**:
  - `pipenv/resolver/pure_python_provider.py` (extended
    `get_dependencies` Requirement construction with
    `introducing_marker=parsed.marker` + dual-marker comment block).
  - `tests/unit/test_pure_python_provider.py` (added
    `TestGetDependenciesIntroducingMarker` with 4 tests covering
    marker present, marker absent, extras-filter unchanged, and
    extras-context active marker).

---

### T_M3: `_translate_mapping` emits markers

- **depends_on**: `[T_M2]`
- **location**: `pipenv/resolver/backends/pure_python.py` (extend
  `_translate_mapping`).
- **description**:
  For each resolved `(identifier, candidate)`:
  - Read `candidate.requires_python` (a string like `>=3.10`).
    Convert to a marker string: `>=3.10` → `python_version >= '3.10'`,
    `>=3.8,<4` → `python_version >= '3.8' and python_version < '4'`,
    etc. Use `pipenv.vendor.packaging.specifiers.SpecifierSet`
    iteration + a small `_op_to_marker` mapping.
  - Look up the `Requirement` instance(s) that selected this
    candidate — `resolvelib.Result.criteria` (or whatever the
    vendored resolvelib exposes) holds the requirements; combine
    each non-None `introducing_marker` via `and`. For multiple
    introducing markers (a candidate satisfies multiple
    requirements), `OR` them with parentheses.
  - Combine Requires-Python marker AND introducing marker(s) into
    a single canonical marker string.
  - Emit as `markers="..."` on the `LockedRequirement`.
- **validation**:
  - Candidate with `requires_python=">=3.10"`, no introducing
    marker → `markers == "python_version >= '3.10'"`.
  - Candidate with `requires_python=">=3.8"`, one introducing
    marker `python_version < '3.12'` → `markers ==
    "python_version >= '3.8' and python_version < '3.12'"` (or
    a canonically-equivalent form).
  - Candidate with no `requires_python`, no introducing marker →
    `markers is None`.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_M4: Index URL → source name lookup

- **depends_on**: `[T_M3]`
- **location**: `pipenv/resolver/backends/pure_python.py` (extend
  `_translate_mapping`).
- **description**:
  Build a `dict[str, str]` map of `url → name` from `request.sources`
  at the top of `resolve()`. Pass to `_translate_mapping`. For each
  resolved candidate, emit `index=<source_name>` instead of the
  raw URL. Default to `default_index` if the URL doesn't match
  any source (defensive).
- **validation**:
  - `request.sources = [Source(name="pypi", url="https://pypi.org/simple")]`
    + resolved candidate from `https://pypi.org/simple` →
    `LockedRequirement.index == "pypi"`.
  - URL not in `request.sources` → emit the URL as-is (defensive
    fallback documented).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_M5: Marker translation unit tests

- **depends_on**: `[T_M4]`
- **location**: `tests/unit/test_pure_python_backend.py` (extend) +
  `tests/unit/test_pure_python_provider.py` (extend).
- **description**:
  - Backend tests for `_translate_mapping` marker emission
    (Requires-Python alone; introducing marker alone; both
    combined; neither → `markers is None`).
  - Provider tests for `get_dependencies` setting
    `introducing_marker` correctly across the four shapes
    (no marker, marker-only, marker+extras, marker+target-env).
  - Index-name lookup tests covering URL→name + the defensive
    fallback.
- **validation**: coverage stays ≥ 90 % on the two modules.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_S1: `pure_python_sdist.py` — sdist METADATA extractor

- **depends_on**: `[]`
- **location**: `pipenv/resolver/pure_python_sdist.py` (new).
- **description**:
  Direct PEP 517 build via vendored `pyproject_hooks`.
  - Public surface:
    `extract_metadata_from_sdist(candidate, session, *, cache=None) -> CoreMetadata`.
  - Flow:
    1. Cache hit → return.
    2. Download the sdist body to a tempdir via `session.get(url)`
       (re-use the polymorphism helpers from `pure_python_metadata`).
    3. `tarfile.open` / `zipfile.ZipFile` extract into another
       tempdir.
    4. Locate `pyproject.toml`; parse the `[build-system]` table.
       If missing, use the legacy `setuptools.build_meta:__legacy__`
       fallback (PEP 517 §10).
    5. Install build requirements into an isolated venv? **NO** —
       Phase 3b skips build isolation. The user's environment must
       carry build-time deps (or the package's `pyproject.toml`
       names them and we trust pip's installation history). This
       is a known tradeoff vs pip; document in T_PARITY_MATRIX.
    6. Run `BuildBackendHookCaller(srcdir, backend_name).prepare_metadata_for_build_wheel(out_dir)`.
    7. Read `METADATA` from `<out_dir>/<dist-info>/METADATA`.
    8. Parse via `_parse_metadata_text` (shared with the wheel
       path).
    9. `cache.put` if cache is provided.
  - All temp dirs cleaned up in a `finally`.
  - Errors raise `SdistBuildError(MetadataFetchError)` with the
    backend's stderr if available, so failures are actionable.
- **validation**:
  - Against a real PyPI sdist (e.g. a small pure-Python package
    that publishes only sdists), `extract_metadata_from_sdist` returns
    a `CoreMetadata` with `requires_dist` populated.
  - Synthetic sdist fixture in `tmp_path` (build via
    `python -m build --sdist` in conftest, or hand-craft a minimal
    tarball with a `pyproject.toml` and a `setuptools` build-system
    pointer): metadata extracts cleanly.
  - Build failure (sdist with a syntax error or unbuildable
    `pyproject.toml`) → `SdistBuildError` with the backend's stderr
    visible.
- **status**: Completed
- **log**:
  - 2026-05-12: TDD RED→GREEN — wrote 27 tests covering the 7-case
    matrix from the plan brief (happy path, cache round-trip, HTTP
    failure, corrupt archive, build-backend failure, no-pyproject
    legacy fallback, path traversal) plus 9 defensive-branch tests
    (zip happy path, empty body, non-string backend, backend-path
    handling, empty zip member, missing METADATA, non-UTF-8 METADATA,
    cache write OSError, filename-from-URL edge cases, timeout via
    monkeypatched hook caller).
  - PEP 517 frontend: vendored
    `pipenv.patched.pip._vendor.pyproject_hooks.BuildBackendHookCaller`
    (constructor: `source_dir, build_backend, backend_path=None,
    runner=None, python_executable=None`).
    `prepare_metadata_for_build_wheel(metadata_directory)` returns the
    relative dist-info subfolder name as a `str`.
  - **No build isolation** in Phase 3b: the vendored
    `BuildBackendHookCaller` has no isolation knob; its `runner`
    callable simply subprocess-spawns the in-process hook script using
    `sys.executable` in the current Python env.  Build-time deps must
    be carried by the resolver user's environment.  Documented in the
    module docstring.
  - Timeout: 300 s via `concurrent.futures.ThreadPoolExecutor`; surfaces
    as `SdistBuildError("sdist build timed out after 300s ...")`.
  - Path-traversal protection: manual pre-extract validation of every
    member name — reject empties, absolute paths, and any `..`
    segment — applied uniformly to both tar (`tarfile`) and zip
    (`zipfile`) archives.  Tar extraction also uses Python 3.12+'s
    `filter="data"` for defense in depth.
  - Source-root enforcement: sdist convention requires exactly one
    top-level directory; multi-dir / file-at-root tarballs reject.
  - Coverage: 94 % on the new module (target was ≥ 90 %).  Remaining
    misses are the py3.10 tomli fallback, the older-Python tar filter
    `TypeError` rescue, and a few tarfile-only defensive branches
    (symlink/dev/fifo) that are awkward to portably construct.
  - Adjacent suites unaffected: `tests/unit/test_pure_python_metadata.py`
    65/65 still green.
- **files edited/created**:
  - `pipenv/resolver/pure_python_sdist.py` (new, 150 statements)
  - `tests/unit/test_pure_python_sdist.py` (new, 27 tests)

---

### T_S2: Integrate sdist path into `MetadataFetcher.fetch_metadata`

- **depends_on**: `[T_S1]`
- **location**: `pipenv/resolver/pure_python_metadata.py` (extend
  `fetch_metadata`).
- **description**:
  Today `fetch_metadata` always treats candidates as wheels. Phase 3b:
  - Branch on `candidate.is_wheel`.
  - Wheel: existing PEP 658 + wheel-head fallback.
  - Sdist: delegate to `extract_metadata_from_sdist(candidate, session,
    cache=cache)` (T_S1).
  - Cache is shared — same on-disk `MetadataCache` keyed by URL
    sha256.
- **validation**:
  - Wheel candidate routes through existing path (regression test).
  - Sdist candidate routes through T_S1; result is a
    `CoreMetadata` indistinguishable in shape from a wheel result.
  - Cache hit on a sdist doesn't re-build.
- **status**: Completed
- **log**:
  - Branch sits after the cache short-circuit and before the wheel
    PEP 658 / wheel-head paths. Wheel path is byte-identical to
    pre-T_S2; sdist path delegates to
    `pure_python_sdist.extract_metadata_from_sdist(candidate,
    session, cache=cache)` via a local import (so `pyproject_hooks`
    + `tarfile` + `zipfile` aren't paid for on wheel-only resolves).
  - Cache lookup happens in `fetch_metadata` first, so a populated
    entry short-circuits both the heavy import AND the extractor
    entirely. T_S1 also calls `cache.get` internally — that's the
    intentional "double-dip" the plan calls out; the second call
    only fires on a cold-cache sdist, where the cost is dwarfed by
    the download + build step that follows.
  - 3 new tests in `TestFetchMetadataSdistRouting`:
    `test_sdist_candidate_routes_to_sdist_extractor` (no HTTP
    issued on sdist URL; result propagated verbatim),
    `test_wheel_candidate_does_not_route_to_sdist` (extractor
    patched to raise — never invoked on wheel candidate),
    `test_sdist_cache_passed_through` (cache kwarg forwarded;
    pre-populated cache short-circuits extractor entirely).
  - Coverage on `pure_python_metadata.py` is 96 % (≥ 90 % gate). All
    65 pre-existing tests still pass; T_S1's 27 sdist tests still
    pass (untouched).
  - `grep "pip\._internal" pipenv/resolver/pure_python_metadata.py` →
    0 import matches (one docstring mention of the constraint
    survives, by design).
- **files edited/created**:
  - `pipenv/resolver/pure_python_metadata.py` (added sdist branch +
    docstring section in `fetch_metadata`)
  - `tests/unit/test_pure_python_metadata.py` (added
    `_make_sdist_candidate` helper + `TestFetchMetadataSdistRouting`
    class with 3 tests)

---

### T_S3: Remove `_SdistEncountered` fail-loud from provider

- **depends_on**: `[T_S2]`
- **location**: `pipenv/resolver/pure_python_provider.py` (modify
  `get_dependencies`) + `pipenv/resolver/backends/pure_python.py`
  (remove the Q-A handler).
- **description**:
  - Provider: `get_dependencies` no longer raises
    `_SdistEncountered` on sdist candidates. It simply calls
    `self._metadata_fetcher(candidate)`, which routes through T_S2
    transparently.
  - Keep `_SdistEncountered` exported as a typed exception for
    backwards-compat (some tests reference it), but mark it
    deprecated and never raise it from production code.
  - Backend: remove the `except _SdistEncountered` block from
    `resolve()`. Update the docstring.
- **validation**:
  - Sdist candidate → `get_dependencies` returns the transitive
    `Requirement`s like a wheel candidate.
  - The 9 T7 unit tests stay green; the one that expected
    `_SdistEncountered` is converted to assert the new behaviour
    (no exception, transitives returned via T_S2).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_S4: Remove Q-F top-level wheel pre-check (or repurpose)

- **depends_on**: `[T_S3]`
- **location**: `pipenv/resolver/backends/pure_python.py` (modify
  `resolve` step 2).
- **description**:
  Now that sdists work, the Q-F top-level wheel-availability
  pre-check is no longer a failure gate. Two options:
  - **A**: delete entirely.
  - **B**: repurpose for "no candidates at all for a top-level
    package" (e.g., typo / yanked-only / network blackout).
  Pick B — better UX. Rename internally to
  `_top_level_emptiness_pre_check` and update the error message
  to say "no candidates found" rather than "no wheel available".
- **validation**:
  - Top-level package with only sdists → resolves (no pre-check
    fire). T14's Q-F test is converted: pass a top-level package
    with ZERO candidates → still fails loud with the new message.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_S5: `_translate_mapping` collects all-distfile hashes

- **depends_on**: `[T_S4]`
- **location**: `pipenv/resolver/backends/pure_python.py` (extend
  `_translate_mapping`).
- **description**:
  Pip's lockfile convention: emit hashes for every distfile of the
  resolved version (wheel + sdist + any other wheel variants).
  Phase 3a emitted only the resolved candidate's single hash.
  Phase 3b:
  - For each resolved `(identifier, candidate)`, look up ALL
    candidates from the cache matching `(candidate.name,
    candidate.version)` across configured indexes.
  - Collect every `(algo, value)` hash from those candidates'
    `hashes` frozensets.
  - Emit as `tuple(sorted("<algo>:<value>"))` on the
    `LockedRequirement`.
  - Skip duplicates (the same wheel file may appear in multiple
    indexes' caches with the same hash).
- **validation**:
  - Candidate `click==8.3.3` cached with a wheel + an sdist; both
    appear in `LockedRequirement.hashes`.
  - Same candidate without a sibling sdist in the cache → only
    the wheel hash. Document this as the "we hash what we
    actually saw" semantic (vs pip's "we hash whatever the index
    advertises", which is the same thing in practice — the cache
    IS the index slice we've read).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_S6: Sdist + hashes integration tests

- **depends_on**: `[T_S5]`
- **location**:
  - `tests/unit/test_pure_python_sdist.py` (new)
  - `tests/unit/test_pure_python_backend.py` (extend)
- **description**:
  - Unit tests for `pure_python_sdist`: synthetic sdist build,
    cache round-trip, build-failure error path.
  - Backend tests: T_S5 hash-collection edge cases (single hash,
    multiple hashes, cross-index dedup).
  - Coverage gate stays ≥ 90 % on both modules.
- **validation**: tests pass; coverage gate maintained.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_CI1: CI matrix entry — `PIPENV_RESOLVER_BACKEND=pure-python`

- **depends_on**: `[T_M5, T_S6]`
- **location**: `.github/workflows/ci.yaml`
- **description**:
  Add a new matrix entry alongside the existing test job that runs
  the full pipenv test suite with the env var set:
  ```yaml
  - name: tests (pure-python backend)
    if: matrix.os == 'ubuntu-latest' && matrix.python-version == '3.12'
    continue-on-error: true
    env:
      PIPENV_RESOLVER_BACKEND: pure-python
    run: ... <existing test command> ...
  ```
  Confirm `PIPENV_RESOLVER_BACKEND` env var is honoured by the
  T_PLUMBING dispatcher; if not, add the env-var path (env >
  CLI > Pipfile > default).
  Start with `python-version == '3.12'` only to keep CI minutes
  reasonable; widen later.
- **validation**:
  - CI job appears in the workflow.
  - At least one PR push triggers the matrix entry and produces
    a result (pass or fail) — failure doesn't block merge.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T_CI2: Update design doc — Phase 3b acceptance gate

- **depends_on**: `[T_CI1]`
- **location**: `docs/dev/initiative-g-phase3-design.md` (extend
  §8 Acceptance Criteria).
- **description**:
  Add a Phase 3b row to the acceptance criteria table noting that
  the CI matrix is the new strong gate; lockfile byte-identity
  on the 100-pkg bench (T15) becomes a sub-criterion of "matrix
  passes". The Q-A decision flips from "fail loud" to "build
  transparently via PEP 517". Document the
  no-build-isolation tradeoff.
- **validation**:
  - Doc renders cleanly.
  - Phase 3b row added to acceptance matrix.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

## Parallel Execution Groups

| Wave | Tasks            | Can Start When           |
| ---- | ---------------- | ------------------------ |
| 1    | T_M1, T_S1       | Immediately              |
| 2    | T_M2, T_S2       | Wave 1 (per-track)       |
| 3    | T_M3, T_S3       | Wave 2 (per-track)       |
| 4    | T_M4, T_S4       | Wave 3 (per-track)       |
| 5    | T_M5, T_S5       | Wave 4 (per-track)       |
| 6    | T_S6             | T_S5 done                |
| 7    | T_CI1            | T_M5 + T_S6 done         |
| 8    | T_CI2            | T_CI1 done               |

Track 1 (markers) and track 2 (sdists) run in parallel for waves 1-5.

---

## Risks & Mitigations

| Risk | Mitigation |
| ---- | ---------- |
| PEP 517 builds blow up on packages with build-time deps not installed | T_S1 documents the no-build-isolation tradeoff. If a test suite package hits this, fix by pinning build-time deps in pyproject's `requires` (which we already trust the env to satisfy). Phase 3c can add isolation. |
| Marker-string canonicalisation differs from pip's exact format | T_M3 tests assert behaviour, not byte-for-byte string identity. T_PARITY_MATRIX records any format divergence we accept. |
| CI matrix surfaces 20+ failing tests in one go | `continue-on-error: true` is the safety net. Triage one at a time; each fix is its own commit. |
| T_S1 PEP 517 invocation deadlocks on some sdists (build backend never returns) | Wrap the hook call in `concurrent.futures` with a 5-minute timeout; failure surfaces as `SdistBuildError(timeout=...)`. |
| Removing Q-A fail-loud silently masks real failures | T_S4 keeps the "no candidates at all" pre-check so empty-cache cases still surface clearly. |

---

## Out of Scope (Phase 3b)

Explicitly **not** in Phase 3b:

- PEP 517 build isolation (Phase 3c if CI surfaces it).
- VCS sources (git/hg/svn URLs in Pipfile).
- File / path sources (`-e .`, local sdists).
- Editable installs (`-e <vcs>+<url>`).
- Cross-platform lockfiles.
- Promoting the CI matrix to required (separate PR after green).

If the CI matrix run surfaces a test that needs one of these, log
it as a known-gap in T_PARITY_MATRIX and skip the affected test
under `PIPENV_RESOLVER_BACKEND=pure-python` rather than expanding
Phase 3b scope.

---
