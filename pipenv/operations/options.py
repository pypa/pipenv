# -*- coding=utf-8 -*-
"""Various utilities for "pipenv --XXXX".

Global imports should be kept at a minimum to reduce start up time as much
as possible.
"""
import os
import sys

from pipenv.patched import crayons
from pipenv.vendor import click


def do_completion():
    from pipenv import shells
    from pipenv.vendor import click_completion
    try:
        shell = shells.detect_info()[0]
    except shells.ShellDetectionFailure:
        click.echo(
            'Fail to detect shell. Please provide the {0} environment '
            'variable.'.format(crayons.normal('PIPENV_SHELL', bold=True)),
            err=True,
        )
        sys.exit(1)
    print(click_completion.get_code(shell=shell, prog_name='pipenv'))


def do_man():
    from pipenv.utils import system_which
    man = system_which('man')
    if man:
        path = os.path.join(os.path.dirname(__file__), 'pipenv.1')
        os.execle(man, 'man', path, os.environ)
        return  # Shouldn't reach here.
    click.echo(
        'man does not appear to be available on your system.',
        err=True,
    )
    click.get_current_context().exit(1)


def do_envs():
    from pipenv import environments
    click.echo(
        'The following environment variables can be set, '
        'to do various things:\n',
    )
    for key in environments.__dict__:
        if key.startswith('PIPENV'):
            click.echo('  - {0}'.format(crayons.normal(key, bold=True)))
    click.echo('\nYou can learn more at:\n   {0}'.format(
        crayons.green(
            'https://docs.pipenv.org/advanced/'
            '#configuration-with-environment-variables'
        )),
    )


def warn_in_virtualenv():
    # Only warn if pipenv isn't already active.
    from pipenv.environments import PIPENV_USE_SYSTEM
    if not PIPENV_USE_SYSTEM or 'PIPENV_ACTIVE' in os.environ:
        return
    from pipenv.patched import crayons
    from pipenv.vendor import click
    click.echo(
        '{0}: Pipenv found itself running within a virtual environment, '
        'so it will automatically use that environment, instead of '
        'creating its own for any project. You can set '
        '{1} to force pipenv to ignore that environment and create '
        'its own instead.'.format(
            crayons.green('Courtesy Notice'),
            crayons.normal('PIPENV_IGNORE_VIRTUALENVS=1', bold=True),
        ),
        err=True,
    )


def do_py(system=False):
    from pipenv.core import which
    from pipenv.environments import PIPENV_USE_SYSTEM
    if PIPENV_USE_SYSTEM:
        system = True
    try:
        click.echo(which('python', allow_global=system))
        click.get_current_context().exit(0)
    except AttributeError:
        click.echo(crayons.red('No project found!'))
        click.get_current_context().exit(1)


def do_venv():
    # There is no virtualenv yet.
    from pipenv.project import Project
    project = Project()
    if not project.virtualenv_exists:
        click.echo(
            crayons.red(
                'No virtualenv has been created for this project yet!'
            ),
            err=True,
        )
        click.get_current_context().exit(1)
    click.echo(project.virtualenv_location)


def do_rm():
    # Abort if --system (or running in a virtualenv).
    from pipenv.environments import PIPENV_USE_SYSTEM
    if PIPENV_USE_SYSTEM:
        click.echo(
            crayons.red(
                'You are attempting to remove a virtualenv that '
                'Pipenv did not create. Aborting.'
            )
        )
        click.get_current_context().exit(1)

    from pipenv.project import Project
    project = Project()
    if not project.virtualenv_exists:
        click.echo(crayons.red(
            'No virtualenv has been created for this project yet!',
            bold=True,
        ), err=True)
        click.get_current_context().exit(1)

    click.echo(
        crayons.normal(
            u'{0} ({1})...'.format(
                crayons.normal('Removing virtualenv', bold=True),
                crayons.green(project.virtualenv_location),
            )
        )
    )

    # Remove the virtualenv.
    from ._utils import spinner
    with spinner():
        from .virtualenv import cleanup_virtualenv
        cleanup_virtualenv(bare=True)
    click.get_current_context().exit(0)
