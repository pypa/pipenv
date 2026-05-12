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
- **status**: Completed
- **log**:
  - 2026-05-12: RED→GREEN.  Pre-implementation `python -c "from pipenv.resolver.pep691_types import SimplePageResponse, FetchError"` failed with `ModuleNotFoundError: No module named 'pipenv.resolver.pep691_types'`.  Implemented `pipenv/resolver/pep691_types.py` per design §5.1: two `@dataclass(frozen=True, slots=True)` types (`SimplePageResponse`, `FetchError`) plus two `Literal` aliases (`SimplePageStatus`, `FetchErrorKind`).  `FetchError.original` defaults to `None` (callers that only have an HTTP status — e.g., a clean 401 — needn't synthesise an exception).  `raw_meta` typed as bare `dict` (not `dict[str, Any]`) per the plan brief, so forward-compat PyPI fields land in this bucket without a type-check failure.  No mutable default value: `raw_meta` is a required positional argument, matching the design-doc spec.
  - GREEN evidence: (a) acceptance one-liner `python -c "from pipenv.resolver.pep691_types import SimplePageResponse, FetchError; r = SimplePageResponse(candidates=(), etag=None, last_modified=None, raw_meta={}, status='missing'); print(r.status)"` prints `missing`.  (b) `grep "pip._internal" pipenv/resolver/pep691_types.py` exits with code 1 (no matches).  (c) extended smoke confirms: `r.status = 'missing'` on a frozen instance raises `dataclasses.FrozenInstanceError`; `FetchError(kind='missing', url='...', message='...')` constructs with `original=None`; both classes have proper `__slots__` (no `__dict__`).  Tests land transitively in T13 (PEP691Client tests), so no test file is committed for this task.
  - No regressions: zero `pip._internal` references, zero new runtime dependencies, mirrors `Candidate`'s `frozen=True, slots=True` style.
- **files edited/created**:
  - Created: `pipenv/resolver/pep691_types.py` (two frozen dataclasses + two Literal aliases).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Implemented `pipenv/resolver/pep691.py` on branch `maintenance/code-cleanup-phase5-perf-2026-06` (commit `de425bcd`). Public-shape: module-level private function `_parse_pep691_json(body: bytes, page_url: str) -> tuple[Candidate, ...]`; T8 will add the `PEP691Client` class to the same module without touching the parser.
  - Helpers (all module-private): `_parse_upload_time` (3.9-compat `Z`→`+00:00` fallback), `_normalize_yanked` (bool-or-string flatten), `_normalize_hashes` (algo-lower frozenset[Hash]), `_strip_archive_suffix` (`.tar.gz` / `.tar.bz2` / `.whl` / `.zip` / `.tgz`), `_extract_version` (strips canonical-name prefix accepting `-`↔`_` and case variants, then takes first `-`-chunk for wheels / whole remainder for sdists), `_build_candidate` (per-entry construction, returns `None` on any failure).
  - RED→GREEN evidence: pre-impl smoke `tests/unit/test_pep691_parser_smoke.py` (4 tests) collected with `ModuleNotFoundError: No module named 'pipenv.resolver.pep691'`. Post-impl: 4/4 GREEN. Three plan acceptance criteria pass inline: (1) `six.json` → 48/48 candidates with non-empty `name`/`version`/`url` (`name="six"`, urls start `https://`); (2) synthetic relative-url JSON `"../files/x.whl"` against `https://pypi.org/simple/foo/` resolves to `https://pypi.org/simple/files/x.whl` (note: plan brief example was slightly off — `urljoin` only pops one path segment per `..`, so reaching `/files/` from `/simple/foo/` needs `../../files/`; either form yields an absolute `https://` URL as required); (3) `yanked-pkg.json` CVE entry → `yanked=True, yanked_reason="security-advisory-CVE-2024-99999"`.
  - Full-fixture round-trip counts (no entries dropped on any real-PyPI fixture): six=48/48, django=781/781, cryptography=3496/3496, tablib=68/68, yanked-pkg=4/4, missing-hash=2/2.
  - Constraints met: zero `pip._internal` imports (`grep "pip._internal" pipenv/resolver/pep691.py` → exit 1 / empty); zero imports of `SimplePageResponse`/`FetchError` from `pep691_types` (T8's territory) — only stdlib (`json`, `datetime`, `typing.Any`, `urllib.parse.urljoin`) + `pipenv.resolver.candidate.{Candidate, Hash}`. Parser is a pure function (no globals beyond `_SUPPORTED_API_MAJOR = "1."`, no I/O, no HTTP).
  - Yanked semantics: empty-string `"yanked": ""` is resolved as **not yanked** (conservative — a misbehaving index can't mark every release yanked via a stray `""`). Documented in `_normalize_yanked` docstring.
  - Malformed-wheel handling: T11's `TestEdgeCases::test_malformed_wheel_filename_raises_value_error` pinned `Candidate.from_filename` to **raise** `ValueError` on a wheel filename without the PEP 427 tag triple. `_build_candidate` catches `(ValueError, TypeError)` and returns `None`, so the bad entry is silently skipped and well-formed siblings still appear in the tuple. The plan brief said "the verbosity gate lives at the client layer" — this parser emits nothing.
  - Smoke test deleted before commit (T12 writes the real test suite for both parsers). `git status` post-delete: only `pipenv/resolver/pep691.py` staged. Initial commit attempt failed ruff `I001` (import-block sort: `from __future__` needed its own block); `ruff check --fix` resolved it, re-ran inline acceptance to confirm no behavioural change, re-committed cleanly.
- **files edited/created**:
  - Created: `pipenv/resolver/pep691.py` (~306 LOC; `_parse_pep691_json` + six private helpers + `_SUPPORTED_API_MAJOR` constant).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Extended `pipenv/resolver/pep691.py` (T4's file) with `_parse_pep503_html(body: bytes, page_url: str) -> tuple[Candidate, ...]` on branch `maintenance/code-cleanup-phase5-perf-2026-06`. Implementation reuses T4's helpers wholesale (`_extract_version`, `_strip_archive_suffix`, `Candidate.from_filename`) so JSON and HTML parsers emit equivalent candidate sets for the same package — invariant verified by inline cross-format parity at 100% overlap on every available fixture pair (see counts below).
  - New module-level additions (all module-private except the public function): `_AnchorCollector` (small `HTMLParser` subclass that collects `(attrs_dict, inner_text)` tuples per `<a>`), `_split_href_hash` (splits `href` on `#`, lower-cases algo, returns `(base, frozenset[Hash])`), `_normalize_yanked_html` (HTML-specific yanked semantics — see below), `_package_name_from_page_url` (derives canonical package name from `urlsplit(page_url).path` via `packaging.utils.canonicalize_name`), `_build_candidate_from_html` (per-anchor construction, parallels T4's `_build_candidate`).
  - New imports: stdlib `html.parser.HTMLParser`, `html.unescape`, `urllib.parse.urlsplit` (alongside T4's existing `urljoin`); `pipenv.vendor.packaging.utils.canonicalize_name`. Zero `pip._internal` imports verified by `grep "pip._internal" pipenv/resolver/pep691.py` → exit 1.
  - **Yanked semantics divergence (intentional)** pinned in `_normalize_yanked_html` docstring: absent `data-yanked` attribute → `yanked=False`; present with empty value (`data-yanked=""`) → `yanked=True, reason=None`; present with text → `yanked=True, reason=<unescaped text>`. This *differs from* T4's `_normalize_yanked` (JSON path treats empty-string `"yanked": ""` as not-yanked). HTML's *presence* of the attribute is the unambiguous signal (per the de-facto PEP 503 extension that aligned PEP 592 to the HTML serialisation); JSON's empty-string is a value an index might serve without intent to yank. T12 will pin both behaviours against the shared `yanked-pkg.{html,json}` fixture pair.
  - PEP 658 (`data-core-metadata` / `data-dist-info-metadata`) is observed by `_AnchorCollector` but **deferred** — not threaded into the `Candidate`. Phase-3 work.
  - HTML entity handling: `data-requires-python="&gt;=2.7"` (and the reason text for `data-yanked`) is run through `html.unescape` at consumption time. HTMLParser doesn't unescape attribute values for us. Validated inline against six.html (`>=2.7`-prefixed specifiers round-trip correctly).
  - RED→GREEN evidence: pre-impl `python -c "from pipenv.resolver.pep691 import _parse_pep503_html"` → `ImportError: cannot import name '_parse_pep503_html'`. Smoke `tests/unit/test_pep503_parser_smoke.py` (7 tests) collected with `ImportError`. Post-impl: 7/7 GREEN. Three plan acceptance criteria pass inline: (1) `set(c.filename for c in _parse_pep503_html(six.html))` equals `_parse_pep691_json(six.json)`'s filename set — **48/48 (100%)**; (2) `<a href="...#sha256=ABC123">` → `Hash("sha256", "ABC123")` (algo lower-cased, value preserved verbatim per design — value-case is *not* normalised because hash hex is case-insensitive by convention but the spec doesn't mandate it); (3) `data-yanked=""` → `yanked=True, reason=None`, `data-yanked="security-advisory-CVE-2024-99999"` → `yanked=True, reason="security-advisory-CVE-2024-99999"`.
  - Full-fixture cross-format parity (HTML candidates vs JSON candidates, by filename): six=48/48 (100%), django=781/781 (100%), cryptography=3496/3496 (100%), yanked-pkg=4/4 (100%). Zero divergence on any fixture pair — well above the 80% acceptance floor.
  - Smoke deleted before commit per plan brief (T12 writes the real test suite). `git status` post-delete: only `pipenv/resolver/pep691.py` modified in the scope of this task. `python -m ruff check pipenv/resolver/pep691.py` → "All checks passed!" pre-commit. T4's `_parse_pep691_json` behaviour verified unchanged by the parity test (same 48 candidates for `six.json`).
  - Gotcha for T12: `_split_href_hash` lower-cases the algo (`sha256` not `SHA256`) but preserves the value verbatim. The acceptance criterion says `Hash("sha256", "ABC123")` for `#sha256=ABC123` — note the **value** is `"ABC123"`, not `"abc123"`. Cross-format parity holds because real PyPI emits lower-case hashes in both JSON and HTML, but a synthetic fixture with mixed-case values would expose the (correct) verbatim-preservation behaviour.
- **files edited/created**:
  - Edited: `pipenv/resolver/pep691.py` (extends T4's file: +313 / -2; total ~617 LOC; adds `_parse_pep503_html` + `_AnchorCollector` + four private helpers without touching T4's `_parse_pep691_json` or its helpers).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Implemented `pipenv/resolver/manifest_cache.py` per design §5.2. Module exports `CachedManifest` (`@dataclass(frozen=True, slots=True)`) and `ParsedManifestCache` with the four documented methods (`get`, `put`, `invalidate`, `clear_all`) plus `SCHEMA_VERSION = 1` class constant. Cache root is caller-supplied — class does NOT default to `~/.cache/pipenv/...` (that decision lives with T9 / T19 per plan instructions). Disk path layout: `<root>/manifests-v<sv>/<sha256(index_url)>/<canonicalize_name(pkg)>.json` (full 64-char sha256 to avoid prefix collisions per T14's collision test). Atomic write: `tempfile.NamedTemporaryFile(delete=False, dir=parent)` → `tmp.write` → `tmp.flush` → `os.fsync` → `tmp.close` → `os.replace(tmp.name, target)`, with best-effort temp-file cleanup on the failure path. Datetimes are timezone-aware UTC throughout (`datetime.now(timezone.utc)`, never naïve). Serialisation helpers: `_candidate_to_json` flattens `frozenset[Hash]` → sorted `list[list[str, str]]`, `frozenset[Tag]` → sorted `list[str]`, `datetime` → ISO 8601; `_candidate_from_json` reads cached `wheel_tags` directly when present (preserving deterministic round-trips even across `packaging.tags` upgrades) and falls back to `Candidate.from_filename` only when the field is missing (forward-compat shim). RED→GREEN evidence: pre-impl `python -c "from pipenv.resolver.manifest_cache import ParsedManifestCache"` raised `ModuleNotFoundError`; post-impl all four plan acceptance scenarios pass inline (round-trip, ttl_seconds=0, schema_version=99 mismatch ignored, mid-write `os.replace` crash leaves prior payload intact). `grep -n "pip._internal" pipenv/resolver/manifest_cache.py` returns no matches (exit 1). Tests deferred to T14 per the revised plan (no smoke file committed).
  - Gotcha for T14: writer-vs-writer test — compare the loaded payload to **either** of the two known candidate-sets rather than asserting which one won. `datetime.now(timezone.utc)` can produce equal timestamps on fast hardware, so "later cached_at wins" is not an invariant; the actual invariant is last-`os.replace`-wins, which the test can't observe ordering on without explicit synchronisation.
  - Gotcha for T14: corruption tests should write raw bytes directly (e.g. `target.write_bytes(b"not json")`) — `get()` swallows `json.JSONDecodeError`, `UnicodeDecodeError`, missing keys, and bad ISO timestamps as misses (returns `None`). The T14 atomic-write test should assert no `<target>.<rand>.tmp` litter on the **success** path; the failure path may legitimately leave one stale temp file behind (documented in the `put` docstring — aggressive cleanup risks racing another writer's temp file in the same directory).
- **files edited/created**:
  - Created: `pipenv/resolver/manifest_cache.py` (CachedManifest + ParsedManifestCache + private serialisation helpers; ~391 LOC).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Implemented `PEP691Client` in `pipenv/resolver/pep691.py` (commit appends the class + two small helpers `_basic_auth_header` / `_get_header` after T4/T5's parser functions; T4/T5 code untouched). Public shape: `PEP691Client(session, *, netrc_path=None, cert=None, verify=True)` constructor + `fetch(index_url, package_name, *, if_none_match=None) -> SimplePageResponse | FetchError`. Module-private internals: `_build_auth_header`, `_dispatch_response`. Module-private constants: `_ACCEPT_HEADER`, `_JSON_CT_PREFIX`, `_HTML_CT_PREFIXES`, `_DEFAULT_CONNECT_TIMEOUT=10.0`, `_DEFAULT_READ_TIMEOUT=30.0`. urllib3 sourced from `pipenv.patched.pip._vendor.urllib3` (NOT `_internal`); grep gate clean: `grep -n "pip._internal" pipenv/resolver/pep691.py` → exit 1 / no matches. Algorithm follows plan brief exactly: (1) canonicalize_name via `pipenv.vendor.packaging.utils`; (2) strip URL creds via T6's `extract_url_credentials`; (3) build `{stripped}/{canonical}/`; (4) compose headers — `Accept` always (with PEP 691 JSON preferred, HTML at q=0.1, text/html at q=0.01); `If-None-Match` when caller supplies; `Authorization: Basic <b64(user:pass).utf-8>` from URL creds OR netrc fallback via T6's `lookup_netrc_auth` (URL creds win when both present); NO `Cache-Control: max-age=0` (deliberate divergence from pip — freshness is the cache layer's job). (5) GET via `self._session.request("GET", url, headers=, timeout=urllib3.Timeout(connect=10, read=30))`; `urllib3.exceptions.HTTPError` (the base of MaxRetryError / ProtocolError / TimeoutError / SSLError / NewConnectionError) and `OSError` → `FetchError(kind="transient", original=exc)`. (6) Status dispatch: 200 → Content-Type-driven parser (case-insensitive prefix match on `application/vnd.pypi.simple.v1+json` → T4; `application/vnd.pypi.simple.v1+html` or `text/html` → T5; anything else → `FetchError("transient", "unexpected content-type: ...")`; JSON `ValueError` on a malformed 200 body → `FetchError("transient", original=exc)`); 304 → `SimplePageResponse(status="not-modified", etag=if_none_match, candidates=())` (carries caller's ETag forward, NOT the response's — RFC 7232 §4.1 servers vary on whether they re-emit it); 404 → `SimplePageResponse(status="missing", candidates=())`; 401/403 → `FetchError(kind="auth")`; other 4xx/5xx → `FetchError(kind="transient")`. Connection hygiene: `response.release_conn()` always called via `finally` (even on parse failure inside the 200 branch), with a defensive try/except so a pool-release failure doesn't mask the return value. Header access: `_get_header` is case-insensitive — works against urllib3's `HTTPHeaderDict` (which has case-insensitive `.get`) AND plain-dict mocks (linear scan fallback). Auth-header value: `"Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")` per RFC 7617. Host extraction for netrc: `urllib3.util.parse_url(stripped_url).host` (port-less hostname is what netrc keys off per RFC 1929). `cert` constructor arg falls back to `client_cert_from_env()` (`$PIP_CLIENT_CERT`); both `cert` and `verify` are stored on `self` but the active session is the source of truth — a phase-3 `Session` rewrite is needed before per-request TLS threading. Logging discipline: `_LOGGER.debug` on transient/parse errors logs only the *stripped* URL; we never log Authorization headers or the unstripped URL. RED→GREEN evidence (inline run): all 5 plan acceptance items pass (1: 200 JSON six.json → 48 candidates matching `_parse_pep691_json` direct call, etag carried; 2: 304 + if_none_match='"abc"' → status='not-modified', etag='"abc"'; 3: 404 → status='missing'; 4: 401 → FetchError(kind='auth'); 5: `https://u:p@host.example/simple` → outgoing URL `https://host.example/simple/six/` (no creds in URL) + `Authorization: Basic dTpw`) plus a 6th smoke (urllib3 `MaxRetryError` → `FetchError(kind='transient', original=exc)`). RED pre-impl: `python -c "from pipenv.resolver.pep691 import PEP691Client"` raised `ImportError`. Six-test smoke file (`tests/unit/test_pep691_client_smoke.py`) authored RED, run GREEN, then deleted before commit per plan — full client test suite lands in T13.
- **files edited/created**:
  - Edited: `pipenv/resolver/pep691.py` (+~410 lines: PEP691Client class with constructor + fetch + two private methods + two module-level helpers + 5 module constants; T4/T5 parser code untouched).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Landed parity test against pip's `Link.from_json` / `Link.from_element` on every fixture in the T2 set on branch `maintenance/code-cleanup-phase5-perf-2026-06`.  10 parametrised tests (6 JSON + 4 HTML) all pass; `pytest tests/unit/test_pep691_parity_fixtures.py -v` is full-green in 0.42 s offline.  Field-by-field comparison covers `filename` (set parity), `url` (vs pip's `url_without_fragment`), `hashes` (sorted tuples of `(algo.lower(), value)`), `requires_python` (with `link.requires_python or None` normalisation), `yanked` (vs pip's `is_yanked` property), and `yanked_reason` (with pip's `""` → `None` normalisation for the "yanked, no reason" case).
  - **Zero observable divergences** on the curated T2 fixture set at the `Candidate`-equivalent field level.  Largest fixture (`cryptography.json` at 3496 files, including 85 yanked entries of which 48 carry free-text reasons) round-trips with zero diffs on every field; ditto `cryptography.html` (3496 anchors).  `django` (781 files JSON+HTML), `tablib` (68 files), `six` (48 files JSON+HTML), `missing-hash` (2 files), `yanked-pkg` (4 files JSON+HTML) all clean.
  - **Representation-level diffs documented in `_known_diffs.md`** and normalised in the test (NOT silent-skipped): (1) pip stores `yanked_reason=""` for "yanked-no-reason" cases while we store `yanked=True + yanked_reason=None` — the test normalises `link.yanked_reason or None if link.is_yanked else None`; (2) `upload_time` is deliberately not compared because pip uses its internal `parse_iso_datetime` helper and we use stdlib `datetime.fromisoformat`, which may produce different `tzinfo` flavours for the same instant (T12 pins upload-time on our side directly against the fixture string); (3) hash algo-name case is lower-cased on both sides in the test for robustness (all current fixtures already use lower-case so it's a no-op today).  No semantic divergences — see the `_known_diffs.md` file for the full justification template and citations (PEP 503 §3, PEP 592 §3, PEP 691 §3).
  - **Production-tree gate verified**: `grep -rn "^[[:space:]]*\(from\|import\).*pip._internal" pipenv/resolver/` returns zero lines (only doc-strings / comments / a string-literal in the logger-name allow-list in `core.py` mention the path).  The deliberate `pip._internal` import lives only in the test file, marked with a `# parity-test-by-design` trailing comment for human-readable review.
  - **Gotchas pinned**: pip's `Link.from_element` signature is `(anchor_attribs, page_url, base_url)` (three positional args; PyPI doesn't emit a `<base>` element so `page_url == base_url` is correct for the T2 fixtures).  Pip's `Link._hashes` is a `dict[str, str]` (not a `Hashes` object) and is the right attribute to read for parity — `Link.as_hashes()` returns a `Hashes` wrapper that's harder to compare structurally.  Pip's `Link.is_yanked` is a property that returns `yanked_reason is not None` (so `""` counts as yanked); the test compares `bool(link.is_yanked)` to `c.yanked` defensively in case pip ever changes to a tri-state.
- **files edited/created**:
  - Created: `tests/unit/test_pep691_parity_fixtures.py` (267 lines; 10 parametrised tests across two test functions covering all six JSON fixtures and all four HTML fixtures; one deliberate `pip._internal` import marked with `parity-test-by-design` trailing comment).
  - Created: `tests/unit/test_pep691_parity_known_diffs.md` (170 lines; documents five representation-level diffs that are normalised in the test, plus a template for future additions and a "current divergences: NONE at the Candidate-output level" header).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Extended T1's 8 smoke tests by 23 new tests grouped into 7 new test classes (`TestAllFieldsConstruction`, `TestEqualitySemantics`, `TestHashabilityForSetDictUse`, `TestHashTupleEquality`, `TestFromFilenameWheelTagVariants`, `TestFromFilenameSdist`, `TestEdgeCases`).  All 31 tests pass.  Coverage of `pipenv/resolver/candidate.py` is **100 %** (36 / 36 statements, 0 missed) — exceeds the ≥95 % floor.  The previously uncovered line (the `ValueError` raised on malformed wheel filenames at module line 169) is now pinned by `TestEdgeCases::test_malformed_wheel_filename_raises_value_error`.  Wheel-tag platform-variant coverage is exhaustive: legacy manylinux2014, PEP 600 `manylinux_X_Y`, musllinux, macosx arm64, win_amd64, pure-Python `py3-none-any`, stable-ABI `cp311-abi3`, and non-manylinux `linux_x86_64` each have their own test.  Sdist branch covered for `.tar.gz` and `.zip`.  Equality + hashability pinned for set / dict use.  `Hash` ↔ plain-tuple equality pinned for O(1) frozenset intersection with Pipfile-pinned hash lists.  Malformed-wheel contract pinned to **propagate `ValueError`** (option (a) — explicit failure over silent tag-less wheel), matching T1's implementation choice.  Zero `pip._internal.*` imports; all `packaging` references go through `pipenv.vendor.packaging.tags`.  T1's 8 smoke tests preserved unchanged.
- **files edited/created**:
  - Edited: `tests/unit/test_candidate.py` (8 → 31 tests; +23 tests, +318 lines; T1's smoke tests preserved verbatim).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Wrote `tests/unit/test_pep691_parser.py` (145 tests, 1284 LOC) on branch `maintenance/code-cleanup-phase5-perf-2026-06` (commit `04afa70e`). 145/145 GREEN on first run.
  - **Parser-surface coverage: 100%** (189/189 statements in lines 1–631 of `pipenv/resolver/pep691.py` — every helper + both top-level parsers).  Total file coverage reads 70% (289 stmts, 86 missed) only because the PEP691Client class (lines 667–1026, ~100 statements) lives in the same module; that surface is **T13's territory** and was deliberately left untouched.
  - Test categories landed (16 test classes, organised by surface):
    - **JSON fixture round-trips** (`TestPep691JsonFixtures`): six=48, django=781, cryptography=3496, tablib=68, yanked-pkg=4, missing-hash=2; wheel-vs-sdist branch on `six.json`; canonical-name preserved.
    - **JSON synthetic edge cases** (`TestPep691JsonSynthetic`): api-version 1.0/2.0/non-string/missing; top-level array/string/missing-name/empty-name/non-string-name/missing-files/files-not-list/non-dict-entries; malformed filename / malformed wheel / missing filename / missing url / empty filename / empty url / non-string filename skipped; invalid JSON body raises (T8's transient-error contract); relative-URL `"../../files/foo.whl"` against `/simple/foo/` → `/files/foo.whl`.
    - **JSON yanked variants** (`TestPep691JsonYanked`): all four `yanked-pkg.json` branches + the JSON-side empty-string contract (NOT yanked, opposite of HTML).
    - **JSON hashes + requires-python** (`TestPep691JsonHashesAndRequiresPython`): `missing-hash.json` fixture; missing `hashes` field; `requires-python` empty-string + non-string normalised to None.
    - **JSON upload-time** (`TestPep691JsonUploadTime`): fixture round-trip + missing field → None.
    - **HTML fixture round-trips** (`TestPep503HtmlFixtures`): six/django/cryptography/yanked-pkg counts match the JSON side.
    - **HTML synthetic edge cases** (`TestPep503HtmlSynthetic`): `#sha256=ABC` fragment, algo-lowercasing, `data-requires-python="&gt;=3.10"` HTML-unescaped, `../../files/` relative URL, anchor-without-href skipped, empty-text falls back to href basename, anchor-text wins over href-basename when present, PEP 658 `data-core-metadata` / `data-dist-info-metadata` IGNORED, unparseable page URL → empty tuple, garbage body → empty tuple (lenient), UTF-8 mojibake recovered.
    - **HTML yanked variants** (`TestPep503HtmlYanked`): absent / empty / with-reason / HTML-entity-unescaping; full `yanked-pkg.html` fixture matrix.
    - **Cross-format parity** (`TestCrossFormatParity`): filename sets equal for all four fixture pairs; hashes-by-filename equal for the synthetic `yanked-pkg` pair.
    - **Helper-level direct tests** (10 classes): `_extract_version` (canonical match, sdist, Django case variant, `python_dateutil`↔`python-dateutil`, unparseable, unknown suffix, prefix mismatch, empty remainder, build-tag wheel, `.tgz`/`.zip`/`.tar.bz2`); `_strip_archive_suffix` (5 suffixes + unknown + no-suffix passthrough); `_normalize_yanked` (8 branches incl. empty-string→False); `_normalize_yanked_html` (4 branches incl. HTML entity unescape); `_normalize_hashes` (empty/non-dict/single/multi/uppercase-algo/non-string-keys-or-values filtered); `_parse_upload_time` (None / "" / non-string / full-microseconds-Z / Z-no-microseconds / no-Z / garbage / malformed-with-Z); `_split_href_hash` (no fragment / fragment-without-`=` / normal / empty-algo / empty-value / algo-lowercased / empty-fragment); `_package_name_from_page_url` (trailing slash, no trailing slash, `Django`→`django` canonicalisation, `Python_Dateutil`→`python-dateutil`, no path segments, empty URL); `_AnchorCollector` (attrs + text, bare-attribute-normalised-to-empty-string, non-anchor tags ignored, chunked text concatenated, handle_data outside anchor ignored); `_build_candidate` / `_build_candidate_from_html` (success / non-string-filename / non-string-url / unparseable-version / no-href / empty-href / non-string-href / empty-text-falls-back / empty-text-and-no-basename / unparseable-filename / malformed-wheel).
  - **Contracts pinned that weren't fully specified upstream**:
    - JSON parser on a non-decodable body **raises** `json.JSONDecodeError` (per T4 docstring: "the caller needs that signal to map a 200 with a malformed body to a `FetchError(\"transient\", ...)`").  Pinned by `test_invalid_json_body_raises`.
    - JSON parser on a top-level array/string returns an empty tuple (not a raise).
    - JSON `meta.api-version` of non-string type (e.g. float `1.0`) is silently tolerated — falls through the `isinstance(api_version, str)` guard and best-effort parses.
    - HTML parser is **lenient on bad bodies** — non-HTML garbage yields an empty tuple, never raises (HTMLParser is lenient by design).
    - HTML parser's UTF-8 fallback uses `errors="replace"`; mojibake recovered.
    - `_build_candidate_from_html` with both empty anchor text **and** an href whose basename is empty (e.g. `"https://x/"`) returns None.
    - `_AnchorCollector`'s bare attribute (`data-yanked` with no `=`) is normalised to empty-string in the collected dict, **distinguishable** from "attribute absent" — this is what lets `_normalize_yanked_html` differentiate the two cases per T5's intentional divergence from JSON.
  - Coverage command: `python -m pytest tests/unit/test_pep691_parser.py --cov=pipenv.resolver.pep691 --cov-report=term-missing -q --override-ini="addopts=-ra"`.  The `--override-ini` is required because `pyproject.toml`'s default `addopts = "-ra --no-cov"` silently disables coverage (already flagged by T11 + T16 agents).
- **files edited/created**:
  - Created: `tests/unit/test_pep691_parser.py` (1284 LOC, 145 tests, 16 test classes).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Implemented `tests/unit/test_manifest_cache.py` on branch `maintenance/code-cleanup-phase5-perf-2026-06`. 47 tests across 9 classes — TestRoundTripBasicAPI (8), TestTTLExpiry (4), TestSchemaVersioning (2), TestAtomicWrite (3), TestConcurrentReaderVsWriter (1), TestConcurrentWriterVsWriter (1), TestURLHashing (3), TestCorruptionRobustness (12), TestCandidateSerialization (4), TestSerialisationHelpers (8). Coverage: `pipenv/resolver/manifest_cache.py` 112 stmts, 0 miss, 100% (target was ≥95%). T7 contracts pinned in tests: (a) raw-byte writes for corruption tests (per T7 hand-off — `target.write_bytes(b"not json")` rather than mutating via JSON round-trip), (b) writer-vs-writer asserts "either payload acceptable" (last-os.replace-wins, ordering unobservable), (c) atomic-write failure path tested for both single-failure (os.replace raises, previous payload intact) and double-failure (os.replace + cleanup os.unlink both raise → original OSError still propagates, exercising the `except OSError: pass` in put's cleanup), (d) no .tmp litter checked only on the success path (100 puts → 0 .tmp files), (e) the cached-wheel-tags-wins-over-filename branch in `_candidate_from_json` is pinned with an injected unrelated tag-string so a future `packaging.tags` upgrade can't silently change behaviour, (f) `etag` field with wrong type sanitises to None rather than misses (separate branch in get() — `etag is not None and not isinstance(etag, str)`). Clock-advancement TTL test patches `datetime` at the module level (subclass with overridden classmethod `now`). Concurrent tests use `threading.Barrier(2)` for writer-vs-writer synchronisation; stress-tested 5x with no flakiness. Test invocation: `python -m pytest tests/unit/test_manifest_cache.py --cov=pipenv.resolver.manifest_cache --cov-report=term-missing -q --override-ini="addopts=-ra"`. Did NOT modify `pipenv/resolver/manifest_cache.py` (instructed not to).
- **files edited/created**:
  - Created: `tests/unit/test_manifest_cache.py` (47 tests, 100% coverage of `pipenv/resolver/manifest_cache.py`).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Implemented `tests/unit/test_resolver_auth.py` on branch
    `maintenance/code-cleanup-phase5-perf-2026-06`.  28 tests covering the
    three T6 helpers; 27 run on Linux (1 Windows-only `_netrc` test is
    `skipif`-gated per pipenv convention).
    - `extract_url_credentials` (9 tests): no-creds passthrough; plain
      `user:pass`; URL-encoded creds decoded (`%40`→`@`, `%23`→`#`);
      empty-URL defensive (`("", None)`); http/ftp schemes preserved;
      query+fragment preserved; port preserved; username-only-no-colon
      yields `("user", "")`.
    - `lookup_netrc_auth` (15 tests, 14 run on Linux): missing-file; empty
      file; matching host; non-matching host; malformed netrc swallowed
      (no raise); `OSError` from `netrc.netrc(...)` swallowed via
      `monkeypatch`; empty-login skipped; `None`-password skipped (via
      monkeypatched fake `netrc.netrc`); `$NETRC` overrides `~/.netrc`;
      explicit `netrc_path` arg overrides `$NETRC`; empty `host=""`
      short-circuits; falls back to `~/.netrc` when no `$NETRC`; skips
      missing explicit path then uses `$NETRC`; `expanduser("~")` returns
      `"~"` branch (no-home); Windows-only `_netrc` filename
      (`skipif(os.name != "nt")`).
    - `client_cert_from_env` (4 tests): unset → `None`; empty → `None`;
      single path duplicated → `(value, value)`; whitespace-only
      `"  "` → returned verbatim as `("  ", "  ")` (pinning T6's choice
      that whitespace is NOT stripped — the plan's open question;
      documented in the test docstring so a future strip change can't
      drift silently).
    - All tests use `tmp_path` + `monkeypatch`; the user's real `~/.netrc`
      is never read (verified by always redirecting `$HOME`/`$USERPROFILE`
      into `tmp_path` for cases where `~` fallback could activate).
    - Coverage:
      `python -m pytest tests/unit/test_resolver_auth.py --override-ini="addopts=-ra" --cov=pipenv.resolver.auth --cov-report=term-missing`
      → `pipenv/resolver/auth.py 53 stmts 2 miss 96% Missing: 84-85`.
      The 2 missing lines are the Windows-only `_netrc` candidate branch
      in `_netrc_candidate_paths`, which the `skipif(os.name != "nt")`
      test correctly exercises on Windows only.  ≥95 % target met on
      Linux; will be 100 % on the Windows CI lane.
    - Zero `pip._internal` imports in the test file (per Initiative G
      gate).
- **files edited/created**:
  - Created: `tests/unit/test_resolver_auth.py` (28 tests; 27 run on
    Linux, 1 Windows-only).

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
- **status**: Completed
- **log**:
  - 2026-05-12: Implemented on branch `maintenance/code-cleanup-phase5-perf-2026-06`.
    - Added a small `_ENV_OVERRIDE_KEYS` registry + `_env_override` helper to
      `pipenv/utils/settings.py`; wired `Settings.get` / `Settings.__getitem__`
      / `Settings.__contains__` to consult it.  Env-var override wins over
      both Pipfile and caller-supplied default (matches pipenv's existing
      `PIPENV_<KEY>` precedence convention used elsewhere).
    - Added `PIPENV_PREFETCH_INDEX_MANIFESTS` to `pipenv/environments.py`
      via the existing `get_from_env(...)` helper, with the verbatim
      docstring from the plan.  `check_for_negation=False` is deliberate
      so the boolean read flows through a single conventional env name.
    - Added 4 unit tests (default-False, Pipfile=true, env=1 override,
      env=0 override) in `tests/unit/test_settings.py` under a new
      T18 section.  TDD: RED on the two env-var-override cases (the
      default-False and Pipfile-true cases happened to pass before the
      helper was wired because they just go through `_table().get`),
      GREEN after implementation.
    - Manually verified the three plan acceptance one-liners against
      `/tmp/test-prefetch-default/Pipfile` (no `[pipenv]` section) and
      `/tmp/test-prefetch-setting/Pipfile` (`prefetch_index_manifests = true`):
      - default-False: `Project().settings.get('prefetch_index_manifests', False)` -> `False`.
      - Pipfile=true: same call against the second Pipfile -> `True`.
      - `PIPENV_PREFETCH_INDEX_MANIFESTS=1 python -c "..."` -> `True`.
    - Full unit suite green: 872 passed, 9 Windows-only skips, 0 failures.
- **files edited/created**:
  - edited: `pipenv/utils/settings.py` (env-override helper + wiring into `get` / `__getitem__` / `__contains__`)
  - edited: `pipenv/environments.py` (new `PIPENV_PREFETCH_INDEX_MANIFESTS` setting)
  - edited: `tests/unit/test_settings.py` (4 new tests covering the three plan acceptance criteria + the falsy-env-override case)

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
