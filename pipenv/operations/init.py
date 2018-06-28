# -*- coding=utf-8 -*-
import os
import sys

from pipenv.patched import crayons
from pipenv.vendor import click

from pipenv._compat import TemporaryDirectory
from pipenv.core import project

from ._install import do_install_dependencies
from .ensure import ensure_pipfile
from .lock import do_lock
from .virtualenv import cleanup_virtualenv, do_create_virtualenv


def do_init(
    dev=False,
    requirements=False,
    allow_global=False,
    ignore_pipfile=False,
    skip_lock=False,
    verbose=False,
    system=False,
    concurrent=True,
    deploy=False,
    pre=False,
    keep_outdated=False,
    requirements_dir=None,
    pypi_mirror=None,
):
    """Executes the init functionality."""
    cleanup_reqdir = False
    global PIPENV_VIRTUALENV
    if not system:
        if not project.virtualenv_exists:
            try:
                do_create_virtualenv()
            except KeyboardInterrupt:
                cleanup_virtualenv(bare=False)
                sys.exit(1)
    # Ensure the Pipfile exists.
    if not deploy:
        ensure_pipfile(system=system)
    if not requirements_dir:
        cleanup_reqdir = True
        requirements_dir = TemporaryDirectory(
            suffix='-requirements', prefix='pipenv-'
        )
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if (project.lockfile_exists and not ignore_pipfile) and not skip_lock:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            if deploy:
                click.echo(
                    crayons.red(
                        'Your Pipfile.lock ({0}) is out of date. Expected: ({1}).'.format(
                            old_hash[-6:], new_hash[-6:]
                        )
                    )
                )
                click.echo(
                    crayons.normal('Aborting deploy.', bold=True), err=True
                )
                requirements_dir.cleanup()
                sys.exit(1)
            elif (system or allow_global) and not (PIPENV_VIRTUALENV):
                click.echo(
                    crayons.red(
                        u'Pipfile.lock ({0}) out of date, but installation '
                        u'uses {1}... re-building lockfile must happen in '
                        u'isolation. Please rebuild lockfile in a virtualenv. '
                        u'Continuing anyway...'.format(
                            crayons.white(old_hash[-6:]),
                            crayons.white('--system')
                        ),
                        bold=True,
                    ),
                    err=True,
                )
            else:
                click.echo(
                    crayons.red(
                        u'Pipfile.lock ({0}) out of date, updating to ({1})...'.format(
                            old_hash[-6:], new_hash[-6:]
                        ),
                        bold=True,
                    ),
                    err=True,
                )
                do_lock(system=system, pre=pre, keep_outdated=keep_outdated, write=True, pypi_mirror=pypi_mirror)
    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists and not skip_lock:
        # Unless we're in a virtualenv not managed by pipenv, abort if we're
        # using the system's python.
        if (system or allow_global) and not (PIPENV_VIRTUALENV):
            click.echo(
                '{0}: --system is intended to be used for Pipfile installation, '
                'not installation of specific packages. Aborting.'.format(
                    crayons.red('Warning', bold=True)
                ),
                err=True,
            )
            click.echo('See also: --deploy flag.', err=True)
            requirements_dir.cleanup()
            sys.exit(1)
        else:
            click.echo(
                crayons.normal(u'Pipfile.lock not found, creating...', bold=True),
                err=True,
            )
            do_lock(
                system=system,
                pre=pre,
                keep_outdated=keep_outdated,
                verbose=verbose,
                write=True,
                pypi_mirror=pypi_mirror,
            )
    do_install_dependencies(
        dev=dev,
        requirements=requirements,
        allow_global=allow_global,
        skip_lock=skip_lock,
        verbose=verbose,
        concurrent=concurrent,
        requirements_dir=requirements_dir.name,
        pypi_mirror=pypi_mirror,
    )
    if cleanup_reqdir:
        requirements_dir.cleanup()

    # Hint the user what to do to activate the virtualenv.
    if not allow_global and not deploy and 'PIPENV_ACTIVE' not in os.environ:
        click.echo(
            "To activate this project's virtualenv, run {0}.\n"
            "Alternativaly, run a command "
            "inside the virtualenv with {1}.".format(
                crayons.red('pipenv shell'),
                crayons.red('pipenv run'),
            )
        )
