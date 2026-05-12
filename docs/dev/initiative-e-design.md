# Initiative E — Requirement-Model Consolidation Design Proposal (T_E.1)

Status: **awaiting maintainer sign-off**. No code moves under T_E.2+ until this
document is approved.

## 1. Summary

Initiative B's triage closed out the "inlined-former-vendor pathology" inside
`pipenv/utils/requirementslib.py`, `pipenv/utils/requirements.py`,
`pipenv/utils/fileutils.py`, and `pipenv/utils/markers.py`: seven dead symbols
were deleted, six boltons-style helpers were replaced with a purpose-built
dict merger, two pip-internal fork pairs were re-adopted with provenance
docstrings, and four cross-cutting follow-ups were explicitly handed off to
Initiative E.

This document proposes the **target shape** of the requirement-modelling
layer after Initiative E lands. It is a design proposal only: no code
changes here.

**In scope.**

1. Pick `pipenv/utils/dependencies.py` as the canonical home for the
   requirement-model API (parse, normalise, serialise, hash, Pipfile/lockfile
   bridging) — versus splitting it into multiple themed files.
2. Identify the surviving Wave-1c symbols in the three sibling modules
   (`requirements.py`, `requirementslib.py`, `markers.py`) and decide, for
   each, whether it moves into `dependencies.py` or stays put with rationale.
3. Resolve the three named cross-cutting follow-ups Initiative B flagged:
   `BAD_PACKAGES` co-location, the module-level `add_index_to_pipfile` name
   collision with `Project.add_index_to_pipfile`, and the misleading file
   name `requirementslib.py` now that 13 of 20 original symbols are gone.
4. Sequence the moves into one wave per logical group so each migration PR
   is reviewable in isolation and behaviour-preserving.

**Out of scope.** The moves themselves (those are T_E.2+). The
`normalize_name` / `pep423_name` overlap is **already resolved** under
Wave 1c commit `e874e9d0` and is not in scope for Initiative E. Anything in
Initiative C/D/F's lane. Anything user-visible (CLI surface, Pipfile schema).

**Relationship to Initiative B.** Initiative B was the *triage* —
adopt/replace/delete decisions per symbol. Initiative E is the *physical*
move that makes the adopt decisions actually land in one predictable place.
The triage table in `initiative-b-triage.md` is the foundation; this doc
does not relitigate any adopt decision.

**Relationship to T_C.3 sign-off.** Per the §9 maintainer sign-off on the
RoutineContext design, the project's `pipenv.routines.*` and
`pipenv.utils.*` Python surface is **internal**: the CLI is the contract.
This means Initiative E can change the public Python module surface
wholesale — no `DeprecationWarning` shims, no module-level `from .new import
old`-style import bridges, no deprecation period. Imports break in
exactly one commit per wave.

---

## 2. Current state of the requirement-model layer (post Initiative B)

Module sizes after Wave 1c:

| Module | Lines | Public symbols (post-1c) |
|---|---|---|
| `pipenv/utils/dependencies.py` | 1535 | 54 top-level defs/classes |
| `pipenv/utils/requirements.py`  |  414 | 8 functions + `BAD_PACKAGES` const |
| `pipenv/utils/requirementslib.py` | 274 | 7 public symbols (was 20) |
| `pipenv/utils/markers.py`       |  661 | ~30 helpers + `PipenvMarkers`, `RequirementError` |
| **Total** | **2884** | |

For each module below, "external caller count" means the number of `pipenv/`
files (excluding `pipenv/patched/` and `pipenv/vendor/`) that import the
symbol, verified by grep. Where the triage doc disagrees with current grep
output, current grep wins.

### 2.1 `pipenv/utils/dependencies.py` — the canonical home

54 top-level public symbols. This is the "newer core logic" module the PRD
designated as the canonical home for the requirement model. Already imports
the three Wave-1c adopt survivors from `requirementslib.py`
(`add_ssh_scheme_to_git_uri`, `get_pip_command`, `unpack_url`) at module top.
Already imports `PipenvMarkers` from `markers.py`.

Public surface (alphabetical, grouped by theme):

- **Pipfile parsing / shaping:** `get_version`, `clean_pkg_version`,
  `pep440_version`, `pep423_name`, `translate_markers`, `is_star`,
  `is_pinned`, `is_pinned_requirement`, `is_editable`, `is_editable_path`,
  `is_required_version`, `has_name_with_extras`, `as_pipfile`,
  `from_pipfile`, `install_req_from_pipfile`, `handle_non_vcs_requirement`,
  `file_path_from_pipfile`, `clean_resolved_dep`.
- **Conversion to pip:** `dependency_as_pip_install_line`,
  `convert_deps_to_pip`, `expansive_install_req_from_line`,
  `get_link_from_line`, `create_link`, `normalize_editable_path_for_pip`.
- **URL / VCS shape:** `extract_vcs_url`, `normalize_vcs_url`,
  `determine_path_specifier`, `determine_vcs_specifier`, `get_vcs_backend`,
  `determine_vcs_revision_hash`, `VCSURLProcessor` (class),
  `_file_url_to_relative_path` (private but referenced).
- **Package-name discovery from artefact:** `find_package_name_from_tarball`,
  `find_package_name_from_zipfile`, `find_package_name_from_directory`,
  `find_package_name_from_filename`, `determine_package_name`,
  `parse_metadata_file`, `parse_pkginfo_file`, `parse_setup_file`,
  `parse_cfg_file`, `parse_toml_file`.
- **Hashes and constraints:** `unearth_hashes_for_dep`,
  `get_constraints_from_deps`, `get_constraints_from_resolved_deps`,
  `prepare_constraint_file`.
- **Environment / Python shim:** `python_version`, `HackedPythonVersion`,
  `get_canonical_names`, `expand_env_variables`, `get_lockfile_section_using_pipfile_category`,
  `get_pipfile_category_using_lockfile_section`.
- **Filesystem helpers in scope here for layout reasons:**
  `ensure_path_is_relative`, `generate_temp_dir_path`, `locked_repository`.

This is the right home. The themes already span Pipfile, lockfile, pip
interop, URLs, and constraints — exactly the layer Initiative E is
consolidating.

### 2.2 `pipenv/utils/requirements.py` — Pipfile/lockfile bridges plus pip-internal forks

Survives Wave 1c with **6 adopt + 2 vendor (project-owned forks) + 1
constant** = 8 public defs and `BAD_PACKAGES`.

| Symbol | Decision (triage) | External callers (verified 2026-05-12) |
|---|---|---|
| `redact_netloc` | vendor (project-owned fork) | 0 outside file |
| `redact_auth_from_url` | vendor (project-owned fork) | 0 outside file (only by `import_requirements` here) |
| `import_requirements` | adopt | 2: `pipenv/utils/pipfile.py:104`, `pipenv/routines/install.py:538` |
| `add_index_to_pipfile` | adopt | 2: `pipenv/routines/install.py:169`, `pipenv/routines/update.py:649` |
| `requirement_from_lockfile` | adopt | 1 (external file): `pipenv/utils/locking.py` (3 call sites at L584, L599, L603, plus 1 internal use here) |
| `requirements_from_lockfile` | adopt | 2: `pipenv/routines/audit.py:244`, `pipenv/routines/requirements.py:89` |
| `requirement_from_pipfile` | adopt | 0 outside file (only by `requirements_from_pipfile` here) |
| `requirements_from_pipfile` | adopt | 1: `pipenv/routines/requirements.py:139` |
| `BAD_PACKAGES` (constant) | n/a | 3: `pipenv/routines/graph.py:9`, `pipenv/routines/uninstall.py:16`, `pipenv/routines/clean.py:8` |

Total importing files outside `requirements.py` itself: **6**
(`pipfile.py`, `locking.py`, `routines/install.py`, `routines/update.py`,
`routines/audit.py`, `routines/requirements.py`, `routines/graph.py`,
`routines/uninstall.py`, `routines/clean.py` — i.e. **9 import statements
across 8 caller files**). Wave 1c did not change this count.

### 2.3 `pipenv/utils/requirementslib.py` — survived Wave 1c at 274 lines

Was 740 lines pre-1c with 20 public symbols. Survives at 274 lines with the
following:

| Symbol | Decision (triage) | External callers (verified 2026-05-12) |
|---|---|---|
| `add_ssh_scheme_to_git_uri` | adopt | 1: `pipenv/utils/dependencies.py:37` (used at `:1044`) |
| `is_vcs` | adopt | 4 import sites: `pipenv/utils/locking.py:30`, `pipenv/utils/pipfile.py:15`, `pipenv/project.py:909`, **and used as `link.is_vcs` attribute access in 7 unrelated places** — those are NOT calls to our function (they're pip's `Link.is_vcs` property). Function-call sites: `locking.py:362`, `pipfile.py:341`, `project.py:912`. |
| `merge_items` | adopt | 2 import sites: `pipenv/utils/locking.py:30`, `pipenv/utils/pipfile.py:15`. Used at `locking.py:387,580`, `pipfile.py:319`. |
| `get_pip_command` | adopt | 1: `pipenv/utils/dependencies.py:38` (used at `:919`) |
| `unpack_url` | adopt (with provenance) | 1: `pipenv/utils/dependencies.py:39` (used at `:923`) |
| `get_http_url` | adopt (with provenance) | 0 outside file (only by `unpack_url` here) |
| `_merge_into`, `_new_container_like` | private | internal helpers behind `merge_items` |

Plus the local constants `VCS_LIST`, `SCHEME_LIST`, `VCS_SCHEMES` —
duplicated in `pipenv/utils/constants.py`, used here for the verbatim
provenance-locked `unpack_url`/`get_http_url` pair (see §2.3 note in the
triage doc). `STRING_TYPE` and the local `PipfileEntryType`/`PipfileType`
type aliases are also defined here for the function signatures.

**Naming:** the file is named after the archived `requirementslib` PyPI
package it was inlined from. Post-1c the file contains no `requirementslib`
code (the boltons subset was replaced; the URI helpers were Pipfile-schema
predicates with no upstream lineage anyway). The name is now actively
misleading.

### 2.4 `pipenv/utils/markers.py` — owned glue over distlib/packaging

T_B.4 found: not inlined former vendor code. It composes
`pipenv.patched.pip._vendor.distlib.util.parse_marker` and the
`packaging.markers`/`packaging.specifiers` API into pipenv-specific helpers
(specifier cleanup, intersection, lookup tables, marker round-trip). No
adopt/vendor/delete decision was needed in B.

Three external import sites:

- `pipenv/utils/pipfile.py:13` — imports `RequirementError`.
- `pipenv/utils/dependencies.py:51` — imports `PipenvMarkers`.
- `pipenv/utils/resolver.py:813` — late-imports `marker_from_specifier`.

Plus `pipenv/utils/locking.py` defines a function literally also called
`merge_markers` (locking-local) that is **not** the same as the
module-level `merge_markers` in `markers.py:612`; this is an
unrelated naming overlap, not a duplicate.

The triage doc explicitly says "refactor freely under Initiative E if
useful." This proposal recommends **leaving `markers.py` as-is** for
Initiative E. Rationale in §6 decision question (5).

---

## 3. Cross-cutting findings already flagged in Initiative B

Three items the B triage explicitly handed to Initiative E.

### 3.1 `BAD_PACKAGES` constant — co-location

Currently in `requirements.py:167`. The contents are:

```
BAD_PACKAGES = (
    "distribute", "packaging", "pip", "pkg-resources", "setuptools",
    "wheel", ...
)
```

Imported by three `routines/` files (`graph.py`, `uninstall.py`,
`clean.py`). None of those routines import any *other* helper from
`requirements.py`, so `BAD_PACKAGES` is the *only* coupling. The constant
is also used internally by `import_requirements` in `requirements.py:117`.

**Decision proposal:** move to `pipenv/utils/dependencies.py`. Rationale:
the constant gates whether a package name is in scope for installation /
graphing / uninstallation, which is a requirement-model concern, not a
serialisation concern. Co-locating with `pep423_name` (already in
`dependencies.py:134`) is sensible because `uninstall.py:176` already
composes the two (`{pep423_name(pkg) for pkg in BAD_PACKAGES}`).

**Alternative considered:** keep in `requirements.py`. Rejected because
once the bridge functions move (E.2), the constant would be the *only*
content in `requirements.py` besides the two `redact_*` forks — and
`redact_*` and `BAD_PACKAGES` have no thematic relationship.

**Alternative considered:** new file `pipenv/utils/exclusions.py` or
similar. Rejected as over-engineered for a 6-tuple of strings.

### 3.2 `add_index_to_pipfile` name collision

The module-level `add_index_to_pipfile` in `requirements.py:148` shares its
name with `Project.add_index_to_pipfile` at `pipenv/project.py:1536`.
Function calls method:

```python
# requirements.py:163
index_name = project.add_index_to_pipfile(index, verify_ssl=require_valid_https)
```

The function does extra work on top of the method (decides whether HTTPS is
required based on `trusted_hosts`), but a reader scanning a call site like
`add_index_to_pipfile(project, index)` has to chase the import to know
which entry point is in use.

**Decision proposal:** rename the module-level function to
`add_index_to_pipfile_with_trust_check` when it moves under E.2.
Alternatives: `register_index_in_pipfile`, `ensure_index_in_pipfile`,
`prepare_and_add_index_to_pipfile`. The longer name carries its own
documentation. The new name will land in the same PR that moves the
function into `dependencies.py` (E.2), so callers update once.

**Note on §5 sequencing:** rename and move happen in the same PR. No
separate "E.6 rename" task is needed; tracked in §5 just for completeness.

### 3.3 `requirementslib.py` filename — rename, split, or retire

Now that the file holds no `requirementslib`-lineage code, three options.

**Option (a): rename to `pipfile_schema.py`** (or similar). Rejected
because only two of the seven survivors are Pipfile-schema predicates
(`is_vcs`, `add_ssh_scheme_to_git_uri`); the rest (`merge_items`,
`get_pip_command`, `unpack_url`, `get_http_url`) span Pipfile-merge and
pip-prepare-step semantics. No single new name covers them all.

**Option (b): split and retire** — move the four predicates and
single-line helpers (`is_vcs`, `add_ssh_scheme_to_git_uri`,
`merge_items`, `get_pip_command`) into `dependencies.py`; keep
`unpack_url` / `get_http_url` (the verbatim pip-internal fork pair with
their long provenance docstrings) under a more honest filename
`pipenv/utils/pip_internals_fork.py`, or move them into `dependencies.py`
behind a marker comment. After this, `requirementslib.py` no longer
exists.

**Option (c): keep the file as a historical artifact.** Rejected. The
name actively misinforms a reader new to the codebase.

**Decision proposal:** option (b) — **split and retire**. Implementation:

- E.3 moves `is_vcs`, `add_ssh_scheme_to_git_uri`, `merge_items`,
  `get_pip_command` into `dependencies.py`.
- E.4 moves `unpack_url`, `get_http_url` (the pair) into a new file
  `pipenv/utils/unpack.py` (or alternatively, the bottom of
  `dependencies.py` behind a `# region: pip._internal.operations.prepare
  fork` block). The new home is a maintainer decision in §6 question 4.
- After E.3 and E.4 land, `pipenv/utils/requirementslib.py` is empty.
  Delete the file. Tests that import from this path are already in the
  E.3/E.4 PRs (caller migration).

---

## 4. Proposed canonical API

After Initiative E lands, the public Python surface for requirement
modelling is exactly **one module** — `pipenv/utils/dependencies.py` —
plus `markers.py` for marker/specifier glue. Below is the full proposed
shape per module.

### 4.1 `pipenv/utils/dependencies.py` — canonical home

**Stays as-is (already there, 54 symbols).** All public symbols enumerated
in §2.1 keep their current home. No symbol leaves `dependencies.py`.

**Moves IN from `requirements.py`** (under E.2):

| Symbol | External callers to migrate | Action |
|---|---|---|
| `import_requirements` | 2 (`pipfile.py`, `routines/install.py`) | Move; update 2 imports |
| `add_index_to_pipfile` → **`add_index_to_pipfile_with_trust_check`** | 2 (`routines/install.py`, `routines/update.py`) | Move + rename; update 2 imports and 2 call sites |
| `requirement_from_lockfile` | 1 file, 3 call sites (`locking.py`) | Move; update 1 late-import |
| `requirements_from_lockfile` | 2 (`routines/audit.py`, `routines/requirements.py`) | Move; update 2 imports |
| `requirement_from_pipfile` | 0 outside file | Move; no external callers |
| `requirements_from_pipfile` | 1 (`routines/requirements.py`) | Move; update 1 import |
| `BAD_PACKAGES` (constant) | 3 (`routines/graph.py`, `routines/uninstall.py`, `routines/clean.py`) | Move (per §3.1); update 3 imports |

**Moves IN from `requirementslib.py`** (under E.3):

| Symbol | External callers to migrate | Action |
|---|---|---|
| `is_vcs` | 3 (`utils/locking.py`, `utils/pipfile.py`, `project.py`) | Move; update 3 imports. *Note:* `link.is_vcs` attribute accesses elsewhere are pip's `Link.is_vcs` property — unaffected. |
| `add_ssh_scheme_to_git_uri` | 1 (`utils/dependencies.py` — self) | After move it becomes an intra-file reference; remove the cross-module import |
| `merge_items` | 2 (`utils/locking.py`, `utils/pipfile.py`) | Move; update 2 imports. Brings `_merge_into` and `_new_container_like` private helpers with it. |
| `get_pip_command` | 1 (`utils/dependencies.py` — self) | After move it becomes intra-file |

**Stays in its current home with rationale**:

| Symbol | Home | Why |
|---|---|---|
| `redact_netloc`, `redact_auth_from_url` | `requirements.py` | Project-owned forks of pip's `_internal.utils.misc` versions with intentional env-var-placeholder and SSH-username preservation. The provenance docstring landed in Wave 1c commit `dc58f7a6`; the divergence is load-bearing for user-visible CLI output and lockfile contents. They have no thematic fit in `dependencies.py` (this is netloc redaction, not requirement modelling). See §6 question 6. |
| `unpack_url`, `get_http_url` | TBD per §3.3 / §6 question 4 — proposal: new `pipenv/utils/unpack.py` | Verbatim pip-internal forks; behavioural divergence (VCS-link handling in `unpack_url`; `globally_managed=False` in `get_http_url`) is documented in long provenance docstrings landed in Wave 1c commit `2d897a0c`. The pair has 30+ lines of provenance commentary protecting them. Mixing that into `dependencies.py` would visually dominate any nearby unrelated function. |
| All of `markers.py` | `markers.py` | Already-canonical owned glue over `distlib.util.parse_marker` and `packaging.markers`/`packaging.specifiers`. Limited but real cross-module reuse from `pipfile.py` (RequirementError), `dependencies.py` (PipenvMarkers), `resolver.py` (marker_from_specifier). See §6 question 5. |

### 4.2 `pipenv/utils/requirements.py` — post-E

After E.2 + E.5 (BAD_PACKAGES move), the file holds only:

- `redact_netloc`
- `redact_auth_from_url`

Two symbols, ~70 lines. **Decision proposal:** the file stays — these two
deserve their own home because the provenance docstrings make them
thematically distinct. **Alternative:** rename the file to
`pipenv/utils/redact.py` once it shrinks. See §6 question 7.

`import_requirements` was the only caller of `redact_auth_from_url`
(`requirements.py:123`). When `import_requirements` moves into
`dependencies.py` under E.2, the call site moves with it; that single
caller is then `dependencies.py` importing `redact_auth_from_url` from
`pipenv/utils/requirements.py` (or `redact.py`).

### 4.3 `pipenv/utils/requirementslib.py` — post-E

**File deleted** after E.3 (predicates move) + E.4 (pip-internal pair
moves) land. The `STRING_TYPE`, `PipfileEntryType`, `PipfileType` type
aliases that survive only in this file are not used elsewhere; they
disappear with the file.

### 4.4 `pipenv/utils/markers.py` — post-E

**Unchanged.** Recommended explicitly in §6 question 5.

---

## 5. Sequencing

Five PRs total, sequenced cheapest / lowest-coupling first. Each PR is
behaviour-preserving and (per T_C.3 §9 sign-off) does **not** ship a
`DeprecationWarning` shim or import alias; imports are updated in lockstep
with the move.

Sequencing principle: in each PR, the order is:

1. **Test pin first.** If no test pins the symbol's behaviour, add one in
   the same PR before any move (Initiative B noted `requirements.py` and
   `requirementslib.py` have no dedicated test files — see
   `modernization-plan.md` testing strategy note for T_B.5 / T_E.1
   coverage-gap prework). The pinning test goes in the destination file's
   matching test module so it stays pinned post-move.
2. **Move the symbol** (with its private helpers if any).
3. **Update every importing call site** in the same PR.
4. **Run `python -m pytest tests/unit -x`** before commit per swarm-ops §2.

### T_E.2 — Move Pipfile/lockfile bridges out of `requirements.py`

**Symbols moved into `dependencies.py`:**

- `import_requirements`
- `requirement_from_lockfile`
- `requirements_from_lockfile`
- `requirement_from_pipfile`
- `requirements_from_pipfile`
- `add_index_to_pipfile`, renamed to **`add_index_to_pipfile_with_trust_check`**

**Caller files to update** (8 file-level import changes; 7 if `pipfile.py`
keeps its `import_requirements` import on one line, 8 if separate):

| File | Old | New |
|---|---|---|
| `pipenv/utils/pipfile.py:14` | `from pipenv.utils.requirements import import_requirements` | `from pipenv.utils.dependencies import import_requirements` |
| `pipenv/utils/locking.py:566` | `from pipenv.utils.requirements import requirement_from_lockfile` (late import) | `from pipenv.utils.dependencies import requirement_from_lockfile` |
| `pipenv/routines/install.py:31` | `from pipenv.utils.requirements import add_index_to_pipfile, import_requirements` | `from pipenv.utils.dependencies import add_index_to_pipfile_with_trust_check, import_requirements` |
| `pipenv/routines/install.py:169` | `add_index_to_pipfile(project, index)` | `add_index_to_pipfile_with_trust_check(project, index)` |
| `pipenv/routines/update.py:23` | `from pipenv.utils.requirements import add_index_to_pipfile` | `from pipenv.utils.dependencies import add_index_to_pipfile_with_trust_check` |
| `pipenv/routines/update.py:649` | `add_index_to_pipfile(project, index_url)` | `add_index_to_pipfile_with_trust_check(project, index_url)` |
| `pipenv/routines/audit.py:237` | `from pipenv.utils.requirements import requirements_from_lockfile` (late import) | `from pipenv.utils.dependencies import requirements_from_lockfile` |
| `pipenv/routines/requirements.py:5-7` | `from pipenv.utils.requirements import (requirements_from_lockfile, requirements_from_pipfile,)` | `from pipenv.utils.dependencies import (requirements_from_lockfile, requirements_from_pipfile,)` |

Internal import inside `dependencies.py`: `redact_auth_from_url` (used by
`import_requirements`) is now imported from `pipenv.utils.requirements`
(or `pipenv.utils.redact` if E.7 lands first — but E.7 is the smallest
possible reshuffle and is sequenced last).

**Risk:** low. None of these functions are called via reflection or string
lookup. The rename is mechanical.

**Test pinning required:** yes — none of the moved functions have
dedicated unit tests in `tests/unit/`. Recommend pinning at minimum:
- `requirement_from_lockfile` happy paths (VCS / file / path / standard
  PyPI) — these are the most behaviourally complex.
- `requirement_from_pipfile` happy paths.
- `import_requirements` end-to-end with a fixture requirements.txt.
- `add_index_to_pipfile_with_trust_check` decides HTTPS/HTTP correctly
  from a trusted-hosts list (small).

### T_E.3 — Move predicates and helpers out of `requirementslib.py`

**Symbols moved into `dependencies.py`:**

- `is_vcs` (with its dependency on `add_ssh_scheme_to_git_uri`)
- `add_ssh_scheme_to_git_uri`
- `merge_items` (with private helpers `_merge_into`, `_new_container_like`)
- `get_pip_command`

**Caller files to update** (5 import changes):

| File | Old | New |
|---|---|---|
| `pipenv/utils/locking.py:30` | `from pipenv.utils.requirementslib import is_vcs, merge_items` | `from pipenv.utils.dependencies import is_vcs, merge_items` |
| `pipenv/utils/pipfile.py:15` | `from pipenv.utils.requirementslib import is_vcs, merge_items` | `from pipenv.utils.dependencies import is_vcs, merge_items` |
| `pipenv/project.py:909` | `from pipenv.utils.requirementslib import is_vcs` (late import) | `from pipenv.utils.dependencies import is_vcs` |
| `pipenv/utils/dependencies.py:36-40` | imports from `requirementslib` | Remove (now intra-file) |

After this PR, `requirementslib.py` contains only `unpack_url`,
`get_http_url`, their helpers, and three local constants (`VCS_LIST`,
`SCHEME_LIST`, `VCS_SCHEMES`). The local `VCS_LIST`/`SCHEME_LIST` shadow
the ones in `pipenv/utils/constants.py` and are only needed by
`unpack_url`. The `VCS_SCHEMES` set is unique to this file.

**Risk:** low. `is_vcs` looks scary because of the `link.is_vcs`
attribute-access count, but those are pip's property and unrelated.

**Test pinning required:** yes — at minimum `merge_items` and `is_vcs`.

### T_E.4 — Relocate the pip-internal fork pair

**Symbols moved:** `unpack_url`, `get_http_url` (with the local
`VCS_SCHEMES` constant they depend on).

**Proposed destination:** new file `pipenv/utils/unpack.py`. Rationale:
the two functions are a coherent pair, are heavily provenance-commented,
and their pip-internal-fork nature is best signaled by a module-level
docstring that says exactly that. Folding them into `dependencies.py`
would put 60+ lines of provenance commentary inline with unrelated
Pipfile-modelling helpers.

**Alternative:** if the maintainer's preference (per §6 question 4) is
"don't add another file", fold into `dependencies.py` behind a clear
region comment like `# --- pip._internal.operations.prepare fork ---`.

**Caller files to update** (1):

| File | Old | New |
|---|---|---|
| `pipenv/utils/dependencies.py:36-40` | `from pipenv.utils.requirementslib import unpack_url` | `from pipenv.utils.unpack import unpack_url` (or intra-file) |

After this PR, `pipenv/utils/requirementslib.py` is empty: delete the
file in the same PR.

**Test pinning required:** `unpack_url`'s VCS-link return-value behaviour
is the load-bearing divergence from pip — this should be pinned before
the move. The patched-pip-vs-our-copy question raised in the triage stays
open as a future investigation; not part of E.

### T_E.5 — Co-locate `BAD_PACKAGES`

**Symbol moved:** `BAD_PACKAGES` constant (a 6-tuple, no helpers).

**Destination:** `pipenv/utils/dependencies.py` (per §3.1).

**Caller files to update** (4):

| File | Old | New |
|---|---|---|
| `pipenv/routines/graph.py:9` | `from pipenv.utils.requirements import BAD_PACKAGES` | `from pipenv.utils.dependencies import BAD_PACKAGES` |
| `pipenv/routines/uninstall.py:16` | `from pipenv.utils.requirements import BAD_PACKAGES` | `from pipenv.utils.dependencies import BAD_PACKAGES` |
| `pipenv/routines/clean.py:8` | `from pipenv.utils.requirements import BAD_PACKAGES` | `from pipenv.utils.dependencies import BAD_PACKAGES` |
| `pipenv/utils/requirements.py:117` | `BAD_PACKAGES` (intra-file ref inside `import_requirements`) | This call site moved to `dependencies.py` under E.2, so by E.5 it's intra-file in `dependencies.py` |

**Risk:** trivial. A 6-tuple of immutable strings.

**Test pinning required:** no behaviour to pin; the move is just a string
relocation.

### T_E.6 — `add_index_to_pipfile` rename

**Already folded into T_E.2.** Tracked here for completeness only; no
separate PR.

### T_E.7 — (optional, last) Rename `requirements.py` to `redact.py`

After E.2 and E.5 land, `requirements.py` holds only the two `redact_*`
helpers. The filename then becomes misleading in the same way
`requirementslib.py` was. Optional rename, decided per §6 question 7.

**Symbols moved:** none; just `git mv pipenv/utils/requirements.py
pipenv/utils/redact.py`.

**Caller files to update** (1 — the `redact_auth_from_url` import that
landed in E.2 inside `dependencies.py`):

| File | Old | New |
|---|---|---|
| `pipenv/utils/dependencies.py` (post-E.2) | `from pipenv.utils.requirements import redact_auth_from_url` | `from pipenv.utils.redact import redact_auth_from_url` |

**Risk:** trivial.

---

## 6. Decisions needed (sign-off list)

The maintainer must answer these before T_E.2 begins.

1. **Canonical home — `dependencies.py` vs themed split.** This proposal
   recommends `dependencies.py` as the single canonical home for the
   requirement model API (per the PRD). The alternative is to split into
   themed files (e.g. `pipfile_schema.py` for predicates,
   `requirement_io.py` for serialisation/lockfile bridges,
   `pip_compat.py` for the pip-internal fork pair). The split has clarity
   benefits but multiplies the number of moves and the chance of
   bikeshed-flavoured churn. **Recommendation: single home,
   `dependencies.py`.** Confirm or override.

2. **`requirementslib.py` filename — split and retire.** Three options
   were considered (§3.3). Recommendation is option (b): split and
   retire the file across E.3 (predicates + helpers) and E.4 (pip-internal
   pair). After both land, `git rm pipenv/utils/requirementslib.py`.
   Confirm or override.

3. **Module-level `add_index_to_pipfile` rename.** Recommendation:
   `add_index_to_pipfile_with_trust_check`. Alternatives:
   `register_index_in_pipfile`, `ensure_index_in_pipfile`,
   `prepare_and_add_index_to_pipfile`. **What's the right name?**

4. **`unpack_url` / `get_http_url` home.** Two options under E.4:
   - 4a. New file `pipenv/utils/unpack.py` (preferred — preserves the
     provenance-locked feel and groups the pair under a single module
     docstring).
   - 4b. Folded into the bottom of `dependencies.py` behind a region
     marker comment (avoids adding a file, costs visual separation).
   **Pick one.**

5. **`markers.py` — fold into `dependencies.py` or keep separate?**
   `markers.py` is 661 lines of owned glue. Folding it into
   `dependencies.py` would push the latter past 2200 lines and mix two
   distinct concerns (requirement modelling vs marker/specifier
   manipulation). **Recommendation: keep separate.** The cross-module
   imports are minimal (`PipenvMarkers` from dependencies; `RequirementError`
   from pipfile; `marker_from_specifier` late-imported from resolver) —
   merging would not eliminate any "where does X live?" ambiguity for
   the symbols at issue. Confirm or override.

6. **`redact_netloc` / `redact_auth_from_url` — stay or move?**
   Recommendation: stay in `requirements.py` (or in the renamed
   `redact.py` if §6 question 7 picks the rename). They are a
   project-owned fork of `pip._internal.utils.misc` helpers with
   load-bearing behavioural divergence (preserves `${ENV_VAR}` placeholders
   and `git` SSH username). They have **no thematic fit** with
   `dependencies.py` — they redact arbitrary URL credentials, not
   requirements. Confirm or override.

7. **Rename `requirements.py` to `redact.py` after E.2 + E.5?** Once the
   bridges and `BAD_PACKAGES` are gone, the file is two functions about
   URL credential redaction. The filename `requirements.py` would then
   actively mislead. **Recommendation: yes, rename as T_E.7.**
   Alternative: leave the file as-is and accept the legacy filename.
   Confirm or override.

8. **Coverage-gap remediation: which scope?** The modernization plan
   testing-strategy note flags `pipenv/utils/requirements.py` and
   `pipenv/utils/requirementslib.py` as having no dedicated test files,
   to be addressed during T_B.5 / T_E.1. T_B.5 added integration smoke
   coverage; T_E.1 (this design) marks the *unit* coverage as a
   per-wave pinning task in §5. **Recommendation: per-wave pinning
   (each E.2..E.5 PR adds pin tests for the symbols it moves), not a
   monolithic coverage-bump PR upfront.** Confirm or override.

---

## 7. Open implementation questions

Items the design surfaced but are not blocking decisions.

1. **Local `VCS_LIST` / `SCHEME_LIST` / `VCS_SCHEMES` constants in
   `requirementslib.py`.** Shadows of `pipenv/utils/constants.py`. After
   E.4, `unpack_url` is the only consumer of the local `VCS_SCHEMES`.
   Open question: does the local set differ semantically from
   `pipenv/utils/constants.py:VCS_SCHEMES`? If yes, preserve as a
   private module-level constant in the new home; if no, consolidate.
   Verify during E.4 implementation, not now.

2. **`patched-pip` direct-call for `unpack_url`/`get_http_url`.**
   Initiative B flagged the question "can we delete our fork and call
   `pipenv.patched.pip._internal.operations.prepare.unpack_url`
   directly?" The Wave 1c adopt-with-provenance commit (`2d897a0c`)
   documented two intentional behavioural divergences that block this
   today. Future investigation; not part of E.

3. **`merge_items` `sourced=True` branch.** The triage notes the
   `sourced=True` branch is preserved for API parity but has no in-tree
   callers. Open question for a future cleanup PR (not E): is anyone
   outside `pipenv/` calling this with `sourced=True`? CLI-as-contract
   policy from T_C.3 §9 says we don't owe external Python callers
   stability, so this is delete-candidate code. Out of scope for E
   (E is moves, not deletions of further-dead branches).

4. **Test-fixture co-location.** The pinning tests added under E.2..E.4
   should land in `tests/unit/utils/`. The naming convention for the new
   test files (`test_dependencies_bridges.py`? `test_dependencies_io.py`?
   one per logical group? one consolidated `test_dependencies.py`?) is
   a per-PR decision; not pre-committed here.

5. **`STRING_TYPE`, `PipfileEntryType`, `PipfileType` type aliases.**
   Defined at `requirementslib.py:19-22` and used only by the function
   signatures inside that file. After E.4 they're gone with the file.
   No move needed; flagged here only so the cleanup doesn't accidentally
   propagate them.

6. **Late imports vs top-level imports.** Three of the call sites are
   late imports (function-body `import` statements):
   `pipenv/utils/locking.py:566` (`requirement_from_lockfile`),
   `pipenv/routines/audit.py:237` (`requirements_from_lockfile`),
   `pipenv/project.py:909` (`is_vcs`), `pipenv/utils/resolver.py:813`
   (`marker_from_specifier`). These are presumably late-imported to
   avoid circular imports. The E.2/E.3 moves preserve the
   late-import pattern; the question of "can these now move to
   module-top imports?" is a separate import-cycle investigation,
   not part of E.

---

## 8. Out of scope for E.1

- **The actual moves (E.2..E.7).** This document specifies them; it
  does not execute them. Each subsequent task takes one wave from §5.
- **Anything in Initiative C / D / F's lane.** No routine context
  changes. No Project god-class decomposition. No resolver-protocol
  schema design.
- **Anything user-visible.** No CLI flag changes, no Pipfile schema
  changes, no error message changes, no logging changes.
- **`normalize_name` / `pep423_name` consolidation.** This was already
  resolved under Wave 1c commit `e874e9d0`. The triage doc flagged it
  for Initiative E pre-Wave-1c; the work landed earlier than the
  initiative gating suggested.
- **`pipenv/utils/constants.py` cleanup.** The `VCS_LIST`/`SCHEME_LIST`
  shadow in `requirementslib.py` (open question §7.1) is in scope for
  E.4 only insofar as the local constant disappears with the file;
  the broader question of whether `constants.py` is the right home for
  these tuples is a separate Initiative-A-style URL/scheme question.
- **Patched-pip direct-call investigation for `unpack_url`.** Flagged
  in §7.2 as future work.
- **Test-coverage policy beyond pinning the moved symbols.** Broader
  unit-coverage backfills are Initiative-D-adjacent / general-hygiene
  work, not Initiative E.

---

## Appendix: caller-count verification commands

The counts in §2 and §5 were verified on `maintenance/code-cleanup-2026-05`
at HEAD on 2026-05-12 with:

```
grep -rn "from pipenv.utils.requirements import\|from .requirements import" \
  pipenv/ --include="*.py" | grep -v patched | grep -v vendor

grep -rn "from pipenv.utils.requirementslib import\|from .requirementslib import" \
  pipenv/ --include="*.py" | grep -v patched | grep -v vendor

grep -rn "from pipenv.utils.markers import\|from .markers import" \
  pipenv/ --include="*.py" | grep -v patched | grep -v vendor

# Per-symbol example:
grep -rn "\bBAD_PACKAGES\b" pipenv/ --include="*.py" \
  | grep -v patched | grep -v vendor
```

A reviewer can re-run these to verify nothing shifted between this design
and the first execution PR (T_E.2).
