The pure-Python resolver backend no longer stalls on large dependency sets
with deep conflicts.  Parsed package manifests are now kept in memory for
the duration of a resolve, and candidate lookups are memoized on every
input that affects their result (as pip's finder does), so backtracking no
longer re-reads the on-disk cache or re-filters thousands of versions for
the same unsatisfiable query.  Locking the benchmark's Sentry requirement
set went from not finishing in over ten minutes to about ten seconds with
a warm cache, with an identical lock result.
