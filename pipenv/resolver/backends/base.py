"""The ``Backend`` protocol for pluggable resolver backends (T_F.5).

A resolver backend is any object that exposes a stable ``name``
attribute, an ``is_available()`` check (so the dispatcher can fail loud
before doing network I/O), and a ``resolve(request)`` method that takes
a typed :class:`pipenv.resolver.schema.ResolverRequest` and returns a
typed :class:`pipenv.resolver.schema.ResolverResponse`.

Per the maintainer sign-off in
``docs/dev/initiative-f-backends-design.md`` (2026-05-12, answer 8),
T_F.5 in this PR is **scaffolding only**: the ``Backend`` protocol, the
registry, the ``[pipenv] resolver`` / ``--resolver`` plumbing, the
fail-loud behaviour.  The actual uv backend implementation (and the
vendor-vs-system decision) is a follow-up (T_F.8 or similar).

The protocol is a stdlib ``typing.Protocol``, not an ``abc.ABC``, so
backends can be plain classes or module-level singletons without
subclassing ceremony.  Structural typing lets a future out-of-tree
third party implement the protocol against the schema-only surface;
*registering* a backend is still gated by the in-tree registry, so the
public exposure is bounded.

The registry is exported here as :data:`REGISTRY` (a dict from name to
backend class).  ``pipenv/resolver/backends/__init__.py`` populates it
on import.  We expose the dict from ``base`` so the registry is a
single shared object — tests can monkey-patch via ``mock.patch.dict``
on either module name and see the same effect.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipenv.resolver.schema import ResolverRequest, ResolverResponse


@runtime_checkable
class Backend(Protocol):
    """A resolver-backend implementation.

    Backends translate between the typed ``ResolverRequest`` envelope
    (the wire contract from T_F.3) and whatever native API they speak.
    The contract is purely schema-shaped.

    Attributes
    ----------
    name : str
        Registry key, e.g. ``"pip"``.  Used by the dispatcher to look
        the backend up.

    Methods
    -------
    is_available() -> bool
        Return ``True`` iff this backend can actually run on this
        machine.  Pip is always available (vendored).  Future external
        backends (uv, etc.) override this to check for the binary on
        ``$PATH``.
    resolve(request: ResolverRequest) -> ResolverResponse
        Run resolution.  Return the typed response.  The implementation
        is expected to honour every load-bearing field on ``request``.
        On any failure the backend should construct a structured
        ``ResolutionError`` or ``InternalError`` rather than raising.
    """

    name: str

    def is_available(self) -> bool: ...

    def resolve(self, request: ResolverRequest) -> ResolverResponse: ...


# Single shared registry.  The ``backends/__init__.py`` populates this
# on import with the in-tree backends.  Keeping it here (rather than on
# ``__init__``) lets test code patch via ``mock.patch.dict`` against a
# single canonical reference no matter which module the patch targets.
REGISTRY: dict[str, Backend] = {}
