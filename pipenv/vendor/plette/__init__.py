try:
    from ._version import __version__
except ImportError:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version

    try:
        __version__ = version("plette")
    except PackageNotFoundError:
        __version__ = "0.0.0"

__all__ = [
    "__version__",
    "Lockfile", "Pipfile",
]

from .lockfiles import Lockfile
from .pipfiles import Pipfile
