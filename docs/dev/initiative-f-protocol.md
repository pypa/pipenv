# Initiative F — Resolver Subprocess Protocol (current state)

> Status: reference documentation. No code change.
> Source-of-truth date: 2026-05-12, working branch
> `maintenance/code-cleanup-2026-05`.
> Companion to `docs/dev/modernization-prd.md` § "Initiative F".

## 1. Summary

This document enumerates, in one place, the contract between pipenv's
parent process and the `pipenv-resolver` subprocess it spawns to perform
dependency resolution. It covers what argv is built, what environment
variables cross the boundary, what JSON shape comes back, what failure
modes exist, and where the in-process and subprocess paths have
diverged.

Two audiences read it:

- **The author of T_F.2.** That task introduces a typed
  `ResolverRequest` / `ResolverResponse` pair (dataclasses) and replaces
  the current ad-hoc `argv` + env-var + temp-file + JSON-on-stdout
  marshaling with a single typed schema. This doc enumerates every
  field the typed schema must cover.
- **Whoever is debugging a subprocess crash in the field.** When a user
  reports "pipenv install hangs / dies / produces garbage JSON", this
  doc is the map from the user-visible symptom to the source line where
  it crosses the boundary.

Be warned: the current protocol has accumulated cruft. Some argv flags
are accepted-but-unused (`--parse-only`, `--pipenv-site`); some
environment variables are read by the subprocess but never explicitly
exported by the parent (they leak through `os.environ` inheritance);
the JSON envelope is just `list[dict]` with no version field and no
discriminator between "success" and "failure". One of T_F.2's jobs is
to decide what to keep, what to drop, and what to formalize.

## 2. Architecture overview

```
+--------------------------------------------------------------------+
|  Parent process (the `pipenv` CLI invocation)                      |
|                                                                    |
|  pipenv install / lock / update / uninstall                        |
|         |                                                          |
|         v                                                          |
|  pipenv/routines/{lock,install,update,uninstall}.py                |
|         |                                                          |
|         v                                                          |
|  pipenv/utils/resolver.py :: venv_resolve_deps()    (line 1282)    |
|         |                                                          |
|         |  branches on  project.s.PIPENV_RESOLVER_PARENT_PYTHON    |
|         |                                                          |
|     +---+---------------------------------+                        |
|     |                                     |                        |
|     v                                     v                        |
| in-process branch                  subprocess branch (default)     |
| (debugger / unit test)             (production)                    |
|     |                                     |                        |
|     |  imports pipenv.resolver            |  builds argv list      |
|     |  calls resolver.resolve_packages()  |  calls resolve()       |
|     |  in the *parent* interpreter        |  (line 1180)           |
|     |                                     |                        |
|     |                                     v                        |
|     |                              subprocess_run() / Popen        |
|     |                              -> spawns:                      |
|     |                                                              |
|     |                              python -m pipenv.resolver \     |
|     |                                  --write /tmp/resolverXXXX.json \
|     |                                  --constraints-file /tmp/... \
|     |                                  --category default \        |
|     |                                  ... <package specs> ...     |
|     |                                     |                        |
+-----+-------------------------------------+------------------------+
      |                                     |
      |                                     v
      |                +-----------------------------------------+
      |                | Child process (pipenv-resolver)         |
      |                |                                         |
      |                | pipenv/resolver.py :: main()  (line 537)|
      |                |   -> _ensure_modules()                  |
      |                |   -> handle_parsed_args()               |
      |                |   -> _apply_python_version_override()   |
      |                |   -> _main()                            |
      |                |   -> resolve_packages()  (line 401)     |
      |                |        -> pipenv/utils/resolver.py      |
      |                |             resolve_deps()  (line 1524) |
      |                |             actually_resolve_deps()     |
      |                |                  (line 1119)            |
      |                |             -> Resolver.resolve()       |
      |                |             -> Resolver.resolve_hashes  |
      |                |             -> Resolver.clean_results() |
      |                |        -> process_resolver_results()    |
      |                |             -> Entry dataclass wrap     |
      |                |   -> json.dump(processed, --write file) |
      |                |   -> sys.exit(0)                        |
      |                +-----------------------------------------+
      |                                     |
      v                                     v
in-process: results flow                parent reads --write file:
back as Python objects via              json.load(open(target_file))
the same resolve_packages()             (resolver.py line 1469)
return value.
      |                                     |
      +------------------+------------------+
                         |
                         v
                pipenv/utils/locking.py :: prepare_lockfile()
                         |
                         v
              Pipfile.lock mutation, on disk.
```

Key files and entry points:

- `pipenv/resolver.py` — the *top-level* resolver script. This is the
  `pipenv-resolver` console-script entry (see `pyproject.toml` line 63,
  `scripts.pipenv-resolver = "pipenv.resolver:main"`). It is what the
  subprocess is. The parent never calls `main()` directly; it reaches
  in to `resolver.resolve_packages` for the in-process path.
- `pipenv/utils/resolver.py` — the *library* resolver. The `Resolver`
  class (line 284) does the actual work; `venv_resolve_deps`
  (line 1282) and `resolve()` (line 1180) are the subprocess plumbing;
  `resolve_deps` (line 1524) and `actually_resolve_deps` (line 1119)
  are the inner pip-driving routine.
- `pipenv/utils/locking.py :: format_requirement_for_lockfile` (line
  46) — the function that turns a resolved `InstallRequirement` into a
  lockfile-shaped dict. Called from `Resolver.clean_results()`.

The "in-process" branch is not a true in-process path: it still goes
through `pipenv.resolver.resolve_packages`, just inside the parent
interpreter. It exists so that a developer can drop `pdb.set_trace()`
inside the resolver and have it actually fire. It is gated by
`PIPENV_RESOLVER_PARENT_PYTHON` (see
`pipenv/environments.py:430`).

## 3. Subprocess invocation contract

### 3.1 argv

The argv is constructed in `pipenv/utils/resolver.py`
`venv_resolve_deps()` between lines **1430 and 1463**. The shape is:

```
<python> <abs/path/to/pipenv/resolver.py>
    [--pre]
    [--clear]
    [--system]
    [--category <pipfile-category>]
    [--verbose]
    --write <tempfile-1.json>
    --constraints-file <tempfile-2.txt>
    [--resolved-default-deps-file <tempfile-3.json>]
```

Argv elements, in order:

| Position           | Source line (parent)                           | Source line (child argparse) | Meaning                                                                                                                                                                                |
| ------------------ | ---------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<python>`         | `resolver.py:1431` (`which("python", ...)`)    | n/a (interpreter)            | Path to the Python interpreter for the target environment (project virtualenv, or system Python when `--system`).                                                                       |
| script path        | `resolver.py:1432` (`resolver.__file__.rstrip("co")`) | n/a                  | Absolute path to `pipenv/resolver.py`. Note: the `.rstrip("co")` defensively converts a `.pyc`/`.pyo` import-cache path back to `.py`.                                                |
| `--pre`            | `resolver.py:1434–1435`                        | `resolver.py:53`             | Allow pre-release versions. Boolean.                                                                                                                                                   |
| `--clear`          | `resolver.py:1436–1437`                        | `resolver.py:54`             | Clear pip's wheel / HTTP cache before resolving. Boolean.                                                                                                                              |
| `--system`         | `resolver.py:1438–1439`                        | `resolver.py:62`             | Resolve against the system Python rather than a virtualenv. Boolean.                                                                                                                   |
| `--category <cat>` | `resolver.py:1440–1442`                        | `resolver.py:57–61`          | Pipfile category being resolved. Defaults to `"default"` if absent. Values seen: `default`, `dev-packages`, custom user categories.                                                    |
| `--verbose`        | `resolver.py:1443–1444`                        | `resolver.py:55`             | Increase resolver verbosity. Subprocess sets `PIPENV_VERBOSITY=1` and `PIP_RESOLVER_DEBUG=1` on receipt (`resolver.py:103–105`).                                                       |
| `--write <path>`   | `resolver.py:1445–1449`                        | `resolver.py:76–81`          | Path to a temp JSON file the subprocess must write its results to. **This is the actual result transport** — stdout is *not* the result channel. Created with `tempfile.NamedTemporaryFile(prefix="resolver", suffix=".json", delete=False)`. |
| `--constraints-file <path>` | `resolver.py:1451–1459`               | `resolver.py:82–87`          | Path to a temp text file containing one line per package: `"<name>, <pip-line>\n"`. The subprocess parses this back into `parsed.packages` (`resolver.py:106–114`) and deletes the file on read. This is the actual "what to resolve" channel. |
| `--resolved-default-deps-file <path>` | `resolver.py:1463` (via `_append_resolved_default_deps_args` line 1244) | `resolver.py:88–93` | Path to a JSON dump of the default-category resolution result, used to constrain non-default categories' resolution. Only added when `resolved_default_deps` is non-empty. Subprocess `json.load`s and deletes (`resolver.py:123–129`). Tracks gh-4665. |
| trailing positional `packages` | (none — see note)                    | `resolver.py:94`             | The argparse parser still accepts positional package specs (`nargs="*"`), but **the parent does not pass any** — packages are routed through `--constraints-file` instead. This is dead surface. |

Accepted but **unused** argv flags (cruft to remove or formalize in
T_F.2):

| Flag                  | Defined at         | Status                                                                                                                                                                          |
| --------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--parse-only`        | `resolver.py:63`   | Parsed into `parsed.parse_only`, plumbed through `_main(parse_only=...)` at `resolver.py:565`, then **dropped on the floor** — `_main` ignores the parameter (`resolver.py:494–504`). |
| `--pipenv-site`       | `resolver.py:64–69`| Parsed into `parsed.pipenv_site`, never referenced elsewhere in the file. The parent exports `PIPENV_SITE_DIR` as an env var (line 1379) but never passes the flag.            |
| positional `packages` | `resolver.py:94`   | Code path exists (`resolver.py:115–118`: `_parse_package_list`), but the parent always sets `--constraints-file` so the positional branch is unreachable in production.        |

### 3.2 Environment variables

Environment variables flow across the boundary in three classes:
**explicitly exported by the parent**, **read by the child explicitly**,
and **read implicitly by pip / the rest of the stack via `os.environ`
inheritance**. Listed alphabetically below.

Explicit, set by parent inside `venv_resolve_deps()` `temp_environ()`
block (`pipenv/utils/resolver.py:1360–1391`):

| Variable                          | Parent sets at                          | Child reads at                         | Purpose                                                                                                                            |
| --------------------------------- | --------------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `PIP_NO_INPUT`                    | `resolver.py:1364`                      | (pip internal)                         | Forces non-interactive pip — never prompts on stdin.                                                                              |
| `PIP_KEYRING_PROVIDER`            | `resolver.py:1368–1370` (conditional)   | (pip internal)                         | Lets a credential manager (e.g. Windows Credential Manager) supply private-index creds. See gh-5715.                              |
| `NETRC`                           | `resolver.py:1266` via `_set_resolver_netrc()` | (pip internal, via patched code)| Points at a temp netrc file containing private-index credentials extracted from Pipfile sources. Re-injects creds out-of-band to avoid leaking them in argv. See GHSA-8xgg-v3jj-95m2. |
| `PIPENV_SITE_DIR`                 | `resolver.py:1377–1381` (conditional)   | `resolver.py:68` (argparse default, but consumer is dead) | Computed from `get_pipenv_sitedir()`. Allows the subprocess to locate the installed pipenv package; currently overridden by `_ensure_modules` which fixes up `sys.path` directly (`resolver.py:11–46`). Effectively redundant. |
| `PIPENV_EXTRA_PIP_ARGS`           | `resolver.py:1382–1383` (conditional)   | `pipenv/utils/resolver.py:487–490`     | JSON-encoded list of extra pip args to splice into `Resolver.prepare_pip_args()`. JSON-in-an-env-var is a smell T_F.2 should fix. |
| `PIPENV_PYPI_MIRROR`              | `resolver.py:1362–1363` (conditional)   | `resolver.py:438–441`                  | PyPI mirror URL substituted for `pypi.org`. Also used by `_generate_resolution_cache_key` (`pipenv/utils/resolver.py:1065`).      |
| `PIPENV_RESOLVER_PYTHON_VERSION`  | `resolver.py:1388–1391` (conditional)   | `resolver.py:516`                      | Full Python version string (e.g. `"3.11.6"`) used to patch `pip._vendor.packaging.markers.default_environment` so marker evaluation matches the Pipfile-required Python version rather than the running interpreter. See gh-5908. |

Explicit, set by parent inside the child interpreter itself (after the
subprocess has started — these are set by `pipenv/resolver.py:541–543`
in `main()` *before* the actual resolve begins):

| Variable                          | Set at                                  | Purpose                                                                                                                            |
| --------------------------------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `PIP_DISABLE_PIP_VERSION_CHECK`   | `resolver.py:541`                       | Suppress pip's self-update warning. Also set in `pipenv/__init__.py:14` for all pipenv invocations.                              |
| `PYTHONIOENCODING`                | `resolver.py:542`                       | Force UTF-8 stdout encoding so JSON dumps round-trip on Windows.                                                                  |
| `PYTHONUNBUFFERED`                | `resolver.py:543`                       | Force unbuffered stdout/stderr so download-progress lines reach the parent in real time.                                          |
| `PIPENV_VERBOSITY`, `PIP_RESOLVER_DEBUG` | `resolver.py:104–105` (when `--verbose`)| Wired up after argparse runs.                                                                                                    |

Implicit, inherited through `os.environ.copy()` in
`subprocess_run([...], env=os.environ.copy())`
(`pipenv/utils/resolver.py:1182`), plus `subprocess_run`'s own
overlay of `PYTHONIOENCODING` (`pipenv/utils/processes.py:65–66`):

- `PIP_PYTHON_PATH` — set by `HackedPythonVersion`
  (`pipenv/utils/dependencies.py:111–112`) before resolution. Tells
  patched pip which interpreter to target for compatibility checks.
- `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, all other `PIP_*` — standard
  pip configuration inherited from the parent shell.
- `PIP_SRC` — set by `resolve_deps` (`pipenv/utils/resolver.py:1542–
  1543`) if not already in env.
- The full parent shell env. Everything inherits.

### 3.3 stdin

The subprocess does **not** read stdin. `PIP_NO_INPUT=1` is exported
explicitly to prevent any nested pip call from attempting an
interactive prompt. The parent passes no `stdin=` argument to `Popen`,
so the child inherits the parent's stdin file descriptor; pip-driven
network code never reads from it.

### 3.4 cwd

The parent does **not** set `cwd` when calling `subprocess_run`
(`pipenv/utils/resolver.py:1182`). The subprocess inherits the parent's
working directory. The subprocess locates the project via `Project()`
(`pipenv/resolver.py:432, 448`), which performs its own
Pipfile-discovery walk from the cwd up — so an unusual cwd at spawn
time can produce confusing "Pipfile not found" errors in the child.

## 4. stdout / stderr / exit-code contract

### 4.1 stdout

`stdout` is **not** the result channel. The JSON results are written
to the `--write <path>` tempfile and the parent reads them from disk
after the child exits (`pipenv/utils/resolver.py:1467–1469`).

The parent does still *collect* stdout — line 1189 (`stdout_chunks`)
in `resolve()` accumulates it via a reader thread (line 1192–1198),
specifically to drain the pipe and prevent buffer-full deadlocks.
That collected stdout is:

- printed back to the user (`err.print(out.strip())`) only when
  `--verbose` is set (`pipenv/utils/resolver.py:1239–1240`).
- echoed on failure as part of the diagnostic dump
  (`pipenv/utils/resolver.py:1489`).

In practice the subprocess produces little or no stdout in non-verbose
mode — pip's chatter goes to stderr, the JSON goes to the tempfile.

### 4.2 stderr

`stderr` carries:

- All resolver progress logging (`logger.info` etc.).
- All pip download / build chatter.
- Tracebacks if the subprocess crashes uncleanly.

The parent reads stderr in a dedicated reader thread
(`pipenv/utils/resolver.py:1200–1210`). Per line, it does one of:

- if verbose: echo unconditionally.
- otherwise: pattern-match for "Downloading ... (NN MB)" via
  `_is_download_status_line()` (`pipenv/utils/resolver.py:1159–1177`)
  and echo just those, so the user sees something during a long
  download. See issue #5718.

On non-zero exit, stderr is dumped wholesale to the user, with a
`ResolutionImpossible`-aware hint to re-run with `--verbose`
(`pipenv/utils/resolver.py:1228–1238`). On zero exit but non-empty
stderr, the parent prints a `Warning: ...` (`pipenv/utils/resolver.py:
1481–1484`).

### 4.3 Exit codes

The subprocess only ever exits via `sys.exit` indirectly. Concretely:

- Exit 0 — success. `resolve_packages` ran cleanly and wrote
  `--write` file. Parent reads the file.
- Exit non-zero — failure. The parent assumes this means resolution
  failed and raises `ResolutionFailure("Failed to lock Pipfile.lock!")`
  (`pipenv/utils/resolver.py:1238`). There is no distinction between
  "ResolutionImpossible (dependency conflict, user-actionable)" vs
  "InternalError (pipenv bug, file an issue)" vs "Network error". Every
  non-zero exit is opaquely "locking failed", and the parent best-effort
  parses stderr for hints.

There is **no protocol-level exit-code map.** The subprocess exits
non-zero if Python itself does — uncaught exception bubble, OS signal,
etc. This is one of the more uncomfortable parts of the current
protocol and is called out in §9 as a decision deferred to T_F.2.

## 5. JSON payload schema

The `--write` tempfile contains `json.dump(processed_results, fh)`
(`pipenv/resolver.py:476–477`), where `processed_results` is the return
value of `process_resolver_results()` (`pipenv/resolver.py:361–398`).

### 5.1 Envelope

The top-level JSON value is a `list[dict]`. There is **no envelope**:
no version field, no top-level discriminator, no error-vs-success tag.
A failed resolution does not produce a JSON file at all — it exits
non-zero and the parent never reaches the `json.load` call.

```json
[
  { /* lockfile entry 1 */ },
  { /* lockfile entry 2 */ },
  ...
]
```

### 5.2 Per-entry shape

Each entry is the dict returned by `Entry.get_cleaned_dict`
(`pipenv/resolver.py:288–320`), with all `None` values stripped. Every
top-level key, its type, and its meaning:

| Key            | Type                  | Origin                          | Meaning                                                                                                                                                       |
| -------------- | --------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`         | `str`                 | `Entry.requirement.name`        | Canonical package name. **Always present.**                                                                                                                  |
| `version`      | `str` (e.g. `"==1.2.3"`) | `Entry._clean_version`       | PEP 440 specifier. `_clean_version` (`resolver.py:241–252`) prefixes a bare version with `==` if no operator is present. **Omitted for VCS entries** (popped at `resolver.py:317`). |
| `extras`       | `list[str]`           | `entry_dict["extras"]`          | Sorted list of extras (e.g. `["security"]`). Omitted when empty.                                                                                              |
| `markers`      | `str`                 | `Entry._clean_markers`          | A space-and-joined PEP 508 marker expression. Built by combining `sys_platform`, `python_version`, `os_name`, `platform_machine`, and raw `markers` keys from the inner resolved dict (`resolver.py:254–273`). |
| `hashes`       | `list[str]`           | `entry_dict["hashes"]`          | Sorted list of pip-style `algorithm:hex` strings (e.g. `"sha256:abcd..."`). Omitted when empty.                                                              |
| `subdirectory` | `str`                 | `Entry.requirement.source.subdirectory` | VCS subdirectory fragment. Only present for VCS/file/URL entries.                                                                                  |
| `editable`     | `bool`                | `entry_dict["editable"]`        | `True` when the entry is an editable install. Omitted otherwise.                                                                                              |
| `path`         | `str`                 | `entry_dict["path"]`            | Filesystem path for local-path requirements. Omitted otherwise.                                                                                               |
| `file`         | `str`                 | `entry_dict["file"]`            | URL / file URI for direct-file requirements. Omitted otherwise.                                                                                               |
| `index`        | `str`                 | `Entry.requirement.source.index`| Name of the Pipfile `[[source]]` block this came from. Resolver uses `Resolver.index_lookup` (`pipenv/utils/resolver.py:313, 596–599`) to populate.            |
| `git` / `hg` / `svn` / `bzr` | `str`   | `Entry.requirement.source.vcs/url` | VCS URL. Mutually exclusive — exactly one of these four is present for a VCS entry. Set via `resolver.py:311–312`.                                          |
| `ref`          | `str`                 | `entry_dict["ref"]` or `requirement.source.ref` | VCS reference (commit hash, branch, tag). Only for VCS entries (`resolver.py:313–316`).                                                                |

Note: `index`, `git`/`hg`/`svn`/`bzr`, `ref`, and `subdirectory` are
added conditionally (`resolver.py:307–316`); they only appear when
populated. The final dict-comprehension at `resolver.py:320`
(`{k: v for k, v in cleaned.items() if v is not None}`) drops any key
whose value is `None`, so the absence of a key always means "this
entry does not carry that information".

### 5.3 Representative example — successful resolution

A two-package resolution: `requests==2.31.0` (with one transitive
hash) and a VCS pin `flask` from GitHub.

```json
[
  {
    "name": "requests",
    "version": "==2.31.0",
    "markers": "python_version >= '3.7'",
    "hashes": [
      "sha256:58cd2187c01e70e6e26505bca751777aa9f2ee0b7f4300988b709f44e013003f",
      "sha256:942c5a758f98d790eaed1a29cb6eefc7ffb0d1cf7af05c3d2791656dbd6ad1e1"
    ],
    "index": "pypi"
  },
  {
    "name": "flask",
    "git": "https://github.com/pallets/flask.git",
    "ref": "9f4f0e72cc6b4a5f8b3d3a01d3a18a8b1f7c4f9a",
    "subdirectory": null,
    "editable": false
  }
]
```

(In practice, `subdirectory: null` and `editable: false` would be
absent — the `if v is not None` filter at `resolver.py:320` drops
them. The example shows them for illustration only. Note also that
`Entry.validate_constraints` runs *before* the entry reaches this
list — see `resolver.py:394`.)

### 5.4 Representative example — failure

There is no payload. The subprocess exits non-zero before the JSON
file is written; the parent never opens it. Diagnostic information is
emitted to stderr as free-form text, e.g.:

```
ERROR: Cannot install foo==1.0 and bar==2.0 because these package versions have conflicting dependencies.

The conflict is caused by:
    foo 1.0 depends on shared>=3.0
    bar 2.0 depends on shared<2.0

To fix this you could try to:
1. loosen the range of package versions you've specified
2. remove package versions to allow pip to attempt to solve the dependency conflict
```

The parent reformats and displays this via the
`ResolutionImpossible`-aware branch in `resolve()`
(`pipenv/utils/resolver.py:1230–1237`). This text is not structured —
no JSON, no machine-readable shape. Initiative F's typed schema is
the natural place to introduce a structured `ResolutionError` variant.

## 6. Failure modes

| Failure                                       | Detection point                                       | Behaviour                                                                                                                                                            |
| --------------------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Subprocess crashes mid-resolution (e.g. SIGSEGV, uncaught exception) | `c.returncode != 0` at `pipenv/utils/resolver.py:1228` | `ResolutionFailure("Failed to lock Pipfile.lock!")` is raised. Stderr is echoed wholesale. The `--write` file is never read, but is also never cleaned up (cruft on `/tmp`). |
| Subprocess emits valid JSON file but exits non-zero | `c.returncode != 0` (same path)                       | Same — non-zero exit dominates; the JSON file is orphaned.                                                                                                          |
| Subprocess writes partial JSON before crashing | `json.load` at line 1469 raises `json.JSONDecodeError` | Caught at `pipenv/utils/resolver.py:1470`; both stdout and stderr are echoed; the `--write` file is unlinked; `RuntimeError("There was a problem with locking.")` is raised. |
| Subprocess writes valid JSON but with unexpected schema | Not detected upfront                              | The list flows into `prepare_lockfile` (`pipenv/utils/locking.py:195`) which iterates `dep["name"]`. A missing `name` raises `KeyError`. Other missing keys silently produce malformed lockfile entries. **There is no schema validation.** |
| Parent process is interrupted (Ctrl+C / SIGINT) | `KeyboardInterrupt` propagates through `c.wait()` (line 1222) | Default Python behaviour: the SIGINT also reaches the child via the same controlling-terminal process group, so the child dies. Pipenv does not install an explicit signal handler; orphaned tempfiles in `/tmp/pipenv*` and `/tmp/resolver*.json` are not cleaned up. |
| Network failures inside the subprocess (pip fetch errors) | pip raises `InstallationError` in `Resolver.resolve` (`pipenv/utils/resolver.py:758`) | Wrapped in `ResolutionFailure` with formatted message from `_format_resolution_error` (`pipenv/utils/resolver.py:208–281`). Subprocess exits non-zero. Parent treats this the same as any other failure. |
| Subprocess imports fail (pip vendoring mismatch, missing `typing_extensions`) | `_ensure_modules()` (`pipenv/resolver.py:11–46`) attempts to fix `sys.path` and load `typing_extensions` defensively | If it fails, the subprocess raises an `ImportError` before reaching `main()` proper; non-zero exit follows.                                                          |
| Tempfile cleanup failure (race, disk full, permission) | `os.unlink(target_file.name)` at `pipenv/utils/resolver.py:1473–1477` | Wrapped in an `os.path.exists` check on the failure path; on the success path, the unlink runs unconditionally. Errors propagate. |

Two cross-cutting issues to flag for T_F.2:

1. **Orphaned tempfiles**. The success path unlinks `--write` and
   `--constraints-file` (the child unlinks the constraints file at
   `resolver.py:109`; the parent unlinks the write file at line 1477).
   The failure path leaves both behind under `/tmp`, since
   `tempfile.NamedTemporaryFile(delete=False)` is used.
2. **No timeout**. `c.wait()` is unbounded. A hung pip resolution
   (e.g. a dead network mirror, or a build-from-sdist that hangs)
   produces the user-visible symptom "pipenv hangs forever".

## 7. In-process call path

When `PIPENV_RESOLVER_PARENT_PYTHON` is truthy
(`pipenv/environments.py:430`), `venv_resolve_deps` short-circuits the
subprocess spawn and instead calls `resolver.resolve_packages` directly
in the parent interpreter (`pipenv/utils/resolver.py:1405–1428`).

- **When is this enabled?** Set the env var
  `PIPENV_RESOLVER_PARENT_PYTHON=1`. There is no Pipfile-level setting
  and no CLI flag. It is intended for **debugging only** — the comment
  at `pipenv/utils/resolver.py:1404` reads: *"Useful for debugging and
  hitting breakpoints in the resolver"*. Without it, `pdb.set_trace()`
  inside `actually_resolve_deps` fires inside a child interpreter that
  has no controlling terminal and so cannot accept input.
- **What changes structurally?** Nothing about the JSON shape — the
  same `process_resolver_results` runs and produces the same dicts.
  What's skipped is the argv-build, tempfile-write,
  `subprocess_run`, stderr/stdout reader-thread, and tempfile-read.
- **What is still serialized?** Nothing — the function call returns
  Python objects directly. The `write=False` argument
  (`pipenv/utils/resolver.py:1413`) suppresses the `json.dump` in
  `resolve_packages`.
- **Caveat.** The `temp_environ()` block at line 1360 still runs, so
  the same env-var dance happens. In particular,
  `PIPENV_RESOLVER_PYTHON_VERSION` is still set on `os.environ` — but
  the in-process branch separately enters `_patched_marker_environment`
  (line 1407) to apply the same patch. The subprocess relies on
  `_apply_python_version_override` (`pipenv/resolver.py:507–534`).
  Two different mechanisms, one effect. T_F.2 should pick one.

The in-process branch is **not** a "true" in-process path in the sense
of cleaning up the architecture — it is a debug bypass. Folding the
two paths together is the goal of T_F.4 / T_F.5 (per the modernization
PRD), not of T_F.1.

## 8. Divergent helpers between in-process and subprocess paths

The following pairs / clusters exist because the protocol grew
ad-hoc. Initiative F's downstream tasks will fold them.

| # | Divergence                                                                                             | In-process site                                              | Subprocess site                                          | Notes                                                                                                                                                          |
| - | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 | Python-version marker override                                                                         | `_patched_marker_environment()` context manager (`pipenv/utils/resolver.py:130–159`) | `_apply_python_version_override()` (`pipenv/resolver.py:507–534`) | Same effect — patch `pip._vendor.packaging.markers.default_environment`. One uses a context manager, the other monkey-patches at module load. Communication channel is `PIPENV_RESOLVER_PYTHON_VERSION` env var. |
| 2 | Mirror handling                                                                                        | Mirror is folded into `sources` before `resolve_deps` (parent reads `PIPENV_PYPI_MIRROR` via `_generate_resolution_cache_key`) | `resolve_packages` re-reads `PIPENV_PYPI_MIRROR` from env and re-applies via `create_mirror_source` + `replace_pypi_sources` (`pipenv/resolver.py:436–453`) | Two implementations of the same source-substitution; one in `pipenv/utils/sources.py`, one inline in `resolver.py`. Same env-var channel.        |
| 3 | Extra pip args                                                                                         | `Resolver.prepare_pip_args` reads `PIPENV_EXTRA_PIP_ARGS` env var (`pipenv/utils/resolver.py:487–490`) | Same path — `prepare_pip_args` is shared between both    | The env var is set by `venv_resolve_deps` (line 1383) *and* by `routines/update.py:652`. T_F.2 should pass this as a typed field, not an env var.            |
| 4 | Result-cleanup pipeline                                                                                | Returns from `Resolver.clean_results()` (`pipenv/utils/resolver.py:998–1037`) directly into the return value of `resolve_packages` | Same — `resolve_packages` is called in the subprocess too. *However*, the subprocess additionally runs `process_resolver_results` → `Entry.get_cleaned_dict` → `Entry.validate_constraints` (`pipenv/resolver.py:361–398`) on top of `clean_results`. | The `Entry` dataclass duplicates logic from `format_requirement_for_lockfile` (`pipenv/utils/locking.py:46`): both handle version normalization, marker merging, VCS dispatch, extras sorting. **Two competing requirement-output formats.** This is the single largest cluster to fold. |
| 5 | Sources read                                                                                           | `project.sources.pipfile_sources()` is consumed in-process by the parent before constructing `Resolver` | Subprocess constructs its *own* `Project()` and re-reads `pipfile_sources()` from disk (`pipenv/resolver.py:448–453`) | The subprocess does not receive sources over the wire; it re-discovers them. If the parent computed mirror-substituted sources, the subprocess re-substitutes via env-var. Same answer; redundant work. |
| 6 | `which` callable                                                                                       | Parent passes `project._which` into `resolve_deps`           | Subprocess defines its own `which(*args, **kwargs) -> sys.executable` (`pipenv/resolver.py:98–99`) | The subprocess's `which` is a stub that always returns `sys.executable`, because the subprocess *is* the target interpreter — there's nothing to look up. The parent has to do real lookup. Two unrelated signatures sharing a name. |
| 7 | Netrc credential injection                                                                             | `_set_resolver_netrc` (`pipenv/utils/resolver.py:1259–1266`) writes a temp netrc and exports `NETRC` | Subprocess inherits `NETRC` via `os.environ.copy()`      | No separate code path in the child — but the netrc tempfile lifetime is managed by `req_dir`, not by the subprocess boundary. Cleanup is implicit. |
| 8 | Resolved-default-deps marshaling                                                                       | Passed as a Python `dict` directly to `actually_resolve_deps` | Written to a temp JSON file, path passed via `--resolved-default-deps-file`, child `json.load`s and unlinks (`pipenv/resolver.py:122–129`) | Two encodings of the same data. T_F.2 should pick one.                                                                                                          |
| 9 | Constraints marshaling                                                                                 | In-process: `deps` (a `dict[name, pip-line]`) passed directly | Subprocess: written to `--constraints-file` as `<name>, <pip-line>` lines, child re-parses with `str.split(",", 1)` (`resolver.py:106–114`) | Custom line format with no escaping. Comma-in-pip-line would break it (rare but possible for some PEP 508 marker strings). T_F.2: fold into the typed request schema. |
| 10 | Verbose-logging level                                                                                  | Parent passes `project.s.is_verbose()` as a Python bool      | Subprocess receives `--verbose` argv flag, then `handle_parsed_args` re-exports `PIPENV_VERBOSITY` + `PIP_RESOLVER_DEBUG` to env (`resolver.py:102–105`) | Three serializations of one bit: CLI flag, two env vars, one method on `project.s`.                                                                            |

## 9. Decisions deferred to T_F.2

T_F.2 introduces a typed `ResolverRequest` / `ResolverResponse` pair.
Before that work begins, the following design questions need
answering. Each is annotated with the section above it derives from
and a tentative default if a strong preference doesn't surface.

1. **Schema definition format.** Should the typed schema be Python
   dataclasses (round-tripped via `dataclasses.asdict` and `json.dumps`),
   `TypedDict`, `pydantic.BaseModel`, or a JSON Schema declared
   externally? Default: stdlib `@dataclass` with manual JSON adapters,
   to avoid adding a runtime dep. The existing `PackageRequirement` /
   `Entry` dataclasses in `pipenv/resolver.py:149–223` are precedent.

2. **Versioning.** Should the protocol carry a `schema_version` field
   on the wire? If yes, what does the child do when it receives an
   unknown version? Default: yes, integer field, child rejects with
   exit code 2 if the major doesn't match. This is necessary for the
   "additive on the wire; old subprocess entrypoint stays valid for
   one release" mitigation called out in the PRD's risk table.

3. **Public-vs-internal.** Is `pipenv-resolver` a public protocol that
   external tools can drive directly, or strictly internal pipenv?
   This is open question #11 in the PRD. Default: internal-only, but
   the typed schema is exported under `pipenv.resolver.schema` so that
   downstream consumers *can* import and read it, even though pipenv
   doesn't commit to stability. (PRD §10 explicitly leaves this open.)

4. **Failure encoding.** The current protocol uses non-zero exit code
   as the sole failure indicator. Should the typed `ResolverResponse`
   include a `result: ResolverSuccess | ResolverFailure` discriminated
   union, written to the same `--write` file even on resolution failure
   (and exit 0)? This lets the parent distinguish
   "ResolutionImpossible" from "subprocess crashed" cleanly. Default:
   yes, but keep non-zero exit for genuine subprocess crashes
   (uncaught exception). Resolution-level failures become payload, not
   exit-code.

5. **Argument transport.** The current protocol mixes argv flags,
   tempfile contents, and environment variables for inputs. Should
   the typed `ResolverRequest` be written to a single tempfile and
   passed by `--request-file`, eliminating all the other channels?
   Default: yes. argv shrinks to `pipenv-resolver --request-file
   <path>`; all input goes through the typed request; env vars survive
   only for genuinely environment-scoped things (`PIP_NO_INPUT`,
   `NETRC`, `PYTHONIOENCODING`).

6. **Result transport.** Today the result is a JSON file at the path
   passed via `--write`. Should that stay (file-based) or move to
   stdout (pipe-based)? File-based is friendlier to large payloads
   and to debugging (the file persists). Pipe-based is one fewer
   tempfile to clean up. Default: keep file-based for results, but
   structure stdout for human progress (today stdout is largely
   silent, with download notices on stderr). T_F.2 may choose to add
   a `--progress-format=json` mode for parent-side streaming, but
   that's optional.

7. **Dead surface.** `--parse-only`, `--pipenv-site`, the positional
   `packages` argument, and the `which()` stub in `resolver.py:98–99`
   are dead. Are any of these reachable by third-party callers we
   should keep working through deprecation, or can T_F.2 remove them
   in the same PR? Default: remove. They're not in any documentation
   and they're shaped wrong for any sensible use.

8. **Two output formatters.** `Entry.get_cleaned_dict`
   (`pipenv/resolver.py:288–320`) and
   `format_requirement_for_lockfile` (`pipenv/utils/locking.py:46–
   160`) produce overlapping shapes from different inputs. The typed
   schema is an opportunity to collapse them. Default: pick
   `format_requirement_for_lockfile` as the canonical implementation
   (it has more thorough VCS / file / no-binary handling) and have
   `Entry` consume from its output instead of reimplementing. This is
   really the work of T_F.4 / T_F.5 but T_F.2's schema design should
   pick the format on day one.

9. **Marker-override channel.** The
   `PIPENV_RESOLVER_PYTHON_VERSION` env var is read by
   `_apply_python_version_override` in the subprocess. Should the
   typed `ResolverRequest` carry a `python_marker_override:
   Optional[str]` field and drop the env-var hop? Default: yes.

10. **Sources serialization.** The subprocess re-reads sources from
    Pipfile (`pipenv/resolver.py:448–453`) rather than receiving them
    from the parent. Should the typed `ResolverRequest.sources` carry
    the resolved, post-mirror-substitution source list, so the
    subprocess does no Pipfile parsing of its own? Default: yes. This
    eliminates an entire class of "parent and child disagreed about
    what the Pipfile said" bugs.

11. **Timeout.** Should the parent enforce a wall-clock timeout on the
    subprocess (with a reasonable default, e.g. 30 minutes)? Today
    there is no timeout — a hung mirror or hung sdist build hangs
    pipenv indefinitely (see §6). Default: yes, with a configurable
    `[pipenv].resolver_timeout` Pipfile setting. Strictly speaking
    this is a behaviour change, not a protocol change — but the
    protocol design should leave room for it.

---

*End of document. T_F.2 supersedes the ad-hoc protocol described here
with a typed `ResolverRequest` / `ResolverResponse` pair.*
