# -*- coding: utf-8 -*-

import os

import blindspin
import click
import crayons
import delegator

from pip._vendor.packaging.version import parse as parse_version
from pipenv.environments import PIPENV_INSTALL_TIMEOUT, PYENV_ROOT

from .base import match_version


def find_python(version):
    versions_dir = os.path.join(PYENV_ROOT, 'versions')
    if os.path.isdir(versions_dir):
        versions = (
            v for v in (parse_version(n) for n in os.listdir(versions_dir))
            if match_version(version, v)
        )
    else:
        click.echo(
            '{0}: PYENV_ROOT is not set. New Python paths will '
            'probably not be exported properly after installation.'
            ''.format(crayons.red('Warning', bold=True)),
            err=True,
        )
        versions = []
    try:
        best = max(versions)
    except ValueError:
        pass
    else:
        return os.path.join(versions_dir, best.base_version, 'bin', 'python')


def install_python(name, user_confirm):
    version_map = {
        # TODO: Keep this up to date!
        # These versions appear incompatible with pew:
        # '2.5': '2.5.6',
        '2.6': '2.6.9',
        '2.7': '2.7.14',
        # '3.1': '3.1.5',
        # '3.2': '3.2.6',
        '3.3': '3.3.7',
        '3.4': '3.4.7',
        '3.5': '3.5.4',
        '3.6': '3.6.4',
    }
    try:
        if len(name.split('.')) == 2:
            # Find the latest version of Python available.
            version = version_map[name]
        else:
            version = name
    except KeyError:
        return False

    # Prompt the user to continue...
    ok = user_confirm('{0} {1} {2}'.format(
        'Would you like us to install',
        crayons.green('CPython {0}'.format(version)),
        'with pyenv?',
    ))
    if not ok:
        return False

    # Tell the user we're installing Python.
    click.echo(
        u'{0} {1} {2} {3}{4}'.format(
            crayons.normal(u'Installing', bold=True),
            crayons.green(u'CPython {0}'.format(version), bold=True),
            crayons.normal(u'with pyenv', bold=True),
            crayons.normal(u'(this may take a few minutes)'),
            crayons.normal(u'…', bold=True)
        )
    )

    with blindspin.spinner():
        # Install Python.
        c = delegator.run(
            'pyenv install {0} -s'.format(version),
            timeout=PIPENV_INSTALL_TIMEOUT,
            block=False
        )

        # Wait until the process has finished...
        c.block()

        if c.return_code != 0:
            click.echo(u'Something went wrong…')
            click.echo(crayons.blue(c.err), err=True)
            return False

        # Print the results, in a beautiful blue...
        click.echo(crayons.blue(c.out), err=True)

    return True
