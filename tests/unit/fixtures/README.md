# `tests/unit/fixtures/` — Test fixture provenance

This directory holds **frozen** copies of upstream artifacts used by the
unit-test suite.  No live network is consulted during `pytest` runs;
fixtures are the offline parity baseline.

The PEP 691 (`pep691/`) and PEP 503 (`pep503/`) trees were introduced
for Initiative G phase 1, task T2 (pure-Python simple-API client).

## Real-PyPI snapshots — captured 2026-05-12

Each file below was fetched from `https://pypi.org/simple/<name>/` with
the documented `Accept` header.  Re-fetch with:

```bash
curl -H 'Accept: application/vnd.pypi.simple.v1+json' -o <path> <url>
curl -H 'Accept: text/html'                            -o <path> <url>
```

If a fixture's behaviour changes upstream (e.g., a release is yanked,
a wheel is removed, the `meta.api-version` rolls forward to `"2.x"`),
**treat the diff as test signal — investigate before re-baselining.**
The whole point of frozen fixtures is to surface upstream churn
explicitly rather than silently re-record over it.

### PEP 691 JSON (`Accept: application/vnd.pypi.simple.v1+json`)

| Path                                | Source URL                                   | Size (bytes) | Notes                                  |
| ----------------------------------- | -------------------------------------------- | -----------: | -------------------------------------- |
| `pep691/six.json`                   | https://pypi.org/simple/six/                 |       24,065 | Small, stable package; 48 file entries |
| `pep691/django.json`                | https://pypi.org/simple/django/              |      401,061 | Many releases; 781 file entries        |
| `pep691/cryptography.json`          | https://pypi.org/simple/cryptography/        |    2,350,042 | Many platform wheels; 3,496 entries    |
| `pep691/tablib.json`                | https://pypi.org/simple/tablib/              |       32,763 | Sdist + wheel mix; 68 entries          |

All four were served with `meta.api-version` = `"1.4"` on capture day.

### PEP 503 HTML (`Accept: text/html`)

| Path                                | Source URL                            | Size (bytes) |
| ----------------------------------- | ------------------------------------- | -----------: |
| `pep503/six.html`                   | https://pypi.org/simple/six/          |       16,337 |
| `pep503/django.html`                | https://pypi.org/simple/django/       |      284,321 |
| `pep503/cryptography.html`          | https://pypi.org/simple/cryptography/ |    1,945,696 |

## Synthetic fixtures — hand-crafted

These do **not** correspond to real PyPI packages; they exercise edge
cases the upstream fixtures may not currently surface.

| Path                            | Edge case exercised                                                                                                  |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `pep691/yanked-pkg.json`        | `yanked` field: boolean `true`, boolean `false` (control), and the string-with-reason form (PEP 592 §yanked release) |
| `pep691/missing-hash.json`      | File entry whose `hashes` object is `{}` (empty) — parser must not crash; downstream code must handle the gap        |
| `pep503/yanked-pkg.html`        | PEP 503 anchor-tag form of yanked, including `data-yanked="<reason>"` and empty-`data-yanked` (boolean-true variant) |

The synthetic JSON files declare `meta.api-version` = `"1.0"` so they
stay on the conservative end of the supported range; the parser must
accept any `"1.x"` value.

## Re-generation procedure (for future maintainers)

1. Re-run the `curl` commands above with the same `Accept` headers.
2. Diff the new file against the old.  If the diff is purely additive
   (new releases appended), update `README.md`'s row sizes and commit.
3. If the diff includes deletions, mutations of existing entries, or
   `meta.api-version` changes: **stop and investigate** — either an
   upstream release was retroactively edited (rare but happens with
   yanks) or the simple-API format itself rolled forward.  Either case
   warrants a code-side review, not a silent re-baseline.
4. Never re-fetch the synthetic fixtures from PyPI; they intentionally
   reference `files.example.invalid` URLs and contain edge-case data
   that does not exist upstream.
