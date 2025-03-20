from __future__ import annotations

from .base_finder import BaseFinder
from .path_finder import PathFinder
from .system_finder import SystemFinder
from .pyenv_finder import PyenvFinder
from .asdf_finder import AsdfFinder

__all__ = [
    "BaseFinder",
    "PathFinder",
    "SystemFinder",
    "PyenvFinder",
    "AsdfFinder",
]

# Import Windows registry finder if on Windows
import os
if os.name == "nt":
    from .windows_registry import WindowsRegistryFinder
    __all__.append("WindowsRegistryFinder")
