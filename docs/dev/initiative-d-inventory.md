# Initiative D — `Project` god-class inventory

T_D.1 deliverable. Inventory and cluster every public method, property,
and `@cached_property` on `pipenv.project.Project` against the five
proposed collaborators (`Pipfile`, `Lockfile`, `Sources`, `VenvLocator`,
`Settings`) plus a residual `coordinator` group and a `helper` bucket for
utility-shaped methods that probably want to move to `pipenv/utils/`.
This document drives T_D.2 (the first extraction proof-of-concept).

Counts captured on 2026-05-12 against the working branch
`maintenance/code-cleanup-2026-05`.

## 1. Summary

`pipenv/project.py` is **1848 lines**. The `Project` class begins at
line 211 (lines 1–210 are imports, encoder, and the `SourceNotFound`
exception). The class exposes **93 public attributes** when counted as
follows:

- 41 `@property` getters (anchored at the line *after* `@property`,
  so the cluster table key counts properties as `prop`).
- 1 `@cached_property` (`finders`).
- 48 regular methods (`def foo(self, ...)`), excluding leading-
  underscore internals and `__init__`.
- 2 `@classmethod` helpers (`prepend_hash_types`, `populate_source`).
- 1 `@staticmethod` helper (`get_file_hash`).

(Raw `def` lines in the file: 95, which includes `__init__`, the
`_LockFileEncoder` methods, and 9 underscore-prefixed internals listed
separately at the end of §2.)

Cluster distribution across the seven buckets:

| Bucket         | Count | Notes |
|----------------|-------|-------|
| `Pipfile`      | 38    | Parsing, reading, writing, package mutation, casing, hash, name/location, build-system metadata, packages/dev-packages accessors. |
| `Sources`      | 16    | Index list, source lookup, hashes-from-index, src-name, requests-session caching. |
| `VenvLocator`  | 13    | Discovery, location, hashing, scripts/src/download dirs, finders, `which`/`python`. |
| `Lockfile`     | 13    | Reading, writing, locating, hash, meta, pylock variants. |
| `coordinator`  | 7     | Orchestration that crosses boundaries (environment, get-or-create lockfile, create-pipfile bootstrap). |
| `helper`       | 3     | Pure utilities with no `self` coupling — candidates to move to `pipenv/utils/`. |
| `Settings`     | 3     | `[pipenv]` section + `settings`-shaped writes. |
| **Total**      | **93** | |

The numbers above match the row count in §2.

**Recommended first extraction: `Sources`.** Cross-checked against the
PRD's suggestion (§4) and confirmed. Among the *true* collaborator
clusters (excluding `coordinator`/`helper`/`Settings`, which the PRD
treats specially), `Sources` is the smallest at 16 public members and
has the cleanest data boundary
(`pipfile_sources()` plus a list-of-dicts in `self.parsed_pipfile["source"]`
and the cached `self.default_source`), and crucially **only one of its
methods writes back to the Pipfile** (`add_index_to_pipfile`). That one
write site is the only cross-collaborator coupling we need to plumb
through; everything else is read-only against the parsed-pipfile dict.
By contrast `Pipfile`-bucket extraction would have to thread cached
mtime-invalidation through every mutation site, and `VenvLocator` has
deep entanglement with `Settings` (the `PIPENV_VENV_IN_PROJECT` /
`PIPENV_CUSTOM_VENV_NAME` / `PIPENV_PYTHON` env vars are read inline by
its core methods). `Sources` is the right proof-of-concept target.

## 2. Cluster table

Methods are listed in source-file order. The "Line" column points to
the definition site in `pipenv/project.py`. "Kind" is one of `prop`,
`cprop` (cached_property), `clsm` (classmethod), `stcm` (staticmethod),
`meth`.

| Line | Kind  | Name                                | Bucket        | One-line role |
|------|-------|-------------------------------------|---------------|---------------|
| 271  | meth  | `path_to`                           | `helper`      | `(p)` → absolute Path against `_original_dir`. Pure utility, no self-state. |
| 279  | meth  | `get_pipfile_section`               | `Pipfile`     | `parsed_pipfile.get(section, {})`. Trivial accessor. |
| 283  | meth  | `get_package_categories`            | `Pipfile`     | Derives package-section list from `parsed_pipfile.keys()`. |
| 292  | meth  | `get_requests_session_for_source`   | `Sources`     | Caches a `requests.Session` per source; reads `self.s.PIPENV_*` for timeout/retries. |
| 307  | clsm  | `prepend_hash_types`                | `helper`      | Pure string helper. No `self`. Candidate to move to `pipenv/utils/`. |
| 318  | meth  | `get_hash_from_link`                | `Sources`     | Returns hash from a `Link` or via `HashCache`. Conceptually source-indexing. |
| 324  | meth  | `get_hashes_from_pypi`              | `Sources`     | Hits `pypi.org/pypi/{name}/json`. Uses `get_requests_session_for_source`. |
| 349  | meth  | `get_hashes_from_remote_index_urls` | `Sources`     | Scrapes a non-PyPI simple-index HTML page for hashes. |
| 409  | stcm  | `get_file_hash`                     | `helper`      | Pure: hash a file streamed from a `Link`. No `self`. Candidate `pipenv/utils/`. |
| 420  | prop  | `name`                              | `Pipfile`     | Parent-dir name of `pipfile_location`. |
| 426  | prop  | `pipfile_exists`                    | `Pipfile`     | `Path(pipfile_location).is_file()`. |
| 430  | prop  | `required_python_version`           | `Pipfile`     | Reads `[requires]` section. |
| 439  | prop  | `project_directory`                 | `Pipfile`     | Parent of `pipfile_location`. |
| 443  | prop  | `requirements_exists`               | `Pipfile`     | Truthy `requirements_location`. |
| 458  | meth  | `is_venv_in_project`                | `VenvLocator` | Three-way precedence: env var → `[pipenv]` Pipfile → `.venv` autodetect. Touches both `Settings` and `Pipfile`. |
| 471  | prop  | `virtualenv_exists`                 | `VenvLocator` | Checks for the activate script in the resolved venv. |
| 490  | meth  | `get_location_for_virtualenv`       | `VenvLocator` | Core path-resolution: `.venv` vs `WORKON_HOME`. Touches `Settings.PIPENV_VENV_IN_PROJECT` and `_pipfile_venv_in_project`. |
| 528  | prop  | `installed_packages`                | `coordinator` | Delegates to `Environment`. The `Environment` is built from `parsed_pipfile` + `sources` + `virtualenv_location`. Stays on coordinator. |
| 532  | prop  | `installed_package_names`           | `coordinator` | Wraps `installed_packages`. |
| 536  | prop  | `lockfile_package_names`            | `Lockfile`    | Reads `lockfile_content` keyed by category. |
| 547  | prop  | `pipfile_package_names`             | `Pipfile`     | Reads `parsed_pipfile` keyed by category. |
| 559  | meth  | `get_environment`                   | `coordinator` | Builds an `Environment` from sources+pipfile+venv. By definition cross-cutting. |
| 578  | prop  | `environment`                       | `coordinator` | Lazy cached `_environment`. Reads `Settings.PIPENV_USE_SYSTEM`. |
| 585  | meth  | `get_outdated_packages`             | `coordinator` | Delegates to `environment`; *also has a bug* — calls `self.pipfile.get(...)` but `Project` has no `pipfile` attribute (only `parsed_pipfile`); flag this as `TODO(swarm)` separately, not in scope for T_D.1. |
| 641  | prop  | `virtualenv_name`                   | `VenvLocator` | Slug + 8-char hash + optional Python suffix. Reads `Settings.PIPENV_CUSTOM_VENV_NAME` / `PIPENV_PYTHON`. |
| 658  | prop  | `virtualenv_location`               | `VenvLocator` | Resolves and caches `_virtualenv_location`. Reads `Settings.PIPENV_IGNORE_VIRTUALENVS`. |
| 672  | prop  | `virtualenv_src_location`           | `VenvLocator` | `<venv>/src`, created on access. |
| 681  | prop  | `virtualenv_scripts_location`       | `VenvLocator` | `bin`/`Scripts` dir of the resolved venv. |
| 685  | prop  | `download_location`                 | `VenvLocator` | `<venv>/downloads`, created on access. |
| 694  | prop  | `proper_names_db_path`              | `VenvLocator` | `<venv>/pipenv-proper-names.txt`, created on access. |
| 703  | prop  | `proper_names`                      | `Pipfile`     | Reads names DB (file lives under the venv, but the *purpose* is proper-casing package names — Pipfile concern). |
| 708  | meth  | `register_proper_name`              | `Pipfile`     | Appends to the names DB. |
| 713  | prop  | `pipfile_location`                  | `Pipfile`     | Honours `Settings.PIPENV_PIPFILE`, otherwise walks up. |
| 728  | prop  | `requirements_location`             | `Pipfile`     | Mirrors `pipfile_location` for a sibling `requirements.txt`. |
| 738  | prop  | `parsed_pipfile`                    | `Pipfile`     | mtime-invalidated tomlkit cache. **Critical lazy-init**, see §5. |
| 764  | meth  | `read_pipfile`                      | `Pipfile`     | Raw file read; records `_pipfile_newlines`. |
| 796  | prop  | `build_requires`                    | `Pipfile`     | From `_build_system` populated by `_read_pyproject` (called from `__init__`-adjacent paths). |
| 800  | prop  | `build_backend`                     | `Pipfile`     | Same source as above. |
| 804  | prop  | `pipfile_build_requires`            | `Pipfile`     | `parsed_pipfile["build-system"]["requires"]`. |
| 824  | prop  | `settings`                          | `Settings`    | `parsed_pipfile.get("pipenv", {})`. Anchor of the `Settings` bucket. |
| 829  | meth  | `has_script`                        | `Pipfile`     | `name in parsed_pipfile["scripts"]`. |
| 835  | meth  | `build_script`                      | `Pipfile`     | Builds a `Script` from `[scripts]`. |
| 844  | meth  | `update_settings`                   | `Settings`    | Mutates the `[pipenv]` table and writes back. Needs to call `Pipfile.write_toml`. |
| 857  | meth  | `lockfile`                          | `Lockfile`    | Loads `Pipfile.lock` or falls back to `pylock.toml`/derived. |
| 897  | prop  | `pylock_location`                   | `Lockfile`    | `find_pylock_file(project_directory)`. |
| 905  | prop  | `pylock_exists`                     | `Lockfile`    | Truthy `pylock_location`. |
| 910  | prop  | `lockfile_location`                 | `Lockfile`    | `f"{pipfile_location}.lock"`. |
| 914  | prop  | `lockfile_exists`                   | `Lockfile`    | `Path(lockfile_location).is_file()`. |
| 918  | prop  | `any_lockfile_exists`               | `Lockfile`    | Either `Pipfile.lock` or `pylock.toml`. |
| 923  | prop  | `lockfile_content`                  | `Lockfile`    | Prefers pylock → falls back to `load_lockfile()`. Reads `use_pylock` from `Settings`. |
| 936  | meth  | `get_editable_packages`             | `Pipfile`     | Filter parsed_pipfile section by `is_editable`. |
| 947  | prop  | `all_packages`                      | `Pipfile`     | Flattens all package categories from the Pipfile. |
| 955  | prop  | `packages`                          | `Pipfile`     | `get_pipfile_section("packages")`. |
| 960  | prop  | `dev_packages`                      | `Pipfile`     | `get_pipfile_section("dev-packages")`. |
| 965  | prop  | `pipfile_is_empty`                  | `Pipfile`     | Trivial check. |
| 975  | meth  | `create_pipfile`                    | `coordinator` | Bootstraps a new Pipfile. Touches `Sources` (default_source), `VenvLocator` (`virtualenv_exists`, `_which`), `Settings` (`PIPENV_DEFAULT_PYTHON_VERSION`), `Pipfile` (`write_toml`). |
| 1018 | clsm  | `populate_source`                   | `Sources`     | Fills in missing `name`/`verify_ssl` from `url`. Pure-ish (no `self`); could be a Sources staticmethod or a free helper. |
| 1030 | meth  | `get_or_create_lockfile`            | `coordinator` | Coordinates `Lockfile` + `Sources` (via `pipfile_sources` for meta) + `Pipfile`. Stays on coordinator. |
| 1081 | meth  | `get_lockfile_meta`                 | `Lockfile`    | Computes `_meta` block; reads `pipfile_sources()` and `calculate_pipfile_hash()` (cross-collaborator). |
| 1097 | meth  | `write_toml`                        | `Pipfile`     | Writes a TOML structure (defaulting to the Pipfile path) and invalidates the parsed cache. |
| 1127 | prop  | `use_pylock`                        | `Settings`    | `self.settings.get("use_pylock", False)`. |
| 1132 | prop  | `pylock_output_path`                | `Lockfile`    | Default `pylock.toml` path, optionally overridden by `Settings`. |
| 1140 | meth  | `write_lockfile`                    | `Lockfile`    | Atomic-write `Pipfile.lock`; optionally also writes pylock. |
| 1166 | meth  | `pipfile_sources`                   | `Sources`     | Reads `parsed_pipfile["source"]`; expands env vars; honours `PIPENV_PYPI_MIRROR`. |
| 1185 | meth  | `get_default_index`                 | `Sources`     | First of `pipfile_sources()`. |
| 1188 | meth  | `get_index_by_name`                 | `Sources`     | Linear scan by `name`. |
| 1193 | meth  | `get_index_by_url`                  | `Sources`     | Linear scan by `url`. |
| 1198 | prop  | `sources`                           | `Sources`     | Prefers lockfile `_meta.sources`, otherwise `pipfile_sources()`. Reads from `Lockfile.lockfile_content` (boundary crossing!). |
| 1209 | prop  | `sources_default`                   | `Sources`     | `self.sources[0]`. |
| 1213 | prop  | `index_urls`                        | `Sources`     | `[s["url"] for s in self.sources]`. |
| 1217 | meth  | `find_source`                       | `Sources`     | URL-or-name dispatcher around `get_source`. |
| 1232 | meth  | `get_source`                        | `Sources`     | Search `self.sources` then `pipfile_sources()`, raise `SourceNotFound`. |
| 1264 | meth  | `get_package_name_in_pipfile`       | `Pipfile`     | Case-normalised key lookup. |
| 1272 | meth  | `get_pipfile_entry`                 | `Pipfile`     | Wraps the above with `.get`. |
| 1296 | meth  | `remove_package_from_pipfile`       | `Pipfile`     | Mutate + write_toml. Reads `Settings.sort_pipfile`. |
| 1315 | meth  | `reset_category_in_pipfile`         | `Pipfile`     | Mutate + write_toml. |
| 1325 | meth  | `remove_packages_from_pipfile`      | `Pipfile`     | Bulk version of above. |
| 1338 | meth  | `generate_package_pipfile_entry`    | `Pipfile`     | Builds an entry dict from an `InstallRequirement` + raw pip-line. Largest method; pure-ish (no I/O), but conceptually Pipfile-shape. |
| 1426 | meth  | `add_package_to_pipfile`            | `Pipfile`     | `generate_…` + `add_pipfile_entry_to_pipfile`. |
| 1433 | meth  | `add_pipfile_entry_to_pipfile`      | `Pipfile`     | Mutate + write_toml. Reads `Settings.sort_pipfile`. |
| 1461 | meth  | `add_packages_to_pipfile_batch`     | `Pipfile`     | Batched form of the above; single write at end. Reads `Settings.sort_pipfile`. |
| 1551 | meth  | `src_name_from_url`                 | `Sources`     | Synthesises a unique name for a new source; uses `get_source` for uniqueness check. |
| 1568 | meth  | `add_index_to_pipfile`              | `Sources`     | **Boundary crosser** — mutates `parsed_pipfile["source"]` and writes back via `write_toml`. The one and only `Sources → Pipfile` write coupling. |
| 1625 | meth  | `recase_pipfile`                    | `Pipfile`     | `ensure_proper_casing()` + write. |
| 1629 | meth  | `load_lockfile`                     | `Lockfile`    | JSON-load `Pipfile.lock`, repair `_meta` from Pipfile if missing. Cross-collaborator (Pipfile) on missing-meta repair. |
| 1681 | meth  | `get_lockfile_hash`                 | `Lockfile`    | Reads cached hash from `_meta`. |
| 1696 | meth  | `calculate_pipfile_hash`            | `Pipfile`     | PEP 503 canonical hash of the Pipfile. |
| 1756 | meth  | `ensure_proper_casing`              | `Pipfile`     | Walk `packages` + `dev-packages` to fix casing. |
| 1763 | meth  | `proper_case_section`               | `Pipfile`     | Used by the above; consults `proper_names`. |
| 1789 | cprop | `finders`                           | `VenvLocator` | `cached_property` — list of `Finder` instances rooted at the venv scripts dir. **§5 lazy-init concern.** |
| 1796 | prop  | `finder`                            | `VenvLocator` | First of `finders`. |
| 1800 | meth  | `which`                             | `VenvLocator` | Uses `finders`, falls back to `_which`. |
| 1807 | meth  | `python`                            | `VenvLocator` | Wraps `project_python(self, system=...)`. |

### Underscore-prefixed items (treated as internal; listed for completeness)

These are not in the row count but matter for the extraction.

| Line | Name                       | Status | Notes |
|------|----------------------------|--------|-------|
| 447  | `_pipfile_venv_in_project` | internal | `VenvLocator` helper; reads `[pipenv]` section. Crosses Pipfile/Settings. |
| 588  | `_sanitize`                | internal | classmethod helper for `_get_virtualenv_hash`. Pure. |
| 604  | `_get_virtualenv_hash`     | internal | `VenvLocator` core hashing routine. |
| 774  | `_parse_pipfile`           | internal | tomlkit-or-toml fallback parser. `Pipfile` private. |
| 782  | `_read_pyproject`          | internal | Populates `_build_system`. `Pipfile` adjacent. Only call site is unclear — see footnote. |
| 890  | `_pipfile`                 | internal | Returns a `ReqLibPipfile` instance from `pipenv.utils.pipfile`. Distinct from `parsed_pipfile`. |
| 940  | `_get_vcs_packages`        | internal | `Pipfile` private. |
| 1276 | `_sort_category`           | internal | `Pipfile` private. |
| 1813 | `_which`                   | internal | `VenvLocator` private. |

Footnote on `_read_pyproject`: defined but I see no in-file caller; the
`_build_system` attribute is set in `__init__` to a default dict.
External callers presumably invoke it — leave a `TODO(swarm)` to verify
in T_D.2 whether the read path is dead code or driven from outside.

## 3. Cross-collaborator references

For each collaborator, the other collaborators its methods must reach.
These are the boundaries the extraction will have to make explicit via
constructor injection or a back-reference to the `Project` coordinator.

### `Pipfile` reaches into:

- `Settings`: `remove_package_from_pipfile`,
  `add_pipfile_entry_to_pipfile`, `add_packages_to_pipfile_batch` all
  consult `self.settings.get("sort_pipfile")`. Frequent and read-only —
  easy to plumb as a getter on the `Pipfile` collaborator that closes
  over the `Settings` instance.
- `VenvLocator`: `proper_names_db_path` is *defined* under VenvLocator
  in this inventory (it physically lives under the venv) but is *used*
  by `Pipfile.proper_case_section`. Two-way coupling. Easiest fix:
  redefine `proper_names_db_path` as a venv-located *file path* under
  `VenvLocator` and a *proper-names list* under `Pipfile` that takes the
  path as a constructor arg.

### `Lockfile` reaches into:

- `Pipfile`: `lockfile()`, `load_lockfile()`, `get_lockfile_meta()` all
  re-open `pipfile_location` or call `calculate_pipfile_hash()`. The
  Lockfile collaborator needs a `Pipfile` reference.
- `Sources`: `get_lockfile_meta()` calls `pipfile_sources()` and
  `populate_source()`. Lockfile needs a `Sources` reference (or
  Lockfile-meta construction stays on the coordinator).
- `Settings`: `lockfile_content` reads `self.use_pylock`. Minor.
- `Sources` reaches back into `Lockfile`: `Project.sources` (the
  *property*) reads `lockfile_content._meta.sources` when a lockfile
  exists. This is the most subtle coupling — it means `Sources` is not
  read-only against the lockfile, it has a *read* dependency on it. See
  §4 for how this affects extraction order.

### `Sources` reaches into:

- `Pipfile`: `pipfile_sources()` reads `parsed_pipfile`;
  `add_index_to_pipfile` mutates `parsed_pipfile["source"]` and calls
  `write_toml`. This is the single boundary-crossing write.
- `Lockfile`: `sources` property reads `lockfile_content._meta.sources`
  if a lockfile exists.
- `Settings`: `get_requests_session_for_source` reads
  `PIPENV_MAX_RETRIES`, `PIPENV_CACHE_DIR`, `PIPENV_REQUESTS_TIMEOUT`;
  `pipfile_sources` consults `os.environ["PIPENV_PYPI_MIRROR"]`.

### `VenvLocator` reaches into:

- `Settings`: deeply. `PIPENV_VENV_IN_PROJECT`, `PIPENV_CUSTOM_VENV_NAME`,
  `PIPENV_PYTHON`, `PIPENV_IGNORE_VIRTUALENVS`, `VIRTUAL_ENV` env var.
- `Pipfile`: `is_venv_in_project` reads `[pipenv]` from the Pipfile;
  `_get_virtualenv_hash` uses `pipfile_location` as the hash seed.
- `Settings` reaches back into `VenvLocator`: `Settings.update_settings`
  is implemented in terms of `Pipfile.write_toml`, but `Pipfile.write_toml`
  writes to a path determined by `Pipfile.pipfile_location`, which is
  *not* a venv concern — no actual cycle here. Listed for completeness.

### `Settings` reaches into:

- `Pipfile`: `settings` is a *view* into `parsed_pipfile["pipenv"]`;
  `update_settings` mutates that view and calls `write_toml`. `Settings`
  cannot exist without a `Pipfile` reference (or without owning the
  pipenv-section view inside `Pipfile`).

### Summary of boundary writes (the painful set)

There are exactly three places where a non-Pipfile collaborator writes
the Pipfile:

1. `Sources.add_index_to_pipfile` → writes new source.
2. `Settings.update_settings` → writes the `[pipenv]` table.
3. `coordinator.create_pipfile` → bootstraps the file. (Stays on
   coordinator.)

Reads of the Pipfile from non-Pipfile collaborators are pervasive but
read-only and can be served by passing a `Pipfile` reference at
construction time.

## 4. First-extraction recommendation

Per-collaborator public surface and boundary count:

| Collaborator   | Public methods/props | Other collaborators read | Other collaborators written |
|----------------|----------------------|--------------------------|------------------------------|
| `Settings`     | 3                    | `Pipfile`                | `Pipfile`                    |
| `Sources`      | 16                   | `Pipfile`, `Lockfile`, `Settings` | `Pipfile` (1 method)         |
| `Lockfile`     | 13                   | `Pipfile`, `Sources`, `Settings`  | `Pipfile` (none — writes lockfile only) |
| `VenvLocator`  | 13                   | `Pipfile`, `Settings`    | none                          |
| `Pipfile`      | 38                   | `Settings`, `VenvLocator`| `Settings` (none — it owns the section) |

`Settings` has the smallest surface, but extracting it first is *worse*
than `Sources` because:

- `settings` is a tomlkit-section view (a *live* reference into
  `parsed_pipfile["pipenv"]`), not a copy. The lazy-init / cache
  semantics of `parsed_pipfile` (§5) leak into `Settings` and have to be
  re-thought as part of any extraction.
- `Settings` is the most diffuse caller-facing API: nearly every
  collaborator reads it. Extracting it before the others stabilises
  means we'd be re-touching the new `Settings` constructor signature on
  every subsequent extraction.

`Sources` wins because:

- 16 public methods/properties (manageable in a single PR — and three
  of those, `get_hash_from_link` / `get_hashes_from_pypi` /
  `get_hashes_from_remote_index_urls`, are leaf calls into the requests
  layer that move *en bloc*).
- Only one outbound write (`add_index_to_pipfile`), and that write site
  is naturally expressed as "ask the Pipfile to append a source and
  rewrite". Easy to model as constructor-injected `Pipfile` callback.
- The read of `lockfile_content._meta.sources` in the `sources` property
  is the only `Sources ← Lockfile` coupling. We can either:
  (a) accept the coupling and pass a `Lockfile` reference to `Sources`,
  or (b) keep `Project.sources` (the property) on the coordinator and
  move only `pipfile_sources`-shaped methods into the new module.
  Option (b) is the conservative call for the proof-of-concept and
  keeps the new module purely Pipfile-facing.
- The Pipfile-write coupling needs an explicit pattern (callback vs.
  back-reference vs. injected `Pipfile`); landing it for `Sources` first
  establishes the pattern for the other four extractions.

The PRD's choice of `Sources` as the proof-of-concept is **confirmed**.

## 5. Lazy-init / cached-property considerations

The post-extraction shape per the PRD is `Project` holding each
collaborator via `@cached_property`. The current `Project` has the
following lazy / cached state that the extraction needs to handle:

- **`parsed_pipfile` (property + mtime cache).** Backed by
  `_parsed_pipfile_cache` and `_parsed_pipfile_mtime_ns`. **Invalidated
  manually** in `write_toml` (lines 1123–1125: `self._parsed_pipfile_cache
  = None; self._parsed_pipfile_mtime_ns = None`). When `Pipfile` becomes
  a collaborator, this cache lives on `Pipfile`, and *every* writer
  (including the cross-collaborator writers in §3, e.g. `Sources.add_index_to_pipfile`)
  must invalidate through the `Pipfile.write_toml` API rather than
  poking at private state. This is fine as long as no caller uses
  `parsed_pipfile` directly to mutate and then re-write — a fast grep
  during T_D.2 should confirm.
- **`finders` (`@cached_property`).** A list of pythonfinder `Finder`
  objects rooted at `virtualenv_scripts_location`. If `virtualenv_location`
  changes after the property is first read (it shouldn't, but
  `_virtualenv_location` is in principle writeable), the cache is stale.
  Move with `VenvLocator` and audit the (currently zero?) invalidation
  paths.
- **`_environment` (manually cached in `environment` property).** Built
  once from sources+pipfile+venv. Stays on `coordinator` — it inherently
  spans collaborators.
- **`_virtualenv_location`, `_download_location`, `_proper_names_db_path`,
  `_pipfile_location`, `_requirements_location`.** All `__init__`-set
  to `None` and lazily computed. None of them invalidate. Move with
  their owning collaborator. Note `_pipfile_location` is set from
  `PIPENV_PIPFILE` env var *or* a directory walk; once captured it never
  changes within a process lifetime.
- **`sessions` dict (rebuilt on demand by source name).** Lives on
  `Sources` post-extraction; one entry per source. Already lazy.

### Implication for `@cached_property`-of-collaborator pattern

If `Project.sources` becomes `@cached_property Project.sources()`
returning a `Sources(...)` instance, the instance lives for the
lifetime of the `Project`. Since `Sources` doesn't carry mutable state
beyond `sessions`, this is fine. The same is **not** true of
`Project.pipfile` (the future `Pipfile` collaborator) — that one
carries the mtime cache, and it must be the *only* `Pipfile`-collaborator
instance reachable from any sub-collaborator. The extraction's
constructor wiring needs to pass the *Project's* `Pipfile` to the other
collaborators, not let each one make its own.

Concretely: this means the post-extraction `Project.sources` should be
constructed as `Sources(pipfile=self.pipfile, settings=self.s)` rather
than `Sources(pipfile_location=...)`, and the `@cached_property` on
`Project` is fine.

## 6. Decisions needed (sign-off list)

Maintainer questions, ordered from most consequential to least:

1. **Five-collaborator split correctness.** Is `Pipfile`, `Lockfile`,
   `Sources`, `VenvLocator`, `Settings` the right cut, or should:
   - `Pipfile` + `Lockfile` collapse into one `PipfileBundle` (they
     share the on-disk-Pipfile root and the canonical hash function)?
     The hash function `calculate_pipfile_hash` lives naturally on
     `Pipfile` but is consumed only by `Lockfile.get_lockfile_meta`.
   - `VenvLocator` split into `VenvLocator` (resolution-only,
     read-only) + `VenvBootstrap` (write / install)?  In this inventory
     `VenvLocator` has no writers (creation happens in `routines/`),
     so a split is probably unnecessary, but flag it.
   - `Settings` collapse into `Pipfile` (since `[pipenv]` is just one
     section of the Pipfile, like `[packages]`)?  This inventory keeps
     them separate because the `env-var precedence over Pipfile`
     pattern is a `Settings` concern, not a Pipfile concern.

2. **Where do new collaborators live?** Three plausible homes:
   - `pipenv/utils/sources.py`, `pipenv/utils/lockfile.py`, etc. — matches
     the existing `pipenv/utils/pipfile.py` precedent and is the lowest-
     friction option.
   - A new `pipenv/project_collaborators/` package — visually emphasises
     that these are not free-standing utilities but `Project`'s direct
     collaborators. Costs an import-path migration for `pipenv/utils/pipfile.py`
     too, if we want to be consistent.
   - Absorbed into existing modules — e.g. `Sources` into
     `pipenv/utils/indexes.py` (which already exists). Cheapest for
     `Sources`, hardest for the others. Recommend against unless we're
     willing to do it case-by-case.

3. **First-extraction target.** Confirm `Sources` per §4 recommendation.
   The PRD already nominates it; this inventory verifies the choice.

4. **Backward-compatibility window.** The PRD says `Project.foo()` stays
   as a thin delegating wrapper for at least one release after extraction.
   Confirm or push back. Two sub-questions:
   - Do we want `DeprecationWarning` on the wrappers right away, or
     silent-delegate first and emit warnings in a follow-up?
   - Do we want the wrappers to land in `news/` as `behavior` fragments
     (yes if we emit deprecation warnings; no if we silent-delegate)?

5. **Treatment of helper-bucket methods (`path_to`, `prepend_hash_types`,
   `get_file_hash`).** Move to `pipenv/utils/`, or leave on `Project`?
   These are 3–4 small methods, not load-bearing for the decomposition.
   Recommendation: leave them on `Project` for T_D.2 and revisit during
   the per-collaborator extractions. (No need to block T_D.1 on this.)

6. **The `_pipfile` property (line 890) vs the bug at line 586.** The
   `Project` class has a private `_pipfile` property that returns a
   `pipenv.utils.pipfile.Pipfile` instance, and `get_outdated_packages`
   uses `self.pipfile.get(...)` (no underscore) which appears to be a
   bug — there is no public `pipfile` attribute. Confirm whether this
   was meant to be `self.parsed_pipfile` or `self._pipfile`; the
   extraction will need to rename the new `Pipfile` collaborator
   carefully to avoid clashing with either name. Filed as a `TODO(swarm)`
   for the T_D.2 PR to address inline.

## 7. Out of scope for T_D.1

- The actual `Sources` extraction is **T_D.2**. This document only
  identifies the target.
- The four other extractions (`Pipfile`, `Lockfile`, `VenvLocator`,
  `Settings`) and their caller-migrations get regenerated as new tasks
  once T_D.2 lands and the extraction *pattern* (collaborator
  construction, delegating wrappers, caller migration) is proven.
- Internal-caller migration (e.g. `project.add_index_to_pipfile` →
  `project.sources.add_index_to_pipfile`) is explicitly out of T_D.2
  per the plan; it gets its own follow-up task per extracted
  collaborator.
- Type annotations on the extracted collaborators are a PRD-flagged
  open question (Initiative D §365 in the PRD) — defer to the maintainer.

## 8. Maintainer sign-off (2026-05-12)

Recorded answers for each of the six §6 decision questions:

1. **Five-way split — APPROVED with a forward-looking caveat.** Keep
   `Pipfile` and `Lockfile` separate (do not collapse into
   `PipfileBundle`). The maintainer flagged that pipenv also supports
   `pylock.toml` (PEP 751) and may promote it to first-class in 2027,
   deprecating the legacy `Pipfile.lock` over time. The `Lockfile`
   subsystem's extracted shape must therefore be **format-aware**, not
   `Pipfile.lock`-locked. Options to consider when `Lockfile` actually
   gets extracted (after T_D.2 proves the pattern with `Sources`):
   - One `Lockfile` subsystem that internally detects and dispatches
     to per-format handlers (Pipfile.lock today, pylock.toml in
     parallel or as the 2027 successor).
   - Two siblings (`PipfileLock`, `PylockLock`) behind a small format-
     detection layer.
   The decision is deferred to that point, but the boundary recorded
   here should not preclude either option. Add a `TODO(pylock)` tag
   anywhere the extraction pattern touches lockfile state so we can
   re-find it in 2027.

2. **Where new subsystem modules live — APPROVED as the existing
   pattern (`pipenv/utils/sources.py`, etc.).** Also: the maintainer
   pushed back on the "collaborator" term ("those are people who open
   PRs"). Future docs in Initiative D should use **"subsystem"**,
   **"component"**, or just **"class"** instead of "collaborator". This
   is a terminology fix, not an architecture change. I'll update the
   PRD and the plan in a follow-up commit; no action required from
   the executing agent in T_D.2 beyond not echoing "collaborator" in
   new prose.

3. **First-extraction target — APPROVED as proposed: `Sources`.**

4. **No backwards-compatibility window required.** Consistent with the
   T_C.3 sign-off ("we only maintain the CLI APIs"). T_D.2 does NOT
   need to land thin delegating wrappers as a holding pattern: extract
   `Sources` AND migrate every internal `project.X()` caller to
   `project.sources.X()` in the same task, single PR. No
   `DeprecationWarning` on a wrapper, no shipped wrapper.

   **This materially changes T_D.2's scope.** The plan currently
   describes T_D.2 as "instantiate the new class and delegate via
   thin wrappers that preserve current call sites without change. No
   internal caller migrated in this task." That description is
   superseded by this sign-off. The plan-bookkeeping commit for T_D.1
   should also amend T_D.2's description.

5. **Helper-bucket methods (`path_to`, `prepend_hash_types`,
   `get_file_hash`) — executing agent's discretion.** Recommendation
   from §6.5 stands: leave on `Project` for T_D.2 and revisit during
   the per-subsystem extractions. Not a blocker for T_D.2.

6. **Bug at `project.py:586` — ALREADY FIXED** in commit `c794cf3c`
   ("refactor(project): remove dead get_outdated_packages wrapper").
   The buggy `self.pipfile.get(...)` lived inside a dead wrapper
   method; removing the wrapper took the bug with it. The orphan
   `_read_pyproject` flagged alongside was also resolved (commit
   `fe38d27c` removed the whole dead pyproject.toml subsystem).

### Ramifications of decisions 1 and 4

- **T_D.2 is now a single-PR direct extraction + caller migration.**
  Net effect on scope: roughly halves the number of follow-up tasks
  per extracted subsystem. The plan-bookkeeping commit should update
  T_D.2's description and downstream task descriptions accordingly.
- **`Lockfile`'s eventual extraction inherits the pylock support
  question.** Don't extract `Lockfile` without revisiting that
  decision first. The current plan defers all four non-Sources
  extractions to "regenerated tasks" anyway, so this is naturally
  honored, but worth flagging.

T_D.2 may now proceed: extract `Sources` to `pipenv/utils/sources.py`,
migrate every internal `project.<sources-method>` caller in the same
PR, no wrappers retained.
