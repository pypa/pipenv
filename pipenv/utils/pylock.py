"""
PEP 751 pylock.toml file handling utilities.

This module provides functionality for reading and parsing pylock.toml files
as specified in PEP 751 (A file format to record Python dependencies for
installation reproducibility).
"""

import datetime
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from pipenv.utils import err
from pipenv.utils.locking import atomic_open_for_write
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
    def from_lockfile(
        cls, lockfile_path: Union[str, Path], pylock_path: Union[str, Path] = None
    ) -> "PylockFile":
        """Create a PylockFile from a Pipfile.lock file.

        Args:
            lockfile_path: Path to the Pipfile.lock file
            pylock_path: Path to save the pylock.toml file, defaults to pylock.toml in the same directory

        Returns:
            A PylockFile instance

        Raises:
            FileNotFoundError: If the Pipfile.lock file doesn't exist
            ValueError: If the Pipfile.lock file is invalid
        """
        if isinstance(lockfile_path, str):
            lockfile_path = Path(lockfile_path)

        if not lockfile_path.exists():
            raise FileNotFoundError(f"Pipfile.lock not found: {lockfile_path}")

        if pylock_path is None:
            pylock_path = lockfile_path.parent / "pylock.toml"
        elif isinstance(pylock_path, str):
            pylock_path = Path(pylock_path)

        try:
            with open(lockfile_path, encoding="utf-8") as f:
                lockfile_data = json.load(f)
        except Exception as e:
            raise ValueError(f"Invalid Pipfile.lock file: {e}")

        # Create the basic pylock.toml structure
        pylock_data = {
            "lock-version": "1.0",
            "environments": [],
            "extras": [],
            "dependency-groups": [],
            "default-groups": [],
            "created-by": "pipenv",
            "packages": [],
        }

        # Add Python version requirement if present
        meta = lockfile_data.get("_meta", {})
        requires = meta.get("requires", {})
        if "python_version" in requires:
            pylock_data["requires-python"] = f">={requires['python_version']}"
        elif "python_full_version" in requires:
            pylock_data["requires-python"] = f"=={requires['python_full_version']}"

        # Add sources
        sources = meta.get("sources", [])
        if sources:
            pylock_data["sources"] = sources

        # Process packages
        for section in ["default", "develop"]:
            packages = lockfile_data.get(section, {})
            for name, package_data in packages.items():
                package = {"name": name}

                # Add version if present
                if "version" in package_data:
                    version = package_data["version"]
                    if version.startswith("=="):
                        package["version"] = version[2:]
                    else:
                        package["version"] = version

                # Add markers if present
                if "markers" in package_data:
                    # For develop packages, add dependency_groups marker
                    if section == "develop":
                        if "markers" in package_data:
                            package["marker"] = (
                                f"dependency_groups in ('dev', 'test') and ({package_data['markers']})"
                            )
                        else:
                            package["marker"] = "dependency_groups in ('dev', 'test')"
                    else:
                        package["marker"] = package_data["markers"]
                elif section == "develop":
                    package["marker"] = "dependency_groups in ('dev', 'test')"

                # Add hashes if present
                if "hashes" in package_data:
                    wheels = []
                    for hash_value in package_data["hashes"]:
                        if hash_value.startswith("sha256:"):
                            hash_value = hash_value[7:]  # Remove "sha256:" prefix
                            wheel = {
                                "name": f"{name}-{package.get('version', '0.0.0')}-py3-none-any.whl",
                                "hashes": {"sha256": hash_value},
                            }
                            wheels.append(wheel)
                    if wheels:
                        package["wheels"] = wheels

                pylock_data["packages"].append(package)

        # Add tool.pipenv section with metadata
        pylock_data["tool"] = {
            "pipenv": {
                "generated_from": "Pipfile.lock",
                "generation_date": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }
        }

        instance = cls(path=pylock_path, data=pylock_data)
        return instance

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

    def write(self) -> None:
        """Write the pylock.toml file to disk.

        Raises:
            OSError: If there is an error writing the file
        """
        try:
            # Convert the data to a TOML document
            doc = tomlkit.document()

            # Add top-level keys in a specific order for readability
            for key in [
                "lock-version",
                "environments",
                "requires-python",
                "extras",
                "dependency-groups",
                "default-groups",
                "created-by",
            ]:
                if key in self.data:
                    doc[key] = self.data[key]

            # Add packages
            if "packages" in self.data:
                doc["packages"] = []
                for package in self.data["packages"]:
                    pkg_table = tomlkit.table()
                    for k, v in package.items():
                        if k not in {"wheels", "sdist"}:
                            pkg_table[k] = v

                    # Add wheels as an array of tables
                    if "wheels" in package:
                        pkg_table["wheels"] = []
                        for wheel in package["wheels"]:
                            wheel_table = tomlkit.inline_table()
                            for k, v in wheel.items():
                                wheel_table[k] = v
                            pkg_table["wheels"].append(wheel_table)

                    # Add sdist as a table
                    if "sdist" in package:
                        sdist_table = tomlkit.table()
                        for k, v in package["sdist"].items():
                            sdist_table[k] = v
                        pkg_table["sdist"] = sdist_table

                    doc["packages"].append(pkg_table)

            # Add tool section
            if "tool" in self.data:
                tool_table = tomlkit.table()
                for tool_name, tool_data in self.data["tool"].items():
                    tool_section = tomlkit.table()
                    for k, v in tool_data.items():
                        tool_section[k] = v
                    tool_table[tool_name] = tool_section
                doc["tool"] = tool_table

            # Write the document to the file
            with atomic_open_for_write(self.path, encoding="utf-8") as f:
                f.write(tomlkit.dumps(doc))

        except Exception as e:
            err.print(f"[bold red]Error writing pylock.toml: {e}[/bold red]")
            raise OSError(f"Error writing pylock.toml: {e}")

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
