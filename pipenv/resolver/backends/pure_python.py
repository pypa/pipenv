"""``pure-python`` resolver backend (Initiative G Phase 3).

Implements the Initiative F ``Backend`` protocol over the
``PurePythonProvider`` (T3–T8) + ``MetadataFetcher`` (T2) +
``Requirement`` (T1) chain.

Translates ``ResolverRequest`` → ``Requirement`` set → drive
``resolvelib.Resolver`` → ``ResolverResponse``.  Falls back to the
pip backend transparently when an sdist-only candidate is
encountered (design §3.2 + Q-A) — emitting one info-level log so
users can audit fallbacks via ``pipenv lock --verbose``.

See ``docs/dev/initiative-g-phase3-design.md`` §5.4 for the design
and ``initiative-g-phase3-plan.md`` T9 for the implementation brief.

NOT YET IMPLEMENTED — branch scaffolding only.
Phase 3 implementation lands in T9; registry wiring lands in T10.
"""

# T9: PurePythonBackend implementing Initiative F's Backend protocol.
# T10: Register under name "pure-python" in
# ``pipenv/resolver/backends/__init__.py``.
