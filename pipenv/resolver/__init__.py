"""pipenv.resolver — subprocess entry point + typed wire-schema package.

T_F.3 Wave B1 rewrote the subprocess entry to consume a typed
:class:`pipenv.resolver.schema.ResolverRequest` and produce a typed
:class:`pipenv.resolver.schema.ResolverResponse`.  The legacy
``Entry`` / ``PackageRequirement`` / ``PackageSource`` dataclasses and
``process_resolver_results`` helper are gone — their behaviour is
absorbed into :meth:`LockedRequirement.from_install_requirement`
(constructor at the wire boundary) and the typed resolve driver
:func:`pipenv.resolver.main.resolve_packages`.

Initiative G phase 1 (T17) re-exports the pure-Python simple-API
client surface so callers do ``from pipenv.resolver import
PEP691Client`` rather than reaching into the submodules.  These
modules are standalone in phase 1; phases 2/3 wire them into the
``do_lock`` cache-prime bridge and the resolvelib-backed provider.
"""

from pipenv.resolver.candidate import Candidate, Hash
from pipenv.resolver.fetcher import ParallelFetcher
from pipenv.resolver.main import (
    _main,
    main,
    resolve_packages,
    which,
)
from pipenv.resolver.manifest_cache import CachedManifest, ParsedManifestCache
from pipenv.resolver.pep691 import PEP691Client
from pipenv.resolver.pep691_types import FetchError, SimplePageResponse

__all__ = [
    # Initiative G phase 1 (T17) — pure-Python simple-API client surface.
    "Candidate",
    "CachedManifest",
    "FetchError",
    "Hash",
    "PEP691Client",
    "ParallelFetcher",
    "ParsedManifestCache",
    "SimplePageResponse",
    # Subprocess entry point + typed-schema bridge.
    "_main",
    "main",
    "resolve_packages",
    "which",
]
