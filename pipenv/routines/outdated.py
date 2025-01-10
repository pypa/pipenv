import sys
from collections import namedtuple
from collections.abc import Mapping

from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
from pipenv.routines.lock import do_lock
from pipenv.utils.dependencies import (
    as_pipfile,
    expansive_install_req_from_line,
    get_version,
    pep423_name,
)
from pipenv.vendor import click


def do_outdated(project, pypi_mirror=None, pre=False, clear=False):
    packages = {}
    package_info = namedtuple("PackageInfo", ["name", "installed", "available"])

    installed_packages = project.environment.get_installed_packages()
    outdated_packages = {
        canonicalize_name(pkg.name): package_info(
            pkg.name, parse_version(pkg.version), pkg.latest_version
        )
        for pkg in project.environment.get_outdated_packages()
    }
    reverse_deps = {
        canonicalize_name(name): deps
        for name, deps in project.environment.reverse_dependencies().items()
    }
    for result in installed_packages:
        dep, _ = expansive_install_req_from_line(f"{result.name}=={result.version}")
        packages.update(as_pipfile(dep))

    updated_packages = {}
    lockfile = do_lock(
        project, clear=clear, pre=pre, write=False, pypi_mirror=pypi_mirror
    )
    for category in project.get_package_categories(for_lockfile=True):
        for package in lockfile.get(category, []):
            try:
                updated_packages[package] = parse_version(
                    lockfile[category][package]["version"].replace("==", "")
                )
            except KeyError:  # noqa: PERF203
                pass
    outdated = []
    skipped = []
    for package in packages.keys():  # noqa: PLC0206
        norm_name = pep423_name(package)
        if norm_name in updated_packages.keys():
            version = packages[package]
            if isinstance(version, Mapping):
                version = parse_version(version.get("version", "").replace("==", ""))
            else:
                version = parse_version(version.replace("==", ""))
            if updated_packages[norm_name] != version:
                outdated.append(
                    package_info(package, str(version), str(updated_packages[norm_name]))
                )
            elif canonicalize_name(package) in outdated_packages:
                skipped.append(outdated_packages[canonicalize_name(package)])
    for package, old_version, new_version in skipped:
        for category in project.get_package_categories():
            name_in_pipfile = project.get_package_name_in_pipfile(
                package, category=category
            )
            pipfile_section = project.get_pipfile_section(category)
            if name_in_pipfile and name_in_pipfile in pipfile_section:
                required = ""
                version = get_version(pipfile_section[name_in_pipfile])
                rdeps = reverse_deps.get(canonicalize_name(package))
                if isinstance(rdeps, Mapping) and "required" in rdeps:
                    required = " {rdeps['required']} required"
                if version:
                    pipfile_version_text = f" ({version} set in Pipfile)"
                else:
                    pipfile_version_text = " (Unpinned in Pipfile)"
                click.secho(
                    f"Skipped Update of Package {package!s}:"
                    f" {old_version!s} installed,{required!s}{pipfile_version_text!s}, "
                    f"{new_version!s} available.",
                    fg="yellow",
                    err=True,
                )
    for package, old_version, new_version in set(outdated).union(set(skipped)):
        click.echo(
            f"Package {package!r} out-of-date: {old_version!r} installed, {new_version!r} available."
        )
    if not outdated:
        click.echo(click.style("All packages are up to date!", fg="green", bold=True))
    sys.exit(bool(outdated))
