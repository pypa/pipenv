"""The pip resolver backend (T_F.5).

A thin wrapper around the canonical resolve flow that previously lived
inline in :func:`pipenv.resolver.core.resolve_for_pipenv`.  T_F.5 turns
that flow into the body of ``PipBackend.resolve``; the dispatcher in
``core`` now routes through the registry instead of calling the flow
directly.  **No behaviour change** — this is a structural refactor.

Per the maintainer sign-off in
``docs/dev/initiative-f-backends-design.md`` (2026-05-12), the pip
backend is the only backend shipped in this PR.  The uv backend port
from ``origin/uv-backend`` becomes a future initiative (T_F.8 or
similar).
"""
from __future__ import annotations

from pipenv.resolver.schema import ResolverRequest, ResolverResponse


class PipBackend:
    """Resolver backend that drives pipenv's vendored pip.

    The implementation delegates to :func:`pipenv.resolver.core._pip_resolve`,
    which carries the original resolve plumbing (log capture, deadline
    guard, marker-env patching, exception translation).  ``PipBackend``
    itself contains no logic — its purpose in the registry is to make
    dispatch uniform, not to introduce new behaviour.
    """

    name: str = "pip"

    def is_available(self) -> bool:
        """The pip backend is always available — pip is vendored inside
        the pipenv distribution; there is no external binary to
        discover.
        """
        return True

    def resolve(self, request: ResolverRequest) -> ResolverResponse:
        """Delegate to the canonical pip resolve flow.

        The flow lives in :mod:`pipenv.resolver.core` rather than here
        so that callers can still monkey-patch
        ``core.resolve_packages`` from tests — every existing test
        seam continues to work without modification.
        """
        # Lazy import to avoid a circular import: ``pipenv.resolver.core``
        # imports from ``pipenv.resolver.backends`` (the registry).
        from pipenv.resolver.core import _pip_resolve

        return _pip_resolve(request)
