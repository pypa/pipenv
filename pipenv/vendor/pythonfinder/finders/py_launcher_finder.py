from __future__ import annotations

import os
import subprocess
import re
from pathlib import Path
from typing import Iterator

from ..exceptions import InvalidPythonVersion
from ..models.python_info import PythonInfo
from ..utils.version_utils import parse_python_version
from .base_finder import BaseFinder


class PyLauncherFinder(BaseFinder):
    """
    Finder that uses the Windows py launcher (py.exe) to find Python installations.
    This is only available on Windows and requires the py launcher to be installed.
    """

    def __init__(self, ignore_unsupported: bool = True):
        """
        Initialize a new PyLauncherFinder.

        Args:
            ignore_unsupported: Whether to ignore unsupported Python versions.
        """
        self.ignore_unsupported = ignore_unsupported
        self._python_versions: dict[Path, PythonInfo] = {}
        self._available = os.name == "nt" and self._is_py_launcher_available()

    def _is_py_launcher_available(self) -> bool:
        """
        Check if the py launcher is available.

        Returns:
            True if the py launcher is available, False otherwise.
        """
        try:
            subprocess.run(
                ["py", "--list-paths"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            return True
        except (FileNotFoundError, subprocess.SubprocessError):
            return False

    def _get_py_launcher_versions(self) -> list[tuple[str, str, str]]:
        """
        Get a list of Python versions available through the py launcher.

        Returns:
            A list of tuples (version, path, is_default) where:
                - version is the Python version (e.g. "3.11")
                - path is the path to the Python executable
                - is_default is "*" if this is the default version, "" otherwise
        """
        if not self._available:
            return []

        try:
            result = subprocess.run(
                ["py", "--list-paths"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )

            versions = []
            # Parse output like:
            # -V:3.12 *        C:\Software\Python\Python_3_12\python.exe
            # -V:3.11          C:\Software\Python\Python_3_11\python.exe
            pattern = r'-V:(\S+)\s+(\*?)\s+(.+)'
            for line in result.stdout.splitlines():
                match = re.match(pattern, line.strip())
                if match:
                    version, is_default, path = match.groups()
                    versions.append((version, path, is_default))

            return versions
        except (subprocess.SubprocessError, Exception):
            return []

    def _create_python_info_from_py_launcher(
        self, version: str, path: str, is_default: str
    ) -> PythonInfo | None:
        """
        Create a PythonInfo object from py launcher information.

        Args:
            version: The Python version (e.g. "3.11").
            path: The path to the Python executable.
            is_default: "*" if this is the default version, "" otherwise.

        Returns:
            A PythonInfo object, or None if the information is invalid.
        """
        if not path or not os.path.exists(path):
            return None

        # Parse the version
        try:
            version_data = parse_python_version(version)
        except InvalidPythonVersion:
            if not self.ignore_unsupported:
                raise
            return None

        # Create the PythonInfo object
        return PythonInfo(
            path=Path(path),
            version_str=version,
            major=version_data["major"],
            minor=version_data["minor"],
            patch=version_data["patch"],
            is_prerelease=version_data["is_prerelease"],
            is_postrelease=version_data["is_postrelease"],
            is_devrelease=version_data["is_devrelease"],
            is_debug=version_data["is_debug"],
            version=version_data["version"],
            architecture=None,  # Will be determined when needed
            company="PythonCore",  # Assuming py launcher only finds official Python
            name=f"python-{version}",
            executable=path,
        )

    def _iter_pythons(self) -> Iterator[PythonInfo]:
        """
        Iterate over all Python installations found by the py launcher.

        Returns:
            An iterator of PythonInfo objects.
        """
        if not self._available:
            return iter([])  # Return empty iterator when py launcher is not available

        for version, path, is_default in self._get_py_launcher_versions():
            python_info = self._create_python_info_from_py_launcher(version, path, is_default)
            if python_info:
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
        if not self._available:
            return []

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
