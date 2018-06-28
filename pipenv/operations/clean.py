import sys

from pipenv.patched import crayons
from pipenv.vendor import click, delegator, requirementslib

from pipenv.core import BAD_PACKAGES, project, which_pip

from .ensure import ensure_project, ensure_lockfile


def do_clean(
    three=None, python=None, dry_run=False, bare=False, verbose=False,
):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)
    ensure_lockfile()

    installed_package_names = []
    pip_freeze_command = delegator.run('{0} freeze'.format(which_pip()))
    for line in pip_freeze_command.out.split('\n'):
        installed = line.strip()
        if not installed or installed.startswith('#'):  # Comment or empty.
            continue
        r = requirementslib.Requirement.from_line(installed).requirement
        # Ignore editable installations.
        if not r.editable:
            installed_package_names.append(r.name.lower())
        else:
            if verbose:
                click.echo('Ignoring {0}.'.format(repr(r.name)), err=True)
    # Remove known "bad packages" from the list.
    for bad_package in BAD_PACKAGES:
        if bad_package in installed_package_names:
            if verbose:
                click.echo('Ignoring {0}.'.format(repr(bad_package)), err=True)
            del installed_package_names[
                installed_package_names.index(bad_package)
            ]
    # Intelligently detect if --dev should be used or not.
    develop = [k.lower() for k in project.lockfile_content['develop'].keys()]
    default = [k.lower() for k in project.lockfile_content['default'].keys()]
    for used_package in set(develop + default):
        if used_package in installed_package_names:
            del installed_package_names[
                installed_package_names.index(used_package)
            ]
    failure = False
    for apparent_bad_package in installed_package_names:
        if dry_run:
            click.echo(apparent_bad_package)
        else:
            click.echo(
                crayons.white(
                    'Uninstalling {0}...'.format(repr(apparent_bad_package)),
                    bold=True,
                )
            )
            # Uninstall the package.
            c = delegator.run(
                '{0} uninstall {1} -y'.format(
                    which_pip(), apparent_bad_package
                )
            )
            if c.return_code != 0:
                failure = True
    sys.exit(int(failure))
