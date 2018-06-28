# -*- coding=utf-8 -*-
import glob
import os
import sys

from pipenv.patched import crayons
from pipenv.vendor import click, delegator

from pipenv.core import project, set_using_default_python
from pipenv.environments import (
    PIPENV_DEFAULT_PYTHON_VERSION,
    PIPENV_DONT_USE_PYENV,
    PIPENV_INSTALL_TIMEOUT,
    PIPENV_PYTHON,
    PIPENV_YES,
    PYENV_INSTALLED,
    PYENV_ROOT,
    SESSION_IS_INTERACTIVE,
)
from pipenv.pythonfinder import find_a_system_python
from pipenv.utils import get_python_executable_version

from ._utils import spinner


def _add_to_path(p):
    """Adds a given path to the PATH."""
    if p not in os.environ['PATH']:
        os.environ['PATH'] = '{0}{1}{2}'.format(
            p, os.pathsep, os.environ['PATH']
        )


def _convert_three_to_python(three, python):
    """Converts a Three flag into a Python flag, and raises customer warnings
    in the process, if needed.
    """
    if not python:
        if three is False:
            return '2'

        elif three is True:
            return '3'
    else:
        return python


def ensure_python(three=None, python=None):
    # Support for the PIPENV_PYTHON environment variable.
    if PIPENV_PYTHON and python is False and three is None:
        python = PIPENV_PYTHON

    def abort():
        click.echo(
            'You can specify specific versions of Python with:\n  {0}'.format(
                crayons.red(
                    '$ pipenv --python {0}'.format(
                        os.sep.join(('path', 'to', 'python'))
                    )
                )
            ),
            err=True,
        )
        sys.exit(1)

    def activate_pyenv():
        from notpip._vendor.packaging.version import parse as parse_version

        """Adds all pyenv installations to the PATH."""
        if PYENV_INSTALLED:
            if PYENV_ROOT:
                pyenv_paths = {}
                for found in glob.glob(
                    '{0}{1}versions{1}*'.format(PYENV_ROOT, os.sep)
                ):
                    pyenv_paths[os.path.split(found)[1]] = '{0}{1}bin'.format(
                        found, os.sep
                    )
                for version_str, pyenv_path in pyenv_paths.items():
                    version = parse_version(version_str)
                    if version.is_prerelease and pyenv_paths.get(
                        version.base_version
                    ):
                        continue

                    _add_to_path(pyenv_path)
            else:
                click.echo(
                    '{0}: PYENV_ROOT is not set. New python paths will '
                    'probably not be exported properly after installation.'
                    ''.format(crayons.red('Warning', bold=True),),
                    err=True,
                )

    # Add pyenv paths to PATH.
    activate_pyenv()
    path_to_python = None
    set_using_default_python(three is None and not python)
    # Find out which python is desired.
    if not python:
        python = _convert_three_to_python(three, python)
    if not python:
        python = project.required_python_version
    if not python:
        python = PIPENV_DEFAULT_PYTHON_VERSION
    if python:
        path_to_python = find_a_system_python(python)
    if not path_to_python and python is not None:
        # We need to install Python.
        click.echo(
            u'{0}: Python {1} {2}'.format(
                crayons.red('Warning', bold=True),
                crayons.blue(python),
                u'was not found on your system...',
            ),
            err=True,
        )
        # Pyenv is installed
        if not PYENV_INSTALLED:
            abort()
        else:
            if (not PIPENV_DONT_USE_PYENV) and (SESSION_IS_INTERACTIVE or PIPENV_YES):
                version_map = {
                    # TODO: Keep this up to date!
                    # These versions appear incompatible with pew:
                    # '2.5': '2.5.6',
                    '2.6': '2.6.9',
                    '2.7': '2.7.15',
                    # '3.1': '3.1.5',
                    # '3.2': '3.2.6',
                    '3.3': '3.3.7',
                    '3.4': '3.4.8',
                    '3.5': '3.5.5',
                    '3.6': '3.6.5',
                }
                try:
                    if len(python.split('.')) == 2:
                        # Find the latest version of Python available.
                        version = version_map[python]
                    else:
                        version = python
                except KeyError:
                    abort()
                s = (
                    '{0} {1} {2}'.format(
                        'Would you like us to install',
                        crayons.green('CPython {0}'.format(version)),
                        'with pyenv?',
                    )
                )
                # Prompt the user to continue...
                if not (PIPENV_YES or click.confirm(s, default=True)):
                    abort()
                else:
                    # Tell the user we're installing Python.
                    click.echo(
                        u'{0} {1} {2} {3}{4}'.format(
                            crayons.normal(u'Installing', bold=True),
                            crayons.green(
                                u'CPython {0}'.format(version), bold=True
                            ),
                            crayons.normal(u'with pyenv', bold=True),
                            crayons.normal(u'(this may take a few minutes)'),
                            crayons.normal(u'...', bold=True),
                        )
                    )
                    with spinner():
                        # Install Python.
                        c = delegator.run(
                            'pyenv install {0} -s'.format(version),
                            timeout=PIPENV_INSTALL_TIMEOUT,
                            block=False,
                        )
                        # Wait until the process has finished...
                        c.block()
                        try:
                            assert c.return_code == 0
                        except AssertionError:
                            click.echo(u'Something went wrong...')
                            click.echo(crayons.blue(c.err), err=True)
                        # Print the results, in a beautiful blue...
                        click.echo(crayons.blue(c.out), err=True)
                    # Add new paths to PATH.
                    activate_pyenv()
                    # Find the newly installed Python, hopefully.
                    path_to_python = find_a_system_python(version)
                    try:
                        assert get_python_executable_version(path_to_python) == version
                    except AssertionError:
                        click.echo(
                            '{0}: The Python you just installed is not available on your {1}, apparently.'
                            ''.format(
                                crayons.red('Warning', bold=True),
                                crayons.normal('PATH', bold=True),
                            ),
                            err=True,
                        )
                        sys.exit(1)
    return path_to_python
