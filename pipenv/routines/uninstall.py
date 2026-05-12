import shutil
import sys
from dataclasses import replace

from pipenv import exceptions
from pipenv.patched.pip._internal.build_env import get_runnable_pip
from pipenv.project import Project
from pipenv.routines.context import RoutineContext
from pipenv.routines.lock import do_lock
from pipenv.utils import console
from pipenv.utils.dependencies import (
    BAD_PACKAGES,
    expansive_install_req_from_line,
    get_lockfile_section_using_pipfile_category,
    get_pipfile_category_using_lockfile_section,
    pep423_name,
)
from pipenv.utils.processes import run_command, subprocess_run
from pipenv.utils.resolver import venv_resolve_deps
from pipenv.utils.shell import cmd_list_to_shell, project_python


def _uninstall_from_environment(project: Project, package, system=False):
    # Execute the uninstall command for the package
    with project.environment.activated() as is_active:
        if not is_active:
            return False

        console.print(f"Uninstalling {package}...", style="bold green")
        cmd = [
            project_python(project, system=system),
            get_runnable_pip(),
            "uninstall",
            package,
            "-y",
        ]
        c = run_command(cmd, is_verbose=project.s.is_verbose())
        console.print(c.stdout, style="cyan")
        if c.returncode != 0:
            console.print(f"Error occurred while uninstalling package {package}.")
            return False
    return True


def do_uninstall(project: Project, ctx: RoutineContext):
    """Uninstall packages from the project.

    Per T_C.9: consumes :class:`~pipenv.routines.context.RoutineContext`
    for every user-facing input (``packages`` / ``editable_packages`` /
    ``python`` / ``system`` / ``lock`` / ``all_dev`` / ``all`` / ``pre`` /
    ``pypi_mirror`` / ``categories``).

    The old ``ctx`` keyword (a Click context, distinct from
    :class:`RoutineContext`) was a CLI-error-rendering passthrough that
    ``cmd_uninstall`` never supplied; it has been dropped per design doc
    section 3, and CLI usage errors at the click layer will fall back to
    Click's default presentation.
    """
    target = ctx.target_env
    policy = ctx.install_policy
    sel = ctx.package_selection

    packages = list(sel.packages) if sel.packages else []
    editable_packages = (
        list(sel.editable_packages) if sel.editable_packages else []
    )
    system = target.system
    pypi_mirror = target.pypi_mirror
    pre = policy.pre
    lock = policy.lock
    all_dev = sel.all_dev
    all = sel.all
    categories = list(sel.categories) if sel.categories else None

    # Initialization similar to the upgrade function
    if not any([packages, editable_packages, all_dev, all]):
        raise exceptions.PipenvUsageError("No package provided!")

    if not categories:
        categories = ["default"]

    lockfile_content = project.lockfile.content

    if all_dev:
        console.print(
            "Un-installing all [yellow][dev-packages][/yellow]...",
            style="bold",
        )
        # Uninstall all dev-packages from environment
        for package in project.get_pipfile_section("dev-packages"):
            _uninstall_from_environment(project, package, system=system)
        # Remove the package from the Pipfile
        if project.reset_category_in_pipfile(category="dev-packages"):
            console.print("Removed [dev-packages] from Pipfile.")
        # Finalize changes to lockfile
        lockfile_content["develop"] = {}
        lockfile_content.update({"_meta": project.lockfile.meta()})
        project.lockfile.write(lockfile_content)

    if all:
        console.print(
            "Un-installing all packages...",
            style="bold",
        )
        # Purge all packages from the virtualenv without touching Pipfile or
        # Pipfile.lock.  The --all flag is documented as "Purge all package(s)
        # from virtualenv. Does not edit Pipfile." — the lockfile must also be
        # left intact so that a subsequent `pipenv install` (or `pipenv sync`)
        # can restore exactly the same environment from the existing lock data.
        do_purge(project, bare=False, downloads=False, allow_global=system)
        return

    package_args = list(packages) + [f"-e {pkg}" for pkg in editable_packages]

    # Determine packages and their dependencies for removal
    for category in categories:
        category = get_lockfile_section_using_pipfile_category(
            category
        )  # In case they passed pipfile category
        pipfile_category = get_pipfile_category_using_lockfile_section(category)

        for package in package_args[:]:
            install_req, _ = expansive_install_req_from_line(package, expand_env=True)
            name, normalized_name, pipfile_entry = project.generate_package_pipfile_entry(
                install_req, package, category=pipfile_category
            )

            # Remove the package from the Pipfile
            if project.remove_package_from_pipfile(
                normalized_name, category=pipfile_category
            ):
                console.print(f"Removed {normalized_name} from Pipfile.")

            # Rebuild the dependencies for resolution from the updated Pipfile
            updated_packages = project.get_pipfile_section(pipfile_category)

            # Resolve dependencies with the package removed
            resolved_lock_data = venv_resolve_deps(
                updated_packages,
                which=project.venv_locator._which,
                project=project,
                lockfile={},
                pipfile_category=pipfile_category,
                pre=pre,
                allow_global=system,
                pypi_mirror=pypi_mirror,
            )

            # Determine which dependencies are no longer needed
            try:
                current_lock_data = lockfile_content[category]
                if current_lock_data:
                    deps_to_remove = [
                        dep for dep in current_lock_data if dep not in resolved_lock_data
                    ]
                    # Remove unnecessary dependencies from Pipfile and lockfile
                    for dep in deps_to_remove:
                        if (
                            category in lockfile_content
                            and dep in lockfile_content[category]
                        ):
                            del lockfile_content[category][dep]
            except KeyError:
                pass  # No lockfile data for this category

    # Finalize changes to lockfile
    lockfile_content.update({"_meta": project.lockfile.meta()})
    project.lockfile.write(lockfile_content)

    # Perform uninstallation of packages and dependencies
    failure = False
    for package in package_args:
        _uninstall_from_environment(project, package, system=system)

    if lock:
        # Build a lock-only ctx carrying the target env + pre flag from
        # the uninstall ctx; clear the package selection so do_lock
        # spans every configured Pipfile section.
        lock_ctx = replace(
            ctx,
            install_policy=replace(policy, pre=pre, lock=False),
            package_selection=replace(sel, categories=()),
        )
        do_lock(project, lock_ctx)

    sys.exit(int(failure))


def do_purge(project, bare=False, downloads=False, allow_global=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            console.print("Clearing out downloads directory...", style="bold")
        shutil.rmtree(project.venv_locator.download_location)
        return

    # Remove comments from the output, if any.
    installed = {
        pkg._normalized_name for pkg in project.environment.get_installed_packages()
    }
    bad_pkgs = {pep423_name(pkg) for pkg in BAD_PACKAGES}
    # Remove setuptools, pip, etc from targets for removal
    to_remove = installed - bad_pkgs

    # Skip purging if there is no packages which needs to be removed
    if not to_remove:
        if not bare:
            console.print("Found 0 installed package, skip purging.")
            console.print("Environment now purged and fresh!", style="green")
        return installed

    if not bare:
        console.print(f"Found {len(to_remove)} installed package(s), purging...")

    command = [
        project_python(project, system=allow_global),
        get_runnable_pip(),
        "uninstall",
        "-y",
    ] + list(to_remove)
    if project.s.is_verbose():
        console.print(f"$ {cmd_list_to_shell(command)}")
    c = subprocess_run(command)
    if c.returncode != 0:
        raise exceptions.UninstallError(
            installed, cmd_list_to_shell(command), c.stdout + c.stderr, c.returncode
        )
    if not bare:
        console.print(c.stdout, style="cyan")
        console.print("Environment now purged and fresh!", style="green")
    return installed
