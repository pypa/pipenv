import importlib.util
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def _ensure_modules():
    spec = importlib.util.spec_from_file_location(
        "typing_extensions",
        location=os.path.join(
            os.path.dirname(__file__), "patched", "pip", "_vendor", "typing_extensions.py"
        ),
    )
    typing_extensions = importlib.util.module_from_spec(spec)
    sys.modules["typing_extensions"] = typing_extensions
    spec.loader.exec_module(typing_extensions)
    spec = importlib.util.spec_from_file_location(
        "pipenv", location=os.path.join(os.path.dirname(__file__), "__init__.py")
    )
    pipenv = importlib.util.module_from_spec(spec)
    sys.modules["pipenv"] = pipenv
    spec.loader.exec_module(pipenv)


def get_parser():
    from argparse import ArgumentParser

    parser = ArgumentParser("pipenv-resolver")
    parser.add_argument("--pre", action="store_true", default=False)
    parser.add_argument("--clear", action="store_true", default=False)
    parser.add_argument("--verbose", "-v", action="count", default=False)
    parser.add_argument(
        "--category",
        metavar="category",
        action="store",
        default=None,
    )
    parser.add_argument("--system", action="store_true", default=False)
    parser.add_argument("--parse-only", action="store_true", default=False)
    parser.add_argument(
        "--pipenv-site",
        metavar="pipenv_site_dir",
        action="store",
        default=os.environ.get("PIPENV_SITE_DIR"),
    )
    parser.add_argument(
        "--requirements-dir",
        metavar="requirements_dir",
        action="store",
        default=os.environ.get("PIPENV_REQ_DIR"),
    )
    parser.add_argument(
        "--write",
        metavar="write",
        action="store",
        default=os.environ.get("PIPENV_RESOLVER_FILE"),
    )
    parser.add_argument(
        "--constraints-file",
        metavar="constraints_file",
        action="store",
        default=None,
    )
    parser.add_argument("packages", nargs="*")
    return parser


def which(*args, **kwargs):
    return sys.executable


def handle_parsed_args(parsed):
    if parsed.verbose:
        os.environ["PIPENV_VERBOSITY"] = "1"
        os.environ["PIP_RESOLVER_DEBUG"] = "1"
    if parsed.constraints_file:
        with open(parsed.constraints_file) as constraints:
            file_constraints = constraints.read().strip().split("\n")
        os.unlink(parsed.constraints_file)
        packages = {}
        for line in file_constraints:
            dep_name, pip_line = line.split(",", 1)
            packages[dep_name] = pip_line
        parsed.packages = packages
    return parsed


@dataclass
class PackageSource:
    """Represents the source/origin of a package."""

    index: Optional[str] = None
    url: Optional[str] = None
    vcs: Optional[str] = None
    ref: Optional[str] = None
    path: Optional[Path] = None
    subdirectory: Optional[str] = None

    @property
    def is_vcs(self) -> bool:
        return bool(self.vcs)

    @property
    def is_local(self) -> bool:
        return bool(self.path)


@dataclass
class PackageRequirement:
    """Core package requirement information."""

    name: str
    version: Optional[str] = None
    extras: Set[str] = field(default_factory=set)
    markers: Optional[str] = None
    hashes: Set[str] = field(default_factory=set)
    source: PackageSource = field(default_factory=PackageSource)

    def __post_init__(self):
        if isinstance(self.extras, list):
            self.extras = set(self.extras)
        if isinstance(self.hashes, list):
            self.hashes = set(self.hashes)


@dataclass
class Entry:
    """Represents a resolved package entry with its dependencies and constraints."""

    name: str
    entry_dict: Dict[str, Any]
    project: Any  # Could be more specific with a Project type
    resolver: Any  # Could be more specific with a Resolver type
    reverse_deps: Optional[Dict[str, Any]] = None
    category: Optional[str] = None

    def __post_init__(self):
        """Initialize derived attributes after dataclass initialization."""
        self.lockfile_section = self._get_lockfile_section()
        self.pipfile = self._get_pipfile_content()
        self.requirement = self._build_requirement()

    def _build_requirement(self) -> PackageRequirement:
        """Construct a PackageRequirement from entry data."""
        # Extract VCS information
        vcs_info = self._extract_vcs_info()
        source = PackageSource(
            index=self.resolver.index_lookup.get(self.name), **vcs_info
        )

        # Clean and normalize version
        version = self._clean_version(self.entry_dict.get("version"))

        # Build the core requirement
        return PackageRequirement(
            name=self.name,
            version=version,
            extras=set(self.entry_dict.get("extras", [])),
            markers=self._clean_markers(),
            hashes=set(self.entry_dict.get("hashes", [])),
            source=source,
        )

    def _extract_vcs_info(self) -> Dict[str, Optional[str]]:
        """Extract VCS information from entry dict and lockfile."""
        vcs_info = {}
        vcs_keys = {"git", "hg", "svn", "bzr"}

        # Check both entry_dict and lockfile_dict for VCS info
        for key in vcs_keys:
            if key in self.entry_dict:
                vcs_info["vcs"] = key
                vcs_info["url"] = self.entry_dict[key]
                vcs_info["ref"] = self.entry_dict.get("ref")
                vcs_info["subdirectory"] = self.entry_dict.get("subdirectory")
                break

        return vcs_info

    @staticmethod
    def _clean_version(version: Optional[str]) -> Optional[str]:
        """Clean and normalize version strings."""
        if not version:
            return None
        if version.strip().lower() in {"any", "<any>", "*"}:
            return "*"
        if not any(
            version.startswith(op) for op in ("==", ">=", "<=", "~=", "!=", ">", "<")
        ):
            version = f"=={version}"
        return version

    def _clean_markers(self) -> Optional[str]:
        """Clean and normalize marker strings."""
        markers = []
        marker_keys = {
            "sys_platform",
            "python_version",
            "os_name",
            "platform_machine",
            "markers",
        }

        for key in marker_keys:
            if key in self.entry_dict:
                value = self.entry_dict.pop(key)
                if value and key != "markers":
                    markers.append(f"{key} {value}")
                elif value:  # key == "markers"
                    markers.append(value)

        return " and ".join(markers) if markers else None

    def _get_lockfile_section(self) -> str:
        """Get the appropriate lockfile section based on category."""
        from pipenv.utils.dependencies import get_lockfile_section_using_pipfile_category

        return get_lockfile_section_using_pipfile_category(self.category)

    def _get_pipfile_content(self) -> Dict[str, Any]:
        """Get and normalize pipfile content."""
        from pipenv.utils.toml import tomlkit_value_to_python

        return tomlkit_value_to_python(self.project.parsed_pipfile.get(self.category, {}))

    @property
    def get_cleaned_dict(self) -> Dict[str, Any]:
        """Create a cleaned dictionary representation of the entry."""
        cleaned = {
            "name": self.name,
            "version": self.requirement.version,
            "extras": (
                sorted(self.requirement.extras) if self.requirement.extras else None
            ),
            "markers": self.requirement.markers,
            "hashes": (
                sorted(self.requirement.hashes) if self.requirement.hashes else None
            ),
            "subdirectory": self.requirement.source.subdirectory,
            "editable": self.entry_dict.get("editable", None),
            "path": self.requirement.source.path,
            "file": self.requirement.source.path,
        }

        # Add index if present
        if self.requirement.source.index:
            cleaned["index"] = self.requirement.source.index

        # Add VCS information if present
        if self.requirement.source.is_vcs:
            cleaned[self.requirement.source.vcs] = self.requirement.source.url
            if self.entry_dict.get("ref"):
                cleaned["ref"] = self.entry_dict["ref"]
            elif self.requirement.source.ref:
                cleaned["ref"] = self.requirement.source.ref
            cleaned.pop("version", None)  # Remove version for VCS entries

        # Clean up None values
        return {k: v for k, v in cleaned.items() if v is not None}

    def validate_constraints(self) -> bool:
        """Validate that all constraints are satisfied."""
        from pipenv.exceptions import DependencyConflict
        from pipenv.patched.pip._vendor.packaging.requirements import Requirement

        constraints = self.resolver.parsed_constraints
        version = self.requirement.version

        if not version:
            return True

        # Remove any operator from version for comparison
        clean_version = self._strip_version(version)

        for constraint in constraints:
            if not isinstance(constraint, Requirement):
                continue

            if not constraint.name == self.name:
                continue

            if not constraint.specifier.contains(clean_version, prereleases=True):
                msg = (
                    f"Cannot resolve conflicting version {self.name}{constraint.specifier} "
                    f"while {self.name}=={clean_version} is locked."
                )
                raise DependencyConflict(msg)
        return True

    @staticmethod
    def _strip_version(version: str) -> str:
        """Remove version operators from a version string."""
        operators = {"==", ">=", "<=", "~=", "!=", ">", "<"}
        for op in operators:
            if version.startswith(op):
                return version[len(op) :].strip()
        return version.strip()


def process_resolver_results(
    results: List[Dict[str, Any]], resolver: Any, project: Any, category: Optional[str]
) -> List[Dict[str, Any]]:
    """
    Process the results from the dependency resolver into cleaned lockfile entries.

    Args:
        results: Raw results from the resolver
        resolver: The resolver instance that produced the results
        project: The current project instance
        category: The category of dependencies being processed

    Returns:
        List of processed entries ready for the lockfile
    """
    if not results:
        return []

    # Get reverse dependencies for the project
    reverse_deps = project.environment.reverse_dependencies()

    processed_results = []
    for result in results:
        # Create Entry instance with our new dataclass
        entry = Entry(
            name=result["name"],
            entry_dict=result,
            project=project,
            resolver=resolver,
            reverse_deps=reverse_deps,
            category=category,
        )

        # Get the cleaned dictionary representation
        cleaned_entry = entry.get_cleaned_dict

        # Validate the entry meets all constraints
        entry.validate_constraints()

        processed_results.append(cleaned_entry)

    return processed_results


def resolve_packages(
    pre: bool,
    clear: bool,
    verbose: bool,
    system: bool,
    write: Optional[str],
    requirements_dir: Optional[str],
    packages: Dict[str, Any],
    pipfile_category: Optional[str],
    constraints: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolve package dependencies and return processed results.

    Args:
        pre: Whether to include pre-release versions
        clear: Whether to clear caches
        verbose: Whether to output verbose logging
        system: Whether to use system packages
        write: Path to write results to
        requirements_dir: Directory containing requirements files
        packages: Package specifications to resolve
        pipfile_category: Category of dependencies being processed
        constraints: Additional constraints to apply

    Returns:
        List of processed package entries
    """
    from pipenv.project import Project
    from pipenv.utils.internet import create_mirror_source, replace_pypi_sources
    from pipenv.utils.resolver import resolve_deps

    # Handle mirror configuration
    pypi_mirror_source = (
        create_mirror_source(os.environ["PIPENV_PYPI_MIRROR"], "pypi_mirror")
        if "PIPENV_PYPI_MIRROR" in os.environ
        else None
    )

    # Update packages with constraints if provided
    if constraints:
        packages.update(constraints)

    # Initialize project and configure sources
    project = Project()
    sources = (
        replace_pypi_sources(project.pipfile_sources(), pypi_mirror_source)
        if pypi_mirror_source
        else project.pipfile_sources()
    )

    # Resolve dependencies
    results, resolver = resolve_deps(
        packages,
        which,
        project=project,
        pre=pre,
        pipfile_category=pipfile_category,
        sources=sources,
        clear=clear,
        allow_global=system,
        req_dir=requirements_dir,
    )

    # Process results
    processed_results = process_resolver_results(
        results, resolver, project, pipfile_category
    )

    # Write results if requested
    if write:
        with open(write, "w") as fh:
            json.dump(processed_results, fh)

    return processed_results


def _main(
    pre,
    clear,
    verbose,
    system,
    write,
    requirements_dir,
    packages,
    parse_only=False,
    category=None,
):
    resolve_packages(
        pre, clear, verbose, system, write, requirements_dir, packages, category
    )


def main(argv=None):
    parser = get_parser()
    parsed, remaining = parser.parse_known_args(argv)
    _ensure_modules()
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUNBUFFERED"] = "1"
    parsed = handle_parsed_args(parsed)
    if not parsed.verbose:
        logging.getLogger("pipenv").setLevel(logging.WARN)
    _main(
        parsed.pre,
        parsed.clear,
        parsed.verbose,
        parsed.system,
        parsed.write,
        parsed.requirements_dir,
        parsed.packages,
        parse_only=parsed.parse_only,
        category=parsed.category,
    )


if __name__ == "__main__":
    main()
