# Initiative B Triage: `pipenv/utils/requirements.py`

Per-function audit of the 395-line module. Caller counts are external
call sites only (the symbol's own definition and intra-module helper
calls are excluded). Greps were run across `pipenv/`, excluding
`pipenv/patched/` and `pipenv/vendor/`.

Reproduce a count with, e.g.:

```
grep -rn "normalize_name" pipenv/ --include="*.py" \
  | grep -v pipenv/patched/ | grep -v pipenv/vendor/
```

## Function table

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

## The `normalize_name` / `pep423_name` overlap (flag for Initiative E)

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

## Why we don't just `from pip._internal.utils.misc import redact_*`

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

## Summary

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
