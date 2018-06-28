# -*- coding=utf-8 -*-
import json
import os
import sys

from pipenv.patched import crayons, pipfile
from pipenv.vendor import click, delegator

from pipenv import pep508checker
from pipenv.core import project, which
from pipenv.utils import escape_grouped_arguments, system_which

from ._utils import import_from_code
from .ensure import ensure_project


def do_check(three=None, python=False, system=False, unused=False, ignore=None, args=None):
    if not system:
        # Ensure that virtualenv is available.
        ensure_project(three=three, python=python, validate=False, warn=False)
    if not args:
        args = []
    if unused:
        deps_required = [k for k in project.packages.keys()]
        deps_needed = import_from_code(unused)
        for dep in deps_needed:
            try:
                deps_required.remove(dep)
            except ValueError:
                pass
        if deps_required:
            click.echo(
                crayons.normal(
                    'The following dependencies appear unused, and may be safe for removal:'
                )
            )
            for dep in deps_required:
                click.echo('  - {0}'.format(crayons.green(dep)))
            sys.exit(1)
        else:
            sys.exit(0)
    click.echo(crayons.normal(u'Checking PEP 508 requirements...', bold=True))
    if system:
        python = system_which('python')
    else:
        python = which('python')
    # Run the PEP 508 checker in the virtualenv.
    c = delegator.run(
        '"{0}" {1}'.format(
            python,
            escape_grouped_arguments(pep508checker.__file__.rstrip('cdo')),
        )
    )
    results = json.loads(c.out)
    # Load the pipfile.
    p = pipfile.Pipfile.load(project.pipfile_location)
    failed = False
    # Assert each specified requirement.
    for marker, specifier in p.data['_meta']['requires'].items():
        if marker in results:
            try:
                assert results[marker] == specifier
            except AssertionError:
                failed = True
                click.echo(
                    'Specifier {0} does not match {1} ({2}).'
                    ''.format(
                        crayons.green(marker),
                        crayons.blue(specifier),
                        crayons.red(results[marker]),
                    ),
                    err=True,
                )
    if failed:
        click.echo(crayons.red('Failed!'), err=True)
        sys.exit(1)
    else:
        click.echo(crayons.green('Passed!'))
    click.echo(
        crayons.normal(u'Checking installed package safety...', bold=True)
    )
    path = pep508checker.__file__.rstrip('cdo')
    path = os.sep.join(__file__.split(os.sep)[:-1] + ['patched', 'safety.zip'])
    if not system:
        python = which('python')
    else:
        python = system_which('python')
    if ignore:
        ignored = '--ignore {0}'.format('--ignore '.join(ignore))
        click.echo(crayons.normal('Notice: Ignoring CVE(s) {0}'.format(crayons.yellow(', '.join(ignore)))), err=True)
    else:
        ignored = ''
    c = delegator.run(
        '"{0}" {1} check --json --key=1ab8d58f-5122e025-83674263-bc1e79e0 {2}'.format(
            python, escape_grouped_arguments(path), ignored
        )
    )
    try:
        results = json.loads(c.out)
    except ValueError:
        click.echo('An error occurred:', err=True)
        click.echo(c.err, err=True)
        sys.exit(1)
    for (package, resolved, installed, description, vuln) in results:
        click.echo(
            '{0}: {1} {2} resolved ({3} installed)!'.format(
                crayons.normal(vuln, bold=True),
                crayons.green(package),
                crayons.red(resolved, bold=False),
                crayons.red(installed, bold=True),
            )
        )
        click.echo('{0}'.format(description))
        click.echo()
    if not results:
        click.echo(crayons.green('All good!'))
    else:
        sys.exit(1)
