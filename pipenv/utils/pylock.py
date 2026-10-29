"""
PEP 751 pylock.toml file handling utilities.

This module provides functionality for reading and parsing pylock.toml files
as specified in PEP 751 (A file format to record Python dependencies for
installation reproducibility).
"""

import datetime
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Union
from urllib.parse import urljoin

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


class PylockEnvironmentError(PylockError):
    """Raised when the pylock.toml file does not apply to the target environment."""

    pass


# pylock.toml is read several times per command; warn about a newer minor
# lock-version once per file.
_warned_newer_lock_versions: Set[Path] = set()


@dataclass
class PylockFile:
    """Represents a pylock.toml file as specified in PEP 751."""

    path: Path
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_lockfile(
        cls,
        lockfile_path: Union[str, Path],
        pylock_path: Optional[Union[str, Path]] = None,
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
            with open(lockfile_path, encoding="utf-8-sig") as f:
                lockfile_data = json.load(f)
        except Exception as e:
            raise ValueError(f"Invalid Pipfile.lock file: {e}")

        from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

        # Group names are PEP 735 normalized; category names are not, so
        # record which category each group came from for the way back.
        dev_groups = list(dict.fromkeys(canonicalize_name(group) for group in dev_groups))
        category_groups = {"default": ["default"], "develop": dev_groups}
        group_categories = {"default": "default"}
        for section in dict.fromkeys(["develop", *lockfile_data]):
            if section in {"_meta", "default"}:
                continue
            groups = category_groups.setdefault(section, [canonicalize_name(section)])
            for group in groups:
                owner = group_categories.setdefault(group, section)
                if owner != section:
                    raise ValueError(
                        f"Pipfile.lock categories {owner!r} and {section!r} both "
                        f"map to the dependency group {group!r}; rename the "
                        "category or choose different --dev-groups"
                    )
        del group_categories["default"]

        # Create the basic pylock.toml structure
        pylock_data: Dict[str, Any] = {
            "lock-version": "1.0",
            "environments": [],
            "extras": [],
            "dependency-groups": list(dict.fromkeys(
                group for section, groups in category_groups.items()
                if section != "default" for group in groups
            )),
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
        source_map = {}
        default_index = "https://pypi.org/simple/"
        if sources:
            for source in sources:
                source_name = source.get("name", "")
                source_url = source.get("url", "")
                if source_name and source_url:
                    # Convert to simple API URL format
                    index_url_map[source_name] = source_url.rstrip("/") + "/"
                    source_map[source_name] = source
            # Use the first source as default
            if sources and sources[0].get("url"):
                default_index = sources[0]["url"].rstrip("/") + "/"

        # Guard every category, including default, so an unconditional shared
        # dependency can be recovered when installing a custom category alone.
        entries_by_name: Dict[str, Any] = {}
        for section, groups in category_groups.items():
            group_marker = " or ".join(f"'{group}' in dependency_groups" for group in groups)
            packages = lockfile_data.get(section, {})
            for name, package_data in packages.items():
                marker = package_data.get("markers")
                marker = f"({group_marker}) and ({marker})" if marker else group_marker
                shared_entry = next(
                    (entry for original, entry in entries_by_name.get(name, [])
                     if _same_locked_package(original, package_data)),
                    None,
                )
                if shared_entry is not None:
                    shared_entry["marker"] = f"({shared_entry['marker']}) or ({marker})"
                    continue

                package: Dict[str, Any] = {"name": name, "marker": marker}
                entries_by_name.setdefault(name, []).append((package_data, package))

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

                # Packages from a local path, a VCS or a URL don't come from the
                # index: record where they come from (PEP 751 packages.directory,
                # packages.vcs, packages.archive) instead of an index and wheels.
                source = _pylock_source_from_lockfile_entry(package_data)
                if source:
                    package.update(source)
                    pylock_data["packages"].append(package)
                    continue

                # Add package index URL (PEP 751 packages.index)
                # Use the index from package_data if specified, otherwise default
                if "index" in package_data:
                    index_name = package_data["index"]
                    package["index"] = index_url_map.get(index_name, default_index)
                else:
                    package["index"] = default_index

                # A Pipfile.lock hash does not identify a filename or URL. Match
                # it against the actual files in the package's Simple API page.
                hashes = package_data.get("hashes", [])
                if hashes:
                    source_info = source_map.get(package_data.get("index"))
                    if source_info is None and sources:
                        source_info = sources[0]
                    files = _files_for_lockfile_hashes(
                        name, package["index"], hashes, source_info
                    )
                    wheels = [item for item in files if item["name"].endswith(".whl")]
                    sdists = [item for item in files if not item["name"].endswith(".whl")]
                    if wheels:
                        package["wheels"] = wheels
                    if sdists:
                        package["sdist"] = sdists[0]

                    # Keep hashes that could not be assigned to a real file for
                    # Pipenv's round trip. They cannot be portable PEP 751 file
                    # entries without an artifact identity.
                    recorded_files = wheels + sdists[:1]
                    matched = {
                        f"{algorithm}:{digest}"
                        for item in recorded_files
                        for algorithm, digest in item["hashes"].items()
                    }
                    unmatched = sorted(set(hashes) - matched)
                    if unmatched:
                        package["tool"] = {"pipenv": {"hashes": unmatched}}

                pylock_data["packages"].append(package)

        # Add tool.pipenv section with metadata
        # TODO(T_F.8): surface ``[tool.pipenv] resolver = "..."`` here
        # so a pylock.toml-only project can pin a non-default resolver
        # backend (sign-off 2026-05-12 answer 1).  T_F.5 lays the
        # framework; populating this field is deferred to the uv-backend
        # follow-up initiative.
        pylock_data["tool"] = {
            "pipenv": {
                "generated_from": "Pipfile.lock",
                "generation_date": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
                "categories": group_categories,
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
            with open(path, encoding="utf-8-sig") as f:
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

        # Currently, we support version 1.0. PEP 751 requires an error for an
        # unsupported major version; a newer minor version is still readable,
        # so warn that keys it adds are ignored.
        major, _, minor = str(lock_version).partition(".")
        if not (major.isdigit() and minor.isdigit()):
            raise PylockVersionError(f"Invalid lock-version: {lock_version}")
        if int(major) != 1:
            raise PylockVersionError(
                f"Unsupported lock-version: {lock_version}. Only version 1.0 is supported."
            )
        if int(minor) > 0 and path.resolve() not in _warned_newer_lock_versions:
            _warned_newer_lock_versions.add(path.resolve())
            err.print(
                f"[bold yellow]Warning: {path} has lock-version {lock_version}, "
                "newer than the 1.0 pipenv supports; keys added after 1.0 are "
                "ignored.[/bold yellow]"
            )

        return cls(path=path, data=data_dict)

    @classmethod
    def from_pyproject(
        cls,
        pyproject_path: Union[str, Path],
        pylock_path: Optional[Union[str, Path]] = None,
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
            with open(pyproject_path, encoding="utf-8-sig") as f:
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
            data_copy: Dict[str, Any] = {}
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
        environment: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get packages that should be installed for the given environment.

        Args:
            extras: Set of extras to include
            dependency_groups: Set of dependency groups to include
            environment: Marker variables that override the running
                interpreter's (e.g. the target virtualenv's Python version)

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
                    marker_environment = {
                        **(environment or {}),
                        "extras": _extras,
                        "dependency_groups": _dependency_groups,
                    }
                    if not marker.evaluate(
                        environment=marker_environment, context="lock_file"
                    ):
                        # Marker does not match, skip this package
                        continue
                except InvalidMarker:
                    # If the marker is invalid, include the package anyway
                    # to be safe and let the installer handle it
                    pass

            result.append(package)

        return result

    def check_environment(
        self,
        extras: Optional[Set[str]] = None,
        dependency_groups: Optional[Set[str]] = None,
        environment: Optional[Dict[str, str]] = None,
    ) -> None:
        """Check that the lock applies to the environment being installed for.

        PEP 751 requires installers to raise an error when the top-level
        ``requires-python``, the ``environments`` list, or the
        ``requires-python`` of a package that would be installed excludes the
        environment.

        Args:
            extras: Set of extras to include
            dependency_groups: Set of dependency groups to include
            environment: Marker variables that override the running
                interpreter's (e.g. the target virtualenv's Python version)

        Raises:
            PylockEnvironmentError: If the lock doesn't apply to the environment
            PylockFormatError: If a ``requires-python`` or environment marker
                is invalid
        """
        from pipenv.patched.pip._vendor.packaging.markers import (
            InvalidMarker,
            Marker,
            default_environment,
        )
        from pipenv.patched.pip._vendor.packaging.specifiers import (
            InvalidSpecifier,
            SpecifierSet,
        )

        target_environment = {**default_environment(), **(environment or {})}
        python_version = target_environment["python_full_version"]

        def satisfies(requires_python: str) -> bool:
            try:
                specifier = SpecifierSet(requires_python)
            except InvalidSpecifier:
                raise PylockFormatError(f"Invalid requires-python: {requires_python!r}")
            return specifier.contains(python_version, prereleases=True)

        if self.requires_python and not satisfies(self.requires_python):
            raise PylockEnvironmentError(
                f"Python {python_version} does not satisfy the lock file's "
                f"requires-python {self.requires_python!r}"
            )

        if self.environments:
            try:
                markers = [Marker(marker) for marker in self.environments]
            except InvalidMarker as e:
                raise PylockFormatError(f"Invalid marker in environments: {e}")
            if not any(
                marker.evaluate(environment=target_environment) for marker in markers
            ):
                raise PylockEnvironmentError(
                    "The environment does not match any of the lock file's "
                    f"environments: {self.environments}"
                )

        seen = set()
        for package in self.get_packages_for_environment(
            extras=extras,
            dependency_groups=dependency_groups,
            environment=environment,
        ):
            name = package.get("name", "").lower()
            if name in seen:
                raise PylockFormatError(
                    f"Package {name!r} has multiple entries that match the selected "
                    "groups and environment; they must narrow down to a single entry"
                )
            seen.add(name)
            requires_python = package.get("requires-python")
            if requires_python and not satisfies(requires_python):
                raise PylockEnvironmentError(
                    f"Python {python_version} does not satisfy the requires-python "
                    f"{requires_python!r} of package {package.get('name')!r}"
                )

    def _narrow_package_entries(
        self, environment: Optional[Dict[str, str]] = None,
        packages: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Narrow packages listed more than once to the entry for the environment.

        PEP 751 lets a lock list a package several times with different
        markers (e.g. one version per Python range), and requires all entries
        to narrow down to a single one at install time. Pipfile.lock holds one
        entry per name, so pick it here instead of keeping whichever comes last.

        Args:
            environment: Marker variables that override the running
                interpreter's (e.g. the target virtualenv's Python version)

        Returns:
            One package entry per name, in the order of their first entry

        Raises:
            PylockFormatError: If more than one entry for a name matches
        """
        from pipenv.patched.pip._vendor.packaging.markers import (
            InvalidMarker,
            Marker,
        )

        entries_by_name: Dict[str, List[Dict[str, Any]]] = {}
        for package in self.packages if packages is None else packages:
            name = package.get("name")
            if name:
                entries_by_name.setdefault(name.lower(), []).append(package)

        marker_environment = {
            **(environment or {}),
            "extras": frozenset(self.extras),
            "dependency_groups": frozenset(self.dependency_groups)
            | frozenset(self.default_groups),
        }

        def matches(package: Dict[str, Any]) -> bool:
            marker = package.get("marker")
            if not marker:
                return True
            try:
                return Marker(marker).evaluate(
                    environment=marker_environment, context="lock_file"
                )
            except InvalidMarker:
                return True

        result = []
        for name, entries in entries_by_name.items():
            if len(entries) == 1:
                result.append(entries[0])
                continue
            matching = [package for package in entries if matches(package)]
            if len(matching) > 1:
                raise PylockFormatError(
                    f"Package {name!r} has {len(matching)} entries that match the "
                    "environment; they must narrow down to a single entry"
                )
            # With no match, keep an entry whose marker excludes the
            # environment, so the package is skipped like a single entry.
            result.append(matching[0] if matching else entries[0])
        return result

    def _category_groups(self) -> Dict[str, Set[str]]:
        """Map Pipfile.lock categories to normalized pylock dependency groups."""
        from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

        defaults = {canonicalize_name(group) for group in self.default_groups}
        categories = {"default": defaults, "develop": set()}
        names = {canonicalize_name(group): group for group in self.dependency_groups}
        # Accept older locks which omit the top-level dependency-groups list.
        for package in self.packages:
            for group in sorted(_marker_dependency_groups(package.get("marker"))):
                names.setdefault(group, group)
        # Pipenv records the category each group was exported from.
        recorded = self.tool.get("pipenv", {}).get("categories", {})
        if not isinstance(recorded, dict):
            recorded = {}
        recorded = {canonicalize_name(group): category for group, category in recorded.items()}
        for group, name in names.items():
            if group in defaults:
                continue
            category = recorded.get(group) or (
                "develop" if group in {"dev", "develop", "dev-packages"} else name
            )
            categories.setdefault(category, set()).add(group)
        return categories

    def groups_for_categories(self, categories: Iterable[str]) -> Set[str]:
        """Translate an install's category selection without enabling other groups."""
        category_groups = self._category_groups()
        return set().union(*(
            category_groups.get(_lockfile_category(category), set())
            for category in categories
        ))

    def _packages_for_category(self, category, groups, selected_groups=None):
        """Resolve group conditions while retaining ordinary environment markers."""
        result = []
        for package in self.packages:
            marker = package.get("marker")
            if category != "default" and not (_marker_dependency_groups(marker) & groups):
                continue
            if category == "default" and _project_marker(marker, groups, self.extras) is False:
                continue
            projected = _project_marker(
                marker, groups if selected_groups is None else selected_groups, self.extras
            )
            if projected is False:
                continue
            entry = dict(package)
            if projected is True:
                entry.pop("marker", None)
            else:
                entry["marker"] = projected
            result.append(entry)
        return result

    def convert_to_pipenv_lockfile(
        self, environment: Optional[Dict[str, str]] = None,
        categories: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Convert the pylock.toml file to a Pipfile.lock format.

        Args:
            environment: Marker variables that override the running
                interpreter's, used to pick between entries of a package
                listed more than once
            categories: Optional install selection. Group expressions are
                evaluated against precisely this combination of categories.
                Otherwise each category is converted independently.

        Returns:
            A dictionary in Pipfile.lock format
        """
        # Create the basic structure
        lockfile: Dict[str, Any] = {
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
            lockfile["_meta"]["requires"].update(
                _pipfile_requires_from_pylock(self.requires_python)
            )

        # Add sources if present
        if "sources" in self.data:
            # Expand ${VAR} tokens in source URLs at read time so that
            # callers downstream (resolver, finder, netrc-writer) see the
            # real credentials.  Mirrors the legacy ``Pipfile.lock`` reader
            # (``Lockfile.load``); without this, users with ``[pipenv]
            # use_pylock = true`` lose env-var expansion in private-index
            # URLs (gh-6670).
            from pipenv.utils.shell import expand_url_credentials

            sources = []
            for source in self.data["sources"]:
                if isinstance(source, dict) and "url" in source:
                    source = {**source, "url": expand_url_credentials(source["url"])}
                sources.append(source)
            lockfile["_meta"]["sources"] = sources
        # If no sources in pylock.toml, add a default source
        else:
            lockfile["_meta"]["sources"] = [
                {
                    "name": "pypi",
                    "url": "https://pypi.org/simple",
                    "verify_ssl": True,
                }
            ]

        category_groups = self._category_groups()
        selected_groups = None
        if categories is not None:
            categories = [_lockfile_category(category) for category in categories]
            selected_groups = self.groups_for_categories(categories)
            category_groups = {
                category: category_groups.get(category, set()) for category in categories
            }

        for category, groups in category_groups.items():
            lockfile[category] = {}
            packages = self._packages_for_category(category, groups, selected_groups)
            for package in self._narrow_package_entries(environment, packages=packages):
                lockfile[category][package["name"]] = _pipfile_package(package)

        return lockfile


def _lockfile_category(category):
    return {"packages": "default", "dev-packages": "develop"}.get(category, category)


def _marker_dependency_groups(marker: Optional[str]) -> Set[str]:
    """Read group names from the marker grammar, independent of whitespace."""
    from pipenv.patched.pip._vendor.packaging.markers import InvalidMarker, Marker, Value, Variable
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    if not marker:
        return set()
    try:
        parsed = Marker(marker)
    except InvalidMarker:
        return set()

    def names(nodes):
        result = set()
        for node in nodes:
            if isinstance(node, list):
                result.update(names(node))
            elif isinstance(node, tuple) and any(
                isinstance(term, Variable) and term.value == "dependency_groups" for term in node
            ):
                result.update(canonicalize_name(term.value) for term in node if isinstance(term, Value))
        return result

    return names(parsed._markers)


def _project_marker(marker, groups, extras):
    """Substitute lock-file-only conditions, retaining the PEP 508 expression.

    A boolean result means the whole expression is unconditional or excluded.
    In particular, an inactive group in an OR branch must become false, rather
    than being stripped as though every group had been selected.
    """
    from pipenv.patched.pip._vendor.packaging.markers import InvalidMarker, Marker, Variable

    if not marker:
        return True
    try:
        parsed = Marker(marker)
    except InvalidMarker:
        return marker
    environment = {"dependency_groups": frozenset(groups), "extras": frozenset(extras)}

    def simplify(nodes):
        branches, terms = [], []
        for node in nodes + ["or"]:
            if node == "or":
                if not any(term is False for term in terms):
                    kept = [term for term in terms if term is not True]
                    if not kept:
                        return True
                    branch = []
                    for term in kept:
                        branch.extend(["and", term] if branch else [term])
                    branches.extend(["or", *branch] if branches else branch)
                terms = []
            elif node != "and":
                if isinstance(node, list):
                    node = simplify(node)
                elif any(isinstance(term, Variable) and term.value in environment for term in node):
                    node = Marker._from_markers([node]).evaluate(environment, context="lock_file")
                terms.append(node)
        return branches or False

    projected = simplify(parsed._markers)
    if isinstance(projected, bool):
        return projected
    if projected == parsed._markers:
        return marker
    return str(Marker._from_markers(projected))


def _pipfile_package(package):
    """Convert an already selected package, including its remaining marker."""
    # Create the package entry
    package_entry = _lockfile_source_from_pylock_package(package)

    # Add version if present, otherwise use wildcard for Pipfile.lock compatibility
    if package_entry:
        # Local, VCS and URL entries are pinned by their source, not a version
        pass
    elif "version" in package:
        package_entry["version"] = f"=={package['version']}"
    else:
        # No version in pylock.toml means any version is acceptable
        package_entry["version"] = "*"

    # Add hashes if present
    hashes: List[str] = []
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
    hashes.extend(package.get("tool", {}).get("pipenv", {}).get("hashes", []))
    if hashes:
        package_entry["hashes"] = sorted(set(hashes))

    # Add marker if present
    if package.get("marker"):
        package_entry["markers"] = package["marker"]

    return package_entry


_REQUIRES_PYTHON_RE = re.compile(r"^\s*(>=|==)\s*(\d+(?:\.\d+)*)\s*$")


def _pipfile_requires_from_pylock(requires_python):
    """Map a pylock ``requires-python`` to the Pipfile.lock ``requires`` entry.

    This reverses what ``PylockFile.from_lockfile`` writes (``>=X.Y`` for
    ``python_version`` and ``==X.Y.Z`` for ``python_full_version``). Any other
    specifier is kept as ``python_version`` unchanged.
    """
    match = _REQUIRES_PYTHON_RE.match(requires_python)
    if match:
        operator, version = match.groups()
        if operator == ">=":
            return {"python_version": version}
        if version.count(".") >= 2:
            return {"python_full_version": version}
    return {"python_version": requires_python}


def _same_locked_package(default_data, develop_data) -> bool:
    """Whether two Pipfile.lock entries pin the same artifact, ignoring markers."""
    if not isinstance(default_data, dict) or not isinstance(develop_data, dict):
        return False

    def without_markers(data):
        return {key: value for key, value in data.items() if key != "markers"}

    return without_markers(default_data) == without_markers(develop_data)


def _files_for_lockfile_hashes(name, index_url, hashes, source=None):
    """Find actual distribution files for hashes in a Pipfile.lock entry.

    The Simple API supplies file identities and hashes for both PyPI and
    private indexes. A hash with no matching index file cannot be represented
    as a PEP 751 wheel or sdist.
    """
    from pipenv.patched.pip._internal.index.collector import IndexContent, parse_links
    from pipenv.patched.pip._internal.utils.misc import remove_auth_from_url
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
    from pipenv.patched.pip._vendor.requests.exceptions import RequestException
    from pipenv.utils.internet import get_requests_session
    from pipenv.utils.shell import expand_url_credentials

    wanted = {value[7:].lower() for value in hashes if value.startswith("sha256:")}
    if not wanted:
        return []

    project_url = urljoin(
        expand_url_credentials(index_url.rstrip("/") + "/"),
        canonicalize_name(name) + "/",
    )
    try:
        with get_requests_session(
            max_retries=0,
            verify_ssl=source.get("verify_ssl", True) if source else True,
            source=expand_url_credentials(index_url),
        ) as session:
            response = session.get(
                project_url,
                headers={
                    "Accept": "application/vnd.pypi.simple.v1+json, "
                    "application/vnd.pypi.simple.v1+html;q=0.2, text/html;q=0.1"
                },
                timeout=5,
            )
            response.raise_for_status()
            page = IndexContent(
                response.content,
                response.headers.get("Content-Type", "text/html"),
                response.encoding,
                response.url,
                cache_link_parsing=False,
            )
            links = list(parse_links(page))
    except (RequestException, ValueError, OSError):
        return []

    files = []
    seen = set()
    for link in links:
        digest = link._hashes.get("sha256")
        if not digest or digest.lower() not in wanted:
            continue
        filename = link.filename
        if not filename.endswith((".whl", ".tar.gz", ".zip", ".tar.bz2", ".tar.xz", ".tgz")):
            continue
        if digest.lower() in seen:
            continue
        seen.add(digest.lower())
        files.append(
            {
                "name": filename,
                "url": remove_auth_from_url(link.url_without_fragment),
                "hashes": {"sha256": digest.lower()},
            }
        )
    return sorted(files, key=lambda item: item["name"])


VCS_TYPES = ("git", "hg", "svn", "bzr")
ARCHIVE_SUFFIXES = (".whl", ".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")


def _pylock_source_from_lockfile_entry(package_data: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Pipfile.lock path, VCS or file entry to PEP 751 package fields."""
    vcs_type = next((vcs for vcs in VCS_TYPES if vcs in package_data), None)
    if vcs_type:
        vcs = {"type": vcs_type, "url": package_data[vcs_type]}
        if package_data.get("ref"):
            vcs["commit-id"] = package_data["ref"]
        if package_data.get("subdirectory"):
            vcs["subdirectory"] = package_data["subdirectory"]
        return {"vcs": vcs}

    if "path" not in package_data and "file" not in package_data:
        return {}

    location = package_data.get("path") or package_data["file"]
    if "file" in package_data or location.lower().endswith(ARCHIVE_SUFFIXES):
        archive = {"path" if "path" in package_data else "url": location}
        hashes = {
            algorithm: digest
            for algorithm, _, digest in (
                value.partition(":") for value in package_data.get("hashes", [])
            )
            if digest
        }
        if hashes:
            archive["hashes"] = hashes
        return {"archive": archive}

    directory = {"path": location}
    if package_data.get("editable"):
        directory["editable"] = True
    if package_data.get("subdirectory"):
        directory["subdirectory"] = package_data["subdirectory"]
    return {"directory": directory}


def _lockfile_path(path: str) -> str:
    """Return a pylock.toml path in the form Pipfile.lock uses for local paths.

    PEP 751 writes relative paths as plain ``localpkg``, which pipenv would
    read as a package name, so relative paths get a leading ``./``.
    """
    if Path(path).is_absolute() or path.startswith(("./", "../", ".\\", "..\\")):
        return path
    return f"./{path}"


def _lockfile_source_from_pylock_package(package: Dict[str, Any]) -> Dict[str, Any]:
    """Map PEP 751 directory, VCS and archive fields to a Pipfile.lock entry."""
    if "vcs" in package:
        vcs = package["vcs"]
        entry = {vcs["type"]: vcs.get("url") or vcs.get("path")}
        ref = vcs.get("commit-id") or vcs.get("requested-revision")
        if ref:
            entry["ref"] = ref
        if vcs.get("subdirectory"):
            entry["subdirectory"] = vcs["subdirectory"]
        return entry

    if "directory" in package:
        directory = package["directory"]
        entry = {"path": _lockfile_path(directory["path"])}
        if directory.get("editable"):
            entry = {"editable": True, **entry}
        if directory.get("subdirectory"):
            entry["subdirectory"] = directory["subdirectory"]
        return entry

    if "archive" in package:
        archive = package["archive"]
        entry = (
            {"file": archive["url"]}
            if "url" in archive
            else {"path": _lockfile_path(archive["path"])}
        )
        if archive.get("hashes"):
            entry["hashes"] = [
                f"{algorithm}:{digest}" for algorithm, digest in archive["hashes"].items()
            ]
        return entry

    return {}


def find_pylock_file(directory: Optional[Union[str, Path]] = None) -> Optional[Path]:
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
