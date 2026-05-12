# Initiative C — Routine Parameter Inventory

This document is a temporary working artefact for Initiative C of the
2026-05 modernization plan (see `docs/dev/modernization-plan.md`, task
`T_C.2`). It inventories the function signatures of pipenv's routine
entry points and their internal helpers, buckets each parameter into a
semantic group, and surfaces patterns that motivate the proposed
`RoutineContext` dataclass in task `T_C.3`.

The threshold for inclusion in the main table is **more than 3
parameters besides `project`**. Trivial-arity helpers and routines that
are essentially `(project)` plus 1-2 simple flags are noted in an
appendix.

This file will be deleted once `T_C.3` absorbs its content into the
`RoutineContext` design proposal.

`pipenv/core.py` does not exist in the current tree (the historical
`core.py` was decomposed into `pipenv/routines/*.py` and
`pipenv/utils/*` by earlier modernization work), so this inventory is
sourced entirely from `pipenv/routines/`.

## Semantic groups

Parameters are bucketed into one of six groups:

- `install_policy` — flags governing install behaviour: `pre`, `deploy`,
  `skip_lock`, `ignore_pipfile`, `lockfile_only`, `clear`, `lock`,
  `lock_only`, `dry_run`.
- `target_env` — what Python / where to install: `system`,
  `allow_global`, `python`, `pypi_mirror`, `site_packages`.
- `package_selection` — which packages: `packages`, `editable_packages`,
  `pipfile_categories`, `categories`, `dev`, `index`, `index_url`,
  `index_name`, `package_args`, `package_name`, `dev_only`, `all`,
  `all_dev`.
- `execution_options` — how to run: `extra_pip_args`, `requirementstxt`,
  `requirements_directory`, `requirements_dir`, `requirements_file`,
  `no_deps`, `ignore_hashes`, `use_pep517`, `from_pipfile`, `no_lock`,
  `include_hashes`, `include_markers`, `include_index`, `write`,
  `quiet`, `bare`, `verbose`, `outdated`, `auto_install`.
- `state_flags` — flags that describe a sub-routine's intent:
  `perform_upgrades`, `warn`, `has_package_args`, `explicitly_requested`,
  `lock_only` (in helper context), `scan` (in `do_check`), `legacy_mode`,
  `use_installed`, `use_lockfile`.
- `other` — doesn't fit; explained in notes. Includes data-flow params
  passed between helpers (e.g. `reverse_deps`, `lockfile`,
  `original_lockfile`, `procs`, `sources`, `ctx`, `old_hash`, `new_hash`,
  `new_version`, `resolved_default_deps`, `requested_packages`).

Where a parameter could plausibly belong to two groups, it is
classified by the role it plays in the routine's intent rather than its
type. `package_args` is always `package_selection` even though it is
sometimes paired with state flags. Output-formatting toggles
(`bare`, `quiet`, `verbose`) go in `execution_options` because they
describe *how* to run, not *what* to install.

## Summary by semantic group

Distinct-parameter-name counts across all in-scope functions (a
parameter name is counted once per appearance row in the per-routine
table):

| Group              | Row count |
|--------------------|-----------|
| install_policy     | 36        |
| target_env         | 50        |
| package_selection  | 54        |
| execution_options  | 57        |
| state_flags        | 9         |
| other              | 34        |
| **Total**          | **240**   |

Per-routine row counts:

| Routine                          | Rows |
|----------------------------------|------|
| install.do_install               | 15   |
| install.handle_new_packages      | 10   |
| install.handle_lockfile          | 9    |
| install.handle_outdated_lockfile | 9    |
| install.handle_missing_lockfile  | 4    |
| install.do_install_validations   | 10   |
| install.do_install_dependencies  | 9    |
| install.batch_install_iteration  | 8    |
| install.batch_install            | 10   |
| install.do_init                  | 9    |
| update.do_update                 | 17   |
| update.check_version_conflicts   | 4    |
| update._process_package_args     | 9    |
| update._resolve_and_update_lockfile | 9 |
| update._clean_unused_dependencies | 5   |
| update.upgrade                   | 10   |
| uninstall.do_uninstall           | 11   |
| lock.do_lock                     | 8    |
| sync.do_sync                     | 10   |
| requirements.generate_requirements | 8  |
| check.do_check                   | 18   |
| audit.do_audit                   | 20   |
| scan.do_scan                     | 18   |
| **Total**                        | **240** |

## Per-routine parameter table

### install.do_install (`pipenv/routines/install.py`)

| Parameter            | Type              | Default | Semantic group     | Notes                                                                 |
|----------------------|-------------------|---------|--------------------|-----------------------------------------------------------------------|
| packages             | list[str] / False | False   | package_selection  | CLI positional; falsy default sentinel.                               |
| editable_packages    | list[str] / False | False   | package_selection  | `-e` packages.                                                        |
| index                | str / False       | False   | package_selection  | `--index` URL or named source.                                        |
| dev                  | bool              | False   | package_selection  | Routes to `[dev-packages]`.                                           |
| python               | str / False       | False   | target_env         | `--python` interpreter selector.                                      |
| pypi_mirror          | str \| None       | None    | target_env         | Mirror URL; duplicated across nearly every routine.                   |
| system               | bool              | False   | target_env         | `--system` install target.                                            |
| ignore_pipfile       | bool              | False   | install_policy     | Use lockfile only.                                                    |
| requirementstxt      | str / False       | False   | execution_options  | Path or URL to a requirements file.                                   |
| pre                  | bool              | False   | install_policy     | Allow pre-releases.                                                   |
| deploy               | bool              | False   | install_policy     | `--deploy`: fail on hash mismatch.                                    |
| site_packages        | bool \| None      | None    | target_env         | Enable venv site-packages.                                            |
| extra_pip_args       | list[str] \| None | None    | execution_options  | Passthrough to pip.                                                   |
| pipfile_categories   | list[str] \| None | None    | package_selection  | Categories to target.                                                 |
| skip_lock            | bool              | False   | install_policy     | Skip `do_lock` step.                                                  |

### install.handle_new_packages

| Parameter          | Type              | Default | Semantic group    | Notes                                       |
|--------------------|-------------------|---------|-------------------|---------------------------------------------|
| packages           | list[str]         | —       | package_selection | Required positional.                        |
| editable_packages  | list[str]         | —       | package_selection | Required positional.                        |
| dev                | bool              | —       | package_selection | Required positional.                        |
| pre                | bool              | —       | install_policy    |                                             |
| system             | bool              | —       | target_env        |                                             |
| pypi_mirror        | str \| None       | —       | target_env        |                                             |
| extra_pip_args     | list[str] \| None | —       | execution_options |                                             |
| pipfile_categories | list[str] \| None | —       | package_selection |                                             |
| perform_upgrades   | bool              | True    | state_flags       | Sub-routine intent: also call `do_update`.  |
| index              | str \| None       | None    | package_selection |                                             |

### install.handle_lockfile

| Parameter      | Type              | Default | Semantic group    | Notes                                       |
|----------------|-------------------|---------|-------------------|---------------------------------------------|
| packages       | list[str]         | —       | package_selection | Used to decide whether to early-return.     |
| ignore_pipfile | bool              | —       | install_policy    |                                             |
| skip_lock      | bool              | —       | install_policy    |                                             |
| system         | bool              | —       | target_env        |                                             |
| allow_global   | bool              | —       | target_env        | Mirrors `system` in calling context.        |
| deploy         | bool              | —       | install_policy    |                                             |
| pre            | bool              | —       | install_policy    |                                             |
| pypi_mirror    | str \| None       | —       | target_env        |                                             |
| categories     | list[str] \| None | —       | package_selection |                                             |

### install.handle_outdated_lockfile

| Parameter    | Type              | Default | Semantic group    | Notes                                          |
|--------------|-------------------|---------|-------------------|------------------------------------------------|
| packages     | list[str]         | —       | package_selection |                                                |
| old_hash     | str               | —       | other             | Lockfile-hash data-flow value.                 |
| new_hash     | str               | —       | other             | Lockfile-hash data-flow value.                 |
| system       | bool              | —       | target_env        |                                                |
| allow_global | bool              | —       | target_env        |                                                |
| skip_lock    | bool              | —       | install_policy    |                                                |
| pre          | bool              | —       | install_policy    |                                                |
| pypi_mirror  | str \| None       | —       | target_env        |                                                |
| categories   | list[str] \| None | —       | package_selection |                                                |

### install.handle_missing_lockfile

| Parameter    | Type        | Default | Semantic group | Notes |
|--------------|-------------|---------|----------------|-------|
| system       | bool        | —       | target_env     |       |
| allow_global | bool        | —       | target_env     |       |
| pre          | bool        | —       | install_policy |       |
| pypi_mirror  | str \| None | —       | target_env     |       |

### install.do_install_validations

| Parameter             | Type              | Default | Semantic group    | Notes                                              |
|-----------------------|-------------------|---------|-------------------|----------------------------------------------------|
| package_args          | list[str]         | —       | package_selection | Combined positional + editable list.               |
| requirements_directory | str              | —       | execution_options | Temp dir path.                                     |
| dev                   | bool              | False   | package_selection |                                                    |
| system                | bool              | False   | target_env        |                                                    |
| ignore_pipfile        | bool              | False   | install_policy    |                                                    |
| requirementstxt       | str \| bool       | False   | execution_options |                                                    |
| pre                   | bool              | False   | install_policy    |                                                    |
| deploy                | bool              | False   | install_policy    |                                                    |
| categories            | list[str] \| None | None    | package_selection | Receives `pipfile_categories` from `do_install`.   |
| skip_lock             | bool              | False   | install_policy    |                                                    |

### install.do_install_dependencies

| Parameter        | Type              | Default | Semantic group    | Notes                                       |
|------------------|-------------------|---------|-------------------|---------------------------------------------|
| dev              | bool              | False   | package_selection |                                             |
| bare             | bool              | False   | execution_options | Output verbosity toggle.                    |
| allow_global     | bool              | False   | target_env        |                                             |
| ignore_hashes    | bool              | False   | execution_options | pip flag passthrough.                       |
| requirements_dir | str \| None       | None    | execution_options |                                             |
| pypi_mirror      | str \| None       | None    | target_env        |                                             |
| extra_pip_args   | list[str] \| None | None    | execution_options |                                             |
| categories       | list[str] \| None | None    | package_selection |                                             |
| skip_lock        | bool              | False   | install_policy    |                                             |

### install.batch_install_iteration

| Parameter        | Type              | Default | Semantic group    | Notes                                |
|------------------|-------------------|---------|-------------------|--------------------------------------|
| deps_to_install  | list[tuple]       | —       | other             | Per-call data-flow payload.          |
| sources          | list[dict]        | —       | other             | Index source list.                   |
| procs            | queue.Queue       | —       | other             | Shared subprocess queue.             |
| requirements_dir | str               | —       | execution_options |                                      |
| no_deps          | bool              | True    | execution_options |                                      |
| ignore_hashes    | bool              | False   | execution_options |                                      |
| allow_global     | bool              | False   | target_env        |                                      |
| extra_pip_args   | list[str] \| None | None    | execution_options |                                      |

### install.batch_install

| Parameter        | Type              | Default | Semantic group    | Notes                                  |
|------------------|-------------------|---------|-------------------|----------------------------------------|
| deps_list        | list[tuple]       | —       | other             | Resolved dependency list.              |
| lockfile_section | dict              | —       | other             | Section of lockfile (default/develop). |
| procs            | queue.Queue       | —       | other             |                                        |
| requirements_dir | str               | —       | execution_options |                                        |
| no_deps          | bool              | True    | execution_options |                                        |
| ignore_hashes    | bool              | False   | execution_options |                                        |
| allow_global     | bool              | False   | target_env        |                                        |
| pypi_mirror      | str \| None       | None    | target_env        |                                        |
| sequential_deps  | list[tuple] \| None | None  | other             | Editable/VCS subset.                   |
| extra_pip_args   | list[str] \| None | None    | execution_options |                                        |

### install.do_init

| Parameter      | Type              | Default | Semantic group    | Notes                                  |
|----------------|-------------------|---------|-------------------|----------------------------------------|
| packages       | list[str] \| None | None    | package_selection |                                        |
| allow_global   | bool              | False   | target_env        |                                        |
| ignore_pipfile | bool              | False   | install_policy    |                                        |
| system         | bool              | False   | target_env        |                                        |
| deploy         | bool              | False   | install_policy    |                                        |
| pre            | bool              | False   | install_policy    |                                        |
| pypi_mirror    | str \| None       | None    | target_env        |                                        |
| skip_lock      | bool              | False   | install_policy    |                                        |
| categories     | list[str] \| None | None    | package_selection |                                        |

### update.do_update

| Parameter         | Type              | Default | Semantic group    | Notes                                       |
|-------------------|-------------------|---------|-------------------|---------------------------------------------|
| python            | str \| None       | None    | target_env        |                                             |
| pre               | bool              | False   | install_policy    |                                             |
| system            | bool              | False   | target_env        |                                             |
| packages          | list[str] \| None | None    | package_selection |                                             |
| editable_packages | list[str] \| None | None    | package_selection |                                             |
| site_packages     | bool              | False   | target_env        |                                             |
| pypi_mirror       | str \| None       | None    | target_env        |                                             |
| dev               | bool              | False   | package_selection |                                             |
| categories        | list[str] \| None | None    | package_selection |                                             |
| index_url         | str \| None       | None    | package_selection |                                             |
| extra_pip_args    | list[str] \| None | None    | execution_options |                                             |
| quiet             | bool              | False   | execution_options |                                             |
| bare              | bool              | False   | execution_options |                                             |
| dry_run           | bool \| None      | None    | install_policy    | Triggers `outdated` mode when truthy.       |
| outdated          | bool              | False   | execution_options | Switches routine to `do_outdated` path.     |
| clear             | bool              | False   | install_policy    | Clear resolver cache.                       |
| lock_only         | bool              | False   | install_policy    | Update lockfile without installing.         |

### update.check_version_conflicts

| Parameter    | Type                                     | Default | Semantic group    | Notes                                       |
|--------------|------------------------------------------|---------|-------------------|---------------------------------------------|
| package_name | str                                      | —       | package_selection | Single-package context; no `project`.       |
| new_version  | str                                      | —       | other             | Version-string payload.                     |
| reverse_deps | dict[str, set[tuple[str, str]]]          | —       | other             | Reverse-dep map.                            |
| lockfile     | dict                                     | —       | other             | Lockfile data.                              |

### update._process_package_args

| Parameter             | Type              | Default | Semantic group    | Notes                                              |
|-----------------------|-------------------|---------|-------------------|----------------------------------------------------|
| package_args          | list[str]         | —       | package_selection |                                                    |
| pipfile_category      | str               | —       | package_selection | Single category name (singular).                   |
| index_name            | str \| None       | —       | package_selection |                                                    |
| reverse_deps          | dict              | —       | other             |                                                    |
| explicitly_requested  | dict[str, list]   | —       | state_flags       | Tracks which packages were explicitly named.       |
| category              | str               | —       | package_selection | Lockfile section (default/develop).                |
| has_package_args      | bool              | —       | state_flags       | Cached truthy of `package_args` for inner logic.   |
| requested_packages    | defaultdict[dict] | —       | other             | Mutable accumulator.                               |
| lock_only             | bool              | False   | install_policy    |                                                    |

### update._resolve_and_update_lockfile

| Parameter             | Type        | Default | Semantic group    | Notes                                            |
|-----------------------|-------------|---------|-------------------|--------------------------------------------------|
| requested_packages    | defaultdict | —       | other             |                                                  |
| pipfile_category      | str         | —       | package_selection |                                                  |
| category              | str         | —       | package_selection |                                                  |
| package_args          | list[str]   | —       | package_selection |                                                  |
| pre                   | bool        | —       | install_policy    |                                                  |
| system                | bool        | —       | target_env        |                                                  |
| pypi_mirror           | str \| None | —       | target_env        |                                                  |
| lockfile              | dict        | —       | other             | Mutated in place.                                |
| resolved_default_deps | dict \| None | None   | other             | Constraint payload for non-default categories.   |

### update._clean_unused_dependencies

| Parameter            | Type        | Default | Semantic group    | Notes                                      |
|----------------------|-------------|---------|-------------------|--------------------------------------------|
| lockfile             | dict        | —       | other             |                                            |
| category             | str         | —       | package_selection |                                            |
| full_lock_resolution | dict        | —       | other             |                                            |
| original_lockfile    | dict        | —       | other             |                                            |
| reverse_deps         | dict \| None | None   | other             |                                            |

### update.upgrade

| Parameter         | Type              | Default | Semantic group    | Notes |
|-------------------|-------------------|---------|-------------------|-------|
| pre               | bool              | False   | install_policy    |       |
| system            | bool              | False   | target_env        |       |
| packages          | list[str] \| None | None    | package_selection |       |
| editable_packages | list[str] \| None | None    | package_selection |       |
| pypi_mirror       | str \| None       | None    | target_env        |       |
| index_url         | str \| None       | None    | package_selection |       |
| categories        | list[str] \| None | None    | package_selection |       |
| dev               | bool              | False   | package_selection |       |
| lock_only         | bool              | False   | install_policy    |       |
| extra_pip_args    | list[str] \| None | None    | execution_options |       |

### uninstall.do_uninstall

| Parameter         | Type              | Default | Semantic group    | Notes                                      |
|-------------------|-------------------|---------|-------------------|--------------------------------------------|
| packages          | list[str] \| None | None    | package_selection |                                            |
| editable_packages | list[str] \| None | None    | package_selection |                                            |
| python            | str / False       | False   | target_env        |                                            |
| system            | bool              | False   | target_env        |                                            |
| lock              | bool              | False   | install_policy    | Re-run `do_lock` afterwards.               |
| all_dev           | bool              | False   | package_selection | Remove all `[dev-packages]`.               |
| all               | bool              | False   | package_selection | Purge entire venv.                         |
| pre               | bool              | False   | install_policy    |                                            |
| pypi_mirror       | str \| None       | None    | target_env        |                                            |
| ctx               | click.Context     | None    | other             | Click context passthrough for error usage. |
| categories        | list[str] \| None | None    | package_selection |                                            |

### lock.do_lock

| Parameter      | Type              | Default | Semantic group    | Notes                              |
|----------------|-------------------|---------|-------------------|------------------------------------|
| system         | bool              | False   | target_env        |                                    |
| clear          | bool              | False   | install_policy    | Clear resolver cache.              |
| pre            | bool              | False   | install_policy    |                                    |
| write          | bool              | True    | execution_options | Write to disk or return dict.      |
| quiet          | bool              | False   | execution_options |                                    |
| pypi_mirror    | str \| None       | None    | target_env        |                                    |
| categories     | list[str] \| None | None    | package_selection |                                    |
| extra_pip_args | list[str] \| None | None    | execution_options |                                    |

### sync.do_sync

| Parameter      | Type              | Default | Semantic group    | Notes |
|----------------|-------------------|---------|-------------------|-------|
| dev            | bool              | False   | package_selection |       |
| python         | str \| None       | None    | target_env        |       |
| bare           | bool              | False   | execution_options |       |
| clear          | bool              | False   | install_policy    |       |
| pypi_mirror    | str \| None       | None    | target_env        |       |
| system         | bool              | False   | target_env        |       |
| deploy         | bool              | False   | install_policy    |       |
| extra_pip_args | list[str] \| None | None    | execution_options |       |
| categories     | list[str] \| None | None    | package_selection |       |
| site_packages  | bool              | False   | target_env        |       |

### requirements.generate_requirements

| Parameter        | Type   | Default | Semantic group    | Notes                                            |
|------------------|--------|---------|-------------------|--------------------------------------------------|
| dev              | bool   | False   | package_selection |                                                  |
| dev_only         | bool   | False   | package_selection |                                                  |
| include_hashes   | bool   | False   | execution_options | Output formatting toggle.                        |
| include_markers  | bool   | True    | execution_options |                                                  |
| categories       | str    | ""      | package_selection | Comma-separated string (not list).               |
| from_pipfile     | bool   | False   | execution_options | Filter by Pipfile categories.                    |
| no_lock          | bool   | False   | execution_options | Generate from Pipfile rather than lockfile.      |
| include_index    | bool   | True    | execution_options |                                                  |

### check.do_check

| Parameter         | Type              | Default | Semantic group    | Notes                                              |
|-------------------|-------------------|---------|-------------------|----------------------------------------------------|
| python            | str / False       | False   | target_env        |                                                    |
| system            | bool              | False   | target_env        |                                                    |
| db                | str \| None       | None    | other             | Safety DB URL.                                     |
| ignore            | list[str] \| None | None    | other             | CVEs to ignore.                                    |
| output            | str               | "screen" | execution_options |                                                   |
| key               | str \| None       | None    | other             | Safety API key.                                    |
| quiet             | bool              | False   | execution_options |                                                    |
| verbose           | bool              | False   | execution_options |                                                    |
| exit_code         | bool              | True    | execution_options |                                                    |
| policy_file       | str               | ""      | other             | Safety policy file.                                |
| save_json         | str               | ""      | execution_options |                                                    |
| audit_and_monitor | bool              | True    | execution_options |                                                    |
| safety_project    | str \| None       | None    | other             |                                                    |
| pypi_mirror       | str \| None       | None    | target_env        |                                                    |
| use_installed     | bool              | False   | state_flags       | Switch source between installed and lockfile.      |
| categories        | str               | ""      | package_selection |                                                    |
| auto_install      | bool              | False   | execution_options | Auto-install safety package.                       |
| scan              | bool              | False   | state_flags       | Delegate to `do_scan`.                             |

### audit.do_audit

| Parameter             | Type              | Default   | Semantic group    | Notes                                       |
|-----------------------|-------------------|-----------|-------------------|---------------------------------------------|
| python                | str / False       | False     | target_env        |                                             |
| system                | bool              | False     | target_env        |                                             |
| output                | str               | "columns" | execution_options |                                             |
| quiet                 | bool              | False     | execution_options |                                             |
| verbose               | bool              | False     | execution_options |                                             |
| strict                | bool              | False     | execution_options |                                             |
| ignore                | list[str] \| None | None      | other             | Vulnerability IDs to ignore.                |
| fix                   | bool              | False     | execution_options |                                             |
| dry_run               | bool              | False     | install_policy    |                                             |
| skip_editable         | bool              | False     | execution_options |                                             |
| no_deps               | bool              | False     | execution_options |                                             |
| local_only            | bool              | False     | execution_options |                                             |
| vulnerability_service | str               | "pypi"    | other             | Backend selector.                           |
| descriptions          | bool              | False     | execution_options |                                             |
| aliases               | bool              | False     | execution_options |                                             |
| output_file           | str \| None       | None      | execution_options |                                             |
| pypi_mirror           | str \| None       | None      | target_env        |                                             |
| categories            | str               | ""        | package_selection |                                             |
| use_installed         | bool              | False     | state_flags       |                                             |
| use_lockfile          | bool              | False     | state_flags       |                                             |

### scan.do_scan

| Parameter         | Type              | Default | Semantic group    | Notes                                       |
|-------------------|-------------------|---------|-------------------|---------------------------------------------|
| python            | str / False       | False   | target_env        |                                             |
| system            | bool              | False   | target_env        |                                             |
| db                | str \| None       | None    | other             |                                             |
| ignore            | list[str] \| None | None    | other             |                                             |
| output            | str               | "screen"| execution_options |                                             |
| key               | str \| None       | None    | other             |                                             |
| quiet             | bool              | False   | execution_options |                                             |
| verbose           | bool              | False   | execution_options |                                             |
| exit_code         | bool              | True    | execution_options |                                             |
| policy_file       | str               | ""      | other             |                                             |
| save_json         | str               | ""      | execution_options |                                             |
| audit_and_monitor | bool              | True    | execution_options |                                             |
| safety_project    | str \| None       | None    | other             |                                             |
| pypi_mirror       | str \| None       | None    | target_env        |                                             |
| use_installed     | bool              | False   | state_flags       |                                             |
| categories        | str               | ""      | package_selection |                                             |
| legacy_mode       | bool              | False   | state_flags       | Falls back to old safety CLI.               |
| auto_install      | bool              | False   | execution_options |                                             |

## Routines out of scope (≤3 non-project params, or per-task-spec exclusion)

Per the task spec, the following routines are noted here rather than
included in the main table. Counts are non-`project` parameters.

- `pipenv/routines/clear.py:do_clear` — 0 params besides `project`.
- `pipenv/routines/uninstall.py:do_purge` — 3 params (`bare`, `downloads`, `allow_global`).
- `pipenv/routines/uninstall.py:_uninstall_from_environment` — 2 params (`package`, `system`).
- `pipenv/routines/install.py:install_build_system_packages` — 3 params (`allow_global`, `pypi_mirror`, `requirements_dir`).
- `pipenv/routines/install.py:_target_marker_environment` — 1 param.
- `pipenv/routines/install.py:_should_use_no_binary` — 2 params, takes no `project`.
- `pipenv/routines/install.py:_cleanup_procs` — 1 param.
- `pipenv/routines/lock.py:overwrite_with_default` — 2 params, takes no `project`.
- `pipenv/routines/clean.py:do_clean` — 5 params (`python`, `dry_run`, `bare`, `pypi_mirror`, `system`); excluded per task spec ("clean" is a routine that doesn't need RoutineContext).
- `pipenv/routines/clean.py:ensure_lockfile` — 1 param.
- `pipenv/routines/graph.py:do_graph` — 4 params (`bare`, `json`, `json_tree`, `reverse`); excluded per task spec.
- `pipenv/routines/shell.py:do_shell` — 5 params (`python`, `fancy`, `shell_args`, `pypi_mirror`, `quiet`); excluded per task spec.
- `pipenv/routines/shell.py:do_run` — 5 params (`command`, `args`, `python`, `pypi_mirror`, `system`); excluded per task spec (script-execution path, not dependency management).
- `pipenv/routines/shell.py:_run_script_sequence`, `do_run_posix`, `do_run_nt`, `_launch_windows_subprocess` — script-sequencing helpers; no `project`-centric routine context applies.
- `pipenv/routines/outdated.py:do_outdated` — 3 params (`pypi_mirror`, `pre`, `clear`).
- `pipenv/routines/outdated.py:_get_lockfile_entry_version` — 1 param, no `project`.
- `pipenv/routines/update.py:get_reverse_dependencies` — 1 param (`project`).
- `pipenv/routines/update.py:_locked_version_satisfies_pipfile_specifier` — 2 params, no `project`.
- `pipenv/routines/update.py:get_modified_pipfile_entries` — 2 params (`project`, `pipfile_categories`).
- `pipenv/routines/update.py:_prepare_categories` — 3 params (`categories`, `dev`, `packages`), no `project`.
- `pipenv/routines/update.py:_find_additional_categories` — 3 params (`packages`, `lockfile`, `current_categories`), no `project`.
- `pipenv/routines/update.py:_detect_conflicts` — 3 params (`package_args`, `reverse_deps`, `lockfile`), no `project`.
- `pipenv/routines/scan.py:build_safety_check_options` — 11 params, no `project` (it is an arg-builder, not a routine).
- `pipenv/routines/scan.py:build_safety_scan_options` — 7 params, no `project` (arg-builder).
- `pipenv/routines/check.py:build_safety_options` — 8 params, no `project` (arg-builder).
- `pipenv/routines/audit.py:build_audit_options` — 14 params, no `project` (arg-builder).
- `pipenv/routines/scan.py:run_pep508_check`, `check_pep508_requirements`, `get_requirements`, `is_safety_installed`, `install_safety`, `run_safety_scan`, `parse_safety_output`, `create_temp_requirements_file` — internal scan helpers, all ≤3 params or no `project`.
- `pipenv/routines/check.py:run_pep508_check`, `check_pep508_requirements`, `get_requirements`, `create_temp_requirements`, `is_safety_installed`, `install_safety`, `run_safety_check`, `parse_safety_output` — internal check helpers, all ≤3 params or no `project`.
- `pipenv/routines/audit.py:is_pip_audit_installed`, `install_pip_audit` — 2 params each.
- `pipenv/routines/requirements.py:_generate_requirements_from_pipfile` — internal sibling of `generate_requirements`; same shape.

The arg-builders (`build_safety_*`, `build_audit_options`) are
explicitly **not** routine-context candidates — they translate Python
arguments into subprocess CLI flag lists and would not benefit from a
shared `RoutineContext`. They are listed here for completeness.

## Cross-cutting observations

1. **`pypi_mirror` and `system` are universal.** Almost every routine
   entry point and helper carries `pypi_mirror` and `system` (or its
   alias `allow_global`) as separate keyword arguments, even though
   `pypi_mirror` is also surfaceable as a project setting. Together
   they account for ~40 rows in the per-routine table. These are the
   strongest signal that a shared `RoutineContext.target_env` field
   group exists.

2. **`package_selection` shape is duplicated three ways.** The trio
   `(packages, editable_packages, categories/pipfile_categories)`
   appears verbatim in `do_install`, `do_update`, `do_uninstall`,
   `upgrade`, and `handle_new_packages`. The same shape with a
   different name (`package_args`, `pipfile_category`, `category`)
   recurs in `_process_package_args` and
   `_resolve_and_update_lockfile`. Two near-identical sub-flavours
   (`category` vs `pipfile_category`, `categories` vs
   `pipfile_categories`) co-exist within `update.py` and call into
   `get_lockfile_section_using_pipfile_category` /
   `get_pipfile_category_using_lockfile_section` for translation —
   a `RoutineContext` could centralise this translation once.

3. **`install_policy` flags travel as a packet.** `pre`, `deploy`,
   `skip_lock`, `ignore_pipfile`, `lockfile_only` always travel
   together through the install/init/lock chain. `clear` and
   `lock_only` join them in update flows. None of these flags is
   useful in isolation — they describe a coherent install/lock
   intent. They are the strongest candidate for a single nested
   dataclass.

4. **`state_flags` is small and incoherent.** Only 9 rows. The flags
   in this group (`perform_upgrades`, `has_package_args`,
   `explicitly_requested`, `use_installed`, `use_lockfile`,
   `legacy_mode`, `scan`) describe sub-routine intent rather than
   user-facing policy and are heterogeneous. This group probably
   should *not* be a field of `RoutineContext`; instead these stay as
   explicit local parameters to the helpers that need them, or fold
   into `install_policy` if they map cleanly. The presence of `scan`
   in `do_check` (a flag that routes to a completely different
   routine) is a particularly strong code smell.

5. **`other` is dominated by data-flow plumbing.** Most `other` rows
   are dicts/queues/strings passed between helpers within a single
   routine call: `lockfile`, `requested_packages`, `reverse_deps`,
   `procs`, `sources`, `old_hash`/`new_hash`. These belong in a
   per-routine workflow context (a `LockOperation` /
   `UpgradeOperation` object) and should not appear on
   `RoutineContext` itself, which is for *inputs to a user-facing
   routine*.

## Drives T_C.3

This inventory feeds directly into `T_C.3`'s `RoutineContext` dataclass
shape proposal. The observations above suggest a `RoutineContext` with
three nested groups (`TargetEnv`, `InstallPolicy`, `PackageSelection`)
plus a list-typed `extra_pip_args` field; `state_flags` and `other` are
explicitly left out of the dataclass and remain as call-site arguments
to internal helpers. T_C.3 should reference this file for the
field-by-field rationale, then this file is deleted as part of T_C.3's
commit.
