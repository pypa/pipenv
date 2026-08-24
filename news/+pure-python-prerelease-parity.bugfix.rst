The pure-Python resolver backend (``[pipenv] resolver_backend =
"pure-python"``) now mirrors pip's two-pass prerelease filter: the
first pass strictly excludes prereleases (matching pip's
``CandidateEvaluator.get_applicable_candidates`` default), and only
falls back to admitting them when no stable version satisfies the
merged specifier.  Previously every prerelease leaked through under
plain ``>=X`` constraints because the per-candidate
``SpecifierSet.contains(..., prereleases=None)`` shape applies
PEP 440's "no final release matched — accept the prerelease"
fallback on a one-element iterable; pip dodges this by filtering the
full candidate list at once.  Bench-fixture trigger: ``billiard``,
``hiredis``, and ``sentry-sdk`` were resolving to pre-release
versions (``4.3.0rc1``, ``3.4.0.dev0``, ``3.0.0a7``) where pip
picked the stable below.
