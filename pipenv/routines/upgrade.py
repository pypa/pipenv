from pipenv.utils.dependencies import (
    convert_deps_to_pip,
    get_pipfile_category_using_lockfile_section,
    is_star,
)
from pipenv.utils.project import ensure_project
from pipenv.utils.resolver import venv_resolve_deps
from pipenv.vendor.requirementslib.models.requirements import Requirement


def do_upgrade(
    project,
    python=None,
    pre=False,
    system=False,
    packages=None,
    editable_packages=None,
    site_packages=False,
    pypi_mirror=None,
    categories=None,
    quiet=False,
):

    ensure_project(
        project,
        python=python,
        pypi_mirror=pypi_mirror,
        warn=(not quiet),
        site_packages=site_packages,
    )

    lockfile = project._lockfile()
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if not categories:
        categories = ["default"]

    package_args = [p for p in packages] + [f"-e {pkg}" for pkg in editable_packages]

    reqs = {}
    requested_packages = {}
    for package in package_args[:]:
        # section = project.packages if not dev else project.dev_packages
        section = {}
        package = Requirement.from_line(package)
        package_name, package_val = package.pipfile_entry
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
            correct_package_lock = full_lock_resolution[package_name]
            lockfile[category][package_name] = correct_package_lock

    lockfile.update({"_meta": project.get_lockfile_meta()})
    project.write_lockfile(lockfile)
