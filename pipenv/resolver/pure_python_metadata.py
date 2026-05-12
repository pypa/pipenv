"""Wheel ``METADATA`` fetcher for the pure-Python resolver backend
(Initiative G Phase 3).

Two-tier strategy:

1. PEP 658 fast path when the index advertises ``core-metadata``.
2. Wheel-head HTTP-range fallback for indexes that don't.

Plus a small on-disk cache at
``<PIPENV_CACHE_DIR>/pipenv-manifests/metadata-v1/`` keyed by
``sha256(wheel_url)``.  Wheels are immutable on PyPI, so cache entries
are valid forever.

See ``docs/dev/initiative-g-phase3-design.md`` §5.2 for the design
and ``initiative-g-phase3-plan.md`` T2 for the implementation brief.

NOT YET IMPLEMENTED — branch scaffolding only.
Phase 3 implementation lands in T2.
"""

# T2: ``CoreMetadata`` dataclass + ``fetch_metadata`` two-tier flow
# + ``MetadataCache``.  Plan file ``initiative-g-phase3-plan.md`` T2 is
# the implementation brief.
