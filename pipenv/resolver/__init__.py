"""pipenv.resolver — subprocess entry point + typed wire-schema package.

This package replaces the historical single-file ``pipenv/resolver.py``.
T_F.3 Wave A turned the file into a package so the typed schema module
(:mod:`pipenv.resolver.schema`) can live next to the subprocess entry
(:mod:`pipenv.resolver.main`) without a name collision.

Historical symbols (``main``, ``_main``, ``Entry``, ``PackageRequirement``,
``resolve_packages``, ``process_resolver_results``, ``which``) are re-exported
here so existing imports — including the three test modules at
``tests/unit/test_dependencies.py``, ``tests/unit/test_resolver_regressions.py``,
``tests/unit/test_locking_no_mutation.py`` — continue to work.  T_F.3 Wave B
deletes the legacy symbols (``Entry``, ``PackageRequirement``,
``process_resolver_results``); the re-export shim shrinks accordingly when
those deletions land.
"""

from pipenv.resolver.main import (
    Entry,
    PackageRequirement,
    PackageSource,
    _main,
    main,
    process_resolver_results,
    resolve_packages,
    which,
)

__all__ = [
    "Entry",
    "PackageRequirement",
    "PackageSource",
    "_main",
    "main",
    "process_resolver_results",
    "resolve_packages",
    "which",
]
