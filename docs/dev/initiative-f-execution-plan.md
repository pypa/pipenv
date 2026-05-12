# Plan: T_F.3 — Execute the Typed Resolver Subprocess Schema

**Generated**: 2026-05-12
**Source design**: [`initiative-f-typed-design.md`](./initiative-f-typed-design.md)
**Companion reference**: [`initiative-f-protocol.md`](./initiative-f-protocol.md) (current ad-hoc protocol catalogue)
**Target branch**: `maintenance/code-cleanup-phase2-2026-05` (same branch as T_D.4/T_E.3; **single atomic PR** for the whole T_F.3 scope per maintainer answer 2026-05-12)

---

## Overview

Execute the typed `ResolverRequest` / `ResolverResponse` migration designed in T_F.2. One atomic rewrite of the pipenv ↔ `pipenv-resolver` subprocess wire format:

- Introduce `pipenv/resolver/schema.py` with the stdlib `@dataclass` envelope + discriminated `ResolverResult`
- Convert `pipenv/resolver.py` (single file) into `pipenv/resolver/` (package): `__init__.py` + `main.py`
- Subprocess entry consumes `--request-file <path>` only (drops all other argv + three env-var hops)
- Single canonical `LockedRequirement.from_install_requirement(...)` formatter replaces **both** `Entry.get_cleaned_dict` and `format_requirement_for_lockfile`
- `prepare_lockfile` consumes typed `LockedRequirement` via `to_lockfile_dict()` adapter
- New unit-suite for the schema dataclasses; new integration test pinning the JSON wire shape; comma-in-marker regression fixture

No backwards-compat shim. No external-API guarantees (CLI is the contract). Subprocess and parent ship together; protocol-version negotiation is unnecessary.

## Prerequisites

This plan assumes the §8 Q1–Q10 recommendations in the design doc are accepted (maintainer stated "we agree with the ideas/discussions" on 2026-05-12). Specifically:

- **Q1**: Schema home = `pipenv/resolver/schema.py` (package layout). Reserves `pipenv/resolver/backends/` for future pluggability (§6a).
- **Q2**: Schema-version mismatch = structured `InternalError` written to response file AND non-zero exit.
- **Q3**: `LockedRequirement.to_lockfile_dict()` returns plain dict (no Plette in schema module).
- **Q4**: Ship a one-line `news/T_F.3.behavior.rst` fragment ("Resolver subprocess now produces structured error messages on dependency conflicts").
- **Q5**: `no_binary` is a first-class field on `LockedRequirement`.
- **Q6**: T_F.3 does NOT fold the in-process branch (deferred to T_F.4).
- **Q7**: Add the comma-in-marker fixture and regression test (PEP 508 markers with internal commas).
- **Q8**: Schema versioning policy = non-breaking additive default; only field rename / semantics change bumps `SCHEMA_VERSION`.
- **Q9**: `Diagnostics.resolver_log` is reserved-but-empty in T_F.3 — stderr stays the user-facing channel.
- **Q10**: Two tempfiles (`--request-file` + `--response-file`), no consolidation.

**If any recommendation is overridden the plan needs revision** — affected tasks are flagged below.

## Dependency Graph

```
Wave A (parallel, foundation):
  A1 ──────────────┐
  A2 ──────────────┤
                   │
Wave B (parallel, depend on Wave A):
                   ├─→ B1 (subprocess rewrite) ──┐
                   ├─→ B2 (parent rewrite)      ─┤
                   └─→ B3 (lockfile writer)     ─┤
                                                 │
Wave C (parallel, depend on Wave B):             │
                                                 ├─→ C1 (schema unit tests)
                                                 ├─→ C2 (JSON wire-shape integ test)
                                                 ├─→ C3 (comma-in-marker fixture)
                                                 └─→ C4 (news fragment)
                                                                          │
Wave D (depends on Wave C):                                               │
                                                                          └─→ D1 (mark T_F.3 complete in plan)
```

## Tasks

### A1: Schema dataclasses + canonical formatter + golden-output snapshots

- **depends_on**: []
- **location**:
  - **NEW** `pipenv/resolver/schema.py` — all dataclasses from design §3 (`ResolverRequest`, `ResolverResponse`, `ResolverSuccess`, `ResolutionError`, `InternalError`, `LockedRequirement`, `VCSPin`, `PackageSpecs`, `Source`, `ResolverOptions`, `ResolvedDeps`, `RequestMetadata`, `ConflictRecord`, `Diagnostics`) + `SCHEMA_VERSION = 1` module-level constant
  - The single canonical formatter `LockedRequirement.from_install_requirement(req, *, sources_lookup, markers_lookup, pipfile_entry, hashes) -> LockedRequirement` (design §3.3 + §6). Absorbs the richer behaviour from `format_requirement_for_lockfile` (file/path Pipfile-override, direct-URL handling, `no_binary` propagation, `merge_markers`, index lookup) and the `_clean_version` / `_clean_markers` logic from `Entry`.
  - **NEW** `tests/unit/fixtures/resolver_schema/` directory containing committed golden JSON snapshots produced by running today's `Entry.get_cleaned_dict` AND today's `format_requirement_for_lockfile` on a parameterised set of `InstallRequirement` inputs (PyPI / VCS git+hg+svn+bzr / file:// / path / editable / extras / markers / `no_binary`). The snapshots are the regression depth that `tests/unit/test_utils.py:1323-1538`'s 17 cases currently provide; after B3 deletes `format_requirement_for_lockfile`, these snapshots become C1's parity gate. Generate them while both old formatters still exist.
- **description**:
  Plain stdlib `@dataclass(frozen=True)`. Manual `to_json_dict()` / `from_json_dict()` classmethods (no `dataclasses.asdict` — it doesn't handle the discriminated union pattern). `LockedRequirement.__post_init__` enforces the mutual-exclusion invariants (no version-and-vcs both; at least one of {version, vcs, file, path}). `to_json_dict` MUST be deterministic — sorted dict keys, sorted hashes, no None-valued keys on the wire (so the JSON matches today's pruned-dict shape).

  `from_install_requirement` is the single hardest piece. It reads from a pip `InstallRequirement` plus the maps the caller maintains. Pull behaviour from these existing locations (cite line numbers in the docstring so future readers can diff):
  - `pipenv/resolver.py:213-245` — `_clean_version` / `_clean_markers` from `Entry`
  - `pipenv/resolver.py:288-320` — `Entry.get_cleaned_dict` shape
  - `pipenv/utils/locking.py:46-160` — `format_requirement_for_lockfile` (the richer one)
  - `pipenv/utils/locking.py:121-131` — `merge_markers` handling
  - `pipenv/utils/locking.py:142-154` — file/path Pipfile-override semantics
  - `pipenv/utils/locking.py:156-157` — `no_binary` propagation
- **validation**:
  - `python -c "from pipenv.resolver.schema import ResolverRequest, ResolverResponse, LockedRequirement, SCHEMA_VERSION; assert SCHEMA_VERSION == 1"` passes
  - `python -c "from pipenv.resolver.schema import LockedRequirement; LockedRequirement(name='foo')"` raises `ValueError` (post-init invariant fires)
  - Schema module **does not import pip-internal types in module-level namespace** — only inside `from_install_requirement` body. Verify with `grep -n "from pipenv.patched" pipenv/resolver/schema.py` returning zero hits OR only inside function bodies.
- **status**: Completed
- **log**:
  - 2026-05-12 — `85993ca4` `feat(resolver): introduce typed schema module + canonical LockedRequirement formatter + golden fixtures`. RED→GREEN cycle: 17 unit tests in `TestLockedRequirementInvariants` + `TestEnvelopeRoundtrip` failed with `ModuleNotFoundError` before `schema.py` landed, all 17 pass after. Full unit suite 694 passed / 9 skipped (was 677 / 9 prior). Acceptance grep gates clean (zero `pipenv.patched` top-level imports; zero `typing.Self` / `tomllib`). 27 golden JSON snapshots committed under `tests/unit/fixtures/resolver_schema/`.
  - **Boundary-crossing note**: A1's deliverable location `pipenv/resolver/schema.py` requires `pipenv/resolver/` to exist as a package, which Python's import system makes mutually exclusive with the historical `pipenv/resolver.py` file (the package directory shadows the .py module). A1 therefore moved `pipenv/resolver.py` → `pipenv/resolver/main.py` and added a re-exporting `__init__.py` for `Entry`, `PackageRequirement`, `PackageSource`, `_main`, `main`, `process_resolver_results`, `resolve_packages`, `which`. The three test modules at `tests/unit/test_dependencies.py`, `tests/unit/test_resolver_regressions.py`, `tests/unit/test_locking_no_mutation.py` continue to import these names through the shim. `pyproject.toml`'s console-script `pipenv.resolver:main` still resolves correctly. A2's remaining scope is therefore reduced — see A2's log when it lands.
- **files edited/created**:
  - **CREATED** `pipenv/resolver/__init__.py` — package + re-export shim
  - **CREATED** `pipenv/resolver/schema.py` — typed dataclass envelope (14 dataclasses + `SCHEMA_VERSION`)
  - **MOVED** `pipenv/resolver.py` → `pipenv/resolver/main.py` (necessity, see boundary-crossing note above)
  - **CREATED** `tests/unit/test_resolver_schema.py` — 17 tests covering invariants + envelope round-trip
  - **CREATED** `tests/unit/fixtures/resolver_schema/format_requirement_for_lockfile/*.json` — 16 golden snapshots
  - **CREATED** `tests/unit/fixtures/resolver_schema/entry_get_cleaned_dict/*.json` — 11 golden snapshots

### A2: Convert `pipenv/resolver.py` → `pipenv/resolver/` package (pure restructure, NO behavior change)

- **depends_on**: [A1] (A1 must commit its golden-fixture snapshots BEFORE A2 moves the file, because the snapshot generator runs against today's symbols at today's import path)
- **location**:
  - **MOVE** `pipenv/resolver.py` → `pipenv/resolver/main.py` (full content, no logic change)
  - **NEW** `pipenv/resolver/__init__.py` — re-exports current public names (`main`, `_main`, `Entry`, `PackageRequirement`, `resolve_packages`, `process_resolver_results`) so existing imports keep working through Wave B. These re-exports come out in B1 when the symbols are deleted.
  - **EDIT** `pyproject.toml` line 63: `scripts.pipenv-resolver = "pipenv.resolver:main"` → `"pipenv.resolver.main:main"`
  - **EDIT** `tests/unit/test_dependencies.py:9`, `tests/unit/test_resolver_regressions.py:358`, `tests/unit/test_locking_no_mutation.py:93` to rely on the new package layout via the temporary re-exports (path stays `pipenv.resolver.X` — the re-export keeps the import working until B1 takes the symbol away)
- **description**:
  Pure code-move + console-script entry update. Zero behavior change. Lands as one commit so the diff is reviewable as "file moved, console-script entry updated, three test imports unchanged via re-export, nothing else."

  **Dev-environment note**: changing `pyproject.toml`'s console-script entry requires `pip install -e . --force-reinstall` (or equivalent re-link) in any pipenv-development checkout so `pipenv-resolver` on `$PATH` resolves to the new entry point. Without this the subprocess invocation in B2's smoke test will still hit the old file path (which won't exist) and fail mysteriously. Call this out in the commit message AND in the PR description so reviewers don't trip on it.

  After this task the test suite must pass without changing any other code under `pipenv/`. If a test fails after A2, the move broke something — diagnose and fix (likely a circular import via `__init__.py` re-exports).
- **validation**:
  - `python -m pytest tests/unit/ -q` green
  - `python -c "from pipenv.resolver import main; assert callable(main)"` passes
  - `pipenv-resolver --help` (or equivalent invocation) still works after `pip install -e . --force-reinstall`
  - `git diff` shows the move + the pyproject.toml line + the three test imports (only) and nothing else
- **status**: Not Completed
- **log**:
- **files edited/created**:

### B1: Subprocess entry rewrite — read `--request-file`, write `--response-file`; delete dead symbols + dead test imports

- **depends_on**: [A1, A2]
- **location**:
  - `pipenv/resolver/main.py` (the renamed entry point)
  - `pipenv/resolver/__init__.py` (prune the temporary A2 re-exports of deleted symbols)
  - `tests/unit/test_dependencies.py` (line 9 imports `Entry` — delete the test, or rewrite to use `LockedRequirement`)
  - `tests/unit/test_resolver_regressions.py` (line 358 imports `process_resolver_results` — same, delete or rewrite against the new typed pipeline)
  - `tests/unit/test_locking_no_mutation.py` (line 93 mocks `pipenv.resolver.resolve_packages` — verify the signature change does not break the mock; update if it does)
- **description**:
  Rewrite `main()` / `_main()` / `resolve_packages()` / `process_resolver_results()` so the subprocess:
  1. Accepts ONLY `--request-file <path>` and `--response-file <path>` (drop `--pre`, `--clear`, `--system`, `--verbose`, `--category`, `--constraints-file`, `--resolved-default-deps-file`, `--parse-only`, `--pipenv-site`, positional `packages`, the `which()` stub at lines 90-91).
  2. Reads + validates the JSON `ResolverRequest`; on `schema_version != SCHEMA_VERSION`, writes a `ResolverResponse(result=InternalError(message="schema version mismatch: parent sent N, child expects M"))` and exits non-zero (per Q2).
  3. Uses `request.python_marker_override` directly (drops the `PIPENV_RESOLVER_PYTHON_VERSION` env-var hop).
  4. Uses `request.sources` directly (drops the in-child Pipfile re-read at `resolver.py:448-453` and the duplicate mirror substitution at lines 436-453).
  5. Uses `request.extra_pip_args` directly (drops the `PIPENV_EXTRA_PIP_ARGS` env-var hop).
  6. Builds `LockedRequirement` instances via `LockedRequirement.from_install_requirement(...)` (no more `Entry.get_cleaned_dict`).
  7. Wraps the result in `ResolverResponse(schema_version=SCHEMA_VERSION, result=ResolverSuccess(...))` on success, or `ResolverResponse(..., result=ResolutionError(...))` on dependency conflict. **Both paths exit 0** — non-zero exit is reserved for genuine crashes.
  8. On uncaught exception: best-effort write a `ResolverResponse(..., result=InternalError(message=str(e), traceback=...))` to `--response-file`, then exit non-zero.
  9. Stderr free-text continues to flow (Q9 — `_is_download_status_line` pattern preserved on the parent side).

  Drop the re-exports added in A2 from `pipenv/resolver/__init__.py` IF the test files have been migrated to import from `pipenv.resolver.main`; otherwise keep them only for the symbols still imported by tests.

  `Entry` and `PackageRequirement` classes can be **deleted** from `main.py` after this rewrite — `LockedRequirement` and the `from_install_requirement` path replace them.
- **validation**:
  - `python -m pytest tests/unit/ -q` green
  - The subprocess invoked with `--request-file /tmp/x.json --response-file /tmp/y.json` against a hand-built fixture request produces a valid `ResolverResponse` JSON
  - Schema-version mismatch path (request file with `schema_version: 999`) produces structured `InternalError` response AND non-zero exit
  - `grep -nE -- "--parse-only|--pipenv-site|--constraints-file|--resolved-default-deps-file|--category" pipenv/resolver/main.py` returns zero hits
  - `grep -nE "PIPENV_RESOLVER_PYTHON_VERSION|PIPENV_EXTRA_PIP_ARGS|PIPENV_SITE_DIR" pipenv/resolver/main.py` returns zero hits
- **status**: Not Completed
- **log**:
- **files edited/created**:

### B2: Parent-side rewrite — `pipenv/utils/resolver.py :: venv_resolve_deps` + `resolve` + in-process branch

- **depends_on**: [A1, A2]
- **location**:
  - `pipenv/utils/resolver.py` (lines ~1180 `venv_resolve_deps`, ~1282 `resolve`, ~1431 `PIPENV_RESOLVER_PARENT_PYTHON` in-process branch, and `actually_resolve_deps` callers at lines ~1581 / ~1610 — all touched in a single commit so the file-level diff is internally consistent)
- **description**:
  Build a `ResolverRequest` instead of an argv list + multiple tempfiles. Serialize to ONE `--request-file` tempfile (Q10 — two tempfiles, request stays readable post-mortem). Invoke the subprocess with only `--request-file <p> --response-file <q>`. Parse the response JSON, dispatch on `response.result.kind`:
  - `success` → unwrap `LockedRequirement` instances; existing downstream code at `pipenv/utils/locking.py :: prepare_lockfile` consumes them (see B3).
  - `resolution_error` → raise `ResolutionFailure` with `pip_message` as the user-facing text + `conflicts` as structured detail. Existing `ResolutionFailure`-aware code path stays.
  - `internal_error` → raise the same crash-path exception as today's non-zero-exit handling.
  - Non-zero exit without a response file → unchanged stderr-fallback path (true subprocess crash; the structured response was never written).

  Drop the env-var setup hops for `PIPENV_RESOLVER_PYTHON_VERSION`, `PIPENV_EXTRA_PIP_ARGS`, `PIPENV_SITE_DIR` from the parent. The pip-config family (`PIP_*`), `NETRC`, `PYTHONIOENCODING`, `PYTHONUNBUFFERED`, `PIPENV_PYPI_MIRROR` continue to be inherited via `os.environ.copy()` because pip-internal code reads them directly.

  `_is_download_status_line` filter at `pipenv/utils/resolver.py:1159-1177` stays — stderr is still the user-facing log channel.

  **In-process branch migration**: the `PIPENV_RESOLVER_PARENT_PYTHON=1` debug bypass at `pipenv/utils/resolver.py:1431` calls `actually_resolve_deps` directly in the parent interpreter. Per Q6 the *fold* between the two branches is deferred to T_F.4, but the *type migration* must happen here: after B1 changes `resolve_packages` to return typed `LockedRequirement` instances, the in-process call site must consume them the same way the subprocess parse-step does. B2 owns this migration entirely (not B1) so there is no file collision on `pipenv/utils/resolver.py` between the two tasks.
- **validation**:
  - `python -m pytest tests/unit/ -q` green
  - `python -m pytest tests/integration/ -q -k "lock or install"` smoke-passes a representative subset (full integration suite is the wave-D gate)
  - Manual: `pipenv lock` on a tiny test Pipfile produces a valid lockfile (no crash, no malformed JSON)
  - Manual with `PIPENV_RESOLVER_PARENT_PYTHON=1`: same `pipenv lock` produces an identical lockfile via the in-process branch
  - `grep -nE "PIPENV_RESOLVER_PYTHON_VERSION|PIPENV_EXTRA_PIP_ARGS|PIPENV_SITE_DIR" pipenv/utils/resolver.py` returns zero hits
- **status**: Not Completed
- **log**:
- **files edited/created**:

### B3: Lockfile writer consumes `LockedRequirement`; delete old formatters; port test coverage

- **depends_on**: [A1, A2]
- **location**:
  - `pipenv/utils/locking.py` (delete `format_requirement_for_lockfile` at lines 46-160; update `prepare_lockfile` at line ~195 to consume `LockedRequirement`)
  - `pipenv/resolver/main.py` (delete `Entry.get_cleaned_dict` if not already removed in B1 — should be removed there; this task verifies the deletion)
  - `tests/unit/test_utils.py` — 17 test cases at lines ~1323-1538 pin `format_requirement_for_lockfile` behaviour. **Port every case** to either (a) call `LockedRequirement.from_install_requirement` directly and assert on the resulting dataclass, or (b) move into the C1 parameterised fixture set against the A1 golden JSON snapshots. **Coverage depth must not regress**; this is a hard requirement, not a nice-to-have.
  - `tests/unit/test_core.py:533` — comment/docstring reference to `format_requirement_for_lockfile`; clean up.
- **description**:
  `prepare_lockfile` takes the `Sequence[LockedRequirement]` produced by the subprocess (via B2's parse step) and emits the TOML-ready dict the lockfile writer expects. The conversion is `LockedRequirement.to_lockfile_dict()` (plain dict per Q3 — no Plette imports in the schema module).

  After this lands, neither `Entry.get_cleaned_dict` nor `format_requirement_for_lockfile` exists in the tree. Both are replaced by `LockedRequirement.from_install_requirement` (constructor, A1) + `LockedRequirement.to_lockfile_dict` (sink, here).

  **Test-coverage porting is part of this task** (NOT C1) so the deletion + the equivalent coverage land in the same commit. The 17 `test_utils.py` cases pin behaviours like file/path Pipfile-override, marker merging, `no_binary` propagation, VCS ref normalization — every one of those behaviours must have at least one explicit assertion in the new world before the deletion.
- **validation**:
  - `grep -n "def format_requirement_for_lockfile\|def get_cleaned_dict" pipenv/` returns zero hits
  - All `format_requirement_for_lockfile` callers either go through `prepare_lockfile` or have been migrated to use `LockedRequirement.to_lockfile_dict()` directly
  - `tests/unit/test_utils.py` no longer references `format_requirement_for_lockfile`
  - Behavioural coverage count: `grep -c "format_requirement_for_lockfile" tests/` was 17 before the task; the equivalent count of `LockedRequirement` / `from_install_requirement` test cases is ≥ 17 after (i.e. coverage did not shrink)
  - `python -m pytest tests/unit/ -q` green
- **status**: Not Completed
- **log**:
- **files edited/created**:

### C1: Schema-dataclass unit tests

- **depends_on**: [B1, B2, B3]
- **location**:
  - **NEW** `tests/unit/test_resolver_schema.py`
- **description**:
  Cover every dataclass-level invariant and round-trip:
  - `LockedRequirement.__post_init__` rejects (a) no version+vcs+file+path; (b) version-and-vcs both present.
  - `LockedRequirement.from_install_requirement` produces the same wire shape today's `Entry.get_cleaned_dict` produced, on a parameterised set of fixture `InstallRequirement` objects (PyPI, VCS git/hg/svn/bzr, file://, path, editable, with/without extras, with/without markers, with `no_binary`).
  - Same fixture set ALSO checks that today's `format_requirement_for_lockfile` output would match — but since that function is deleted in B3, this assertion is *historical*: pin against committed expected-output JSON instead.
  - `ResolverRequest.to_json_dict` / `from_json_dict` round-trip is lossless for every combination of optional fields.
  - `ResolverResponse.from_json_dict` dispatches correctly for each `result.kind ∈ {success, resolution_error, internal_error}`; unknown `kind` raises a typed error.
  - Schema-version mismatch at `from_json_dict` parse time raises with a clear message.
- **validation**:
  - `python -m pytest tests/unit/test_resolver_schema.py -v` shows ≥ 20 tests, all green
- **status**: Not Completed
- **log**:
- **files edited/created**:

### C2: JSON wire-shape integration test

- **depends_on**: [B1, B2, B3]
- **location**:
  - **NEW** `tests/integration/test_resolver_protocol.py`
  - **NEW** `tests/integration/fixtures/resolver_protocol/` (request + response golden JSON files)
- **description**:
  Run an actual `pipenv lock` against a tiny committed Pipfile (3-4 packages: one PyPI, one with markers, one with extras). Patch the subprocess invocation to copy `--request-file` and `--response-file` to a fixture-comparison location before tempfile cleanup. Snapshot-diff each against committed golden JSON.

  This is the wire-shape canary. Any PR that changes a field name without bumping `SCHEMA_VERSION` will fail this test.

  **Fixture-regen mechanism is part of this task's scope** — implement the regen branch explicitly, do not assume it already exists. Sketch:

  ```python
  def test_resolver_protocol_lock_smoke(tmp_path):
      request_path, response_path = _run_pipenv_lock_capturing_tempfiles(...)
      actual_request = json.loads(request_path.read_text())
      actual_response = json.loads(response_path.read_text())
      if os.environ.get("PIPENV_REGEN_PROTOCOL_FIXTURES"):
          GOLDEN_REQUEST.write_text(json.dumps(actual_request, indent=2, sort_keys=True))
          GOLDEN_RESPONSE.write_text(json.dumps(actual_response, indent=2, sort_keys=True))
          pytest.skip("fixtures regenerated; rerun without env var to assert")
      assert actual_request == json.loads(GOLDEN_REQUEST.read_text())
      assert actual_response == json.loads(GOLDEN_RESPONSE.read_text())
  ```

  Fixture-update workflow: when a deliberate schema change lands, the maintainer regenerates the golden by running `PIPENV_REGEN_PROTOCOL_FIXTURES=1 pytest tests/integration/test_resolver_protocol.py`, reviews the resulting `git diff` on the fixture files, and commits both the code change and the fixture update together.
- **validation**:
  - Test passes green against committed fixtures
  - Test fails (with a readable diff) if `LockedRequirement` field names are renamed without a `SCHEMA_VERSION` bump
  - Fixture-regen flag works end-to-end
- **status**: Not Completed
- **log**:
- **files edited/created**:

### C3: Comma-in-marker regression fixture

- **depends_on**: [B1, B2, B3]
- **location**:
  - Add a fixture + test case to `tests/unit/test_resolver_schema.py` (the C1 file)
- **description**:
  Per Q7: today's constraints-file parser uses `str.split(",", 1)` to separate name from pip-line (F.1 §8 row 9). PEP 508 markers can contain commas (e.g. `'python_version >= "3.10", sys_platform == "linux"'`), which currently breaks the parser. The typed-schema replacement uses `PackageSpecs.specs: dict[str, str]` so commas are no longer a parser concern — but the regression test pins this so the bug can't sneak back if anyone ever refactors `PackageSpecs` to line-based parsing.

  Fixture: `ResolverRequest` with one package whose pip-line includes a comma-bearing marker. Assert the round-trip preserves it byte-for-byte.
- **validation**:
  - The test exists and passes
- **status**: Not Completed
- **log**:
- **files edited/created**:

### C4: News fragment

- **depends_on**: [B1, B2, B3]
- **location**:
  - **NEW** `news/T_F.3.behavior.rst`
- **description**:
  Per Q4. One-line news fragment in the `.behavior.rst` category:

  ```rst
  Resolver subprocess now produces structured error messages on
  dependency conflicts, surfacing the conflicting packages and the
  specific requirements that cause the conflict.
  ```

  The internal protocol rewrite itself is invisible to users; the user-facing diff is the cleaner error message on `pipenv install` / `pipenv lock` failure.
- **validation**:
  - File present, valid RST, towncrier pre-commit hook accepts it
- **status**: Not Completed
- **log**:
- **files edited/created**:

### D1: Mark T_F.3 complete in modernization plan

- **depends_on**: [C1, C2, C3, C4]
- **location**:
  - `docs/dev/modernization-plan.md` (add a T_F.3 task entry mirroring the T_F.1/T_F.2 entries' shape; no dependency-row edits — the wave table at the bottom of the plan does not list T_F.3 yet, so the addition is purely additive)
- **description**:
  Add the T_F.3 entry: status Completed, log lists every commit hash from waves A–C, files edited/created enumerates the full diff surface. Append a "T_F.4 still pending" note pointing at the design doc §4 step 6 ("the in-process branch fold").

  **No other plan-doc edits in T_F.3** — this is the one and only writer of `docs/dev/modernization-plan.md` for the whole initiative. No other task in this plan touches that file, so no parallel-collision risk.
- **validation**:
  - Plan diff shows only the T_F.3 entry addition + a status flip
- **status**: Not Completed
- **log**:
- **files edited/created**:

## Parallel Execution Groups

| Wave | Tasks | Can Start When | Notes |
|------|-------|----------------|-------|
| A | A1, then A2 | Immediately for A1; A2 after A1 commits golden fixtures | **A1 must commit golden JSON snapshots BEFORE A2 moves the file**, because the snapshot generator runs against today's `Entry.get_cleaned_dict` and `format_requirement_for_lockfile` at today's import paths. A1 commits the snapshots in a single commit; A2 then proceeds with the file move + console-script update + import re-export setup. A1 and A2 are therefore *strictly serial*, not parallel. |
| B | B1, B2, B3 | Wave A complete | Disjoint files: B1 owns `pipenv/resolver/main.py` + the three Entry/process_resolver_results-importing test files; B2 owns `pipenv/utils/resolver.py` (including the in-process branch); B3 owns `pipenv/utils/locking.py` + `tests/unit/test_utils.py` (17 test-case port). They communicate through the typed schema from A1 + the response-file shape both write/read. **Wire-shape coordination point**: B1 and B2 must agree on the JSON layout — that's locked in by A1's `to_json_dict` / `from_json_dict` methods. If anything ambiguous in A1 surfaces during B execution, fix A1 first then resume B. **Single-atomic-PR ordering note**: between any two intermediate Wave-B commits the subprocess wire shape may be temporarily inconsistent (e.g. parent has flipped to `--request-file` while subprocess still reads old argv, or vice versa). The PR is reviewable + green at the TIP, not at every intermediate commit. This is acceptable per the maintainer's "single atomic PR" decision; CI runs only at PR tip and merge. |
| C | C1, C2, C3, C4 | Wave B complete | All test/doc adds. Fully disjoint. |
| D | D1 | Wave C complete | Single plan-bump commit; sole writer of modernization-plan.md across the whole T_F.3 scope. |

**Maximum concurrent agents:** 3 (in Wave B). 1 in Wave A (A1 then A2 serial). 4 in Wave C.

## Testing Strategy

- **Per-task gate** (each agent): `python -m pytest tests/unit/ -q` green before commit.
- **Wave-B gate**: `python -m pytest tests/integration -q -k "lock or install or sync"` green (subset; the full integration suite runs in CI).
- **Wave-C gate**: full unit suite + the new `test_resolver_schema.py` + `test_resolver_protocol.py` green.
- **PR gate** (CI): full unit + integration suite green on Linux/macOS/Windows × Python 3.10–3.14.
- **Wave-D gate** (maintainer-side): manual smoke `pipenv install requests` + `pipenv lock` + `pipenv install -e git+https://github.com/foo/bar.git@v1` to verify the structured-error path on a deliberately-broken-resolve.

## Risks & Mitigations

1. **`LockedRequirement.from_install_requirement` divergence from current behaviour.** The richer `format_requirement_for_lockfile` and the simpler `Entry.get_cleaned_dict` produce slightly different shapes today (the divergence cases are flagged in F.1 §8 row 4). The unified constructor must absorb the union, not the intersection.
   **Mitigation**: C1's parameterised fixture set includes one case per divergence point. If a test fails, the constructor is missing a branch from one of the two source functions.

2. **JSON wire-shape regression that the canary misses.** A renamed field with the same string value at one fixture point would still pass C2. Field-name discipline depends on developer attention, not the test.
   **Mitigation**: C1 unit-tests for the round-trip cover the *type* level; C2 covers the *fixture* level. The two together close most gaps. `SCHEMA_VERSION` bumping policy (Q8) is the third line of defence.

3. **Console-script entry breakage on packaged install.** `pyproject.toml` change in A2 only takes effect after `pip install -e .` is rerun.
   **Mitigation**: A2's validation step includes `pipenv-resolver --help`. If that fails because the entry-point cache is stale, `pip install -e . --force-reinstall` is the recovery command — call it out in A2's log entry.

4. **In-process branch breaks because `Entry` is gone.** The in-process branch at `pipenv/utils/resolver.py :: actually_resolve_deps` (F.1 §7) currently constructs `Entry` instances. After B1 deletes `Entry`, that branch must instead construct `LockedRequirement` via the same constructor.
   **Mitigation**: B1 is responsible for updating both branches. The in-process branch is NOT folded (Q6) but it MUST be migrated to the new types. If B1 misses this, B2's parent-side rewrite will surface it (the parent calls into the in-process branch directly).

5. **Parallel-agent collisions on shared callers.** B1 touches `pipenv/resolver/main.py`; B2 and B3 do not. B2 touches `pipenv/utils/resolver.py`; B1 and B3 do not. B3 touches `pipenv/utils/locking.py`; B1 and B2 do not. So in principle no file-level collision. But all three import from `pipenv/resolver/schema.py` (A1's output) — if A1 needs amendment mid-wave-B, coordinate the amendment as a single commit visible to all three.
   **Mitigation**: The standard parallel-agent rules apply (no `git stash`; explicit `git commit -- <files>`).

6. **Schema-version mismatch test path requires writing the response file even on schema rejection** — the subprocess must construct an `InternalError` response before the schema-version check completes successfully (per Q2). Care: `schema_version` is the *first* field on the envelope precisely so a partial parse can still detect mismatch and produce a structured rejection.
   **Mitigation**: B1's task description spells out the two-stage parse (read `schema_version` first, then conditionally parse the rest). A1's `from_json_dict` should expose this two-stage option.

7. **Behaviour drift between subprocess and in-process branches** during the wave-B work. The in-process branch shares `resolve_packages()` with the subprocess; if B1's rewrite of `resolve_packages` regresses the in-process call site, B2's parent-side smoke tests catch it.
   **Mitigation**: B2's validation explicitly includes a small `pipenv lock` smoke, which exercises both branches depending on `PIPENV_RESOLVER_PARENT_PYTHON`.

8. **Test-coverage regression from deleting `format_requirement_for_lockfile`'s 17 pinning cases.** `tests/unit/test_utils.py:1323-1538` is the single largest behavioural coverage block for the lockfile-entry shape. If B3 deletes those cases without porting equivalent coverage to `LockedRequirement.from_install_requirement`, the typed-schema regression net is thinner than today's untyped one — exactly the wrong direction.
   **Mitigation**: B3's task description treats the test port as part of the deletion commit (single atomic change: delete + port). Validation step explicitly counts behavioural test-cases-before vs after; the count must not drop. The A1 golden snapshots serve as a parity gate for the trickier cases (file/path Pipfile-override, marker merging, `no_binary` propagation).

9. **Target-Python compatibility of the schema module.** Per design §3.6, `pipenv/resolver/schema.py` runs inside the *target* venv's Python — typically the minimum pipenv supports (currently CPython 3.10) through the latest — not the parent pipenv's Python. A1 must use only stdlib idioms that work back to that minimum: `@dataclass(frozen=True)` ✓, `from __future__ import annotations` ✓, `Optional`/`Sequence`/`Mapping` from `typing` ✓. **Disallowed at module top level**: `typing.Self` (3.11+), `tomllib` (3.11+; pipenv already conditionally imports it), exhaustive `match` patterns that depend on 3.11+ semantics, ANY new vendored dependency, ANY `from pipenv.patched.pip._internal` import. Pip-internal types are accepted only inside the body of `LockedRequirement.from_install_requirement` because the subprocess is the only caller that has the patched-pip path available.
   **Mitigation**: A1's validation adds `python3.10 -c "from pipenv.resolver.schema import *"` (if 3.10 is available locally) and `grep -n "^from pipenv.patched\\|^import pipenv.patched" pipenv/resolver/schema.py` must return zero hits. CI's Python-version matrix (3.10–3.14) is the integration gate.

## What this plan deliberately does NOT cover

- **T_F.4** — fold the in-process and subprocess branches into a single implementation (PRD-stated acceptance: "one resolver implementation, two thin adapters"). Per Q6 this is the next task in line, not this one.
- **Wall-clock timeout enforcement** — `RequestMetadata.deadline_seconds` exists on the wire, but T_F.3 does not enforce it. A follow-up small PR adds `c.wait(timeout=...)` with its own news fragment because the behaviour change (hanging installs start dying) is user-visible.
- **`Diagnostics.resolver_log` population** — reserved field, empty tuple in T_F.3 per Q9. A future PR may start populating it if a structured-log use case materialises.
- **Pluggable resolver backends** — the design's §6a discusses future pluggability for uv etc. T_F.3 stays strictly pip-only; the schema is shaped to preserve the option but does not introduce a `Backend` ABC.

---

*Source design under `docs/dev/initiative-f-typed-design.md`. Updates to this plan or to the design should be made in lock-step.*
