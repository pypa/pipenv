from __future__ import annotations

import os
import sys
from pathlib import Path

from ..utils.path_utils import ensure_path, exists_and_is_accessible
from .path_finder import PathFinder


class SystemFinder(PathFinder):
    """
    Finder that searches for Python in the system PATH.
    """

    def __init__(
        self,
        paths: list[str | Path] | None = None,
        global_search: bool = True,
        system: bool = False,
        only_python: bool = False,
        ignore_unsupported: bool = True,
    ):
        """
        Initialize a new SystemFinder.

        Args:
            paths: List of paths to search for Python executables.
            global_search: Whether to search in the system PATH.
            system: Whether to include the system Python.
            only_python: Whether to only find Python executables.
            ignore_unsupported: Whether to ignore unsupported Python versions.
        """
        paths = list(paths) if paths else []

        # Add paths from PATH environment variable
        if global_search and "PATH" in os.environ:
            paths.extend(os.environ["PATH"].split(os.pathsep))

        # Add system Python path
        if system:
            system_path = Path(sys.executable).parent
            if system_path not in paths:
                paths.append(system_path)

        # Add virtual environment path
        venv = os.environ.get("VIRTUAL_ENV")
        if venv:
            bin_dir = "Scripts" if os.name == "nt" else "bin"
            venv_path = Path(venv).resolve() / bin_dir
            if venv_path.exists() and venv_path not in paths:
                paths.insert(0, venv_path)

        # Convert paths to Path objects and filter out non-existent paths
        resolved_paths = []
        for path in paths:
            path_obj = ensure_path(path)
            if exists_and_is_accessible(path_obj):
                resolved_paths.append(path_obj)

        super().__init__(
            paths=resolved_paths,
            only_python=only_python,
            ignore_unsupported=ignore_unsupported,
        )
