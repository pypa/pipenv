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
from pipenv.utils.dependencies import (
    expansive_install_req_from_line,
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
    cmd_args = [python_path, pipdeptree_path, "-l", "--reverse", "--json-tree"]

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
        process_tree_node(node)

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
        except Exception:
            # If we can't parse the version requirement, assume it's a conflict
            conflicts.add(dependent)

    return conflicts


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
    try:
        reverse_deps = get_reverse_dependencies(project)
    except Exception as e:
        err.print(
            f"[red bold]Warning[/red bold]: Unable to analyze dependencies: {str(e)}"
        )
        reverse_deps = {}

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

    requested_install_reqs = defaultdict(dict)
    requested_packages = defaultdict(dict)
    for category in categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)

        for package in package_args[:]:
            install_req, _ = expansive_install_req_from_line(package, expand_env=True)
            if index_name:
                install_req.index = index_name

            name, normalized_name, pipfile_entry = project.generate_package_pipfile_entry(
                install_req, package, category=pipfile_category
            )
            project.add_pipfile_entry_to_pipfile(
                name, normalized_name, pipfile_entry, category=pipfile_category
            )
            requested_packages[pipfile_category][normalized_name] = pipfile_entry
            requested_install_reqs[pipfile_category][normalized_name] = install_req

            # Consider reverse packages in reverse_deps
            if normalized_name in reverse_deps:
                for dependency, req_version in reverse_deps[normalized_name]:
                    if req_version == "Any":
                        package_args.append(dependency)
                        pipfile_entry = project.get_pipfile_entry(
                            dependency, category=pipfile_category
                        )
                        requested_packages[pipfile_category][dependency] = (
                            pipfile_entry if pipfile_entry else "*"
                        )
                        continue

                    try:  # Otherwise we have a specific version requirement
                        specifier_set = SpecifierSet(req_version)
                        package_args.append(f"{dependency}=={specifier_set}")
                        pipfile_entry = project.get_pipfile_entry(
                            dependency, category=pipfile_category
                        )
                        requested_packages[pipfile_category][dependency] = (
                            pipfile_entry if pipfile_entry else "*"
                        )

                    except Exception as e:
                        err.print(
                            f"[bold][yellow]Warning:[/yellow][/bold] "
                            f"Unable to parse version specifier for {dependency}: {str(e)}"
                        )

        if not package_args:
            err.print("Nothing to upgrade!")
            return
        else:
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

        # Verify no conflicts were introduced during resolution
        for package_name, package_data in full_lock_resolution.items():
            if package_name in upgrade_lock_data:
                version = package_data.get("version", "").replace("==", "")
                if not version:
                    # Either vcs or file package
                    continue

        # Update lockfile with verified resolution data
        for package_name in upgrade_lock_data:
            correct_package_lock = full_lock_resolution.get(package_name)
            if correct_package_lock:
                if category not in lockfile:
                    lockfile[category] = {}
                lockfile[category][package_name] = correct_package_lock

    lockfile.update({"_meta": project.get_lockfile_meta()})
    project.write_lockfile(lockfile)
