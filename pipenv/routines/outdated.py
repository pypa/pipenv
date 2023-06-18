import sys
from collections import namedtuple
from collections.abc import Mapping

from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.routines.lock import do_lock
from pipenv.utils.dependencies import pep423_name
from pipenv.vendor import click
from pipenv.vendor.requirementslib.models.requirements import Requirement
from pipenv.vendor.requirementslib.models.utils import get_version


def do_outdated(project, pypi_mirror=None, pre=False, clear=False):
    packages = {}
    package_info = namedtuple("PackageInfo", ["name", "installed", "available"])

    installed_packages = project.environment.get_installed_packages()
    outdated_packages = {
        canonicalize_name(pkg.project_name): package_info(
            pkg.project_name, pkg.parsed_version, pkg.latest_version
        )
        for pkg in project.environment.get_outdated_packages()
    }
    reverse_deps = {
        canonicalize_name(name): deps
        for name, deps in project.environment.reverse_dependencies().items()
    }
    for result in installed_packages:
        dep = Requirement.from_line(str(result.as_requirement()))
        packages.update(dep.as_pipfile())
    updated_packages = {}
    lockfile = do_lock(
        project, clear=clear, pre=pre, write=False, pypi_mirror=pypi_mirror
    )
    for category in project.get_package_categories(for_lockfile=True):
        for package in lockfile.get(category, []):
            try:
                updated_packages[package] = lockfile[category][package]["version"]
            except KeyError:
                pass
    outdated = []
    skipped = []
    for package in packages:
        norm_name = pep423_name(package)
        if norm_name in updated_packages:
            version = packages[package]
            if isinstance(version, Mapping):
                version = version.get("version")
            if updated_packages[norm_name] != version:
                outdated.append(
                    package_info(package, updated_packages[norm_name], packages[package])
                )
            elif canonicalize_name(package) in outdated_packages:
                skipped.append(outdated_packages[canonicalize_name(package)])
    for package, old_version, new_version in skipped:
        for category in project.get_package_categories():
            name_in_pipfile = project.get_package_name_in_pipfile(
                package, category=category
            )
            if name_in_pipfile:
                required = ""
                version = get_version(
                    project.get_pipfile_section(category)[name_in_pipfile]
                )
                rdeps = reverse_deps.get(canonicalize_name(package))
                if isinstance(rdeps, Mapping) and "required" in rdeps:
                    required = " {} required".format(rdeps["required"])
                if version:
                    pipfile_version_text = f" ({version} set in Pipfile)"
                else:
                    pipfile_version_text = " (Unpinned in Pipfile)"
                click.secho(
                    "Skipped Update of Package {!s}: {!s} installed,{!s}{!s}, "
                    "{!s} available.".format(
                        package, old_version, required, pipfile_version_text, new_version
                    ),
                    fg="yellow",
                    err=True,
                )
    if not outdated:
        click.echo(click.style("All packages are up to date!", fg="green", bold=True))
        sys.exit(0)
    for package, new_version, old_version in outdated:
        click.echo(
            "Package {!r} out-of-date: {!r} installed, {!r} available.".format(
                package, old_version, new_version
            )
        )
    sys.exit(bool(outdated))
