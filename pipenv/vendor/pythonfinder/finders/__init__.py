from __future__ import annotations

from .asdf_finder import AsdfFinder
from .base_finder import BaseFinder
from .path_finder import PathFinder
from .pyenv_finder import PyenvFinder
from .system_finder import SystemFinder

__all__ = [
    "BaseFinder",
    "PathFinder",
    "SystemFinder",
    "PyenvFinder",
    "AsdfFinder",
]

# Import Windows-specific finders if on Windows
import os

if os.name == "nt":
    from .windows_registry import WindowsRegistryFinder
    from .py_launcher_finder import PyLauncherFinder

    __all__.extend(["WindowsRegistryFinder", "PyLauncherFinder"])
