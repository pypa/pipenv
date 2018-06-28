import sys

from pipenv.patched import crayons
from pipenv.vendor import click, delegator, requirementslib

from pipenv.core import project, which
from pipenv.utils import pep423_name

from .ensure import ensure_project
from .lock import do_lock
from .sync import do_sync


def _do_outdated(pypi_mirror=None):
    packages = {}
    results = delegator.run('{0} freeze'.format(which('pip'))).out.strip(
    ).split(
        '\n'
    )
    results = filter(bool, results)
    for result in results:
        dep = requirementslib.Requirement.from_line(result)
        packages.update(dep.as_pipfile())
    updated_packages = {}
    lockfile = do_lock(write=False, pypi_mirror=pypi_mirror)
    for section in ('develop', 'default'):
        for package in lockfile[section]:
            try:
                updated_packages[package] = lockfile[section][package][
                    'version'
                ]
            except KeyError:
                pass
    outdated = []
    for package in packages:
        norm_name = pep423_name(package)
        if norm_name in updated_packages:
            if updated_packages[norm_name] != packages[package]:
                outdated.append(
                    (package, updated_packages[norm_name], packages[package])
                )
    for package, new_version, old_version in outdated:
        click.echo(
            'Package {0!r} out-of-date: {1!r} installed, '
            '{2!r} available.'.format(package, old_version, new_version),
        )
    sys.exit(bool(outdated))


def do_update(
    package, more_packages, three, python, pypi_mirror, verbose, clear,
    keep_outdated, pre, dev, bare, sequential, dry_run, outdated,
):
    ensure_project(three=three, python=python, warn=True)
    if not outdated:
        outdated = bool(dry_run)
    if outdated:
        _do_outdated(pypi_mirror=pypi_mirror)
    if not package:
        click.echo(
            '{0} {1} {2} {3}{4}'.format(
                crayons.white('Running', bold=True),
                crayons.red('$ pipenv lock', bold=True),
                crayons.white('then', bold=True),
                crayons.red('$ pipenv sync', bold=True),
                crayons.white('.', bold=True),
            )
        )
    else:
        for package in ([package] + list(more_packages)):
            if package not in project.all_packages:
                click.echo(
                    '{0}: {1} was not found in your Pipfile! Aborting.'
                    ''.format(
                        crayons.red('Warning', bold=True),
                        crayons.green(package, bold=True),
                    ),
                    err=True,
                )
                sys.exit(1)
    do_lock(
        verbose=verbose, clear=clear, pre=pre,
        keep_outdated=keep_outdated, pypi_mirror=pypi_mirror,
    )
    do_sync(
        dev=dev,
        three=three,
        python=python,
        bare=bare,
        dont_upgrade=False,
        user=False,
        verbose=verbose,
        clear=clear,
        unused=False,
        sequential=sequential,
        pypi_mirror=pypi_mirror,
    )
