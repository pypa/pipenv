# Initiative G — Pure-Python Resolver Backend Design

Status: **Phases 1 + 2 shipped (Phase 2 with CI bench gate skipped);
phases 3–4 awaiting maintainer sign-off.**
Phase 1 (the standalone PEP 691 client + parsed-manifest cache +
parallel fetcher) is on `main` as of T17 (see §11 below for the
per-criterion sign-off).  Phase 2 (the prefetch bridge that wires the
parallel fetcher into `do_lock` behind the opt-in
`[pipenv] prefetch_index_manifests` setting) shipped at T22 **without**
the originally-planned CI bench measurement gate (T21) — see the
Phase-2 sign-off note in §11a for the explicit scoping decision and the
honest "claim is theoretical, not measured" caveat.  Phases 3–4 remain
at design stage pending the bench-data sign-off described in §11.

Companion documents:

- [`initiative-f-backends-design.md`](./initiative-f-backends-design.md) —
  established the `Backend` protocol and pluggable-backend registry
  this initiative slots into.  Initiative G is a *new backend
  implementation*, not a new architecture.
- [`initiative-f-typed-design.md`](./initiative-f-typed-design.md) —
  the typed `ResolverRequest` / `ResolverResponse` envelope every
  backend speaks.
- [`modernization-plan.md`](./modernization-plan.md) — overall
  modernization framing.

## Table of contents

1. [Summary](#1-summary)
2. [Motivation](#2-motivation)
3. [Scope](#3-scope)
4. [Architecture overview](#4-architecture-overview)
5. [Component design](#5-component-design)
6. [Dependency strategy](#6-dependency-strategy)
7. [Migration path](#7-migration-path)
8. [Backwards compatibility](#8-backwards-compatibility)
9. [Test surface](#9-test-surface)
10. [Open questions for maintainer sign-off](#10-open-questions-for-maintainer-sign-off)
11. [Acceptance criteria per phase](#11-acceptance-criteria-per-phase)
12. [Out of scope](#12-out-of-scope)

---

## 1. Summary

Initiative G is a multi-phase effort to replace the parts of pipenv's
resolution path that depend on pip's `_internal` APIs with an in-tree,
pure-Python implementation modeled on uv's architecture (PEP 691
simple-API client, parallel fetch, parsed-manifest cache).

It implements a new backend under the Initiative F framework
(`pipenv/resolver/backends/pure_python.py`).  pip remains the default
backend during the migration.  The pure-Python backend ships first as
opt-in via `[pipenv] resolver_backend = "pure-python"` (or
`--backend pure-python`); promotion to default and eventual removal of
the pip backend is gated on real-CI parity over a release window.

The two goals, in priority order:

1. **Eliminate the maintenance cost of tracking pip internals.**  Every
   pip release breaks `pipenv/patched/pip/_internal/...` consumers;
   each of phases 3 and 4 of the 2026-05 modernization initiative was
   driven by chasing that churn.  A pure-Python client whose only
   external contract is PEP 691 / PEP 503 is stable against pip's
   internal refactors.
2. **Reclaim the architectural perf wins that pip's design forecloses.**
   The May 2026 perf-cut investigation
   ([`maintenance/code-cleanup-phase5-perf-2026-06`](
   https://github.com/pypa/pipenv/tree/maintenance/code-cleanup-phase5-perf-2026-06)
   commit history) measured the warm-relock ceiling at ~19 s for a
   100-package Pipfile.  ~9 s of that is urllib3 streaming/decoding
   inside pip's sequential per-package index revalidation.  Pip's
   architecture (Cache-Control: max-age=0 forced revalidation, raw
   response cache, sequential `find_all_candidates`) is the bound; no
   amount of pipenv-side optimisation breaks it.  uv resolves the
   same fixture in ~1-2 s by replacing those decisions, not by being
   Rust.

This document covers **what to build, in what order, against which
contract**.  Phase 1 ships the standalone client; phase 2 wires it as a
cache-prime layer behind pip; phase 3 replaces the
`PackageFinder.find_all_candidates` call entirely; phase 4 (optional)
replaces pip's resolvelib `Provider` with one that consumes our typed
`Candidate`s directly.

---

## 2. Motivation

### 2.1 The pip-internal-API tax

The `pipenv/patched/pip/_vendor/` and `pipenv/patched/pip/_internal/`
trees contain ~MB of vendored pip code that we patch and re-distribute.
The patches exist because pip's resolution path uses APIs that pip
explicitly marks as internal:

- `pip._internal.commands.install.InstallCommand` — used as a config
  parser proxy; pip docs forbid this use.
- `pip._internal.index.package_finder.PackageFinder` — pipenv drives
  it directly via `Resolver.get_resolver()`.
- `pip._internal.network.session.PipSession` —
  re-used as our HTTP client.
- `pip._internal.req.req_install.InstallRequirement` — pipenv
  constructs these directly.
- `pip._internal.models.link.Link` — used as the lockfile-entry
  source-of-truth.
- `pip._internal.req.constructors.parse_req_from_line` — pipenv's
  parse path.
- `pip._internal.resolution.resolvelib.resolver.Resolver` — the
  internal driver.

Counting the May 2026 modernization commits, ~40 % of the merged
work was reactive churn to keep these consumers compiling after
upstream pip refactors.  Phase 3's typed-resolver schema reduced this
to a single seam (the `ResolverResponse` envelope), but the seam is
still pip-shaped on the inside.

### 2.2 The architectural perf ceiling

Profile of a representative 100-package `pipenv lock` (warm cache),
in-process resolver, no spinner:

| component (cumulative time) | wall  | notes |
|---|---:|---|
| `Resolver.resolve_for_pipenv` (parent dispatch) | 12.5 s | full wall  |
| `find_best_candidate` / `find_all_candidates` | 9.7 s | inside the resolver |
| `process_project_url` | 8.5 s | per-package PyPI fetch |
| urllib3 streaming + decode | 9.4 s | mostly inside the fetch |
| `Link.from_json` | 9.6 s (cum) | per-link URL construction |
| `_ensure_quoted_url` | 8.9 s (cum) | called from `Link.from_json` |
| `evaluate_link` self time | 0.24 s | per-link compatibility check |

The 8.5 s in `process_project_url` is ~50 sequential HTTP round-trips
(PyPI simple-API GETs with `Cache-Control: max-age=0` — pip
deliberately revalidates every read; see `_get_simple_response` in
`pipenv/patched/pip/_internal/index/collector.py:108`).  On the
benchmark CI (lock-warm = 19.25 s) the ratio is similar.

The May 2026 phase-5 work hit a ceiling around 7-11 % improvement
because every remaining cut runs into one of:

- pip's per-package serial revalidation (parent-side parallel
  prefetch is net-harmful on warm caches; verified empirically).
- pip's `Link.from_json` running `urlsplit`/`urlunsplit` on every
  candidate (cumulative wins are mostly I/O, not CPU).
- pip's resolvelib graph traversal (works correctly, not a hot
  path on warm runs).
- Per-process Python interpreter startup (~170 ms parent + ~170 ms
  subprocess; already reduced via lazy imports).

**None of these are pipenv-side problems.**  The only durable wins
require changing the decisions, not the implementation details.

### 2.3 uv's relevant decisions, decomposed

uv ships ~10× faster on the same workload.  The Rust isn't the win;
the architecture is.  Decomposed:

| decision | pip | uv |
|---|---|---|
| transport | HTTP/1.1, up to ~10 parallel connections via urllib3 pool | HTTP/2, multiplexed over one TCP connection |
| simple-API parse | `Link.from_json` per candidate, `urlsplit`/`urlunsplit` per URL | one parse per package, store typed `Candidate` |
| cache format | raw HTTP responses in CacheControl/SafeFileCache | parsed candidate manifests on disk |
| revalidation | `Cache-Control: max-age=0` forces conditional GET on every read | trust cache within session; revalidate on `--refresh` |
| fetch order | sequential per-package inside `find_all_candidates` | all top-level packages' candidates fetched concurrently before resolution |
| resolver | resolvelib (PubGrub-shaped, backtracking) | pubgrub (same family, different impl) |

Three of those (transport, simple-API parse, cache format) are
language-agnostic and replicable in pure Python.  The other three
(revalidation policy, fetch ordering, resolver) flow from there.

Initiative G targets the first three first — the transport + parse +
cache rewrite is where the architectural lift comes from.  Replacing
resolvelib is explicitly **out of scope** for this initiative.

---

## 3. Scope

### 3.1 In scope

- A pure-Python PEP 691 (`application/vnd.pypi.simple.v1+json`)
  client with PEP 503 HTML fallback.
- A typed `Candidate` dataclass and a parsed-manifest on-disk cache
  with explicit TTL, invalidation, and schema versioning.
- A parallel fetch driver that fetches all top-level Pipfile
  packages' candidate manifests before invoking the resolver.
- Integration as a new `Backend` (`pipenv/resolver/backends/pure_python.py`)
  under the Initiative F framework.
- A migration path that keeps the pip backend default until parity
  is demonstrated across pip release N-1, N, N+1.

### 3.2 Out of scope

- Replacing pip's resolvelib.  We continue to drive resolution
  through `resolvelib`, just with our own `Provider` and our own
  candidate source.
- Replacing pip's wheel installation.  `pipenv install`'s wheel
  download + install path stays on `pip install` for now; only the
  resolution side moves.
- Replacing pip's metadata extraction (PEP 517 build).  Local
  source trees and sdists still build through pip's
  `prepare_metadata_for_build_wheel`.
- HTTP/2 support is **deferred** until phase 3 (see §5.3); phase 1
  ships on HTTP/1.1 with parallel connections.
- Bypassing `pipenv/patched/pip/_vendor/` entirely.  Pip remains
  vendored for the install side and as a fallback backend.
- Lockfile format change.  The wire shape stays exactly as Initiative
  F's typed schema.  Backend differences live on the candidate-source
  side, not the lockfile side.

---

## 4. Architecture overview

```
                ┌──────────────────────────────────────────┐
                │            pipenv parent process          │
                │                                            │
                │  do_lock / do_install                      │
                │      │                                     │
                │      ▼                                     │
                │  ResolverRequest (Initiative F typed)     │
                │      │                                     │
                └──────┼─────────────────────────────────────┘
                       │
        ┌──────────────┴─────────────┐
        │                            │
   pip backend                pure-python backend  ← NEW (Initiative G)
   (existing)                       │
        │                ┌──────────┴──────────┐
        │                │                     │
        │            PEP691Client       ParsedManifestCache
        │           (HTTP/1.1 -> 2)    (~/.cache/pipenv/manifests/)
        │                │                     ▲
        │                └─────────┬───────────┘
        │                          │
        │                   pure_python.Provider
        │                  (resolvelib.Provider impl
        │                   over our Candidate)
        │                          │
        │                          ▼
        └──────► resolvelib.Resolver ◄───────────┘
                          │
                          ▼
                   ResolverResponse (typed)
```

Key points:

- The `ResolverRequest` / `ResolverResponse` typed envelope is the
  unchanged contract between pipenv's parent process and any
  backend.  Backend selection is the Initiative F existing
  mechanism.
- The pure-Python backend is self-contained.  It does **not** import
  any `pip._internal.*` symbols.  Its only pip dependency is
  `resolvelib` (vendored under `pipenv/patched/pip/_vendor/resolvelib/`),
  which is upstream-stable and not pip-internal.
- The `PEP691Client` and `ParsedManifestCache` are reusable across
  backends — a future "uv-backend" delegating to the uv binary could
  use the same cache, and a future replacement for pip's installation
  side could share the manifest data.

---

## 5. Component design

### 5.1 `PEP691Client` (phase 1)

**Module**: `pipenv/resolver/pep691.py`

**Responsibility**: fetch a single package's simple-API page from a
single index URL.  Returns a parsed list of `Candidate`s.  Does not
cache.  Does not retry beyond HTTP-level transient errors.

**Interface** (proposed):

```python
class PEP691Client:
    def __init__(
        self,
        *,
        session: httpx.Client | urllib3.PoolManager,
        # ↑ Pluggable for testability; concrete choice in §6.
        netrc: NetrcLookup | None = None,
        cert: tuple[str, str] | None = None,
    ) -> None: ...

    def fetch(
        self,
        index_url: str,
        package_name: str,
        *,
        if_none_match: str | None = None,  # ETag for conditional GET
    ) -> SimplePageResponse: ...
```

```python
@dataclass(frozen=True)
class SimplePageResponse:
    candidates: tuple[Candidate, ...]
    etag: str | None
    last_modified: str | None
    raw_meta: dict  # api-version, etc., for forward-compat
    status: Literal["fresh", "not-modified", "missing"]
```

```python
@dataclass(frozen=True)
class Candidate:
    name: str                  # canonical (PEP 503)
    version: str               # PEP 440
    url: str                   # ABSOLUTE; no further quoting needed
    filename: str              # for tag inspection
    hashes: frozenset[Hash]    # (algo, value)
    requires_python: str | None
    yanked: bool
    yanked_reason: str | None
    upload_time: datetime | None
    is_wheel: bool             # derived from filename
    # Wheel-only fields; None for sdists
    wheel_tags: frozenset[Tag] | None
```

**Critical design notes**:

- `url` is stored already-absolute and already-quoted.  Done once at
  parse time, not per-evaluation.  This is the replacement for pip's
  `_ensure_quoted_url`-per-link cost.
- `wheel_tags` is computed at parse time from the filename via
  `pipenv/vendor/packaging.tags.parse_tag` (vendored packaging, not
  patched-pip), so compatibility checks become a `frozenset`
  intersection instead of pip's `Wheel.supported(tags)` call.
- `Hash` is a `(algo: str, value: str)` tuple, frozen and hashable so
  hash-set comparisons are fast.
- We accept PEP 691 JSON (`Accept: application/vnd.pypi.simple.v1+json,
  application/vnd.pypi.simple.v1+html; q=0.1, text/html; q=0.01`)
  and parse HTML as a fallback.  HTML parsing uses
  `html.parser.HTMLParser` (stdlib).
- We do **not** send `Cache-Control: max-age=0`.  Freshness is
  controlled by the cache layer (§5.2), not by forcing
  revalidation on every read.

**Tests** (`tests/unit/test_pep691_client.py`):

- Synthetic PEP 691 JSON → expected `Candidate` set.
- Synthetic PEP 503 HTML → same expected `Candidate` set.
- 304 Not Modified with prior etag → `status="not-modified"`.
- 404 / missing package → `status="missing"`.
- Yanked candidate: `yanked=True`, reason preserved.
- Wheel tags parsed correctly for `manylinux`, `musllinux`,
  `macosx`, `win_amd64`, `any`, `abi3`.
- Hash extraction from both inline JSON `hashes` and HTML
  `data-` attributes.

### 5.2 `ParsedManifestCache` (phase 1)

**Module**: `pipenv/resolver/manifest_cache.py`

**Responsibility**: persist parsed `Candidate` tuples to disk, keyed
by `(index_url, package_name)`.  Replace pip's CacheControl + JSON
re-parse hot path.

**Interface**:

```python
class ParsedManifestCache:
    def __init__(self, root: Path, schema_version: int = 1) -> None: ...

    def get(
        self, index_url: str, package_name: str
    ) -> CachedManifest | None: ...

    def put(self, index_url: str, package_name: str,
            candidates: Sequence[Candidate],
            etag: str | None,
            ttl_seconds: int) -> None: ...

    def invalidate(self, index_url: str, package_name: str) -> None: ...
```

```python
@dataclass(frozen=True)
class CachedManifest:
    candidates: tuple[Candidate, ...]
    etag: str | None
    cached_at: datetime
    expires_at: datetime
```

**Disk format**:

- Root: `~/.cache/pipenv/manifests-v{schema_version}/`.
- Path: `<sha256(index_url)>/<canonical_package_name>.msgpack`
  (or json — see §10 Q1).
- File contents: serialised `CachedManifest` including version,
  schema_version, cached_at, expires_at, etag, candidates.
- Atomic write via `tempfile.NamedTemporaryFile` + `os.replace`.

**Freshness policy** (versus pip's `max-age=0` revalidate-every-time):

- Default TTL: 600 s (matches PyPI's CDN cache-control header).
- Within TTL: read from cache, no network.
- After TTL: send conditional GET (`If-None-Match: <etag>`); on 304,
  extend `expires_at` by TTL; on 200, replace.
- `--clear` invalidates the whole cache root.
- `pipenv update --refresh-index` (new flag) bypasses TTL for the
  current resolve.

This is a **behaviour change** from pip's hard-coded
revalidate-every-read.  The honest tradeoff: `twine upload && pipenv
install` race window grows from "~10 minutes" (pip's PyPI Cache-Control
window) to "TTL seconds", but the more important property — fresh
resolves pick up matching new releases — is unchanged because the user
running `pipenv update` always gets a fresh fetch.

### 5.3 Parallel fetch driver (phase 1 + 2)

**Module**: `pipenv/resolver/fetcher.py`

**Responsibility**: given a list of `(index_url, package_name)` pairs
and a `ParsedManifestCache`, populate the cache concurrently.  Returns
a `dict[package_name, CachedManifest | FetchError]`.

**Concurrency model**:

- Phase 1: `concurrent.futures.ThreadPoolExecutor` with up to 16
  workers (matches the urllib3 connection-pool ceiling we measured —
  beyond 16 we hit "Connection pool is full, discarding connection"
  warnings).
- Phase 3 (deferred): replace with `asyncio` + `httpx[http2]` for
  multiplexed fetches.  Spec'd behind a feature flag in phase 3 design.

**Error handling**:

- 404 / missing → recorded as `FetchError(kind="missing")`, the
  package may still resolve from another index.
- Network error / timeout → recorded as `FetchError(kind="transient")`,
  the resolver retries the affected lookup on demand.
- Auth error (401, 403) → propagated to caller as a hard failure;
  this matches pip's behaviour on auth issues.

### 5.4 `pure_python.Provider` — resolvelib integration (phase 3)

**Module**: `pipenv/resolver/backends/pure_python_provider.py`

**Responsibility**: implement the `resolvelib.AbstractProvider`
interface (`identify`, `get_preference`, `find_matches`,
`is_satisfied_by`, `get_dependencies`) over our `Candidate` types,
backed by `PEP691Client` + `ParsedManifestCache`.

**Critical methods**:

- `find_matches(identifier, requirements, incompatibilities)` →
  returns candidates from our cache, filtered to those matching
  *every* requirement and *not* matching any incompatibility.
  This is the hottest path; correctness here drives the whole
  resolution.
- `get_dependencies(candidate)` → for wheel candidates, fetch the
  wheel's `METADATA` from the index (using PEP 658 metadata files
  where the index advertises them; downloading the wheel head
  bytes for those that don't).  For sdists, fall back to pip's
  metadata extraction (sdist build is out of scope for Initiative G).
- `get_preference(...)` → match pip's preference ordering exactly
  so lockfiles produced by pure_python backend ≡ lockfiles produced
  by pip backend for the same input.  This is the parity criterion.

### 5.5 `pure_python` Backend (phase 3)

**Module**: `pipenv/resolver/backends/pure_python.py`

**Responsibility**: implement Initiative F's `Backend` protocol.
Translates `ResolverRequest` → resolvelib resolve via our
`Provider`, translates the resolved graph back into the typed
`ResolverResponse`.

Pseudo-code shape:

```python
class PurePythonBackend:
    name = "pure-python"

    def resolve(self, request: ResolverRequest) -> ResolverResponse:
        client = PEP691Client(session=...)
        cache = ParsedManifestCache(root=...)
        fetcher = ParallelFetcher(client, cache, max_workers=16)

        # Pre-fetch top-level packages.
        top_level = [(src.url, name) for src in request.sources
                     for name in request.packages.specs]
        fetcher.populate(top_level)

        provider = PurePythonProvider(client, cache, request)
        resolver = resolvelib.Resolver(provider, ...)
        result = resolver.resolve(...)

        return _result_to_response(result, request)
```

---

## 6. Dependency strategy

### 6.1 HTTP client

**Options** (ranked):

1. **`urllib3` directly** (phase 1 ships here).
   - Already in `pipenv/vendor/` transitively.
   - HTTP/1.1, parallel via thread pool.
   - Stable, well-understood, zero new dependencies.

2. **`httpx[http2]`** (phase 3 — deferred).
   - HTTP/2 multiplexing.
   - New runtime dependency.
   - Either vendored (~80 KB compressed) or required.
   - Phase 3 sign-off makes the vendor-vs-require call.

**Phase 1 chooses urllib3** because it ships zero new dependency risk
and the architectural lift (parsed-manifest cache, parallel fetch,
single parse-per-package) is most of the win.  HTTP/2 is a phase 3
multiplier on an already-faster baseline.

### 6.2 Parser

- JSON: `json` stdlib.  PEP 691 responses are well under 1 MB
  typically; no streaming-parser need.
- HTML: `html.parser.HTMLParser` stdlib.  PEP 503 anchor parsing is
  trivial; no `lxml` dependency.

### 6.3 Hashing / packaging

- `pipenv.vendor.packaging` is the version / specifier / marker /
  tag library.  Already vendored, not pip-internal.  Initiative G
  uses it directly.

### 6.4 No new runtime dependencies in phase 1

Phase 1's only requirement is the stdlib + already-vendored
`pipenv.vendor.packaging` + already-vendored
`pipenv.patched.pip._vendor.urllib3`.  Adding `httpx` is a phase 3
decision; the design doc for that phase lays out the vendoring
posture explicitly.

---

## 7. Migration path

### 7.1 Phase 0 — Initiative F backend abstraction (already done)

The pluggable-backend registry from Initiative F is the integration
point.  No work needed here; just confirming the seam exists.

### 7.2 Phase 1 — standalone client + cache (no integration)

**Deliverable**: `PEP691Client`, `Candidate`, `ParsedManifestCache`,
`ParallelFetcher` with unit tests.  Not wired into `do_lock`.

**Acceptance**: feed the client a list of 100 packages, get back
parsed `Candidate` tuples that match pip's `Link.from_json` output
candidate-for-candidate (`name`, `version`, `url`, `hashes`,
`requires_python`, `yanked`) on a fixture index.

**Scope estimate**: ~1 week of focused work.

### 7.3 Phase 2 — cache-prime bridge

**Deliverable**: a new optional code path in
`pipenv/routines/lock.py` that, when enabled by a Pipfile setting,
runs `ParallelFetcher.populate(top_level_packages)` before the
resolver subprocess fires.  pip's resolver still does the actual
resolution; we just warm its cache more intelligently.

This is a smaller cousin of the "parallel prefetch" experiment from
phase-5 that didn't pay off.  The difference: we cache the
**parsed** form, so even on dev boxes with warm pip cache we save
the per-link parse cost.

**Acceptance**: on CI lock-warm bench, ≥10 % wall-time reduction
versus phase-5 baseline.  No regression on tests.

**Scope estimate**: ~3-5 days after phase 1 lands.

### 7.4 Phase 3 — full backend (`pure_python.Provider`)

**Deliverable**: the `pure_python` backend selectable via
`[pipenv] resolver_backend = "pure-python"`.  Bypasses
`PackageFinder.find_all_candidates` entirely.  Reads only from
our `ParsedManifestCache` (warmed by `ParallelFetcher`).
Drives `resolvelib` with our `Provider`.

**Acceptance** (parity criterion):

- Lockfiles produced by `pure-python` are byte-identical (modulo
  field ordering) to lockfiles produced by `pip` for the same
  Pipfile, across:
  - The 100-package bench fixture.
  - The integration-test fixture set
    (`tests/integration/test_lock.py`).
  - 10 real-world top-PyPI projects (TBD list).
- Lockfile parity proven for pip versions N-1, N, N+1.
- Wall-time on CI lock-warm bench is ≥30 % faster than
  the phase-5 baseline.

**Scope estimate**: 4-6 weeks of focused work.

### 7.5 Phase 4 (optional) — promote to default

After phase 3 ships and a release cycle of opt-in users report no
regressions, flip the default in a major version bump.  The pip
backend remains available as `[pipenv] resolver_backend = "pip"`
for the next major thereafter, then is removed.

**Not gated by this design doc.**  Phase 4 gets its own sign-off
based on phase-3 production data.

---

## 8. Backwards compatibility

- **Lockfile format**: unchanged.  Same `_meta.hash`, same per-package
  shape.  Initiative F's typed schema is the only contract.
- **Default backend**: pip remains default through phase 3.  Phase 4
  promotion is a separate sign-off.
- **`[pipenv]` settings**: `resolver_backend` is the only new field
  in phase 3.  Defaults to `"pip"`.
- **CLI**: no new required flags.  `--backend` is the optional
  selector (already specified by Initiative F).
- **Resolution semantics**: pure-python backend matches pip backend
  exactly on the parity criterion (§7.4).  Any divergence is a bug
  blocking phase-3 sign-off.

---

## 9. Test surface

### 9.1 Unit (phase 1)

- `tests/unit/test_pep691_client.py` — protocol-level fetch tests
  against synthetic responses, no real network.
- `tests/unit/test_candidate.py` — `Candidate` construction,
  hashing, equality, wheel-tag derivation.
- `tests/unit/test_manifest_cache.py` — TTL, etag round-trip,
  atomic write, schema versioning, concurrent read/write safety.
- `tests/unit/test_parallel_fetcher.py` — pool sizing, error
  handling, FetchError propagation.

### 9.2 Integration (phase 2)

- `tests/integration/test_pure_python_prefetch.py` — exercise the
  prefetch-only mode against a real PyPI fixture (or `tests/pytest-pypi/`
  local index).  Verify lockfile parity with pip-only mode.

### 9.3 Parity (phase 3)

- `tests/integration/test_backend_parity.py` — same Pipfile resolved
  with both backends, lockfiles compared field-by-field.  Run on
  the 100-package bench fixture plus a curated 10-real-project list.
- `tests/integration/test_pure_python_backend.py` — full integration
  smoke; lock + install + run for the bench fixture.

### 9.4 Existing tests

The existing `tests/integration/test_lock.py` etc. continue to run
under the **pip backend** during phases 1-3.  No changes required.

A separate CI matrix entry runs the same suite under the
`pure-python` backend during phase 3.  Failures block phase-3 sign-off.

---

## 10. Open questions for maintainer sign-off

**Q1: Cache file format — msgpack or JSON?**

JSON is human-readable for debugging; msgpack is ~3× smaller and
~5× faster to deserialise.  For a per-package manifest at 5-20 KB
this matters at scale (100 packages × 10 KB = 1 MB read on warm
relock; msgpack would be 200-300 KB).

*Recommendation*: JSON for phase 1 (debug-friendliness wins while
the format is in flux); revisit in phase 3 once the format
stabilises.

**Q2: Should `Candidate` carry the wheel-METADATA contents
inline?**

PEP 658 provides per-file `core-metadata` URLs / content-hashes.
We could fetch + cache the METADATA at the same time as the manifest
and avoid the second round of fetches during `get_dependencies`.

*Recommendation*: defer to phase 3 — the bandwidth and storage cost
isn't trivial and we need real-data measurement before committing
the cache format to it.

**Q3: Default TTL for parsed manifests?**

Tradeoffs: longer TTL = faster relocks but staler "did a new
release land" detection.  pip's `Cache-Control: max-age=0` is
the conservative extreme (every read revalidates); 600 s matches
PyPI's CDN; 1 hour is uv's default.

*Recommendation*: 600 s for phase 1.  Reconsider after measuring
real usage patterns.

**Q4: Phase 3 — resolvelib `Provider` parity with pip's?**

pip's `provider.py` has dozens of small behaviours (preference
ordering, prerelease handling, yanked-pinned override, etc.).
Phase 3 acceptance requires matching them exactly.  How aggressively
do we audit pip's `Provider` for behaviours to replicate?

*Recommendation*: phase 3 produces a "parity matrix" doc listing
every behaviour we replicate and every divergence (with
justification).  Sign-off requires no unjustified divergence.

**Q5: Vendoring strategy for the new modules?**

The Initiative G code lives in `pipenv/resolver/` (not
`pipenv/patched/...` or `pipenv/vendor/...`).  This is consistent
with the existing typed-resolver code from Initiative F.

*Recommendation*: confirmed — new code is first-party, not vendored.

**Q6: Auth / netrc / keyring parity?**

pip's `PipSession` integrates with keyring providers and netrc.
Our `PEP691Client` needs to do the same so private indexes keep
working.  How much of pip's auth handling do we replicate?

*Recommendation*: phase 1 replicates netrc + basic-auth-in-URL +
`PIP_CLIENT_CERT`.  Keyring is phase 3 (less common, deferrable).

---

## 11. Acceptance criteria per phase

### Phase 1
*Shipped at T17 on branch `maintenance/code-cleanup-phase5-perf-2026-06`.*

- [x] All unit tests in §9.1 pass.  (T11–T16 landed; resolver-module
  suite green at 99.67 % aggregate line coverage — well above the
  90 % CI floor wired by T17.)
- [x] `PEP691Client.fetch` returns the same candidate set as pip's
  `Link.from_json` for a fixture of 20 packages spanning JSON
  and HTML simple-API formats.  (T10 parity fixture green.)
- [x] No `pip._internal.*` imports anywhere in the new code.
  (Enforced ongoing by the `no-pip-internal-in-resolver`
  pre-commit hook added in T17 — scoped to `^pipenv/resolver/`,
  pattern-anchored on actual import statements rather than raw
  substring so docstring mentions don't false-positive.)
- [x] No new runtime dependency added.  (Only stdlib + already-vendored
  `packaging` are imported by the phase-1 surface.)
- [x] `pipenv lock --clear` / `pipenv install --clear` invalidate the
  parsed-manifest cache root alongside pip's HTTP cache.  (T17 wired
  `_clear_parsed_manifest_cache` at the top of `do_lock`.)
- [x] CI coverage gate (`--cov-fail-under=90` on the resolver-module
  suite) and pre-commit `pip._internal` gate ship together so the
  acceptance criteria above are enforced continuously, not just at
  merge time.

### Phase 2
*Shipped at T22 on branch `maintenance/code-cleanup-phase5-perf-2026-06`.
The CI bench measurement gate (T21) is **deferred** — see the Phase-2
sign-off note in §11a for the scoping rationale.*

- [x] All phase 1 criteria still hold.  (Phase-1 acceptance items
  above remain green; phase-2 work did not regress any of them — the
  prefetch bridge is purely additive and gated off-by-default.)
- [ ] CI lock-warm bench ≥10 % wall-time reduction vs phase-5
  baseline.  *(deferred — maintainer scoped Phase-2 to ship without
  a CI bench gate; see note below)*
- [x] Existing integration tests pass with prefetch enabled.  (T19
  unit coverage of the wiring + T20 integration test in
  `tests/integration/test_prefetch_manifest.py` verify lockfile
  parity, best-effort failure handling, `--clear` short-circuiting,
  and no URL leakage at any verbosity level.)

### Phase 2a — sign-off note (T22)

Phase 2 ships **without** the CI bench measurement gate (T21).  The
maintainer scoped T21 out during execution review (no appetite for a
multi-run statistically-guarded CI bench step at this time).  The
Phase-2 perf claim is therefore **theoretical** rather than measured
against the current CI baseline:

- The prefetch path is functionally correct (T19 + T20 verify
  lockfile parity, best-effort failure handling, `--clear`
  short-circuiting, and no URL leakage at any verbosity level).
- The underlying perf hypothesis — that parallel parent-side
  pre-fetching warms pip's HTTP cache faster than pip's serial
  per-package fetch — is sound but unmeasured on the current
  benchmark suite.
- The setting ships **opt-in** (default `false`) specifically because
  the phase-5 parallel-prefetch experiment was empirically
  net-harmful on warm-cache dev machines.  Users with cold-cache
  workflows (typical CI without persisted pip cache) are the target
  beneficiaries.

If future maintainer interest produces real benchmark data, the
Phase-2 acceptance criteria should be revisited and the bench gate
re-spec'd.  Until then, this is shipped as a low-risk opt-in feature
gated on user opt-in via `[pipenv] prefetch_index_manifests = true`.

### Phase 3
- Parity test suite (§9.3) passes for pip versions N-1, N, N+1.
- CI lock-warm bench ≥30 % wall-time reduction vs phase-5 baseline.
- Lockfile byte-identity for the 100-pkg bench Pipfile.
- Documentation: parity matrix doc shipped, `[pipenv]
  resolver_backend = "pure-python"` documented as supported.

---

## 12. Out of scope

Explicitly **not** part of Initiative G:

- Replacing pip's wheel installation.
- Replacing pip's PEP 517 build path for sdists / local sources.
- Removing the pip backend (deferred to phase 4, post-sign-off).
- HTTP/2 transport in phase 1 (deferred to phase 3 design).
- Replacing `resolvelib` with another resolver (out of scope
  entirely — `resolvelib` is upstream-stable, not pip-internal,
  and not the bottleneck).
- A separate uv backend (Initiative F already specifies that as
  a parallel effort).
- Cross-platform lockfiles (orthogonal feature, separate design).
- Cache-warming across CI runs (CI cache strategy is a separate
  concern; the manifest cache is opportunistic, not load-bearing).
