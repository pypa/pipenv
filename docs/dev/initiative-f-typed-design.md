# Initiative F — Typed Resolver Subprocess Protocol Design (T_F.2)

Status: **awaiting maintainer sign-off**. No code change under T_F.3+
until this document is approved.

Companion to:
- [`initiative-f-protocol.md`](./initiative-f-protocol.md) — the 588-line
  catalogue of the *current* ad-hoc protocol. References below cite that
  doc's section / table / line numbers (abbreviated as "F.1 §X.Y").
- [`modernization-prd.md`](./modernization-prd.md) § Initiative F.

## 1. Summary

The current resolver subprocess protocol is a mix of argv flags, a
constraints tempfile, a write tempfile, six environment-variable
channels, an exit-code-as-failure-discriminator, and a top-level JSON
`list[dict]` with **no envelope, no version field, no success/failure
tag** (F.1 §5.1, §9 decision 4). Two separate output formatters —
`Entry.get_cleaned_dict` in the subprocess (`pipenv/resolver.py:288-320`)
and `format_requirement_for_lockfile` in the parent
(`pipenv/utils/locking.py:46-160`) — produce overlapping lockfile-shaped
dicts from different inputs, with subtle divergences in VCS, file, and
`no_binary` handling (F.1 §8 row 4, §9 decision 8). Resolution-impossible
errors and subprocess crashes are indistinguishable.

This document specifies the replacement: stdlib `@dataclass`-based
`ResolverRequest` / `ResolverResponse` types, an explicit
`schema_version` integer, a discriminated `success | error` result, a
single canonical `LockedRequirement` formatter shared by both sides of
the boundary, and a one-shot migration that drops the legacy
argv/env-var/tempfile channels in the same commit.

Per the T_C.3 §9 / T_E.1 §6 sign-offs ("CLI is the contract"), the typed
schema does **not** ship a backwards-compat shim. The protocol is
internal; only `pipenv-resolver` invoked from `pipenv` itself is a
supported caller.

## 2. Scope

**In scope.**

1. A versioned envelope: `ResolverRequest` and `ResolverResponse`, both
   carrying `schema_version: int` as the first field.
2. A discriminated result on `ResolverResponse`: success with locked
   entries vs. structured `ResolutionError` payload vs. `InternalError`
   for subprocess-level failures (uncaught exception).
3. A single canonical `LockedRequirement` dataclass that replaces both
   `Entry.get_cleaned_dict` and `format_requirement_for_lockfile` at the
   wire boundary.
4. Migration: removing dead argv flags (`--parse-only`, `--pipenv-site`,
   positional `packages`), folding the constraints tempfile and the
   resolved-default-deps tempfile into the typed request, and replacing
   `PIPENV_RESOLVER_PYTHON_VERSION` + `PIPENV_EXTRA_PIP_ARGS` env-var
   hops with typed request fields (F.1 §3.1–3.2).
5. Schema-versioning policy: how the schema version field is bumped,
   what the subprocess does on mismatch.

**Out of scope.**

- **CLI-shape changes.** The `pipenv install` / `pipenv lock` / etc.
  user-facing CLI does not move at all.
- **Performance optimizations.** Latency of subprocess startup and JSON
  round-trip is not a target. Today's profile is dominated by pip's
  resolve work, not by the wire format.
- **Eliminating the subprocess boundary.** Folding the in-process and
  subprocess paths into a single implementation is the work of T_F.4 /
  T_F.5. This design preserves the subprocess as a process boundary;
  it only types the contract that crosses it.
- **Wall-clock timeout.** F.1 §9 decision 11 flagged that
  `c.wait()` is unbounded. Adding a timeout is a behaviour change
  shipped separately; the schema design leaves room for a
  `request_metadata.deadline_seconds` field but T_F.3 does not enforce
  one.
- **External / public-tool exposure.** Per T_C.3 §9 / T_E.1 §6, the
  Python surface (including `pipenv.resolver.schema`) is internal. No
  semver guarantee, no `DeprecationWarning` on field renames.
- **`pipenv/patched/` and `pipenv/vendor/`.** Untouched. The typed
  schema lives in `pipenv/resolver/` (or `pipenv/utils/resolver_schema.py`
  — see §8 question 4) and consumes pip-internal types defensively.

## 3. Proposed shape

All types are `@dataclass(frozen=True)` from the standard library. No
new dependencies (per the user's no-new-vendored-deps rule). JSON
round-trip via a thin pair of `to_json_dict()` / `from_json_dict()`
classmethods, **not** via `dataclasses.asdict` — `asdict` recurses
through `Optional[dict]` fields in a way that breaks the discriminator
pattern.

### 3.1 Top-level envelope

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

# Current schema version. Bump on any breaking field rename or
# semantics change. Additive fields (with safe defaults) do not bump.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ResolverRequest:
    """The single input to a pipenv-resolver subprocess invocation.

    Replaces the current argv + env-var + constraints-tempfile +
    resolved-default-deps-tempfile cocktail (F.1 §3.1–3.2).
    """

    schema_version: int  # MUST be SCHEMA_VERSION. F.1 §9 decision 2.
    category: str        # Replaces --category (F.1 §3.1).
    packages: "PackageSpecs"  # Replaces --constraints-file (F.1 §3.1).
    options: "ResolverOptions"  # Replaces --pre / --clear / --system / --verbose.
    sources: Sequence["Source"]  # Replaces in-child Pipfile re-read (F.1 §8 row 5, §9 decision 10).
    python_marker_override: Optional[str] = None  # Replaces PIPENV_RESOLVER_PYTHON_VERSION (F.1 §9 decision 9).
    extra_pip_args: Sequence[str] = ()  # Replaces PIPENV_EXTRA_PIP_ARGS env var (F.1 §8 row 3).
    resolved_default_deps: Optional["ResolvedDeps"] = None  # Replaces --resolved-default-deps-file (F.1 §3.1, §8 row 8).
    metadata: "RequestMetadata" = field(default_factory=lambda: RequestMetadata())


@dataclass(frozen=True)
class ResolverResponse:
    """The single output written by pipenv-resolver to --response-file.

    Replaces the current top-level list[dict] payload (F.1 §5.1).
    """

    schema_version: int  # MUST be SCHEMA_VERSION.
    result: "ResolverResult"  # Discriminated union: see §3.2.
    diagnostics: "Diagnostics" = field(default_factory=lambda: Diagnostics())
```

`schema_version` is the **first** field on each envelope so a parent
that has not yet upgraded can read `json.load(...)["schema_version"]`
and decide whether to interpret the rest. The current absence of any
version field (F.1 §5.1) is the single biggest gap; this fixes it.

### 3.2 Discriminator: success vs. resolution error vs. internal error

The current protocol uses non-zero exit code as the sole failure
indicator and dumps free-text stderr for diagnostics (F.1 §4.3, §5.4).
The typed schema replaces this with a tagged union written to the
response file **even on resolution failure** (exit 0). Genuine
subprocess crashes (uncaught Python exceptions) still produce non-zero
exit and no response file — handled by the parent as before.

```python
from typing import Union


@dataclass(frozen=True)
class ResolverSuccess:
    """Resolution completed; lockfile entries follow."""

    kind: str  # Always "success". Discriminator field for JSON readers.
    locked: Sequence["LockedRequirement"]  # Replaces F.1 §5.2 list[dict].


@dataclass(frozen=True)
class ResolutionError:
    """The dependency set has no satisfying solution.

    Distinguishes user-actionable resolution failure from
    subprocess-internal failure. Today these are conflated under
    "non-zero exit + stderr text" (F.1 §4.3, §5.4).
    """

    kind: str  # Always "resolution_error".
    conflicts: Sequence["ConflictRecord"]  # Structured equivalent of pip's free-text "The conflict is caused by..." (F.1 §5.4).
    pip_message: str  # The pip-formatted human-readable message, preserved verbatim.


@dataclass(frozen=True)
class InternalError:
    """Subprocess hit an unexpected internal error (not a resolution
    failure). The parent typically also sees a non-zero exit and
    stderr traceback in this case; the structured payload is best-
    effort.
    """

    kind: str  # Always "internal_error".
    message: str
    traceback: Optional[str] = None  # Last-resort: full Python traceback.


ResolverResult = Union[ResolverSuccess, ResolutionError, InternalError]
```

JSON discriminator: each variant carries a literal `kind` string. The
`from_json_dict` classmethod on `ResolverResponse` dispatches on
`result["kind"]`. This is the same pattern T_C.3 §9.7 deferred but T_F.2
needs.

### 3.3 Canonical locked-requirement formatter (the fold-target)

This is the single largest fold in Initiative F (F.1 §8 row 4, §9
decision 8). Today two formatters produce overlapping shapes:

- `Entry.get_cleaned_dict` (`pipenv/resolver.py:288-320`) — runs in the
  subprocess, consumes the *post-resolve* dict that pip emits, drops
  `None` values, handles VCS via `Entry.requirement.source`.
- `format_requirement_for_lockfile` (`pipenv/utils/locking.py:46-160`)
  — runs in the parent, consumes an `InstallRequirement` plus a
  Pipfile-entries dict, has more thorough handling of: file/path with
  Pipfile-override semantics, `no_binary` propagation (line 156-157),
  direct-URL `pkg @ file://` (line 102-107), index lookup, marker
  merging via `merge_markers`.

The typed-schema replacement:

```python
@dataclass(frozen=True)
class LockedRequirement:
    """The canonical lockfile-entry shape.

    Each field corresponds 1:1 to a key in today's
    Entry.get_cleaned_dict output (F.1 §5.2 table). VCS-vs-non-VCS
    semantics are encoded as Optional[VCSPin]; the
    "either git/hg/svn/bzr or version, never both" invariant from
    F.1 §5.2 is enforced by __post_init__.
    """

    name: str                          # F.1 §5.2 "name". Always present.
    version: Optional[str] = None       # F.1 §5.2 "version". Required iff vcs is None.
    extras: Sequence[str] = ()          # F.1 §5.2 "extras". Empty tuple = omitted on wire.
    markers: Optional[str] = None       # F.1 §5.2 "markers".
    hashes: Sequence[str] = ()          # F.1 §5.2 "hashes". Sorted by caller.
    index: Optional[str] = None         # F.1 §5.2 "index".
    vcs: Optional["VCSPin"] = None      # F.1 §5.2 git/hg/svn/bzr + ref + subdirectory.
    file: Optional[str] = None          # F.1 §5.2 "file".
    path: Optional[str] = None          # F.1 §5.2 "path".
    editable: bool = False              # F.1 §5.2 "editable" (only emitted when True).
    no_binary: bool = False             # locking.py:156-157 (currently only on parent side).
    subdirectory: Optional[str] = None  # F.1 §5.2 "subdirectory" (also lives on VCSPin; here for file-mode).

    def __post_init__(self) -> None:
        if self.vcs is None and self.version is None and self.file is None and self.path is None:
            # The wire-shape invariant: every entry has at least one
            # of {version, vcs, file, path}. Bare-name entries are
            # rejected at the boundary.
            raise ValueError(f"LockedRequirement {self.name!r} carries no version, vcs, file, or path")
        if self.vcs is not None and self.version is not None:
            raise ValueError(f"LockedRequirement {self.name!r}: vcs and version are mutually exclusive (F.1 §5.2)")


@dataclass(frozen=True)
class VCSPin:
    """VCS pin: git/hg/svn/bzr URL + ref + optional subdirectory."""

    backend: str  # One of {"git", "hg", "svn", "bzr"}. F.1 §5.2.
    url: str
    ref: Optional[str] = None        # Commit hash / branch / tag.
    subdirectory: Optional[str] = None
```

**Canonical formatter strategy** (proposed answer to F.1 §9 decision 8):
neither `Entry.get_cleaned_dict` nor `format_requirement_for_lockfile`
survives as-is. They are **both** rewritten as thin adapters to a new
`LockedRequirement.from_install_requirement(req, *, sources_lookup,
markers_lookup, pipfile_entry, hashes) -> LockedRequirement`
constructor. The constructor lives next to `LockedRequirement` (likely
`pipenv/resolver/schema.py`). The richer behaviour from
`format_requirement_for_lockfile` (the file/path Pipfile-override,
direct-URL handling, `no_binary` propagation) is preserved; the simpler
`Entry`-style cleaning becomes a degenerate case. See §6.

### 3.4 Input types (request side)

```python
@dataclass(frozen=True)
class PackageSpecs:
    """The constraints-file content, typed.

    Today: comma-joined "<name>, <pip-line>" lines parsed with
    str.split(",", 1) (F.1 §3.1, §8 row 9 — flagged as fragile
    because pip-lines can contain commas in PEP 508 marker strings).
    Replacement: a typed mapping.
    """

    specs: dict[str, str]  # name -> pip-line (full pip install argument string).


@dataclass(frozen=True)
class Source:
    """One Pipfile [[source]] block, post-mirror-substitution.

    Replaces the in-subprocess Pipfile re-read at resolver.py:448-453
    and the duplicate mirror substitution at resolver.py:436-453
    (F.1 §8 row 2, row 5; §9 decision 10).
    """

    name: str
    url: str
    verify_ssl: bool = True


@dataclass(frozen=True)
class ResolverOptions:
    """Boolean / verbosity options that today are argv flags.

    Today: --pre, --clear, --system, --verbose (F.1 §3.1).
    """

    pre: bool = False
    clear: bool = False
    system: bool = False
    verbose: bool = False


@dataclass(frozen=True)
class ResolvedDeps:
    """The already-resolved default-category deps, used to constrain
    non-default categories. Today: written to a temp JSON file at
    --resolved-default-deps-file (F.1 §3.1, §8 row 8). Tracks gh-4665.
    """

    entries: Sequence[LockedRequirement]


@dataclass(frozen=True)
class RequestMetadata:
    """Caller-side context the subprocess may use for diagnostics.
    Strictly non-functional — none of these fields affects resolution.
    """

    pipenv_version: str = ""
    parent_pid: int = 0
    deadline_seconds: Optional[float] = None  # Reserved; T_F.3 will not enforce. See §2.
```

### 3.5 Diagnostics (response side)

```python
@dataclass(frozen=True)
class ConflictRecord:
    """One row of pip's 'The conflict is caused by' table.

    Today: free text only (F.1 §5.4). Structured here so the parent
    can format it without re-parsing pip's English.
    """

    package: str            # e.g. "foo"
    version: str            # e.g. "1.0"
    requires: str           # e.g. "shared>=3.0"


@dataclass(frozen=True)
class Diagnostics:
    """Side-channel info: warnings, timing, source-substitution log.
    The parent may surface these in --verbose mode; non-verbose
    callers ignore them.
    """

    warnings: Sequence[str] = ()
    elapsed_seconds: float = 0.0
    pip_version: str = ""
    resolver_log: Sequence[str] = ()
```

## 4. Migration path

Per the T_C.3 §9 / T_E.1 §6 sign-offs, backwards compatibility is **not
a goal**. The CLI is the only stable surface. The subprocess protocol
is an internal-only contract between the parent `pipenv` process and
the `pipenv-resolver` script it spawns — both shipped in the same
release. There is no scenario where a new parent invokes an old child
or vice versa across version boundaries; even if a user has two
pipenvs on `$PATH`, `pipenv-resolver` is invoked by absolute path
(`resolver.py:1431-1432` — `which("python", ...)` + `resolver.__file__`).

Therefore the migration is a **single PR** (T_F.3), not a phased rollout:

1. **Introduce** `pipenv/resolver/schema.py` with the dataclasses from
   §3.
2. **Rewrite** `pipenv/resolver.py` (the subprocess entry) to:
   - Accept `--request-file <path>` and **only** `--request-file`. Drop
     `--pre`, `--clear`, `--system`, `--verbose`, `--category`,
     `--constraints-file`, `--resolved-default-deps-file`,
     `--parse-only`, `--pipenv-site`, positional `packages`, and the
     `which()` stub at `resolver.py:90-91` (F.1 §3.1, §9 decision 7).
   - Read and validate the `ResolverRequest`; reject on schema-version
     mismatch with exit 2 (F.1 §9 decision 2).
   - Use `request.python_marker_override` directly instead of reading
     `PIPENV_RESOLVER_PYTHON_VERSION` (F.1 §9 decision 9).
   - Use `request.sources` directly instead of constructing `Project()`
     and re-reading the Pipfile (F.1 §8 row 5, §9 decision 10).
   - Write a `ResolverResponse` to `--response-file` on both success
     and resolution-error paths. Exit 0 in both cases. Internal errors
     attempt to write an `InternalError` response then exit non-zero.
3. **Rewrite** `pipenv/utils/resolver.py :: venv_resolve_deps()` and
   `resolve()` (lines 1180, 1282) to:
   - Build a `ResolverRequest` instead of an argv list + tempfiles.
   - Serialize to a single `--request-file` tempfile.
   - Call `subprocess_run(... ["--request-file", path])`.
   - Read `--response-file`; dispatch on `result.kind`.
   - Surface `ResolutionError` via the existing
     `ResolutionFailure`-aware code path; surface `InternalError` via
     the existing crash path. **Stderr free-text fallback is preserved**
     for the case where the subprocess truly crashes before writing a
     response file.
4. **Fold** `Entry.get_cleaned_dict` and
   `format_requirement_for_lockfile` into
   `LockedRequirement.from_install_requirement` per §3.3. The two old
   functions are deleted in the same PR. Callers that today receive
   `dict[str, Any]` lockfile entries now receive `LockedRequirement`
   instances; the lockfile writer
   (`pipenv/utils/locking.py :: prepare_lockfile`) gets a single
   `LockedRequirement.to_lockfile_dict()` adapter call site.
5. **Update** the env-var contract:
   - Keep: `PIP_NO_INPUT`, `NETRC`, `PIP_KEYRING_PROVIDER`,
     `PIP_DISABLE_PIP_VERSION_CHECK`, `PYTHONIOENCODING`,
     `PYTHONUNBUFFERED`, `PIPENV_PYPI_MIRROR` (still inherited via
     `os.environ.copy()` because pip-internal code reads it), the
     `PIP_*` family (pip configuration).
   - Drop the typed-request hops: `PIPENV_RESOLVER_PYTHON_VERSION`,
     `PIPENV_EXTRA_PIP_ARGS`, `PIPENV_SITE_DIR`. The subprocess stops
     reading them.
   - `PIPENV_VERBOSITY` and `PIP_RESOLVER_DEBUG` continue to be set by
     the subprocess on receipt of `request.options.verbose=True`, but
     they are no longer part of the *protocol* — they are pip's own env
     vars.
6. **Tests.** Per §7.

No deprecation shim, no protocol-version negotiation (the schema
*version* field exists for future expansion; T_F.3 ships with
`SCHEMA_VERSION = 1` and unknown versions are hard-rejected). News
fragment: "internal-only subprocess protocol rewritten; user-visible
behaviour unchanged."

The in-process branch (`PIPENV_RESOLVER_PARENT_PYTHON=1`, F.1 §7) is
preserved as-is: the same `resolve_packages()` function still runs in
the parent interpreter, just bypassing the JSON-round-trip. The typed
dataclasses are constructed and passed in Python directly — no
serialization. This is the simplest path; folding the two branches
together is T_F.4 / T_F.5 work.

## 5. Resolution of F.1's 11 deferred decisions

Each item below corresponds to a numbered question in F.1 §9.

1. **Schema definition format → stdlib `@dataclass`.** Adopt the F.1
   default. Plain `@dataclass(frozen=True)` with manual
   `to_json_dict` / `from_json_dict` classmethods. **No** pydantic, no
   msgspec, no attrs (per user's no-new-deps rule, and consistent with
   `Entry` / `PackageRequirement` precedent at `resolver.py:121-156`).
   Validation is by `__post_init__` (see §3.3 `LockedRequirement`).
2. **Versioning → integer `schema_version: int = 1`.** First field on
   both envelopes. Mismatch is a hard reject by the child (exit 2);
   the parent gets a structured `InternalError` if it can be written,
   otherwise the non-zero exit + stderr fallback path engages.
   Additive fields with safe defaults do **not** bump; only
   field-rename or semantics-change does. Per §4: no protocol-version
   negotiation, because parent and child always ship together.
3. **Public-vs-internal → internal-only.** Consistent with T_C.3 §9
   and T_E.1 §6: pipenv's only stable API is the CLI. The schema
   lives in `pipenv/resolver/schema.py` (or `pipenv/utils/
   resolver_schema.py` — §8 question 4) and is **not** documented for
   external consumers. The PRD §10 open question is resolved as
   non-goal: external tools that import the schema do so at their own
   risk; field-rename PRs do not run a deprecation cycle.
4. **Failure encoding → discriminated `ResolverResult` union written
   to the response file on exit 0.** See §3.2. Exit-non-zero is
   reserved for genuine subprocess crash (Python uncaught exception,
   SIGSEGV, OOM-kill, schema-version mismatch). The parent's
   `c.returncode != 0` path still triggers `ResolutionFailure`, but it
   becomes the rare path; the common "user has conflicting deps" path
   becomes structured `ResolutionError`.
5. **Argument transport → single `--request-file <path>`.** All argv
   inputs and three of the env vars
   (`PIPENV_RESOLVER_PYTHON_VERSION`, `PIPENV_EXTRA_PIP_ARGS`,
   `PIPENV_SITE_DIR`) fold into the typed request. Surviving env vars
   are *environment-scoped* (pip configuration, IO encoding, netrc
   path) and stay because they have no caller — pip-internal code
   reads them via `os.environ` directly.
6. **Result transport → keep file-based; one tempfile for response.**
   Stdout stays human (the parent's existing `_is_download_status_line`
   pattern at `pipenv/utils/resolver.py:1159-1177` still works; the
   subprocess emits nothing structured to stdout). The
   `--progress-format=json` mode floated in F.1 §9 is deferred — the
   typed schema does not preclude it but T_F.3 does not implement it.
7. **Dead surface → delete.** `--parse-only`, `--pipenv-site`,
   positional `packages`, and `which()` stub all go away in T_F.3.
   None are documented; none have plausible external callers; the
   shapes are wrong for any sensible use (F.1 §3.1).
8. **Two output formatters → fold into `LockedRequirement` with a
   single `from_install_requirement` constructor.** See §6 below for
   the detailed rationale. Both old functions are deleted in T_F.3.
9. **Marker-override channel → typed field
   `ResolverRequest.python_marker_override: Optional[str]`.** The env
   var hop disappears. The subprocess no longer reads
   `PIPENV_RESOLVER_PYTHON_VERSION` from `os.environ`; it consumes
   `request.python_marker_override` and calls
   `_apply_python_version_override(override_str)` with the string
   argument.
10. **Sources serialization → `ResolverRequest.sources: Sequence[
    Source]`.** Pre-mirror-substituted by the parent. The subprocess
    stops constructing `Project()` and stops calling
    `pipfile_sources()` / `create_mirror_source` /
    `replace_pypi_sources` internally (F.1 §8 row 2, row 5;
    `resolver.py:420-425, 436-453`). One source of truth.
11. **Timeout → reserved field, not enforced in T_F.3.**
    `RequestMetadata.deadline_seconds: Optional[float] = None` exists
    on the wire. T_F.3 does not implement enforcement (no `c.wait(
    timeout=...)`). The behaviour change of "pipenv subprocess can be
    killed after N minutes" is left for a separate small PR with its
    own news fragment, since it changes user-visible behaviour
    (currently-hanging installs will start dying instead of hanging
    forever). The protocol design *allows* it without further
    schema changes.

## 6. Resolution of the two-competing-formatters issue

F.1 §8 row 4 and §9 decision 8 flagged this as the single largest fold
in Initiative F. The proposal in F.1's default ("pick
`format_requirement_for_lockfile` as canonical, have `Entry` consume
from its output") is **not** what this design adopts. The reason: both
functions have the wrong **input** shape for the cross-cutting use case.

- `Entry.get_cleaned_dict` consumes a `dict[str, Any]` returned by the
  upstream resolver. It runs in the subprocess only.
- `format_requirement_for_lockfile` consumes an `InstallRequirement`
  plus a `pipfile_entries: Dict[str, Any]`. It runs in the parent
  only, after `Resolver.clean_results()`.

The typed-schema work needs to **produce** a `LockedRequirement` from
both sides:

- Subprocess side: the resolver produces an `InstallRequirement`
  internally during `Resolver.resolve()`. The same
  `InstallRequirement`-to-`LockedRequirement` conversion that the
  parent today does in `format_requirement_for_lockfile` can run in
  the subprocess. `Entry.get_cleaned_dict`'s dict-cleaning logic
  becomes unnecessary because the wire format is no longer a stripped
  dict — it's a typed `LockedRequirement`.
- Parent side: when the parent does its own
  `actually_resolve_deps()` call in the in-process branch
  (F.1 §7), it also has `InstallRequirement` objects. Same constructor.

**Conclusion.** Adopt a *third* unified replacement
(`LockedRequirement.from_install_requirement`) that lives in the
schema module. It absorbs the richer behaviour from
`format_requirement_for_lockfile` (file/path Pipfile-override at
`locking.py:142-154`, direct-URL handling at lines 110-116,
`no_binary` propagation at lines 156-157, `merge_markers` at lines
121-131, index lookup at lines 117-119) and the
`_clean_version` / `_clean_markers` logic from `Entry`
(`resolver.py:213-245`). The result is **one** function with one input
type (`InstallRequirement`) and one output type
(`LockedRequirement`). Both `Entry.get_cleaned_dict` and
`format_requirement_for_lockfile` are deleted in T_F.3.

`prepare_lockfile` at `pipenv/utils/locking.py:195` becomes the
`LockedRequirement.to_lockfile_dict()` consumer — one place where
typed data turns into TOML-ready dicts.

## 7. Test plan

The current resolver subprocess has no protocol-level test coverage:
the unit tests at `tests/unit/test_resolver_regressions.py` exercise
the in-process `Resolver` class but never construct or assert against
the subprocess JSON shape, and the integration tests treat the
subprocess as a black box (assert on installed packages, not on wire
format). T_F.3 ships with the following pinning coverage in the same
PR:

1. **Unit tests for the dataclasses.** New file
   `tests/unit/test_resolver_schema.py`:
   - `LockedRequirement.__post_init__` rejects (a) no version + no
     vcs + no file + no path, (b) version-and-vcs both present.
   - `LockedRequirement.from_install_requirement` reproduces today's
     `Entry.get_cleaned_dict` output on a fixture set of resolved
     dicts (snapshot test). Today's `format_requirement_for_lockfile`
     output likewise (parameterized; the same fixture set runs against
     both source paths).
   - `ResolverRequest.to_json_dict` / `from_json_dict` round-trip is
     lossless for at least one fixture per field (pre, clear, system,
     verbose, marker override, extra pip args, resolved-default-deps,
     each VCS backend).
   - `ResolverResponse` discriminator dispatches correctly for each
     of the three `result.kind` values; unknown `kind` raises.
   - Schema-version mismatch raises a typed error.
2. **Integration test pinning the JSON wire shape.** New file
   `tests/integration/test_resolver_protocol.py`. Run an actual
   `pipenv lock` against a tiny known Pipfile, intercept the
   request-file and response-file before they are cleaned up, snapshot
   them, and diff against committed fixture JSON. This is the canary
   for any accidental wire-shape regression — any PR that changes a
   field name without bumping `SCHEMA_VERSION` will fail this test.
3. **Existing integration suite stays green.** The full
   `pytest tests/integration` run is the acceptance gate for T_F.3, as
   for every prior initiative.

Pinning the JSON wire shape is explicitly **not** a backwards-compat
gate — the fixture exists to make wire-shape changes a deliberate,
diff-visible decision, not to prevent them. The maintainer can update
the fixture in the same commit as a schema bump.

## 8. Open questions for maintainer sign-off

Numbered, in the shape of the T_C.3 §7 / T_D.1 / T_E.1 §6 addenda.
Matt's answers gate T_F.3 execution.

1. **Schema home — `pipenv/resolver/schema.py` vs.
   `pipenv/utils/resolver_schema.py`?** Today `pipenv/resolver.py` is
   the *file*, not a package; the subprocess entry has historically
   been a single module. Moving it to a package
   (`pipenv/resolver/__init__.py` + `pipenv/resolver/schema.py` +
   `pipenv/resolver/main.py`) is the cleanest layout, but touches the
   `pyproject.toml` console-script entry
   (`scripts.pipenv-resolver = "pipenv.resolver:main"`).
   Alternative: keep `pipenv/resolver.py` as the script, put schema in
   `pipenv/utils/resolver_schema.py`, accept the cross-module reach.
   **Recommendation:** turn `pipenv/resolver.py` into a package; the
   console-script line becomes
   `"pipenv.resolver.main:main"`. Confirm or override.
2. **Schema version on mismatch — exit 2 vs. write an
   `InternalError` response?** F.1 §9 decision 2's default was "exit
   2". The cleaner protocol-level answer is "write
   `InternalError(message='schema version mismatch: parent sent N,
   child expects M')` to `--response-file`, exit 0". The latter gives
   the parent a structured failure even on protocol breakage; the
   former is simpler. **Recommendation:** write structured response
   *and* exit non-zero (the only failure path that exits 0 is
   `ResolutionError`, which is user-actionable; everything else
   exits non-zero so callers / CI / wrappers see failure). Confirm or
   override.
3. **`LockedRequirement.to_lockfile_dict` — does it produce a TOML-
   ready dict or a Plette `Lockfile` entry?** Today
   `prepare_lockfile` accepts plain dicts (`locking.py:195-204`).
   `LockedRequirement.to_lockfile_dict()` could either preserve that
   dict shape (lower friction, no Plette knowledge in schema) or
   produce a Plette entry directly (less downstream conversion).
   **Recommendation:** plain dict. The schema module should not
   import Plette. Confirm or override.
4. **News fragment for T_F.3 — required, or skip?** The protocol is
   internal; the only user-visible diff is the cleaner error message
   on resolution conflicts (structured `ResolutionError` vs.
   free-text). T_C.4 / T_D.3 / T_E.2 each shipped a news fragment;
   T_F.3 could either follow suit (one-line news entry: "Resolver
   subprocess now produces structured error messages on dependency
   conflicts") or skip (it's an internal-only refactor).
   **Recommendation:** ship a news fragment, single line, type
   `behavior` — the structured error path *is* a user-facing
   improvement even though the protocol isn't documented. Confirm or
   override.
5. **`no_binary` field on `LockedRequirement` — keep, or compute on
   read?** Today `format_requirement_for_lockfile` writes
   `entry["no_binary"] = True` when the Pipfile entry has
   `no_binary` (`locking.py:156-157`), and `Entry.get_cleaned_dict`
   does **not** emit it. The fold replaces both; whether
   `LockedRequirement` carries `no_binary` as a first-class field or
   recomputes it from the Pipfile at lockfile-write time is a design
   question. The §3.3 proposal includes the field for parity with
   today's parent-side behaviour. **Recommendation:** keep as a
   field; one less Pipfile re-read at lockfile-write time.
   Confirm or override.
6. **In-process branch fold — does T_F.3 do it, or strictly T_F.4?**
   This proposal preserves the in-process branch
   (`PIPENV_RESOLVER_PARENT_PYTHON=1`, F.1 §7) untouched in T_F.3.
   Folding the two branches together (one resolver implementation,
   two thin adapters per the PRD acceptance criteria) is the work
   of T_F.4 / T_F.5. **Question:** is it acceptable for T_F.3 to ship
   without that fold, leaving the debug-bypass branch in place?
   **Recommendation:** yes, ship without the fold. The typed schema
   is the prerequisite; the fold is the next task in line.
   Confirm or override.
7. **Constraints-file comma-escape bug — fix in T_F.3 by virtue of
   the typed dict, or call out as separate?** F.1 §8 row 9 flags
   that `<name>, <pip-line>` lines with commas inside the pip-line
   (e.g. PEP 508 markers with comma-separated conditions) break the
   parser. The typed schema fixes this for free
   (`PackageSpecs.specs: dict[str, str]`). **Question:** do we want a
   regression test pinning the comma-in-marker case to prevent
   re-regression if the protocol ever gets refactored back to
   line-based parsing? **Recommendation:** yes, add one fixture in
   the §7 unit suite with a marker containing a comma.
   Confirm or override.
8. **Schema-versioning policy on field additions — non-breaking by
   default, or always bump?** The proposal says additive fields with
   safe defaults do **not** bump `SCHEMA_VERSION`. The alternative is
   "any change bumps". The former is more permissive (less churn);
   the latter is more defensive (every protocol change is visible at
   `git blame schema.py` on the version constant). **Recommendation:**
   non-breaking by default. Pipenv ships parent and child together;
   the schema version's job is to fail loudly when an unrelated tool
   (or an out-of-tree fork) connects to `pipenv-resolver` with the
   wrong shape — not to gate routine internal refactors.
   Confirm or override.
9. **`Diagnostics.resolver_log` and stderr handling — both, or one?**
   Today stderr is the only log channel
   (`pipenv/utils/resolver.py:1200-1210`). The proposal adds
   `Diagnostics.resolver_log: Sequence[str]` as a structured side
   channel. **Question:** do we want both (stderr free-text continues
   to flow for `--verbose`, *and* the structured log lands on the
   response), or strictly one? **Recommendation:** keep stderr as the
   user-facing channel (the `_is_download_status_line` filter at
   `pipenv/utils/resolver.py:1159-1177` is well-tuned and depends on
   line-streaming, which JSON-over-file can't match). The structured
   `resolver_log` is **reserved but unpopulated** in T_F.3 — exists
   on the schema for future use, child writes empty tuple.
   Confirm or override.
10. **Tempfile lifetime — keep two tempfiles (request + response), or
    consolidate?** Today there are up to three tempfiles
    (`--write`, `--constraints-file`, `--resolved-default-deps-file`).
    The proposal collapses to two (`--request-file`, `--response-file`).
    A further consolidation is "the subprocess writes its response
    back to the *same* file the request was read from, after reading
    and truncating" — one tempfile total. **Recommendation:** two
    tempfiles. The request file should remain readable post-mortem
    for debugging (the F.1 §6 "orphaned tempfile" concern is now an
    asset, not a bug — but only if request and response are
    separable). Confirm or override.

---

*Source of truth for the current protocol: F.1
([`initiative-f-protocol.md`](./initiative-f-protocol.md)). Updates to
this design or to F.1 should be made in lock-step.*
