import sys

from pipenv._compat import TemporaryDirectory
from pipenv.core import project
from pipenv.patched import crayons
from pipenv.vendor import click

from .ensure import ensure_project
from .init import do_init


def do_sync(
    dev=False,
    three=None,
    python=None,
    bare=False,
    dont_upgrade=False,
    user=False,
    verbose=False,
    clear=False,
    unused=False,
    sequential=False,
    pypi_mirror=None,
    system=False,
    deploy=False,
):
    # The lock file needs to exist because sync won't write to it.
    if not project.lockfile_exists:
        click.echo(
            '{0}: Pipfile.lock is missing! You need to run {1} first.'.format(
                crayons.red('Error', bold=True),
                crayons.red('$ pipenv lock', bold=True),
            ),
            err=True,
        )
        sys.exit(1)

    # Ensure that virtualenv is available if not system.
    ensure_project(three=three, python=python, validate=False, deploy=deploy)

    # Install everything.
    requirements_dir = TemporaryDirectory(
        suffix='-requirements', prefix='pipenv-'
    )
    do_init(
        dev=dev,
        verbose=verbose,
        concurrent=(not sequential),
        requirements_dir=requirements_dir,
        ignore_pipfile=True,    # Don't check if Pipfile and lock match.
        pypi_mirror=pypi_mirror,
        deploy=deploy,
        system=system,
    )
    requirements_dir.cleanup()
    click.echo(crayons.green('All dependencies are now up-to-date!'))
