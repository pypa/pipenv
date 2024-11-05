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
    try:
        new_version_obj = Version(new_version)
    except InvalidVersion:
        new_version_obj = SpecifierSet(new_version)

    for dependent, req_version in reverse_deps.get(package_name, set()):
        if req_version == "Any":
            continue

        try:
            specifier_set = SpecifierSet(req_version)
            if not specifier_set.contains(new_version_obj):
                conflicts.add(dependent)
        except Exception:  # noqa: PERF203
            # If we can't parse the version requirement, assume it's a conflict
            conflicts.add(dependent)

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
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if not categories:

        if dev and not packages:
            categories = ["default", "develop"]
        elif dev and packages:
            categories = ["develop"]
        else:
            categories = ["default"]
    elif "dev-packages" in categories:
        categories.remove("dev-packages")
        categories.insert(0, "develop")
    elif "packages" in categories:
        categories.remove("packages")
        categories.insert(0, "default")

    # Get current dependency graph
    reverse_deps = get_reverse_dependencies(project)

    index_name = None
    if index_url:
        index_name = add_index_to_pipfile(project, index_url)

    if extra_pip_args:
        os.environ["PIPENV_EXTRA_PIP_ARGS"] = json.dumps(extra_pip_args)

    package_args = list(packages) + [f"-e {pkg}" for pkg in editable_packages]

    # Early conflict detection
    conflicts_found = False
    for package in package_args:
        if "==" in package:
            name, version = package.split("==")
            conflicts = check_version_conflicts(name, version, reverse_deps, lockfile)
            if conflicts:
                conflicts_found = True
                err.print(
                    f"[red bold]Error[/red bold]: Updating [bold]{name}[/bold] "
                    f"to version {version} would create conflicts with: {', '.join(sorted(conflicts))}"
                )

    if conflicts_found:
        err.print(
            "\nTo resolve conflicts, try:\n"
            "1. Explicitly upgrade conflicting packages together\n"
            "2. Use compatible versions\n"
            "3. Remove version constraints from Pipfile"
        )
        sys.exit(1)

    # Create clean package_args first
    has_package_args = False
    if package_args:
        has_package_args = True

    requested_packages = defaultdict(dict)
    for category in categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)

        # Get modified entries if no explicit packages specified
        if not package_args and project.lockfile_exists:
            modified_entries = get_modified_pipfile_entries(project, [pipfile_category])
            for name, entry in modified_entries[category].items():
                requested_packages[pipfile_category][name] = entry

        # Process each package arg
        for package in package_args[:]:
            install_req, _ = expansive_install_req_from_line(package, expand_env=True)

            name, normalized_name, pipfile_entry = project.generate_package_pipfile_entry(
                install_req, package, category=pipfile_category, index_name=index_name
            )

            # Only add to Pipfile if explicitly requested
            if has_package_args:
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

        # When packages are not provided we simply perform full resolution
        upgrade_lock_data = None
        if requested_packages[pipfile_category]:
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
                return

        complete_packages = project.parsed_pipfile.get(pipfile_category, {})

        if upgrade_lock_data is not None:  # Upgrade a subset of packages
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

        # reset package args in case of multiple categories being processed
        if has_package_args is False:
            package_args = []

    lockfile.update({"_meta": project.get_lockfile_meta()})
    project.write_lockfile(lockfile)
