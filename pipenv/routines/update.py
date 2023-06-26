import sys

from pipenv.routines.install import do_sync
from pipenv.routines.lock import do_lock
from pipenv.routines.outdated import do_outdated
from pipenv.utils.dependencies import (
    convert_deps_to_pip,
    get_pipfile_category_using_lockfile_section,
    is_star,
    pep423_name,
)
from pipenv.utils.project import ensure_project
from pipenv.utils.requirements import add_index_to_pipfile
from pipenv.utils.resolver import venv_resolve_deps
from pipenv.vendor import click
from pipenv.vendor.requirementslib.models.requirements import Requirement


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
    keep_outdated=False,
    clear=False,
    lock_only=False,
):
    ensure_project(
        project,
        python=python,
        pypi_mirror=pypi_mirror,
        warn=(not quiet),
        site_packages=site_packages,
        clear=clear,
    )
    if not outdated:
        outdated = bool(dry_run)
    if outdated:
        do_outdated(
            project,
            clear=clear,
            pre=pre,
            pypi_mirror=pypi_mirror,
        )
    packages = [p for p in packages if p]
    editable = [p for p in editable_packages if p]
    if not packages:
        click.echo(
            "{} {} {} {}{}".format(
                click.style("Running", bold=True),
                click.style("$ pipenv lock", fg="yellow", bold=True),
                click.style("then", bold=True),
                click.style("$ pipenv sync", fg="yellow", bold=True),
                click.style(".", bold=True),
            )
        )
        do_lock(
            project,
            clear=clear,
            pre=pre,
            keep_outdated=keep_outdated,
            pypi_mirror=pypi_mirror,
            write=not quiet,
        )
    else:
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
        )

    do_sync(
        project,
        dev=dev,
        categories=categories,
        python=python,
        bare=bare,
        dont_upgrade=not keep_outdated,
        user=False,
        clear=clear,
        unused=False,
        pypi_mirror=pypi_mirror,
        extra_pip_args=extra_pip_args,
    )


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
):
    lockfile = project.lockfile()
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if dev:
        categories = ["develop"]
    elif not categories:
        categories = ["default"]

    package_args = [p for p in packages] + [f"-e {pkg}" for pkg in editable_packages]

    index_name = None
    if index_url:
        index_name = add_index_to_pipfile(project, index_url)

    reqs = {}
    requested_packages = {}
    for package in package_args[:]:
        # section = project.packages if not dev else project.dev_packages
        section = {}
        package = Requirement.from_line(package)
        if index_name:
            package.index = index_name
        package_name, package_val = package.pipfile_entry
        package_name = pep423_name(package_name)
        requested_packages[package_name] = package
        try:
            if not is_star(section[package_name]) and is_star(package_val):
                # Support for VCS dependencies.
                package_val = convert_deps_to_pip(
                    {package_name: section[package_name]}, project=project
                )[0]
        except KeyError:
            pass
        reqs[package_name] = package_val

    if not reqs:
        click.echo("Nothing to upgrade!")
        sys.exit(0)

    # Resolve package to generate constraints of new package data
    upgrade_lock_data = venv_resolve_deps(
        reqs,
        which=project._which,
        project=project,
        lockfile={},
        category="default",
        pre=pre,
        allow_global=system,
        pypi_mirror=pypi_mirror,
        keep_outdated=False,
    )
    if not upgrade_lock_data:
        click.echo("Nothing to upgrade!")
        sys.exit(0)

    # Upgrade the relevant packages in the various categories specified
    for category in categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)
        if project.pipfile_exists:
            packages = project.parsed_pipfile.get(pipfile_category, {})
        else:
            packages = project.get_pipfile_section(pipfile_category)
        for package_name, requirement in requested_packages.items():
            requested_package = reqs[package_name]
            if package_name not in packages:
                packages.append(package_name, requested_package)
            else:
                packages[package_name] = requested_package
            if lock_only is False:
                project.add_package_to_pipfile(requirement, category=pipfile_category)

        full_lock_resolution = venv_resolve_deps(
            packages,
            which=project._which,
            project=project,
            lockfile={},
            category=pipfile_category,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
            keep_outdated=False,
        )
        # Mutate the existing lockfile with the upgrade data for the categories
        for package_name, _ in upgrade_lock_data.items():
            correct_package_lock = full_lock_resolution.get(package_name)
            if correct_package_lock:
                lockfile[category][package_name] = correct_package_lock

    lockfile.update({"_meta": project.get_lockfile_meta()})
    project.write_lockfile(lockfile)
