from __future__ import annotations

import sys


TYPE_CHECKING = False

if TYPE_CHECKING:
    from importlib import metadata
elif sys.version_info >= (3, 10, 2):
    from importlib import metadata  # pragma: no cover
else:  # pragma: no cover
    try:
        import importlib_metadata as metadata
    except ModuleNotFoundError:
        # helps bootstrapping when dependencies aren't installed
        from importlib import metadata


__all__ = [
    'metadata',
]
