# Initiative B Triage: Inlined-Former-Vendor Modules

This document captures the Initiative B triage decisions for inlined-former-vendor modules under `pipenv/utils/`. Each section flagged a symbol or symbol-group as **adopt**, **vendor**, or **delete**. The work is executed directly under Initiative B / Wave 1c rather than tracked as GitHub issues — the per-symbol audit below is the working record.

Scope covered by this synthesis:

- `pipenv/utils/requirementslib.py` (T_B.1) — 20 public symbols
- `pipenv/utils/requirements.py` (T_B.2) — 9 functions + `BAD_PACKAGES` constant
- `pipenv/utils/fileutils.py` (T_B.3) — 3 URL/path converters
- `pipenv/utils/markers.py` (T_B.4) — no separate vendor lineage; recorded for completeness

## Summary table

Rows are sorted by Decision (delete, then vendor, then adopt — cheapest first), and alphabetically within each decision group. Caller counts are external call sites; see the per-module sections for grep methodology.

| Symbol or group | Module | Decision | Caller count |
|---|---|---|---|
| `convert_entry_to_path` | `pipenv/utils/requirementslib.py` | delete | 0 (cascade from `is_installable_file`) |
| `get_package_finder` | `pipenv/utils/requirementslib.py` | delete | 0 (shadowed by canonical copy in `resolver.py:162`) |
| `get_setup_paths` | `pipenv/utils/requirementslib.py` | delete | 0 |
| `is_installable_file` | `pipenv/utils/requirementslib.py` | delete | 0 |
| `is_star` | `pipenv/utils/requirementslib.py` | delete | 0 (shadowed by canonical copy in `dependencies.py:418`) |
| `normalize_name` | `pipenv/utils/requirements.py` | delete | 4 (callers migrate to `pep423_name`; `pep423_name`'s dead-`else` bug fixed in the same wave) |
| `prepare_pip_source_args` | `pipenv/utils/requirementslib.py` | investigate (was: delete) | 1 (`dependencies.py:36-41,524` — W1 verification surfaced a real caller the triage missed; the requirementslib and indexes.py copies are observably divergent) |
| `strip_ssh_from_git_uri` | `pipenv/utils/requirementslib.py` | delete | 0 |
| `default_visit` | `pipenv/utils/requirementslib.py` | replace (purpose-built helper) | 0 external (used by `remap`, `merge_items`) |
| `dict_path_enter` | `pipenv/utils/requirementslib.py` | replace (purpose-built helper) | 0 external (used by `remap`, `merge_items`) |
| `dict_path_exit` | `pipenv/utils/requirementslib.py` | replace (purpose-built helper) | 0 external (used by `remap`, `merge_items`) |
| `get_path` | `pipenv/utils/requirementslib.py` | replace (purpose-built helper) | 0 external (one internal use in `merge_items`) |
| `PathAccessError` | `pipenv/utils/requirementslib.py` | replace (purpose-built helper) | 0 external (used by `get_path`) |
| `remap` | `pipenv/utils/requirementslib.py` | replace (purpose-built helper) | 0 external (used by `merge_items`) |
| `redact_auth_from_url` | `pipenv/utils/requirements.py` | adopt (with provenance docstring) | 0 external (only by `import_requirements` in this module) |
| `redact_netloc` | `pipenv/utils/requirements.py` | adopt (with provenance docstring) | 0 external (only by `redact_auth_from_url`) |
| `add_index_to_pipfile` | `pipenv/utils/requirements.py` | adopt | 2 |
| `add_ssh_scheme_to_git_uri` | `pipenv/utils/requirementslib.py` | adopt | 2 |
| `get_http_url` | `pipenv/utils/requirementslib.py` | adopt (or delete via patched-pip) | 1 (only internal: `unpack_url`) |
| `get_pip_command` | `pipenv/utils/requirementslib.py` | adopt | 2 |
| `import_requirements` | `pipenv/utils/requirements.py` | adopt | 2 |
| `is_editable` | `pipenv/utils/requirementslib.py` | adopt (collapse duplicate in `dependencies.py:1503`) | 2 import sites + 4 use sites |
| `is_file_url` | `pipenv/utils/fileutils.py` | adopt | 0 external (gates `file://` branch in `open_file`, `url_to_path`) |
| `is_vcs` | `pipenv/utils/requirementslib.py` | adopt | 4 import sites + multiple use sites |
| `merge_items` | `pipenv/utils/requirementslib.py` | adopt (rebuilt on purpose-built helper) | 3 (project's public entry point) |
| `path_to_url` | `pipenv/utils/fileutils.py` | adopt | 0 external (only internal caller is `open_file`); duplicate-name hazard in `shell.py:104` resolved under Initiative A |
| `requirement_from_lockfile` | `pipenv/utils/requirements.py` | adopt | 3 |
| `requirement_from_pipfile` | `pipenv/utils/requirements.py` | adopt | 0 external (only by `requirements_from_pipfile`) |
| `requirements_from_lockfile` | `pipenv/utils/requirements.py` | adopt | 2 |
| `requirements_from_pipfile` | `pipenv/utils/requirements.py` | adopt | 1 |
| `unpack_url` | `pipenv/utils/requirementslib.py` | adopt (or delete via patched-pip) | 2 (verbatim copy of `pip._internal.operations.prepare.unpack_url`) |
| `url_to_path` | `pipenv/utils/fileutils.py` | adopt | 2 (in `requirementslib.py`); inverse of `path_to_url` |

The `markers.py` module is **not in this table**: T_B.4 found it is owned project glue over `pipenv.patched.pip._vendor.{distlib,packaging}` and has no separate vendor lineage to triage. It is recorded under its own section below so the "is this vendored?" question stays closed.

Cross-cutting flags surfaced during triage (acted on under other initiatives, not this one):

- `normalize_name` ↔ `pep423_name` overlap — Initiative E (requirement-model consolidation).
- Second `path_to_url` at `pipenv/utils/shell.py:104` — Initiative A's URL/scheme consolidation pass.
- `BAD_PACKAGES` constant in `requirements.py` — Initiative E co-location question.

---

## `pipenv/utils/requirementslib.py` (T_B.1)

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

### Per-symbol table

| # | Symbol | Purpose (one line) | Internal callers | Provenance | Recommendation |
|---|--------|--------------------|------------------|------------|----------------|
| 1 | `strip_ssh_from_git_uri` | Rewrite `git+ssh://` URI to pip's `git+git@…` form. | **0** (no importers, no in-module callers) — delete candidate | Pip-internal-style VCS URI helper; mirrors logic in legacy `pip._internal.vcs.git`. Not boltons. | **delete** |
| 2 | `add_ssh_scheme_to_git_uri` | Inverse of #1: add `ssh://` scheme so `urlparse` works on `git+user@host:…`. | 2 (`pipfile_entry` in `is_vcs` here; `pipenv/utils/dependencies.py:37,1031`) | Pip-internal-style VCS URI helper. Not boltons. | **adopt** |
| 3 | `is_vcs` | Return True if a Pipfile entry (mapping or string) is a VCS dep. | 4 import sites (`pipenv/utils/pipfile.py:14`, `pipenv/utils/locking.py:30`, `pipenv/project.py:942`, plus `dependencies.py` via star-of-block import) and used in `pipfile.py:340`, `locking.py:362`, `project.py:945`. | Project predicate over Pipfile schema — pipenv-specific. Not from a live upstream. | **adopt** |
| 4 | `is_editable` | Return True if a Pipfile entry has `editable: true` or `-e ` prefix. | 2 import sites (`pipfile.py:14`, `locking.py:30`); used in `pipfile.py:342`, `locking.py:364`, `project.py:48,938`. **Note:** a near-duplicate `is_editable` lives at `pipenv/utils/dependencies.py:1503` (mapping-only, no `-e ` string branch). | Project predicate. Not boltons. | **adopt** (also: collapse the dependencies.py duplicate during the adopt pass) |
| 5 | `is_star` | Return True if a Pipfile version is `"*"` (string or `{"version": "*"}`). | **0** importers of *this* `is_star`. All real callers use the duplicate `pipenv/utils/dependencies.py:418` (`is_editable_path, is_star, …` imports) — delete candidate | Project predicate. The dependencies.py copy is the canonical one. | **delete** |
| 6 | `convert_entry_to_path` | Convert a Pipfile `{file: …}` / `{path: …}` mapping to a filesystem path string. | 1 (only internal: `is_installable_file` at line 149 in this module). | Pipenv-specific helper over Pipfile schema. | **delete** (only kept alive by #7, which is itself a delete candidate — cascades) |
| 7 | `is_installable_file` | Heuristic: is the given path/URL something pip can install? | **0** importers — delete candidate | Pip-internal-style predicate; legacy of `requirementslib`. | **delete** |
| 8 | `get_setup_paths` | Locate `setup.py` / `setup.cfg` / `pyproject.toml` under a directory. | **0** importers — delete candidate | Legacy of `requirementslib`. No replacement needed — pip handles this itself. | **delete** |
| 9 | `prepare_pip_source_args` | Build `-i …`/`--extra-index-url …` CLI args from a `sources` list. | **1**: `pipenv/utils/dependencies.py:36-41` imports from `requirementslib`; used at `dependencies.py:524`. (`pipenv/utils/pip.py:9`, `environment.py:31`, `resolver.py:48` correctly import from `indexes.py`.) W1's verification corrected the triage's original claim of 0 callers. | Pipenv-specific. The two copies **diverge**: the `indexes.py` copy strips credentials with `_strip_credentials_from_url`, validates URL presence with `PipenvUsageError`, handles ports in trusted-host args via `urllib3.util.parse_url`, and uses `.get("url")` defensively; the `requirementslib.py` copy uses subscript access (`sources[0]["url"]`), `urlparse(...).hostname` for trusted-host, and silently skips the URL-missing case. Switching `dependencies.py:524` between them is a behaviour change. | **investigate** under W3 — pair with the `unpack_url`/`get_http_url` "is the divergent stale copy safely replaceable?" question. |
| 10 | `get_package_finder` | Thin shim around `InstallCommand._build_package_finder`. | **0** importers — delete candidate. A near-duplicate at `pipenv/utils/resolver.py:162` (adds explicit `py_version_info` kwarg) is what real callers (`environment.py:554`, `resolver.py:605`) use. | Pip-internal-style shim. The resolver.py copy is canonical. | **delete** |
| 11 | `PathAccessError` (class) | Exception type unifying `KeyError`/`IndexError`/`TypeError` for nested-lookup failures. | **0** external; used internally by `get_path` only. | **boltons.iterutils** (live upstream). | **vendor** (group A — see below) |
| 12 | `get_path` | Look up a value in a nested dict/list by tuple path, with optional default. | **0** external. The two `get_path` matches outside this module are `sysconfig.get_path(…)` — a stdlib attribute access, not this function. One internal caller at line 636 (inside `merge_items`). | **boltons.iterutils** (live upstream). | **vendor** (group A) |
| 13 | `default_visit` | No-op visit callback for `remap`. | **0** external; used by `remap` (line 471) and `merge_items` (line 655). | **boltons.iterutils** (live upstream). | **vendor** (group A) |
| 14 | `dict_path_enter` | `remap` enter callback that handles dict / list / set / `tomlkit` containers. | **0** external; used by `remap` (line 471) and `merge_items` (line 631). | **boltons.iterutils** (live upstream); modified to add `tomlkit.items.Table`/`InlineTable`/`Array` branches. | **vendor** (group A) — but flag the tomlkit-specific branches as a pipenv-side modification a maintainer may need to keep applied if/when this is re-vendored from upstream boltons. |
| 15 | `dict_path_exit` | `remap` exit callback; reassembles parents after children are visited. | **0** external; used by `remap` (line 471) and `merge_items` (line 645). | **boltons.iterutils** (live upstream); modified for `tomlkit.items.Array`. | **vendor** (group A) — same tomlkit-modification caveat as #14. |
| 16 | `remap` | Recursive traverse-and-transform over heterogeneous nested structures. | **0** external; used by `merge_items` (line 657). | **boltons.iterutils** (live upstream). | **vendor** (group A) |
| 17 | `merge_items` | Merge a list of nested dicts (Pipfile categories) using `remap`. | 3 import sites (`pipfile.py:14`, `locking.py:30`) and used in `pipfile.py:318`, `locking.py:387,580`. | Built on top of the boltons primitives but the *signature* (Pipfile-category list merge) is pipenv's own usage shape. | **adopt** (this is the project's public entry-point into the boltons tree) |
| 18 | `get_pip_command` | Construct pip's `InstallCommand` for option/conf parsing. | 2 (`dependencies.py:38,906`). | Pipenv-specific thin wrapper around `pipenv.patched.pip._internal.commands.install.InstallCommand`. | **adopt** |
| 19 | `unpack_url` | Unpack a `Link` (VCS / file / HTTP) into a target location. | 2 (`dependencies.py:40,910`). | Lifted verbatim from `pip._internal.operations.prepare.unpack_url`. Pip still ships this function — it is reachable as `pipenv.patched.pip._internal.operations.prepare.unpack_url`. | **adopt** — but flag for follow-up: investigate whether the patched-pip copy can be called directly. |
| 20 | `get_http_url` | Download an HTTP URL into a temp dir; honour `download_dir`. | 1 (only internal: `unpack_url` at line 703). | Lifted verbatim from `pip._internal.operations.prepare.get_http_url`. Same as #19 — pip still ships this. | **adopt** (lives with #19; if #19 is later swapped for the patched-pip version, this dies with it) |

### Coherent groups

#### Group A — Boltons iterutils dict-tree walkers (vendor as a unit)

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

#### Group B — Resurrected pip prepare-step helpers (adopt as a pair)

`unpack_url` and `get_http_url` (rows 19–20). Lifted verbatim from
`pip._internal.operations.prepare`. They form a closed pair (`get_http_url`
has no external callers; it exists solely to support `unpack_url`).

**Recommendation:** adopt the pair for now, but log a follow-up to
investigate whether `pipenv.patched.pip._internal.operations.prepare.unpack_url`
can be called directly. If yes, both rows die together.

#### Group C — Pipfile-schema project predicates (adopt)

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

#### Group D — Dead code (delete candidates)

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

### Summary (requirementslib.py)

| Bucket | Count | Symbols |
|--------|-------|---------|
| **adopt** | 7 | `add_ssh_scheme_to_git_uri`, `is_vcs`, `is_editable`, `merge_items`, `get_pip_command`, `unpack_url`, `get_http_url` |
| **vendor** | 6 | `PathAccessError`, `get_path`, `default_visit`, `dict_path_enter`, `dict_path_exit`, `remap` (boltons.iterutils — group A) |
| **delete** | 7 | `strip_ssh_from_git_uri`, `is_star`, `convert_entry_to_path`, `is_installable_file`, `get_setup_paths`, `prepare_pip_source_args`, `get_package_finder` |
| **total** | **20** | |

### Most consequential findings (requirementslib.py)

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
   dependencies.py copy drops the `-e ` string-prefix branch. The
   refactor pass should reconcile these intentionally rather
   than letting two slightly-wrong copies persist.
5. **`unpack_url` / `get_http_url` are verbatim copies of still-extant
   `pip._internal.operations.prepare` helpers.** The refactor pass should
   evaluate whether the patched-pip versions can be called directly; if
   so the adopt-count drops from 7 to 5.

---

## `pipenv/utils/requirements.py` (T_B.2)

Per-function audit of the 395-line module. Caller counts are external
call sites only (the symbol's own definition and intra-module helper
calls are excluded). Greps were run across `pipenv/`, excluding
`pipenv/patched/` and `pipenv/vendor/`.

Reproduce a count with, e.g.:

```
grep -rn "normalize_name" pipenv/ --include="*.py" \
  | grep -v pipenv/patched/ | grep -v pipenv/vendor/
```

### Function table

| # | Symbol | One-line description | External callers | Provenance | Recommendation |
|---|---|---|---|---|---|
| 1 | `redact_netloc` | Mask credentials in a URL netloc, preserving `${ENV_VAR}` placeholders and standard SSH usernames (e.g. `git`). | 0 (only called by `redact_auth_from_url` in the same module) | Pip-internal fork. Pip's `pipenv.patched.pip._internal.utils.misc.redact_netloc` (misc.py:456) has the same signature but lossy semantics — it always replaces user/password with `****`. Our copy intentionally preserves env-var placeholders and the standard `git` SSH user. | **vendor** (keep as project-owned fork; see provenance note below) |
| 2 | `redact_auth_from_url` | Apply `redact_netloc` to the netloc of a full URL via pip's `_transform_url`. | 1 (`pipenv/utils/requirements.py:104` via `import_requirements`) — i.e. 0 outside this file | Pip-internal fork. Pip's `redact_auth_from_url` (misc.py:523) is a one-line wrapper around the lossy `redact_netloc`; ours is the same wrapper but delegates to the env-var-aware local `redact_netloc`. | **vendor** (keep as project-owned fork; tied to #1) |
| 3 | `normalize_name` | Lowercase a name and replace `_` with `-`. | 4 call sites: `pipenv/utils/locking.py:55`, `pipenv/project.py:351`, `pipenv/project.py:1354`, `pipenv/utils/resolver.py:1004` | **Project-owned, overlaps with `pep423_name`** (see overlap section). | **delete** (move/merge under Initiative E — see overlap section) |
| 4 | `import_requirements` | Parse a `requirements.txt` with pip's `parse_requirements`, batch-add each package to the Pipfile, and register discovered indexes/trusted hosts. | 2 (`pipenv/utils/pipfile.py:103`, `pipenv/routines/install.py:536`) | Project-owned bridge: composes pip parsing with the `Project` model. | **adopt** |
| 5 | `add_index_to_pipfile` | Decide whether a Pipfile index requires HTTPS based on the trusted-hosts list, then delegate to `Project.add_index_to_pipfile`. | 2 (`pipenv/routines/install.py:167`, `pipenv/routines/update.py:649`) | Project-owned bridge. Name collides with the method `Project.add_index_to_pipfile` (`pipenv/project.py:1569`); the module-level function calls the method, not vice versa. | **adopt** (consider renaming under Initiative E to disambiguate from the `Project` method) |
| 6 | `requirement_from_lockfile` | Convert a single `(name, locked_info)` pair into a pip-installable line (handles VCS, file/path, and standard PyPI cases, with optional hashes/markers). | 3 (`pipenv/utils/locking.py:584`, `pipenv/utils/locking.py:599`, `pipenv/utils/locking.py:603`) | Project-owned lockfile bridge. | **adopt** |
| 7 | `requirements_from_lockfile` | Map `requirement_from_lockfile` over a lock dict. | 2 (`pipenv/routines/audit.py:244`, `pipenv/routines/requirements.py:89`) | Project-owned lockfile bridge. | **adopt** |
| 8 | `requirement_from_pipfile` | Convert a single Pipfile entry (str or dict) into a pip-installable line using Pipfile version specifiers rather than locked versions. | 0 (only invoked by the sibling `requirements_from_pipfile` in this module) | Project-owned Pipfile bridge. | **adopt** |
| 9 | `requirements_from_pipfile` | Map `requirement_from_pipfile` over a Pipfile deps dict. | 1 (`pipenv/routines/requirements.py:139`) | Project-owned Pipfile bridge. | **adopt** |

The module-level constant `BAD_PACKAGES` (line 148) is not a function
but is also a public export and is imported by `pipenv/routines/graph.py`,
`pipenv/routines/clean.py`, and `pipenv/routines/uninstall.py`. It is in
scope for Initiative E only as a co-location question and is not part of
this audit's adopt/vendor/delete tally.

### The `normalize_name` / `pep423_name` overlap (flag for Initiative E)

The two helpers normalize a distribution name to the same target
(lowercase, hyphenated) and live in sibling modules:

`pipenv/utils/requirements.py:61`

```python
def normalize_name(pkg) -> str:
    """Given a package name, return its normalized, non-canonicalized form."""
    return pkg.replace("_", "-").lower()
```

`pipenv/utils/dependencies.py:134`

```python
def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    name = name.lower()
    if any(i not in name for i in (VCS_LIST + SCHEME_LIST)):
        return name.replace("_", "-")
    else:
        return name
```

For ordinary distribution names the two functions return the same
string. `pep423_name` adds a guard that skips the `_`→`-` rewrite when
the input *contains every* VCS scheme and URL scheme in
`VCS_LIST + SCHEME_LIST` simultaneously — a condition that is effectively
unreachable for real package names, which means the two helpers are de
facto equivalent in practice. The guard is also almost certainly buggy:
the `any(... not in name for ...)` predicate is true for any name that
is missing at least one scheme token, so the early-return branch is the
common case and the `else` branch is dead. That bug is out of scope for
this triage.

External call-site counts:

- `normalize_name`: 4 external call sites (table above).
- `pep423_name`: 11 external call sites across `pipenv/utils/locking.py`,
  `pipenv/project.py`, `pipenv/routines/outdated.py`, and
  `pipenv/routines/uninstall.py`.

**Recommendation (flag, do not act here):** `normalize_name` is a
candidate to be merged into `pep423_name` (or both replaced by a single
canonical helper, plausibly `pipenv.utils.dependencies.normalize_name`)
under **Initiative E** — requirement-model consolidation. This triage
only flags the overlap; the actual move belongs to Initiative E so it
can be planned alongside the other dependency-helper relocations.

### Why we don't just `from pip._internal.utils.misc import redact_*`

`pipenv/utils/requirements.py:18` and `:52` look at first glance like
copy-paste of `pipenv/patched/pip/_internal/utils/misc.py:456` and
`:523`. They are not safe to delete in favor of the pip imports:

1. **Env-var placeholders are preserved.** Pip's `redact_netloc`
   unconditionally rewrites the user (and password) to `****`. Pipenv's
   variant matches `${\w+}` on both fields and leaves the placeholder
   intact. Pipenv users routinely encode credentials with env-var
   expansion in their Pipfile/lockfile (e.g.
   `https://${PYPI_USER}:${PYPI_PASS}@example.com/simple`); redacting
   those placeholders would lose information the user expects to see
   after a round-trip.
2. **Standard SSH usernames are preserved.** A `STANDARD_SSH_USERNAMES =
   ("git",)` tuple keeps `git@github.com:org/repo.git` readable instead
   of rewriting it to `****@github.com:org/repo.git`. Pip has no
   equivalent.

Both behaviors are user-visible (they appear in CLI output and in the
generated `Pipfile.lock`), so swapping in pip's version would be a
behavior change rather than a refactor. The recommendation is therefore
**vendor** (treat as a project-owned fork) rather than **adopt-by-import**.
A `# Fork of pip._internal.utils.misc.{redact_netloc,redact_auth_from_url}`
docstring note would make the divergence obvious to future readers; that
small comment cleanup belongs to the cleanup pass that actually edits
these functions, not to this triage.

### Summary (requirements.py)

| Recommendation | Count | Symbols |
|---|---|---|
| **adopt** | 6 | `import_requirements`, `add_index_to_pipfile`, `requirement_from_lockfile`, `requirements_from_lockfile`, `requirement_from_pipfile`, `requirements_from_pipfile` |
| **vendor** | 2 | `redact_netloc`, `redact_auth_from_url` (project-owned forks of pip-internal helpers; do not replace with the pip imports) |
| **delete** | 1 | `normalize_name` (overlaps with `pep423_name` in `pipenv/utils/dependencies.py`; merge under Initiative E) |
| **total** | 9 | |

Key findings to carry forward:

- The `normalize_name` ↔ `pep423_name` overlap is the one cross-module
  duplicate in this file. It belongs to Initiative E's
  requirement-model consolidation; flagged here so E can plan the merge.
- The two redact helpers are deliberate forks, not blind copies; the
  cleanup pass should add a one-line provenance comment and leave the
  behavior alone.
- The four pipfile/lockfile bridge functions (`*_from_lockfile`,
  `*_from_pipfile`) are project-owned glue between pip's parser and
  pipenv's lockfile/Pipfile schemas; they have no upstream equivalent
  and should be kept as-is for this initiative.
- `BAD_PACKAGES` is also exported from this module and used by three
  `pipenv/routines/` files; flagging for Initiative E in case the
  constant moves with the helpers.

---

## URL/path helpers in `pipenv/utils/fileutils.py` (T_B.3)

Narrow audit of the three URL/path converters in
`pipenv/utils/fileutils.py`: `is_file_url`, `url_to_path`, `path_to_url`.
`is_valid_url` also lives in this file but is the duplicate flagged in
Initiative A (T_A.2) and is **out of scope** here.

### Domain-boundary rule

Initiative A draws the line as: URL/scheme concerns belong in
`pipenv/utils/internet.py`; filesystem-path concerns belong in
`pipenv/utils/fileutils.py`. The three symbols below all sit on the
boundary because they translate between the two. Under the rule, the
deciding question is "which side is doing the heavy lifting?". For these
three, the answer is the filesystem side — they exist specifically to
move a `Path` across the `file://` boundary, and only the `file:` scheme
is meaningful to them. A generic URL utility that knew nothing about
local paths could not implement them. So they stay in `fileutils.py`.

### Per-symbol recommendation

- **`is_file_url`** — Keep in `fileutils.py`. It is a scheme check, but
  it exists only to gate the `file://`-vs-everything-else branch in
  `open_file`, `url_to_path`, and (in callers) path-vs-URL dispatch.
  No external (non-test) callers in `pipenv/` outside this module today.
- **`url_to_path`** — Keep in `fileutils.py`. Returns a `pathlib.Path`,
  handles UNC netloc reconstruction, and is the inverse of `path_to_url`.
  External callers: `pipenv/utils/requirementslib.py` (2 sites).
- **`path_to_url`** — Keep in `fileutils.py`. Operates on a `Path`, calls
  `normalize_drive` (also in `fileutils.py`), and emits a `file://` URI.
  Only internal caller today is `open_file` in the same module.

### Adjacent finding (not in scope, flagged for later)

`pipenv/utils/shell.py:104` defines a **second** `path_to_url` with a
different implementation (`Path(...).as_uri()` vs. the quoting-aware
version here) and no callers in `pipenv/`. This is a duplicate-name
hazard analogous to the `is_valid_url` case in Initiative A; recommend
folding into Initiative A's URL/scheme consolidation pass rather than
opening a new task here.

---

## `pipenv/utils/markers.py` (T_B.4)

`pipenv/utils/markers.py` is **owned project glue**, not inlined former vendor
code. Its import head (lines 1-14) pulls `parse_marker` from
`pipenv.patched.pip._vendor.distlib.util` and `InvalidMarker`, `Marker`,
`Specifier`, and `SpecifierSet` from `pipenv.patched.pip._vendor.packaging`;
the marker/specifier semantics themselves live in those vendored libraries
and are managed by the vendor tooling, while this module only composes them
into pipenv-specific helpers (cleanup, intersection, lookup tables such as
`MAX_VERSIONS` / `DEPRECATED_VERSIONS`, and the local `RequirementError`).
There is therefore no separate vendor lineage to triage under Initiative B,
and the module can be refactored freely under Initiative E (requirement-model
consolidation) if useful. Recorded here so the "is this vendored?" question
stays closed.

---
