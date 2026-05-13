# Initiative F — Pluggable Resolver Backends Design (T_F.5a)

Status: **awaiting maintainer sign-off**. No code change under T_F.5
until this document is approved.

Companion documents:

- [`initiative-f-typed-design.md`](./initiative-f-typed-design.md) — the
  T_F.2 design that locked in the typed `ResolverRequest` /
  `ResolverResponse` envelope. §6a of that doc enumerates the four open
  questions this design must resolve.
- [`initiative-f-execution-plan.md`](./initiative-f-execution-plan.md) —
  the T_F.3 execution plan that just landed the typed schema.
- [`initiative-f-protocol.md`](./initiative-f-protocol.md) — the F.1
  catalogue of the historical ad-hoc protocol.
- [`modernization-prd.md`](./modernization-prd.md) § Initiative F for
  tone and acceptance-criteria framing.

## Table of contents

1. Summary
2. Scope
3. Proposed shape — the `Backend` protocol, registry, dispatch
4. Lockfile compatibility
5. Migration path from `origin/uv-backend`
6. Vendoring posture
7. Execution plan (T_F.5.1 … T_F.5.8)
8. Backwards compatibility
9. Open questions for maintainer sign-off
10. Acceptance criteria for T_F.5
11. Out of scope

---

## 1. Summary

Initiative F's T_F.3 introduced a backend-agnostic wire schema
(`pipenv/resolver/schema.py`). The §6a addendum to the T_F.2 design
recorded that the schema is "intentionally shaped so that a future
backend swap is not foreclosed" but explicitly deferred the questions
of *which backend*, *how a project opts in*, *how lockfiles are
discriminated*, and *whether uv is vendored*. A WIP branch
`origin/uv-backend` (commit `22359624`, 2025-12-14) has ~1260 lines of
exploratory code — `pipenv/utils/uv.py` (969 lines), `pipenv/routines/
lock.py` patches (176 lines), `pipenv/routines/install.py` patches (55
lines), `pipenv/environments.py` `PIPENV_USE_UV` env-var (10 lines) —
that prototypes the uv path *before* the typed schema landed.

This document specifies the T_F.5 architecture: a `Backend` protocol
implemented by `pipenv/resolver/backends/pip.py` (the current
behaviour, refactored from `pipenv/resolver/main.py`'s resolution call
chain) and `pipenv/resolver/backends/uv.py` (refactored from the WIP).
A registry in `pipenv/resolver/backends/__init__.py` selects the
backend by name; the name comes from a `[pipenv] resolver_backend`
field in Pipfile or a `--backend` CLI flag. The typed
`ResolverRequest` is the contract — every backend translates between
the schema and its native API internally.

pip remains the default and is the only backend whose dependency lives
inside `pipenv/vendor/`. uv is treated as an *external* dependency
discovered on `$PATH`; if absent, an informative error tells the user
how to install it. The lockfile format question is the most
substantive: this design **recommends** that the uv backend writes
`Pipfile.lock` (using the same `LockedRequirement → dict` adapter the
pip backend uses) with a `_meta.resolver_backend` discriminator,
**not** a parallel `pylock.toml` as the WIP does — see §4 and §9
question 3.

This is a design-only document. No production code changes. The 8
sign-off questions in §9 gate T_F.5 execution.

## 2. Scope

**In scope.**

1. A `Backend` protocol with `resolve(request: ResolverRequest) ->
   ResolverResponse` as its core method. Stdlib `typing.Protocol`,
   no abstract base class.
2. The `pipenv/resolver/backends/` subpackage layout reserved by
   T_F.2 §6a: `__init__.py` (registry), `pip.py` (current behaviour,
   the only required backend), and `uv.py` (optional, prototyped on
   `origin/uv-backend`).
3. Backend selection mechanism: Pipfile setting (`[pipenv]
   resolver_backend = "uv"`) + env-var override (`PIPENV_RESOLVER_
   BACKEND=uv`) + CLI override (`--backend uv`), with explicit
   precedence order.
4. Lockfile-side discrimination: a `_meta.resolver_backend` field that
   records which backend produced the lockfile, plus the policy for
   what happens when a Pipfile resolved by uv is later locked by pip
   (or vice versa).
5. Vendoring posture for uv: do **not** vendor; discover on `$PATH`
   with `shutil.which`; fail loudly if the configured backend isn't
   available rather than silently falling back.
6. Migration path from `origin/uv-backend`'s `pipenv/utils/uv.py` (the
   pre-typed-schema prototype) to the post-schema `pipenv/resolver/
   backends/uv.py` shape.
7. Execution plan splitting T_F.5 into eight sub-tasks (T_F.5.1 …
   T_F.5.8) suitable for the swarm-planner to expand into a parallel
   execution plan.

**Out of scope.**

- **T_F.4 — the in-process / subprocess fold.** Folding the two
  parent-side branches into one shared call site is a sibling task on
  the same branch and is being executed by a separate agent
  concurrently with this design. Backend dispatch happens *inside* the
  resolver call path, downstream of whichever branch dispatches it.
- **Additional backends.** Poetry's resolver, conda's solver, and any
  Rust/Go re-implementation are out of scope. The plugin point exists;
  designing for plurality past two backends is premature.
- **Schema-version bump.** The typed schema is already designed to be
  backend-agnostic; no `LockedRequirement` field changes are required
  to make backends work. Adding `LockedRequirement.resolver_backend`
  or `Diagnostics.resolver_name` is surfaced as §9 question 7.
- **External / public-tool exposure of the `Backend` interface.** Per
  T_C.3 §9 and T_E.1 §6 sign-offs, `pipenv.resolver.*` is internal.
  Third-party packages may not register backends; the `Backend`
  protocol is documented but not stabilized.
- **CLI-shape changes beyond a single new flag.** The new `--backend`
  flag is the only user-facing CLI surface change. `pipenv install`,
  `pipenv lock`, `pipenv update`, `pipenv sync` all keep their current
  argv shape.
- **Performance benchmarking.** Pipenv's slowness vs uv is a
  Rust-vs-Python gap (PRD §9). T_F.5 makes uv *available*; it does not
  attempt to measure or guarantee the speedup.
- **Vendoring uv.** Explicitly rejected — see §6.
- **Pipfile.lock format changes beyond an additive `_meta.resolver_
  backend` key.** No restructuring of the per-category entries; no
  removal of existing `_meta` keys.

## 3. Proposed shape — the `Backend` protocol, registry, dispatch

### 3.1 The protocol

`pipenv/resolver/backends/base.py`:

```python
from __future__ import annotations

from typing import Protocol

from pipenv.resolver.schema import ResolverRequest, ResolverResponse


class Backend(Protocol):
    """A resolver-backend implementation.

    Backends translate between the typed ``ResolverRequest`` envelope
    (the wire contract from T_F.3) and whatever native API they speak.
    The contract is purely schema-shaped — backends MAY NOT reach into
    pip-internal types via the schema; they may use them internally.
    """

    name: str
    """Registry key, e.g. ``"pip"`` or ``"uv"``."""

    def is_available(self) -> bool:
        """Return True iff this backend can actually run on this
        machine.  Pip is always available (vendored).  uv returns
        ``shutil.which("uv") is not None``.
        """

    def resolve(self, request: ResolverRequest) -> ResolverResponse:
        """Run resolution.  Return the typed response.

        The implementation is expected to honour every load-bearing
        field on ``request``: ``sources`` (with pipenv's index-
        restriction semantics), ``options.pre``, ``options.clear``,
        ``python_marker_override``, ``extra_pip_args`` (pass-through;
        non-pip backends translate a documented subset),
        ``resolved_default_deps``.

        Returns ``ResolverResponse(schema_version=SCHEMA_VERSION,
        result=...)`` with the result discriminated by ``kind``.  On
        resolution failure the backend constructs a
        ``ResolutionError``; the outer wire boundary at
        ``pipenv/resolver/main.py`` is unchanged.
        """
```

The protocol is stdlib `typing.Protocol`, not `abc.ABC`, so backends
can be plain modules that expose a module-level singleton without
subclassing ceremony. Structural typing also means an out-of-tree
third party could *implement* the protocol without importing pipenv —
but registering them is gated by the in-tree registry, so the public
exposure is bounded.

### 3.2 The registry

`pipenv/resolver/backends/__init__.py`:

```python
from __future__ import annotations

from typing import Mapping

from pipenv.resolver.backends.base import Backend
from pipenv.resolver.backends.pip import PIP_BACKEND
from pipenv.resolver.backends.uv import UV_BACKEND

_REGISTRY: Mapping[str, Backend] = {
    PIP_BACKEND.name: PIP_BACKEND,  # "pip"
    UV_BACKEND.name: UV_BACKEND,    # "uv"
}

DEFAULT_BACKEND_NAME = "pip"


def get_backend(name: str) -> Backend:
    """Look up a backend by registry key.

    Raises ``KeyError`` with a list of known names on miss.
    """
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(
            f"Unknown resolver backend {name!r}; known: {known}"
        )
    return _REGISTRY[name]


def list_backends() -> list[str]:
    """Return the sorted list of registered backend names."""
    return sorted(_REGISTRY)
```

Concrete, eager registry. No `entry_points` discovery, no plugin
hook. Adding a new backend requires editing this file in-tree — that
is the right level of friction for now (matches the no-public-API
posture). If we ever want third-party plugins, we add an
`entry_points` scan in a separate initiative.

### 3.3 Dispatch — where backend selection happens

Backend dispatch lives one layer above the resolver call path. The
parent-side caller (`pipenv/utils/resolver.py :: venv_resolve_deps`,
post T_F.4 fold) consults this order:

1. `--backend <name>` CLI flag, if present.
2. `PIPENV_RESOLVER_BACKEND=<name>` environment variable.
3. `[pipenv] resolver_backend = "<name>"` in Pipfile.
4. Default: `"pip"`.

The chosen backend's `is_available()` is checked **before** any
network I/O. If it returns `False` the user gets a clear error
pointing at how to install the missing backend (for uv: `pip install
uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`). No silent
fallback to pip — see §9 question 4.

The CLI flag is added on `pipenv install`, `pipenv lock`, `pipenv
update`, and `pipenv sync`. Other subcommands (`pipenv graph`, `pipenv
shell`, `pipenv run`, `pipenv check`) do not run resolution and are
not affected.

### 3.4 How the typed schema flows through each backend

The `Backend.resolve(request)` contract is the **only** schema
boundary. Backends are free to translate the request into their
native format internally:

- **pip backend** (`pipenv/resolver/backends/pip.py`) calls the
  existing in-subprocess `resolve_packages()` function from
  `pipenv/resolver/main.py`, which already accepts the typed
  `ResolverRequest` after T_F.3 (commit `d1563a1e`). The pip backend
  is therefore mostly a `Backend`-protocol shim around the existing
  resolver entry point. Its purpose in the registry is to make
  *dispatch* uniform, not to introduce new code.
- **uv backend** (`pipenv/resolver/backends/uv.py`) takes the typed
  request, generates a temporary `pyproject.toml` with `[[tool.uv.
  index]]` entries derived from `request.sources` and `[tool.uv.
  sources]` entries derived from `request.packages` (the
  index-restriction translation lives at lines 173-259 of
  `origin/uv-backend`'s `pipenv/utils/uv.py`), invokes `uv lock` in
  the tempdir (lines 261-371), parses the resulting `uv.lock`, and
  produces a `Sequence[LockedRequirement]` via a new
  `LockedRequirement.from_uv_package(...)` constructor that sits next
  to the existing `LockedRequirement.from_install_requirement(...)`
  in `pipenv/resolver/schema.py`. The output is wrapped in
  `ResolverSuccess(...)` and returned as a `ResolverResponse`.

Neither backend exposes pip-internal or uv-internal types on its
public method signatures. The schema module remains the contract.

### 3.5 Where each backend lives — the package layout

After T_F.3, `pipenv/resolver/` is:

```
pipenv/resolver/
├── __init__.py     # re-export shim, ~10 lines
├── main.py         # subprocess entry, ~700 lines
└── schema.py       # typed envelope, ~900 lines
```

After T_F.5 it becomes:

```
pipenv/resolver/
├── __init__.py
├── main.py         # subprocess entry, dispatches to backend
├── schema.py       # typed envelope (unchanged; possibly +1
│                   #   constructor for LockedRequirement.from_uv_package)
└── backends/
    ├── __init__.py # registry: get_backend(name), list_backends()
    ├── base.py     # Backend Protocol
    ├── pip.py      # the existing pip behaviour, as a Backend
    └── uv.py       # uv translation, refactored from
                    #   origin/uv-backend's pipenv/utils/uv.py
```

`pipenv/utils/uv.py` (the WIP location) **does not** become the home.
The schema lives under `pipenv/resolver/`; backends that consume the
schema live next to it. This co-location matches the §6a precedent
("`pipenv/resolver/backends/` subpackage layout").

### 3.6 The `Settings` integration

T_D.3 introduced `pipenv/utils/project_settings.py :: Settings` as the
canonical home for `[pipenv]`-section reads. The Pipfile field
`[pipenv] resolver_backend = "uv"` is added to `Settings` as a new
attribute `resolver_backend: str | None` (`None` meaning "use the
default"). The dispatch in §3.3 reads this attribute, not the raw
TOML, so it composes cleanly with the env-var and CLI overrides
`Settings` already handles.

The legacy `PIPENV_USE_UV` boolean env-var from `origin/uv-backend`'s
`pipenv/environments.py` line 377 is replaced by
`PIPENV_RESOLVER_BACKEND=uv` (a string, not a boolean). The boolean
shape forecloses future backends; the string shape generalizes.
`PIPENV_USE_UV` is **not** carried over as a compat alias — the WIP
never shipped, so nobody has it in production.

## 4. Lockfile compatibility

This is the most substantive design decision in T_F.5. The WIP's
choice (uv → `pylock.toml` only; pip → `Pipfile.lock`) is the most
visible difference between the WIP and what this design proposes.

### 4.1 The WIP's posture

`origin/uv-backend`'s `pipenv/routines/lock.py :: _do_lock_uv` writes
`pylock.toml` (PEP 751) and explicitly does **not** write
`Pipfile.lock`:

```python
# WIP, pipenv/routines/lock.py:65-72
if use_uv:
    # UV backend: resolve with UV and write pylock.toml only
    # (no Pipfile.lock)
    _do_lock_uv(...)
    # UV backend does not generate Pipfile.lock - only pylock.toml
    return None
```

The argued benefit: PEP 751 is the standardized cross-tool format;
emitting it makes pipenv lockfiles interoperable with other tools that
read `pylock.toml`.

The cost: every other pipenv subcommand (`install`, `sync`, `update`,
`graph`, `check`, `audit`) reads `Pipfile.lock` today. The WIP
silently breaks each one when uv is enabled, because the WIP simply
doesn't write `Pipfile.lock`. The integration tests on the WIP run
only `pipenv lock`, so the breakage is hidden.

### 4.2 The proposed posture

**Recommendation: both backends write `Pipfile.lock`.** Both backends
produce `Sequence[LockedRequirement]` per §3.4; the existing
`pipenv/utils/locking.py :: prepare_lockfile` consumer (which already
accepts `LockedRequirement` after T_F.3 commit `5e6eca82`) emits
`Pipfile.lock` unchanged.

Rationale: `Pipfile.lock` is what pipenv reads everywhere else.
Producing it from both backends keeps the rest of the codebase
backend-blind. The PEP 751 `pylock.toml` is a *future* output format
(see §11 — out of scope for T_F.5); when pipenv emits it, it should
do so from *both* backends, not as a uv-only quirk.

The `_meta` block grows a single new field:

```toml
[_meta]
hash = {...}
pipfile-spec = 6
requires = {...}
sources = [{...}, ...]
resolver_backend = "uv"    # NEW — additive; absent means "pip"
```

`resolver_backend` is absent on lockfiles produced before T_F.5 lands
and on lockfiles produced by the pip backend (per §9 question 5). Its
presence with value `"uv"` means "this lockfile was resolved by uv".
Pip-backend lockfiles can either omit the field or emit
`resolver_backend = "pip"` — see §9 question 5.

### 4.3 Cross-backend re-locking policy

What happens when a project resolved by uv is later locked by pip (or
vice versa)?

**Recommended policy (subject to §9 question 8):** re-resolve fully
under the new backend. The lockfile is treated as scratch input to
the resolver, not as state. The `_meta.resolver_backend` discriminator
is *informational only* — it does not gate behaviour. Reasons:

- Lockfile entries are tool-agnostic by construction
  (`LockedRequirement` is pip-free at the type level; uv's output is
  translated to the same shape).
- A user switching backends should get the same observable result as
  if they had checked out a fresh repo and run `pipenv lock` with the
  new backend. Anything more elaborate (warning, refusal, partial
  reuse) is policy that belongs to a later initiative.
- The hash check (`Pipfile.lock._meta.hash` vs the current Pipfile)
  already gates "is the lockfile valid for this Pipfile". The
  backend-discriminator is orthogonal.

The alternatives — refuse to operate on a uv-locked Pipfile when uv is
absent, or fall back to pip with a loud warning — are surfaced in §9
question 4.

### 4.4 Why not distinct lockfile filenames

`Pipfile.lock` (pip) vs `uv.lock` (uv) per-backend was considered and
rejected. Reasons:

- Doubles the surface area for every subcommand that reads a lockfile
  (`install`, `sync`, `update`, `audit`, `verify`, `graph`).
- Forces user-visible churn: tooling that watches `Pipfile.lock`
  changes (CI cache keys, dependency scanners) breaks silently when a
  project switches backends.
- The PEP 751 `pylock.toml` future-output format already has its own
  filename; adding `uv.lock` would create three lockfile filenames
  total.

Single-filename + `_meta` discriminator is the simpler shape. Surfaced
as §9 question 3.

## 5. Migration path from `origin/uv-backend`

The WIP commit `22359624` "WIP: Add UV backend for pipenv lock
command" (2025-12-14, pre-T_F.3) is the prior art. Its content
predates the typed schema; the T_F.5 migration is a refactor from
"untyped pipenv-utils-level helper" to "typed resolver-backends-level
backend".

### 5.1 File-by-file

**`pipenv/utils/uv.py` (969 lines) → `pipenv/resolver/backends/uv.py`.**
The translation is mostly mechanical:

| WIP function (line range) | T_F.5 destination |
|---|---|
| `is_uv_available` (lines 41-43), `get_uv_command` (lines 45-47) | `UV_BACKEND.is_available()` |
| `prepare_uv_source_args` (lines 50-105) | folded into the `pyproject.toml` generator |
| `prepare_uv_install_args` (lines 108-133) | helper retained but consumes `request.options` directly, not free-form kwargs |
| `build_index_lookup_from_lockfile` (lines 136-167) | unused under the new shape; `request.packages` already carries the per-package index |
| `generate_uv_pyproject_toml` (lines 173-259) | direct port; consumes `request.sources` and `request.packages` instead of free-form dicts |
| `uv_resolve_with_index_restriction` (lines 261-371) | core of `UV_BACKEND.resolve()`, refactored to return `LockedRequirement` instances |
| `uv_resolve_deps` (lines 374-490) | the per-index grouping logic is preserved; the requirements.txt output path is dropped (we go straight to `LockedRequirement` via `uv.lock` parsing) |
| `_pipfile_spec_to_requirement` (lines 493-525) | dropped; `request.packages.specs` already arrives as pip-line strings |
| `uv_pip_install_deps` (lines 528-700) | **deferred to a follow-up**. T_F.5 scopes the *resolve* path; the *install* path (using uv to download/install resolved deps) is a separate concern. See §11. |
| `_extract_package_name` (lines 703-740), `_strip_hashes` (lines 743-747) | dropped — install-path-only helpers |
| `uv_lock_to_pylock` (lines 749-825) | becomes `_uv_lock_to_locked_requirements()` private helper inside the uv backend; returns `Sequence[LockedRequirement]`, not a pylock dict. The PEP 751 path is dropped per §4. |
| `_convert_uv_lock_to_pylock` (lines 828-960) | dropped; replaced by `LockedRequirement.from_uv_package(...)` constructor in `pipenv/resolver/schema.py` |

**`pipenv/routines/lock.py` patches (176 lines diff) → discarded.** The
WIP's `do_lock(use_uv=...)` parameter plus the `_do_lock_uv` / `_do_
lock_pip` split is no longer needed: backend selection happens at the
resolver-call layer (§3.3), not at the routine layer. `do_lock` stays
backend-blind.

**`pipenv/routines/install.py` patches (55 lines diff) → discarded for
the resolve path.** The install-path patches (uv-based wheel
installation) are out of scope per §11.

**`pipenv/environments.py` `PIPENV_USE_UV` (10 lines) → renamed.**
Becomes `PIPENV_RESOLVER_BACKEND: str` per §3.6. Same `Settings`
plumbing.

**`pyproject.toml` `uv` test dependency (1 line) → kept as-is.** The
WIP added a `uv` dependency for tests. T_F.5 keeps this for the
integration-test path (which must actually exercise the uv backend),
but does **not** add `uv` to runtime dependencies — see §6.

**`tests/integration/conftest.py` (84 lines diff) → partially kept.**
The `--use-uv` pytest flag + the test compatibility layer is the
useful prior art. T_F.5 generalizes it to `--backend=uv` to mirror the
CLI flag, but the test fixture shape is essentially what the WIP had.

### 5.2 What the WIP got right that's worth preserving

- **Index-restriction translation** (`generate_uv_pyproject_toml`,
  lines 173-259): correctly encodes pipenv's index-restriction
  security model into uv's `[[tool.uv.index]]` + `explicit = true` +
  `[tool.uv.sources]` vocabulary. Not obvious from uv's docs; the WIP
  author got it right. T_F.5 preserves this logic verbatim (modulo
  the free-form dicts → typed `Source`/`PackageSpecs` plumbing).
- **Per-index resolution grouping** (`uv_resolve_deps`, lines
  376-456): uv's `first-index` strategy is not the same as pipenv's
  strict index-restriction; the WIP groups packages by their assigned
  index for independent resolve passes. T_F.5 preserves this even at
  N subprocess invocations for N indexes — correctness over speed.

### 5.3 What the WIP got wrong (or punted on)

- **No `Pipfile.lock` output.** §4 above is the long version; T_F.5
  routes uv's output through the same `LockedRequirement` →
  `Pipfile.lock` adapter the pip backend uses.
- **Silent fallback to pip when uv is missing** (`_do_lock` lines
  39-44). T_F.5 fails loudly — see §9 question 4.
- **`PIPENV_USE_UV` boolean.** §3.6 covered this.
- **Untested install path** (`uv_pip_install_deps`, lines 528-700):
  parallel implementation of `pipenv/utils/pip.py :: pip_install_deps`
  with no integration coverage on the WIP. T_F.5 scopes to
  resolve-only; install-path uv support is a future initiative.

### 5.4 What's worth flagging to the maintainer

The WIP predates T_F.3 and was built directly on
`venv_resolve_deps`'s untyped shape. About half its complexity
(free-form dict shuttling, per-call source-list reconstruction) is
obviated by the typed schema. T_F.5's port is materially smaller than
the 969-line WIP suggests — likely 400-500 lines of `backends/uv.py`
plus ~40 lines for the new `LockedRequirement.from_uv_package`
constructor. The WIP invokes `uv lock` inside a temp directory with a
generated `pyproject.toml`; T_F.5 reads the resulting `uv.lock` to
materialize `LockedRequirement` entries. None of those temp files
are exposed to the user — `Pipfile.lock` remains the only output.

## 6. Vendoring posture

**Recommendation: do not vendor uv. Accept system uv on `$PATH`.**

### 6.1 Rationale

- **Size.** uv is a 30-40MB Rust binary per platform. The current
  pipenv wheel is ~3MB; vendoring uv binaries for the five common
  platforms (linux-x64, linux-arm64, macos-x64, macos-arm64, win-x64)
  would push pipenv past 100MB. pip is vendored *because it's pure
  Python*; uv has no equivalent dimension to fit through.
- **Update cadence.** uv releases roughly weekly; pipenv's cadence is
  much slower. Vendoring would lock pipenv users to an arbitrarily
  old uv and force pipenv releases to chase uv's cadence. The
  vendor-only posture for pip works because pip's cadence is *slower*
  than pipenv's, not faster.
- **Provenance.** pip is shipped *inside* the source tree
  (`pipenv/patched/pip/`) and subject to pipenv's own patching. uv is
  a sealed external binary; it would land in `pipenv/vendor/` only by
  binary inclusion, which has no analog in pipenv's vendor sync.
- **Discovery is cheap.** `shutil.which("uv")` is < 1ms, runs once
  per resolve.

### 6.2 Detection and error path

`UV_BACKEND.is_available()` returns `shutil.which("uv") is not None`.
If the user requests the uv backend (via Pipfile, env, or CLI) and uv
isn't found:

```
$ pipenv lock --backend uv
Error: resolver backend 'uv' selected but uv was not found on $PATH.

Install uv via one of:
    pip install uv
    curl -LsSf https://astral.sh/uv/install.sh | sh
    brew install uv

Then re-run, or use --backend pip / unset PIPENV_RESOLVER_BACKEND to
use pipenv's default resolver.
```

Exit non-zero. No silent fallback to pip; see §9 question 4.

### 6.3 Version pinning of uv

Not in scope. T_F.5 accepts whatever `uv --version` is on `$PATH`. If
a future uv release breaks pipenv's translation of `request.sources`
into `[[tool.uv.index]]`, that's a bug to fix; we do not gate on
specific uv versions today. The first integration-test run on each
release pins the *behaviour* against whatever uv version is installed
in CI; if CI's uv changes, the tests catch the drift.

### 6.4 Contrast with pip's vendored posture

pip lives at `pipenv/patched/pip/` and `pipenv/vendor/`. The vendor
sync is the project's most-touched maintenance surface (PRD §1).
Vendoring uv would add to that burden with no payoff: pip is vendored
because pipenv *patches* it (the `_internal` fork); uv has no
patching need, just CLI invocation. pip is pure Python and trivially
redistributable; uv is a Rust binary with per-platform packaging.
This is an intentional divergence from "vendor everything" — uv is a
*peer tool* pipenv coordinates with, not a *library* pipenv builds on.

## 7. Execution plan (T_F.5.1 … T_F.5.8)

Sub-tasks suitable for a parallel-execution plan. Dependencies
expressed in the **depends_on** field of each task. The swarm-planner
skill will expand this into a wave-table once the design is signed
off.

### T_F.5.1 — `Backend` protocol + registry skeleton

- **depends_on**: []
- **Location**: NEW `pipenv/resolver/backends/__init__.py`,
  `pipenv/resolver/backends/base.py`.
- **What**: Declare the `Backend` protocol per §3.1. Add the
  registry per §3.2. **Do not** add `pip.py` or `uv.py` yet — they
  land in T_F.5.2 and T_F.5.3 respectively. The registry shipped in
  T_F.5.1 is empty; `list_backends()` returns `[]`.
- **Validation**: `python -c "from pipenv.resolver.backends import
  get_backend, list_backends; assert list_backends() == []"` passes.
- **Estimated diff**: ~80 lines new, 0 lines deleted.

### T_F.5.2 — Wrap the existing pip resolver as `pip` backend

- **depends_on**: [T_F.5.1]
- **Location**: NEW `pipenv/resolver/backends/pip.py`.
- **What**: Implement `PIP_BACKEND: Backend` whose `resolve(request)`
  calls the existing `pipenv/resolver/main.py :: resolve_packages` and
  wraps the return value in `ResolverResponse(... ResolverSuccess(...))`.
  Register it in `backends/__init__.py`. **No behaviour change** —
  this is purely a wrapper layer.
- **Validation**: Full unit and integration suite green; running
  `pipenv lock` with no `--backend` flag (and no env-var) goes
  through `PIP_BACKEND.resolve` and produces a byte-identical
  `Pipfile.lock` to the pre-T_F.5.2 baseline. Use the C2 wire-shape
  fixture from T_F.3 as the regression net.
- **Estimated diff**: ~100 lines new in `backends/pip.py`, ~20 lines
  modified in `pipenv/utils/resolver.py` (route through the registry).

### T_F.5.3 — `LockedRequirement.from_uv_package` constructor

- **depends_on**: [T_F.5.1]
- **Location**: `pipenv/resolver/schema.py` (one new classmethod on
  `LockedRequirement`).
- **What**: Constructor that consumes a `uv.lock` package entry (a
  dict of the shape uv emits — `name`, `version`, `source`, `wheels`,
  `sdist`, `dependencies`) and returns a `LockedRequirement`. This is
  the uv equivalent of the existing `from_install_requirement`.
- **Validation**: Unit test in `tests/unit/test_resolver_schema.py`
  parameterized over a fixture set of uv.lock package entries (PyPI,
  index-restricted, sdist-only, wheel-multi-arch, with markers, with
  extras). Each round-trips through `to_lockfile_dict()` and matches
  a committed golden.
- **Estimated diff**: ~40 lines added to `schema.py`, ~150 lines
  added to `tests/unit/test_resolver_schema.py`, fixtures in
  `tests/unit/fixtures/resolver_schema/uv_package/`.

### T_F.5.4 — Port `pipenv/utils/uv.py` to `pipenv/resolver/backends/uv.py`

- **depends_on**: [T_F.5.1, T_F.5.3]
- **Location**: NEW `pipenv/resolver/backends/uv.py` (~400-500 lines,
  refactored from `origin/uv-backend`'s 969-line `pipenv/utils/uv.py`
  per the §5.1 mapping table).
- **What**: Implement `UV_BACKEND: Backend`. `is_available()` checks
  `shutil.which`. `resolve(request)`:
  1. Generates a temp `pyproject.toml` (port of WIP lines 173-259).
  2. Runs `uv lock` (port of WIP lines 261-371).
  3. Parses the resulting `uv.lock` and materializes
     `LockedRequirement` instances via the T_F.5.3 constructor.
  4. Wraps in `ResolverSuccess` or `ResolutionError` and returns.
- **Validation**: Unit tests for index-restriction translation (the
  load-bearing part — §5.2). Integration test that runs `pipenv
  lock --backend uv` against a 3-package fixture Pipfile (PyPI +
  private index) and asserts the resulting `Pipfile.lock` is
  byte-identical to a committed golden (modulo `_meta.resolver_
  backend`).
- **Estimated diff**: ~450 lines new in `backends/uv.py`, ~80 lines
  of unit tests for the index-restriction logic.

### T_F.5.5 — Backend dispatch in `Settings` + `venv_resolve_deps`

- **depends_on**: [T_F.5.2, T_F.5.4]
- **Location**: `pipenv/utils/project_settings.py` (new attribute on
  `Settings`); `pipenv/utils/resolver.py` (dispatch logic);
  `pipenv/cli/options.py` and `pipenv/cli/command.py` (CLI flag).
- **What**: Add `Settings.resolver_backend: str | None` per §3.6 with
  the precedence order in §3.3. Add `--backend NAME` flag to the four
  affected subcommands. Route `venv_resolve_deps` through
  `get_backend(name).resolve(request)`.
- **Validation**: Unit test for `Settings.resolver_backend` reading
  from Pipfile / env / CLI. Integration smoke: `pipenv lock --backend
  pip` and `pipenv lock --backend uv` both produce valid lockfiles.
- **Estimated diff**: ~30 lines `Settings`; ~50 lines
  `venv_resolve_deps`; ~30 lines CLI; ~100 lines new tests.

### T_F.5.6 — `_meta.resolver_backend` lockfile discriminator

- **depends_on**: [T_F.5.5]
- **Location**: `pipenv/utils/locking.py :: prepare_lockfile` (or the
  `_meta` emitter — wherever `Pipfile.lock._meta` is constructed).
- **What**: When the lockfile is being written, set
  `_meta.resolver_backend = <name>` if the resolving backend is uv,
  or omit/set to `"pip"` per §9 question 5. **Additive only**: no
  existing `_meta` keys move.
- **Validation**: After `pipenv lock --backend uv`, the resulting
  `Pipfile.lock` parses with `_meta.resolver_backend == "uv"`. After
  `pipenv lock` (default), the field is absent or `"pip"` (per Q5).
- **Estimated diff**: ~15 lines `locking.py`; ~40 lines tests.

### T_F.5.7 — Missing-backend error path + tests

- **depends_on**: [T_F.5.5]
- **Location**: `pipenv/utils/resolver.py` (dispatch); fixture-level
  tests.
- **What**: When `Backend.is_available()` returns `False`, emit the
  error message in §6.2 and exit non-zero. No fallback. Add an
  integration test that simulates the missing-uv case (mock
  `shutil.which` to return `None`, run `pipenv lock --backend uv`,
  assert the error message and non-zero exit).
- **Validation**: New integration test green. Manual smoke:
  uninstall uv, run `pipenv lock --backend uv`, verify the message.
- **Estimated diff**: ~25 lines dispatch; ~60 lines tests.

### T_F.5.8 — Documentation + news fragment

- **depends_on**: [T_F.5.6, T_F.5.7]
- **Location**: NEW `docs/concepts/resolver_backends.md`; NEW
  `news/T_F.5.feature.rst`; update `docs/dev/initiative-f-typed-
  design.md` §6a to point at this document instead of carrying the
  open questions.
- **What**: User-facing doc explaining backend selection, the
  Pipfile field, the CLI flag, the missing-backend error path, and
  the lockfile discriminator. News fragment in the `.feature`
  category (this is a user-visible new capability, not a refactor).
- **Validation**: Doc builds, news fragment passes the towncrier
  lint, design-doc cross-reference is updated.
- **Estimated diff**: ~150 lines new docs; ~3 lines news; ~10 lines
  design-doc cross-reference update.

### Wave summary

| Wave | Tasks | Can start when | Parallelism |
|------|-------|----------------|-------------|
| A | T_F.5.1 | sign-off | 1 |
| B | T_F.5.2, T_F.5.3 | A complete | 2 |
| C | T_F.5.4 | B complete | 1 |
| D | T_F.5.5 | C complete | 1 |
| E | T_F.5.6, T_F.5.7 | D complete | 2 |
| F | T_F.5.8 | E complete | 1 |

Maximum concurrent agents: 2 (Wave B and Wave E).

## 8. Backwards compatibility

The CLI is the contract (per T_C.3 §9, T_E.1 §6, T_F.2 §5). T_F.5 adds
to the CLI surface; it does not change existing behaviour:

- **Default behaviour unchanged.** `pipenv install`, `pipenv lock`,
  `pipenv update`, `pipenv sync` with no new flag and no new Pipfile
  field continue to use the pip backend, which routes through the
  same `pipenv/resolver/main.py` code path as before T_F.5. The C2
  wire-shape regression fixture from T_F.3 protects against drift.
- **Existing `Pipfile.lock` files do not need migration.** A lockfile
  without `_meta.resolver_backend` is interpreted as
  pip-resolved. No prompt-to-relock, no warning.
- **`Pipfile` schema is additive.** `[pipenv] resolver_backend` is
  optional; absent means default. No existing `[pipenv]` field
  changes meaning.
- **No deprecated symbols.** The `Backend` protocol is new; there is
  nothing old to deprecate. `pipenv/resolver/backends/` is a new
  subpackage; `pipenv/utils/uv.py` (the WIP location) is never the
  canonical home, so there's no `uv.py` to deprecate either.
- **News fragment ships in T_F.5.8** in the `.feature` category. This
  *is* a user-visible feature addition: pipenv now has a documented
  backend selection mechanism and a uv backend.

The one place we *intentionally* break compatibility is with the WIP:
`PIPENV_USE_UV` is **not** carried forward as an alias for
`PIPENV_RESOLVER_BACKEND=uv`. The WIP never shipped in a release; no
user is depending on the env-var.

## 9. Open questions for maintainer sign-off

Numbered, in the shape of T_C.3 §7 / T_D.1 / T_E.1 §6 / T_F.2 §8
addenda. Each carries a recommendation; Matt's answer gates T_F.5
execution.

1. **Pipfile opt-in field — `[pipenv] resolver_backend` vs. new
   `[pipenv.resolver]` section vs. a `[tool.pipenv.resolver]` table
   for `pyproject.toml` future-proofing.** The proposal in §3.6 picks
   `[pipenv] resolver_backend = "<name>"` because the `[pipenv]`
   section already exists for `allow_prereleases`, `disable_pip_input`
   etc. — adding a new subsection just for the backend name is
   overkill. PRD §10 flags a future move to `[tool.pipenv]` in
   `pyproject.toml`; the field name `resolver_backend` survives such a
   move unchanged. **Recommendation:** `[pipenv] resolver_backend
   = "<name>"`. Confirm or override.

2. **CLI flag name — `--backend NAME` vs. `--resolver-backend NAME`
   vs. `--use-uv` (boolean).** The WIP went `--use-uv`; this design
   recommends `--backend NAME` (string-valued, generalizes past two
   backends). `--resolver-backend` is more explicit but verbose.
   **Recommendation:** `--backend NAME`. Confirm or override.

3. **Lockfile filename — single `Pipfile.lock` with `_meta.resolver_
   backend` discriminator vs. distinct `Pipfile.lock` (pip) +
   `uv.lock` / `pylock.toml` (uv).** This is the most substantive
   question. The §4 recommendation is single filename + `_meta` field,
   because the rest of pipenv reads `Pipfile.lock` unconditionally and
   splitting the filename creates downstream churn. The WIP went the
   other way (uv → `pylock.toml`). **Recommendation:** single
   `Pipfile.lock` for both backends; `_meta.resolver_backend` is the
   discriminator. PEP 751 `pylock.toml` is a separate future emit-also
   format (see §11 — out of scope). Confirm or override.

4. **Missing-backend behaviour — fail loud (recommended), silent
   fallback to pip (the WIP did this), or refuse to operate without
   explicit user action.** The §6.2 recommendation is "fail loud":
   if the user said `--backend uv` and uv is missing, error and exit
   non-zero. The WIP fell back silently to pip, which is debug-hostile.
   "Refuse to operate" (e.g. require the user to run `pipenv unset
   backend` or similar) is a more conservative third option. The
   re-locking corollary: a Pipfile resolved with uv whose
   `_meta.resolver_backend == "uv"`, run on a machine without uv —
   does pipenv error or fall back? **Recommendation:** error in both
   cases, with the error message in §6.2. Confirm or override.

5. **Pip-backend `_meta.resolver_backend` value — omit the field
   entirely vs. explicit `"pip"`.** Omitting keeps existing
   pip-produced lockfiles byte-identical to pre-T_F.5 lockfiles (no
   churn on first re-lock); writing `"pip"` is more explicit and
   makes the field always present. **Recommendation:** omit the field
   when the backend is pip; only the uv backend (and any future
   non-default backend) writes `resolver_backend`. This minimizes
   diff churn on existing projects' next `pipenv lock`. Confirm or
   override.

6. **Cross-backend re-lock policy — re-resolve fully (recommended) vs.
   refuse to re-lock under a different backend without explicit
   confirmation (`--allow-backend-switch` or similar).** §4.3
   recommends "re-resolve fully" (the simplest policy: treat the
   lockfile as input only). The alternative protects against silent
   drift when a CI pipeline runs `pipenv lock` with a different
   backend than the developer used. **Recommendation:** re-resolve
   fully; do not gate. The hash-mismatch path already protects against
   silent staleness. Confirm or override.

7. **Schema fields — add `LockedRequirement.resolver_backend: str |
   None`? Add `Diagnostics.resolver_name: str`?** The §1 framing says
   "no new schema fields without explicit sign-off". Both fields are
   plausible; neither is strictly needed. `LockedRequirement.
   resolver_backend` would let per-entry mixing (some entries
   resolved by uv, some by pip — not currently supported but
   future-possible). `Diagnostics.resolver_name` would expose which
   backend produced the response without the parent inspecting which
   backend it dispatched. **Recommendation:** add **neither** in
   T_F.5. The `_meta.resolver_backend` lockfile field is sufficient
   for the visibility need. Re-evaluate if a third backend lands.
   Confirm or override.

8. **Vendor uv or system uv.** §6 recommends *system uv* (do not
   vendor; discover with `shutil.which`). The contrast with the
   pip-is-vendored posture is justified in §6.4. **Recommendation:**
   system uv. Confirm or override.

9. **Test matrix expansion — every integration test runs twice (pip
   + uv) vs. a representative subset.** Pinning every integration
   test to both backends doubles CI runtime. Picking a representative
   subset (the lock/install/sync smoke tests, plus the index-
   restriction tests, plus VCS) keeps CI tractable. The WIP added a
   `--use-uv` pytest flag that runs the whole suite once with each
   backend; CI runs it twice. **Recommendation:** representative
   subset under the regular CI matrix; full dual-backend run on a
   nightly cron. Document the test selection in T_F.5.8's doc.
   Confirm or override.

10. **News-fragment category — `.feature` (recommended) vs.
    `.behavior` vs. split (one each).** T_F.5 is user-visible enough
    that `.feature` is appropriate (new CLI flag, new Pipfile field,
    new optional backend). `.behavior` would be wrong because nothing
    *existing* changed behaviour. Confirm or override.

## 10. Acceptance criteria for T_F.5

"Done" for T_F.5 means:

1. `pipenv/resolver/backends/` exists with `__init__.py`, `base.py`,
   `pip.py`, and `uv.py`. The four files load cleanly under Python
   3.10 (the minimum supported target).
2. `get_backend("pip")` and `get_backend("uv")` both succeed;
   `get_backend("unknown")` raises with a list of known names.
3. `pipenv lock` with no `--backend` produces a `Pipfile.lock`
   byte-identical to the pre-T_F.5 baseline (T_F.3's C2 wire-shape
   fixture passes unchanged).
4. `pipenv lock --backend uv` on a host with uv installed produces a
   valid `Pipfile.lock` (passes the existing lockfile-validation
   integration tests) with `_meta.resolver_backend == "uv"`.
5. `pipenv lock --backend uv` on a host *without* uv installed exits
   non-zero with the error message in §6.2.
6. `PIPENV_RESOLVER_BACKEND=uv pipenv lock` is equivalent to
   `pipenv lock --backend uv`.
7. `[pipenv] resolver_backend = "uv"` in Pipfile is equivalent to
   `--backend uv` (with CLI precedence — see §3.3).
8. The index-restriction security property is preserved under the uv
   backend: packages without an explicit `index` field are resolved
   *only* from the primary index, not from extra indexes. Pinned by
   an integration test that fails if uv is invoked without
   `[[tool.uv.index]] explicit = true` on non-primary sources.
9. `news/T_F.5.feature.rst` exists with a user-facing description of
   the new capability.
10. `docs/concepts/resolver_backends.md` exists and documents the
    Pipfile field, the env var, the CLI flag, and the lockfile
    discriminator.
11. The full unit suite is green. The full integration suite is
    green. Pipenv's existing CI matrix (Linux, macOS, Windows ×
    Python 3.10–3.14) does not regress.

## 11. Out of scope

- **uv as a wheel-install backend.** The WIP's `uv_pip_install_deps`
  (lines 528-700) replaces `pipenv/utils/pip.py :: pip_install_deps`
  for the install step. T_F.5 scopes to *resolve only*. Install-step
  uv support touches `routines/install.py`, `utils/pip.py`, hash
  verification, and the wheel cache — a separate future initiative.
- **PEP 751 `pylock.toml` output.** T_F.5 emits `Pipfile.lock` from
  both backends per §4. Optional `pylock.toml` emission (in addition
  to, not in place of) is a future feature. The schema's
  `LockedRequirement` carries enough information to drive one.
- **Backend plugins via entry-points.** The §3.2 registry is
  in-tree-only. Third-party plugin discovery via `importlib.metadata.
  entry_points` is a future initiative gated on a credible third
  backend appearing.
- **Poetry / conda / pdm backends.** Outside this initiative.
- **Performance benchmarking.** PRD §9. T_F.5 makes uv *available*;
  measuring its speedup is not a deliverable.
- **`Diagnostics.resolver_log` population from uv.** T_F.3 left this
  field reserved-but-empty (Q9). uv's verbose log could populate it,
  but that's a separate concern from getting the backend protocol
  right.
- **Conflict-record extraction from uv's stderr.** uv's failure
  messages are richer than pip's; parsing them into structured
  `ConflictRecord` instances is its own exercise. T_F.5's uv backend
  emits `ResolutionError(pip_message=<uv stderr>, conflicts=())` on
  failure — the human-readable string is preserved, the structured
  field is empty.
- **Subprocess-boundary collapse for the uv backend.** uv is itself
  a subprocess; T_F.5 keeps pipenv → `pipenv-resolver` → uv (two
  subprocess hops). Cutting the inner boundary for the uv backend
  (pipenv → uv directly) is a natural follow-up *after* T_F.4 lands
  the in-process / subprocess fold.

---

*Source of truth for the typed schema: T_F.2 / T_F.3
(`pipenv/resolver/schema.py`). Source of truth for the prior art:
`origin/uv-backend` commit `22359624`. Updates to this design or to
the schema should be made in lock-step.*
