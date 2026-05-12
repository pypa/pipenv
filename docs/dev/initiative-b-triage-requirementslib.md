# Initiative B Triage: `pipenv/utils/requirementslib.py`

Per-symbol audit of the 740-line module `pipenv/utils/requirementslib.py`,
inlined from the now-archived `requirementslib` PyPI package. For each
public top-level symbol the table records: a one-line purpose; the count
of internal callers (excluding the definition site, excluding
`patched/`/`vendor/`); a provenance assessment; and a recommendation of
**adopt** (project owns it; refactor freely), **vendor** (treat as frozen
upstream; move under `pipenv/vendor/` and stop modifying), or **delete**
(no internal callers, no plan to expose externally).

> **Method.** Caller counts come from
> `grep -rn "\b<symbol>\b" pipenv/ --include="*.py" | grep -v patched | grep -v vendor`,
> with the definition site removed and ambiguous matches (e.g. attribute
> accesses like `link.is_vcs`, `sysconfig.get_path`) audited by hand. The
> orchestrator can re-verify any row by running the same grep.

## 1. Per-symbol table

| # | Symbol | Purpose (one line) | Internal callers | Provenance | Recommendation |
|---|--------|--------------------|------------------|------------|----------------|
| 1 | `strip_ssh_from_git_uri` | Rewrite `git+ssh://` URI to pip's `git+git@…` form. | **0** (no importers, no in-module callers) — 🗑️ **delete candidate** | Pip-internal-style VCS URI helper; mirrors logic in legacy `pip._internal.vcs.git`. Not boltons. | **delete** |
| 2 | `add_ssh_scheme_to_git_uri` | Inverse of #1: add `ssh://` scheme so `urlparse` works on `git+user@host:…`. | 2 (`pipfile_entry` in `is_vcs` here; `pipenv/utils/dependencies.py:37,1031`) | Pip-internal-style VCS URI helper. Not boltons. | **adopt** |
| 3 | `is_vcs` | Return True if a Pipfile entry (mapping or string) is a VCS dep. | 4 import sites (`pipenv/utils/pipfile.py:14`, `pipenv/utils/locking.py:30`, `pipenv/project.py:942`, plus `dependencies.py` via star-of-block import) and used in `pipfile.py:340`, `locking.py:362`, `project.py:945`. | Project predicate over Pipfile schema — pipenv-specific. Not from a live upstream. | **adopt** |
| 4 | `is_editable` | Return True if a Pipfile entry has `editable: true` or `-e ` prefix. | 2 import sites (`pipfile.py:14`, `locking.py:30`); used in `pipfile.py:342`, `locking.py:364`, `project.py:48,938`. **Note:** a near-duplicate `is_editable` lives at `pipenv/utils/dependencies.py:1503` (mapping-only, no `-e ` string branch). | Project predicate. Not boltons. | **adopt** (also: collapse the dependencies.py duplicate during the adopt pass) |
| 5 | `is_star` | Return True if a Pipfile version is `"*"` (string or `{"version": "*"}`). | **0** importers of *this* `is_star`. All real callers use the duplicate `pipenv/utils/dependencies.py:418` (`is_editable_path, is_star, …` imports) — 🗑️ **delete candidate** | Project predicate. The dependencies.py copy is the canonical one. | **delete** |
| 6 | `convert_entry_to_path` | Convert a Pipfile `{file: …}` / `{path: …}` mapping to a filesystem path string. | 1 (only internal: `is_installable_file` at line 149 in this module). | Pipenv-specific helper over Pipfile schema. | **delete** (only kept alive by #7, which is itself a delete candidate — cascades) |
| 7 | `is_installable_file` | Heuristic: is the given path/URL something pip can install? | **0** importers — 🗑️ **delete candidate** | Pip-internal-style predicate; legacy of `requirementslib`. | **delete** |
| 8 | `get_setup_paths` | Locate `setup.py` / `setup.cfg` / `pyproject.toml` under a directory. | **0** importers — 🗑️ **delete candidate** | Legacy of `requirementslib`. No replacement needed — pip handles this itself. | **delete** |
| 9 | `prepare_pip_source_args` | Build `-i …`/`--extra-index-url …` CLI args from a `sources` list. | **0** importers — 🗑️ **delete candidate**. A **second**, divergent definition lives at `pipenv/utils/indexes.py:18` and is what every real caller (`pipenv/utils/pip.py:9`, `environment.py:31`, `dependencies.py:39`, `resolver.py:48`) actually imports. | Pipenv-specific. The `indexes.py` copy is the canonical, more defensively coded version (validates URL presence, uses `parse_url` for trusted-host formatting). | **delete** |
| 10 | `get_package_finder` | Thin shim around `InstallCommand._build_package_finder`. | **0** importers — 🗑️ **delete candidate**. A near-duplicate at `pipenv/utils/resolver.py:162` (adds explicit `py_version_info` kwarg) is what real callers (`environment.py:554`, `resolver.py:605`) use. | Pip-internal-style shim. The resolver.py copy is canonical. | **delete** |
| 11 | `PathAccessError` (class) | Exception type unifying `KeyError`/`IndexError`/`TypeError` for nested-lookup failures. | **0** external; used internally by `get_path` only. | **boltons.iterutils** (live upstream). | **vendor** (group A — see §2) |
| 12 | `get_path` | Look up a value in a nested dict/list by tuple path, with optional default. | **0** external. The two `get_path` matches outside this module are `sysconfig.get_path(…)` — a stdlib attribute access, not this function. One internal caller at line 636 (inside `merge_items`). | **boltons.iterutils** (live upstream). | **vendor** (group A) |
| 13 | `default_visit` | No-op visit callback for `remap`. | **0** external; used by `remap` (line 471) and `merge_items` (line 655). | **boltons.iterutils** (live upstream). | **vendor** (group A) |
| 14 | `dict_path_enter` | `remap` enter callback that handles dict / list / set / `tomlkit` containers. | **0** external; used by `remap` (line 471) and `merge_items` (line 631). | **boltons.iterutils** (live upstream); modified to add `tomlkit.items.Table`/`InlineTable`/`Array` branches. | **vendor** (group A) — but flag the tomlkit-specific branches as a pipenv-side modification a maintainer may need to keep applied if/when this is re-vendored from upstream boltons. |
| 15 | `dict_path_exit` | `remap` exit callback; reassembles parents after children are visited. | **0** external; used by `remap` (line 471) and `merge_items` (line 645). | **boltons.iterutils** (live upstream); modified for `tomlkit.items.Array`. | **vendor** (group A) — same tomlkit-modification caveat as #14. |
| 16 | `remap` | Recursive traverse-and-transform over heterogeneous nested structures. | **0** external; used by `merge_items` (line 657). | **boltons.iterutils** (live upstream). | **vendor** (group A) |
| 17 | `merge_items` | Merge a list of nested dicts (Pipfile categories) using `remap`. | 3 import sites (`pipfile.py:14`, `locking.py:30`) and used in `pipfile.py:318`, `locking.py:387,580`. | Built on top of the boltons primitives but the *signature* (Pipfile-category list merge) is pipenv's own usage shape. | **adopt** (this is the project's public entry-point into the boltons tree) |
| 18 | `get_pip_command` | Construct pip's `InstallCommand` for option/conf parsing. | 2 (`dependencies.py:38,906`). | Pipenv-specific thin wrapper around `pipenv.patched.pip._internal.commands.install.InstallCommand`. | **adopt** |
| 19 | `unpack_url` | Unpack a `Link` (VCS / file / HTTP) into a target location. | 2 (`dependencies.py:40,910`). | Lifted verbatim from `pip._internal.operations.prepare.unpack_url`. Pip still ships this function — it is reachable as `pipenv.patched.pip._internal.operations.prepare.unpack_url`. | **adopt** — but flag for follow-up: investigate whether the patched-pip copy can be called directly (T_B.5 territory). |
| 20 | `get_http_url` | Download an HTTP URL into a temp dir; honour `download_dir`. | 1 (only internal: `unpack_url` at line 703). | Lifted verbatim from `pip._internal.operations.prepare.get_http_url`. Same as #19 — pip still ships this. | **adopt** (lives with #19; if #19 is later swapped for the patched-pip version, this dies with it) |

## 2. Coherent groups

### Group A — Boltons iterutils dict-tree walkers (vendor as a unit)

`PathAccessError`, `get_path`, `default_visit`, `dict_path_enter`,
`dict_path_exit`, `remap` (rows 11–16). These six symbols are an inlined,
lightly-modified copy of `boltons.iterutils`. The package is still
maintained upstream (https://github.com/mahmoud/boltons). They have zero
non-pipenv external callers and **only one in-tree caller**: `merge_items`
(row 17), which is pipenv-owned.

**Recommendation:** vendor the boltons subset under `pipenv/vendor/boltons/`
via the project's standard vendoring tooling, then have `merge_items`
import from there. This stops the maintenance treadmill on code we
should not be modifying. The two pipenv-side modifications worth
preserving on re-vendor are the `tomlkit.items.Table`/`InlineTable`/
`Array` branches inside `dict_path_enter` (row 14) and `dict_path_exit`
(row 15) — these exist so `merge_items` works on tomlkit's container
types directly, not just plain dicts/lists.

### Group B — Resurrected pip prepare-step helpers (adopt as a pair)

`unpack_url` and `get_http_url` (rows 19–20). Lifted verbatim from
`pip._internal.operations.prepare`. They form a closed pair (`get_http_url`
has no external callers; it exists solely to support `unpack_url`).

**Recommendation:** adopt the pair for now, but log a follow-up under
T_B.5 to investigate whether `pipenv.patched.pip._internal.operations.prepare.unpack_url`
can be called directly. If yes, both rows die together.

### Group C — Pipfile-schema project predicates (adopt)

`is_vcs`, `is_editable`, `add_ssh_scheme_to_git_uri`, `merge_items`,
`get_pip_command` (rows 2, 3, 4, 17, 18). These are pipenv-specific. The
domain is "the shape of a Pipfile entry" plus "where pip's options
parser lives", which is pipenv's responsibility regardless of upstream
status. They should be refactored freely. During the adopt pass:

- Collapse the `is_editable` duplicate at `dependencies.py:1503`. Inspect
  whether the missing `-e ` string branch is intentional in any callers.
- Decide where these helpers actually belong long-term — `requirementslib.py`
  is a historical name; `pipenv/utils/pipfile_schema.py` or absorbing
  them into `pipenv/utils/pipfile.py` would be more honest.

### Group D — Dead code (delete candidates) 🗑️

Rows 1, 5, 6, 7, 8, 9, 10. All have **zero** importers in `pipenv/`
(after disambiguating attribute-access collisions and accounting for
in-module-only callers that themselves have no importers):

- `strip_ssh_from_git_uri` (row 1) — never called.
- `is_star` (row 5) — shadowed by the canonical copy at `dependencies.py:418`.
- `convert_entry_to_path` (row 6) — only kept alive by `is_installable_file`, which is itself dead.
- `is_installable_file` (row 7) — never imported.
- `get_setup_paths` (row 8) — never imported.
- `prepare_pip_source_args` (row 9) — shadowed by the canonical (and more robust) copy at `indexes.py:18`.
- `get_package_finder` (row 10) — shadowed by the canonical copy at `resolver.py:162`.

**Recommendation:** these are the cheap wins for Initiative E (dead-code
removal). Deleting all seven (plus `convert_entry_to_path` as a cascade
from `is_installable_file`) drops roughly 180 lines from the module
without behaviour change. The `prepare_pip_source_args` and
`get_package_finder` rows in particular are doubly compelling — they are
*divergent stale copies*, so removing them eliminates a future
"which-version-am-I-importing?" footgun.

## 3. Summary

| Bucket | Count | Symbols |
|--------|-------|---------|
| **adopt** | 7 | `add_ssh_scheme_to_git_uri`, `is_vcs`, `is_editable`, `merge_items`, `get_pip_command`, `unpack_url`, `get_http_url` |
| **vendor** | 6 | `PathAccessError`, `get_path`, `default_visit`, `dict_path_enter`, `dict_path_exit`, `remap` (boltons.iterutils — group A) |
| **delete** 🗑️ | 7 | `strip_ssh_from_git_uri`, `is_star`, `convert_entry_to_path`, `is_installable_file`, `get_setup_paths`, `prepare_pip_source_args`, `get_package_finder` |
| **total** | **20** | |

## 4. Most consequential findings (for the orchestrator)

1. **Seven of twenty public symbols are dead code or stale duplicates**
   of canonical copies elsewhere in the tree. This is the largest cheap
   win identified so far in the modernization sweep — likely ~25% of the
   module by line count.
2. **Two of those seven dead duplicates (`prepare_pip_source_args`,
   `get_package_finder`) have *divergent* implementations** from the
   versions actually in use. Anyone editing this module today is
   plausibly editing the wrong copy without noticing. Delete-first is
   the right hygiene step before any further work on Initiative B.
3. **The six boltons-derived dict-walkers cluster cleanly into a single
   `vendor` decision.** They have a single in-tree user (`merge_items`),
   which makes the redirect mechanical. The only wrinkle is that
   pipenv has added tomlkit-container branches inside `dict_path_enter`
   / `dict_path_exit`; if these are kept after vendoring, the
   modifications need to live as a small adapter, not as edits to the
   vendored file.
4. **`is_editable` is duplicated within the project** (`requirementslib.py`
   vs. `dependencies.py:1503`) with *different* semantics — the
   dependencies.py copy drops the `-e ` string-prefix branch. T_B.5
   (the refactor pass) should reconcile these intentionally rather
   than letting two slightly-wrong copies persist.
5. **`unpack_url` / `get_http_url` are verbatim copies of still-extant
   `pip._internal.operations.prepare` helpers.** T_B.5 should evaluate
   whether the patched-pip versions can be called directly; if so the
   adopt-count drops from 7 to 5.
