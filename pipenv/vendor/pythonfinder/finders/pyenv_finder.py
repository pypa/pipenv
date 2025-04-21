from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ..environment import PYENV_INSTALLED, PYENV_ROOT

if TYPE_CHECKING:
    from pathlib import Path
from ..utils.path_utils import ensure_path
from ..utils.version_utils import parse_pyenv_version_order
from .path_finder import PathFinder


class PyenvFinder(PathFinder):
    """
    Finder that searches for Python in pyenv installations.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        ignore_unsupported: bool = True,
    ):
        """
        Initialize a new PyenvFinder.

        Args:
            root: The root directory of the pyenv installation.
            ignore_unsupported: Whether to ignore unsupported Python versions.
        """
        if not PYENV_INSTALLED:
            super().__init__(paths=[], ignore_unsupported=ignore_unsupported)
            return

        self.root = ensure_path(root or PYENV_ROOT)
        self.versions_dir = self.root / "versions"

        if not self.versions_dir.exists():
            super().__init__(paths=[], ignore_unsupported=ignore_unsupported)
            return

        # Get the pyenv version order
        version_order = parse_pyenv_version_order()

        # Get all version directories
        version_dirs = {}
        for path in self.versions_dir.iterdir():
            if path.is_dir() and path.name != "envs":
                version_dirs[path.name] = path

        # Sort the version directories according to the pyenv version order
        paths = []

        # First add the versions in the pyenv version order
        for version in version_order:
            if version in version_dirs:
                bin_dir = version_dirs[version] / ("" if os.name == "nt" else "bin")
                if bin_dir.exists():
                    paths.append(bin_dir)
                    del version_dirs[version]

        # Then add the remaining versions
        for version_dir in version_dirs.values():
            bin_dir = version_dir / ("" if os.name == "nt" else "bin")
            if bin_dir.exists():
                paths.append(bin_dir)

        super().__init__(
            paths=paths,
            only_python=True,
            ignore_unsupported=ignore_unsupported,
        )
