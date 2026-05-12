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
- **location**: `pipenv/utils/fileutils.py`, `news/` (removal fragment).
- **description**:
  Once T_A.3 confirms zero internal callers and **at least one tagged
  pipenv release** has shipped the deprecation shim from T_A.2 (giving
  external consumers a window to migrate), remove the shim. T_A.2
  already updated intra-module call sites in `fileutils.py` to use the
  canonical `internet` import, so no in-module call needs updating
  here. Add a news fragment documenting the removal.
- **validation**:
  - Shim line removed from `pipenv/utils/fileutils.py`.
  - `python -c "from pipenv.utils.fileutils import is_valid_url"` now
    raises `ImportError` — this is the intended behaviour after the
    deprecation window.
  - `python -c "import pipenv.utils.fileutils"` still succeeds.
  - News fragment present and recognized.
  - Unit suite green; the changelog history shows a release between
    T_A.2's deprecation fragment and this removal fragment.
- **status**: Not Completed (held for release)
- **log**:
- **files edited/created**:

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
- **status**: Not Completed
- **log**:
- **files edited/created**:

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
- **status**: Not Completed
- **log**:
- **files edited/created**:

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
  - `docs/dev/initiative-e-design.md` (new, 692 lines)

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
