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
        cls,
        lockfile_path: Union[str, Path],
        pylock_path: Union[str, Path] = None,
        dev_groups: Optional[List[str]] = None,
    ) -> "PylockFile":
        """Create a PylockFile from a Pipfile.lock file.

        Args:
            lockfile_path: Path to the Pipfile.lock file
            pylock_path: Path to save the pylock.toml file, defaults to pylock.toml in the same directory
            dev_groups: List of dependency group names for develop packages (default: ['dev'])

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

        # Default dev groups
        if dev_groups is None:
            dev_groups = ["dev"]

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
            "dependency-groups": dev_groups.copy(),  # Include dev groups
            "default-groups": ["default"],  # Default group for non-dev packages
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

        # Ensure all values are properly formatted for TOML
        # Convert None values to empty strings or arrays
        for key in ["environments", "extras", "dependency-groups", "default-groups"]:
            if key in pylock_data and pylock_data[key] is None:
                pylock_data[key] = []

        # Extract sources and build index URL map
        sources = meta.get("sources", [])
        index_url_map = {}  # Map source name to URL
        default_index = "https://pypi.org/simple/"
        if sources:
            for source in sources:
                source_name = source.get("name", "")
                source_url = source.get("url", "")
                if source_name and source_url:
                    # Convert to simple API URL format
                    index_url_map[source_name] = source_url.rstrip("/") + "/"
            # Use the first source as default
            if sources and sources[0].get("url"):
                default_index = sources[0]["url"].rstrip("/") + "/"

        # Build dev marker expression: 'group1' in dependency_groups or 'group2' in ...
        dev_marker = " or ".join(f"'{g}' in dependency_groups" for g in dev_groups)

        # Process packages
        for section in ["default", "develop"]:
            packages = lockfile_data.get(section, {})
            for name, package_data in packages.items():
                package = {"name": name}

                # Add version if present and not a wildcard
                if "version" in package_data:
                    version = package_data["version"]
                    if version == "*":
                        # Skip wildcard versions - they don't belong in pylock.toml
                        pass
                    elif version.startswith("=="):
                        package["version"] = version[2:]
                    else:
                        package["version"] = version

                # Add markers if present
                # PEP 751 marker syntax: 'group' in dependency_groups
                if "markers" in package_data:
                    # For develop packages, add dependency_groups marker
                    if section == "develop":
                        package["marker"] = (
                            f"({dev_marker}) and ({package_data['markers']})"
                        )
                    else:
                        package["marker"] = package_data["markers"]
                elif section == "develop":
                    package["marker"] = dev_marker

                # Add package index URL (PEP 751 packages.index)
                # Use the index from package_data if specified, otherwise default
                if "index" in package_data:
                    index_name = package_data["index"]
                    package["index"] = index_url_map.get(index_name, default_index)
                else:
                    package["index"] = default_index

                # Add hashes if present, with proper wheel/sdist structure
                if "hashes" in package_data:
                    wheels = []
                    for hash_value in package_data["hashes"]:
                        if hash_value.startswith("sha256:"):
                            hash_hex = hash_value[7:]  # Remove "sha256:" prefix
                            version_str = package.get("version", "0.0.0")
                            wheel_name = (
                                f"{name.replace('-', '_')}-{version_str}-py3-none-any.whl"
                            )
                            wheel = {
                                "name": wheel_name,
                                "url": f"{package['index']}{name}/{wheel_name}",
                                "hashes": {"sha256": hash_hex},
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
                content = f.read()
                data = tomlkit.parse(content)
                # Convert tomlkit objects to Python native types
                data_dict = {}
                for key, value in data.items():
                    if isinstance(
                        value,
                        (tomlkit.items.Table, tomlkit.items.AoT, tomlkit.items.Array),
                    ):
                        data_dict[key] = value.unwrap()
                    else:
                        data_dict[key] = value
        except Exception as e:
            raise PylockFormatError(f"Invalid pylock.toml file: {e}")

        # Validate lock-version
        lock_version = data_dict.get("lock-version")
        if not lock_version:
            raise PylockFormatError("Missing required field: lock-version")

        # Currently, we only support version 1.0
        if lock_version != "1.0":
            raise PylockVersionError(
                f"Unsupported lock-version: {lock_version}. Only version 1.0 is supported."
            )

        return cls(path=path, data=data_dict)

    @classmethod
    def from_pyproject(
        cls,
        pyproject_path: Union[str, Path],
        pylock_path: Union[str, Path] = None,
    ) -> "PylockFile":
        """Create a PylockFile skeleton from a pyproject.toml file.

        This reads the dependencies from pyproject.toml and creates a pylock.toml
        structure. Note: This does NOT resolve dependencies - it only reads
        the declared dependencies. Use a locker to resolve and populate full details.

        Args:
            pyproject_path: Path to the pyproject.toml file
            pylock_path: Path to save the pylock.toml file

        Returns:
            A PylockFile instance with declared dependencies (unresolved)

        Raises:
            FileNotFoundError: If the pyproject.toml file doesn't exist
            ValueError: If the pyproject.toml file is invalid
        """
        if isinstance(pyproject_path, str):
            pyproject_path = Path(pyproject_path)

        if not pyproject_path.exists():
            raise FileNotFoundError(f"pyproject.toml not found: {pyproject_path}")

        if pylock_path is None:
            pylock_path = pyproject_path.parent / "pylock.toml"
        elif isinstance(pylock_path, str):
            pylock_path = Path(pylock_path)

        try:
            with open(pyproject_path, encoding="utf-8") as f:
                pyproject_data = tomlkit.parse(f.read())
        except Exception as e:
            raise ValueError(f"Invalid pyproject.toml file: {e}")

        # Extract project metadata (PEP 621)
        project = pyproject_data.get("project", {})
        project_name = project.get("name", "")
        requires_python = project.get("requires-python", "")

        # Create the basic pylock.toml structure
        pylock_data: Dict[str, Any] = {
            "lock-version": "1.0",
            "environments": [],
            "created-by": "pipenv",
            "packages": [],
        }

        if requires_python:
            pylock_data["requires-python"] = requires_python

        # Extract dependencies from [project.dependencies] (PEP 621)
        dependencies = project.get("dependencies", [])

        # Extract optional dependencies for extras (PEP 621)
        optional_deps = project.get("optional-dependencies", {})
        extras = list(optional_deps.keys())
        if extras:
            pylock_data["extras"] = extras

        # Extract dependency groups (PEP 735)
        dependency_groups_data = pyproject_data.get("dependency-groups", {})
        dependency_groups = list(dependency_groups_data.keys())
        if dependency_groups:
            pylock_data["dependency-groups"] = dependency_groups

        # Default groups (main dependencies)
        pylock_data["default-groups"] = ["default"] if dependencies else []

        # Parse main dependencies
        for dep in dependencies:
            package = cls._parse_dependency_string(dep)
            if package:
                pylock_data["packages"].append(package)

        # Parse optional dependencies (extras)
        for extra_name, extra_deps in optional_deps.items():
            for dep in extra_deps:
                package = cls._parse_dependency_string(dep)
                if package:
                    # Add marker for extra
                    existing_marker = package.get("marker", "")
                    extra_marker = f"'{extra_name}' in extras"
                    if existing_marker:
                        package["marker"] = f"({extra_marker}) and ({existing_marker})"
                    else:
                        package["marker"] = extra_marker
                    pylock_data["packages"].append(package)

        # Parse dependency groups (PEP 735)
        for group_name, group_deps in dependency_groups_data.items():
            for dep in group_deps:
                # Skip include directives like {include-group = "..."}
                if isinstance(dep, dict):
                    continue
                package = cls._parse_dependency_string(dep)
                if package:
                    # Add marker for dependency group
                    existing_marker = package.get("marker", "")
                    group_marker = f"'{group_name}' in dependency_groups"
                    if existing_marker:
                        package["marker"] = f"({group_marker}) and ({existing_marker})"
                    else:
                        package["marker"] = group_marker
                    pylock_data["packages"].append(package)

        # Add tool.pipenv section with metadata
        pylock_data["tool"] = {
            "pipenv": {
                "generated_from": "pyproject.toml",
                "project_name": project_name,
                "generation_date": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }
        }

        return cls(path=pylock_path, data=pylock_data)

    @staticmethod
    def _parse_dependency_string(dep_string: str) -> Optional[Dict[str, Any]]:
        """Parse a PEP 508 dependency string into a package dict.

        Args:
            dep_string: A PEP 508 dependency specifier (e.g., "requests>=2.28.0")

        Returns:
            A dict with 'name' and optionally 'marker', or None if parsing fails
        """
        if not dep_string or not isinstance(dep_string, str):
            return None

        try:
            # Use pip's requirement parser
            from pipenv.patched.pip._vendor.packaging.requirements import Requirement

            req = Requirement(dep_string)
            package: Dict[str, Any] = {"name": req.name}

            # Add marker if present
            if req.marker:
                package["marker"] = str(req.marker)

            return package
        except Exception:
            # Fallback: simple name extraction
            import re

            match = re.match(r"^([a-zA-Z0-9][-a-zA-Z0-9._]*)", dep_string)
            if match:
                return {"name": match.group(1).lower()}
            return None

    def write(self) -> None:
        """Write the pylock.toml file to disk.

        Raises:
            OSError: If there is an error writing the file
        """
        try:
            # Ensure all values are properly formatted for TOML
            # Create a deep copy of the data to avoid modifying the original
            data_copy = {}
            for key, value in self.data.items():
                if isinstance(value, dict):
                    data_copy[key] = value.copy()
                elif isinstance(value, list):
                    data_copy[key] = value.copy()
                else:
                    data_copy[key] = value

            # Convert None values to empty strings or arrays
            for key in ["environments", "extras", "dependency-groups", "default-groups"]:
                if key in data_copy:
                    if data_copy[key] is None:
                        data_copy[key] = []

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
                if key in data_copy:
                    doc[key] = data_copy[key]

            # Add packages
            if "packages" in data_copy:
                doc["packages"] = tomlkit.aot()
                for package in data_copy["packages"]:
                    pkg_table = tomlkit.table()

                    # Add basic package info first for better readability
                    for key in ["name", "version", "marker", "requires-python"]:
                        if key in package:
                            pkg_table[key] = package[key]

                    # Add remaining keys except wheels and sdist
                    for k, v in package.items():
                        if k not in {
                            "name",
                            "version",
                            "marker",
                            "requires-python",
                            "wheels",
                            "sdist",
                        }:
                            pkg_table[k] = v

                    # Add wheels as an array of tables with better formatting
                    if "wheels" in package:
                        wheels_array = tomlkit.array()
                        wheels_array.multiline(True)

                        for wheel in package["wheels"]:
                            wheel_table = tomlkit.inline_table()

                            # Add wheel properties in a specific order
                            for key in ["name", "upload-time", "url", "size"]:
                                if key in wheel:
                                    wheel_table[key] = wheel[key]

                            # Add hashes as a table
                            if "hashes" in wheel:
                                hashes_table = tomlkit.inline_table()
                                for hash_algo, hash_value in wheel["hashes"].items():
                                    hashes_table[hash_algo] = hash_value
                                wheel_table["hashes"] = hashes_table

                            wheels_array.append(wheel_table)

                        pkg_table["wheels"] = wheels_array

                    # Add sdist as a table
                    if "sdist" in package:
                        sdist_table = tomlkit.inline_table()

                        # Add sdist properties in a specific order
                        for key in ["name", "upload-time", "url", "size"]:
                            if key in package["sdist"]:
                                sdist_table[key] = package["sdist"][key]

                        # Add hashes as a table
                        if "hashes" in package["sdist"]:
                            hashes_table = tomlkit.inline_table()
                            for hash_algo, hash_value in package["sdist"][
                                "hashes"
                            ].items():
                                hashes_table[hash_algo] = hash_value
                            sdist_table["hashes"] = hashes_table

                        pkg_table["sdist"] = sdist_table

                    doc["packages"].append(pkg_table)

            # Add tool section
            if "tool" in data_copy:
                tool_table = tomlkit.table()
                for tool_name, tool_data in data_copy["tool"].items():
                    tool_section = tomlkit.table()
                    for k, v in tool_data.items():
                        tool_section[k] = v
                    tool_table[tool_name] = tool_section
                doc["tool"] = tool_table

            # Write the document to the file with proper formatting
            with atomic_open_for_write(self.path, encoding="utf-8") as f:
                content = tomlkit.dumps(doc)
                # Ensure there's a blank line between package entries for readability
                content = content.replace("[[packages]]\n", "\n[[packages]]\n")
                f.write(content)

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
        from pipenv.patched.pip._vendor.packaging.markers import (
            InvalidMarker,
            Marker,
        )

        # Set up extras and dependency_groups for marker evaluation
        _extras = frozenset(extras) if extras is not None else frozenset()
        _dependency_groups = (
            frozenset(dependency_groups)
            if dependency_groups is not None
            else frozenset(self.default_groups)
        )

        result = []

        for package in self.packages:
            # Check if the package has a marker
            marker_str = package.get("marker")
            if marker_str:
                try:
                    marker = Marker(marker_str)
                    # Evaluate the marker with the lock_file context
                    # which supports extras and dependency_groups as sets
                    environment = {
                        "extras": _extras,
                        "dependency_groups": _dependency_groups,
                    }
                    if not marker.evaluate(environment=environment, context="lock_file"):
                        # Marker does not match, skip this package
                        continue
                except InvalidMarker:
                    # If the marker is invalid, include the package anyway
                    # to be safe and let the installer handle it
                    pass

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

        # Add sources if present
        if "sources" in self.data:
            lockfile["_meta"]["sources"] = self.data["sources"]
        # If no sources in pylock.toml, add a default source
        else:
            lockfile["_meta"]["sources"] = [
                {
                    "name": "pypi",
                    "url": "https://pypi.org/simple",
                    "verify_ssl": True,
                }
            ]

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

            # Add version if present, otherwise use wildcard for Pipfile.lock compatibility
            if "version" in package:
                package_entry["version"] = f"=={package['version']}"
            else:
                # No version in pylock.toml means any version is acceptable
                package_entry["version"] = "*"

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
