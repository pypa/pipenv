# PEP 691 / PEP 503 parser parity — known divergences from pip

This file documents intentional differences in observable output
between `pipenv.resolver.pep691`'s parsers (`_parse_pep691_json`,
`_parse_pep503_html`) and pip's `Link.from_json` /
`Link.from_element` on the T2 fixture set.

Companion test: `tests/unit/test_pep691_parity_fixtures.py`.  That
test asserts field-by-field parity; any entry below either:

1. **shows up as a normalised comparison** in the test (e.g. pip's
   `yanked_reason=""` vs our `yanked_reason=None` for the
   yanked-with-no-reason case — both encode the same fact, just
   differently; the test normalises before comparing), or
2. **is explicitly skipped in the test** with a citation to this
   file.

Silent skips are forbidden: any new divergence MUST be added here
with a written justification (cite a PEP, a pip commit, or a
ratified spec — not just "we chose differently").

Scope: T2 fixtures only.  Live-PyPI parity across 20 real packages
is deferred to Phase 3 per design §7.4.

---

## Current divergences on the T2 fixture set: NONE (at the
## Candidate-output level)

As of T10 (2026-05-12), every fixture in
`tests/unit/fixtures/pep691/*.json` and
`tests/unit/fixtures/pep503/*.html` round-trips through both
parsers with **zero observable divergence** at the
`Candidate`-equivalent field level (`url`, `hashes`,
`requires_python`, `yanked`, `yanked_reason`).  See the test's
`test_pep691_json_parity_with_pip` and
`test_pep503_html_parity_with_pip` parametrisations.

What follows below are the **representation-level** differences
that the test deliberately normalises before comparing, so that
"same meaning, different encoding" doesn't trigger a false-positive
parity failure.  These are NOT bugs in either parser — they're
data-model choices, pinned here so a future reader doesn't
mistake a normalisation for a silent skip.

---

### 1. `yanked_reason` representation for the "yanked, no reason" case

* **pip's encoding**: `Link.yanked_reason = ""` when the JSON
  payload says `"yanked": true` (see
  `pipenv/patched/pip/_internal/models/link.py` around the
  `from_json` classmethod, where `yanked_reason = ""` is set
  explicitly when the input is a boolean `True`).  On HTML, an
  attribute spelt `data-yanked=""` likewise stores `""`.
* **Our encoding**: `Candidate.yanked_reason = None`, paired with
  `Candidate.yanked = True`.  The presence-vs-absence of the reason
  is carried by the boolean; the reason field stays canonical
  (`Optional[str]`, empty-string never a valid value).
* **Why this is fine**: both encodings round-trip to the same
  user-visible fact ("yanked, no reason"); pip's `is_yanked`
  property returns `True` for both `""` and `"reason text"`, and
  our `Candidate.yanked` is set to `True` in the same cases.  The
  parity test normalises pip's `""` → `None` via
  `link.yanked_reason or None if link.is_yanked else None` before
  comparing.
* **Citation**: PEP 592 §3 (the "Yank" field) treats yank-with-no-
  reason and yank-with-reason as the same operation distinguished
  by an optional free-text payload — both encodings honour that.

### 2. JSON `"yanked": ""` (empty-string-yanked) interpretation

* **pip's encoding** (per `Link.from_json` in the vendored pip):
  `if yanked_reason and not isinstance(yanked_reason, str):` —
  empty string is falsy, so pip falls into the `else` branch and
  sets `yanked_reason = None` (treated as **not yanked**).
* **Our encoding** (per `_normalize_yanked` in
  `pipenv/resolver/pep691.py`): empty-string-yanked is
  conservatively treated as **not yanked** for the same reason
  (the JSON ambiguity is best resolved by "trust the boolean and
  the non-empty string, ignore noise").
* **Why this is fine**: both parsers agree on the same outcome.
  The T2 fixture set does not exercise this code path (none of
  the JSON fixtures emit `"yanked": ""`); cryptography uses bool
  `True`/`False` and free-text strings only.  If a future fixture
  or a Phase-3 live-PyPI snapshot turns up an empty-string-yanked
  entry, the existing assertions will validate that we still
  agree.

### 3. HTML `data-yanked=""` (empty-attribute-yanked) interpretation

* **pip's encoding**: `Link.yanked_reason = ""`, `Link.is_yanked
  = True`.
* **Our encoding**: `Candidate.yanked = True`,
  `Candidate.yanked_reason = None`.
* **Why this is fine**: HTML's *presence* of the attribute is the
  unambiguous yanked signal (per PEP 592 §3 aligned to PEP 503's
  HTML serialisation), and both parsers honour that.  The parity
  test normalises in the same way as item 1.
* **Citation**: PEP 503 §3 + PEP 592 §3.  Pinned in
  `_normalize_yanked_html`'s docstring in
  `pipenv/resolver/pep691.py`.

### 4. Hash-algorithm name case

* **pip's encoding**: preserves the algo case as supplied by the
  index (e.g. `{"sha256": ...}` stays lower-case; a hypothetical
  `{"SHA256": ...}` would be stored upper-case).
* **Our encoding**: always lower-cases the algo at parse time
  (per PEP 691 §3 which specifies lower-case).
* **Why this is fine**: every fixture in the T2 set (and every
  real-PyPI response we've ever seen) uses lower-case algo names,
  so the parity test's `sorted([...])` comparison is a no-op
  here.  The test still calls `algo.lower()` on the pip side
  defensively in `_pip_link_hashes`, so a future PyPI bug serving
  `"SHA256"` would not cause a false parity failure.

### 5. `upload_time` representation

* **pip's encoding**: uses pip's internal `parse_iso_datetime`
  helper to parse the ISO-8601 string into a `datetime`.
* **Our encoding**: uses stdlib `datetime.fromisoformat` (with a
  manual `Z` → `+00:00` fallback for Python < 3.11 compatibility).
* **Why we don't compare**: the resulting `datetime` objects may
  have different `tzinfo` flavours (UTC instance vs. an offset
  instance) even when they represent the same instant; T12 pins
  upload-time on our side directly against the fixture string,
  which is the load-bearing assertion for that field.  Parity
  against pip's choice of `tzinfo` constructor is not a useful
  invariant — both sides represent the same wall-clock UTC
  moment.
* **Citation**: pip's `parse_iso_datetime` is an implementation
  detail of the vendored pip and not part of any spec.  Pinning
  to pip's choice would couple us to pip's internal helpers,
  which is the opposite of Initiative G's goal.

---

## How to add a new divergence

If a future test run (Phase-3 live-PyPI parity audit, a new
fixture, etc.) surfaces a real divergence — i.e., one parser
produces a `Candidate` field the other doesn't, and the difference
is NOT a re-encoding of the same fact — do not skip the assertion.
Add an entry here following the template:

```markdown
### <N>. <short title>

* **pip's encoding**: <what pip does>
* **Our encoding**: <what we do>
* **Why this is fine** (or: **Why we accept the divergence**):
  <justification>
* **Citation**: <PEP / pip commit / fixture provenance>
```

…and then either (a) normalise both sides in the test before
comparing (preferred — represents "same meaning, different
encoding"), or (b) `pytest.skip(...)` that specific assertion
inside the parametrised test with a clear pointer to the entry
number above (only when the divergence really is a wontfix).
