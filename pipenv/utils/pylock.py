"""
PEP 751 pylock.toml file handling utilities.

This module provides functionality for reading and parsing pylock.toml files
as specified in PEP 751 (A file format to record Python dependencies for
installation reproducibility).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from pipenv.utils.toml import tomlkit_value_to_python
from pipenv.vendor import tomlkit


class PylockError(Exception):
    """Base exception for pylock.toml related errors."""

    pass


class PylockVersionError(PylockError):
    """Raised when the lock-version is not supported."""

    pass


class PylockFormatError(PylockError):
    """Raised when the pylock.toml file format is invalid."""

    pass


@dataclass
class PylockFile:
    """Represents a pylock.toml file as specified in PEP 751."""

    path: Path
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(cls, path: Union[str, Path]) -> "PylockFile":
        """Load a pylock.toml file from the given path.

        Args:
            path: Path to the pylock.toml file

        Returns:
            A PylockFile instance

        Raises:
            FileNotFoundError: If the file doesn't exist
            PylockFormatError: If the file is not a valid pylock.toml file
            PylockVersionError: If the lock-version is not supported
        """
        if isinstance(path, str):
            path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Pylock file not found: {path}")

        try:
            with open(path, encoding="utf-8") as f:
                data = tomlkit.parse(f.read())
        except Exception as e:
            raise PylockFormatError(f"Invalid pylock.toml file: {e}")

        # Validate lock-version
        lock_version = data.get("lock-version")
        if not lock_version:
            raise PylockFormatError("Missing required field: lock-version")

        # Currently, we only support version 1.0
        if lock_version != "1.0":
            raise PylockVersionError(
                f"Unsupported lock-version: {lock_version}. Only version 1.0 is supported."
            )

        return cls(path=path, data=tomlkit_value_to_python(data))

    @property
    def lock_version(self) -> str:
        """Get the lock-version."""
        return self.data.get("lock-version", "")

    @property
    def environments(self) -> List[str]:
        """Get the environments list."""
        return self.data.get("environments", [])

    @property
    def requires_python(self) -> Optional[str]:
        """Get the requires-python value."""
        return self.data.get("requires-python")

    @property
    def extras(self) -> List[str]:
        """Get the extras list."""
        return self.data.get("extras", [])

    @property
    def dependency_groups(self) -> List[str]:
        """Get the dependency-groups list."""
        return self.data.get("dependency-groups", [])

    @property
    def default_groups(self) -> List[str]:
        """Get the default-groups list."""
        return self.data.get("default-groups", [])

    @property
    def created_by(self) -> str:
        """Get the created-by value."""
        return self.data.get("created-by", "")

    @property
    def packages(self) -> List[Dict[str, Any]]:
        """Get the packages list."""
        return self.data.get("packages", [])

    @property
    def tool(self) -> Dict[str, Any]:
        """Get the tool table."""
        return self.data.get("tool", {})

    def get_packages_for_environment(
        self,
        extras: Optional[Set[str]] = None,
        dependency_groups: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get packages that should be installed for the given environment.

        Args:
            extras: Set of extras to include
            dependency_groups: Set of dependency groups to include

        Returns:
            List of package dictionaries that should be installed
        """
        if extras is None:
            extras = set()
        if dependency_groups is None:
            dependency_groups = set(self.default_groups)

        result = []

        for package in self.packages:
            # Check if the package has a marker
            marker = package.get("marker")
            if marker:
                # TODO: Implement proper marker evaluation with extras and dependency_groups
                # For now, we'll just include packages without markers or with simple markers
                if "extras" in marker or "dependency_groups" in marker:
                    # Skip packages with extras or dependency_groups markers for now
                    continue

            result.append(package)

        return result

    def convert_to_pipenv_lockfile(self) -> Dict[str, Any]:
        """Convert the pylock.toml file to a Pipfile.lock format.

        Returns:
            A dictionary in Pipfile.lock format
        """
        # Create the basic structure
        lockfile = {
            "_meta": {
                "hash": {"sha256": ""},  # We don't have a hash in pylock.toml
                "pipfile-spec": 6,
                "requires": {},
                "sources": [],
            },
            "default": {},
            "develop": {},
        }

        # Add Python version requirement if present
        if self.requires_python:
            lockfile["_meta"]["requires"]["python_version"] = self.requires_python

        # Process packages
        for package in self.packages:
            name = package.get("name")
            if not name:
                continue

            # Determine if this is a dev package based on markers
            # This is a simplification - in reality we'd need to parse the markers
            is_dev = False
            marker = package.get("marker", "")
            if marker and "dependency_groups" in marker:
                # Simple heuristic - if it mentions dev or test, it's probably a dev package
                if "dev" in marker.lower() or "test" in marker.lower():
                    is_dev = True

            # Create the package entry
            package_entry = {}

            # Add version if present
            if "version" in package:
                package_entry["version"] = f"=={package['version']}"

            # Add hashes if present
            hashes = []
            if "wheels" in package:
                hashes.extend(
                    f"sha256:{wheel['hashes']['sha256']}"
                    for wheel in package["wheels"]
                    if "hashes" in wheel and "sha256" in wheel["hashes"]
                )
            if (
                "sdist" in package
                and "hashes" in package["sdist"]
                and "sha256" in package["sdist"]["hashes"]
            ):
                hashes.append(f"sha256:{package['sdist']['hashes']['sha256']}")
            if hashes:
                package_entry["hashes"] = hashes

            # Add marker if present
            if marker:
                package_entry["markers"] = marker

            # Add to the appropriate section
            section = "develop" if is_dev else "default"
            lockfile[section][name] = package_entry

        return lockfile


def find_pylock_file(directory: Union[str, Path] = None) -> Optional[Path]:
    """Find a pylock.toml file in the given directory.

    Args:
        directory: Directory to search in, defaults to current directory

    Returns:
        Path to the pylock.toml file if found, None otherwise
    """
    if directory is None:
        directory = os.getcwd()

    if isinstance(directory, str):
        directory = Path(directory)

    # First, look for pylock.toml
    pylock_path = directory / "pylock.toml"
    if pylock_path.exists():
        return pylock_path

    # Then, look for named pylock files (pylock.*.toml)
    for file in directory.glob("pylock.*.toml"):
        return file

    return None
