# Initiative C — `RoutineContext` Design Proposal (T_C.3)

This document proposes the shape of the typed `RoutineContext` dataclass
that Initiative C task `T_C.4` will introduce into `pipenv/routines/`.
It is sourced directly from the parameter inventory captured in
[`initiative-c-params.md`](./initiative-c-params.md) (240 parameter
rows across 23 in-scope routines and helpers). It is awaiting
maintainer sign-off before any production code changes land.

The proposal is intentionally conservative: it groups together only the
parameters the inventory shows travel together as a coherent packet
across multiple routines. Per-routine workflow plumbing
(`lockfile`, `procs`, `reverse_deps`, `requested_packages`, etc.) is
explicitly kept out — see section 3.

## 1. Summary

`RoutineContext` is an immutable (frozen) dataclass that bundles the
inputs to pipenv's user-facing routines — the same inputs that today
arrive at `do_install`, `do_update`, `do_uninstall`, `do_lock`,
`do_sync`, and friends as 9–17 separate keyword arguments. It is
composed of four nested frozen dataclasses
(`TargetEnv`, `InstallPolicy`, `PackageSelection`, `ExecutionOptions`)
that correspond directly to the four largest semantic groups identified
in `T_C.2`'s inventory (`target_env`, `install_policy`,
`package_selection`, `execution_options` — 50/36/54/57 rows
respectively, ~80% of the 240-row total).

**Problem solved.** Routine signatures today copy the same 10+
parameters through three call frames (CLI → `do_install` → `do_init` →
`do_install_dependencies`); each step is an opportunity to drop a flag
or pass `pypi_mirror=False` instead of `pypi_mirror=None`.
`RoutineContext` makes that bundle a single typed value that flows
through the call chain unchanged unless a routine explicitly intends
to mutate it (via `dataclasses.replace`).

**In scope.** The 197 parameter rows across the four semantic groups
above. The dataclass is the *input* contract for user-facing
dependency-management routines.

**Out of scope.** The `state_flags` (9 rows) and `other` (34 rows)
groups remain as explicit call-site arguments; see section 3.
`Project` stays as a separate first positional argument to every
routine (it carries its own lifecycle and is not just a bundle of
flags). Routines explicitly excluded by the `T_C.2` task spec
(`do_shell`, `do_run`, `do_clean`, `do_graph`) are also out of scope
for this dataclass.

## 2. Proposed dataclass shape

```python
"""Routine-context dataclass for pipenv.routines.

Bundles the user-facing inputs that travel together across the
install / update / lock / sync / uninstall call chains. See
docs/dev/initiative-c-design.md for rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional, Sequence


@dataclass(frozen=True)
class TargetEnv:
    """Which Python and where to install.

    Sourced from the `target_env` semantic group in T_C.2 (50 rows).
    Every routine but the arg-builders carries `pypi_mirror` and
    `system`; most carry `python` and a subset carry `site_packages`
    and `allow_global`.
    """

    system: bool = False
    allow_global: bool = False
    python: Optional[str] = None
    pypi_mirror: Optional[str] = None
    site_packages: Optional[bool] = None


@dataclass(frozen=True)
class InstallPolicy:
    """Flags governing install / lock behaviour.

    Sourced from the `install_policy` semantic group in T_C.2 (36
    rows). These flags travel as a packet through the
    install / init / lock chain.
    """

    pre: bool = False
    deploy: bool = False
    skip_lock: bool = False
    ignore_pipfile: bool = False
    clear: bool = False
    lock_only: bool = False
    lock: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class PackageSelection:
    """Which packages a routine should act on.

    Sourced from the `package_selection` semantic group in T_C.2 (54
    rows). The trio (packages, editable_packages, categories) appears
    verbatim in do_install / do_update / do_uninstall / upgrade and
    in five helpers.

    Notes on aliases / collapses:
    * `pipfile_categories` and `categories` collapse into one field
      (`categories`). T_C.2 observation 2 calls out that these two
      names co-exist in update.py with translation helpers; the
      dataclass picks one and the translation moves into either
      `from_cli` or a derived property.
    * `index_url` and `index` (used by `do_update` / `upgrade` vs
      `do_install`) collapse to `index`.
    * `package_args` (the helper-internal combined positional +
      editable list) is *not* a field; it is derived inside the
      routine as `tuple(packages) + tuple(editable_packages)` and is
      a property on `PackageSelection`.
    * The `all` / `all_dev` / `dev_only` flags are uninstall-specific
      and live on `PackageSelection` only because they are
      semantically about "which packages to remove"; an alternative
      placement is discussed in section 7.
    """

    packages: Sequence[str] = ()
    editable_packages: Sequence[str] = ()
    categories: Sequence[str] = ()
    dev: bool = False
    dev_only: bool = False
    all: bool = False
    all_dev: bool = False
    index: Optional[str] = None
    index_name: Optional[str] = None
    requirementstxt: Optional[str] = None

    @property
    def package_args(self) -> tuple[str, ...]:
        """Combined positional + editable list used by validators."""
        return tuple(p for p in self.packages if p) + tuple(
            p for p in self.editable_packages if p
        )


@dataclass(frozen=True)
class ExecutionOptions:
    """How to run a routine: passthrough flags, output, paths.

    Sourced from the `execution_options` semantic group in T_C.2 (57
    rows). Includes pip passthrough (`extra_pip_args`), output
    formatting (`bare`, `quiet`, `verbose`) and resolver-time
    behaviour toggles (`no_deps`, `ignore_hashes`, `use_pep517`).

    Notes:
    * `requirements_directory` and `requirements_dir` collapse to
      `requirements_directory`.
    * `write` (in `do_lock`) defaults to True because the historical
      default is "write the lockfile to disk"; do_lock's
      return-a-dict mode is a non-default override.
    * Audit / scan / check output knobs (`output`, `save_json`,
      `output_file`, `policy_file`) are deliberately NOT in
      `ExecutionOptions` — they belong to the audit / scan routines
      which are not really "dependency-management" calls and may end
      up in a different context object entirely; see section 8.
    """

    extra_pip_args: Sequence[str] = ()
    requirements_directory: Optional[str] = None
    no_deps: bool = False
    ignore_hashes: bool = False
    use_pep517: bool = True
    bare: bool = False
    quiet: bool = False
    verbose: bool = False
    write: bool = True


@dataclass(frozen=True)
class RoutineContext:
    """Top-level routine context.

    Composed of four nested frozen dataclasses. Constructed once at
    the CLI boundary via `RoutineContext.from_cli(...)`; mutated
    downstream via `dataclasses.replace`.
    """

    target_env: TargetEnv = field(default_factory=TargetEnv)
    install_policy: InstallPolicy = field(default_factory=InstallPolicy)
    package_selection: PackageSelection = field(default_factory=PackageSelection)
    execution_options: ExecutionOptions = field(
        default_factory=ExecutionOptions
    )

    @classmethod
    def from_cli(
        cls,
        *,
        # target_env
        system: bool = False,
        allow_global: Optional[bool] = None,
        python: Optional[str] = None,
        pypi_mirror: Optional[str] = None,
        site_packages: Optional[bool] = None,
        # install_policy
        pre: bool = False,
        deploy: bool = False,
        skip_lock: bool = False,
        ignore_pipfile: bool = False,
        clear: bool = False,
        lock_only: bool = False,
        lock: bool = False,
        dry_run: bool = False,
        # package_selection
        packages: Sequence[str] = (),
        editable_packages: Sequence[str] = (),
        categories: Sequence[str] = (),
        dev: bool = False,
        dev_only: bool = False,
        all: bool = False,
        all_dev: bool = False,
        index: Optional[str] = None,
        index_name: Optional[str] = None,
        requirementstxt: Optional[str] = None,
        # execution_options
        extra_pip_args: Sequence[str] = (),
        requirements_directory: Optional[str] = None,
        no_deps: bool = False,
        ignore_hashes: bool = False,
        use_pep517: bool = True,
        bare: bool = False,
        quiet: bool = False,
        verbose: bool = False,
        write: bool = True,
    ) -> "RoutineContext":
        """Single materialization point for CLI defaults.

        `allow_global` defaults to `None` here so we can default it
        to `system` when unspecified (the historical pattern in
        do_install: `allow_global=system`). Callers may override.
        """
        if allow_global is None:
            allow_global = system
        return cls(
            target_env=TargetEnv(
                system=system,
                allow_global=allow_global,
                python=python,
                pypi_mirror=pypi_mirror,
                site_packages=site_packages,
            ),
            install_policy=InstallPolicy(
                pre=pre,
                deploy=deploy,
                skip_lock=skip_lock,
                ignore_pipfile=ignore_pipfile,
                clear=clear,
                lock_only=lock_only,
                lock=lock,
                dry_run=dry_run,
            ),
            package_selection=PackageSelection(
                packages=tuple(packages),
                editable_packages=tuple(editable_packages),
                categories=tuple(categories),
                dev=dev,
                dev_only=dev_only,
                all=all,
                all_dev=all_dev,
                index=index,
                index_name=index_name,
                requirementstxt=requirementstxt,
            ),
            execution_options=ExecutionOptions(
                extra_pip_args=tuple(extra_pip_args),
                requirements_directory=requirements_directory,
                no_deps=no_deps,
                ignore_hashes=ignore_hashes,
                use_pep517=use_pep517,
                bare=bare,
                quiet=quiet,
                verbose=verbose,
                write=write,
            ),
        )
```

**Field count proposed.** 5 (TargetEnv) + 8 (InstallPolicy) +
10 (PackageSelection, excluding the derived `package_args` property)
+ 9 (ExecutionOptions) = **32 fields** across the four nested
dataclasses.

## 3. What's NOT in `RoutineContext`

The `state_flags` group (9 rows) and the `other` group (34 rows)
from `T_C.2`'s inventory are explicitly excluded. The design
principle is:

> **`RoutineContext` carries *user-facing inputs* to a routine.
> Anything that is per-call workflow state — created, mutated, and
> consumed by helpers inside a single routine invocation — belongs
> in a routine-local operation object or as an explicit helper
> argument, not in the shared context.**

### `state_flags` — sub-routine intent, not user input

- `perform_upgrades` (in `handle_new_packages`) — a flag set by
  `do_install`'s body, not by the user. Stays as a positional arg
  to the helper.
- `has_package_args` (in `_process_package_args`) — cached truthy
  of `package_args`; this is a local optimisation, not context.
- `explicitly_requested` (in `_process_package_args`) — a mutable
  dict that tracks which packages the user named on the CLI. This
  is workflow accumulator state, not context.
- `use_installed`, `use_lockfile`, `legacy_mode` (in audit / scan
  / check) — switches between data sources within a single routine.
  These belong on a per-routine operation object (e.g.
  `AuditOperation`) if they are factored out at all.
- `scan` (in `do_check`) — flag that delegates to a completely
  different routine. `T_C.2` flagged this as a code smell; T_C.4
  should not propagate it via `RoutineContext`. It stays a local
  parameter and the medium-term fix is to delete it
  (the CLI should route to `do_scan` directly).

### `other` — data-flow plumbing between helpers

- `lockfile`, `original_lockfile`, `full_lock_resolution`,
  `lockfile_section` — the lockfile in various stages of
  resolution. Belongs on a `LockOperation` object that the
  `do_lock` / `_resolve_and_update_lockfile` family constructs
  internally.
- `procs` (queue.Queue), `sources`, `deps_to_install`,
  `deps_list`, `sequential_deps` — internal batch-install
  bookkeeping. Belongs on a `BatchInstall` object created inside
  `do_install_dependencies`.
- `reverse_deps`, `requested_packages`, `resolved_default_deps` —
  upgrade-flow accumulators created by `do_update`'s body. Belongs
  on an `UpgradeOperation` object scoped to a single `do_update`
  call.
- `old_hash`, `new_hash`, `new_version` — single-string payloads
  passed between two helpers. Stay as direct args.
- `ctx` (click context in `do_uninstall`) — a click-specific
  passthrough. Should move to the CLI layer entirely (`do_uninstall`
  should raise a typed exception that the CLI layer translates to
  a `UsageError`); see T_C.6 if scoped, otherwise out of scope.
- Audit / scan-specific payloads (`db`, `ignore`, `key`,
  `policy_file`, `safety_project`, `vulnerability_service`,
  `output_file`, `save_json`) — Safety / pip-audit configuration
  that is genuinely user-facing but pertains to one routine each.
  These should either land on a separate
  `SafetyOptions` / `AuditOptions` dataclass (parallel to
  `RoutineContext`, not nested under it) or remain as kwargs on
  the audit / scan entry points.

The design principle above means the proposal stays narrow:
`RoutineContext` is the shared bundle, and per-routine richer
operation types (suggested above but not designed here) live
alongside it.

## 4. `from_cli` classmethod contract

`from_cli` is the **single materialization point** for CLI-default
values. It is called exactly once per pipenv invocation, in
`pipenv/cli/command.py`, immediately after Click finishes parsing
arguments and before the corresponding `do_*` routine is called.

Signature (see section 2 for the full kwargs list):

```python
class RoutineContext:
    @classmethod
    def from_cli(cls, *, system=False, allow_global=None,
                 write=True) -> "RoutineContext":
        ...  # see section 2 for the full kwargs list
```

Contract:

1. **Keyword-only.** All arguments are keyword-only (`*`) so that
   the CLI call site is self-documenting and resilient to field
   reordering.
2. **Defaults match CLI defaults.** Every default in `from_cli`
   matches the corresponding Click option default in
   `pipenv/cli/command.py`. Where CLI defaults differ from
   dataclass defaults (e.g. `allow_global` defaults to `system`
   on the CLI side, but to `False` on `TargetEnv`), `from_cli`
   does the translation.
3. **Tuple-coerces sequences.** Any list arguments are coerced to
   tuples so the frozen dataclasses stay genuinely immutable.
4. **No I/O.** `from_cli` does not read the Pipfile, the lockfile,
   or any environment variables. It is pure construction. Reading
   Pipfile settings (e.g. resolving `pypi_mirror` from
   `[pipenv]` section) is the routine's job, not the context's.
5. **No `Project`.** `Project` is not a field of `RoutineContext`;
   it is a separate first positional arg to every routine. See
   section 7 decision 2.

Construction at the call site looks like:

```python
ctx = RoutineContext.from_cli(
    system=state.system,
    python=state.python,
    pypi_mirror=state.pypi_mirror,
    packages=packages,
    editable_packages=editables,
    dev=state.installstate.dev,
    pre=state.installstate.pre,
    deploy=state.installstate.deploy,
    skip_lock=state.installstate.skip_lock,
    # ... etc.
)
do_install(state.project, ctx)
```

## 5. Mutation pattern

`RoutineContext` and all four nested dataclasses are
`@dataclass(frozen=True)`. Mutation produces a new context via
`dataclasses.replace`:

```python
from dataclasses import replace

# Flip a single install-policy flag.
ctx2 = replace(
    ctx,
    install_policy=replace(ctx.install_policy, skip_lock=True),
)

# Switch categories for a recursive call into a sub-routine.
ctx3 = replace(
    ctx,
    package_selection=replace(
        ctx.package_selection,
        categories=("packages", "dev-packages"),
    ),
)
```

The two-level `replace(replace(...))` is verbose but explicit. If
maintainers want sugar, optional helpers can be added:

```python
# Optional nice-to-haves; deferred until call sites demand them.
def with_install_policy(self, **kwargs) -> "RoutineContext":
    return replace(self,
                   install_policy=replace(self.install_policy, **kwargs))

def with_package_selection(self, **kwargs) -> "RoutineContext":
    return replace(self,
                   package_selection=replace(self.package_selection, **kwargs))
```

The proposal is to **omit these helpers initially** and only add them
if T_C.4 / T_C.5 find call sites where the bare `replace` pattern is
genuinely painful. Frozen-dataclass mutation is well-understood by
Python developers; the helpers would mainly save typing.

## 6. Concrete migration example — `do_install`

The current signature (17 parameters including `project`):

```python
def do_install(
    project,
    packages=False,
    editable_packages=False,
    index=False,
    dev=False,
    python=False,
    pypi_mirror=None,
    system=False,
    ignore_pipfile=False,
    requirementstxt=False,
    pre=False,
    deploy=False,
    site_packages=None,
    extra_pip_args=None,
    pipfile_categories=None,
    skip_lock=False,
):
    requirements_directory = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("ignore", category=ResourceWarning)
    packages = packages if packages else []
    editable_packages = (
        [normalize_editable_path_for_pip(p) for p in editable_packages]
        if editable_packages
        else []
    )
    package_args = [p for p in packages if p] + [p for p in editable_packages if p]
    new_packages = []
    if dev and not pipfile_categories:
        pipfile_categories = ["dev-packages"]
    elif not pipfile_categories:
        pipfile_categories = ["packages"]

    ensure_project(
        project,
        python=python,
        system=system,
        warn=True,
        deploy=deploy,
        skip_requirements=False,
        pypi_mirror=pypi_mirror,
        site_packages=site_packages,
        pipfile_categories=pipfile_categories,
        lockfile_only=ignore_pipfile,
    )
    do_install_validations(
        project,
        package_args,
        requirements_directory,
        dev=dev,
        system=system,
        ignore_pipfile=ignore_pipfile,
        requirementstxt=requirementstxt,
        pre=pre,
        deploy=deploy,
        categories=pipfile_categories,
        skip_lock=skip_lock,
    )
    # ... continues for ~60 more lines ...
```

The proposed signature (2 parameters):

```python
def do_install(project, ctx: RoutineContext) -> None:
    requirements_directory = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("ignore", category=ResourceWarning)

    # Normalize editable paths and derive package_args from the
    # context's package_selection.
    pkg_sel = ctx.package_selection
    editable_normalized = tuple(
        normalize_editable_path_for_pip(p) for p in pkg_sel.editable_packages
    )
    ctx = replace(
        ctx,
        package_selection=replace(
            pkg_sel, editable_packages=editable_normalized
        ),
        execution_options=replace(
            ctx.execution_options,
            requirements_directory=requirements_directory,
        ),
    )

    # Pin default categories if the user didn't pass any.
    if not ctx.package_selection.categories:
        default_cats = ("dev-packages",) if ctx.package_selection.dev else ("packages",)
        ctx = replace(
            ctx,
            package_selection=replace(
                ctx.package_selection, categories=default_cats
            ),
        )

    new_packages: list[tuple[str, str]] = []

    ensure_project(
        project,
        python=ctx.target_env.python,
        system=ctx.target_env.system,
        warn=True,
        deploy=ctx.install_policy.deploy,
        skip_requirements=False,
        pypi_mirror=ctx.target_env.pypi_mirror,
        site_packages=ctx.target_env.site_packages,
        pipfile_categories=list(ctx.package_selection.categories),
        lockfile_only=ctx.install_policy.ignore_pipfile,
    )

    do_install_validations(project, ctx)
    do_init(project, ctx)

    if not ctx.install_policy.deploy:
        new_packages, _ = handle_new_packages(project, ctx)

    try:
        if ctx.package_selection.dev:
            # Install both develop and default categories from Pipfile.
            ctx = replace(
                ctx,
                package_selection=replace(
                    ctx.package_selection,
                    categories=("packages", "dev-packages"),
                ),
            )
        do_install_dependencies(project, ctx)
    except Exception:
        for pkg_name, category in new_packages:
            project.remove_package_from_pipfile(pkg_name, category)
        raise

    sys.exit(0)
```

Observations:

- The body of `do_install` shrinks because helpers (`do_init`,
  `do_install_validations`, `handle_new_packages`,
  `do_install_dependencies`) now take `(project, ctx)` and read
  what they need from the context instead of having flags threaded
  through them.
- The "default categories" computation moves from local-variable
  mutation to a `replace`. It is more verbose but explicit about
  *which sub-field changed*.
- The `requirements_directory` (an `other`-group value that lives
  only inside this routine) is folded into
  `ctx.execution_options.requirements_directory` for the duration
  of the call. This is arguably a borderline case — it could also
  remain a local variable passed explicitly to
  `do_install_dependencies`. See section 8 question 3.
- The "if dev: install both categories" mutation produces a new
  context for the `do_install_dependencies` call rather than
  re-assigning `pipfile_categories`; the user-facing
  `ctx.package_selection.categories` is now distinct from the
  derived install-time category list.

## 7. Decisions needed (sign-off)

1. **Field grouping.** Are the four nested dataclasses
   (`TargetEnv`, `InstallPolicy`, `PackageSelection`,
   `ExecutionOptions`) the right cut? Alternatives considered and
   rejected:
   - Flat `RoutineContext` with all 32 fields at one level —
     rejected because the four groups have distinct semantics and
     are mutated independently.
   - Three groups, collapsing `ExecutionOptions` into
     `InstallPolicy` — rejected because `execution_options`
     contains output-formatting toggles (`bare`, `quiet`) that
     are orthogonal to install behaviour.
   - Five groups, splitting `PackageSelection` into "scope"
     (`dev`, `dev_only`, `all`, `all_dev`, `categories`) and
     "names" (`packages`, `editable_packages`,
     `requirementstxt`) — possibly cleaner; flagged as an
     alternative the maintainer may prefer.

2. **`Project` reference.** Should `RoutineContext` carry a
   reference to `project`, or stay project-free? The PRD suggests
   `project` stays as a separate first positional arg. The
   proposal follows the PRD; the alternative is to put
   `project` on `RoutineContext` and have every routine take a
   single `ctx` argument. Pro: even fewer args. Con: muddles
   "input context" (transient) with "project state" (long-lived,
   may be reused across multiple routine calls in tests).

3. **Naming.** `RoutineContext` vs `CommandContext` vs
   `InstallContext`. The plan uses `RoutineContext`. Alternatives:
   - `CommandContext` — matches CLI terminology but conflicts
     with `click.Context`, which is already used in `do_uninstall`.
   - `InstallContext` — over-specific; `do_lock` and `do_sync`
     also consume it.
   - `RoutineContext` — neutral, matches the `pipenv/routines/`
     module path, no naming collisions. **Recommended.**

4. **File location.** `pipenv/routines/context.py` (new file) vs
   `pipenv/routines/__init__.py`. Proposal: **new file**
   `pipenv/routines/context.py`. Rationale: each
   `pipenv/routines/*.py` already imports its sibling routines;
   adding a peer `context.py` is the lowest-friction placement and
   keeps `__init__.py` empty (current state).

5. **`from_cli` naming.** Is `from_cli` the right classmethod
   name, or should it be the regular `__init__` taking kwargs?
   Pros of `from_cli`: discoverable; signals "this is where CLI
   defaults are materialized". Cons: extra indirection, two ways
   to build the type. Alternative: drop `from_cli` and let
   `dataclasses.dataclass`'s generated `__init__` do the work
   (requires the dataclass fields to be flat, which conflicts
   with the nested-groups proposal in section 2).

6. **`all` / `all_dev` / `dev_only` placement.** These three
   `package_selection` flags are uninstall- and
   requirements-generation-specific. Options:
   - Keep them on `PackageSelection` (current proposal) —
     simplest; they default to `False` for routines that don't
     use them.
   - Move them onto a separate `UninstallScope` /
     `RequirementsScope` dataclass — cleaner separation, but
     fragments the context.
   The proposal keeps them on `PackageSelection`; flag for review.

7. **Optional helper methods.** Are the following worth bundling
   into `RoutineContext`?
   - `ctx.has_packages() -> bool` — `bool(ctx.package_selection.package_args)`.
   - `ctx.is_pre_release_allowed() -> bool` — alias for
     `ctx.install_policy.pre`.
   - `ctx.effective_categories() -> tuple[str, ...]` — the
     "default to ('packages',) or ('dev-packages',) if dev"
     fallback currently open-coded in `do_install`.
   Proposal: defer until T_C.4 / T_C.5 surfaces concrete duplication.

## 8. Open implementation questions

1. **Default for `categories`.** Should
   `PackageSelection.categories` default to `()` (current
   proposal) or to `("packages",)`? Arguments for `()`: matches
   "user did not specify". Arguments for `("packages",)`: every
   in-flight routine ultimately needs a non-empty list, and
   defaulting at the dataclass level removes the "if not
   categories: categories = ['packages']" boilerplate that appears
   in five routines.

2. **`BAD_PACKAGES` constant.** Several routines reference
   `BAD_PACKAGES` (the set of names pipenv refuses to install:
   `pip`, `setuptools`, etc.). This is module-level constant
   state, not user input. It stays where it is (top of
   `pipenv/routines/install.py`) and does not become a field of
   `RoutineContext`. Flagging only because the inventory does not
   discuss it.

3. **`requirements_directory` placement.** The migration example
   in section 6 folds `requirements_directory` into
   `ExecutionOptions`, but this value is created *inside*
   `do_install` (via `fileutils.create_tracked_tempdir`), not
   passed in from the CLI. Is folding it onto the context after
   creation a layering violation? Alternative: leave it as a
   local variable threaded through helpers explicitly, and keep
   `ExecutionOptions.requirements_directory` reserved for cases
   where a caller (e.g. a test) wants to pin the path.

4. **`pipfile_categories` vs `categories` aliases.** The proposal
   collapses them to `categories`. `update.py` has
   `pipfile_category` (singular) and `category` (singular) — these
   are *different things* (`pipfile_category` is e.g.
   `"dev-packages"`, while `category` is e.g. `"develop"`). The
   inventory's observation 2 calls out the translation helpers
   `get_lockfile_section_using_pipfile_category` /
   `get_pipfile_category_using_lockfile_section`. Question: should
   `RoutineContext` expose only the user-facing
   `categories` (Pipfile-side), and let the translation to
   lockfile-section names happen at routine-internal boundaries?
   Proposal: **yes** — `RoutineContext.package_selection.categories`
   is always Pipfile-side names; routines translate.

5. **Audit / scan / check.** These routines have a 18–20 parameter
   surface dominated by Safety / pip-audit specific fields
   (`db`, `key`, `policy_file`, `safety_project`,
   `vulnerability_service`, `output_file`, `save_json`,
   `descriptions`, `aliases`, `strict`, `fix`, `skip_editable`,
   `local_only`, `audit_and_monitor`, `auto_install`,
   `exit_code`). The proposal puts only the shared subset
   (`target_env`, `categories`) into `RoutineContext`. The
   audit / scan-specific fields are listed as
   "out of scope, see section 3" and should land on a separate
   `AuditOptions` / `SafetyOptions` dataclass — but that is a
   T_C.5 / future-initiative concern, not this proposal's.

6. **Mutability of `extra_pip_args`.** The dataclass uses
   `Sequence[str]` with default `()`. Existing code passes
   `extra_pip_args=None` in many places and `None` is treated as
   "no extra args". The proposal normalizes to `()` at `from_cli`
   time. Open question: are there any call sites that distinguish
   `None` from `[]`? A grep of `pipenv/routines/` will answer this
   during T_C.4 implementation.

7. **Backwards compatibility for plugin / library consumers.**
   `do_install`, `do_update`, etc. are documented as part of
   pipenv's Python API. Switching to `(project, ctx)` is a
   breaking change for any external caller. T_C.4 must decide
   whether to keep the old kwargs-accepting signature as a thin
   shim that builds a `RoutineContext` and calls the new
   implementation, or take the breaking change. Recommendation:
   ship the shim for one minor release, deprecate, remove. (This
   is an Initiative-C-wide decision; flag for the maintainer.)

---

## 9. Maintainer sign-off (2026-05-12)

Recorded answers for each of the seven §7 decision questions:

1. **Field grouping — APPROVED.** Keep the four-nested-dataclass cut
   (`TargetEnv` / `InstallPolicy` / `PackageSelection` /
   `ExecutionOptions`). The 5-group alternative (splitting
   `PackageSelection` into scope + names) is not pursued.
2. **`Project` reference — APPROVED as proposed.** `project` stays
   as a separate first positional arg; not folded into
   `RoutineContext`.
3. **Naming — APPROVED.** `RoutineContext`. No bikeshedding.
4. **File location — APPROVED with flexibility.** The
   `pipenv/routines/context.py` proposal is acceptable, but the
   maintainer's standing posture is "remain as flexible as we are
   today (which is very flexible)" — the executing agent in T_C.4 may
   pick a different sensible location if a strong reason emerges, and
   we will not retrofit it later as a policy concern.
5. **`from_cli` naming — APPROVED.** Keep the classmethod.
6. **`all` / `all_dev` / `dev_only` placement — DEFERRED.** Keep on
   `PackageSelection` per the proposal until T_C.5 / T_C.7 surface
   concrete duplication or awkwardness. Re-open the question then if
   there's a clear reason.
7. **Optional helper methods — DEFERRED.** No need to design helpers
   for external-caller ergonomics. Pipenv treats only its CLI as the
   stable API; the `pipenv.routines.*` surface is internal. If a
   helper becomes useful during T_C.5+ migration to remove
   call-site duplication, add it then. We are not designing for
   plugin / library consumers.

### Consequential ramifications of decision 7

The "internal-only" posture also resolves the related open
implementation question §8.7 (backwards compatibility for plugin /
library consumers). Concretely:

- T_C.5 and downstream migrations may change the public signatures of
  `do_install`, `do_update`, `do_lock`, etc. wholesale — there is no
  obligation to maintain a backwards-compat shim that accepts the
  pre-context positional/keyword form.
- The CLI is the contract. Anyone calling
  `pipenv.routines.install.do_install(...)` from Python is doing so
  at their own risk; if the migration breaks them, the fix is to
  call the CLI.
- News fragments for the migrations are still appropriate (they
  describe the cleanup), but they should not need to include
  "deprecation period" language.

T_C.4 may now proceed: introduce `pipenv/routines/context.py` with
the four nested dataclasses and `RoutineContext` per section 2,
land tests in `tests/unit/test_routine_context.py` per the existing
TDD pattern, do not modify any existing routine signature yet.

---

*Source of truth: the [T_C.2 inventory](./initiative-c-params.md) for
which parameter goes where; updates to that document or to this
proposal should be made in lock-step.*
