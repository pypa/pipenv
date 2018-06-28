# -*- coding=utf-8 -*-
import shutil
import sys

from pipenv.patched import crayons
from pipenv.vendor import click, delegator, requirementslib

from pipenv.core import BAD_PACKAGES, project, which_pip
from pipenv.environments import PIPENV_USE_SYSTEM
from pipenv.utils import escape_grouped_arguments

from .ensure import ensure_project
from .lock import do_lock


def _purge(bare=False, downloads=False, allow_global=False, verbose=False):
    """Executes the purge functionality."""
    if downloads:
        if not bare:
            click.echo(
                crayons.normal(u'Clearing out downloads directory...', bold=True)
            )
        shutil.rmtree(project.download_location)
        return

    freeze = delegator.run(
        '{0} freeze'.format(
            escape_grouped_arguments(which_pip(allow_global=allow_global))
        )
    ).out
    # Remove comments from the output, if any.
    installed = [
        line
        for line in freeze.splitlines()
        if not line.lstrip().startswith('#')
    ]
    # Remove setuptools and friends from installed, if present.
    for package_name in BAD_PACKAGES:
        for i, package in enumerate(installed):
            if package.startswith(package_name):
                del installed[i]
    actually_installed = []
    for package in installed:
        try:
            dep = requirementslib.Requirement.from_line(package)
        except AssertionError:
            dep = None
        if dep and not dep.is_vcs and not dep.editable:
            dep = dep.name
            actually_installed.append(dep)
    if not bare:
        click.echo(
            u'Found {0} installed package(s), purging...'.format(
                len(actually_installed)
            )
        )
    command = '{0} uninstall {1} -y'.format(
        escape_grouped_arguments(which_pip(allow_global=allow_global)),
        ' '.join(actually_installed),
    )
    if verbose:
        click.echo('$ {0}'.format(command))
    c = delegator.run(command)
    if not bare:
        click.echo(crayons.blue(c.out))
        click.echo(crayons.green('Environment now purged and fresh!'))


def do_uninstall(
    package_name=False,
    more_packages=False,
    three=None,
    python=False,
    system=False,
    lock=False,
    all_dev=False,
    all=False,
    verbose=False,
    keep_outdated=False,
    pypi_mirror=None,
):
    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python)
    package_names = (package_name,) + more_packages
    pipfile_remove = True
    # Un-install all dependencies, if --all was provided.
    if all is True:
        click.echo(
            crayons.normal(
                u'Un-installing all packages from virtualenv...', bold=True
            )
        )
        _purge(allow_global=system, verbose=verbose)
        sys.exit(0)
    # Uninstall [dev-packages], if --dev was provided.
    if all_dev:
        if 'dev-packages' not in project.parsed_pipfile:
            click.echo(
                crayons.normal(
                    'No {0} to uninstall.'.format(
                        crayons.red('[dev-packages]')
                    ),
                    bold=True,
                )
            )
            sys.exit(0)
        click.echo(
            crayons.normal(
                u'Un-installing {0}...'.format(crayons.red('[dev-packages]')),
                bold=True,
            )
        )
        package_names = project.dev_packages.keys()
    if package_name is False and not all_dev:
        click.echo(crayons.red('No package provided!'), err=True)
        sys.exit(1)
    for package_name in package_names:
        click.echo(u'Un-installing {0}...'.format(crayons.green(package_name)))
        cmd = '{0} uninstall {1} -y'.format(
            escape_grouped_arguments(which_pip(allow_global=system)),
            package_name,
        )
        if verbose:
            click.echo('$ {0}'.format(cmd))
        c = delegator.run(cmd)
        click.echo(crayons.blue(c.out))
        if pipfile_remove:
            in_packages = project.get_package_name_in_pipfile(
                package_name, dev=False)
            in_dev_packages = project.get_package_name_in_pipfile(
                package_name, dev=True)
            if not in_dev_packages and not in_packages:
                click.echo(
                    'No package {0} to remove from Pipfile.'.format(
                        crayons.green(package_name)
                    )
                )
                continue

            click.echo(
                u'Removing {0} from Pipfile...'.format(
                    crayons.green(package_name)
                )
            )
            # Remove package from both packages and dev-packages.
            project.remove_package_from_pipfile(package_name, dev=True)
            project.remove_package_from_pipfile(package_name, dev=False)
    if lock:
        do_lock(system=system, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)
