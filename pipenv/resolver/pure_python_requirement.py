"""Typed ``Requirement`` model for the pure-Python resolver backend
(Initiative G Phase 3).

Represents one constraint in the resolution graph as a frozen
dataclass — replaces pip's ``InstallRequirement`` for the in-tree
``resolvelib.Provider`` path.

See ``docs/dev/initiative-g-phase3-design.md`` §5.1 for the design
and ``initiative-g-phase3-plan.md`` T1 for the implementation brief.

NOT YET IMPLEMENTED — branch scaffolding only.
Phase 3 implementation lands in T1.
"""

# T1: Frozen dataclass per design §5.1.  Plan file
# ``initiative-g-phase3-plan.md`` T1 is the implementation brief.
