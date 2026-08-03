"""pipenv.resolver — subprocess entry point + typed wire-schema package.

T_F.3 Wave B1 rewrote the subprocess entry to consume a typed
:class:`pipenv.resolver.schema.ResolverRequest` and produce a typed
:class:`pipenv.resolver.schema.ResolverResponse`.  The legacy
``Entry`` / ``PackageRequirement`` / ``PackageSource`` dataclasses and
``process_resolver_results`` helper are gone — their behaviour is
absorbed into :meth:`LockedRequirement.from_install_requirement`
(constructor at the wire boundary) and the typed resolve driver
:func:`pipenv.resolver.main.resolve_packages`.

The remaining re-exports here are the *current* public surface used by
the rest of the pipenv codebase (notably the in-process branch in
``pipenv/utils/resolver.py``).
"""

from pipenv.resolver.main import (
    _main,
    main,
    resolve_packages,
    which,
)

__all__ = [
    "_main",
    "main",
    "resolve_packages",
    "which",
]
