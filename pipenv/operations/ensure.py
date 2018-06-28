# -*- coding=utf-8 -*-
import os
import sys

from pipenv.patched import crayons
from pipenv.vendor import click

from pipenv.core import (
    BAD_PACKAGES,
    USING_DEFAULT_PYTHON,
    project,
    set_using_default_python,
    which,
)
from pipenv.environments import (
    PIPENV_SKIP_VALIDATION,
    PIPENV_USE_SYSTEM,
    PIPENV_VIRTUALENV,
    PIPENV_YES,
)
from pipenv.utils import get_python_executable_version

from ._utils import spinner
from .ensure_python import ensure_python
from .virtualenv import cleanup_virtualenv, do_create_virtualenv
from .where import shorten_path


def _ensure_environment():
    # Skip this on Windows...
    if os.name != 'nt':
        if 'LANG' not in os.environ:
            click.echo(
                '{0}: the environment variable {1} is not set!'
                '\nWe recommend setting this in {2} (or equivalent) for '
                'proper expected behavior.'.format(
                    crayons.red('Warning', bold=True),
                    crayons.normal('LANG', bold=True),
                    crayons.green('~/.profile'),
                ),
                err=True,
            )


def ensure_virtualenv(three=None, python=None, site_packages=False):
    """Creates a virtualenv, if one doesn't exist."""

    def abort():
        sys.exit(1)

    if not project.virtualenv_exists:
        try:
            # Ensure environment variables are set properly.
            _ensure_environment()
            # Ensure Python is available.
            python = ensure_python(three=three, python=python)
            # Create the virtualenv.
            # Abort if --system (or running in a virtualenv).
            if PIPENV_USE_SYSTEM:
                click.echo(
                    crayons.red(
                        'You are attempting to re-create a virtualenv that '
                        'Pipenv did not create. Aborting.'
                    )
                )
                sys.exit(1)
            do_create_virtualenv(python=python, site_packages=site_packages)
        except KeyboardInterrupt:
            # If interrupted, cleanup the virtualenv.
            cleanup_virtualenv(bare=False)
            sys.exit(1)
    # If --three, --two, or --python were passed...
    elif (python) or (three is not None) or (site_packages is not False):
        set_using_default_python(False)
        # Ensure python is installed before deleting existing virtual env
        ensure_python(three=three, python=python)
        click.echo(crayons.red('Virtualenv already exists!'), err=True)
        # If VIRTUAL_ENV is set, there is a possibility that we are
        # going to remove the active virtualenv that the user cares
        # about, so confirm first.
        if 'VIRTUAL_ENV' in os.environ:
            if not (
                PIPENV_YES or
                click.confirm('Remove existing virtualenv?', default=True)
            ):
                abort()
        click.echo(
            crayons.normal(u'Removing existing virtualenv...', bold=True),
            err=True,
        )
        # Remove the virtualenv.
        cleanup_virtualenv(bare=True)
        # Call this function again.
        ensure_virtualenv(
            three=three, python=python, site_packages=site_packages
        )


def import_requirements(r=None, dev=False):
    from .patched.notpip._vendor import requests as pip_requests
    from .patched.notpip._internal.req.req_file import parse_requirements

    # Parse requirements.txt file with Pip's parser.
    # Pip requires a `PipSession` which is a subclass of requests.Session.
    # Since we're not making any network calls, it's initialized to nothing.
    if r:
        assert os.path.isfile(r)
    # Default path, if none is provided.
    if r is None:
        r = project.requirements_location
    with open(r, 'r') as f:
        contents = f.read()
    indexes = []
    # Find and add extra indexes.
    for line in contents.split('\n'):
        if line.startswith(('-i ', '--index ', '--index-url ')):
            indexes.append(line.split()[1])
    reqs = [f for f in parse_requirements(r, session=pip_requests)]
    for package in reqs:
        if package.name not in BAD_PACKAGES:
            if package.link is not None:
                package_string = (
                    '-e {0}'.format(package.link) if package.editable else str(
                        package.link
                    )
                )
                project.add_package_to_pipfile(package_string, dev=dev)
            else:
                project.add_package_to_pipfile(str(package.req), dev=dev)
    for index in indexes:
        project.add_index_to_pipfile(index)
    project.recase_pipfile()


def ensure_pipfile(validate=True, skip_requirements=False, system=False):
    """Creates a Pipfile for the project, if it doesn't exist."""
    # Assert Pipfile exists.
    python = which('python') if not (USING_DEFAULT_PYTHON or system) else None
    if project.pipfile_is_empty:
        # Show an error message and exit if system is passed and no pipfile exists
        if system and not PIPENV_VIRTUALENV:
            click.echo(
                '{0}: --system is intended to be used for pre-existing Pipfile '
                'installation, not installation of specific packages. Aborting.'.format(
                    crayons.red('Warning', bold=True)
                ),
                err=True,
            )
            sys.exit(1)
        # If there's a requirements file, but no Pipfile...
        if project.requirements_exists and not skip_requirements:
            click.echo(
                crayons.normal(
                    u'requirements.txt found, instead of Pipfile! Converting...',
                    bold=True,
                )
            )
            # Create a Pipfile...
            project.create_pipfile(python=python)
            with spinner():
                # Import requirements.txt.
                import_requirements()
            # Warn the user of side-effects.
            click.echo(
                u'{0}: Your {1} now contains pinned versions, if your {2} did. \n'
                'We recommend updating your {1} to specify the {3} version, instead.'
                ''.format(
                    crayons.red('Warning', bold=True),
                    crayons.normal('Pipfile', bold=True),
                    crayons.normal('requirements.txt', bold=True),
                    crayons.normal('"*"', bold=True),
                )
            )
        else:
            click.echo(
                crayons.normal(
                    u'Creating a Pipfile for this project...', bold=True
                ),
                err=True,
            )
            # Create the pipfile if it doesn't exist.
            project.create_pipfile(python=python)
    # Validate the Pipfile's contents.
    if validate and project.virtualenv_exists and not PIPENV_SKIP_VALIDATION:
        # Ensure that Pipfile is using proper casing.
        p = project.parsed_pipfile
        changed = project.ensure_proper_casing()
        # Write changes out to disk.
        if changed:
            click.echo(
                crayons.normal(u'Fixing package names in Pipfile...', bold=True),
                err=True,
            )
            project.write_toml(p)


def ensure_project(
    three=None,
    python=None,
    validate=True,
    system=False,
    warn=True,
    site_packages=False,
    deploy=False,
    skip_requirements=False,
):
    """Ensures both Pipfile and virtualenv exist for the project."""
    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    if not project.pipfile_exists and not deploy:
        project.touch_pipfile()
    # Skip virtualenv creation when --system was used.
    if not system:
        ensure_virtualenv(
            three=three, python=python, site_packages=site_packages
        )
        if warn:
            # Warn users if they are using the wrong version of Python.
            if project.required_python_version:
                path_to_python = which('python') or which('py')
                if path_to_python and project.required_python_version not in (
                    get_python_executable_version(path_to_python) or ''
                ):
                    click.echo(
                        '{0}: Your Pipfile requires {1} {2}, '
                        'but you are using {3} ({4}).'.format(
                            crayons.red('Warning', bold=True),
                            crayons.normal('python_version', bold=True),
                            crayons.blue(project.required_python_version),
                            crayons.blue(get_python_executable_version(path_to_python)),
                            crayons.green(shorten_path(path_to_python)),
                        ),
                        err=True,
                    )
                    if not deploy:
                        click.echo(
                            '  {0} will surely fail.'
                            ''.format(crayons.red('$ pipenv check')),
                            err=True,
                        )
                    else:
                        click.echo(crayons.red('Deploy aborted.'), err=True)
                        sys.exit(1)
    # Ensure the Pipfile exists.
    ensure_pipfile(validate=validate, skip_requirements=skip_requirements, system=system)


def ensure_lockfile(keep_outdated=False, pypi_mirror=None):
    """Ensures that the lockfile is up-to-date."""
    if not keep_outdated:
        keep_outdated = project.settings.get('keep_outdated')
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if project.lockfile_exists:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash == old_hash:
            return
        click.echo(
            crayons.red(
                u'Pipfile.lock ({0}) out of date, updating to ({1})...'.format(
                    old_hash[-6:], new_hash[-6:]
                ),
                bold=True,
            ),
            err=True,
        )
    from .lock import do_lock
    do_lock(keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)
