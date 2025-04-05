from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .finders import (
    AsdfFinder,
    BaseFinder,
    PyenvFinder,
    SystemFinder,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .models.python_info import PythonInfo

# Import Windows-specific finders if on Windows
if os.name == "nt":
    from .finders import PyLauncherFinder, WindowsRegistryFinder


class Finder:
    """
    Main finder class that orchestrates all the finders.
    """

    def __init__(
        self,
        path: str | None = None,
        system: bool = False,
        global_search: bool = True,
        ignore_unsupported: bool = True,
        sort_by_path: bool = False,
    ):
        """
        Initialize a new Finder.

        Args:
            path: Path to prepend to the search path.
            system: Whether to include the system Python.
            global_search: Whether to search in the system PATH.
            ignore_unsupported: Whether to ignore unsupported Python versions.
        """
        self.path = path
        self.system = system
        self.global_search = global_search
        self.ignore_unsupported = ignore_unsupported
        self.sort_by_path = sort_by_path

        # Initialize finders
        self.system_finder = SystemFinder(
            paths=[path] if path else None,
            global_search=global_search,
            system=system,
            ignore_unsupported=ignore_unsupported,
        )

        self.pyenv_finder = PyenvFinder(
            ignore_unsupported=ignore_unsupported,
        )

        self.asdf_finder = AsdfFinder(
            ignore_unsupported=ignore_unsupported,
        )

        # Initialize Windows-specific finders if on Windows
        self.py_launcher_finder = None
        self.windows_finder = None
        if os.name == "nt":
            self.py_launcher_finder = PyLauncherFinder(
                ignore_unsupported=ignore_unsupported,
            )
            self.windows_finder = WindowsRegistryFinder(
                ignore_unsupported=ignore_unsupported,
            )

        # List of all finders
        self.finders: list[BaseFinder] = [
            self.pyenv_finder,
            self.asdf_finder,
        ]

        # Add Windows-specific finders if on Windows
        if self.py_launcher_finder:
            self.finders.append(self.py_launcher_finder)
        if self.windows_finder:
            self.finders.append(self.windows_finder)
            
        # Add system finder last
        self.finders.append(self.system_finder)

    def which(self, executable: str) -> Path | None:
        """
        Find an executable in the paths searched by this finder.

        Args:
            executable: The name of the executable to find.

        Returns:
            The path to the executable, or None if not found.
        """
        for finder in self.finders:
            path = finder.which(executable)
            if path:
                return path

        return None

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
        # Parse the major version if it's a string
        if isinstance(major, str) and not any([minor, patch, pre, dev, arch]):
            for finder in self.finders:
                version_dict = finder.parse_major(major, minor, patch, pre, dev, arch)
                if version_dict.get("name") and not name:
                    name = version_dict.get("name")
                    major = version_dict.get("major")
                    minor = version_dict.get("minor")
                    patch = version_dict.get("patch")
                    pre = version_dict.get("is_prerelease")
                    dev = version_dict.get("is_devrelease")
                    arch = version_dict.get("arch")
                    break

        # Try to find the Python version in each finder
        for finder in self.finders:
            python_version = finder.find_python_version(
                major, minor, patch, pre, dev, arch, name
            )
            if python_version:
                return python_version

        return None

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
            for finder in self.finders:
                version_dict = finder.parse_major(major, minor, patch, pre, dev, arch)
                if version_dict.get("name") and not name:
                    name = version_dict.get("name")
                    major = version_dict.get("major")
                    minor = version_dict.get("minor")
                    patch = version_dict.get("patch")
                    pre = version_dict.get("is_prerelease")
                    dev = version_dict.get("is_devrelease")
                    arch = version_dict.get("arch")
                    break

        # Find all Python versions in each finder
        python_versions = []
        for finder in self.finders:
            python_versions.extend(
                finder.find_all_python_versions(major, minor, patch, pre, dev, arch, name)
            )

        # Sort by version and remove duplicates
        seen_paths = set()
        unique_versions = []

        # Choose the sort key based on sort_by_path
        if self.sort_by_path:

            def sort_key(x):
                return x.path, x.version_sort

        else:

            def sort_key(x):
                return x.version_sort

        for version in sorted(
            python_versions, key=sort_key, reverse=not self.sort_by_path
        ):
            if version.path not in seen_paths:
                seen_paths.add(version.path)
                unique_versions.append(version)

        return unique_versions
