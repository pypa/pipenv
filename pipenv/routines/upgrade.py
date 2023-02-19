from pipenv.vendor import click

from pipenv.utils.dependencies import (
    get_lockfile_section_using_pipfile_category,
    get_pipfile_category_using_lockfile_section,
    is_pinned,
)
from pipenv.vendor.requirementslib.models.requirements import Requirement
from pipenv.utils.dependencies import convert_deps_to_pip, is_star
from pipenv.utils.resolver import venv_resolve_deps
from pipenv.routines.lock import overwrite_with_default


def do_upgrade(
    project,
    pre=False,
    system=False,
    packages=None,
    editable_packages=None,
    site_packages=False,
    extra_pip_args=None,
    categories=None,
    write=True,
    pypi_mirror=None,
):
    lockfile = project._lockfile()
    upgrade_lockfile = {}
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if not categories:
        categories = ["default"]

    package_args = [p for p in packages] + [f"-e {pkg}" for pkg in editable_packages]


    reqs = {}
    requested_packages = []
    for i, package in enumerate(package_args[:]):
        #section = project.packages if not dev else project.dev_packages
        section = {}
        package = Requirement.from_line(package)
        package_name, package_val = package.pipfile_entry
        requested_packages.append(package_name)
        try:
            if not is_star(section[package_name]) and is_star(package_val):
                # Support for VCS dependencies.
                package_val = convert_deps_to_pip(
                    {package_name: section[package_name]}, project=project
                )[0]
        except KeyError:
            pass
        reqs[package_name] = package_val

    # Resolve package to generate constraints of new package data
    upgrade_lock_data = venv_resolve_deps(
        reqs,
        which=project._which,
        project=project,
        category="default",
        pre=pre,
        allow_global=system,
        pypi_mirror=pypi_mirror,
        keep_outdated=False,
    )

    #
    for category in categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)
        if project.pipfile_exists:
            packages = project.parsed_pipfile.get(pipfile_category, {})
        else:
            packages = project.get_pipfile_section(pipfile_category)
        for package_name in requested_packages:
            requested_package = reqs[package_name]
            packages.append(package_name, requested_package)

        full_lock_resolution = venv_resolve_deps(
            packages,
            which=project._which,
            project=project,
            category=pipfile_category,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
            pipfile=packages,
            keep_outdated=False,
        )
        # Mutate the existing lockfile with the upgrade data for the categories
        for package_name, _ in upgrade_lock_data.items():
            correct_package_lock = full_lock_resolution[package_name]
            lockfile[category][package_name] = correct_package_lock

    # Overwrite any category packages with default packages.
    lockfile_categories = project.get_package_categories(for_lockfile=True)
    for category in lockfile_categories:
        if category == "default":
            pass
        if lockfile.get(category):
            lockfile[category].update(
                overwrite_with_default(lockfile.get("default", {}), lockfile[category])
            )

    lockfile.update({"_meta": project.get_lockfile_meta()})
    project.write_lockfile(lockfile)

