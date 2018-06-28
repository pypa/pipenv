import os
import signal
import sys

from pipenv.patched import crayons, pew
from pipenv.vendor import click, pexpect

from pipenv.core import project
from pipenv.environments import (
    PIPENV_SHELL,
    PIPENV_SHELL_FANCY,
)
from pipenv.utils import temp_environ

from ._utils import load_dot_env
from .ensure import ensure_project

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from .vendor.backports.shutil_get_terminal_size import get_terminal_size
else:
    from shutil import get_terminal_size


def _activate_virtualenv(source=True):
    """Returns the string to activate a virtualenv."""
    # Suffix and source command for other shells.
    suffix = ''
    command = ' .' if source else ''
    # Support for fish shell.
    if PIPENV_SHELL and 'fish' in PIPENV_SHELL:
        suffix = '.fish'
        command = 'source'
    # Support for csh shell.
    if PIPENV_SHELL and 'csh' in PIPENV_SHELL:
        suffix = '.csh'
        command = 'source'
    # Escape any spaces located within the virtualenv path to allow
    # for proper activation.
    venv_location = project.virtualenv_location.replace(' ', r'\ ')
    if source:
        return '{2} {0}/bin/activate{1}'.format(venv_location, suffix, command)
    else:
        return '{0}/bin/activate'.format(venv_location)


def do_shell(three=None, python=False, fancy=False, shell_args=None):
    # Load .env file.
    load_dot_env()
    # Use fancy mode for Windows.
    if os.name == 'nt':
        fancy = True

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)
    # Set an environment variable, so we know we're in the environment.
    os.environ['PIPENV_ACTIVE'] = '1'
    compat = (not fancy)
    # Support shell compatibility mode.
    if PIPENV_SHELL_FANCY:
        compat = False
    # Compatibility mode:
    if compat:
        if PIPENV_SHELL:
            shell = os.path.abspath(PIPENV_SHELL)
        else:
            click.echo(
                crayons.red(
                    'Please ensure that the {0} environment variable '
                    'is set before activating shell.'.format(
                        crayons.normal('SHELL', bold=True)
                    )
                ),
                err=True,
            )
            sys.exit(1)
        click.echo(
            crayons.normal(
                'Spawning environment shell ({0}). Use {1} to leave.'.format(
                    crayons.red(shell), crayons.normal("'exit'", bold=True)
                ),
                bold=True,
            ),
            err=True,
        )
        cmd = "{0} -i'".format(shell)
        args = []
    # Standard (properly configured shell) mode:
    else:
        if project.is_venv_in_project():
            # use .venv as the target virtualenv name
            workon_name = '.venv'
        else:
            workon_name = project.virtualenv_name
        cmd = sys.executable
        args = ['-m', 'pipenv.pew', 'workon', workon_name]
    # Grab current terminal dimensions to replace the hardcoded default
    # dimensions of pexpect
    terminal_dimensions = get_terminal_size()
    try:
        with temp_environ():
            if project.is_venv_in_project():
                os.environ['WORKON_HOME'] = project.project_directory
            c = pexpect.spawn(
                cmd,
                args,
                dimensions=(
                    terminal_dimensions.lines, terminal_dimensions.columns
                ),
            )
    # Windows!
    except AttributeError:
        # import subprocess
        # Tell pew to use the project directory as its workon_home
        with temp_environ():
            if project.is_venv_in_project():
                os.environ['WORKON_HOME'] = project.project_directory
            pew.pew.workon_cmd([workon_name])
            sys.exit(0)
    # Activate the virtualenv if in compatibility mode.
    if compat:
        c.sendline(_activate_virtualenv())
    # Send additional arguments to the subshell.
    if shell_args:
        c.sendline(' '.join(shell_args))

    # Handler for terminal resizing events
    # Must be defined here to have the shell process in its context, since we
    # can't pass it as an argument
    def sigwinch_passthrough(sig, data):
        terminal_dimensions = get_terminal_size()
        c.setwinsize(terminal_dimensions.lines, terminal_dimensions.columns)

    signal.signal(signal.SIGWINCH, sigwinch_passthrough)
    # Interact with the new shell.
    c.interact(escape_character=None)
    c.close()
    sys.exit(c.exitstatus)
