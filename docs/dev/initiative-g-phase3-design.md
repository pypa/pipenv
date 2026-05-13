# Initiative G — Phase 3 Design: Pure-Python `resolvelib.Provider` Backend

Status: **draft awaiting maintainer sign-off**. No code change under
Phase 3 until this document is approved.

Companion documents:

- [`initiative-g-pure-python-design.md`](./initiative-g-pure-python-design.md) —
  the umbrella design doc.  Phase 3's scope was sketched there at §5.4
  and §7.4; this doc fills in the detail.
- [`initiative-f-backends-design.md`](./initiative-f-backends-design.md) —
  the `Backend` protocol Phase 3's deliverable plugs into.
- [`../../initiative-g-phase1-2-plan.md`](../../initiative-g-phase1-2-plan.md) —
  Phases 1 + 2 swarm plan (shipped).  Phase 3 has its own plan at
  `../../initiative-g-phase3-plan.md`.

## Table of contents

1. [Summary](#1-summary)
2. [Motivation](#2-motivation)
3. [Scope](#3-scope)
4. [Architecture overview](#4-architecture-overview)
5. [Component design](#5-component-design)
6. [Migration path](#6-migration-path)
7. [Open questions for maintainer sign-off](#7-open-questions-for-maintainer-sign-off)
8. [Acceptance criteria](#8-acceptance-criteria)
9. [Out of scope](#9-out-of-scope)

---

## 1. Summary

Phase 3 implements the in-tree pure-Python `resolvelib.Provider` adapter
that consumes the typed `Candidate`s from `pipenv.resolver.pep691` /
`pipenv.resolver.manifest_cache` / `pipenv.resolver.fetcher` (all
shipped in Phases 1 + 2) and drives `resolvelib.Resolver` directly —
**without going through pip's `PackageFinder`, `LinkEvaluator`, or
`InstallRequirement`**.

The result is a new selectable backend `pure-python`
(`pipenv/resolver/backends/pure_python.py`) under the Initiative F
backend registry.  pip remains the default; users opt in via
`[pipenv] resolver_backend = "pure-python"` (or `--backend pure-python`).
Phase 4 (separate sign-off, post-production data) promotes to default
and eventually removes the pip backend.

The post-`cf53eb17` CI baseline is `lock-warm ≈ 17 s` on the 100-pkg
bench.  Phase 3's target is **≥ 30 % faster than the pre-phase-5
baseline** (i.e., lock-warm ≤ 14.5 s) per §8 below.

## 2. Motivation

Phase 5's perf hunt brought CI lock-warm from ~21 s to ~17 s
(~21 % — `cf53eb17` did most of that).  The remaining ~17 s is
architecturally bounded by pip's internals:

| where the time goes (post-`cf53eb17`)               | wall    | category |
| --------------------------------------------------- | ------- | -------- |
| pip's resolvelib backtracking loop                  | ~10 s   | pip internal |
| `Link.from_json` × 107 k (~99 k unique)             | ~3.3 s  | pip internal — Link memoization investigated and dropped (only 7 % cache hits) |
| `evaluate_link` × 107 k                             | ~2.2 s  | pip internal |
| `_ensure_quoted_url` × 107 k                        | ~2.2 s  | pip internal |
| `packaging.version.__str__` × 455 k                 | ~1 s    | pip internal (via `canonicalize_version` + resolvelib reporter) |
| network I/O (urllib3 + ssl + zlib)                  | ~5 s    | network ceiling |

Every row except the network ceiling is **pip's own machinery
operating on its own data types**.  We can't move it without replacing
the data path.  Phase 3 replaces it:

- Our `Candidate` (typed dataclass) replaces pip's `Link` (mutable +
  URL-canonicalization-per-construction).
- Our `ParsedManifestCache` (per-package parsed list on disk) replaces
  pip's raw-response cache + per-backtrack re-parse.
- Our `Provider` drives `resolvelib.Resolver` directly with typed
  `Candidate`s — no `LinkEvaluator`, no `Wheel` reconstruction per
  candidate, no `canonicalize_version` stringification storm.

This is the only remaining lever short of switching off pipenv-on-pip
entirely.

## 3. Scope

### 3.1 In scope

- A `Requirement` dataclass — frozen, hashable, carrying name,
  specifier, extras, marker, source (Pipfile / transitive / etc.).
- A `MetadataFetcher` that reads wheel `METADATA` via PEP 658 when the
  index advertises it, falling back to a partial-download path (HEAD
  + range request for the zip directory) for indexes that don't.
- A `PurePythonProvider` implementing `resolvelib.AbstractProvider`
  (`identify`, `get_preference`, `find_matches`, `is_satisfied_by`,
  `get_dependencies`) over `Candidate`.
- A `PurePythonBackend` (Initiative F `Backend` protocol impl)
  translating `ResolverRequest` → resolvelib resolve → `ResolverResponse`.
- Backend registration at `pipenv/resolver/backends/__init__.py`.
- Lockfile-parity test suite against the pip backend.

### 3.2 Out of scope

- **sdist handling**.  sdists need `pyproject.toml` / `setup.py
  egg_info` build to extract metadata.  Phase 3 ships **wheel-only
  resolves**; an sdist appearing in the candidate set causes
  `PurePythonBackend.resolve` to fall back to the pip backend for
  that resolution (or fail loud if the user opted out — see Q-A).
  Native sdist support is Phase 4.
- **Removing the pip backend**.  Phase 4.
- **HTTP/2 transport**.  Still HTTP/1.1 with thread-pool parallelism
  per Phase 1's decision.  HTTP/2 is a separate post-Phase-3 effort.
- **Cross-platform lockfiles**.  Same as Phase 1: orthogonal.
- **Custom resolvers**.  We continue to drive `resolvelib`; replacing
  the resolver itself is not on the roadmap.

---

## 4. Architecture overview

```
                      ┌──────────────────────────────────────────┐
                      │            pipenv parent process          │
                      │  do_lock / do_install                     │
                      │      │ ResolverRequest (Initiative F)     │
                      └──────┼──────────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
           pip backend           pure-python backend  ←  Phase 3 (NEW)
           (existing)                     │
                                          ├── PurePythonProvider
                                          │   (resolvelib.AbstractProvider)
                                          │       │
                                          │       │ candidates from
                                          │       │ ParsedManifestCache
                                          │       │
                                          │       ▼
                                          │   PEP691Client + ParallelFetcher
                                          │       │ (Phases 1 + 2 infra)
                                          │       │
                                          │       ▼
                                          │   ParsedManifestCache
                                          │   (on-disk JSON)
                                          │
                                          ├── MetadataFetcher
                                          │       (PEP 658 + wheel-head fallback)
                                          │
                                          ├── Requirement (typed dataclass)
                                          │
                                          ▼
                                   resolvelib.Resolver
                                          │
                                          ▼ resolved graph
                                  ResolverResponse (typed)
```

Key points:

- The `Backend` protocol is the only shared seam between the parent
  process and the resolver implementation.  Same as pip backend; same
  `ResolverRequest` / `ResolverResponse` envelopes (Initiative F).
- `PurePythonProvider` is a `resolvelib.AbstractProvider` subclass; it
  doesn't subclass pip's `PipProvider`.  This deliberately gives us
  zero `pip._internal.*` imports in the new code path (enforced by
  Phase 1's pre-commit grep gate, scoped to `pipenv/resolver/`).
- `MetadataFetcher` is the only component that may need a per-package
  network round-trip *during* resolution (when an index doesn't
  advertise PEP 658 metadata).  All other candidate data comes from
  the pre-warmed `ParsedManifestCache`.

---

## 5. Component design

### 5.1 `Requirement` — typed requirement model

**Module**: `pipenv/resolver/pure_python_requirement.py`

Frozen dataclass — represents one constraint in the resolution graph:

```python
@dataclass(frozen=True, slots=True)
class Requirement:
    name: str                                    # PEP 503 canonical
    specifier: SpecifierSet                      # may be empty (any version)
    extras: frozenset[str]                       # empty if no extras
    marker: Marker | None                        # environment marker
    source: Literal["pipfile", "transitive", "constraint"]
    parent: str | None = None                    # name of the candidate that
                                                 # produced this transitive
```

`SpecifierSet` and `Marker` come from `pipenv.vendor.packaging`
(already vendored, not pip-internal).

`identify(requirement)` returns `(name, frozenset(extras))` for
`resolvelib`'s key — matches pip's grouping where requests for the
same package with different extras are treated as separate identifiers
in the dependency graph.

### 5.2 `MetadataFetcher` — PEP 658 + wheel-head fallback

**Module**: `pipenv/resolver/pure_python_metadata.py`

Responsibility: given a `Candidate`, return its parsed core metadata
(name, version, requires-dist list, requires-python, etc.).

**Two-tier strategy**:

1. **PEP 658 fast path** (`Candidate.has_pep658_metadata` — added to
   `Candidate` in Phase 1's design, deferred per Q2; this design
   answers Q2: yes, plumb it through, see §7).  When the index
   advertised `core-metadata`, fetch the `<wheel-url>.metadata` file
   directly.  Verify against the advertised hash.  Parse via stdlib
   `email.parser`.  Cost: one small HTTP GET per wheel (~3-5 kB
   typical).

2. **Wheel-head fallback** for indexes that don't advertise PEP 658
   (or for cases where the `.metadata` file is missing).  Use HTTP
   Range requests to download just the central-directory portion of
   the wheel (the last ~few kB), parse the central directory to
   locate `METADATA`, then fetch a second range covering just that
   entry.  Falls back to the full wheel download as a last resort.

**Caching**: a small `MetadataCache` on disk
(`<PIPENV_CACHE_DIR>/pipenv-manifests/metadata-v1/`) keyed by
`(wheel_url, content_hash)`.  Resolves are append-only; cache entries
are valid forever (wheels are immutable on PyPI).

### 5.3 `PurePythonProvider` — `resolvelib.AbstractProvider`

**Module**: `pipenv/resolver/pure_python_provider.py`

Implements the five `AbstractProvider` methods:

- **`identify(req_or_cand)`**: returns `(canonical_name,
  frozenset(extras))` for both `Requirement` and `Candidate`.

- **`get_preference(identifier, resolutions, candidates, information,
  backtrack_causes)`**: returns a small tuple that drives resolvelib's
  ordering.  **Mirror pip's pip-internal `provider.py:get_preference`
  exactly** — this is the parity-critical method.  Specifically:
  - Pinned-version requirements get the highest preference (lowest
    sort key).
  - Requirements from Pipfile beat transitive requirements.
  - Backtrack-causing identifiers get re-tried later.

- **`find_matches(identifier, requirements, incompatibilities)`**:
  the hot path.  Reads the `ParsedManifestCache` for the
  `(index_url, name)` tuple, filters to candidates satisfying every
  `requirement` and not in `incompatibilities`, returns an iterator
  ordered highest-version-first (per the version comparison rules
  in `packaging.version.Version`).  No network I/O — assumes the
  cache was warmed pre-resolve by `ParallelFetcher`.  On cache miss
  (transitive dep we didn't pre-fetch) — lazy network fetch.

- **`is_satisfied_by(requirement, candidate)`**: `candidate.version
  in requirement.specifier` AND extras compatibility AND
  marker-evaluates-True against the target environment.

- **`get_dependencies(candidate)`**: invokes `MetadataFetcher.fetch`
  for wheel candidates.  Parses `Requires-Dist` into `Requirement`
  list.  For sdist candidates: see Q-A.

### 5.4 `PurePythonBackend` — `Backend` protocol impl

**Module**: `pipenv/resolver/backends/pure_python.py`

```python
class PurePythonBackend:
    name = "pure-python"

    def is_available(self) -> bool:
        return True  # in-tree; always available

    def resolve(self, request: ResolverRequest) -> ResolverResponse:
        # 1. Pre-fetch top-level package indexes (Phase 2 infra).
        # 2. Build Requirement objects from request.packages.specs.
        # 3. Build PurePythonProvider against the cache + fetcher.
        # 4. Drive resolvelib.Resolver to a fixed point.
        # 5. Translate resolved graph -> ResolverResponse.
```

Failure modes (each maps to a structured `ResolutionError` /
`InternalError` per the `Backend` protocol contract):

- `resolvelib.ResolutionImpossible` → `ResolutionError` with the
  conflict list translated into `ResolverResponse.conflicts`.
- Network failure during `get_dependencies` for a wheel that's
  required → `InternalError` with the URL redacted.
- sdist appears in the candidate path → see Q-A.

---

## 6. Migration path

### Phase 3.1 — `Requirement` + `MetadataFetcher` standalone

**Deliverable**: `pure_python_requirement.py`, `pure_python_metadata.py`
+ unit tests.  No `Provider`, no `Backend`, no integration.

**Acceptance**: round-trip + standard parsing on a fixture set of 20
PyPI wheels (PEP 658 + non-PEP-658 split).

**Scope estimate**: ~1 week.

### Phase 3.2 — `PurePythonProvider`

**Deliverable**: full `resolvelib.AbstractProvider` impl + unit tests.
No `Backend` integration; tests drive `resolvelib.Resolver` directly
against a mock `ParsedManifestCache`.

**Acceptance**: resolves the 100-pkg bench Pipfile to the same
graph as pip backend would.  Per-package and final-graph diff in a
companion `parity-matrix.md` doc.

**Scope estimate**: 2-3 weeks.

### Phase 3.3 — `PurePythonBackend` + registry wiring

**Deliverable**: backend selectable via `[pipenv] resolver_backend
= "pure-python"`.  Lock + install end-to-end.  Sandboxed under a
matrix CI step against pip versions N-1, N, N+1.

**Acceptance**: lockfile byte-identical (modulo field ordering) to pip
backend for the bench fixture + 10 real-world projects (curated list
in the plan).

**Scope estimate**: 1-2 weeks.

### Phase 3.4 — Bench + parity matrix doc

**Deliverable**: published numbers from the CI bench under both
backends.  Parity matrix doc enumerates every behavioural divergence
with justification.

**Acceptance**: lock-warm ≤ 14.5 s on the 100-pkg bench (≥ 30 % off
the pre-phase-5 baseline of 21.3 s); parity matrix has zero
unjustified entries.

**Scope estimate**: ~1 week.

---

## 7. Decisions for execution (maintainer sign-off 2026-05-12)

The questions originally framed as "open" here have been answered.
Decisions below are load-bearing for the plan in
[`../../initiative-g-phase3-plan.md`](../../initiative-g-phase3-plan.md);
flipping any of them requires re-planning.

**Q-A: sdist handling → FAIL LOUD**

When the pure-python backend encounters an sdist-only candidate (no
wheel for the target Python + platform), the backend raises a typed
`InternalError` naming the trigger.  The user adjusts the Pipfile or
explicitly switches `[pipenv] resolver_backend = "pip"` for that
resolve.  No silent transparent fallback to pip backend.

Rationale: behaviour is auditable; users always know which backend
their lockfile came from; no "this worked in my CI yesterday and
silently fell back today" surprises.  Combined with Q-F's pre-check,
the failure surfaces at lock-startup rather than deep in a 30-second
resolve.

Implementation: T9 raises typed `_SdistEncountered` from
`get_dependencies`; `PurePythonBackend.resolve` translates that into
`ResolverResponse.result = InternalError(message=...)`.

---

**Q-B: PEP 658 metadata pre-fetch → TOP-LEVEL ONLY**

`ParallelFetcher` pre-fetches `core-metadata` files concurrently with
the simple-API JSON for top-level Pipfile packages.  Transitive
candidates stay lazy — their metadata is fetched during
`get_dependencies`.

Rationale: bounded bandwidth (~500 kB at 100 packages) with guaranteed
parallelism on the most-likely-hit set.

---

**Q-C: `get_preference` parity → STRICT MIRROR**

`PurePythonProvider.get_preference` exactly mirrors pip's
`pipenv/patched/pip/_internal/resolution/resolvelib/provider.py:176`
tuple shape and tie-breaking.  Lockfile-byte-identity for the
T15 bench + T_PARITY_REAL real-world list is the gate.

Rationale: any user-visible divergence is a bug (or a deliberate doc
entry in T_PARITY_MATRIX); maintainers can audit the matrix
post-merge.

---

**Q-D: keyring auth → NOT IN PHASE 3**

netrc + URL-embedded basic-auth + `PIP_CLIENT_CERT` are the only
supported auth backends for the new path.  Keyring users stay on the
pip backend.  Phase 4 can scope this separately based on bug-report
data once pure-python has real users.

Rationale: keyring touches user keychains; failure modes are subtle;
no real signal yet on which keyring providers our users need.

---

**Q-E: T_PARITY_REAL real-world list → 10 WHEEL-HEAVY PROJECTS**

The parity test exercises these 10 mainstream wheel-heavy
combinations:

1. `django` + `psycopg[binary]`
2. `flask` + `gunicorn`
3. `fastapi` + `uvicorn`
4. `requests` + `httpx`
5. `pandas` + `numpy`
6. `pytest` + `pytest-cov`
7. `sqlalchemy` + `alembic`
8. `cryptography` + `pyopenssl`
9. `boto3` + `botocore`
10. `click` + `rich`

Rationale: chosen to avoid known sdist-only transitives so the Q-A
fail-loud path doesn't dominate the parity gate.  If any entry develops
sdist-only deps over time (a Python-version-N+1 wheel hasn't shipped
yet, etc.), T_PARITY_REAL marks that entry pending; the gate stays
green on the other 9.

---

**Q-F: sdist UX → BACKEND-STARTUP PRE-CHECK**

When `resolver_backend = "pure-python"` is active, `PurePythonBackend.resolve`
runs a fast pre-check on the top-level Pipfile packages immediately
after `ParallelFetcher.populate` returns:

- For each top-level package, iterate its candidates.
- If at least one candidate is a wheel compatible with the target
  Python + platform → OK.
- Otherwise: raise `ResolutionError` with a message naming the
  offending package(s) and pointing at either pinning to a version
  with wheels or `pipenv lock --backend pip` for this resolve.

This catches the common case (a top-level Pipfile entry whose only
release is an sdist) at lock-startup, before resolvelib spends 30
seconds chasing a transitive graph that's going to fail anyway.
Transitive sdist-only candidates still hit the deeper Q-A fail-loud
path inside `get_dependencies` (rarer; harder to surface early).

Rationale: keep the error close to the cause.  No "different backend"
suggestion phrasing — just `pipenv lock --backend pip` if the user
chooses to retry that way.

---

## 8. Acceptance criteria

Phase 3 ships when:

- All Phase 3 plan tasks are complete.
- `pipenv/resolver/backends/pure_python.py` + its dependencies (`Provider`,
  `Requirement`, `MetadataFetcher`) import zero `pip._internal.*`
  symbols (enforced by Phase 1's pre-commit gate).
- Lockfile byte-identity vs pip backend across:
  - The 100-package bench fixture.
  - The 10-real-PyPI-project list defined in the plan.
  - pip versions N-1, N, N+1 in the matrix CI step.
- Parity matrix doc shipped with every divergence justified.
- `lock-warm` on CI ≤ 14.5 s (≥ 30 % off the pre-phase-5 baseline of
  21.3 s — the Phase 3 perf gate).
- News fragment + user-facing docs for the new `resolver_backend`
  selector.

### Phase 3b — sdist + markers + CI dogfood (maintainer sign-off 2026-05-12)

Phase 3a's static parity gate (byte-identity on a 100-package bench)
is preserved as a sub-criterion; the **strong gate for Phase 3b is
CI dogfood** — the entire pipenv test suite must run under the
new backend and produce a result on every PR.

| Gate                            | Source                  | Blocking? | Status (2026-05-12) |
| ------------------------------- | ----------------------- | --------- | ------------------- |
| Resolver-module unit coverage ≥ 90 % | `resolver-module-coverage` CI job | Yes       | Green (98 % aggregate post-T_S6)        |
| Lockfile byte-identity on `click=*` smoke | Local smoke (Phase 3a) | Yes (regression-tripwire) | Green (post-T_S5)   |
| Lockfile byte-identity on T15 100-package bench | `tests/integration` benchmark | Sub-criterion of CI dogfood | Pending bench refresh         |
| Full test suite under `PIPENV_RESOLVER=pure-python` | `tests-pure-python-backend` CI job (T_CI1) | **No (non-blocking)** until consistently green | Wired (T_CI1, 2026-05-12)   |

The `tests-pure-python-backend` job carries `continue-on-error: true`.
It is a **dogfood gate**, not a release gate, until the backend
demonstrates a clean run for ≥ 2 consecutive weeks of PR traffic. At
that point the flag is flipped (separate one-line PR) and the gate
becomes blocking.

**Q-A flip (Phase 3a → Phase 3b)**: Q-A originally locked sdist
handling at "fail loud" — `_SdistEncountered` raised by
`get_dependencies` and translated to `InternalError`. Phase 3b
**flips this to "build transparently via PEP 517"**: the backend
now resolves sdist-only candidates by downloading, extracting, and
invoking the project's PEP 517 build backend (or
`setuptools.build_meta:__legacy__` fallback) to recover `METADATA`.
The transparent build is implemented in
`pipenv/resolver/pure_python_sdist.py` and routed via
`pipenv/resolver/pure_python_metadata.py::fetch_metadata`'s `.tar.*`
/ `.zip` branch (T_S1, T_S2).

The Q-F backend-startup pre-check survives in repurposed form: it
no longer flags sdists (those now resolve), but it still fires when
a top-level package has **zero** candidates of any kind, surfacing
a "no distfiles available" error at lock-startup rather than mid-resolve
(T_S4).

**No-build-isolation tradeoff**: the sdist build path runs in the
**current process**, not a fresh isolated venv. This is a deliberate
deviation from pip's `--isolated-build` default and trades:

- *Win*: ≥ 5x faster sdist resolves (no venv creation per package),
  and no transient PyPI dependency to bootstrap `build`/`setuptools`
  in the sandbox.
- *Loss*: a malicious or buggy sdist's build hooks observe the
  pipenv process environment (sys.path, env vars). Mitigations:
  - Path-traversal validation on every tar / zip member name
    before extraction (`pure_python_sdist._validate_member_name`).
  - Device / symlink / fifo members are hard-rejected.
  - The build runs in a temp directory; the cache stores the
    extracted `METADATA` only, never the build sandbox.
  - Users who require true isolation can still pin
    `resolver_backend = "pip"` for that resolve.

Phase 4 may revisit isolated builds (`build --no-isolation=false`
fallback) once we have CI dogfood data on which sdists actually
exercise this path in practice.

## 9. Out of scope

- ~~sdist resolution (Phase 4).~~ Resolved in Phase 3b via PEP 517
  build (see §8 Phase 3b row + Q-A flip).
- Removing pip backend (Phase 4).
- HTTP/2 transport.
- Replacing `resolvelib`.
- Cross-platform lockfiles.
- Keyring auth (deferred per Q-D above).
- Isolated-environment sdist builds (Phase 4 — see §8 Phase 3b
  "no-build-isolation tradeoff").
