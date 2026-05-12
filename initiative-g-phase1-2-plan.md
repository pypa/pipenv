# Plan: Initiative G — Phase 1 + 2 (Pure-Python Simple-API Client + Cache-Prime Bridge)

**Generated**: 2026-05-12
**Source design doc**: [`docs/dev/initiative-g-pure-python-design.md`](docs/dev/initiative-g-pure-python-design.md)
**Branch**: `maintenance/code-cleanup-phase5-perf-2026-06` (continues existing perf branch)
**Scope**: Phases 1 + 2 only.  Phase 3 (full `pure-python` backend) and Phase 4 (promote to default) get separate plans after Phase 1 lands and Phase 2 measurement gates pass.

---

## Overview

Phase 1 ships a self-contained PEP 691 simple-API client + parsed-manifest cache + parallel fetcher.  **No integration** with `do_lock`; the modules import zero `pip._internal.*` symbols.

Phase 2 wires the fetcher into `do_lock` behind an opt-in `[pipenv]` setting.  Pip continues to drive the actual resolve; the fetcher just warms pip's filesystem HTTP cache faster than pip's sequential per-package fetches would.  Phase 2 ships disabled-by-default because the earlier phase-5 parallel-prefetch experiment was net-harmful on warm-cache dev boxes; gating it on a setting lets CI / cold-cache users opt in without regressing dev-box workflows.

### Recommendations applied (from §10 of the design doc)

- **Q1** Cache format: **JSON** for phase 1 (debug-friendly; revisit in phase 3).
- **Q3** Default TTL: **600 s** (matches PyPI CDN).
- **Q5** Vendoring: **first-party** in `pipenv/resolver/` (not vendored, not patched).
- **Q6** Auth: **netrc + URL-embedded basic auth + `PIP_CLIENT_CERT`** (keyring deferred to phase 3).

### Acceptance criteria

**Phase 1:**
- All unit tests in T11–T16 pass.
- `PEP691Client.fetch` returns the same candidate set (name, version, url, hashes, requires_python, yanked) as pip's `Link.from_json` for the curated fixture suite in T2 (synthetic + real-PyPI snapshots, no live network) per T10.  Live-PyPI parity across 20 real packages is deferred to Phase 3's parity audit.
- Zero `pip._internal.*` imports in `pipenv/resolver/pep691.py`, `pipenv/resolver/candidate.py`, `pipenv/resolver/manifest_cache.py`, `pipenv/resolver/fetcher.py`, `pipenv/resolver/auth.py` (enforced by pre-commit grep gate added in T17).
- Coverage targets in T11–T15 enforced by `pytest --cov-fail-under` in CI for the new modules; coverage config update lives in T11/T17 (see those tasks).
- Zero new runtime dependencies.

**Phase 2:**
- All Phase 1 criteria still hold.
- `pipenv lock` succeeds end-to-end with `[pipenv] prefetch_index_manifests = true` set.
- CI lock-cold bench ≥10 % wall-time reduction vs phase-5 baseline (T21 measurement, **median of 3 runs**, delta must exceed 2× the run-to-run standard deviation observed in the baseline).
- CI lock-warm bench: ≥0 % (no regression beyond the same 2σ noise floor).  If we see a measurable regression on warm-cache CI runs, the setting stays off-by-default and we document that.
- User-facing documentation for the new setting shipped in T22.

---

## Prerequisites

- Phase-5 perf branch checked out (`maintenance/code-cleanup-phase5-perf-2026-06`, currently at `a6832ce3`).
- Initiative F backend registry already exists at `pipenv/resolver/backends/` — Phase 1+2 don't add to it (that's Phase 3's job).
- Vendored `pipenv.vendor.packaging` (version + tags + specifiers) available; vendored `pipenv.patched.pip._vendor.urllib3` available.

---

## Dependency Graph

```
                    T1 ── T2 ── T17
                     │     │
T3 ── T4 ── T5 ──────┤     │
                     │     │
                     T6 ───┤
                     │     │
                     T8 ───┴── T9 ── T10 ── T11
                     │
T7 ─── T8 ───────────┘
                                         T18 ── T19 ── T20 ── T21
                                          │
T12, T13, T14, T15, T16  (test waves)     T22
```

The visual is approximate; see the **Parallel Execution Groups** table below for the canonical wave breakdown.

---

## Tasks

### T1: `Candidate` dataclass and `Hash` namedtuple

- **depends_on**: `[]`
- **location**:
  - `pipenv/resolver/candidate.py` (new)
- **description**:
  Create `Candidate` as a `@dataclass(frozen=True, slots=True)` with the fields enumerated in design §5.1 (`name`, `version`, `url`, `filename`, `hashes`, `requires_python`, `yanked`, `yanked_reason`, `upload_time`, `is_wheel`, `wheel_tags`).  `Hash` is a `NamedTuple` of `(algo: str, value: str)` so it's hashable and tuple-compatible.  Provide `Candidate.from_filename(filename, **kwargs)` helper that derives `is_wheel` and `wheel_tags` (using `pipenv.vendor.packaging.tags.parse_tag` for wheels; `None` for sdists).  No I/O, no pip-internal imports.
- **validation**:
  - `python -c "from pipenv.resolver.candidate import Candidate, Hash; c = Candidate.from_filename('numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl', name='numpy', version='1.26.0', url='https://...', hashes=frozenset(), requires_python='>=3.9', yanked=False, yanked_reason=None, upload_time=None); print(c.is_wheel, len(c.wheel_tags))"` prints `True` and a non-zero tag count.
  - Zero `pip._internal` imports: `grep -r "pip._internal" pipenv/resolver/candidate.py` returns empty.
- **status**: Completed
- **log**: RED→GREEN.  Wrote 8 smoke tests in `tests/unit/test_candidate.py` covering construction, `frozen=True` mutation rejection, wheel-tag derivation (manylinux + universal `py2.py3-none-any`), sdist branch, and `Hash` namedtuple equality + frozenset membership.  Initial run: 8 `ModuleNotFoundError` failures (module did not exist).  Implemented `pipenv/resolver/candidate.py` as `@dataclass(frozen=True, slots=True)` per design §5.1, with `Hash = NamedTuple(algo, value)` and `Candidate.from_filename` that splits the wheel filename per PEP 427 (`rsplit("-", 3)`), feeds the last three components to `pipenv.vendor.packaging.tags.parse_tag`, and returns `wheel_tags=None` for sdists.  Re-ran: 8/8 GREEN.  Gotchas: (a) the plan's acceptance-criteria one-liner passes `filename` both positionally and as a kwarg, which collides at the Python call-site level — fixed by making the positional argument **positional-only** (`def from_filename(cls, __filename, /, **kwargs)`), letting the caller redundantly pass `filename=` without raising; (b) initial docstring contained a literal "pip._internal" reference that tripped the no-pip-internal grep gate — rewrote as "patched-pip's internal package".  Validation: acceptance one-liner prints `True 1`; `grep -r "pip._internal" pipenv/resolver/candidate.py` exits with code 1 (no matches).
- **files edited/created**:
  - Created: `pipenv/resolver/candidate.py` (Candidate dataclass + Hash NamedTuple + `from_filename` classmethod).
  - Created: `tests/unit/test_candidate.py` (8 smoke tests for T1 acceptance — fuller coverage owned by T11).

---

### T2: PEP 691 JSON + PEP 503 HTML test fixtures

- **depends_on**: `[]`
- **location**:
  - `tests/unit/fixtures/pep691/` (new directory)
  - `tests/unit/fixtures/pep691/six.json` (small package)
  - `tests/unit/fixtures/pep691/django.json` (versioned package with many releases)
  - `tests/unit/fixtures/pep691/cryptography.json` (multi-platform wheels)
  - `tests/unit/fixtures/pep691/tablib.json` (sdist + wheel mix)
  - `tests/unit/fixtures/pep691/yanked-pkg.json` (synthetic — includes `yanked` field)
  - `tests/unit/fixtures/pep691/missing-hash.json` (synthetic — exercises missing-hash edge case)
  - `tests/unit/fixtures/pep503/six.html` (HTML mirror)
  - `tests/unit/fixtures/pep503/django.html`
  - `tests/unit/fixtures/pep503/cryptography.html`
  - `tests/unit/fixtures/pep503/yanked-pkg.html` (synthetic)
  - `tests/unit/fixtures/README.md` (provenance: when fetched, PEP versions)
- **description**:
  Curated, version-pinned samples of real PEP 691 (`application/vnd.pypi.simple.v1+json`) and PEP 503 HTML responses, sourced from `https://pypi.org/simple/<name>/` with `Accept: application/vnd.pypi.simple.v1+json` or default.  Save raw response bodies.  Synthetic samples (`yanked-pkg`, `missing-hash`) are hand-crafted to exercise edge cases the real fixtures may not hit.  Include a README documenting when each fixture was captured and the corresponding PyPI URL so future regenerations are traceable.
- **validation**:
  - `python -c "import json; print(len(json.load(open('tests/unit/fixtures/pep691/django.json'))['files']) > 10)"` prints `True`.
  - All `.html` files validate as parseable HTML via `html.parser.HTMLParser`.
  - The `yanked-pkg` JSON fixture has at least one entry with `"yanked": "<reason>"` (non-boolean form) and at least one with `"yanked": true`.
- **status**: Completed
- **log**:
  - 2026-05-12: Fetched four real PyPI snapshots (`six`, `django`, `cryptography`, `tablib`) via `curl -H 'Accept: application/vnd.pypi.simple.v1+json'` for JSON and `curl -H 'Accept: text/html'` for HTML.  All four JSON responses came back with `meta.api-version` = `"1.4"`, well inside the `"1.x"` range the parser must accept.
  - File entry counts: six=48, django=781, cryptography=3496, tablib=68 — django comfortably clears the `> 10` acceptance bar.
  - Hand-crafted two synthetic JSON fixtures (`yanked-pkg.json`, `missing-hash.json`) and one synthetic HTML fixture (`yanked-pkg.html`) covering the yanked-string-reason, yanked-bool-true, yanked-bool-false (control), and empty-`hashes` edge cases.  Synthetic JSON declares `meta.api-version` = `"1.0"` so it stays on the conservative end of the supported range.
  - All three acceptance checks pass: `len(django files) > 10` → `True`; `six.html`, `django.html`, `cryptography.html`, `yanked-pkg.html` all parse cleanly with `html.parser.HTMLParser`; `yanked-pkg.json` carries the bool-`true`, bool-`false` control, AND string-with-reason `"yanked"` forms.
  - Provenance (URLs, Accept headers, capture date, sizes) and re-baseline procedure documented in `tests/unit/fixtures/README.md`.
- **files edited/created**:
  - `tests/unit/fixtures/pep691/six.json` (new, 24,065 B — real PyPI)
  - `tests/unit/fixtures/pep691/django.json` (new, 401,061 B — real PyPI)
  - `tests/unit/fixtures/pep691/cryptography.json` (new, 2,350,042 B — real PyPI)
  - `tests/unit/fixtures/pep691/tablib.json` (new, 32,763 B — real PyPI)
  - `tests/unit/fixtures/pep691/yanked-pkg.json` (new, synthetic)
  - `tests/unit/fixtures/pep691/missing-hash.json` (new, synthetic)
  - `tests/unit/fixtures/pep503/six.html` (new, 16,337 B — real PyPI)
  - `tests/unit/fixtures/pep503/django.html` (new, 284,321 B — real PyPI)
  - `tests/unit/fixtures/pep503/cryptography.html` (new, 1,945,696 B — real PyPI)
  - `tests/unit/fixtures/pep503/yanked-pkg.html` (new, synthetic)
  - `tests/unit/fixtures/README.md` (new — provenance + re-baseline procedure)

---

### T3: `SimplePageResponse`, `FetchError`, status enum types

- **depends_on**: `[T1]`
- **location**:
  - `pipenv/resolver/pep691_types.py` (new — keeps the parser module focused on parsing logic)
- **description**:
  Define `SimplePageResponse` (frozen dataclass with `candidates: tuple[Candidate, ...]`, `etag: str | None`, `last_modified: str | None`, `raw_meta: dict`, `status: Literal["fresh", "not-modified", "missing"]`).  Define `FetchError` (frozen dataclass with `kind: Literal["missing", "transient", "auth"]`, `url: str`, `message: str`, `original: BaseException | None`).  Pure data; no pip-internal imports.
- **validation**:
  - `python -c "from pipenv.resolver.pep691_types import SimplePageResponse, FetchError; r = SimplePageResponse(candidates=(), etag=None, last_modified=None, raw_meta={}, status='missing'); print(r.status)"` prints `missing`.
  - `grep -r "pip._internal" pipenv/resolver/pep691_types.py` returns empty.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T4: PEP 691 JSON parser (`_parse_pep691_json`)

- **depends_on**: `[T1, T2, T3]`
- **location**:
  - `pipenv/resolver/pep691.py` (new file — parser function)
- **description**:
  Implement `_parse_pep691_json(body: bytes, page_url: str) -> tuple[Candidate, ...]`.  Parses PEP 691 JSON per spec (file objects with `filename`, `url`, `hashes` dict, optional `requires-python`, `yanked` bool-or-string, `upload-time`, `core-metadata`).  Resolves relative URLs against `page_url` once at parse time (replaces pip's `_ensure_quoted_url`-per-link cost).  Normalises hashes to `frozenset[Hash]`.  Yanked: `True` for bool `True` *or* non-empty string; `yanked_reason` carries the string.  Validates `meta.api-version` starts with `"1."`; logs (via `pipenv.utils.err`) and continues on unknown major.  Skips file entries with malformed JSON without raising — caller gets the partial tuple.
- **validation**:
  - All entries in `tests/unit/fixtures/pep691/six.json` round-trip into `Candidate` tuples with non-empty `name`, `version`, `url`.
  - URL with relative `href` (e.g., `"url": "../../packages/foo.whl"`) resolves to an absolute `https://...` URL.
  - The `yanked-pkg.json` fixture's `"yanked": "security-advisory-CVE-...."` entry produces a `Candidate` with `yanked=True` and `yanked_reason="security-advisory-CVE-..."`.
  - Unit-test coverage in T13 ≥ 95 % for this function.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T5: PEP 503 HTML parser (`_parse_pep503_html`)

- **depends_on**: `[T1, T2, T3]`
- **location**:
  - `pipenv/resolver/pep691.py` (additional function in the same module)
- **description**:
  Implement `_parse_pep503_html(body: bytes, page_url: str) -> tuple[Candidate, ...]` using `html.parser.HTMLParser` (stdlib).  Extract anchor tags; for each `<a href="...">` collect `data-requires-python`, `data-yanked`, `data-core-metadata` attributes, plus hash from the `#sha256=<hex>` URL fragment.  Same normalization rules as T4.  HTML fixtures from T2 are the validation set.  Same parity of output: an HTML fixture for `django` must produce the same `Candidate` set (modulo possible missing fields HTML can't express, like `upload_time`) as the JSON fixture for `django`.
- **validation**:
  - `set(c.filename for c in _parse_pep503_html(html_fixture, page_url))` equals the set parsed from the matching JSON fixture (T4 output, filtered to fields HTML supports).
  - Hash extraction from URL fragments: `<a href="...whl#sha256=ABC123">` produces `Hash("sha256", "ABC123")` in the candidate's `hashes` set.
  - Unit-test coverage in T13 ≥ 95 %.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T6: Auth helpers (netrc, URL credentials, client cert)

- **depends_on**: `[]`
- **location**:
  - `pipenv/resolver/auth.py` (new) — implementation only.  The test file is owned exclusively by T16.
- **description**:
  Implement three small helpers:
  - `extract_url_credentials(url: str) -> tuple[str, tuple[str, str] | None]`: returns `(stripped_url, (username, password))` per `pipenv.utils.internet._strip_credentials_from_url`'s contract (the function already exists and works; we re-use the same logic but expose it through the resolver namespace so the new client doesn't import from `pipenv.utils.internet`).
  - `lookup_netrc_auth(host: str, netrc_path: str | None = None) -> tuple[str, str] | None`: reads `~/.netrc` (or `_netrc` on Windows) and returns `(login, password)` if there's a matching `machine` entry.  Respects `$NETRC` env var.
  - `client_cert_from_env() -> tuple[str, str] | None`: reads `PIP_CLIENT_CERT` env var (matches pip's existing convention).
  Keyring is **not** in scope for Phase 1.
- **validation**:
  - Tests live in T16; this task's validation is that the three helpers exist with the documented signatures and pass T16's tests once T16 lands.
- **status**: Completed
- **log**:
  - 2026-05-12: Implemented `pipenv/resolver/auth.py` with the three documented helpers (`extract_url_credentials`, `lookup_netrc_auth`, `client_cert_from_env`). Pure stdlib (`os`, `urllib.parse`, `netrc`); zero `pip._internal` imports (verified by `grep "pip._internal" pipenv/resolver/auth.py` → empty). `extract_url_credentials` mirrors `pipenv.utils.internet._strip_credentials_from_url` byte-for-byte (URL-decodes creds via `unquote`; rebuilds netloc via `urlunsplit`). `lookup_netrc_auth` tries explicit-arg → `$NETRC` → `~/.netrc` (or `~/_netrc` on Windows) in priority order, swallows `netrc.NetrcParseError` + `OSError`, returns `None` on any failure or missing entry. `client_cert_from_env` returns `(value, value)` for `$PIP_CLIENT_CERT` (matches pip's single-path convention; callers expecting `(cert, key)` pairs work unchanged). RED→GREEN evidence: pre-impl `python -c "from pipenv.resolver.auth import ..."` → `ModuleNotFoundError`; post-impl prints `('https://host/path', ('user', 'pass'))` and `None` for the two documented smoke cases. Tests deferred to T16 per the revised plan.
- **files edited/created**:
  - `pipenv/resolver/auth.py` (new)

---

### T7: `ParsedManifestCache` with TTL, atomic write, schema version

- **depends_on**: `[T1]`
- **location**:
  - `pipenv/resolver/manifest_cache.py` (new)
- **description**:
  Implement the class per design §5.2:
  - `__init__(self, root: Path, schema_version: int = 1)`.
  - `get(index_url, package_name) -> CachedManifest | None` — reads from `<root>/manifests-v<sv>/<sha256(index_url)>/<pep503_name>.json`, returns `None` if file is missing OR `expires_at` is in the past.
  - `put(index_url, package_name, candidates, etag, ttl_seconds=600)` — atomic write via `tempfile.NamedTemporaryFile` + `os.replace`.  Serialises `CachedManifest` (and its embedded `Candidate` tuple) as JSON, with a `schema_version` field and `cached_at` / `expires_at` ISO timestamps.
  - `invalidate(index_url, package_name)` — best-effort `os.unlink`.
  - `clear_all()` — `shutil.rmtree(<root>)`, used by `--clear`.
  - Custom `_candidate_to_json` / `_candidate_from_json` helpers handle `frozenset` (→ sorted list), `datetime` (→ ISO), `Tag` (→ string).  Round-trip preserves all fields.
  JSON for Phase 1 per Q1.  Concurrent read/write safety inherits from `os.replace` atomicity + per-file granularity.
- **validation**:
  - Round-trip test: `cache.put("https://pypi.org/simple", "django", candidates, etag="abc"); m = cache.get("https://pypi.org/simple", "django"); assert m.candidates == candidates and m.etag == "abc"`.
  - TTL expiry: with `ttl_seconds=0`, `cache.get(...)` returns `None` immediately after `put`.
  - Schema version mismatch: a manifest written under `schema_version=99` should be ignored (return `None`) when read by a `schema_version=1` cache.
  - Atomic write: kill the process during a `put` (simulated by raising mid-write) → the existing manifest file is unchanged, no partial write visible.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T8: `PEP691Client` class

- **depends_on**: `[T4, T5, T6]`
- **location**:
  - `pipenv/resolver/pep691.py` (class added alongside the parser functions from T4/T5)
- **description**:
  Implement `PEP691Client(session, *, netrc_path=None, cert=None)`.  `session` is a `urllib3.PoolManager` (default-constructed when not supplied; tests pass a `MagicMock`).  `fetch(index_url, package_name, *, if_none_match=None) -> SimplePageResponse | FetchError`:
  - Canonicalises `package_name` via `packaging.utils.canonicalize_name`.
  - Strips URL credentials with T6's helper; constructs request URL `{stripped_index_url}/{canonical_name}/`.
  - Builds headers: `Accept: application/vnd.pypi.simple.v1+json, application/vnd.pypi.simple.v1+html; q=0.1, text/html; q=0.01`.  **Does NOT** send `Cache-Control: max-age=0` (deliberate divergence from pip; freshness is controlled by `ParsedManifestCache.expires_at` instead).  Adds `If-None-Match` when caller supplies `if_none_match`.  Adds `Authorization: Basic <b64>` when credentials were extracted from URL.  Falls back to netrc when no URL creds and a netrc match exists.
  - Sends `GET`.  Branches on `response.status`:
    - `200`: pick parser based on `response.headers["Content-Type"]`.  JSON content-type → T4; HTML or `text/html` → T5.  Returns `SimplePageResponse(status="fresh", ...)` with `etag` from `ETag` header.
    - `304`: returns `SimplePageResponse(status="not-modified", candidates=(), etag=if_none_match, ...)`.  Caller is expected to keep using the previously-cached candidates.
    - `404`: returns `SimplePageResponse(status="missing", candidates=(), ...)`.
    - `401` / `403`: returns `FetchError(kind="auth", ...)`.
    - Other `4xx` / `5xx` / network error: returns `FetchError(kind="transient", ...)`.
  No retries inside the client; retry policy lives in the fetcher (T9).
- **validation**:
  - Mock `session.request` with a 200 JSON response from T2's `six.json` → returns `SimplePageResponse(status="fresh")` with `candidates` matching T4's direct-parser output.
  - Mock 304 with `if_none_match="abc"` → returns `SimplePageResponse(status="not-modified", etag="abc")`.
  - Mock 404 → `status="missing"`.
  - Mock 401 → returns `FetchError(kind="auth")`.
  - URL with embedded creds (`https://u:p@host/simple`) → outgoing request has `Authorization` header AND request URL is `https://host/simple/<pkg>/` (no creds leaked into URL).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T9: `ParallelFetcher` with thread pool

- **depends_on**: `[T7, T8]`
- **location**:
  - `pipenv/resolver/fetcher.py` (new)
- **description**:
  Implement `ParallelFetcher(client, cache, max_workers=16, default_ttl=600)`.  Method `populate(targets: Sequence[tuple[str, str]]) -> dict[str, CachedManifest | FetchError]` where `targets` is `[(index_url, package_name), ...]`.  For each target:
  - Check `cache.get(...)`; if fresh, skip the fetch (no network).
  - Otherwise dispatch `client.fetch(...)` on the executor, passing `if_none_match` if a stale-but-present cache entry exists.
  - On `status="fresh"` → `cache.put(...)`; record the new `CachedManifest`.
  - On `status="not-modified"` → keep existing cache, extend `expires_at` by TTL.
  - On `status="missing"` → record as `FetchError(kind="missing")`.
  - On `FetchError` → recorded directly; per-target failure does not stop other workers.
  Returns the dict keyed by `package_name` (NOT by full target tuple — duplicate names across sources merge with last-fetch-wins; tests cover this).  Max workers capped at 16 (matches the urllib3 default pool size; beyond that we hit "Connection pool is full, discarding connection" warnings, verified empirically in phase-5).
- **validation**:
  - Populate with 5 fresh targets (no cache) → all 5 result entries are `CachedManifest`.
  - Populate same 5 again (cache warm, within TTL) → no `client.fetch` calls (verified by mock), all 5 returned from cache.
  - One target raises `FetchError(kind="transient")` → other 4 still complete with `CachedManifest`; dict has 4 `CachedManifest` + 1 `FetchError`.
  - **Parallelism observable via dispatch order, NOT wall-time.**  With a mock `client.fetch` that records dispatch timestamps, assert ≥80 % of 32 dispatches were submitted before the first dispatch returned.  Wall-time assertions are forbidden in unit tests (CI shared runners flake them).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T10: Phase-1 acceptance — parity check against pip's `Link.from_json` (fixture-only)

- **depends_on**: `[T4, T5]`
- **location**:
  - `tests/unit/test_pep691_parity_fixtures.py` (new)
  - Uses **fixtures from T2 only**.  No live PyPI.  Live-PyPI parity audit (the 20-real-package run) is explicitly deferred to Phase 3's parity matrix work (per design doc §7.4).
- **description**:
  For each PEP 691 JSON fixture in `tests/unit/fixtures/pep691/`, run our parser AND pip's parser path (loading the same JSON body through `pip._internal.models.link.Link.from_json` — this is the **only** test in Phase 1 that deliberately imports from `pip._internal`, justified because parity-against-pip is the whole point of the test).  Compare candidate sets field-by-field: `name`, `version`, `url`, `hashes`, `requires_python`, `yanked`.  Divergences must be documented in a `tests/unit/test_pep691_parity_known_diffs.md` companion file with justification.  Same drill for PEP 503 HTML fixtures vs pip's `Link.from_element`.
- **validation**:
  - `pytest tests/unit/test_pep691_parity_fixtures.py` passes offline.
  - Any divergence is justified in the `_known_diffs.md` file (not a silent skip).
  - The single deliberate `pip._internal` import is in the **test file only**, NOT in `pipenv/resolver/*` (the pre-commit gate added in T17 must scope to `pipenv/resolver/` to allow this exception).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T11: Unit tests — `Candidate` dataclass

- **depends_on**: `[T1]`
- **location**:
  - `tests/unit/test_candidate.py` (new)
- **description**:
  Tests for:
  - Construction with all fields; `frozen=True` enforcement (mutation raises).
  - Equality and hashability (two `Candidate`s with same field values are `==` and hash to the same value).
  - `Candidate.from_filename(...)` for wheel filenames → `is_wheel=True`, `wheel_tags` populated; sdist filenames → `is_wheel=False`, `wheel_tags=None`.
  - `Hash` namedtuple equality and frozenset membership.
- **validation**: `pytest tests/unit/test_candidate.py` passes with ≥95 % coverage of `pipenv/resolver/candidate.py`.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T12: Unit tests — PEP 691 + PEP 503 parsers

- **depends_on**: `[T4, T5, T2]`
- **location**:
  - `tests/unit/test_pep691_parser.py` (new)
- **description**:
  Per design §5.1's test list:
  - Synthetic PEP 691 JSON → expected `Candidate` set (use T2 fixtures).
  - Synthetic PEP 503 HTML → same expected `Candidate` set as the JSON variant of the same package.
  - Yanked candidate: `yanked=True`, reason preserved (both formats).
  - Wheel tags parsed correctly for `manylinux2014_x86_64`, `manylinux_2_17_x86_64`, `musllinux_1_2_x86_64`, `macosx_11_0_arm64`, `win_amd64`, `py3-none-any`, `cp311-abi3-...`.
  - Hash extraction from both JSON `"hashes": {"sha256": "..."}` and HTML `#sha256=...` fragment.
  - Relative URL → absolute (`url: "../../packages/foo.whl"` against `page_url="https://pypi.org/simple/foo/"`).
- **validation**: `pytest tests/unit/test_pep691_parser.py` passes with ≥95 % coverage of `pipenv/resolver/pep691.py`'s parser functions.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T13: Unit tests — `PEP691Client`

- **depends_on**: `[T8]`
- **location**:
  - `tests/unit/test_pep691_client.py` (new)
- **description**:
  Per design §5.1:
  - Mocked `urllib3.PoolManager.request` returns canned responses for 200 JSON, 200 HTML, 304, 404, 401, 500, network error.  Verify `SimplePageResponse` / `FetchError` shape for each.
  - `if_none_match="<etag>"` → outgoing request has `If-None-Match` header.
  - URL with embedded credentials → outgoing request has `Authorization: Basic <b64>`, URL has creds stripped.
  - netrc-supplied creds (tmp_path netrc fixture) → outgoing request has `Authorization`.
  - `PIP_CLIENT_CERT` env set → client passes `cert=` through (mock `PoolManager` records it).
- **validation**: `pytest tests/unit/test_pep691_client.py` passes with ≥90 % coverage of the `PEP691Client` class.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T14: Unit tests — `ParsedManifestCache`

- **depends_on**: `[T7]`
- **location**:
  - `tests/unit/test_manifest_cache.py` (new)
- **description**:
  Per design §5.2:
  - TTL: fresh write → `get` returns within TTL; after TTL expires `get` returns `None`.
  - etag round-trip: put with etag, get returns same etag.
  - Atomic write under failure: monkeypatch `os.replace` to raise → previous manifest unchanged; no `<file>.tmp.*` litter (cleaned up).
  - Schema versioning: write with `schema_version=1`, then load with `schema_version=2` → returns `None` (mismatch ignored).
  - Concurrent **reader-vs-writer**: two threads, one writes, one reads → reader gets either old-or-new content, never partial.
  - Concurrent **writer-vs-writer** (NEW per review item 10): two threads write to the same `(index_url, package_name)` with different candidates → one of the two payloads is the final state (last-write-wins), no corruption, no partial file, no `<file>.tmp.*` survivors.
  - `clear_all()` removes the whole cache root.
  - URL hashing collision: two different index URLs that happen to share a sha256 prefix still write to distinct paths (full sha256 used).
- **validation**: `pytest tests/unit/test_manifest_cache.py` passes with ≥95 % coverage of `pipenv/resolver/manifest_cache.py` (coverage enforced by the `--cov-fail-under` config added in T17).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T15: Unit tests — `ParallelFetcher`

- **depends_on**: `[T9]`
- **location**:
  - `tests/unit/test_parallel_fetcher.py` (new)
- **description**:
  - 5 fresh targets, mock client → all 5 dispatched to `client.fetch`; all return `CachedManifest`.
  - Same 5 targets a second time (cache warm) → zero `client.fetch` calls.
  - 5 targets, 3 within TTL, 2 expired → 2 `client.fetch` calls (with `if_none_match` for those 2).
  - Mixed outcomes: 3 fresh, 1 missing, 1 transient → return dict has 3 `CachedManifest`, 1 `FetchError(kind="missing")`, 1 `FetchError(kind="transient")`; pool didn't deadlock or hang on the failing tasks.
  - **Parallelism via dispatch-order instrumentation** (replaces flaky wall-time assertion): the mock client records each dispatch timestamp + an `arrive_event` and only returns after `release_event` is set; assert at least 14 of 32 dispatches arrived before any returned (proves the executor is dispatching concurrently up to `max_workers`).
  - One target's worker raises an unexpected exception → other targets still complete; the offender becomes `FetchError(kind="transient", original=<exc>)`.
- **validation**: `pytest tests/unit/test_parallel_fetcher.py` passes with ≥90 % coverage of `pipenv/resolver/fetcher.py` (enforced by T17's coverage config).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T16: Unit tests — Auth helpers

- **depends_on**: `[T6]`
- **location**:
  - `tests/unit/test_resolver_auth.py` (new)
- **description**:
  Already specified in T6's deliverable.  Listed as a separate task so it can run in parallel with T11–T15.
- **validation**: `pytest tests/unit/test_resolver_auth.py` passes with ≥95 % coverage of `pipenv/resolver/auth.py`.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T17: Phase-1 ship-tasks: exports, `--clear` wiring, coverage gate, pre-commit gate, news, doc

- **depends_on**: `[T1, T7, T8, T9]`
- **location**:
  - `pipenv/resolver/__init__.py` (add explicit `__all__` re-exporting `Candidate`, `Hash`, `PEP691Client`, `ParsedManifestCache`, `ParallelFetcher`, `SimplePageResponse`, `FetchError`)
  - `pipenv/cli/command.py` (`--clear` handler — add a call to `ParsedManifestCache(...).clear_all()` alongside the existing pip-cache clear)
  - `pyproject.toml` (pytest-cov config: add `[tool.coverage.run] source = ["pipenv/resolver"]` and a `--cov-fail-under=90` invocation in the CI step for the new modules)
  - `.pre-commit-config.yaml` (new local hook: `grep -RnE "^from pipenv\.patched\.pip\._internal|^import pipenv\.patched\.pip\._internal" pipenv/resolver/ && exit 1 || exit 0` — gates the no-`pip._internal` invariant against future drift)
  - `news/initiative-g-phase1-pep691-client.feature.rst` (new)
  - `docs/dev/initiative-g-pure-python-design.md` (mark §11 Phase 1 acceptance bullets as `[x]` complete; add "shipped at <commit>" annotation)
- **description**:
  Bundle the five wrap-up tasks for Phase 1 sign-off:
  1. **Module exports** — `pipenv/resolver/__init__.py` exposes the public Phase-1 surface so callers do `from pipenv.resolver import PEP691Client` rather than reaching into submodules.
  2. **`--clear` wiring** — when the user passes `pipenv lock --clear` (or `pipenv install --clear`), invalidate our parsed-manifest cache in addition to pip's HTTP cache.  Otherwise our cache becomes a poisoning surface a user can't easily nuke.
  3. **Coverage enforcement** — add a pytest-cov config that fails the test step if coverage of `pipenv/resolver/` drops below the per-module floors declared in T11–T15.  Without this, the coverage claims in those tasks are aspirational.
  4. **Pre-commit `pip._internal` gate** — a local hook that fails commit if any file under `pipenv/resolver/` imports from `pipenv.patched.pip._internal`.  The acceptance criterion at the top of this plan is otherwise enforced one-shot at merge time and silently drifts.  Scope is `pipenv/resolver/` only; T10's deliberate-by-design pip-internal import in `tests/` is exempted by the path filter.
  5. **News fragment + design-doc update** — per repo convention.
- **validation**:
  - `python -c "from pipenv.resolver import PEP691Client, ParsedManifestCache, ParallelFetcher, Candidate; print('ok')"` prints `ok`.
  - `pipenv lock --clear` removes both `~/.cache/pip/http-v2/` AND the parsed-manifest cache root.
  - CI test step with one new module dropped to 50 % coverage **fails** the build (verifies `--cov-fail-under` is wired).
  - Pre-commit hook fails when a forbidden import is introduced (verify with a deliberate failing diff in CI).
  - `python -m towncrier --version` succeeds; the fragment file is detected.
  - `git log --oneline -1 docs/dev/initiative-g-pure-python-design.md` shows the status-update commit.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T18: Add `[pipenv] prefetch_index_manifests` setting

- **depends_on**: `[]`
- **location**:
  - `pipenv/utils/settings.py` (add the setting definition + docstring)
  - `pipenv/environments.py` (env-var passthrough `PIPENV_PREFETCH_INDEX_MANIFESTS`)
  - `tests/unit/test_settings.py` (new test that the default is `False`)
- **description**:
  Boolean setting, default `False`.  Pipfile readable as `[pipenv] prefetch_index_manifests = true`; env-var override via `PIPENV_PREFETCH_INDEX_MANIFESTS=1` matching pipenv's existing convention.  Document in the setting's docstring: "When True, parallel-pre-fetch the simple-API index pages for top-level packages before invoking pip's resolver.  Most beneficial on cold caches or slow networks (typical CI runs); may be net-neutral or slightly slower on warm-cache dev machines.  Default: False until benchmark data justifies enabling globally."
- **validation**:
  - `project.settings.get("prefetch_index_manifests", False)` returns `False` by default.
  - Setting `[pipenv] prefetch_index_manifests = true` in a Pipfile + reloading the project → returns `True`.
  - `PIPENV_PREFETCH_INDEX_MANIFESTS=1 python -c "from pipenv.project import Project; print(Project().settings.get('prefetch_index_manifests'))"` prints `True`.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T19: Wire `ParallelFetcher` into `do_lock` (gated by T18) — pip-Session-backed, no SafeFileCache write

- **depends_on**: `[T9, T18]`
- **location**:
  - `pipenv/routines/lock.py` (new helper `_prefetch_index_manifests_if_enabled` invoked between the empty-category fast path and the per-category loop)
- **description**:
  In `do_lock`, after collecting `lockfile_categories` and before the resolve loop, check `project.settings.get("prefetch_index_manifests", False)`.  When `True` (and `not clear`):
  - Walk Pipfile categories, collect top-level package names.
  - Resolve `project.sources.pipfile_sources()` to a list of `(index_url, verify_ssl)` dicts.
  - Construct a `PEP691Client` whose underlying transport is **pip's own `PipSession`** (`pipenv.utils.internet.get_requests_session`).  Critical: this means pip's `SafeFileCache` writes happen automatically as a side effect of our GETs (because we're sharing the same Session class and cache dir).  We do **not** write to pip's `SafeFileCache` directly — that would require reverse-engineering pip's CacheControl on-disk format and would silently break on pip refactors.  By using `PipSession`, the cache compatibility is guaranteed at runtime by pip's own code.
  - Per-source: `verify_ssl=False` → set `session.verify = False`.  Read `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` via the standard `requests`/`urllib3` env-var paths (which `PipSession` already respects).
  - Call `fetcher.populate(targets)` for the cross product (each top-level pkg × each source).
  - Log a single "prefetched N packages in M.MMs" line at info level when verbose.  **Do not log URLs** — they may contain credentials before stripping.
  - Errors are swallowed (best-effort).  Lock continues unchanged on prefetch failure.

  **Note on the perf hypothesis**: Phase 2's expected gain comes from parallelism — pip's `PipSession` fetches sequentially inside the resolver subprocess; pre-warming it concurrently from the parent process amortises latency on cold caches.  This is the same hypothesis as the failed phase-5 experiment, but with two differences: (a) we now also populate our own parsed cache for Phase 3 reuse, and (b) the setting is opt-in so dev-box users who measured neutral-or-worse in phase-5 are not affected.  If T21's CI measurement shows no cold-cache improvement, T22 documents the negative result and the setting stays off-by-default permanently.
- **validation**:
  - `pipenv lock --verbose` with `[pipenv] prefetch_index_manifests = true` prints "prefetched N packages in ..." and produces an identical lockfile (same hash) to a `pipenv lock` with the setting `false`.
  - No URL appears in any log line at any verbosity level (verify by grepping the captured stderr in the integration test).
  - Setting unset → zero change from current behaviour (verified by unchanged unit tests under T20 with setting absent).
  - Mocking `ParallelFetcher.populate` to raise → `do_lock` still completes successfully (best-effort path).
  - With `verify_ssl=False` on a source, the prefetch does not fail TLS validation against a self-signed cert (test via `tests/pytest-pypi/` local index with a self-signed cert).
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T20: Integration test — prefetch enabled produces correct lockfile

- **depends_on**: `[T19]`
- **location**:
  - `tests/integration/test_prefetch_manifest.py` (new)
- **description**:
  - Setup: small Pipfile (3-5 packages, mix of pure-python and platform wheels).
  - Run `pipenv lock` with setting off → record lockfile hash `H1`.
  - Run `pipenv lock` with setting on → record lockfile hash `H2`.
  - Assert `H1 == H2` (resolution result identical).
  - Edge case: simulate a 404 for one package from one source via a mock pypi-server fixture → setting on should still produce the same lockfile (pip's resolver hits the other source successfully).
  - Edge case: simulate a transient network error during prefetch → setting on still completes the lock (best-effort path).
- **validation**: `pytest tests/integration/test_prefetch_manifest.py` passes.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T21: CI bench measurement — confirm cold-cache improvement, no warm regression (multi-run, statistically guarded)

- **depends_on**: `[T19, T20]`
- **location**:
  - `benchmarks/benchmark.py` (add a `--runs N` flag if it doesn't already support multi-run; default 1 today)
  - `.github/workflows/ci.yaml` (extend the benchmark job to run **3× with setting off** and **3× with setting on**; store both stats.csv sets as artifacts)
  - Commit message + PR description record the before/after numbers and the run-to-run variance
- **description**:
  Run the benchmark harness on CI for the same commit, 3 iterations per configuration:
  - **Run A** (3 iterations): existing baseline (setting off).  Compute median + standard deviation per stat.
  - **Run B** (3 iterations): setting on (`PIPENV_PREFETCH_INDEX_MANIFESTS=1`).  Same statistics.
  Acceptance:
  - `lock-cold` and `install-cold` median improves by ≥ max(10 %, 2σ_A) — i.e., the improvement must be both ≥10 % AND statistically distinct from baseline noise.
  - `lock-warm` and `install-warm` median may differ by at most max(±2 %, ±1σ_A) — no regression beyond noise.
  - `import` (install-cold + lock) improves roughly proportionally.
  If the warm-path regresses meaningfully, the setting stays `default = False` and the doc records the tradeoff explicitly.  If both improve, we have evidence for a future Phase 4 promotion to default.

  **Why 3 runs:** single-sample measurements on CI shared runners can swing ±15 % between identical commits.  The phase-5 work taught us not to trust single-sample numbers.  3 runs is the minimum that lets us reason about variance without massively slowing CI; if 3 is still too noisy, T21 may be re-spec'd to 5.
- **validation**:
  - Both artifacts exist; both have 3 iterations of every stat.
  - Median + standard deviation computed for each stat and recorded in the PR description.
  - lock-cold improvement ≥ max(10 %, 2σ_A).
  - lock-warm regression ≤ max(2 %, 1σ_A).
  - The recorded numbers are in the Phase 2 commit message AND in the design doc's §11 for future reference.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

### T22: Phase-2 ship-tasks: user docs, news fragment, design-doc Phase-2 status update

- **depends_on**: `[T19, T20, T21]`
- **location**:
  - `docs/advanced.rst` (or wherever the `[pipenv]` settings reference lives — confirm with `grep -l "allow_prereleases" docs/`) — add an entry for `prefetch_index_manifests`: default, semantics, when to enable, when not to.
  - `news/initiative-g-phase2-prefetch-bridge.feature.rst` (new)
  - `docs/dev/initiative-g-pure-python-design.md` (Phase 2 acceptance bullets flipped to checked, with the actual measured delta from T21)
- **description**:
  Three tasks bundled:
  1. **User-facing doc** for the new `[pipenv] prefetch_index_manifests` setting.  Without this the setting is undiscoverable; users won't know it exists until they read the source.
  2. **News fragment** in repo convention.
  3. **Design-doc status update** — Phase 2 acceptance bullets checked off, T21's measured deltas recorded inline so future maintainers can see whether the experiment paid off.
- **validation**:
  - News fragment validates per repo convention.
  - `grep -A 3 prefetch_index_manifests docs/` returns the new user-facing documentation block.
  - Design doc shows Phase 2 row updated with concrete numbers.
- **status**: Not Completed
- **log**:
- **files edited/created**:

---

## Parallel Execution Groups

Reconciled to per-task `depends_on` (review items 2 + 3 fixed):

| Wave | Tasks (can run concurrently) | Can Start When |
|------|-------|----------------|
| 1 | T1, T2, T6, T18 | Immediately (no deps) |
| 2 | T3, T7, T11, T16 | T1 done (T3, T7, T11); T6 done (T16) |
| 3 | T4, T5 | T1, T2, T3 done |
| 4 | T8, T10, T12, T14 | T4, T5, T6 done (T8); T4, T5 done (T10); T2, T4, T5 done (T12); T7 done (T14) |
| 5 | T9, T13 | T7, T8 done (T9); T8 done (T13) |
| 6 | T15, T17, T19 | T9 done (T15, T17, T19); T1, T7, T8 also done (T17); T18 also done (T19) |
| 7 | T20 | T19 done |
| 8 | T21 | T19, T20 done |
| 9 | T22 | T19, T20, T21 done |

**Maximum parallelism**:
- Wave 1 supports 4 concurrent agents.
- Wave 2 supports 4 concurrent agents.
- Wave 4 supports 4 concurrent agents.
- Wave 6 supports 3 concurrent agents.

Total: 22 tasks, conservatively executable across 9 sequential waves with parallelism inside each wave.

---

## Testing Strategy

- **Unit tests run continuously** alongside implementation tasks (T11–T16 each pin to their respective implementation task).
- **Integration tests** (T10, T20) gated behind `@pytest.mark.network` where they require real PyPI; CI runs them, dev-box opt-in.
- **Parity test** (T10) is the load-bearing Phase-1 acceptance criterion.  Any divergence from pip must be explicitly documented in `tests/integration/test_pep691_parity_known_diffs.md` with a justification.
- **Benchmark measurement** (T21) is the load-bearing Phase-2 acceptance criterion.  Numbers must come from CI, not dev-box.  Local-dev measurements caught us out in phase-5 and that lesson is baked into the criterion.
- **Coverage targets** in the validation sections of T11–T15 are floors, not ceilings.  Reviewer should fail the task if coverage drops below the listed threshold.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| PEP 691 parser misses an edge case pip handles silently | T10 fixture-parity test against pip's own parser on the curated fixture set; divergences justified in writing.  Live-PyPI parity audit deferred to Phase 3 per design §7.4. |
| Cache schema changes break existing users | `schema_version` field + version-mismatch invalidation in T7. |
| Prefetch is net-harmful on warm caches (replays phase-5 failure mode) | T21 measures warm-path explicitly with **3 runs each side and 2σ guards**; setting defaults `False`; ship off-by-default until CI bench shows wins outside noise. |
| Auth path leaks credentials to subprocess argv or logs | T6 + T13 strip URL credentials before request; T19 forbids logging URLs at any verbosity; T20 asserts no creds appear in captured stderr. |
| `ParallelFetcher` connection-pool exhaustion under high worker count | `max_workers=16` cap matches urllib3's default pool size; T15 verifies parallelism via dispatch-order instrumentation (not wall-time). |
| Phase-2 fetcher writes corrupt entries to pip's SafeFileCache, breaking pip's resolver | **Removed via T19 redesign**: the prefetcher now drives pip's own `PipSession`, so SafeFileCache writes happen through pip's own code path. We never reverse-engineer pip's CacheControl on-disk format. Compatibility is guaranteed at runtime by pip. |
| Coverage claims in T11–T15 silently regress | T17 wires `--cov-fail-under` so missing coverage fails CI rather than living as aspirational text. |
| `pip._internal` imports creep back into `pipenv/resolver/*` over time | T17 ships a pre-commit hook scoped to `pipenv/resolver/` that fails any commit reintroducing them. |
| Hostile / compromised index returns absolute URLs pointing off-host (cache poisoning) | **Accepted risk** — pip has the same exposure and we don't fix it in Phase 1. Phase 3's parity audit revisits whether to add cross-host link rejection. Documented here so it's a known surface, not a surprise. |
| Per-source `verify_ssl=False` or proxy env vars not honored, breaking private-index users | T19 explicitly threads `verify_ssl` into the `PipSession` and relies on `PipSession`'s existing proxy handling (`HTTPS_PROXY` / `NO_PROXY`); T20 includes a self-signed-cert integration scenario. |
| Single-sample Phase-2 perf claim is noise | T21 requires 3 runs each side, median + 2σ guard. No single-run pass-or-fail. |
| Real PyPI fixture changes cause T10 parity test to flake | Phase 1 parity is fixture-only (offline); Phase 3 owns the live-PyPI audit with its own provenance pinning. |
| Initiative-G code drifts from Initiative-F backend abstraction during Phase 3 prep | Defer Phase 3 to its own plan; Phase 1+2 explicitly ship without `Backend` integration. |

---

## Out of Scope (this plan only)

- The full `pure-python` backend (`PurePythonProvider` etc.) — that's Phase 3, separate plan.
- HTTP/2 transport (httpx).
- PEP 658 metadata pre-fetching (deferred to Phase 3).
- Keyring auth backend (deferred to Phase 3).
- Removing the pip backend (Phase 4).
- Cross-platform lockfiles (orthogonal).
