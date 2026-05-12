# Initiative B Triage: URL/path helpers in `pipenv/utils/fileutils.py`

Narrow audit of the three URL/path converters in
`pipenv/utils/fileutils.py`: `is_file_url`, `url_to_path`, `path_to_url`.
`is_valid_url` also lives in this file but is the duplicate flagged in
Initiative A (T_A.2) and is **out of scope** here.

## Domain-boundary rule

Initiative A draws the line as: URL/scheme concerns belong in
`pipenv/utils/internet.py`; filesystem-path concerns belong in
`pipenv/utils/fileutils.py`. The three symbols below all sit on the
boundary because they translate between the two. Under the rule, the
deciding question is "which side is doing the heavy lifting?". For these
three, the answer is the filesystem side — they exist specifically to
move a `Path` across the `file://` boundary, and only the `file:` scheme
is meaningful to them. A generic URL utility that knew nothing about
local paths could not implement them. So they stay in `fileutils.py`.

## Per-symbol recommendation

- **`is_file_url`** — Keep in `fileutils.py`. It is a scheme check, but
  it exists only to gate the `file://`-vs-everything-else branch in
  `open_file`, `url_to_path`, and (in callers) path-vs-URL dispatch.
  No external (non-test) callers in `pipenv/` outside this module today.
- **`url_to_path`** — Keep in `fileutils.py`. Returns a `pathlib.Path`,
  handles UNC netloc reconstruction, and is the inverse of `path_to_url`.
  External callers: `pipenv/utils/requirementslib.py` (2 sites).
- **`path_to_url`** — Keep in `fileutils.py`. Operates on a `Path`, calls
  `normalize_drive` (also in `fileutils.py`), and emits a `file://` URI.
  Only internal caller today is `open_file` in the same module.

## Adjacent finding (not in scope, flagged for later)

`pipenv/utils/shell.py:104` defines a **second** `path_to_url` with a
different implementation (`Path(...).as_uri()` vs. the quoting-aware
version here) and no callers in `pipenv/`. This is a duplicate-name
hazard analogous to the `is_valid_url` case in Initiative A; recommend
folding into Initiative A's URL/scheme consolidation pass rather than
opening a new task here.
