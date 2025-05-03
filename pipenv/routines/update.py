import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Set, Tuple

from pipenv.exceptions import JSONParseError, PipenvCmdError
from pipenv.patched.pip._vendor.packaging.specifiers import SpecifierSet
from pipenv.patched.pip._vendor.packaging.version import InvalidVersion, Version
from pipenv.routines.outdated import do_outdated
from pipenv.routines.sync import do_sync
from pipenv.utils import err
from pipenv.utils.constants import VCS_LIST
from pipenv.utils.dependencies import (
    expansive_install_req_from_line,
    get_lockfile_section_using_pipfile_category,
    get_pipfile_category_using_lockfile_section,
)
from pipenv.utils.processes import run_command
from pipenv.utils.project import ensure_project
from pipenv.utils.requirements import add_index_to_pipfile
from pipenv.utils.resolver import venv_resolve_deps
from pipenv.vendor import pipdeptree


def do_update(
    project,
    python=None,
    pre=False,
    system=False,
    packages=None,
    editable_packages=None,
    site_packages=False,
    pypi_mirror=None,
    dev=False,
    categories=None,
    index_url=None,
    extra_pip_args=None,
    quiet=False,
    bare=False,
    dry_run=None,
    outdated=False,
    clear=False,
    lock_only=False,
):
    """Update the virtualenv."""
    packages = [p for p in (packages or []) if p]
    editable = [p for p in (editable_packages or []) if p]
    if not outdated:
        outdated = bool(dry_run)

    ensure_project(
        project,
        python=python,
        pypi_mirror=pypi_mirror,
        warn=(not quiet),
        site_packages=site_packages,
        clear=clear,
    )

    if not outdated:
        # Pre-sync packages for pipdeptree resolution to avoid conflicts
        if project.lockfile_exists:
            do_sync(
                project,
                dev=dev,
                categories=categories,
                python=python,
                bare=bare,
                clear=clear,
                pypi_mirror=pypi_mirror,
                extra_pip_args=extra_pip_args,
            )
        upgrade(
            project,
            pre=pre,
            system=system,
            packages=packages,
            editable_packages=editable,
            pypi_mirror=pypi_mirror,
            categories=categories,
            index_url=index_url,
            dev=dev,
            lock_only=lock_only,
            extra_pip_args=extra_pip_args,
        )
        # Finally sync packages after upgrade
        do_sync(
            project,
            dev=dev,
            categories=categories,
            python=python,
            bare=bare,
            clear=clear,
            pypi_mirror=pypi_mirror,
            extra_pip_args=extra_pip_args,
        )
    else:
        do_outdated(
            project,
            clear=clear,
            pre=pre,
            pypi_mirror=pypi_mirror,
        )


def get_reverse_dependencies(project) -> Dict[str, Set[Tuple[str, str]]]:
    """Get reverse dependencies using pipdeptree."""
    pipdeptree_path = Path(pipdeptree.__file__).parent
    python_path = project.python()
    cmd_args = [python_path, str(pipdeptree_path), "-l", "--reverse", "--json-tree"]

    c = run_command(cmd_args, is_verbose=project.s.is_verbose())
    if c.returncode != 0:
        raise PipenvCmdError(c.err, c.out, c.returncode)
    try:
        dep_tree = json.loads(c.stdout.strip())
    except json.JSONDecodeError:
        raise JSONParseError(c.stdout, c.stderr)

    # Build reverse dependency map: package -> set of (dependent_package, required_version)
    reverse_deps = defaultdict(set)

    def process_tree_node(n, parents=None):
        if parents is None:
            parents = []

        package_name = n["package_name"]
        required_version = n.get("required_version", "Any")

        # Add the current node to its parents' reverse dependencies
        for parent in parents:
            reverse_deps[parent].add((package_name, required_version))

        # Process dependencies recursively, keeping track of parent path
        for dep in n.get("dependencies", []):
            process_tree_node(dep, parents + [package_name])

    # Start processing the tree from the root nodes
    for node in dep_tree:
        try:
            process_tree_node(node)
        except Exception as e:  # noqa: PERF203
            err.print(
                f"[red bold]Warning[/red bold]: Unable to analyze dependencies: {str(e)}"
            )

    return reverse_deps


def check_version_conflicts(
    package_name: str,
    new_version: str,
    reverse_deps: Dict[str, Set[Tuple[str, str]]],
    lockfile: dict,
) -> Set[str]:
    """
    Check if updating a package would create version conflicts with its dependents.
    Returns set of conflicting packages.
    """
    conflicts = set()

    # Handle various wildcard patterns
    if new_version == "*":
        # Full wildcard - matches any version
        # We'll use a very permissive specifier
        new_version_obj = SpecifierSet(">=0.0.0")
    elif new_version.endswith(".*"):
        # Major version wildcard like '2.*'
        try:
            major = int(new_version[:-2])
            new_version_obj = SpecifierSet(f">={major},<{major+1}")
        except (ValueError, TypeError):
            # If we can't parse the major version, use a permissive specifier
            new_version_obj = SpecifierSet(">=0.0.0")
    else:
        try:
            new_version_obj = Version(new_version)
        except InvalidVersion:
            try:
                # Try to parse as a specifier set
                new_version_obj = SpecifierSet(new_version)
            except Exception:  # noqa: PERF203
                # If we can't parse the version at all, return no conflicts
                # This allows the installation to proceed and let pip handle it
                return conflicts

    for dependent, req_version in reverse_deps.get(package_name, set()):
        if req_version == "Any":
            continue

        specifier_set = SpecifierSet(req_version)
        # For Version objects, we check if the specifier contains the version
        # For SpecifierSet objects, we need to check compatibility differently
        if isinstance(new_version_obj, Version):
            if not specifier_set.contains(new_version_obj):
                conflicts.add(dependent)
        # Otherwise this is a complex case where we have a specifier vs specifier ...
        # We'll let the resolver figure those out

    return conflicts


def get_modified_pipfile_entries(project, pipfile_categories):
    """
    Detect Pipfile entries that have been modified since the last lock.
    Returns a dict mapping categories to sets of InstallRequirement objects.
    """
    modified = defaultdict(dict)
    lockfile = project.lockfile()

    for pipfile_category in pipfile_categories:
        lockfile_category = get_lockfile_section_using_pipfile_category(pipfile_category)
        pipfile_packages = project.parsed_pipfile.get(pipfile_category, {})
        locked_packages = lockfile.get(lockfile_category, {})

        for package_name, pipfile_entry in pipfile_packages.items():
            if package_name not in locked_packages:
                # New package
                modified[lockfile_category][package_name] = pipfile_entry
                continue

            locked_entry = locked_packages[package_name]
            is_modified = False

            # For string entries, compare directly
            if isinstance(pipfile_entry, str):
                if pipfile_entry != locked_entry.get("version", ""):
                    is_modified = True

            # For dict entries, need to compare relevant fields
            elif isinstance(pipfile_entry, dict):
                if "version" in pipfile_entry:
                    if pipfile_entry["version"] != locked_entry.get("version", ""):
                        is_modified = True

                # Compare VCS fields
                for key in VCS_LIST:
                    if key in pipfile_entry:
                        if (
                            key not in locked_entry
                            or pipfile_entry[key] != locked_entry[key]
                        ):
                            is_modified = True

                # Compare ref for VCS packages
                if "ref" in pipfile_entry:
                    if (
                        "ref" not in locked_entry
                        or pipfile_entry["ref"] != locked_entry["ref"]
                    ):
                        is_modified = True

                # Compare extras
                if "extras" in pipfile_entry:
                    pipfile_extras = set(pipfile_entry["extras"])
                    locked_extras = set(locked_entry.get("extras", []))
                    if pipfile_extras != locked_extras:
                        is_modified = True

            if is_modified:
                modified[lockfile_category][package_name] = pipfile_entry

    return modified


def _prepare_categories(categories, dev, packages):
    """Prepare and normalize categories for upgrade."""
    if not categories:
        if dev and not packages:
            return ["default", "develop"]
        elif dev and packages:
            return ["develop"]
        else:
            return ["default"]

    result = categories.copy()
    if "dev-packages" in result:
        result.remove("dev-packages")
        result.insert(0, "develop")
    elif "packages" in result:
        result.remove("packages")
        result.insert(0, "default")

    return result


def _find_additional_categories(packages, lockfile, current_categories):
    """Find additional categories where packages exist."""
    if not packages:
        return []

    # Get all available categories from the lockfile
    all_lockfile_categories = [cat for cat in lockfile.keys() if not cat.startswith("_")]

    # Check if any of the packages to upgrade are also in other categories
    additional_categories = []
    for category in all_lockfile_categories:
        if category in current_categories:
            continue  # Skip categories already in the list

        category_section = lockfile.get(category, {})
        for package in packages:
            package_name = package.split("==")[0] if "==" in package else package
            if package_name in category_section:
                # If the package is also in this category, add it to categories
                additional_categories.append(category)
                err.print(
                    f"[bold][green]Package {package_name} found in {category} section, will update there too.[/bold][/green]"
                )
                break

    return additional_categories


def _detect_conflicts(package_args, reverse_deps, lockfile):
    """Detect version conflicts in package arguments."""
    conflicts_found = False
    for package in package_args:
        # Handle both == and = version specifiers
        if "==" in package:
            name, version = package.split("==", 1)  # Split only on the first occurrence
        elif "=" in package and not package.startswith("-e"):  # Avoid matching -e flag
            name, version = package.split("=", 1)  # Split only on the first occurrence
        else:
            continue  # Skip packages without version specifiers

        conflicts = check_version_conflicts(name, version, reverse_deps, lockfile)
        if conflicts:
            conflicts_found = True
            err.print(
                f"[red bold]Error[/red bold]: Updating [bold]{name}[/bold] "
                f"to version {version} would create conflicts with: {', '.join(sorted(conflicts))}"
            )

    return conflicts_found


def _process_package_args(
    project,
    package_args,
    pipfile_category,
    index_name,
    reverse_deps,
    explicitly_requested,
    category,
    has_package_args,
    requested_packages,
):
    """Process package arguments and update requested_packages."""
    for package in package_args[:]:
        install_req, _ = expansive_install_req_from_line(package, expand_env=True)

        name, normalized_name, pipfile_entry = project.generate_package_pipfile_entry(
            install_req, package, category=pipfile_category, index_name=index_name
        )

        # Only add to Pipfile if this category was explicitly requested for this package
        if has_package_args and (
            normalized_name not in explicitly_requested
            or category in explicitly_requested.get(normalized_name, [])
        ):
            project.add_pipfile_entry_to_pipfile(
                name, normalized_name, pipfile_entry, category=pipfile_category
            )

        requested_packages[pipfile_category][normalized_name] = pipfile_entry

        # Handle reverse dependencies
        if normalized_name in reverse_deps:
            for dependency, _ in reverse_deps[normalized_name]:
                pipfile_entry = project.get_pipfile_entry(
                    dependency, category=pipfile_category
                )
                if not pipfile_entry:
                    requested_packages[pipfile_category][dependency] = {
                        normalized_name: "*"
                    }
                    continue
                requested_packages[pipfile_category][dependency] = pipfile_entry


def _resolve_and_update_lockfile(
    project,
    requested_packages,
    pipfile_category,
    category,
    package_args,
    pre,
    system,
    pypi_mirror,
    lockfile,
):
    """Resolve dependencies and update lockfile."""
    if not requested_packages[pipfile_category]:
        return None

    err.print(
        f"[bold][green]Upgrading[/bold][/green] {', '.join(package_args)} in [{category}] dependencies."
    )

    # Resolve package to generate constraints of new package data
    upgrade_lock_data = venv_resolve_deps(
        requested_packages[pipfile_category],
        which=project._which,
        project=project,
        lockfile={},
        pipfile_category=pipfile_category,
        pre=pre,
        allow_global=system,
        pypi_mirror=pypi_mirror,
    )

    if not upgrade_lock_data:
        err.print("Nothing to upgrade!")
        return None

    complete_packages = project.parsed_pipfile.get(pipfile_category, {})

    # Upgrade a subset of packages
    full_lock_resolution = venv_resolve_deps(
        complete_packages,
        which=project._which,
        project=project,
        lockfile={},
        pipfile_category=pipfile_category,
        pre=pre,
        allow_global=system,
        pypi_mirror=pypi_mirror,
    )

    # Update lockfile with verified resolution data
    for package_name in upgrade_lock_data:
        correct_package_lock = full_lock_resolution.get(package_name)
        if correct_package_lock:
            if category not in lockfile:
                lockfile[category] = {}
            lockfile[category][package_name] = correct_package_lock

    return upgrade_lock_data


def _clean_unused_dependencies(
    project, lockfile, category, full_lock_resolution, original_lockfile
):
    """
    Remove dependencies that are no longer needed after an upgrade.

    Args:
        project: The project instance
        lockfile: The current lockfile being built
        category: The category to clean (e.g., 'default', 'develop')
        full_lock_resolution: The complete resolution of dependencies
        original_lockfile: The original lockfile before the upgrade
    """
    if category not in lockfile or category not in original_lockfile:
        return

    # Get the set of packages in the new resolution
    resolved_packages = set(full_lock_resolution.keys())

    # Get the set of packages in the original lockfile for this category
    original_packages = set(original_lockfile[category].keys())

    # Find packages that were in the original lockfile but not in the new resolution
    unused_packages = original_packages - resolved_packages

    # Remove unused packages from the lockfile
    for package_name in unused_packages:
        if package_name in lockfile[category]:
            if project.s.is_verbose():
                err.print(f"Removing unused dependency: {package_name}")
            del lockfile[category][package_name]


def upgrade(
    project,
    pre=False,
    system=False,
    packages=None,
    editable_packages=None,
    pypi_mirror=None,
    index_url=None,
    categories=None,
    dev=False,
    lock_only=False,
    extra_pip_args=None,
):
    """Enhanced upgrade command with dependency conflict detection."""
    lockfile = project.lockfile()
    # Store the original lockfile for comparison later
    original_lockfile = {
        k: v.copy() if isinstance(v, dict) else v for k, v in lockfile.items()
    }

    if not pre:
        pre = project.settings.get("allow_prereleases")

    # Prepare categories
    categories = _prepare_categories(categories, dev, packages)

    # Get current dependency graph
    reverse_deps = get_reverse_dependencies(project)

    # Set up index and environment
    index_name = None
    if index_url:
        index_name = add_index_to_pipfile(project, index_url)

    if extra_pip_args:
        os.environ["PIPENV_EXTRA_PIP_ARGS"] = json.dumps(extra_pip_args)

    # Prepare package arguments
    package_args = list(packages or []) + [
        f"-e {pkg}" for pkg in (editable_packages or [])
    ]

    # Track which packages were explicitly requested for which categories
    explicitly_requested = {}
    for package in packages or []:
        package_name = package.split("==")[0] if "==" in package else package
        explicitly_requested[package_name] = categories[:]  # Copy the original categories

    # Find additional categories where packages exist
    additional_categories = _find_additional_categories(packages, lockfile, categories)
    categories.extend(additional_categories)

    # Early conflict detection
    conflicts_found = _detect_conflicts(package_args, reverse_deps, lockfile)
    if conflicts_found:
        err.print(
            "\nTo resolve conflicts, try:\n"
            "1. Explicitly upgrade conflicting packages together\n"
            "2. Use compatible versions\n"
            "3. Remove version constraints from Pipfile"
        )
        sys.exit(1)

    # Flag for tracking if we have package arguments
    has_package_args = bool(package_args)

    # Process each category
    requested_packages = defaultdict(dict)
    category_resolutions = {}

    for category in categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)

        # Get modified entries if no explicit packages specified
        if not package_args and project.lockfile_exists:
            modified_entries = get_modified_pipfile_entries(project, [pipfile_category])
            for name, entry in modified_entries[category].items():
                requested_packages[pipfile_category][name] = entry

        # Process package arguments
        if package_args:
            _process_package_args(
                project,
                package_args,
                pipfile_category,
                index_name,
                reverse_deps,
                explicitly_requested,
                category,
                has_package_args,
                requested_packages,
            )

        # Resolve dependencies and update lockfile
        upgrade_lock_data = _resolve_and_update_lockfile(
            project,
            requested_packages,
            pipfile_category,
            category,
            package_args,
            pre,
            system,
            pypi_mirror,
            lockfile,
        )

        # Store the full resolution for this category
        if upgrade_lock_data:
            complete_packages = project.parsed_pipfile.get(pipfile_category, {})
            full_lock_resolution = venv_resolve_deps(
                complete_packages,
                which=project._which,
                project=project,
                lockfile={},
                pipfile_category=pipfile_category,
                pre=pre,
                allow_global=system,
                pypi_mirror=pypi_mirror,
            )
            category_resolutions[category] = full_lock_resolution

            # Clean up unused dependencies
            _clean_unused_dependencies(
                project, lockfile, category, full_lock_resolution, original_lockfile
            )

        # Reset package args for next category if needed
        if not has_package_args:
            package_args = []

    # Update and write lockfile
    lockfile.update({"_meta": project.get_lockfile_meta()})
    project.write_lockfile(lockfile)
