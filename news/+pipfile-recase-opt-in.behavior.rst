Pipfile name recasing is now opt-in.  Previously, every ``pipenv install``
walked ``packages`` / ``dev-packages`` and made one synchronous PyPI HTTP
request per unknown package name to learn its display capitalization, then
rewrote the Pipfile entry to match.  On a fresh ``install -r
requirements.txt`` of ~100 packages this added roughly 3 seconds of
sequential network latency on top of the resolve, regardless of cache
state.  The lookup is now skipped by default; package names you wrote
into your Pipfile are preserved as-is (PEP 503 normalization still
governs resolution, so behavior is unchanged for matching purposes).
Set ``PIPENV_RECASE_PIPFILE=1`` to opt back into the previous PyPI
casing lookups.
