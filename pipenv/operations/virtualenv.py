# -*- coding=utf-8 -*-
import os
import shutil
import sys

from pipenv.patched import crayons
from pipenv.vendor import click, delegator

from pipenv.core import project
from pipenv.environments import PIPENV_TIMEOUT
from pipenv.utils import get_python_executable_version

from ._utils import spinner
from .where import do_where


def do_create_virtualenv(python=None, site_packages=False):
    """Creates a virtualenv."""
    click.echo(
        crayons.normal(u'Creating a virtualenv for this project...', bold=True),
        err=True,
    )
    click.echo(u'Pipfile: {0}'.format(
        crayons.red(project.pipfile_location, bold=True),
    ), err=True)
    # The user wants the virtualenv in the project.
    if project.is_venv_in_project():
        cmd = [
            sys.executable, '-m', 'virtualenv',
            project.virtualenv_location,
            '--prompt=({0})'.format(project.name),
        ]
        # Pass site-packages flag to virtualenv, if desired...
        if site_packages:
            cmd.append('--system-site-packages')
    else:
        # Default: use pew.
        cmd = [
            sys.executable,
            '-m',
            'pipenv.pew',
            'new',
            '-d',
            '-a',
            project.project_directory,
        ]
    # Default to using sys.executable, if Python wasn't provided.
    if not python:
        python = sys.executable
    click.echo(
        u'{0} {1} {3} {2}'.format(
            crayons.normal('Using', bold=True),
            crayons.red(python, bold=True),
            crayons.normal(u'to create virtualenv...', bold=True),
            crayons.green('({0})'.format(get_python_executable_version(python))),
        ),
        err=True,
    )
    cmd = cmd + ['-p', python]
    if not project.is_venv_in_project():
        cmd = cmd + ['--', project.virtualenv_name]
    # Actually create the virtualenv.
    with spinner():
        try:
            c = delegator.run(cmd, block=False, timeout=PIPENV_TIMEOUT)
        except OSError:
            click.echo(
                '{0}: it looks like {1} is not in your {2}. '
                'We cannot continue until this is resolved.'
                ''.format(
                    crayons.red('Warning', bold=True),
                    crayons.red(cmd[0]),
                    crayons.normal('PATH', bold=True),
                ),
                err=True,
            )
            sys.exit(1)
    click.echo(crayons.blue(c.out), err=True)
    # Enable site-packages, if desired...
    if not project.is_venv_in_project() and site_packages:
        click.echo(
            crayons.normal(u'Making site-packages available...', bold=True),
            err=True,
        )
        os.environ['VIRTUAL_ENV'] = project.virtualenv_location
        delegator.run('pipenv run pewtwo toggleglobalsitepackages')
        del os.environ['VIRTUAL_ENV']
    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)


def cleanup_virtualenv(bare=True):
    """Removes the virtualenv directory from the system."""
    if not bare:
        click.echo(crayons.red('Environment creation aborted.'))
    try:
        # Delete the virtualenv.
        shutil.rmtree(project.virtualenv_location)
    except OSError as e:
        click.echo(
            '{0} An error occurred while removing {1}!'.format(
                crayons.red('Error: ', bold=True),
                crayons.green(project.virtualenv_location),
            ),
            err=True,
        )
        click.echo(crayons.blue(e), err=True)
