import os
import sys

from pipenv.patched import crayons
from pipenv.vendor import click, delegator

from pipenv.core import which

from .ensure import ensure_project


def do_open(module, three, python):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)
    c = delegator.run(
        '{0} -c "import {1}; print({1}.__file__);"'.format(
            which('python'), module
        )
    )
    try:
        assert c.return_code == 0
    except AssertionError:
        click.echo(crayons.red('Module not found!'))
        sys.exit(1)
    if '__init__.py' in c.out:
        p = os.path.dirname(c.out.strip().rstrip('cdo'))
    else:
        p = c.out.strip().rstrip('cdo')
    click.echo(
        crayons.normal('Opening {0!r} in your EDITOR.'.format(p), bold=True)
    )
    click.edit(filename=p)
