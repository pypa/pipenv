# Plan: Pipenv Codebase Modernization

**Generated**: 2026-05-12
**Input**: `docs/dev/modernization-prd.md`
**Branch base**: `maintenance/code-cleanup-2026-05` (cut from `main`)

## Overview

This plan operationalizes the six initiatives in the modernization PRD as
discrete, swarm-executable tasks. Per the scoping decision:

- **Wave 1 + Wave 2 are planned at PR-granularity** (Initiatives A, B, C).
  These are concrete enough for parallel agent execution today.
- **Wave 3 + Wave 4 are scaffolded only** (Initiatives D, E, F). Each has
  a small set of seed tasks; the full plan for these is regenerated after
  Wave 1+2 lands and the codebase shape is known.

Per the autonomy decision: agents run `pytest` and create commits on the
shared branch. Matt reviews on-branch and merges to `main` when satisfied.
No agent force-pushes, no agent merges to `main`, no agent touches
`patched/` or `vendor/`.

Two PRD corrections were uncovered during ground-truth verification and are
encoded as T0 tasks below:

1. Initiative C describes a `state` dict that does not exist; the actual
   pattern is wide individual parameter lists threaded through routines.
2. `markers.py` is described in Initiative B as inlined former vendor; it
   is actually project-owned glue and should be removed from the triage
   set.

## Prerequisites

- Branch `maintenance/code-cleanup-2026-05` exists locally (already cut).
- `python -m pytest tests/unit` passes on the branch tip (verified
  2026-05-12 in this session: 483 passed, 9 skipped).
- Agents may use `python -m pytest tests/unit` and (where feasible)
  `tests/integration` subsets. Agents do **not** run the full integration
  suite — it requires network access and live PyPI mirrors; that gate is
  CI's job after PR push.
- Agents do not modify anything under `pipenv/patched/` or
  `pipenv/vendor/`.
- Agents commit with a `Co-Authored-By` trailer naming the agent and never
  force-push.

## Dependency Graph

```
T0.1 ── T0.2 (PRD corrections folded in here + agent ops doc)
   │
   ├── Initiative A: T_A.1 ── T_A.2 ── T_A.3 ──[release cut]── T_A.4
   │
   ├── Initiative B: T_B.1 ─┐
   │                  T_B.2 ─┤
   │                  T_B.3 ─┼── T_B.5 ── T_B.6
   │                  T_B.4 ─┘     │
   │                               └── T_B.7 (execute "delete" decisions)
   │
   ├── Initiative C: T_C.2 ── T_C.3 ── T_C.4 ── T_C.5 ── T_C.6 ── T_C.7
   │                                       │
   │                                       ├── T_C.8 (parallel-safe)
   │                                       └── T_C.9 (parallel-safe)
   │
   ├── Wave 3 seed: T_D.1 ── T_D.2
   │                T_E.1 (gated on T_B.7)
   │
   └── Wave 4 seed: T_F.1 (gated on T_E.1)
```

---

## Tasks

### Wave 0 — Corrections & agent operating notes

#### T0.1: Correct PRD where it diverges from code
- **depends_on**: []
- **location**: `docs/dev/modernization-prd.md`
- **description**:
  Apply two corrections discovered during verification:
  1. Initiative C ("Replace the ambient `state` dict in routines"): rename
     to "Replace wide threaded parameter lists in routines". Update the
     "Current state" paragraph to describe the actual pattern — e.g.
     `do_install` takes 17 positional/keyword parameters and threads
     subsets through `handle_new_packages` (11 params), `handle_lockfile`
     (10), `do_init` (10), etc. The target state and approach do not
     change materially: a typed `RoutineContext` dataclass replaces the
     ambient set of arguments.
  2. Initiative B: remove `markers.py` from the list of suspect
     "inlined former vendor" modules. `markers.py` imports from
     `pipenv.patched.pip._vendor.{distlib,packaging}` and is project-owned
     glue; it does not have a vendor lineage to triage. The triage set
     remains `requirementslib.py`, `requirements.py`, and the
     URL/path-overlapping helpers in `fileutils.py`.
- **validation**: PRD section text reflects the corrections; `git diff`
  shows only those two passages changed; no behavioural code changed.
- **status**: Completed
- **log**:
  - Initiative C retitled to "Replace wide threaded parameter lists in
    routines"; current-state paragraph rewritten to cite actual parameter
    counts (`do_install`: 17, `handle_new_packages`: 11, `handle_lockfile`:
    10, `do_init`: 10). Target state and Approach left untouched.
  - Initiative B current-state list updated: `markers.py` removed from the
    suspect set; `requirements.py` and URL/path helpers in `fileutils.py`
    retained alongside `requirementslib.py`.
  - `git diff` confirmed only the two intended passages changed.
- **files edited/created**:
  - `docs/dev/modernization-prd.md`

#### T0.2: Document agent operating procedure
- **depends_on**: []
- **location**: `docs/dev/swarm-ops.md` (new)
- **description**:
  Short page (~50 lines) covering: which branch to push to (per-initiative
  feature branches off `maintenance/code-cleanup-2026-05`), the required
  pre-commit checklist (pytest unit suite green, `ruff check pipenv/`
  green, `Co-Authored-By` trailer present), what's off limits (`patched/`,
  `vendor/`, `pipenv/__version__.py`, `CHANGELOG.md`), commit-message
  conventions (matching existing patterns: `refactor: ...`,
  `chore: ...`, etc.), and how to surface review-requested items (TODO
  comments tagged `TODO(swarm)` so they're greppable).
- **validation**: File exists, lints clean as markdown, references real
  commands that succeed on the current tree.
- **status**: Completed
- **log**:
  Wrote 95-line operating manual covering all seven required sections
  (scope/branch, pre-commit checklist, off-limits paths, commit
  conventions, Towncrier news fragments, review-flagged TODOs, and
  task-complete definition). Verified `python -m pytest tests/unit -x`
  and `ruff check pipenv/` both exit 0 on the current tree before
  documenting them as the validation commands.
- **files edited/created**: `docs/dev/swarm-ops.md` (new)

---

### Wave 1 — Initiative A: URL/path utility consolidation

#### T_A.1: Inventory & canonical-home decision doc
- **depends_on**: [T0.1, T0.2]
- **location**: `docs/dev/initiative-a-inventory.md` (new, temporary)
- **description**:
  Produce a short inventory table for the module-level symbols of
  `pipenv/utils/internet.py` (top-level defs and the
  `PackageIndexHTMLParser` class — public symbols include `is_valid_url`,
  `is_pypi_url`, `replace_pypi_sources`, `create_mirror_source`,
  `download_file`, `get_host_and_port`, `get_url_name`, `is_url_equal`,
  `proper_case`, `write_credentials_netrc`, `get_requests_session`,
  plus the underscore-prefixed helpers `_strip_credentials_from_url` and
  `_read_existing_netrc_content` which are imported from elsewhere in
  `pipenv/` and so are effectively public) and `pipenv/utils/fileutils.py`
  (module-level symbols including `is_file_url`, `is_valid_url`,
  `url_to_path`, `normalize_path`, `normalize_drive`, `path_to_url`,
  `open_file`, `temp_path`, `create_tracked_tempdir`,
  `check_for_unc_path`).
  For each symbol record: caller count (greppable), suggested canonical
  home (`internet` for URL/scheme concerns; `fileutils` for filesystem
  path concerns), and overlap notes. Mark `is_valid_url` as the explicit
  duplicate. Mark URL↔path conversion helpers (`url_to_path`,
  `path_to_url`, `is_file_url`) as candidates to keep in `fileutils.py`
  (they're filesystem-flavored URL handling) but to be cross-referenced
  from `internet.py`.
- **validation**: Doc exists, table is complete, every public symbol
  appears exactly once with a canonical-home decision.
- **status**: Completed (commit 39d80a17; re-committed after filesystem
  freeze corrupted the original commit's object writes — content was
  intact in the working tree)
- **log**:
  Wrote 132-line inventory covering 13 internet.py symbols and 10
  fileutils.py symbols with caller counts and canonical-home decisions.
  Surfaced a separate, latent duplicate `path_to_url` in
  `pipenv/utils/shell.py:104` with zero internal callers (different
  implementation than fileutils' version); flagged for T_A.2 sweep
  rather than a new task.
- **files edited/created**: `docs/dev/initiative-a-inventory.md` (new)

#### T_A.2: Move `is_valid_url` to canonical home with deprecation signal
- **depends_on**: [T_A.1]
- **location**: `pipenv/utils/internet.py`, `pipenv/utils/fileutils.py`,
  `news/` (new fragment).
- **description**:
  `is_valid_url` already exists in both modules with identical
  implementation. Per T_A.1's decision, keep the implementation in
  `pipenv/utils/internet.py`. In `pipenv/utils/fileutils.py`, replace the
  local definition with a shim that re-exports the canonical function
  *and* emits a `DeprecationWarning` on use, so any external consumer
  importing `pipenv.utils.fileutils.is_valid_url` gets a visible signal
  during the deprecation window. Intra-module call sites in
  `fileutils.py` (notably the call at `pipenv/utils/fileutils.py:160`)
  are updated in this task to import the canonical name directly from
  `internet`, so they do not trip the warning themselves. Add a news
  fragment under `news/` documenting the deprecation per the project's
  Towncrier convention (`.removal.rst` or `.deprecation.rst` — match
  existing fragments in the directory). Do not change any non-fileutils
  caller's import line in this task.
- **validation**:
  - `grep -n "def is_valid_url" pipenv/` returns exactly one result.
  - `python -c "import warnings; warnings.simplefilter('error'); from pipenv.utils.fileutils import is_valid_url; is_valid_url('https://x/y')"`
    raises `DeprecationWarning`.
  - `python -c "from pipenv.utils.fileutils import is_valid_url" ` still
    succeeds (no `ImportError`).
  - Intra-module call at the old `pipenv/utils/fileutils.py:160` site
    exercises the canonical `internet` import (verifiable by reading the
    diff).
  - Unit suite green; new news fragment is recognized by the project's
    Towncrier config.
  - **Strict-mode caveat (added post-execution):** A plain
    `python -W error::DeprecationWarning -m pytest tests/unit` cannot
    pass in this environment because `pytest_asyncio` emits a
    `PytestDeprecationWarning` during `pytest_configure` (which
    subclasses `DeprecationWarning`). Use the pytest-scoped form
    instead:
    `python -m pytest tests/unit -x -W "ignore::pytest.PytestDeprecationWarning" -W "error::DeprecationWarning"`.
- **status**: Completed (commit b144f64c; sweep follow-up 3a81cce1
  removed the dead duplicate `path_to_url` in `pipenv/utils/shell.py`
  that T_A.1 and T_B.3 had flagged)
- **log**:
  Replaced the local `is_valid_url` def in `fileutils.py` with a
  `DeprecationWarning`-emitting shim that re-exports the canonical
  function from `pipenv.utils.internet`. Rewired the intra-module
  call in `open_file` to use a module-level
  `from pipenv.utils.internet import is_valid_url as _is_valid_url`
  alias so the shim isn't tripped by pipenv itself. Added news fragment
  `news/+initiative-a-is-valid-url.removal.rst`. TDD: added
  `test_is_valid_url_fileutils_shim_emits_deprecation` in
  `tests/unit/test_utils.py` (RED → GREEN). **T_A.3 was folded into
  this commit** because the strict-mode validation revealed
  `pipenv/utils/requirementslib.py:23` would trip the shim — the
  one-line caller migration was needed to keep the validation passing.
  The sweep commit 3a81cce1 also kept the
  `from pipenv.utils.shell import normalize_drive` re-export
  (with `# noqa: F401`) because `tests/integration/test_cli.py:10`
  binds to `pipenv.utils.shell.normalize_drive` externally.
- **files edited/created**:
  - `pipenv/utils/fileutils.py` (shim, intra-module rewire)
  - `pipenv/utils/requirementslib.py` (import retarget — folded T_A.3)
  - `pipenv/utils/shell.py` (sweep: dead duplicate path_to_url removed)
  - `tests/unit/test_utils.py` (new deprecation-warning test)
  - `news/+initiative-a-is-valid-url.removal.rst` (new Towncrier fragment)

#### T_A.3: Update internal callers to canonical import
- **depends_on**: [T_A.2]
- **location**: every file in `pipenv/` (excl. `patched/`, `vendor/`) that
  currently does `from pipenv.utils.fileutils import ..., is_valid_url, ...`.
  At plan-write time the only such site is
  `pipenv/utils/requirementslib.py:23`, where the import line is
  `from pipenv.utils.fileutils import is_valid_url, normalize_path, url_to_path`
  — a multi-symbol import.
- **description**:
  At each site, surgically remove only the `is_valid_url` name from the
  `fileutils` import and add an `is_valid_url` import from
  `pipenv.utils.internet`. Other names co-imported from `fileutils`
  (e.g. `normalize_path`, `url_to_path` in `requirementslib.py`) must be
  preserved on their original import line — this is not a wholesale line
  replacement.
- **validation**:
  - `grep -rn "from pipenv.utils.fileutils import" pipenv/ | grep is_valid_url`
    returns nothing under non-patched, non-vendor paths.
  - `python -c "from pipenv.utils.requirementslib import is_valid_url, normalize_path, url_to_path"`
    or equivalent caller-specific assertion confirms the other names
    still resolve. (Adapt this check to whichever callers the
    plan-execution agent found.)
  - Running the unit suite produces no `DeprecationWarning` from the
    T_A.2 shim being tripped by an internal caller (use the
    pytest-scoped `-W` form noted in T_A.2's validation block).
  - Unit suite green.
- **status**: Completed (folded into T_A.2 — commit b144f64c)
- **log**:
  Folded into T_A.2 by necessity: the only internal site importing
  `is_valid_url` from `pipenv.utils.fileutils` was
  `pipenv/utils/requirementslib.py:23`, a multi-symbol import line.
  Retargeting that single name (while preserving the co-imported
  `normalize_path` and `url_to_path` on the same line) was required
  for T_A.2's strict-mode `-W error::DeprecationWarning` validation
  to pass. The task brief explicitly authorised this fold-in.
- **files edited/created**:
  - `pipenv/utils/requirementslib.py` (one-line import retarget)

#### T_A.4: Remove `is_valid_url` re-export shim
- **depends_on**: [T_A.3]
- **location**: `pipenv/utils/fileutils.py`.
- **description**:
  Shim deleted along with the parallel `pipenv.project.SourceNotFound`
  re-export (T_D.2). Maintainer call: pipenv's stable API is the CLI,
  so a deprecation window protects nothing — internal-only re-exports
  with `DeprecationWarning` shims add noise without value. Removed
  outright; in-module call sites already used the canonical
  `pipenv.utils.internet` / `pipenv.utils.sources` imports.
- **status**: Completed
- **log**: Removed `is_valid_url` shim + its unit test;
  removed `SourceNotFound` re-export from `pipenv.project` and
  updated the two real importers (`pipenv/utils/indexes.py`,
  `tests/unit/test_sources.py`) to pull from `pipenv.utils.sources`.
- **files edited/created**:
  - `pipenv/utils/fileutils.py` (shim + alias import deleted)
  - `pipenv/project.py` (`SourceNotFound` dropped from sources import)
  - `pipenv/utils/indexes.py` (import path updated)
  - `pipenv/utils/sources.py` (docstring cleaned up)
  - `tests/unit/test_utils.py` (shim-only test deleted)
  - `tests/unit/test_sources.py` (import path updated)

---

### Wave 1 — Initiative B: Inlined-vendor triage

These four triage tasks (T_B.1–T_B.4) are parallel-safe **because each
writes to its own sub-file**, not to a single shared document. T_B.5
concatenates them into the consolidated triage doc. Do not share an
output file between parallel agents.

#### T_B.1: Triage `pipenv/utils/requirementslib.py`
- **depends_on**: [T0.1, T0.2]
- **location**: `pipenv/utils/requirementslib.py` (read-only); decision
  recorded in `docs/dev/initiative-b-triage-requirementslib.md` (new,
  temporary, this task's own output file).
- **description**:
  Audit the 740-line module. For each public symbol (`strip_ssh_from_git_uri`,
  `add_ssh_scheme_to_git_uri`, `is_vcs`, `is_editable`, `is_star`,
  `convert_entry_to_path`, `is_installable_file`, `get_setup_paths`,
  `prepare_pip_source_args`, `get_package_finder`, `PathAccessError`,
  `get_path`, `default_visit`, `dict_path_enter`, `dict_path_exit`,
  `remap`, `merge_items`, `get_pip_command`, `unpack_url`, `get_http_url`):
  - Identify whether the implementation has a live upstream (the original
    `requirementslib` package on PyPI is archived; the dict-tree walkers
    `get_path` / `remap` / `dict_path_enter` / `dict_path_exit` /
    `default_visit` come from `boltons.iterutils` — that one is live).
  - List every internal caller (grep).
  - Recommend one of **adopt**, **vendor**, or **delete** for each symbol
    or coherent group of symbols. The `boltons.iterutils` dict-walker
    group is a natural "vendor" group (move under `pipenv/vendor/boltons/`
    or replace with a small purpose-specific helper). VCS-URI helpers and
    `is_*` predicates are natural "adopt" candidates.
  - Note any symbol with no internal callers as a **delete** candidate.
- **validation**: Triage doc has an entry per symbol with a recommendation
  and a caller list.
- **status**: Completed (commit 7b92b6aa; re-committed after filesystem
  freeze corrupted the original commit's object writes — content was
  intact in the working tree)
- **log**:
  20 public symbols audited. Recommendations roll up to: 7 boltons.iterutils
  dict-walkers form a coherent **vendor** group (move under
  `pipenv/vendor/boltons/` or replace with a purpose-specific helper);
  VCS-URI helpers and `is_*` predicates are **adopt**; symbols with
  zero callers flagged as **delete** candidates for T_B.7.
- **files edited/created**: `docs/dev/initiative-b-triage-requirementslib.md` (new)

#### T_B.2: Triage `pipenv/utils/requirements.py`
- **depends_on**: [T0.1, T0.2]
- **location**: `pipenv/utils/requirements.py` (read-only); decision
  recorded in `docs/dev/initiative-b-triage-requirements.md` (new,
  temporary, this task's own output file).
- **description**:
  Audit the 395-line module's nine public functions (`redact_netloc`,
  `redact_auth_from_url`, `normalize_name`, `import_requirements`,
  `add_index_to_pipfile`, `requirement_from_lockfile`,
  `requirements_from_lockfile`, `requirement_from_pipfile`,
  `requirements_from_pipfile`). Same shape as T_B.1: caller list,
  upstream provenance (the `redact_*` pair are pip-internal copies;
  `normalize_name` overlaps `dependencies.pep423_name` — flag this
  duplication), recommendation. This module is likely mostly **adopt**
  (it's the lockfile <-> Pipfile bridge), but several functions belong
  conceptually in `dependencies.py` and Initiative E will move them.
- **validation**: Triage doc entries complete; overlaps with
  `dependencies.py` (especially `normalize_name` / `pep423_name`) are
  explicitly flagged.
- **status**: Completed (commit cf7695f4)
- **log**:
  9 public functions audited. Recommendations: 6 **adopt** (project-owned
  Pipfile/lockfile bridge), 2 **vendor** (`redact_netloc` /
  `redact_auth_from_url` — deliberate divergent forks of pip-internal
  helpers preserving env-var auth placeholders and the `git` SSH user;
  cannot be replaced by pip imports without a behaviour change),
  1 **delete** (`normalize_name` — overlaps with
  `dependencies.pep423_name`; flagged for Initiative E merge). Also
  surfaced: `pep423_name`'s guard predicate is almost certainly buggy
  (`any(... not in name ...)` makes the `else` branch dead — flag for
  Initiative E); `BAD_PACKAGES` constant used in 3 routines (Initiative
  E co-location); module-level `add_index_to_pipfile` name-collides
  with `Project.add_index_to_pipfile` (Initiative E rename candidate).
- **files edited/created**: `docs/dev/initiative-b-triage-requirements.md` (new)

#### T_B.3: Triage URL/path overlap in `pipenv/utils/fileutils.py`
- **depends_on**: [T0.1, T0.2]
- **location**: `pipenv/utils/fileutils.py` (read-only); decision
  recorded in `docs/dev/initiative-b-triage-fileutils.md` (new,
  temporary, this task's own output file).
- **description**:
  Narrow scope: review the symbols flagged in T_A.1 as "filesystem-
  flavored URL handling" (`is_file_url`, `url_to_path`, `path_to_url`).
  Confirm they belong in `fileutils.py` (not `internet.py`) per the
  domain-boundary argument, or recommend a move with caller-update plan.
  This is the smallest of the triages and may be a 5-line entry in the
  doc.
- **validation**: Triage doc entry exists and is internally consistent
  with T_A.1.
- **status**: Completed (commit 7606f7a6)
- **log**:
  All three target symbols (`is_file_url`, `url_to_path`, `path_to_url`)
  stay in `fileutils.py` per the domain-boundary rule (each one's heavy
  concept is the Path side; a URL utility knowing nothing about local
  paths could not implement them). Caller counts: `is_file_url` 0
  external (only used inside `fileutils.open_file`); `url_to_path` 2
  (both in `requirementslib.py`); `path_to_url` 0 external. Adjacent
  finding (relayed to T_A.1): `pipenv/utils/shell.py:104` defines a
  second `path_to_url` with a different implementation and zero callers.
- **files edited/created**: `docs/dev/initiative-b-triage-fileutils.md` (new)

#### T_B.4: Confirm `markers.py` is owned, not vendored
- **depends_on**: [T0.1]
- **location**: `pipenv/utils/markers.py` (read-only); recorded in
  `docs/dev/initiative-b-triage-markers.md` (new, temporary, this task's
  own output file — single paragraph is fine).
- **description**:
  Per T0.1, this module is not actually inlined-former-vendor. Record
  the disposition explicitly so future readers don't re-open this
  question: "Owned project glue over `pipenv.patched.pip._vendor.distlib`
  and `pipenv.patched.pip._vendor.packaging`. Refactor freely under
  Initiative E if useful." No further triage required.
- **validation**: Closeout paragraph present in triage doc.
- **status**: Completed (commit d98b18e3)
- **log**:
  Verified `markers.py:9-10` imports `parse_marker` from
  `pipenv.patched.pip._vendor.distlib.util` and `Marker` from
  `pipenv.patched.pip._vendor.packaging.markers` — confirms project-owned
  glue, no separate vendor lineage. Disposition recorded so the question
  stays closed; refactor freely under Initiative E if useful.
- **files edited/created**: `docs/dev/initiative-b-triage-markers.md` (new)

#### T_B.5: Synthesize triage doc + open Initiative B execution issues
- **depends_on**: [T_B.1, T_B.2, T_B.3, T_B.4]
- **location**: `docs/dev/initiative-b-triage.md` (new, consolidates the
  four per-module sub-files into a single readable document); GitHub
  Issues (one per adopt/vendor/delete group with multiple items). The
  four sub-files are deleted from the working tree as part of this task
  once their content is incorporated.
- **description**:
  Assemble the four sub-audits into a single readable triage document
  with a summary table at the top: symbol or group → decision → execution
  owner → linked issue/PR. Open GitHub issues for each multi-symbol
  execution group so the work is trackable outside this plan.
- **validation**: Triage doc has a clean summary table; every "adopt"
  and "vendor" decision has a linked issue; the four per-module sub-files
  no longer exist in the working tree. **Note**: per orchestrator
  amendment, `gh issue create` is NOT invoked by the agent — issue
  text is drafted in code-fenced blocks inside the consolidated doc
  for the maintainer to copy-paste after review.
- **status**: Completed (commit d3320613)
- **log**:
  Consolidated 4 sub-files into `docs/dev/initiative-b-triage.md`
  (713 lines). Summary table at top: 32 symbol/group rows sorted by
  decision (8 delete, 6 vendor, 18 adopt). Per-module sections
  preserve each sub-file's substantive findings. Seven code-fenced
  `gh issue create` blocks drafted at the bottom for the maintainer:
  (1) delete dead code in requirementslib, (2) vendor boltons.iterutils
  subset, (3) document redact_* fork provenance, (4) adopt
  Pipfile/lockfile bridge in requirements.py, (5) adopt schema
  predicates in requirementslib, (6) adopt-or-replace decision for
  unpack_url/get_http_url, (7) bundled single-item cleanups +
  Initiative E hand-offs. Cross-cutting flags
  (normalize_name/pep423_name overlap; suspected pep423_name bug;
  add_index_to_pipfile name collision; BAD_PACKAGES co-location)
  routed to Initiative E. NO issues opened.
- **files edited/created**:
  - `docs/dev/initiative-b-triage.md` (new, consolidated)
  - `docs/dev/initiative-b-triage-requirementslib.md` (deleted)
  - `docs/dev/initiative-b-triage-requirements.md` (deleted)
  - `docs/dev/initiative-b-triage-fileutils.md` (deleted)
  - `docs/dev/initiative-b-triage-markers.md` (deleted)

#### T_B.7: Execute Initiative B decisions (Wave 1c)
- **depends_on**: [T_B.5]
- **location**: `pipenv/utils/requirementslib.py`,
  `pipenv/utils/requirements.py`, `pipenv/utils/dependencies.py`,
  `pipenv/utils/locking.py`, `pipenv/project.py`,
  `pipenv/utils/resolver.py`, `tests/unit/test_requirementslib.py`
  (new), `tests/unit/test_dependencies.py`, `tests/unit/test_core.py`,
  `news/`.
- **description**:
  Originally scoped to "delete decisions only" — expanded under
  maintainer direction to execute the full set of triage decisions
  inline (no GitHub issues opened; the triage doc is the working
  record). Five work units launched as Wave 1c:
  - **W1** — delete dead symbols in `requirementslib.py`. Verification
    surfaced that the triage's claim of "0 callers" for
    `prepare_pip_source_args` was stale (real caller in
    `dependencies.py`); scoped down to 6 symbols; the seventh routed
    to W3 for divergence investigation.
  - **W2** — replace 6 inlined `boltons.iterutils` primitives with a
    purpose-built ~30-line recursive dict-merge helper. `merge_items`'s
    public signature preserved.
  - **W3a** — provenance docstrings on `redact_netloc` and
    `redact_auth_from_url`.
  - **W3b** — `unpack_url` / `get_http_url`: ADOPT path. Side-by-side
    found two load-bearing divergences from patched-pip
    (`unpack_url` returns `File(...)` for VCS links where pip returns
    `None`; `get_http_url` uses `globally_managed=False` where pip
    uses `True`). Kept the requirementslib copies with provenance
    docstrings.
  - **W3c** — `prepare_pip_source_args`: REPLACE path. Migrated
    `dependencies.py` to import from the canonical `indexes.py` copy;
    deleted the requirementslib copy. The `indexes.py` version is
    strictly better (preserves port in trusted-host args; raises on
    missing URL; the Pipfile schema guarantees URL presence at the
    sole call site, so divergence #2 is unreachable).
  - **W4** — fix latent bug in `pep423_name` (dead-`else` branch);
    consolidate `normalize_name` into `pep423_name` (4 callers
    migrated; all pass plain names so the migration is observably
    equivalent for them).
  - **W5** — collapse `is_editable` duplicate. The `dependencies.py:1503`
    copy turned out to be dead code; every active caller used
    `requirementslib.is_editable`. Made `dependencies.py` canonical
    (per long-term-home decision); migrated imports.
- **validation**:
  - All five work units committed: `5a84f5ac` (W1), `de6628b8` (W2),
    `e874e9d0` (W4), `842939a4` (W5), `dc58f7a6` (W3a), `2d897a0c`
    (W3b), `8a7d0a79` (W3c).
  - `python -m pytest tests/unit -x`: 516 passed, 9 skipped (baseline
    was 484; +32 new pinning / TDD tests across W2, W4, W5).
  - `ruff check pipenv/`: clean.
  - `pipenv/utils/requirementslib.py`: 740 lines → 274 lines (63%
    reduction).
  - News fragments added for the two behaviour-affecting changes
    (`pep423_name` bug fix; `prepare_pip_source_args` migration).
  - One latent bug found and left unfixed (with a `TODO(swarm)`-style
    flag in W2's reporting): the old boltons-based `dict_path_exit`
    silently produced an empty `tomlkit.items.Array` when reassembling
    nested containers. The new helper preserves array contents. This
    is technically an observable behaviour fix triggered only by an
    unusual Pipfile shape (same `extras = ["..."]` in two merged
    category dicts).
- **status**: Completed
- **log**:
  Wave 1c executed inline per maintainer's "execute, don't track"
  directive: no GitHub issues opened; the triage doc serves as the
  working record. The seven Wave-1c commits net out at roughly
  -470 lines in `requirementslib.py`, +30 lines of purpose-built
  helper, +30 lines of new tests, two correctness fixes, zero new
  vendored surface, zero new external dependencies. Per the
  parallel-agent operating discipline established in T0.2, agents
  used explicit `git commit -- <files>` to avoid sweep-up across
  the wave.
- **files edited/created**:
  - `pipenv/utils/requirementslib.py` (heavy: -466 lines net across
    W1 + W2 + W3b docstrings + W3c + W5)
  - `pipenv/utils/dependencies.py` (W3c imports, W4 pep423_name fix,
    W4 caller migrations, W5 canonical is_editable)
  - `pipenv/utils/requirements.py` (W3a docstrings, W4
    `normalize_name` removal)
  - `pipenv/utils/locking.py` (W4 caller migration, W5 import retarget)
  - `pipenv/project.py` (W4 caller migrations)
  - `pipenv/utils/resolver.py` (W4 caller migration, import update)
  - `tests/unit/test_requirementslib.py` (new — W2; 8 tests)
  - `tests/unit/test_dependencies.py` (W4 +12 tests, W5 +12 tests)
  - `tests/unit/test_core.py` (W4 docstring update)
  - `news/+pep423-name-scheme-guard.bugfix.rst` (new — W4)
  - `news/+initiative-b-prepare-pip-source-args.trivial.rst` (new — W3c)

#### T_B.6: Document owned-vs-vendored policy
- **depends_on**: [T_B.5]
- **location**: `docs/dev/contributing.md` (existing); cross-linked from
  `CONTRIBUTING.md`.
- **description**:
  Add a short section ("Owned code vs. vendored code") stating the
  policy: code lives either under `pipenv/utils/` and elsewhere in
  `pipenv/` (owned; refactor freely; project conventions and test
  coverage apply) or under `pipenv/vendor/` (do not edit; resync from
  upstream per the vendoring tooling). There is no third state. Inlining
  upstream code into `pipenv/utils/` without owning it is explicitly out
  of policy going forward.
- **validation**: Section exists, links to `docs/dev/initiative-b-triage.md`,
  and is reachable from `CONTRIBUTING.md`.
- **status**: Completed (commit aa459f65)
- **log**:
  Added 58-line "Owned code vs. vendored code" section to
  `docs/dev/contributing.md`. Covers the two states, the no-third-state
  rule, and the deliberate-forks exception with the Wave 1c examples
  (`redact_*` in `requirements.py`; `unpack_url`/`get_http_url` in
  `requirementslib.py`). Top-level `CONTRIBUTING.md` got a pointer
  paragraph rather than a duplicate copy.
- **files edited/created**:
  - `docs/dev/contributing.md` (+58 lines)
  - `CONTRIBUTING.md` (+6 lines pointer)
- **files edited/created**:

---

### Wave 2 — Initiative C: Typed routine context

> **Note**: The "PRD reframe applied" marker is folded into T0.1 per
> review feedback (it was a no-op). What was previously T_C.1 is removed;
> Wave 2 begins at T_C.2.

#### T_C.2: Inventory routine parameters
- **depends_on**: [T0.1, T0.2]
- **location**: `docs/dev/initiative-c-params.md` (new, temporary);
  reads `pipenv/routines/*.py` and `pipenv/core.py`.
- **description**:
  Produce a parameter inventory across the routine entry points.
  **Inclusion threshold: any function taking more than 3 parameters
  besides `project`.** Functions known to qualify (verified against
  current code): `do_install` (17), `handle_new_packages` (11),
  `handle_lockfile` (10), `do_init` (10), `do_install_validations`,
  `install_build_system_packages`, `do_install_dependencies`,
  `batch_install_iteration`, `batch_install`, plus analogues in
  `update.py`, `uninstall.py`, `lock.py`, `sync.py`. Trivial-arity
  helpers (e.g. `_target_marker_environment` with 2 params,
  `handle_missing_lockfile` with 5) are listed in an appendix but do
  **not** drive context-shape decisions.
  For each in-scope parameter record: name, type (best-effort if
  un-annotated), default, semantic group (e.g. "install policy" for
  `pre`/`deploy`/`skip_lock`; "target environment" for `system`/
  `allow_global`/`python`/`pypi_mirror`; "package selection" for
  `packages`/`editable_packages`/`pipfile_categories`/`dev`;
  "execution control" for `extra_pip_args`/`site_packages`/
  `requirementstxt`/`index`/`ignore_pipfile`). The semantic groups become
  the candidate shape for the dataclass(es).
- **validation**: Doc table covers every named parameter on every
  in-scope routine; semantic-group assignment is internally consistent;
  trivial-arity helpers are in the appendix, not the main table.
- **status**: Completed (commit 0c60c580)
- **log**:
  240 parameter rows across 23 in-scope functions in
  `pipenv/routines/`. Scope finding: `pipenv/core.py` no longer exists
  (earlier modernization decomposed it into `routines/` + `utils/`);
  inventory sourced exclusively from `pipenv/routines/`.

  Semantic-group distribution: package_selection 54, execution_options
  57, target_env 50, install_policy 36, other 34, state_flags 9.

  Cross-cutting findings for T_C.3:
  - `pypi_mirror` + `system`/`allow_global` universal (~36 rows) —
    strongest signal for a shared `target_env` group.
  - `(packages, editable_packages, categories)` shape duplicated in
    5+ routines, with a parallel `(package_args, pipfile_category,
    category)` rename inside `update.py`'s helpers (worth normalizing
    in `RoutineContext`).
  - `install_policy` flags (`pre`, `deploy`, `skip_lock`,
    `ignore_pipfile`, `clear`, `lock_only`) consistently travel as a
    packet — best candidate for a nested dataclass.
  - `state_flags` (9 rows) is small and incoherent — recommend
    leaving as call-site args rather than folding into `RoutineContext`.
  - `other` group is dominated by per-call workflow plumbing
    (`lockfile`, `procs`, `reverse_deps`, `requested_packages`) — NOT
    `RoutineContext` material; belongs in per-routine operation
    objects.
- **files edited/created**:
  - `docs/dev/initiative-c-params.md` (new, 240-row table + analysis)

#### T_C.3: Design `RoutineContext` proposal
- **depends_on**: [T_C.2]
- **location**: `docs/dev/initiative-c-design.md` (new, temporary).
- **description**:
  Propose the dataclass shape. Likely structure: one top-level
  `RoutineContext` containing nested frozen dataclasses
  `InstallPolicy`, `TargetEnv`, `PackageSelection`, `ExecutionOptions`,
  matching the semantic groups from T_C.2. Each nested dataclass is
  `frozen=True`. Mutation happens via `dataclasses.replace`. Construction
  helper: a `from_cli(...)` classmethod that wraps the current per-
  command parameter list and is the only place CLI defaults are
  materialized. Include a concrete example of `do_install` rewritten
  against the proposed type. Get sign-off from Matt before T_C.4 lands.
- **validation**: Design doc exists, includes type signatures and one
  rewritten call site for illustration, has a "decisions needed"
  section for any open choices.
- **status**: Completed (commit 49f6892f) — **awaits maintainer sign-off
  before T_C.4 begins**
- **log**:
  782-line design proposal. 32 fields across four nested frozen
  dataclasses (TargetEnv: 5, InstallPolicy: 8, PackageSelection: 10,
  ExecutionOptions: 9). Includes the concrete `do_install` migration
  example (17 params → `(project, ctx)`). The agent executed the
  proposed dataclasses at runtime as a sanity check —
  `RoutineContext.from_cli(...)` constructs cleanly,
  `dataclasses.replace` produces a new context without mutating the
  original, derived properties (`allow_global` derives from `system`)
  work.

  Seven decision questions for maintainer sign-off: field grouping
  correctness, `Project` placement (separate first arg vs absorbed
  into ctx), naming, module location (`pipenv/routines/context.py` vs
  alternatives), `from_cli` vs `__init__`, uninstall-flag placement,
  helper-method bundling.

  Seven open implementation questions for follow-up: `categories`
  defaults, `BAD_PACKAGES` co-location, `requirements_directory`
  layering, Pipfile-vs-lockfile category aliases, audit/scan scope
  (deferred to a sibling `AuditOptions` per the design), `None` vs
  `()` for `extra_pip_args`, backwards-compat shim for external API
  consumers.
- **files edited/created**:
  - `docs/dev/initiative-c-design.md` (new, 782 lines)

#### T_C.4: Introduce `RoutineContext` alongside existing params
- **depends_on**: [T_C.3]
- **location**: `pipenv/routines/context.py` (new); does not modify
  existing routine signatures yet.
- **description**:
  Add the dataclass module. Add tests covering construction,
  `replace`-based mutation, and `from_cli` defaults. **No existing call
  site is modified in this task** — this is pure additive scaffolding.
- **validation**: New module + tests in `tests/unit/test_routine_context.py`;
  unit suite green; no other production file changed.
- **status**: Not Completed
- **log**:
- **files edited/created**:

#### T_C.5: Migrate `do_install` to consume `RoutineContext`
- **depends_on**: [T_C.4]
- **location**: `pipenv/routines/install.py`, `pipenv/cli/command.py`
  (the CLI entry point that calls `do_install`).
- **description**:
  Change `do_install` to accept a single `RoutineContext` parameter (plus
  `project`, which stays as the first positional until Initiative D
  reshapes it). Have the CLI entrypoint construct the context via
  `RoutineContext.from_cli(...)`. Internal helpers (`handle_new_packages`,
  `handle_lockfile`, `do_init`) keep their current signatures in this
  PR — they're migrated in subsequent tasks.
- **validation**:
  - `do_install` signature is `(project, ctx: RoutineContext)`.
  - Unit suite green.
  - `pipenv install --help` exits 0 (verifies the CLI wiring imports
    cleanly).
  - Smoke install runs cleanly: from a temporary directory containing
    only the fixture at `tests/pypi/`-equivalent style, run
    `pipenv install --skip-lock requests==2.28.0` (or whichever fixture
    package is present in `tests/test_artifacts/` and known to install
    without network). Document the chosen fixture in the PR description.
  - If no local-only fixture is available, drop the smoke install
    requirement and rely on CI integration tests to catch regressions
    post-push; record this fallback in the PR description.
- **status**: Completed (commit b5419c1c)
- **log**:
  `do_install` signature reduced from 17 params to `(project, ctx)`.
  CLI entry point `cmd_install` in `pipenv/cli/command.py` constructs
  the context via `RoutineContext.from_cli(...)` and passes
  `do_install(state.project, ctx)`. Body of `do_install` accesses
  `ctx.target_env.*`, `ctx.install_policy.*`, `ctx.package_selection.*`,
  `ctx.execution_options.*` and continues to pass individual args to
  unchanged child helpers (T_C.6 migrates them). Editable-path
  normalization preserved by folding back into the context via
  `dataclasses.replace`. 11 new pinning tests in
  `tests/unit/test_do_install_context_routing.py`. No backwards-compat
  shim — old signature deleted wholesale per T_C.3 §9 sign-off.
- **files edited/created**:
  - `pipenv/routines/install.py`
  - `pipenv/cli/command.py`
  - `tests/unit/test_do_install_context_routing.py` (new, 11 tests)

#### T_C.6: Migrate `handle_new_packages` and `handle_lockfile`
- **depends_on**: [T_C.5]
- **location**: `pipenv/routines/install.py`.
- **description**:
  Same migration pattern for the two largest internal helpers in
  `install.py`. They consume `ctx` rather than threading individual
  parameters.
- **validation**: Both helpers take `(project, ctx)`; unit suite green.
- **status**: Completed (commit 776bab9d)
- **log**:
  `handle_new_packages` reduced from 11 params to
  `(project, ctx, *, perform_upgrades=True)` (3 params; `perform_upgrades`
  stays as a call-site intent kwarg). `handle_lockfile` reduced from
  10 params to `(project, ctx)`. `do_install` updated to pass `ctx`
  directly. `do_init` (T_C.7 territory) call site bridged via inline
  `RoutineContext.from_cli(...)` — bridge will collapse naturally when
  T_C.7 migrates `do_init` end-to-end.

  Test updates: `tests/unit/test_do_install_context_routing.py` had
  4 tests refactored to assert against `ctx` fields plus 2 new
  signature-pin tests added (`TestHandleNewPackagesSignature`,
  `TestHandleLockfileSignature`). 575 tests pass.
- **files edited/created**:
  - `pipenv/routines/install.py`
  - `tests/unit/test_do_install_context_routing.py`

#### T_C.7: Migrate `do_init`, `do_install_validations`, `do_install_dependencies`
- **depends_on**: [T_C.6]
- **location**: `pipenv/routines/install.py`.
- **description**:
  Same migration pattern for the remaining `install.py` entry points and
  their batch helpers. After this task, `install.py` is fully on
  `RoutineContext`.
- **validation**: No function in `install.py` takes more than 3 positional
  / keyword arguments besides `project` and `ctx`; unit suite green.
- **status**: Completed (commit 969fa575)
- **log**:
  Seven helpers migrated: `do_init` (9 → 0 non-ctx params),
  `do_install_validations` (10 → 1 `requirements_directory`),
  `do_install_dependencies` (9 → 1 `requirements_dir`),
  `handle_outdated_lockfile` (9 → 2 `old_hash, new_hash` kw),
  `handle_missing_lockfile` (4 → 0), `batch_install` (10 → 4 call-state
  args), `batch_install_iteration` (8 → 4 call-state args).
  `install_build_system_packages` left at 3 non-project params (at the
  threshold). T_C.6's bridge inside `do_init` collapsed. `sync.py` got
  a similar inline-`from_cli` bridge added (T_C.9 collapses it).

  Two pre-existing issues fixed as side-effects:
  - Dead local in `do_install_validations`:
    `pre = project.settings.get("allow_prereleases")` was assigned and
    never read.
  - Subtle bug in `do_install_dependencies`: was mutating its own
    `ignore_hashes` parameter mid-loop; refactor computes
    `effective_ignore_hashes` locally so the frozen ctx is never
    mutated.

  `batch_install`/`batch_install_iteration` retain wide arity for
  `deps_list`/`procs`/`sources`/etc. — these are the "other" group
  per the design that belongs to a future `BatchInstall` object
  (deferred per T_C.4 §3 / T_C.3 sign-off). Flagged with
  `TODO(swarm)` at `pipenv/routines/install.py:763`.

  Test updates: 6 new signature-pin tests + 5 existing tests adjusted.
  584 tests pass.
- **files edited/created**:
  - `pipenv/routines/install.py`
  - `pipenv/routines/sync.py` (inline bridge for T_C.9)
  - `tests/unit/test_do_install_context_routing.py`

#### T_C.8: Migrate `pipenv/routines/update.py`
- **depends_on**: [T_C.4]  (parallel-safe with T_C.5–T_C.7 once T_C.4
  has landed; reviewers should sequence behind `install.py` to keep diff
  review bandwidth manageable)
- **location**: `pipenv/routines/update.py`.
- **description**:
  Same migration pattern for `do_update` and its helpers.
- **validation**: Unit suite green; same shape guarantee as T_C.7.
- **status**: Completed (commit 0add7dfb)
- **log**:
  `do_update` reduced from 17 params to `(project, ctx)`. Two
  wide-arity helpers also migrated: `_process_package_args` and
  `_resolve_and_update_lockfile` (both now `(project, ctx, *kw...)`
  where the keyword-only args are upgrade-internal data flow, not
  user-facing inputs). `cmd_update` in `pipenv/cli/command.py`
  constructs the context via `from_cli`.

  `--outdated` and `--dry-run` collapse: `RoutineContext` carries
  no `outdated` field; `cmd_update` ORs both flags into
  `install_policy.dry_run` and `do_update` mirrors the historical
  `outdated = outdated or bool(dry_run)` derivation.
  Behaviour-preserving.

  Scope-creep (necessary): `pipenv/routines/install.py:handle_new_packages`
  calls `do_update` after adding new packages. Without a
  backwards-compat shim (per T_C.3 §9), the only options were
  (a) leave `do_update`'s old signature (violates acceptance criteria)
  or (b) update the single call site in install.py. Took (b).

  Out of scope and deferred with `TODO(swarm)`: the `upgrade()`
  function in `update.py` (10 params; called from `cmd_upgrade` which
  is itself T_C.8-out-of-scope). It now constructs an internal
  helper context to feed the migrated helpers but its own signature
  is unchanged.

  Test updates: 14 new tests in
  `tests/unit/test_do_update_context_routing.py` (signature pins +
  flag routing); existing `tests/unit/test_update.py` and
  `tests/integration/test_update.py` adjusted to the new shapes.
  598 tests pass.
- **files edited/created**:
  - `pipenv/routines/update.py`
  - `pipenv/cli/command.py`
  - `pipenv/routines/install.py` (single call-site swap)
  - `tests/unit/test_update.py`, `tests/unit/test_do_update_context_routing.py` (new),
    `tests/integration/test_update.py`

#### T_C.9: Migrate `pipenv/routines/uninstall.py`, `lock.py`, `sync.py`
- **depends_on**: [T_C.4]  (parallel-safe with T_C.5–T_C.8 in principle;
  smaller routines, may be a single PR rather than three)
- **location**: `pipenv/routines/uninstall.py`, `pipenv/routines/lock.py`,
  `pipenv/routines/sync.py`.
- **description**:
  Same migration pattern for the remaining routines that consume
  multi-parameter contexts. Routines that take only a `project` (e.g.
  `graph`, `clean`, `clear`, `shell` — verify) are out of scope.
- **validation**: Unit suite green; all routines that thread > 3 params
  consume `RoutineContext` instead.
- **status**: Completed (commit 58ca629b). Companion bug fix:
  commit 4f5fb81c.
- **log**:
  Three routines migrated:
  - `do_lock` 9 params → `(project, ctx)`.
  - `do_sync` 11 params → `(project, ctx)`. T_C.7's inline
    `RoutineContext.from_cli(...)` bridge inside `do_sync` collapsed;
    T_C.8's bridge for the `do_sync` calls from `update.py` also
    collapsed.
  - `do_uninstall` 12 params (including a misnamed Click `ctx=None`
    passthrough) → `(project, ctx)`. The Click-context passthrough
    was dropped per the design's "CLI usage-error rendering lives at
    the CLI layer" — the single use site
    `PipenvUsageError("No package provided!", ctx=ctx)` just omits
    the kwarg.
  - `do_purge` left unchanged (only 3 non-project params, below the
    threshold).

  Internal callers migrated in the same PR: `install.py`
  (`handle_outdated_lockfile`, `handle_missing_lockfile`), `uninstall.py`
  (post-uninstall lock branch), `clean.py` (`ensure_lockfile`),
  `outdated.py` (`do_outdated`), `update.py` (do_sync sites,
  collapsing T_C.8's bridge), `cli/command.py` (`cmd_lock`,
  `cmd_sync`, `cmd_uninstall` via `RoutineContext.from_cli`).

  Pre-existing bug surfaced during T_C.9's test fixturing: `do_lock`
  referenced `old_lock_data` unconditionally after a
  `contextlib.suppress(KeyError)` assignment, raising
  `UnboundLocalError` on first-lock / new-category paths. Fixed in
  follow-up commit 4f5fb81c (one-line initialization).

  Test updates: 22 new tests in
  `tests/unit/test_lock_sync_uninstall_context_routing.py` (signature
  pins + flag routing for all three migrated routines + `do_purge`
  shape); existing tests in `test_locking_no_mutation.py` and
  `test_do_update_context_routing.py` adjusted to the new shapes.
  620 tests pass.

  **Initiative C is structurally complete** for the five
  `pipenv/routines/*.py` modules in T_C.2's inventory. Routine entry
  points that legitimately take only `(project, ...few-args...)`
  (e.g. `graph`, `clean`, `clear`, `shell`) remain on their old
  signatures per the threshold.
- **files edited/created**:
  - `pipenv/routines/{lock,sync,uninstall,install,clean,outdated,update}.py`
  - `pipenv/cli/command.py`
  - `tests/unit/test_lock_sync_uninstall_context_routing.py` (new, 22 tests)
  - `tests/unit/{test_locking_no_mutation,test_do_update_context_routing}.py`
  - Companion bug fix: `pipenv/routines/lock.py` (commit 4f5fb81c)

---

### Wave 3 — Seed tasks (full plan regenerated after Wave 1+2 lands)

#### T_D.1: Inventory `Project` responsibilities
- **depends_on**: [T0.1, T0.2]
- **location**: `docs/dev/initiative-d-inventory.md` (new, temporary).
- **description**:
  Cluster the methods of `pipenv/project.py` (1850 lines) into the five
  proposed subsystems (`Pipfile`, `Lockfile`, `Sources`, `VenvLocator`,
  `Settings`) plus a residual "coordinator" group. Identify cross-
  subsystem references that would become tight coupling after
  extraction. Identify which subsystem should be extracted first
  (PRD suggests `Sources` for self-containedness; verify or revise).
- **validation**: Inventory table exists; first extraction target
  identified with rationale.
- **status**: Completed (commit 7297c8f3) — **awaits maintainer sign-off
  before T_D.2 begins**
- **log**:
  434-line inventory covering 93 public members of `Project` (41
  `@property`, 1 `@cached_property`, 48 `def`, 2 `@classmethod`, 1
  `@staticmethod`). Bucket distribution: Pipfile 38, Sources 16,
  VenvLocator 13, Lockfile 13, coordinator 7, helper 3, Settings 3.
  Sums to 93.

  **First-extraction recommendation: `Sources`** (confirms PRD's
  nomination). Smallest of the four "real" subsystems (Pipfile /
  Lockfile / Sources / VenvLocator), single outbound write
  (`add_index_to_pipfile`), no env-var coupling on its core methods.

  Six decision questions for maintainer sign-off: subsystem-split
  correctness, module location, first-target sign-off,
  deprecation-warning timing for the delegating-wrapper window,
  helper-bucket disposition, and resolution of the `self.pipfile`
  reference at `project.py:586`.

  Notable side-finds flagged for review:
  - **Likely bug at `pipenv/project.py:586`**: `self.pipfile.get(...)`
    references an attribute that doesn't exist on `Project` (likely
    meant `parsed_pipfile` or `_pipfile`). Worth investigating
    independent of the extraction.
  - **Orphan-looking `_read_pyproject` at `project.py:782`**: surfaced
    during the inventory walk; flagged for potential dead-code
    cleanup.
- **files edited/created**:
  - `docs/dev/initiative-d-inventory.md` (new, 434 lines)

#### T_D.2: First extraction (`Sources`)
- **depends_on**: [T_D.1]
- **location**: `pipenv/utils/sources.py` (new) + `pipenv/project.py`
  + every internal caller of the migrating methods.
- **description**:
  Extract `Sources` as a single new module under `pipenv/utils/sources.py`
  (matches the existing `pipenv/utils/pipfile.py` precedent per T_D.1
  sign-off §8.2). **Per the T_D.1 §8.4 sign-off, this task does NOT
  land delegating wrappers as a holding pattern.** Extract `Sources`
  AND migrate every internal `project.<sources-method>` caller to
  `project.sources.<method>` (or whatever access shape we settle on)
  in the same PR. No `DeprecationWarning`, no shipped wrapper, no
  two-phase rollout — the maintainer's standing posture is that
  pipenv's only stable API is the CLI, so internal Python surface
  changes do not need a deprecation window.

  Helper-bucket methods (`path_to`, `prepend_hash_types`,
  `get_file_hash`) stay on `Project` for this task; revisit during
  per-subsystem extractions (T_D.1 §8.5).
- **validation**: `pipenv/project.py` lost roughly the right number of
  lines (≥ 80 net reduction expected for `Sources` plus its callers'
  imports retargeting); new module has its own test file; every
  former `project.<sources-method>` caller now uses the new path;
  unit suite green.
- **status**: Completed (commit 497d9716)
- **log**:
  `Sources` extracted to `pipenv/utils/sources.py` (414 lines).
  `pipenv/project.py` shrunk from 1816 → 1531 lines (-285, far above
  the 80-line floor).

  **Naming-collision resolution**: the pre-existing `project.sources`
  property (returning a list of source dicts) was renamed to
  `project.sources.all`; `project.sources` itself now returns the
  `Sources` subsystem instance via `@cached_property`. Other
  renames follow the same dotted pattern: `project.sources_default`
  → `project.sources.default`, `project.pipfile_sources()` →
  `project.sources.pipfile_sources()`. `SourceNotFound` was moved
  to `pipenv/utils/sources.py` and re-exported from
  `pipenv/project.py` to keep `from pipenv.project import
  SourceNotFound` working (one external caller in `utils/indexes.py`).

  16 new tests in `tests/unit/test_sources.py`. Caller migrations
  across `pipenv/{environment,resolver}.py`,
  `pipenv/routines/install.py`,
  `pipenv/utils/{dependencies,indexes,requirements,resolver,virtualenv}.py`,
  plus two test files updated to match. Pipenv install --help exits 0.

  Helper-bucket methods (`path_to`, `prepend_hash_types`,
  `get_file_hash`) stayed on `Project` per the T_D.1 sign-off §8.5.
- **files edited/created**:
  - `pipenv/utils/sources.py` (new, 414 lines)
  - `pipenv/project.py` (heavy: -285 lines net)
  - `pipenv/environment.py`, `pipenv/resolver.py`,
    `pipenv/routines/install.py`,
    `pipenv/utils/{dependencies,indexes,requirements,resolver,virtualenv}.py`
    (caller migrations)
  - `tests/unit/test_sources.py` (new, 16 tests)
  - `tests/unit/{test_resolver_regressions,test_utils}.py` (test updates)

#### T_D.3 .. T_D.6: Remaining `Project` subsystem extractions (regenerated)

**Regenerated 2026-05-12 after T_D.2 proved the extraction pattern.**
Per the T_D.1 §8 sign-off: no delegating wrappers, no
`DeprecationWarning`, no two-phase rollout — extract AND migrate every
internal caller in the same PR.

**Parallelism reality**: each of the four remaining subsystem extractions
heavily modifies `pipenv/project.py` and migrates internal callers
across many files. Two parallel extractions would race on `project.py`.
The maintainer asked for "as parallel as possible"; in practice that
collapses to **strict serialization** for the four tasks. Each is ~1
working session of agent time; total expected: 4 sequential tasks.

**Order recommendation**: smallest-and-simplest first to keep the
pattern tight, then ramp up. The four tasks in proposed order:

1. **T_D.3 — Settings (smallest, lowest risk)**
2. **T_D.4 — VenvLocator**
3. **T_D.5 — Lockfile** (deferred pylock-awareness per maintainer
   sign-off: extract `Pipfile.lock`-only behaviour; pylock support
   addressed in 2027 when the format flip happens)
4. **T_D.6 — Pipfile (largest, most coupled)**

If a different order is preferred at execution time, it doesn't affect
the design — the four are independent of each other once the
`project.sources` precedent is in place.

#### T_D.3: Extract `Settings` subsystem
- **depends_on**: [T_D.2]
- **location**: `pipenv/utils/settings.py` (new) + `pipenv/project.py`
  + every internal caller of the migrating methods.
- **description**:
  Extract the 3 `Settings`-classified methods from `Project` into a
  new `Settings` class under `pipenv/utils/settings.py`. Access via
  `@cached_property` on `Project`. T_D.1 §2 cluster identified
  `Settings` as a tight 3-method bucket: settings-related accessors
  that compose `self.s.PIPENV_*` env-var values with the
  `[pipenv]` section of the Pipfile.
- **validation**: `pipenv/project.py` lost the 3 methods (and any
  associated state); new module has its own test file; every
  caller updated; unit suite green.
- **status**: Completed (commit 0b8b5830)
- **log**:
  Extracted `Settings` to `pipenv/utils/settings.py` (130 lines).
  `pipenv/project.py:settings`, `Project.update_settings`, and
  `Project.use_pylock` removed; `Project.settings` becomes a
  `@cached_property` returning a `Settings(self)` instance.

  **Naming-collision resolution: Option A (Mapping-shaped subsystem)**.
  `Settings` subclasses `collections.abc.MutableMapping`, so every
  existing `project.settings.get(key, default)` /
  `key in project.settings` / `project.settings[key]` caller works
  unchanged — the subsystem instance has `.get`, `__getitem__`,
  `__iter__`, `__len__`, `__contains__`. Only the writer
  (`update_settings`) and the typed `use_pylock` accessor needed
  caller-site migration. This was a materially smaller migration
  than T_D.2's `sources` rename and produces a cleaner public surface.

  Migration sites: `pipenv/routines/install.py` (2 sites:
  `update_settings(...)` → `settings.update(...)`,
  `project.use_pylock` → `project.settings.use_pylock`),
  `pipenv/project.py` (2 internal references), and
  `tests/integration/test_pylock.py` (2 sites). Zero `.get(...)`
  callers needed migration.

  10 new tests in `tests/unit/test_settings.py`.
- **files edited/created**:
  - `pipenv/utils/settings.py` (new, 130 lines)
  - `pipenv/project.py` (-5 lines net; 1526 → from 1531 after T_D.2)
  - `pipenv/routines/install.py` (2 migration sites)
  - `tests/unit/test_settings.py` (new, 10 tests)
  - `tests/integration/test_pylock.py` (2 migration sites)

  *(T_D.3's commit accidentally swept in T_E.2's `install.py` import
  hunks due to the parallel-collision pattern — see the commit log.
  Net state is correct; both task acceptance criteria satisfied in
  the final tree.)*

#### T_D.4: Extract `VenvLocator` subsystem
- **depends_on**: [T_D.3]
- **location**: `pipenv/utils/venv_locator.py` (new) + `pipenv/project.py`
  + every internal caller of the migrating methods.
- **description**:
  Extract the 13 `VenvLocator`-classified methods from `Project`.
  Per T_D.1 §6.1: `VenvLocator` is currently read-only (no writers
  in this bucket; venv *creation* happens in `routines/`), so no
  split into `Locator` + `Bootstrap` is needed.
- **validation**: same shape as T_D.3.
- **status**: Completed (commit `cb349450`).
- **log**:
  Third Initiative D extraction. The 13 `VenvLocator`-classified
  methods + 4 private helpers (`_sanitize`, `_get_virtualenv_hash`,
  `_pipfile_venv_in_project`, `_which`) moved into a new
  `pipenv.utils.venv_locator.VenvLocator` class accessed via the
  `@cached_property` `Project.venv_locator`.

  **Naming-collision resolution: Option B (rename the API surface)**,
  matching the T_D.2 Sources pattern. The `virtualenv_` prefix on
  the old `Project` surface drops because the subsystem itself is
  named `venv_locator`:

  - `project.virtualenv_location` → `project.venv_locator.location`
  - `project.virtualenv_exists` → `project.venv_locator.exists`
  - `project.virtualenv_name` → `project.venv_locator.name`
  - `project.virtualenv_src_location` → `project.venv_locator.src_location`
  - `project.virtualenv_scripts_location` → `project.venv_locator.scripts_location`
  - `project.download_location` → `project.venv_locator.download_location`
  - `project.proper_names_db_path` → `project.venv_locator.proper_names_db_path`
  - `project.is_venv_in_project()` → `project.venv_locator.is_venv_in_project()`
  - `project.get_location_for_virtualenv()` → `project.venv_locator.get_location()`
  - `project.finders` / `.finder` → `project.venv_locator.finders` / `.finder`
  - `project.which(...)` / `.python(...)` → `project.venv_locator.which(...)` / `.python(...)`
  - `project._which(...)` → `project.venv_locator._which(...)`

  The three `__init__`-set cache attributes (`_virtualenv_location`,
  `_download_location`, `_proper_names_db_path`) moved to
  `VenvLocator` instance state. The `proper_names` and
  `register_proper_name` methods stayed on `Project` (Pipfile-bucket
  per T_D.1 inventory) but now read the proper-names DB path through
  `self.venv_locator.proper_names_db_path`.

  Caller migration in the same PR per T_D.1 §8.4 sign-off — no
  holding-pattern wrappers. ~38 sites migrated across
  `pipenv/cli/command.py`, `pipenv/routines/{graph,install,lock,
  shell,uninstall,update}.py`, `pipenv/utils/{pip,pipfile,project,
  resolver,shell,virtualenv}.py`, `tests/integration/test_project.py`,
  and three `tests/unit/` mock-side migrations.

  `pipenv/project.py` shrinks by 245 net lines (1526 → 1281).
  `VenvLocator` is 431 lines in `pipenv/utils/venv_locator.py`.
  Module-level imports purged from `project.py`: `base64`, `fnmatch`,
  `operator`, `re`, `find_windows_executable`, `get_workon_home`,
  `is_virtual_environment`, `looks_like_dir`, `system_which`,
  `virtualenv_scripts_dir`.

  Behaviour-preserving: every method's logic is a relocation. Same
  env-var precedence (`VIRTUAL_ENV` short-circuit, then
  `PIPENV_VENV_IN_PROJECT`, then Pipfile `[pipenv]` setting, then
  `.venv` autodetect). Same Pipfile-hash seed in `_get_virtualenv_hash`.
  Same mkdir-on-access for `src_location` / `download_location` /
  `proper_names_db_path`.

  17 new tests in `tests/unit/test_venv_locator.py` covering the
  constructor, the `@cached_property` accessor, env-var-vs-Pipfile
  precedence for `is_venv_in_project`, the `VIRTUAL_ENV`
  short-circuit, `location` caching, mkdir-on-access semantics,
  `PIPENV_CUSTOM_VENV_NAME` / `PIPENV_PYTHON` name hooks, and
  `which` / `_which` fallback paths. Full unit suite green
  (677 passed, 9 skipped).
- **files edited/created**:
  - `pipenv/utils/venv_locator.py` (new, 431 lines)
  - `pipenv/project.py` (-245 lines net; 1526 → 1281)
  - `pipenv/cli/command.py` (6 migration sites)
  - `pipenv/routines/{graph,install,lock,shell,uninstall,update}.py`
    (10 migration sites)
  - `pipenv/utils/{pip,pipfile,project,resolver,shell,virtualenv}.py`
    (15 migration sites)
  - `tests/integration/test_project.py` (1 migration site)
  - `tests/unit/test_credential_safety.py`,
    `tests/unit/test_install_error_context.py`,
    `tests/unit/test_utils.py` (mock-side migrations)
  - `tests/unit/test_venv_locator.py` (new, 17 tests)

#### T_D.5: Extract `Lockfile` subsystem (`Pipfile.lock`-only)
- **depends_on**: [T_D.4]
- **location**: `pipenv/utils/lockfile.py` (new) + `pipenv/project.py`
  + every internal caller.
- **description**:
  Extract the 13 `Lockfile`-classified methods from `Project`.
  **Per T_D.1 §8.1 maintainer sign-off**: pylock.toml support is
  NOT folded into this extraction. The new `Lockfile` subsystem
  handles only the legacy `Pipfile.lock` format. When pylock.toml is
  promoted to first-class (anticipated 2027), the boundary set up
  here will either grow a per-format dispatch layer or sprout a
  sibling `PylockLock` class — that's a future-T_D.5 decision, not
  this one's. Add `TODO(pylock)` tags at the format-detection seams
  so they're greppable in 2027.
- **validation**: same shape as T_D.3; plus `TODO(pylock)` tags
  present at the future format-detection seams.
- **status**: Completed (2026-05-12)
- **log**:
  - 2026-05-12: Extracted `Lockfile` subsystem to
    `pipenv/utils/lockfile.py` (354 lines). 13 methods relocated:
    `lockfile_location` -> `location`, `lockfile_exists` -> `exists`,
    `any_lockfile_exists` -> `any_exists`, `pylock_location` /
    `pylock_exists` / `pylock_output_path` (unchanged names),
    `lockfile_content` -> `content`, `lockfile_package_names` ->
    `package_names`, `lockfile(categories=...)` ->
    `as_dict(categories=...)` (callable-method to subsystem-method
    rename to free up `project.lockfile` for the subsystem accessor),
    `get_lockfile_meta` -> `meta`, `get_lockfile_hash` -> `hash`,
    `load_lockfile` -> `load`, `write_lockfile` -> `write`. The
    orchestrating `get_or_create_lockfile` stays on `Project`
    (coordinator bucket per T_D.1 §2). `pipenv/project.py` shrinks
    by 173 net lines (1281 -> 1108). 10 distinct `# TODO(pylock):`
    annotations placed at the format-detection seams in the new
    module. 17 new unit tests in `tests/unit/test_lockfile.py`;
    full unit suite green (816 passed, 9 skipped). `pipenv lock`
    smoke test produces a valid `Pipfile.lock`.
- **files edited/created**:
  - `pipenv/utils/lockfile.py` (new, 354 lines)
  - `tests/unit/test_lockfile.py` (new, 228 lines, 17 tests)
  - `pipenv/project.py` (-173 net lines)
  - `pipenv/help.py`, `pipenv/utils/sources.py`,
    `pipenv/routines/{audit,check,clean,install,lock,requirements,scan,sync,uninstall,update}.py`
  - `tests/integration/{test_install_markers,test_lockfile,test_pylock}.py`,
    `tests/unit/{test_do_update_context_routing,test_lock_sync_uninstall_context_routing,test_pylock}.py`

#### T_D.6: Extract `Pipfile` subsystem (largest, most coupled)
- **depends_on**: [T_D.5]
- **location**: `pipenv/utils/pipfile.py` (existing — already contains
  a partial `Pipfile` scaffolding) + `pipenv/project.py` + every
  internal caller.
- **description**:
  Extract the 38 `Pipfile`-classified methods from `Project`. This
  is the biggest of the four extractions and the most coupled
  (cache invalidation via `_parsed_pipfile_mtime_ns`, writer
  methods consumed by `Sources`/`Settings`, hash computation
  consumed by `Lockfile`).

  Cross-subsystem references (per T_D.1 §3):
  - `Pipfile.write_toml` must invalidate `Sources` and `Settings`
    cached property handles on `Project` (since both `Sources`
    writers and `Settings` writers route through it).
  - `Lockfile.get_lockfile_meta` needs `Pipfile.calculate_pipfile_hash`.
  These are constructor-injected (or `Sources(project=...)` style)
  rather than via module-level imports.

  Helper-bucket methods (`path_to`, `prepend_hash_types`,
  `get_file_hash`) per T_D.1 §8.5 — orchestrator's standing
  recommendation: revisit AFTER T_D.6 lands, when `Project` is at
  its leanest. By that point most helpers will plausibly want to
  move to `pipenv/utils/` as free functions; but it's a judgement
  call to make with the fullest picture.
- **validation**: same shape as T_D.3; plus `project.py` is at its
  intended lean shape (probably ≤ 600 lines after this); plus a
  paragraph in the commit message recording the helper-bucket
  disposition (move out or keep) and rationale.
- **status**: Not Completed
- **log**:
- **files edited/created**:

#### T_E.1: Define canonical requirement-model API target
- **depends_on**: [T_B.7]
- **location**: `docs/dev/initiative-e-design.md` (new, temporary).
- **description**:
  With the Initiative B triage decisions in hand, propose the canonical
  API on `dependencies.py`. Identify which symbols from
  `requirementslib.py` and `requirements.py` will move, which will be
  vendored, and which will be deleted. Sequence the moves. Full
  execution plan is regenerated after this lands.
- **validation**: Design doc lists every in-scope symbol with a target
  location and sequencing notes.
- **status**: Completed (commit 8ff77143) — **awaits maintainer
  sign-off before T_E.2 begins**
- **log**:
  692-line proposal. Post-Wave-1c symbol counts verified by grep:
  `dependencies.py` 54 public symbols (canonical home);
  `requirements.py` 8 funcs + `BAD_PACKAGES` (9 import statements
  across 8 files); `requirementslib.py` 7 public symbols (was 20
  pre-Wave-1c, now down to 4 importing files); `markers.py` ~30
  helpers + 2 classes (3 importing files).

  Sequenced into 6 follow-up tasks (T_E.2 .. T_E.7):
  - T_E.2: move 6 Pipfile/lockfile bridges + `BAD_PACKAGES` from
    `requirements.py` → `dependencies.py`; renames
    `add_index_to_pipfile` → `add_index_to_pipfile_with_trust_check`.
  - T_E.3: move `is_vcs`, `add_ssh_scheme_to_git_uri`, `merge_items`,
    `get_pip_command` from `requirementslib.py` → `dependencies.py`.
  - T_E.4: relocate `unpack_url`/`get_http_url` pip-internal fork
    pair (new `pipenv/utils/unpack.py` preferred); deletes empty
    `requirementslib.py`.
  - T_E.5: move `BAD_PACKAGES` co-location (folded into T_E.2).
  - T_E.6: `add_index_to_pipfile` rename (folded into T_E.2).
  - T_E.7: optional rename `requirements.py` → `redact.py` once it
    shrinks to two `redact_*` forks.

  Recommendations:
  - `markers.py` stays unchanged (owned glue, no upstream lineage,
    limited cross-module reuse — folding wouldn't reduce ambiguity).
  - `redact_netloc`/`redact_auth_from_url` stay in `requirements.py`
    (pip-internal forks with load-bearing behavioural divergence; no
    thematic fit with the requirement model).
  - `normalize_name`/`pep423_name` overlap already resolved under
    Wave 1c (commit e874e9d0); explicitly out of scope.

  8 decision questions for maintainer sign-off (canonical home shape,
  filename fates, rename target, unpack home, markers fold-in
  question, redact stay-or-move, test-pinning approach).
- **files edited/created**:
  - `docs/dev/initiative-e-design.md` (new, 692 lines + 50-line sign-off
    addendum)

#### T_E.2: Move Pipfile/lockfile bridges to `dependencies.py`
- **depends_on**: [T_E.1]
- **location**: `pipenv/utils/requirements.py` (source), `pipenv/utils/dependencies.py` (destination),
  and caller files: `pipenv/utils/{pipfile,locking}.py`,
  `pipenv/routines/{install,update,audit,requirements,clean,uninstall,graph}.py`.
- **description**:
  Per T_E.1 sign-off §3: move 6 Pipfile/lockfile bridge functions
  plus `BAD_PACKAGES` from `requirements.py` into `dependencies.py`
  (canonical home). Rename the module-level `add_index_to_pipfile`
  to `add_index_to_pipfile_with_trust_check` to disambiguate from
  `Project.add_index_to_pipfile`. Caller migration in the same PR
  per the no-shim posture.
- **validation**: every moved symbol importable from
  `pipenv.utils.dependencies`; `requirements.py` reduced to only
  the `redact_*` fork pair; unit suite green.
- **status**: Completed (commit caa72db6)
- **log**:
  Seven symbols moved:
  - `import_requirements` (~60 lines)
  - `add_index_to_pipfile` → **`add_index_to_pipfile_with_trust_check`**
    (~17 lines; rename only, body identical)
  - `requirement_from_lockfile` (~88 lines; local imports of
    `is_editable_path`/`is_star`/`normalize_vcs_url` dropped since
    they're now intra-file)
  - `requirements_from_lockfile` (~13 lines)
  - `requirement_from_pipfile` (~109 lines; same local-import drop)
  - `requirements_from_pipfile` (~21 lines)
  - `BAD_PACKAGES` constant tuple (~7 lines)

  Caller migrations across 9 files: `pipfile.py`, `locking.py`,
  `routines/{install,update,audit,requirements,graph,clean,uninstall}.py`,
  plus 3 integration test files (`test_import_requirements.py`,
  `test_requirements.py`, `test_lockfile.py`).

  `requirements.py` is now 72 lines holding only the two `redact_*`
  fork functions plus their provenance docstrings (per T_E.1 §6
  sign-off). T_E.7 will optionally rename this file to `redact.py`
  per T_E.1 §7 sign-off if it still makes sense.

  21 new tests in `tests/unit/test_dependencies_bridges.py`: 7
  import-shape pins, 2 sanity checks that old paths are gone, 12
  light behaviour pins covering string/dict/star/version paths and
  the trusted-host vs untrusted-host branches of
  `add_index_to_pipfile_with_trust_check`.

  Subtle pre-existing quirk surfaced (not fixed): an unconditional
  `==` prefix in `requirement_from_lockfile`'s bare-version-string
  branch produces `===` when the input already starts with `==`.
  Preserved as-is for behaviour-preservation; documented as a
  future cleanup candidate.

  *(T_D.3 ran in parallel and committed first; T_D.3's commit
  accidentally swept in T_E.2's `pipenv/routines/install.py`
  caller-import hunks. T_E.2 detected the swept-up state and
  committed the remaining 14 files cleanly. Net final tree is
  correct.)*
- **files edited/created**:
  - `pipenv/utils/dependencies.py` (gains 7 moved symbols, +579 lines net for the move)
  - `pipenv/utils/requirements.py` (-361 lines; now 72 lines holding only the redact pair)
  - `pipenv/utils/{pipfile,locking}.py` (caller imports)
  - `pipenv/routines/{install,update,audit,requirements,graph,clean,uninstall}.py` (caller imports + 1 rename site each in install/update)
  - `tests/unit/test_dependencies_bridges.py` (new, 21 tests)
  - `tests/integration/{test_import_requirements,test_requirements,test_lockfile}.py` (test imports)

#### T_E.3: Move predicates and helpers out of `requirementslib.py`
- **depends_on**: [T_E.2]
- **location**: `pipenv/utils/requirementslib.py` (source),
  `pipenv/utils/dependencies.py` (destination), plus caller files
  `pipenv/utils/{locking,pipfile}.py`, `pipenv/project.py`,
  `tests/unit/{test_requirementslib,test_utils,test_dependencies_bridges}.py`.
- **description**:
  Per T_E.1 sign-off §3: move four single-line/short helpers
  (`is_vcs`, `add_ssh_scheme_to_git_uri`, `merge_items`,
  `get_pip_command`) from `requirementslib.py` into `dependencies.py`
  (canonical home). `merge_items` brings its two private helpers
  (`_merge_into`, `_new_container_like`) with it. Caller migration
  in the same PR per the no-shim posture. After this commit
  `requirementslib.py` contains only the `unpack_url`/`get_http_url`
  pip-internal fork pair (plus the `VCS_SCHEMES` constant they need);
  T_E.4 will relocate that pair to a new `pipenv/utils/unpack.py`
  and delete the empty `requirementslib.py` shell.
- **validation**: every moved symbol importable from
  `pipenv.utils.dependencies`; `requirementslib.py` reduced to the
  two pip-internal forks; unit suite green for the moved-symbol
  tests; the four removed symbols no longer exist on
  `pipenv.utils.requirementslib`.
- **status**: Completed
- **log**:
  Four symbols moved (six lines of code including the two private
  helpers that travel with `merge_items`):
  - `is_vcs` (~14 lines) — placed alongside `extract_vcs_url` since
    it shares VCS-URL semantics. Uses the existing `typing.Mapping`
    import in `dependencies.py` (works with isinstance in Py3.9+);
    `is_valid_url` newly imported from `.internet`.
  - `add_ssh_scheme_to_git_uri` (~14 lines) — placed with `is_vcs`
    (intra-module dependency; the existing cross-module import in
    `dependencies.py` becomes a local reference).
  - `merge_items` (~33 lines) + `_merge_into` (~17 lines) +
    `_new_container_like` (~17 lines) — placed just before
    `import_requirements` (the next dict-merge-shaped routine).
  - `get_pip_command` (~9 lines) — placed near `determine_package_name`
    (its only in-tree caller, intra-module after the move);
    `InstallCommand` newly imported.

  Caller migrations across 5 files:
  - `pipenv/utils/locking.py` (folded `is_vcs`, `merge_items` into
    the existing `from pipenv.utils.dependencies import (...)` block)
  - `pipenv/utils/pipfile.py` (same — folded into existing
    `dependencies` import block)
  - `pipenv/project.py` (one-line late-import edit at
    `_get_vcs_packages`; narrow scoped to that import line only
    to avoid T_D.4 conflicts)
  - `tests/unit/test_requirementslib.py` (docstring + import re-target)
  - `tests/unit/test_utils.py` (the `test_is_vcs` late import)

  `requirementslib.py` shrank from 275 lines to 144 (-131 lines).
  After T_E.3 only one importer of `requirementslib` remains in the
  in-tree codebase (`dependencies.py` for `unpack_url`); T_E.4
  will close that out.

  10 new tests in `tests/unit/test_dependencies_bridges.py`: 4
  import-shape pins, 1 sanity check that the old paths are gone,
  and 5 light behavioural pins (`is_vcs` mapping + string-with-ssh
  branches, `add_ssh_scheme_to_git_uri` round-trip, `merge_items`
  recursive last-write-wins + empty-list contract, `get_pip_command`
  returns a usable `InstallCommand`).
- **files edited/created**:
  - `pipenv/utils/dependencies.py` (gains 4 moved symbols + 2
    private helpers; new `InstallCommand` + `is_valid_url` imports;
    drops the cross-module `requirementslib` import for the moved
    symbols)
  - `pipenv/utils/requirementslib.py` (-131 lines; now 144 lines
    holding only the `unpack_url`/`get_http_url` fork pair + the
    `VCS_SCHEMES` constant they need)
  - `pipenv/utils/{locking,pipfile}.py` (caller imports folded
    into the existing `dependencies` import block)
  - `pipenv/project.py` (one-line late-import edit at
    `_get_vcs_packages`)
  - `tests/unit/test_dependencies_bridges.py` (extended with 10
    T_E.3 tests; module docstring updated)
  - `tests/unit/test_requirementslib.py` (docstring + import
    re-target to the new location)
  - `tests/unit/test_utils.py` (one-line late-import edit in
    `test_is_vcs`)

#### T_E.4: Relocate the pip-internal fork pair; delete `requirementslib.py`
- **depends_on**: [T_E.3]
- **location**: `pipenv/utils/requirementslib.py` (source, deleted),
  `pipenv/utils/unpack.py` (destination, new), plus caller file
  `pipenv/utils/dependencies.py` and test files
  `tests/unit/{test_unpack,test_dependencies_bridges}.py`.
- **description**:
  Per T_E.1 sign-off §6 question 4 ("APPROVED as proposed: new
  `pipenv/utils/unpack.py`"), relocate the two pip-internal fork
  helpers (`unpack_url`, `get_http_url`) plus the local
  `VCS_SCHEMES` set out of `requirementslib.py` and into a new
  `pipenv/utils/unpack.py`. The new module's top-level docstring
  records the pip-internal-fork provenance and points at the design
  docs (`initiative-b-triage`, `initiative-e-design` §T_E.4). The
  load-bearing per-function provenance commentary (VCS-link
  divergence in `unpack_url`; `globally_managed=False` in
  `get_http_url`) is preserved verbatim from the source module.

  After the move, `requirementslib.py` has zero remaining symbols
  and is deleted in the same commit. The sole in-tree caller
  (`pipenv/utils/dependencies.py:41`) is migrated to import from
  the new location. This is the final structural move of
  Initiative E; the only remaining E task is the optional T_E.7
  `requirements.py` → `redact.py` rename.

  `VCS_SCHEMES` placement: kept alongside `unpack_url` in
  `unpack.py` (not promoted to `pipenv/utils/constants.py`).
  Reason: zero cross-module callers (only `unpack_url` reads it).
  The `constants.py` `VCS_SCHEMES` is a distinct list of
  `vcs+transport` strings that does NOT include the bare
  `git`/`hg`/`svn`/`bzr` schemes the unpack set needs, so the
  two cannot be unified without changing the semantics of one
  of the consumers.
- **validation**: `pipenv/utils/requirementslib.py` no longer exists;
  `unpack_url` and `get_http_url` importable from
  `pipenv.utils.unpack`; sole caller `pipenv/utils/dependencies.py`
  imports from the new location; unit suite green; zero in-tree
  importers of `pipenv.utils.requirementslib` remain (excluding
  negative-assertion test calls that explicitly check the module
  is gone).
- **status**: Completed
- **log**:
  Three symbols moved:
  - `unpack_url` (~63 lines incl. provenance docstring) — relocated
    verbatim; no behavioural change.
  - `get_http_url` (~38 lines incl. provenance docstring) —
    relocated verbatim; no behavioural change.
  - `VCS_SCHEMES` (25-element set used only by `unpack_url`) —
    relocated verbatim; intentionally kept distinct from the
    `pipenv.utils.constants.VCS_SCHEMES` list, which serves a
    different consumer set (`dependencies.determine_vcs_specifier`,
    `is_vcs`).

  Caller migrations (1 file):
  - `pipenv/utils/dependencies.py` (one-line import edit:
    `from pipenv.utils.requirementslib import unpack_url`
    → `from pipenv.utils.unpack import unpack_url`)

  `pipenv/utils/requirementslib.py` deleted (was 144 lines after
  T_E.3; now zero — the file does not exist).

  8 new tests in `tests/unit/test_unpack.py`:
  - 5 import-shape pins (`unpack_url` and `get_http_url`
    importable from the new home; `VCS_SCHEMES` is a set with the
    bare-scheme entries; legacy `requirementslib` module is gone;
    `dependencies` sources `unpack_url` from the new home).
  - 3 behavioural smoke tests (VCS-link `File`-not-`None` return;
    bare `git` scheme dispatches to the VCS branch via our local
    set; `get_http_url` constructs `TempDirectory` with
    `globally_managed=False`).

  Also updated 1 T_E.3-era test in
  `tests/unit/test_dependencies_bridges.py`: the
  `test_old_requirementslib_module_no_longer_exports_moved_symbols`
  test was rewritten to assert the module itself is gone (a strict
  superset of the prior symbol-by-symbol check, which would now
  crash on `ModuleNotFoundError` at import time).

  Initiative E structural work is complete after T_E.4. T_E.5 and
  T_E.6 were folded into T_E.2. T_E.7 (optional rename
  `requirements.py` → `redact.py`) is the only remaining task and
  has no dependents.
- **files edited/created**:
  - `pipenv/utils/unpack.py` (new — 174 lines, all pip-internal-fork
    provenance preserved)
  - `pipenv/utils/requirementslib.py` (deleted)
  - `pipenv/utils/dependencies.py` (one-line import edit)
  - `tests/unit/test_unpack.py` (new — 8 tests)
  - `tests/unit/test_dependencies_bridges.py` (the T_E.3 "old
    module symbols are gone" test rewritten to "module itself is
    gone")

#### T_F.1: Document current subprocess resolver protocol
- **depends_on**: [T_E.1]  (gated on E's design so we know what data
  shape will cross the boundary)
- **location**: `docs/dev/initiative-f-protocol.md` (new, temporary).
- **description**:
  Write down what currently crosses the in-process / subprocess boundary
  in `pipenv/resolver.py` ↔ `pipenv/utils/resolver.py`: the JSON shape,
  the argv contract, the environment variables, the exit codes. This
  is a doc-only PR; no code change. Used as input for the typed-schema
  design in subsequent tasks.
- **validation**: Doc describes every field crossing the boundary with
  type and provenance.
- **status**: Completed (commit 2a7aa81b)
- **log**:
  588-line protocol reference covering all 9 required sections.
  Coverage counts: 10 argv elements (3 dead-surface flags called out);
  11 explicit env vars + 4 implicit; 12 JSON top-level keys per entry;
  10 divergent in-process-vs-subprocess helper pairs flagged for
  T_F.2+ fold-in; 11 decisions deferred to T_F.2.

  Substantive findings worth surfacing independently of T_F.2:
  - **No subprocess timeout** at `pipenv/utils/resolver.py:1222`
    (`c.wait()`) — a hung mirror means pipenv hangs forever. This
    is a real user-facing reliability issue independent of the
    protocol-typing refactor.
  - **No schema version, no envelope, no success/failure
    discriminator** in the current protocol. Non-zero exit is the
    only failure signal; resolution-impossible vs subprocess-crash
    are indistinguishable to the parent.
  - **Three dead argv flags** in `pipenv/resolver.py`:
    `--parse-only`, `--pipenv-site`, and positional `packages` (always
    shadowed by `--constraints-file` in production). Cruft to remove
    independent of T_F.2.
  - The biggest fold-target between in-process and subprocess paths
    is **two competing requirement-output formatters**:
    `Entry.get_cleaned_dict` (subprocess side,
    `pipenv/resolver.py:288-320`) vs `format_requirement_for_lockfile`
    (parent side, `pipenv/utils/locking.py:46-160`). They overlap
    heavily.
  - The `PIPENV_RESOLVER_PARENT_PYTHON` "in-process" branch is a
    debug bypass, not architectural cleanliness — both paths still
    call `resolver.resolve_packages` and diverge only in
    serialization.
- **files edited/created**:
  - `docs/dev/initiative-f-protocol.md` (new, 588 lines)

#### T_F.2: Typed resolver subprocess protocol — design (sign-off gate)
- **depends_on**: [T_F.1]
- **location**: `docs/dev/initiative-f-typed-design.md` (new, permanent
  until superseded by T_F.3 execution).
- **description**:
  Design-only proposal for the typed `ResolverRequest` /
  `ResolverResponse` pair that T_F.3 will introduce. Resolves the 11
  decisions deferred to T_F.2 by F.1 §9, picks the canonical
  replacement for the two competing requirement formatters
  (`Entry.get_cleaned_dict` and `format_requirement_for_lockfile` — a
  third unified `LockedRequirement.from_install_requirement`
  constructor that lives in the schema module), specifies the
  one-shot migration (no backwards-compat shim, per T_C.3 §9 / T_E.1
  §6), and surfaces 10 numbered open questions for the maintainer.
- **validation**: Doc-only PR; `python -c "import ast;
  ast.parse(open('pipenv/resolver.py').read())"` still works because
  no production code was touched. Doc is 400–800 lines and follows
  the T_C.3 / T_E.1 sign-off addendum shape.
- **status**: Completed (commit 921212e5); **awaits maintainer
  sign-off** before T_F.3 execution begins.
- **log**:
  719-line design doc covering envelope, discriminator, canonical
  formatter, migration path, resolution of F.1's 11 deferred
  decisions, test plan, and 10 sign-off questions.

  Headline decisions proposed:
  - Stdlib `@dataclass(frozen=True)` only — no new vendored
    dependencies (no pydantic, no msgspec, no attrs).
  - `schema_version: int = 1` as the first field on both envelopes;
    mismatch is a hard reject (structured `InternalError` response +
    exit non-zero).
  - Discriminated `ResolverSuccess | ResolutionError | InternalError`
    union written to `--response-file` on exit 0; non-zero exit
    reserved for genuine subprocess crashes.
  - Single `--request-file <path>` tempfile carries all input;
    `--pre`, `--clear`, `--system`, `--verbose`, `--category`,
    `--constraints-file`, `--resolved-default-deps-file`,
    `--parse-only`, `--pipenv-site`, positional `packages`, and the
    `which()` stub all deleted in T_F.3.
  - `PIPENV_RESOLVER_PYTHON_VERSION`, `PIPENV_EXTRA_PIP_ARGS`,
    `PIPENV_SITE_DIR` env-var hops fold into typed request fields.
  - Two output formatters collapse into one new
    `LockedRequirement.from_install_requirement` constructor;
    both `Entry.get_cleaned_dict` and `format_requirement_for_lockfile`
    are deleted.
  - In-process branch (`PIPENV_RESOLVER_PARENT_PYTHON=1`) preserved
    untouched in T_F.3; fold deferred to T_F.4 / T_F.5.
  - Wall-clock timeout reserved on schema (`deadline_seconds`) but
    not enforced in T_F.3.

  Open questions for sign-off (10): schema module home (resolver-as-
  package vs. utils file); schema-version-mismatch behaviour;
  `to_lockfile_dict` return type; news-fragment policy; `no_binary`
  field vs. recompute; whether T_F.3 also folds the in-process
  branch; constraints comma-escape regression test; schema-version
  bump policy on additive fields; `Diagnostics.resolver_log` vs.
  stderr; one or two tempfiles.
- **files edited/created**:
  - `docs/dev/initiative-f-typed-design.md` (new, 719 lines)

#### T_F.3: Execute the typed resolver subprocess schema
- **depends_on**: [T_F.2]
- **location**: `pipenv/resolver/` (new package — `schema.py`, `main.py`, `__init__.py`); `pipenv/utils/resolver.py`; `pipenv/utils/locking.py`; `pyproject.toml` (console-script entry); tests under `tests/unit/test_resolver_schema.py`, `tests/unit/test_resolver_parent_dispatch.py`, `tests/unit/test_resolver_protocol_smoke.py`, `tests/integration/test_resolver_protocol.py`; golden fixtures under `tests/unit/fixtures/resolver_schema/` and `tests/integration/fixtures/resolver_protocol/`; `news/T_F.3.behavior.rst`.
- **description**:
  Single-PR execution of the T_F.2 design. Introduces the typed
  `ResolverRequest` / `ResolverResponse` envelope + discriminated
  `ResolverResult`; folds `Entry.get_cleaned_dict` and
  `format_requirement_for_lockfile` into the new unified
  `LockedRequirement.from_install_requirement` constructor; drops the
  three env-var hops and the dead argv flags; rewrites both the
  subprocess entry and the parent dispatcher around the typed envelope;
  migrates the in-process branch to the new types (without folding it
  with the subprocess branch — that's T_F.4); pins the JSON wire shape
  with a golden-fixture integration test + a `PIPENV_REGEN_PROTOCOL_FIXTURES`
  regen mechanism. Execution structured as a 4-wave swarm (`docs/dev/initiative-f-execution-plan.md`).
- **validation**:
  - 758 unit tests pass (was 677 baseline pre-T_F.3). +81 tests from the schema + parity + dispatch + comma-in-marker + protocol-smoke + parent-dispatch suites.
  - Integration test pins the JSON wire shape (3 consecutive runs ~1.1s each).
  - `pipenv lock` smoke produces byte-identical lockfiles via subprocess AND `PIPENV_RESOLVER_PARENT_PYTHON=1` in-process paths.
  - Acceptance greps clean: zero `Entry.get_cleaned_dict`, zero `format_requirement_for_lockfile`, zero `PIPENV_RESOLVER_PYTHON_VERSION`/`PIPENV_EXTRA_PIP_ARGS`/`PIPENV_SITE_DIR` references, zero `--parse-only`/`--pipenv-site`/`--constraints-file`/`--resolved-default-deps-file`/`--category` argv references in `pipenv/resolver/main.py`.
- **status**: Completed (commits listed below; branch `maintenance/code-cleanup-phase3-resolver-typed-schema-2026-05`).
- **log**:
  Wave A (foundation): `85993ca4` schema module + canonical formatter + 27 golden snapshots (16 `format_requirement_for_lockfile` cases + 11 `entry_get_cleaned_dict` cases); A2 absorbed into A1 because Python's import system makes `pipenv/resolver.py` and `pipenv/resolver/` mutually exclusive. Re-export shim at `pipenv/resolver/__init__.py` kept every legacy import path working.

  Wave B (parallel 3-agent): `5e6eca82` B3 (lockfile writer + 17 → 20 ported test cases); `d1563a1e` B1+B2 (subprocess entry + parent rewrite collapsed into one commit due to pre-commit stash race — functionally clean; both reviewer-friendly diffs reflected in commit message). `bfbecba4` later fixed a wave-B bug where `_main` imported the schema before `_ensure_modules()` populated `sys.path`.

  Wave C (parallel 3-agent): `0c4a11a9` schema `from_lockfile_dict` touch-up; `de3edea9` C1 + C3 (45 new schema tests including parity-against-golden + comma-in-marker per Q7); `706b7ab9` C2 integration test + golden request/response fixtures + `PIPENV_REGEN_PROTOCOL_FIXTURES` regen branch; `e891c888` C4 news fragment.

  Wave D: this entry.

  Bugs surfaced + fixed along the way: bootstrap-order bug in `_main` (`bfbecba4`) that affected any subprocess invocation lacking pipenv on `sys.path` — wave-B unit smokes missed it because `python -m pipenv.resolver.main` invocation pre-populates the path; the integration test caught it.

  Out of scope (intentionally; deferred to follow-up tasks): T_F.4 (fold in-process and subprocess branches into one implementation per the PRD acceptance criterion), wall-clock-timeout enforcement (`RequestMetadata.deadline_seconds` reserved on schema but not enforced), populating `Diagnostics.resolver_log` (reserved-but-empty per Q9), pluggable alternative resolver backends (uv etc — design shape preserves the option per typed-design §6a but explicitly not in F).
- **files edited/created**:
  - `pipenv/resolver/__init__.py` (new, re-export shim — trimmed after Wave B)
  - `pipenv/resolver/main.py` (moved from `pipenv/resolver.py`; rewritten to consume `ResolverRequest` and produce `ResolverResponse`)
  - `pipenv/resolver/schema.py` (new, 14 dataclasses + `SCHEMA_VERSION` + `from_install_requirement` + `from_lockfile_dict` / `to_lockfile_dict`)
  - `pipenv/utils/resolver.py` (parent-side rewrite — typed envelope build + dispatch + in-process-branch type migration)
  - `pipenv/utils/locking.py` (deleted `format_requirement_for_lockfile`; `prepare_lockfile` consumes `Sequence[LockedRequirement]`)
  - `pyproject.toml` (`scripts.pipenv-resolver = "pipenv.resolver.main:main"`)
  - `tests/unit/test_resolver_schema.py` (new, 62 tests covering invariants, envelope round-trip, golden-fixture parity, dispatch, schema-version-mismatch, VCS pins, comma-in-marker regression)
  - `tests/unit/test_resolver_parent_dispatch.py` (new, parent-side typed-dispatch tests)
  - `tests/unit/test_resolver_protocol_smoke.py` (new, subprocess-side typed-envelope smoke)
  - `tests/unit/fixtures/resolver_schema/{format_requirement_for_lockfile,entry_get_cleaned_dict}/*.json` (27 golden snapshots)
  - `tests/integration/test_resolver_protocol.py` (new, JSON wire-shape canary with regen branch)
  - `tests/integration/fixtures/resolver_protocol/{request,response}.json` (new, committed goldens)
  - `news/T_F.3.behavior.rst` (new, one-line behavior fragment)
  - `tests/unit/test_dependencies.py`, `tests/unit/test_resolver_regressions.py`, `tests/unit/test_locking_no_mutation.py` (legacy `Entry` / `process_resolver_results` test cases removed; mock updated for new return shape)
  - `tests/unit/test_utils.py` (17 `format_requirement_for_lockfile` cases ported to 20 typed cases)
  - `tests/unit/test_core.py` (docstring reference updated)
  - `docs/dev/initiative-f-execution-plan.md` (entry-by-entry log of each wave commit)

#### T_F.4: Fold in-process and subprocess resolver paths into one implementation
- **depends_on**: [T_F.3]
- **location**: `pipenv/resolver/core.py` (new); `pipenv/resolver/main.py` (subprocess adapter shrinks); `pipenv/utils/resolver.py` (in-process adapter); `tests/unit/test_resolver_core.py` (new, 6 tests).
- **description**:
  Completes the PRD acceptance criterion "one resolver implementation,
  two thin adapters" for Initiative F. T_F.3 introduced the typed
  `ResolverRequest` / `ResolverResponse` schema but left two near-duplicate
  plumbing chains: the subprocess entry's `_main` (marker patch +
  `resolve_packages` call + ResolverResponse wrap + exit codes) and the
  in-process debug bypass at `PIPENV_RESOLVER_PARENT_PYTHON=1` (its own
  marker patch + `resolve_packages` + exception propagation).

  This task extracts the shared logic into
  `pipenv.resolver.core.resolve_for_pipenv(request) -> ResolverResponse` —
  a single function that applies the python_marker_override via a
  context manager, dispatches to `resolve_packages` through `sys.modules`
  (so existing stub patterns keep working), and ALWAYS returns a typed
  response (never raises). Both adapters become thin wrappers:

  * Subprocess (`pipenv/resolver/main.py:_main`): read request → call
    `resolve_for_pipenv` → write response → exit code on `result.kind`.
    The duplicate `_apply_python_marker_override` helper is deleted.
  * In-process (`pipenv/utils/resolver.py:_resolve_in_process`):
    new ~28-line helper that dispatches on `response.result.kind` to
    return locked entries or raise `ResolutionFailure` / `RuntimeError`.
    The `PIPENV_RESOLVER_PARENT_PYTHON` arm of `venv_resolve_deps` is
    now one delegating line; the orphaned `from pipenv import resolver`
    import is removed.

  The unified path leaves explicit room for two queued follow-ups:
  `request.metadata.deadline_seconds` (T_F.6 timeout enforcement) and
  `Diagnostics.resolver_log` (T_F.7 structured logging). Neither is
  implemented here; both fields are already on the schema and the
  fold target consumes/emits them so future patches are additive.
- **validation**:
  - 764 unit tests pass (758 pre-fold + 6 new in `test_resolver_core.py`
    covering success → ResolverSuccess, ResolutionFailure → ResolutionError,
    arbitrary exception → InternalError, marker override applied + restored).
  - Integration test `tests/integration/test_resolver_protocol.py` (JSON
    wire-shape canary) still passes — the wire schema is untouched.
  - Manual `pipenv lock` smoke on a tiny Pipfile produces byte-identical
    lockfiles (same `_meta.hash`) via the default subprocess path AND
    `PIPENV_RESOLVER_PARENT_PYTHON=1`.
- **status**: Completed (commit `22921044`; branch
  `maintenance/code-cleanup-phase4-resolver-followups-2026-05`).
- **log**:
  - 2026-05-12 — Fold landed in one commit. Sibling agent T_F.5a
    (pluggable-backends design doc) ran concurrently on the same branch
    with no file collision (T_F.5a touched `docs/dev/` only; T_F.4
    touched code only).
- **files edited/created**:
  - `pipenv/resolver/core.py` (new, ~250 lines: `resolve_for_pipenv`,
    `_patched_marker_environment` context manager,
    `_apply_request_env`, `_dispatch_resolve_packages`)
  - `pipenv/resolver/main.py` (subprocess adapter — `_main` now reads/
    writes JSON around a single `resolve_for_pipenv` call;
    `_apply_python_marker_override` deleted; net -54 lines)
  - `pipenv/utils/resolver.py` (in-process adapter — new
    `_resolve_in_process` helper; `PIPENV_RESOLVER_PARENT_PYTHON`
    branch in `venv_resolve_deps` reduces to one delegating line;
    orphaned `from pipenv import resolver` import removed)
  - `tests/unit/test_resolver_core.py` (new, 6 tests for the fold target)

#### T_F.5a: Pluggable resolver backends — design (sign-off gate)
- **depends_on**: [T_F.3]
- **location**: `docs/dev/initiative-f-backends-design.md` (new, 948 lines).
- **description**:
  Design-only document specifying the T_F.5 architecture: a `Backend` protocol
  with pip/uv implementations under `pipenv/resolver/backends/`, a name-keyed
  registry with dispatch precedence (CLI > env > Pipfile > default), single-
  `Pipfile.lock` output with `_meta.resolver_backend` discriminator, system-uv
  (no vendoring) posture, and an 8-task execution plan (T_F.5.1 .. T_F.5.8).
  Resolves the four open questions from `initiative-f-typed-design.md` §6a
  (opt-in section, dispatch mechanism, lockfile-format discriminator,
  vendoring posture) and surfaces 10 numbered sign-off questions gating
  T_F.5 execution. Maps the WIP `origin/uv-backend` commit `22359624`
  (~969-line `pipenv/utils/uv.py` + ~241-line patches across
  routines/environments) to the post-T_F.3-schema shape; the port shrinks
  to ~450 lines of `backends/uv.py` + ~40 lines for a new
  `LockedRequirement.from_uv_package` constructor.

  Key recommendations (each requires sign-off before T_F.5 execution starts):
  Pipfile opt-in via `[pipenv] resolver_backend = "<name>"`; CLI flag
  `--backend NAME`; lockfile remains single `Pipfile.lock` with additive
  `_meta.resolver_backend` field (uv-backend lockfiles only; pip omits);
  missing-backend behaviour fails loud with install instructions; cross-
  backend re-locking is full re-resolve (lockfile is input-only); no new
  schema fields (`LockedRequirement.resolver_backend` /
  `Diagnostics.resolver_name` deferred); uv is detected via `shutil.which`,
  never vendored; test matrix runs a representative subset under both
  backends with full dual-backend coverage on a nightly cron; news fragment
  category is `.feature`.

  Explicitly out of scope for T_F.5: uv as a wheel-install backend
  (resolve-only); PEP 751 `pylock.toml` emission; entry-point plugin
  discovery; poetry/conda/pdm backends; performance benchmarking;
  `Diagnostics.resolver_log` population; structured `ConflictRecord`
  extraction from uv stderr; pipenv → uv direct-invocation (still goes
  pipenv → `pipenv-resolver` → uv until T_F.4 fold lands).
- **status**: Completed (commit `727b6540`; awaits maintainer sign-off
  before T_F.5 execution begins).
- **log**:
  - 2026-05-12 — Design doc landed (948 lines). 10 sign-off questions
    numbered for maintainer answer. Sibling agent T_F.4 (in-process /
    subprocess fold) running concurrently on the same branch; no file
    collision (T_F.4 touches `pipenv/resolver/main.py` + `pipenv/utils/
    resolver.py` + new `pipenv/resolver/core.py`; T_F.5a touches docs only).
- **files edited/created**:
  - `docs/dev/initiative-f-backends-design.md` (new, 948 lines)

#### T_F.5: Pluggable resolver backends — execution
- **depends_on**: [T_F.5a maintainer sign-off]
- **location**: NEW `pipenv/resolver/backends/__init__.py`,
  `pipenv/resolver/backends/base.py`, `pipenv/resolver/backends/pip.py`;
  `pipenv/resolver/core.py` (dispatcher); `pipenv/resolver/schema.py`
  (`ResolverOptions.backend` additive field); `pipenv/utils/settings.py`
  (`Settings.resolver`); `pipenv/utils/resolver.py` (plumbing);
  `pipenv/environments.py` (`PIPENV_RESOLVER`); `pipenv/cli/options.py`
  + `pipenv/cli/command.py` (`--resolver NAME` flag);
  `pipenv/routines/context.py` (`ExecutionOptions.resolver`);
  `pipenv/utils/pylock.py` (TODO(T_F.8) marker);
  `news/T_F.5.feature.rst`; `tests/unit/test_resolver_backends.py`.
- **description**:
  Re-scoped to **scaffolding only** per the maintainer sign-off in
  `initiative-f-backends-design.md` (2026-05-12, answer 8). The uv
  backend port and dual-backend test matrix become a future initiative
  (T_F.8 or similar). What lands in this commit: the `Backend` protocol,
  the `pip` backend wrapping the existing resolve flow, the registry,
  the `--resolver NAME` / `PIPENV_RESOLVER` / `[pipenv] resolver`
  precedence chain, the fail-loud error path for unknown / unavailable
  backends, and a news fragment.
- **status**: Complete (scaffolding shipped 2026-05-12). The uv backend
  port and dual-backend test matrix become T_F.8 (or similar) in a
  later iteration.
- **log**:
  - 2026-05-12 — Scaffolding landed: backends subpackage + PipBackend +
    dispatcher + CLI/env/Pipfile plumbing + 9 unit tests. Wire shape
    unchanged (`ResolverOptions.backend` is suppressed on the wire when
    empty so the C2 protocol fixture passes byte-for-byte; no
    integration fixture regen needed).
- **files edited/created**:
  - NEW `pipenv/resolver/backends/__init__.py`
  - NEW `pipenv/resolver/backends/base.py`
  - NEW `pipenv/resolver/backends/pip.py`
  - `pipenv/resolver/core.py`
  - `pipenv/resolver/schema.py`
  - `pipenv/cli/options.py`
  - `pipenv/cli/command.py`
  - `pipenv/routines/context.py`
  - `pipenv/utils/settings.py`
  - `pipenv/utils/resolver.py`
  - `pipenv/utils/pylock.py`
  - `pipenv/environments.py`
  - NEW `news/T_F.5.feature.rst`
  - NEW `tests/unit/test_resolver_backends.py`

#### T_F.6: Enforce wall-clock timeout via `request.metadata.deadline_seconds`
- **depends_on**: [T_F.3, T_F.4]
- **location**: `pipenv/utils/resolver.py` (subprocess deadline plumbing
  + new `_resolve_deadline_seconds` helper), `pipenv/resolver/core.py`
  (`_wall_clock_deadline` SIGALRM guard for the in-process branch),
  `news/T_F.6.behavior.rst`, `tests/unit/test_resolver_timeout.py`.
- **description**:
  Replaces the reserved-but-unenforced `RequestMetadata.deadline_seconds`
  slot (queued in T_F.3 design Q11 / §5 decision 11) with a fully wired
  enforcement path. Resolution precedence: `[pipenv] resolver_timeout_seconds`
  in the Pipfile > `PIPENV_RESOLVER_TIMEOUT_S` env var > default
  (1800s, set by `Setting`). The resolved deadline is stamped on every
  `ResolverRequest.metadata.deadline_seconds` by `_build_resolver_request`
  so the wire envelope carries the same value the parent uses for
  `subprocess.wait(timeout=...)`. The existing phase-2 hotfix
  (`PIPENV_RESOLVER_TIMEOUT_S` knob; commit `577a12a8`) is preserved as
  the env-var precedence rung — its `subprocess.TimeoutExpired` path
  now reads from the new request-carried deadline, with a fallback to
  `project.s.PIPENV_RESOLVER_TIMEOUT_S` for back-compat with any caller
  not updated to thread the deadline through. The in-process debug
  branch (`PIPENV_RESOLVER_PARENT_PYTHON=1`) enforces the same deadline
  via a `signal.SIGALRM` guard installed by a new
  `_wall_clock_deadline` context manager in `resolver/core.py`; on
  expiry, `resolve_for_pipenv` returns an `InternalError` variant whose
  message names the elapsed deadline. Windows skips the in-process
  guard (no `SIGALRM`); the subprocess path remains the production
  enforcement path on all platforms. User-facing timeout error message
  updated to name BOTH the env var and the new Pipfile setting.
- **validation**:
  - 7 new tests in `tests/unit/test_resolver_timeout.py` cover:
    subprocess `TimeoutExpired` → `ResolutionFailure` with both
    overrides named; default deadline falls back to
    `PIPENV_RESOLVER_TIMEOUT_S`; Pipfile setting wins over env-backed
    default; invalid Pipfile values fall back; `_build_resolver_request`
    stamps `metadata.deadline_seconds`; `resolve()` honours the
    request-carried deadline; in-process branch returns
    `InternalError` on SIGALRM-mediated timeout.
  - Existing `test_resolver_regressions.py` timeout tests continue to
    pass unchanged.
  - Full unit suite green (780 passed, 9 skipped).
- **status**: Completed (branch
  `maintenance/code-cleanup-phase4-resolver-followups-2026-05`).
- **log**:
  - 2026-05-12 — Wired deadline through `_build_resolver_request` →
    `request.metadata.deadline_seconds` → `resolve()` → `subprocess.wait`.
    Added SIGALRM-based in-process guard. Sibling agent T_F.7
    (`Diagnostics.resolver_log`) ran concurrently on the same two files
    with no logical collision: T_F.6 owns timeout wiring and the
    deadline-related lines; T_F.7 owns log capture.
- **files edited/created**:
  - `pipenv/utils/resolver.py` (`_resolve_deadline_seconds` helper;
    `_build_resolver_request` stamps `metadata.deadline_seconds`;
    `resolve()` accepts `deadline_seconds=` keyword;
    `_run_resolver_subprocess` threads request deadline through;
    timeout error message names both overrides)
  - `pipenv/resolver/core.py` (`_wall_clock_deadline` context manager;
    `resolve_for_pipenv` wraps the resolve in the SIGALRM guard)
  - `tests/unit/test_resolver_timeout.py` (new, 7 tests)
  - `tests/unit/test_resolver_parent_dispatch.py` (existing `fake_resolve`
    stubs widened to `**_kwargs` to accept the new keyword)
  - `news/T_F.6.behavior.rst` (new)

#### T_F.7: Populate `Diagnostics.resolver_log` with structured resolve records
- **depends_on**: [T_F.3, T_F.4]
- **location**: `pipenv/resolver/core.py` (capture handler +
  context manager + integration into `resolve_for_pipenv`),
  `pipenv/utils/resolver.py` (verbose-mode surfacing), new
  `tests/unit/test_resolver_diagnostics.py`.
- **description**:
  Replaces the reserved-but-empty `Diagnostics.resolver_log` slot
  (queued in T_F.3 design Q9 / §8) with a structured logging-handler
  capture wired into the unified `resolve_for_pipenv` driver. A new
  `_BoundedListHandler` (capped at 500 records) is attached to the
  `pipenv` and `pip._internal.resolution` loggers for the duration of
  the resolve via a `_capture_resolver_log` context manager that
  restores handler state and original level on exit (even on
  exception). Captured records are formatted as `[LEVELNAME] message`
  strings and land on `response.diagnostics.resolver_log`; truncation
  appends a `... (N records elided)` sentinel.

  Parent-side surfacing in `pipenv/utils/resolver.py`: a new
  `_surface_resolver_log(response, project)` helper iterates the
  records and prints each via `err.print` when `project.s.is_verbose()`
  is true. Stderr behaviour in non-verbose mode is unchanged — the
  structured log is a complement, not a replacement (per Q9).
  Pip download chatter (`pip._internal.network` /
  `pip._internal.operations.prepare`) is intentionally NOT captured;
  stderr remains the appropriate channel for that.

  Both adapters (in-process debug bypass + subprocess) share the same
  capture because it lives inside `resolve_for_pipenv`. The schema
  field already existed (no schema bump); JSON round-trip preserves
  the records via the existing `to_json_dict` / `from_json_dict`
  envelope.
- **validation**:
  - 9 new tests in `tests/unit/test_resolver_diagnostics.py` cover:
    `pipenv` logger capture; `pip._internal.resolution` logger
    capture; `[LEVELNAME] message` formatting; empty resolve yields
    empty tuple; handler removed after resolve (clean exit and
    exception path); flood test asserts 500-record cap +
    `records elided` sentinel; Diagnostics dataclass + tuple typing;
    JSON round-trip preserves the records.
  - Full unit suite green: 780 passed, 9 skipped.
- **status**: Completed (branch
  `maintenance/code-cleanup-phase4-resolver-followups-2026-05`).
- **log**:
  - 2026-05-12 — Wired logging capture into `resolve_for_pipenv`;
    surfaced verbose-mode log in `pipenv/utils/resolver.py`. Sibling
    agent T_F.6 (deadline enforcement) ran concurrently on the same
    two files; the resolve-flow integration commits landed under
    T_F.6's two commits (`165bdb2f`, `e550e7f3`) which include the
    T_F.7 `_BoundedListHandler` / `_capture_resolver_log` /
    `_surface_resolver_log` helpers. This T_F.7 commit completes the
    bookkeeping (new test file + plan entry).
- **files edited/created**:
  - `pipenv/resolver/core.py` (`_BoundedListHandler`,
    `_capture_resolver_log` context manager, integration into
    `resolve_for_pipenv` success / resolution-error / internal-error
    branches)
  - `pipenv/utils/resolver.py` (`_surface_resolver_log` helper;
    call sites in `_run_resolver_subprocess` and `_resolve_in_process`;
    `_resolve_in_process` gains optional `project` parameter for the
    verbose surface)
  - `tests/unit/test_resolver_diagnostics.py` (new, 9 tests)

---

## Parallel Execution Groups

| Wave | Tasks | Can Start When |
|------|-------|----------------|
| 0 | T0.1, T0.2 | Immediately |
| 1a | T_A.1, T_B.1, T_B.2, T_B.3, T_B.4 | Wave 0 complete |
| 1b | T_A.2 | T_A.1 complete |
| 1c | T_A.3 | T_A.2 complete |
| 1d | T_B.5 | T_B.1, T_B.2, T_B.3, T_B.4 complete |
| 1e | T_B.6, T_B.7 | T_B.5 complete (parallel-safe) |
| 1f | T_A.4 | T_A.3 complete + next release cut (held) |
| 2a | T_C.2 | Wave 0 complete |
| 2b | T_C.3 | T_C.2 complete |
| 2c | T_C.4 | T_C.3 complete + reviewer sign-off on design |
| 2d | T_C.5 | T_C.4 complete |
| 2e | T_C.6 | T_C.5 complete |
| 2f | T_C.7 | T_C.6 complete |
| 2g | T_C.8, T_C.9 | T_C.4 complete (parallel-safe with T_C.5–7 in principle; sequence behind for review bandwidth) |
| 3-seed | T_D.1 | Wave 0 complete |
| 3-poc  | T_D.2 | T_D.1 complete |
| 3-seed | T_E.1 | T_B.7 complete |
| 4-seed | T_F.1 | T_E.1 complete |
| 4-design | T_F.2 | T_F.1 complete (design only; awaits sign-off) |

**Maximum parallelism at any moment** is bounded by review bandwidth, not
by the graph. The graph allows ~5 tasks to run concurrently in the early
phase (the four B-triage tasks plus T_A.1); the practical limit is
whatever Matt can review in a day. Suggested concurrency: 2–3 in flight
at a time.

## Testing Strategy

- **Per-task gate (agent-side)**: `python -m pytest tests/unit -x` green
  before the agent commits and pushes.
- **Per-PR gate (CI-side)**: full CI suite green before merge to
  `maintenance/code-cleanup-2026-05`.
- **Wave gate (Matt-side)**: a smoke pipenv command (`pipenv install`,
  `pipenv lock`, `pipenv update`) against a representative fixture
  Pipfile before the branch merges to `main`.
- **Coverage-gap prework**: any task that refactors a code path with
  thin unit coverage adds tests *first* in the same PR — explicitly
  enumerated in the task validation when known. The currently-known gap
  is `pipenv/utils/requirements.py` and `pipenv/utils/requirementslib.py`
  (no dedicated test files); to be addressed during T_B.5 / T_E.1.

## Risks & Mitigations

- **Risk**: A triage decision in T_B.5 contradicts an assumption baked
  into T_A.* (e.g. `is_valid_url`'s canonical home).
  **Mitigation**: T_A.1 produces its decision independently of T_B; if
  they conflict on a symbol, T_A's decision wins for URL/path scope and
  T_B's wins for everything else. Conflict is recorded in the triage
  doc.
- **Risk**: Wave-2 routine migrations break a CLI invocation that the
  unit tests don't cover (e.g. a rare flag combination).
  **Mitigation**: Each migration PR includes the smoke-fixture run as
  validation. T_C.4 lands the dataclass without changing any call
  site, so issues caught later can be reverted at the migration PR
  without losing the scaffolding.
- **Risk**: Initiative B's "vendor" decisions require moving files into
  `pipenv/vendor/`, which is normally vendor-tooling territory; an
  agent doing this naively could break the vendor sync.
  **Mitigation**: Any "vendor" execution PR is owned by Matt or
  @oz123, not by a swarm agent. The triage task can still be done by
  an agent.
- **Risk**: Wave-3 seed tasks (T_D.1, T_E.1) get stale before their
  full plans are regenerated.
  **Mitigation**: Seed tasks produce time-stamped inventory docs; the
  follow-up plan-regeneration step explicitly checks for code drift.
- **Risk**: Maintainer-time evaporation mid-wave (per PRD §8 risk
  table).
  **Mitigation**: Every task above is independently revertible and
  independently useful. The chain `T_A.1 → T_A.2 → T_A.3` shrinks
  duplication on its own even if the rest of the plan never executes.
- **Risk**: Agent commits skip the news-fragment convention.
  pipenv uses Towncrier fragments under `news/` for user-visible
  changes. Behaviour-preserving refactors don't require a fragment, but
  the deprecation in T_A.2 and the removal in T_A.4 do. An agent that
  doesn't know the convention may land the change without the fragment
  and fail CI later, or worse, get merged with no user-facing notice.
  **Mitigation**: T0.2 (swarm-ops doc) explicitly enumerates which
  task categories require news fragments and links to an existing
  fragment as a template. Any task whose description mentions
  `news/` includes the fragment in the same commit, not as a follow-up.
- **Risk**: Hidden user-visible change slips through an agent PR.
  Waves 1–2 are advertised as behaviour-preserving, but a refactor
  could accidentally alter logging, error messages, or exit codes that
  users depend on.
  **Mitigation**: T0.2's checklist requires every agent PR to grep its
  own diff for `print(`, `logger.`, `raise `, `sys.exit(` and report
  any matches in the PR description; reviewer (Matt) treats any such
  match as a flag requiring deliberate sign-off.

## Out of Scope (Plan-Level)

- Anything under `pipenv/patched/` or `pipenv/vendor/`. Initiative B may
  move *into* `pipenv/vendor/` under maintainer supervision; agents do
  not modify existing contents.
- Version bumps, CHANGELOG, release tooling.
- Pipfile / Pipfile.lock format changes.
- Anything in the PRD's §9 (Out of scope) section: performance work,
  feature parity with uv, CLI changes, new features.
