import shutil
import sys

from pipenv import exceptions
from pipenv.patched.pip._internal.build_env import get_runnable_pip
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.routines.lock import do_lock
from pipenv.utils.dependencies import (
    expansive_install_req_from_line,
    get_canonical_names,
    get_lockfile_section_using_pipfile_category,
    get_pipfile_category_using_lockfile_section,
    pep423_name,
)
from pipenv.utils.processes import run_command, subprocess_run
from pipenv.utils.project import ensure_project
from pipenv.utils.requirements import BAD_PACKAGES
from pipenv.utils.shell import cmd_list_to_shell, project_python
from pipenv.vendor import click


def do_uninstall(
    project,
    packages=None,
    editable_packages=None,
    python=False,
    system=False,
    lock=False,
    all_dev=False,
    all=False,
    pypi_mirror=None,
    ctx=None,
    categories=None,
):
    # Automatically use an activated virtualenv.
    if project.s.PIPENV_USE_SYSTEM:
        system = True
    # Ensure that virtualenv is available.
    ensure_project(project, python=python, pypi_mirror=pypi_mirror)
    # Uninstall all dependencies, if --all was provided.
    if not any([packages, editable_packages, all_dev, all]):
        raise exceptions.PipenvUsageError("No package provided!", ctx=ctx)
    if not categories:
        categories = project.get_package_categories(for_lockfile=True)
    editable_pkgs = []
    for p in editable_packages:
        if p:
            install_req, name = expansive_install_req_from_line(f"-e {p}")
            editable_pkgs.append(name)
    packages += editable_pkgs
    package_names = {p for p in packages if p}
    package_map = {canonicalize_name(p): p for p in packages if p}
    installed_package_names = project.installed_package_names
    if project.lockfile_exists:
        project_pkg_names = project.lockfile_package_names
    else:
        project_pkg_names = project.pipfile_package_names
    # Uninstall [dev-packages], if --dev was provided.
    if all_dev:
        if (
            "dev-packages" not in project.parsed_pipfile
            and not project_pkg_names["develop"]
        ):
            click.echo(
                click.style(
                    "No {} to uninstall.".format(
                        click.style("[dev-packages]", fg="yellow")
                    ),
                    bold=True,
                )
            )
            return
        click.secho(
            click.style(
                "Un-installing {}...".format(click.style("[dev-packages]", fg="yellow")),
                bold=True,
            )
        )
        preserve_packages = set()
        dev_packages = set()
        for category in project.get_package_categories(for_lockfile=True):
            if category == "develop":
                dev_packages |= set(project_pkg_names[category])
            else:
                preserve_packages |= set(project_pkg_names[category])

        package_names = dev_packages - preserve_packages

    # Remove known "bad packages" from the list.
    bad_pkgs = get_canonical_names(BAD_PACKAGES)
    ignored_packages = bad_pkgs & set(package_map)
    for ignored_pkg in get_canonical_names(ignored_packages):
        if project.s.is_verbose():
            click.echo(f"Ignoring {ignored_pkg}.", err=True)
        package_names.discard(package_map[ignored_pkg])

    used_packages = project_pkg_names["combined"] & installed_package_names
    failure = False
    if all:
        click.echo(
            click.style(
                "Un-installing all {} and {}...".format(
                    click.style("[dev-packages]", fg="yellow"),
                    click.style("[packages]", fg="yellow"),
                ),
                bold=True,
            )
        )
        do_purge(project, bare=False, allow_global=system)
        sys.exit(0)

    selected_pkg_map = {canonicalize_name(p): p for p in package_names}
    packages_to_remove = [
        package_name
        for normalized, package_name in selected_pkg_map.items()
        if normalized in (used_packages - bad_pkgs)
    ]
    lockfile = project.get_or_create_lockfile(categories=categories)
    for category in categories:
        category = get_lockfile_section_using_pipfile_category(category)
        for normalized_name, package_name in selected_pkg_map.items():
            if normalized_name in project.lockfile_content[category]:
                click.echo(
                    "{} {} {} {}".format(
                        click.style("Removing", fg="cyan"),
                        click.style(package_name, fg="green"),
                        click.style("from", fg="cyan"),
                        click.style("Pipfile.lock...", fg="white"),
                    )
                )
                if normalized_name in lockfile[category]:
                    del lockfile[category][normalized_name]
                lockfile.write()

            pipfile_category = get_pipfile_category_using_lockfile_section(category)
            if project.remove_package_from_pipfile(
                package_name, category=pipfile_category
            ):
                click.secho(
                    f"Removed {package_name} from Pipfile category {pipfile_category}",
                    fg="green",
                )

    for normalized_name, package_name in selected_pkg_map.items():
        still_remains = False
        for category in project.get_package_categories():
            if project.get_package_name_in_pipfile(normalized_name, category=category):
                still_remains = True
        if not still_remains:
            # Uninstall the package.
            if package_name in packages_to_remove:
                click.secho(
                    f"Uninstalling {click.style(package_name)}...",
                    fg="green",
                    bold=True,
                )
                with project.environment.activated():
                    cmd = [
                        project_python(project, system=system),
                        get_runnable_pip(),
                        "uninstall",
                        package_name,
                        "-y",
                    ]
                    c = run_command(cmd, is_verbose=project.s.is_verbose())
                    click.secho(c.stdout, fg="cyan")
                    if c.returncode != 0:
                        failure = True

    if lock:
        do_lock(project, system=system, pypi_mirror=pypi_mirror)
    sys.exit(int(failure))


def do_purge(project, bare=False, downloads=False, allow_global=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            click.secho("Clearing out downloads directory...", bold=True)
        shutil.rmtree(project.download_location)
        return

    # Remove comments from the output, if any.
    installed = {
        pep423_name(pkg.project_name)
        for pkg in project.environment.get_installed_packages()
    }
    bad_pkgs = {pep423_name(pkg) for pkg in BAD_PACKAGES}
    # Remove setuptools, pip, etc from targets for removal
    to_remove = installed - bad_pkgs

    # Skip purging if there is no packages which needs to be removed
    if not to_remove:
        if not bare:
            click.echo("Found 0 installed package, skip purging.")
            click.secho("Environment now purged and fresh!", fg="green")
        return installed

    if not bare:
        click.echo(f"Found {len(to_remove)} installed package(s), purging...")

    command = [
        project_python(project, system=allow_global),
        get_runnable_pip(),
        "uninstall",
        "-y",
    ] + list(to_remove)
    if project.s.is_verbose():
        click.echo(f"$ {cmd_list_to_shell(command)}")
    c = subprocess_run(command)
    if c.returncode != 0:
        raise exceptions.UninstallError(
            installed, cmd_list_to_shell(command), c.stdout + c.stderr, c.returncode
        )
    if not bare:
        click.secho(c.stdout, fg="cyan")
        click.secho("Environment now purged and fresh!", fg="green")
    return installed
