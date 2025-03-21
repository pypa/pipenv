from __future__ import annotations

from typing import TYPE_CHECKING

from ..environment import ASDF_DATA_DIR, ASDF_INSTALLED

if TYPE_CHECKING:
    from pathlib import Path
from ..utils.path_utils import ensure_path
from ..utils.version_utils import parse_asdf_version_order
from .path_finder import PathFinder


class AsdfFinder(PathFinder):
    """
    Finder that searches for Python in asdf installations.
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        ignore_unsupported: bool = True,
    ):
        """
        Initialize a new AsdfFinder.

        Args:
            data_dir: The data directory of the asdf installation.
            ignore_unsupported: Whether to ignore unsupported Python versions.
        """
        if not ASDF_INSTALLED:
            super().__init__(paths=[], ignore_unsupported=ignore_unsupported)
            return

        self.data_dir = ensure_path(data_dir or ASDF_DATA_DIR)
        self.installs_dir = self.data_dir / "installs" / "python"

        if not self.installs_dir.exists():
            super().__init__(paths=[], ignore_unsupported=ignore_unsupported)
            return

        # Get the asdf version order
        version_order = parse_asdf_version_order()

        # Get all version directories
        version_dirs = {}
        for path in self.installs_dir.iterdir():
            if path.is_dir():
                version_dirs[path.name] = path

        # Sort the version directories according to the asdf version order
        paths = []

        # First add the versions in the asdf version order
        for version in version_order:
            if version in version_dirs:
                bin_dir = version_dirs[version] / "bin"
                if bin_dir.exists():
                    paths.append(bin_dir)
                    del version_dirs[version]

        # Then add the remaining versions
        for version_dir in version_dirs.values():
            bin_dir = version_dir / "bin"
            if bin_dir.exists():
                paths.append(bin_dir)

        super().__init__(
            paths=paths,
            only_python=True,
            ignore_unsupported=ignore_unsupported,
        )
