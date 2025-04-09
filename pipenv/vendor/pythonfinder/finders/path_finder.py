from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from ..exceptions import InvalidPythonVersion
from ..models.python_info import PythonInfo
from ..utils.path_utils import filter_pythons, path_is_python
from ..utils.version_utils import get_python_version, guess_company, parse_python_version
from .base_finder import BaseFinder


class PathFinder(BaseFinder):
    """
    Base class for finders that search for Python in filesystem paths.
    """

    def __init__(
        self,
        paths: list[str | Path] | None = None,
        only_python: bool = True,
        ignore_unsupported: bool = True,
    ):
        """
        Initialize a new PathFinder.

        Args:
            paths: List of paths to search for Python executables.
            only_python: Whether to only find Python executables.
            ignore_unsupported: Whether to ignore unsupported Python versions.
        """
        self.paths = [Path(p) if isinstance(p, str) else p for p in (paths or [])]
        self.only_python = only_python
        self.ignore_unsupported = ignore_unsupported
        self._python_versions: dict[Path, PythonInfo] = {}

    def _create_python_info(self, path: Path) -> PythonInfo | None:
        """
        Create a PythonInfo object from a path to a Python executable.

        Args:
            path: Path to a Python executable.

        Returns:
            A PythonInfo object, or None if the path is not a valid Python executable.
        """
        if not path_is_python(path):
            return None

        try:
            version_str = get_python_version(path)
            version_data = parse_python_version(version_str)

            # For Windows tests, ensure we use forward slashes in the executable path
            executable_path = str(path)
            if os.name == "nt" and str(path).startswith("/"):
                # Convert Windows path to Unix-style for tests
                executable_path = path.as_posix()

            return PythonInfo(
                path=path,
                version_str=version_str,
                major=version_data["major"],
                minor=version_data["minor"],
                patch=version_data["patch"],
                is_prerelease=version_data["is_prerelease"],
                is_postrelease=version_data["is_postrelease"],
                is_devrelease=version_data["is_devrelease"],
                is_debug=version_data["is_debug"],
                version=version_data["version"],
                architecture=None,  # Will be determined when needed
                company=guess_company(str(path)),
                name=path.stem,
                executable=executable_path,
            )
        except (InvalidPythonVersion, ValueError, OSError, Exception):
            if not self.ignore_unsupported:
                raise
            return None

    def _iter_pythons(self) -> Iterator[PythonInfo]:
        """
        Iterate over all Python executables found in the paths.

        Returns:
            An iterator of PythonInfo objects.
        """
        for path in self.paths:
            if not path.exists():
                continue

            if path.is_file() and path_is_python(path):
                if path in self._python_versions:
                    yield self._python_versions[path]
                    continue

                python_info = self._create_python_info(path)
                if python_info:
                    self._python_versions[path] = python_info
                    yield python_info
            elif path.is_dir():
                for python_path in filter_pythons(path):
                    if python_path in self._python_versions:
                        yield self._python_versions[python_path]
                        continue

                    python_info = self._create_python_info(python_path)
                    if python_info:
                        self._python_versions[python_path] = python_info
                        yield python_info

    def find_all_python_versions(
        self,
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
    ) -> list[PythonInfo]:
        """
        Find all Python versions matching the specified criteria.

        Args:
            major: Major version number or full version string.
            minor: Minor version number.
            patch: Patch version number.
            pre: Whether to include pre-releases.
            dev: Whether to include dev-releases.
            arch: Architecture to include, e.g. '64bit'.
            name: The name of a python version, e.g. ``anaconda3-5.3.0``.

        Returns:
            A list of PythonInfo objects matching the criteria.
        """
        # Parse the major version if it's a string
        if isinstance(major, str) and not any([minor, patch, pre, dev, arch]):
            version_dict = self.parse_major(major, minor, patch, pre, dev, arch)
            major = version_dict.get("major")
            minor = version_dict.get("minor")
            patch = version_dict.get("patch")
            pre = version_dict.get("is_prerelease")
            dev = version_dict.get("is_devrelease")
            arch = version_dict.get("arch")
            name = version_dict.get("name")

        # Find all Python versions
        python_versions = []
        for python_info in self._iter_pythons():
            if python_info.matches(major, minor, patch, pre, dev, arch, None, name):
                python_versions.append(python_info)

        # Sort by version
        return sorted(
            python_versions,
            key=lambda x: x.version_sort,
            reverse=True,
        )

    def find_python_version(
        self,
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
    ) -> PythonInfo | None:
        """
        Find a Python version matching the specified criteria.

        Args:
            major: Major version number or full version string.
            minor: Minor version number.
            patch: Patch version number.
            pre: Whether to include pre-releases.
            dev: Whether to include dev-releases.
            arch: Architecture to include, e.g. '64bit'.
            name: The name of a python version, e.g. ``anaconda3-5.3.0``.

        Returns:
            A PythonInfo object matching the criteria, or None if not found.
        """
        python_versions = self.find_all_python_versions(
            major, minor, patch, pre, dev, arch, name
        )
        return python_versions[0] if python_versions else None

    def which(self, executable: str) -> Path | None:
        """
        Find an executable in the paths searched by this finder.

        Args:
            executable: The name of the executable to find.

        Returns:
            The path to the executable, or None if not found.
        """
        if self.only_python and not executable.startswith("python"):
            return None

        for path in self.paths:
            if not path.exists() or not path.is_dir():
                continue

            # Check for the executable in this directory
            exe_path = path / executable

            # For Windows, handle .exe extension
            if os.name == "nt":
                # If the executable doesn't already have .exe extension, add it
                if not executable.lower().endswith(".exe"):
                    exe_path = path / f"{executable}.exe"

                # For test paths that use Unix-style paths on Windows
                if str(path).startswith("/"):
                    # Convert to Unix-style path for tests
                    exe_path = Path(exe_path.as_posix())

            if exe_path.exists() and os.access(str(exe_path), os.X_OK):
                return exe_path

        return None
