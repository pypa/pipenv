# Pipenv Codebase Modernization PRD

| Field        | Value                                           |
| ------------ | ----------------------------------------------- |
| Status       | Draft                                           |
| Owners       | @matteius, @oz123                               |
| Created      | 2026-05-12                                      |
| Branch       | `maintenance/code-cleanup-2026-05` (rolling)    |

## 1. Background

Pipenv's internal architecture grew organically across multiple eras of the
project: the early Pipfile-as-config days, the `requirementslib` /
`requirements-parser` vendored era, the post-vendor inlining era, and the
current resolver-modernization era driven by frequent `pip` bumps. Each era
left load-bearing modules in place, and the seams between them have
calcified. The codebase still works and ships, but the cost-per-change has
crept up: small bugs touch many files, new features bottleneck on a handful
of god objects, and pip-version bumps require manual reconciliation work
that should be local.

This PRD captures six structural pain points and proposes incremental,
behaviour-preserving moves against each. **It is not a rewrite plan.** Every
initiative is decomposed into PRs small enough to land independently, with
the existing test suite as the safety harness. Initiatives can be paused,
reordered, or abandoned without leaving the tree in a worse state than they
found it.

## 2. Goals

- **Reduce maintenance tax.** Make pip bumps, security patches, and routine
  bug fixes cheaper to ship.
- **Reduce surface area.** Consolidate parallel abstractions; remove dead
  and near-dead code; collapse arbitrary duplication.
- **Sharpen module boundaries.** A reader should be able to predict which
  file owns a concept without grep.
- **Preserve behaviour.** No user-visible regressions. No change in Pipfile
  / Pipfile.lock semantics. The test suite is the contract.
- **Ship in small commits.** Every PR ≤ ~300 lines of diff where possible;
  every PR independently revertible.

## 3. Non-Goals

- A from-scratch rewrite of pipenv.
- Achieving feature or performance parity with uv / Poetry / PDM.
- Removing the `Pipfile` workflow or breaking backwards compatibility for
  existing users.
- Modifying anything under `pipenv/patched/` or `pipenv/vendor/`.
- Introducing new external dependencies. Where modernization requires a
  dependency, prefer the standard library or capabilities already exposed
  by vendored `pip`.

## 4. Constraints

- **Maintainer time is the scarce resource.** Each initiative must
  demonstrate value independently; none of them are allowed to require a
  follow-up to be useful.
- **Test coverage is the safety net.** No initiative ships without the unit
  and integration suites passing. Where a refactor uncovers a coverage gap,
  the gap is filled *before* the refactor lands, not after.
- **No big-bang merges.** Even within an initiative, decompose into multiple
  PRs. A 12-file rename PR is acceptable; a 12-file rename + behaviour
  change PR is not.
- **Patched / vendored code is off limits.** The patched-pip surface is its
  own discipline and is out of scope here.

## 5. Initiatives

The six initiatives are sequenced into four waves. Wave order is chosen to
front-load low-risk wins that demonstrate the discipline and to defer
invasive work until the supporting cleanup is done.

### Wave 1 — Cheap, isolated wins

#### Initiative A — Consolidate URL and path utility surface

**Current state.** `pipenv/utils/internet.py` and `pipenv/utils/fileutils.py`
overlap on URL/path concerns. `is_valid_url` is defined identically in both
modules. Callers import from whichever was nearest when the code was
written. Other small overlaps (`is_file_url`, scheme parsing, path
normalisation) follow the same pattern.

**Target state.** One canonical URL utility module and one canonical path
utility module, with no functional duplication between them. Imports point
to one location per concept.

**Approach.**

1. Inventory every public function in `internet.py` and `fileutils.py`.
2. For each function: identify all callers; pick one canonical home
   (`internet.py` for URL/scheme concerns; `fileutils.py` for filesystem
   path concerns).
3. Move the function to its canonical home in one PR; leave a thin
   re-export at the old location for one release with a deprecation
   comment.
4. In a follow-up PR, update internal callers to import from the canonical
   location.
5. Remove the re-export shim in a subsequent release.

**Acceptance criteria.**
- Each utility function exists in exactly one module.
- No `import` statement in `pipenv/` (excluding `patched/`, `vendor/`)
  reaches into both `internet` and `fileutils` for overlapping concepts.
- Test suite green.

**Estimated effort.** 2–3 PRs, ≤ 200 lines each.

#### Initiative B — Inventory and triage "inlined former vendor" modules

**Current state.** Several modules under `pipenv/utils/` (notably
`requirementslib.py`, parts of `markers.py`, parts of `fileutils.py`) are
inlined copies of code that used to be vendored. They are no longer
reconciled with upstream, but they also haven't been refactored to project
style. This is the worst-of-both-worlds state: we carry the upstream
complexity without the upstream maintenance.

**Target state.** Every module clearly identifies as either *project-owned*
(refactor freely; project conventions apply; tests are owned) or *vendored*
(lives under `pipenv/vendor/`, do not edit). The middle state is eliminated.

**Approach.**

1. Audit each suspect module. For each: is there a live upstream? Are we
   ever going to re-sync? Is the surface still in use?
2. Produce a triage doc (one section per module) listing one of: **adopt**
   (rename, modernize, document), **vendor** (move under `pipenv/vendor/`,
   stop modifying), or **delete** (no live callers — remove).
3. Execute the triage decisions one module at a time. **Adopt** decisions
   may produce further follow-up cleanup PRs but those are not blockers.
4. Update `CONTRIBUTING.md` / `docs/dev/` to state the policy: code lives
   either under `pipenv/utils/` (owned, refactor freely) or under
   `pipenv/vendor/` (do not touch). There is no third category.

**Acceptance criteria.**
- Every module under `pipenv/utils/` has a clear owner decision.
- Modules marked **vendor** are moved or scheduled for move.
- Modules marked **adopt** have at least one followup cleanup PR or an
  issue tracking what's left.
- Policy is documented.

**Estimated effort.** 1 audit doc PR + 3–5 execution PRs.

### Wave 2 — Routine ergonomics

#### Initiative C — Replace the ambient `state` dict in routines

**Current state.** `pipenv/routines/install.py`, `update.py`,
`uninstall.py`, and several siblings accept a `state` dict that propagates
through the call chain and gets mutated along the way. The dict is the
de-facto interface between top-level commands and the resolver/lock
machinery. Its shape is implicit; its keys are added or removed by reading
through call sites.

**Target state.** A typed, immutable-by-default context object (likely a
`@dataclass(frozen=True)` or `NamedTuple`) with a documented shape. Mutation
points become explicit ("here is where we produce a new context with this
field updated"). Call sites become greppable.

**Approach.**

1. Inventory every key currently written to or read from `state`. Document
   them.
2. Introduce a `RoutineContext` (or similar) dataclass alongside the
   existing dict — populated from the dict at the top of each routine.
3. Migrate one routine at a time to consume the dataclass instead of the
   dict. Leave the dict in place until the last routine flips.
4. Remove the dict.

**Acceptance criteria.**
- No routine function takes a `state` dict.
- The context type is the single source of truth for what flows from
  command-line invocation to the resolver/lock layer.
- Test suite green.

**Estimated effort.** ~6 PRs (one per routine + scaffolding + cleanup).

### Wave 3 — Heavy lifting (parallel-safe with Wave 2)

#### Initiative D — Decompose the `Project` god class

**Current state.** `pipenv/project.py` is 1850 lines. `Project` mixes:
Pipfile parsing/serialization, lockfile I/O, virtualenv discovery and
location resolution, source/index management, settings, environment variable
handling, hash computation, and assorted URL/name helpers. It is passed as
the first argument to nearly every routine and utility, which makes it the
de-facto application context.

**Target state.** `Project` becomes a thin coordinator that composes
focused collaborators:

- `Pipfile` — read/write/parse of `Pipfile` (some scaffolding already in
  `pipenv/utils/pipfile.py`).
- `Lockfile` — read/write/parse of `Pipfile.lock`.
- `Sources` — index URL resolution, source list management.
- `VenvLocator` — virtualenv discovery and creation.
- `Settings` — environment variable / `[pipenv]` section resolution.

Each collaborator owns its data and exposes a small, documented surface.
`Project` holds references to them but delegates.

**Approach (per collaborator).**

1. Identify a coherent slice of `Project` to extract (start with
   `Sources` — smallest and most self-contained).
2. Create the new class in its own module; copy the relevant methods over.
3. Have `Project` instantiate the new class and delegate via thin
   wrappers — preserving the existing `Project.foo()` call sites without
   change.
4. Migrate internal callers from `project.foo()` to
   `project.sources.foo()` in a follow-up PR.
5. Once no internal callers depend on the delegating wrapper, remove it.

**Acceptance criteria.**
- `pipenv/project.py` is materially smaller (target: ≤ 800 lines).
- Each extracted collaborator has its own test module.
- Test suite green; no public method signature on `Project` changes during
  the extraction (deprecation removal comes in a separate release).

**Estimated effort.** 5 extractions × ~3 PRs each = ~15 PRs. Sequenceable
over multiple release cycles.

#### Initiative E — Consolidate the requirement-modelling layer

**Current state.** Three modules cover overlapping requirement-parsing
concerns: `pipenv/utils/requirementslib.py` (740 lines, inlined former
vendored package), `pipenv/utils/dependencies.py` (1515 lines, newer core
logic), and `pipenv/utils/requirements.py` (395 lines). It is not
predictable from a function name which module it lives in.

**Target state.** One module owns the requirement model (parse, normalise,
serialise, hash); other modules consume it through a documented API. Cross-
module helpers that no longer fit the boundary are either folded in or
moved out to their natural home.

**Approach.**

1. Depends on Initiative B (triage of `requirementslib.py`) being done
   first — we need a clean decision on what is owned vs vendored before
   reshaping.
2. Define the canonical requirement-model API on `dependencies.py` (the
   newest and most actively maintained of the three).
3. Migrate functionality from `requirementslib.py` and `requirements.py`
   into the canonical location, one logical group at a time. Each PR
   moves one group, updates callers, runs tests.
4. Remove the empty/stub source modules when the last function is gone.

**Acceptance criteria.**
- A reader can answer "where does requirement X live?" with one module
  name, not three.
- `requirementslib.py` and/or `requirements.py` are eliminated or reduced
  to documented compatibility shims.
- Test suite green; resolver integration tests green.

**Estimated effort.** ~8 PRs, gated on Initiative B.

### Wave 4 — Resolver seam

#### Initiative F — Tighten the in-process vs subprocess resolver boundary

**Current state.** `pipenv/resolver.py` (top-level, 572 lines) wraps
`pipenv/utils/resolver.py` (1607 lines), and the top-level module exists in
part because pipenv invokes itself as a subprocess for resolution
(`pipenv-resolver`). State crosses the subprocess boundary via JSON
serialization of project metadata and arguments. Several functions exist in
two flavours to serve the in-process and out-of-process call paths.

**Target state.** One resolver implementation. The in-process and
subprocess entry points are thin adapters around it. The serialization
boundary has a single, typed schema (a dataclass round-tripped to JSON,
not an ad-hoc dict).

**Approach.**

1. Document the current subprocess protocol — what gets serialized in,
   what gets serialized out, where. This is a doc PR, no code change.
2. Introduce a typed `ResolverRequest` / `ResolverResponse` pair
   (dataclasses) and use them at the in-process boundary first. Subprocess
   still uses the legacy ad-hoc format.
3. Migrate the subprocess entry point to use the same typed pair.
4. Remove the legacy ad-hoc serialization code.
5. Where in-process and subprocess paths have diverged into duplicate
   helper functions, fold them back to one implementation.

**Acceptance criteria.**
- One canonical resolver implementation; two thin adapters.
- The subprocess protocol is typed and documented.
- `pipenv/utils/resolver.py` is materially smaller (target: ≤ 1200 lines
  through duplicate elimination, not just relocation).
- Resolver integration tests green.

**Estimated effort.** ~5 PRs. Gated on Initiative E (a clean requirement
model makes the typed schema design straightforward).

## 6. Sequencing summary

```
Wave 1 (parallel-safe, ~5 PRs total)
├── Initiative A — URL/path utility consolidation
└── Initiative B — Inlined-vendor triage

Wave 2 (depends on nothing in Wave 1; can run in parallel)
└── Initiative C — Routine context type

Wave 3 (Initiative E depends on Initiative B; D is independent)
├── Initiative D — Project god-class decomposition
└── Initiative E — Requirement-model consolidation

Wave 4 (depends on Initiative E)
└── Initiative F — Resolver seam
```

A reasonable rolling cadence is to keep one Wave-3 initiative as the
background project, one Wave-1 or Wave-2 PR as the foreground commit-of-
the-week, and to defer Wave 4 until E is materially complete.

## 7. Success metrics

These are leading indicators, not contractual targets. Move in the right
direction over the next several release cycles.

- **Lines under `pipenv/` (excluding `patched/`, `vendor/`):** down
  meaningfully (~10–20%) once Waves 1–3 complete, primarily through
  deduplication.
- **`project.py` size:** ≤ 800 lines.
- **`utils/resolver.py` size:** ≤ 1200 lines.
- **Files with `requirement` in the name:** at most two, with one canonical.
- **Mean diff size of a `pip` bump PR:** lower (fewer hand-reconciled
  surfaces). Track by sampling the last several pip-bump PRs against the
  next several.
- **Test suite runtime:** no regression.

## 8. Risks and mitigations

| Risk                                                       | Mitigation                                                                                                       |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Refactor introduces regression in a code path the unit tests don't cover. | Identify coverage gaps in the integration suite *before* the refactor PR; add tests first.                       |
| A god-class extraction breaks a third-party caller that imports `Project.foo` directly. | Preserve `Project.foo()` as a thin delegating wrapper for at least one release after the extraction.             |
| Wave 3 work blocks the routine pipeline of bug fixes and pip bumps.  | Wave-3 PRs land in small, independent slices. Bug fixes and pip bumps always take priority on the merge queue.   |
| Resolver seam change introduces a subprocess-protocol incompatibility for in-flight installs across pipenv versions. | The typed schema is additive on the wire; old subprocess entrypoint stays valid for one release after the cut.   |
| Initiative B (vendor triage) determines a module we expected to "adopt" is actually unsafe to touch (e.g. a security-critical inlined parser). | Recorded in the triage doc as "vendor → move under `pipenv/vendor/`". Do not adopt anything we can't confidently maintain. |
| Maintainer time evaporates mid-wave.                       | Every PR is independently revertible and independently useful. No initiative leaves the tree worse than it found it. |

## 9. Out of scope

- Performance work. Pipenv's slowness vs. uv is a Rust-vs-Python gap, not
  an architecture gap, and this PRD does not pretend otherwise.
- Pipfile or Pipfile.lock format changes.
- CLI surface changes.
- New features.
- Anything under `pipenv/patched/` or `pipenv/vendor/` (excluding moves
  *into* `pipenv/vendor/` under Initiative B).

## 10. Open questions

- Should the `[pipenv]` section eventually move to `[tool.pipenv]` in
  `pyproject.toml`? Not in scope for this PRD, but it should not be
  precluded by any refactor here.
- Is there appetite for typing the public `Project` API with proper type
  hints as part of Initiative D? Cheap if done during extraction, expensive
  if done later.
- Initiative F's typed schema is a natural place to expose a stable
  subprocess protocol that *external* tools could consume. Is that a goal
  or a non-goal? Default: non-goal, but worth noting.
