import sys

from pipenv.patched.pip._internal.build_env import get_runnable_pip
from pipenv.routines.lock import do_lock
from pipenv.utils import console, err
from pipenv.utils.processes import run_command
from pipenv.utils.project import ensure_project
from pipenv.utils.requirements import BAD_PACKAGES
from pipenv.utils.shell import project_python


def do_clean(
    project,
    python=None,
    dry_run=False,
    bare=False,
    pypi_mirror=None,
    system=False,
):
    # Ensure that virtualenv is available.
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    ensure_project(project, python=python, validate=False, pypi_mirror=pypi_mirror)
    ensure_lockfile(project, pypi_mirror=pypi_mirror)
    # Make sure that the virtualenv's site packages are configured correctly
    # otherwise we may end up removing from the global site packages directory
    installed_package_names = project.installed_package_names.copy()
    # Remove known "bad packages" from the list.
    for bad_package in BAD_PACKAGES:
        if canonicalize_name(bad_package) in installed_package_names:
            if project.s.is_verbose():
                err.print(f"Ignoring {bad_package}.")
            installed_package_names.remove(canonicalize_name(bad_package))
    # Intelligently detect if --dev should be used or not.
    locked_packages = {
        canonicalize_name(pkg) for pkg in project.lockfile_package_names["combined"]
    }
    for used_package in locked_packages:
        if used_package in installed_package_names:
            installed_package_names.remove(used_package)
    failure = False
    for apparent_bad_package in installed_package_names:
        if dry_run and not bare:
            console.print(apparent_bad_package)
        else:
            if not bare:
                console.print(
                    f"Uninstalling {apparent_bad_package}...", style="white bold"
                )
            # Uninstall the package.
            cmd = [
                project_python(project, system=system),
                get_runnable_pip(),
                "uninstall",
                apparent_bad_package,
                "-y",
            ]
            c = run_command(cmd, is_verbose=project.s.is_verbose())
            if c.returncode != 0:
                failure = True
    sys.exit(int(failure))


def ensure_lockfile(project, pypi_mirror=None):
    """Ensures that the lockfile is up-to-date."""
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if project.lockfile_exists:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            err.print(
                f"Pipfile.lock ({old_hash[-6:]}) out of date, updating to ({new_hash[-6:]})...",
                style="bold yellow",
            )
            do_lock(project, pypi_mirror=pypi_mirror)
    else:
        do_lock(project, pypi_mirror=pypi_mirror)
