# Initiative A — URL/path utility inventory

Inventory of module-level symbols in `pipenv/utils/internet.py` and
`pipenv/utils/fileutils.py`, plus a canonical-home decision for each.
This document drives T_A.2 (consolidation of the `is_valid_url`
duplicate) and is consistent with T_B.3
(`docs/dev/initiative-b-triage-fileutils.md`), which already concluded
that the filesystem-flavored URL helpers (`url_to_path`, `path_to_url`,
`is_file_url`) stay in `fileutils.py`.

## Methodology

"Caller count" is the number of references to a symbol found in
`pipenv/`, excluding `pipenv/patched/`, `pipenv/vendor/`, and the
symbol's own defining file. Both import lines and call sites are
counted; doctest-example lines inside the defining file are excluded by
the same self-file filter. This is the verifiable command:

```
grep -rn --include='*.py' '\b<symbol>\b' pipenv/ \
  --exclude-dir=patched --exclude-dir=vendor
```

The reported number equals total matches minus matches inside the
defining file. The "duplicate" `is_valid_url` is counted independently
for each home (`internet` external = 13, `fileutils` external = 12 —
the overlap arises because import lines and shared call sites match
both bare-name greps; the table notes which call site really binds to
which home).

Counts captured on 2026-05-12 against the working branch
`maintenance/code-cleanup-2026-05`.

## `pipenv/utils/internet.py`

| Symbol                          | Callers | Canonical home | Notes |
|---------------------------------|---------|----------------|-------|
| `get_requests_session`          | 2       | internet       | Pure HTTP. Used by `project.py`. Also called intra-module by `download_file` and `proper_case`. |
| `is_valid_url`                  | 13      | **internet (canonical)** | **Duplicate.** Same name and equivalent body exists in `fileutils.py`. External call sites that bind to `internet` import correctly from `internet` (`routines/install.py`, `project.py`, `utils/indexes.py`, `cli/options.py`). The `utils/requirementslib.py:23` site imports from `fileutils` — that is the only mis-targeted caller and is what T_A.3 fixes. |
| `is_pypi_url`                   | 7       | internet       | Scheme/host check against `pypi.org`. No filesystem dimension. |
| `replace_pypi_sources`          | 2       | internet       | Pure sources-list rewrite around URL identity. |
| `create_mirror_source`          | 4       | internet       | Builds an index-source dict from a URL. |
| `download_file`                 | 2       | internet       | HTTP GET to a local filename. The local filename happens to be a path but the function's concern is the HTTP transfer, not the filesystem destination. |
| `get_host_and_port`             | 3       | internet       | Pure URL parsing via `urllib3.util`. |
| `get_url_name`                  | 4       | internet       | Returns URL host. |
| `is_url_equal`                  | 2       | internet       | URL canonicalization comparison. |
| `proper_case`                   | 2       | internet       | Talks to pypi.org/pypi/{name}/json. HTTP, not path. |
| `_strip_credentials_from_url`   | 9       | internet       | URL userinfo parsing for GHSA-8xgg-v3jj-95m2. Used externally despite leading underscore (`utils/pip.py`, `utils/indexes.py`, `utils/requirementslib.py`). |
| `_read_existing_netrc_content`  | 0       | internet       | Only referenced inside `internet.py` (helper for `write_credentials_netrc`). Stays as a module-private helper; the underscore name correctly signals that. **Not a delete candidate** — it has an in-module caller. |
| `write_credentials_netrc`       | 6       | internet       | Netrc writer for pip auth (GHSA-8xgg-v3jj-95m2 mitigation). Touches the filesystem but the data shape is URL/credentials; conceptually a network-auth concern. Stays. |
| `PackageIndexHTMLParser`        | 3       | internet       | `html.parser.HTMLParser` subclass that pulls `<a href>` out of PyPI simple-index pages. URL-domain. |

## `pipenv/utils/fileutils.py`

| Symbol                          | Callers | Canonical home | Notes |
|---------------------------------|---------|----------------|-------|
| `is_file_url`                   | 3       | fileutils      | Filesystem-flavored scheme check. Per T_B.3, stays in `fileutils`. Cross-reference comment to be added to `internet.py` per task description. Note: the three external grep hits at `pipenv/project.py:1373-1375` are a *local variable* named `is_file_url`, not a call to this helper — there are zero real external callers today, but the bare-name grep cannot distinguish them. |
| `is_valid_url`                  | 12      | **internet (canonical)** | **Explicit duplicate** — identical body to `internet.is_valid_url`. The only external caller that genuinely *resolves* to this `fileutils` copy is `utils/requirementslib.py:23` (multi-symbol import line). The other grep hits overlap with the `internet.is_valid_url` row because both definitions share a name. T_A.3 surgically removes `is_valid_url` from `requirementslib.py:23` without touching `normalize_path` / `url_to_path` on the same line; T_A.2 replaces the local def here with a `DeprecationWarning`-emitting shim. |
| `url_to_path`                   | 3       | fileutils      | Returns `pathlib.Path`; reconstructs UNC netloc. Per T_B.3, filesystem-flavored URL handling stays here. External callers: `utils/requirementslib.py` (import + 2 call sites = 3 hits). Cross-reference from `internet.py` per task description. |
| `get_long_path` (Windows only)  | 0       | fileutils      | Conditional `def` under `if os.name == "nt":`. No callers in `pipenv/` today; kept as Windows-only helper available for future use. Flag as a possible delete in a later cleanup, but **not** in the T_A.2 scope. |
| `normalize_path`                | 8       | fileutils      | Path expansion / resolution. Purely filesystem. |
| `normalize_drive`               | 4       | fileutils      | Windows drive-letter case fixup. Purely filesystem. |
| `path_to_url`                   | 1       | fileutils      | Builds a `file://` URI from a local `Path`, quoting-aware. Per T_B.3, stays in `fileutils`. The single external grep hit is the unrelated def in `pipenv/utils/shell.py:104` — a duplicate-name hazard, not a real caller. No genuine external pipenv/ callers; the only real call site is intra-module (`open_file` at line 163). Cross-reference from `internet.py` per task description. **See "Adjacent duplicates" below for the dead shadow definition in `shell.py`.** |
| `open_file`                     | 2       | fileutils      | Context manager that resolves a link to either a local file open or an HTTP fetch. Sits on the boundary; the dispatch hinges on `is_file_url` / `url_to_path` and the local-path open is the heavy lifter. Stays in `fileutils`. |
| `temp_path`                     | 12      | fileutils      | Saves and restores `sys.path` around a block. `sys.path` is a filesystem-search-path concern. Most of the grep hits are *local variables named `temp_path`* in `utils/locking.py` and `routines/scan.py`, not calls to this context manager — the only genuine callers are `environment.py:29` (import) and `environment.py:450`, `:817` (calls). Bare-name grep cannot distinguish; recorded raw count for verifiability. **See "Adjacent duplicates" below for the dead shadow definition in `shell.py`.** |
| `TRACKED_TEMPORARY_DIRECTORIES` | 0       | fileutils      | Module-level list used by `create_tracked_tempdir` and the `atexit` cleanup. Module-private state; not exported; stays. |
| `create_tracked_tempdir`        | 14      | fileutils      | Heavily used temp-dir factory with atexit cleanup. Purely filesystem. |
| `check_for_unc_path`            | 0       | fileutils      | UNC-path predicate for Windows. No callers in `pipenv/` today; kept as a Windows-specific helper. Flag as a possible delete in a later cleanup, but **not** in the T_A.2 scope. |

## Adjacent duplicates

These are not in the two target files but are duplicate-name hazards
surfaced by T_B.3 and by the temp_path / temp_path conflict found here.
They are recorded so T_A.2 has full context.

- **`pipenv/utils/shell.py:104` — `path_to_url`.** A second
  `path_to_url` lives in `shell.py` with a *different*
  implementation (`Path(...).as_uri()`, no quoting-awareness, no
  `file:///drive:` Windows fixup). Zero callers in `pipenv/`. Dead
  duplicate; safe to **delete** as part of T_A.2's URL/scheme cleanup
  pass.
- **`pipenv/utils/shell.py:528` — `temp_path`.** A second `temp_path`
  context manager identical in body to `fileutils.temp_path` (saves
  and restores `sys.path`). Zero callers in `pipenv/` — all current
  importers go through `fileutils.temp_path` (`environment.py:29`).
  Dead duplicate; safe to **delete** opportunistically alongside the
  shell.path_to_url removal, though strictly speaking it is outside
  Initiative A's URL/path scope. Flagging here so the orchestrator can
  decide whether to fold the cleanup into T_A.2 or open a follow-up.

## Canonical decisions

Acted on in Initiative A:

- `is_valid_url` — **canonical home is `internet`**. The body in
  `fileutils.py` is the duplicate. T_A.2 replaces it with a
  `DeprecationWarning`-emitting shim; T_A.3 surgically removes the
  `is_valid_url` name from `utils/requirementslib.py`'s
  multi-symbol import; T_A.4 deletes the shim one release later.
- `shell.path_to_url` — **delete** (dead duplicate, different and
  inferior implementation, zero callers). Can be removed in T_A.2's
  commit alongside the `is_valid_url` work since both are URL/scheme
  cleanups; if the diff gets noisy, split into a same-task follow-up
  commit.

Stay where they are (no Initiative A action required):

- `is_file_url`, `url_to_path`, `path_to_url` (the `fileutils` one) —
  filesystem-flavored URL handling, kept in `fileutils.py` per T_B.3.
  T_A.2 adds a cross-reference comment header to `internet.py`
  pointing readers at these three names.
- All other symbols listed in the two tables above — single home,
  no overlap with the other module.

Debatable / deferred (not in Initiative A scope):

- `write_credentials_netrc` and `_read_existing_netrc_content` —
  touch the filesystem but are conceptually network-auth helpers and
  live near `_strip_credentials_from_url` which they collaborate
  with. Leaving in `internet.py` keeps the GHSA-8xgg-v3jj-95m2
  mitigation cohesive.
- `open_file` — boundary symbol; stays in `fileutils.py` because the
  local-file branch is the substantive path. Could equally be argued
  for `internet.py`; flagged in case a future reviewer wants to
  revisit, but it is **not** a current overlap.
- `get_long_path`, `check_for_unc_path`, `TRACKED_TEMPORARY_DIRECTORIES`
  — zero external callers but each is non-trivially Windows-specific
  or module-private state. Not delete candidates for Initiative A;
  could be revisited under Initiative B / E cleanup if desired.
- `shell.temp_path` — dead duplicate of `fileutils.temp_path` but
  outside the URL/path domain. Safe to delete, deferred to a separate
  cleanup unless folded into T_A.2's hygiene pass.
