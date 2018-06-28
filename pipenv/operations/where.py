# -*- coding=utf-8 -*-
import os

from pipenv.patched import crayons
from pipenv.vendor import click

from pipenv.core import project


def shorten_path(location, bold=False):
    """Returns a visually shorter representation of a given system path."""
    original = location
    short = os.sep.join([
        s[0] if len(s) > (len('2long4')) else s
        for s in location.split(os.sep)
    ])
    short = short.split(os.sep)
    short[-1] = original.split(os.sep)[-1]
    if bold:
        short[-1] = str(crayons.normal(short[-1], bold=True))
    return os.sep.join(short)


def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""
    if not virtualenv:
        location = project.pipfile_location
        # Shorten the virtual display of the path to the virtualenv.
        if not bare:
            location = shorten_path(location)
        if not location:
            click.echo(
                'No Pipfile present at project home. Consider running '
                '{0} first to automatically generate a Pipfile for you.'
                ''.format(crayons.green('`pipenv install`')),
                err=True,
            )
        elif not bare:
            click.echo(
                'Pipfile found at {0}.\n  Considering this to be the project home.'
                ''.format(crayons.green(location)),
                err=True,
            )
            pass
        else:
            click.echo(project.project_directory)
    else:
        location = project.virtualenv_location
        if not bare:
            click.echo(
                'Virtualenv location: {0}'.format(crayons.green(location)),
                err=True,
            )
        else:
            click.echo(location)
