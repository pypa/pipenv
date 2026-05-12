"""The pluggable-resolver-backend registry (T_F.5).

Per the maintainer sign-off in
``docs/dev/initiative-f-backends-design.md`` (2026-05-12), T_F.5 in
this PR is **scaffolding only**: the ``Backend`` protocol, the
registry, the ``[pipenv] resolver`` / ``--resolver`` / ``PIPENV_RESOLVER``
plumbing, the fail-loud behaviour when an unknown / unavailable backend
is requested.  The actual uv backend implementation is a follow-up
effort (T_F.8 or similar); this package ships with one in-tree
backend: ``"pip"``.

Adding a backend is intentionally an in-tree edit: register it in
:data:`REGISTRY` below.  No ``entry_points`` discovery, no plugin
hook — that's a separate initiative gated on a credible third backend
appearing (design §3.2).
"""
from __future__ import annotations

from pipenv.resolver.backends.base import REGISTRY, Backend
from pipenv.resolver.backends.pip import PipBackend

# Default backend used when no explicit selection has been made via CLI,
# env var, or Pipfile.  Kept at module scope so the dispatcher in
# ``pipenv.resolver.core`` can reference it.
DEFAULT_BACKEND_NAME = "pip"

# Populate the registry on import.  The dict object lives on
# ``pipenv.resolver.backends.base`` so it is shared — tests that
# monkey-patch via ``mock.patch.dict`` see the same dict no matter
# which module they reach for.
REGISTRY["pip"] = PipBackend


def get_backend(name: str) -> Backend:
    """Look up a backend by registry key.

    Parameters
    ----------
    name
        Backend name, e.g. ``"pip"``.

    Returns
    -------
    Backend
        The backend instance (NOT the class).  Instantiated on demand
        so the registry can hold either classes or module-level
        singletons; both shapes round-trip cleanly through this call.

    Raises
    ------
    KeyError
        If ``name`` is not registered.  The message names the bad
        backend AND lists the available ones so users can recover
        from a typo without having to read the source.  This is the
        "fail-loud" behaviour required by the maintainer sign-off
        (2026-05-12, answer 4).
    """
    if name not in REGISTRY:
        available = ", ".join(sorted(REGISTRY)) or "(none registered)"
        raise KeyError(
            f"unknown resolver backend {name!r}; available: {available}"
        )
    entry = REGISTRY[name]
    # The registry may hold either backend *classes* (the in-tree shape
    # used for ``PipBackend``) or pre-instantiated *singletons* (useful
    # for tests and for future backends that need to hold connection
    # state across calls).  Instantiate if we got a class, otherwise
    # return the instance directly.
    if isinstance(entry, type):
        return entry()
    return entry


def list_backends() -> list[str]:
    """Return the sorted list of registered backend names."""
    return sorted(REGISTRY)


__all__ = [
    "Backend",
    "DEFAULT_BACKEND_NAME",
    "PipBackend",
    "REGISTRY",
    "get_backend",
    "list_backends",
]
