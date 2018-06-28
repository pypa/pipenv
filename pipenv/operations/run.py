# -*- coding=utf-8 -*-
import os
import sys

from pipenv.patched import crayons
from pipenv.vendor import click

from pipenv.cmdparse import ScriptEmptyError
from pipenv.core import project, which
from pipenv.utils import system_which

from ._utils import load_dot_env
from .ensure import ensure_project


def _inline_activate_virtualenv():
    try:
        activate_this = which('activate_this.py')
        if not activate_this or not os.path.exists(activate_this):
            click.echo(
                u'{0}: activate_this.py not found. Your environment is most '
                u'certainly not activated. Continuing anyway...'
                u''.format(crayons.red('Warning', bold=True)),
                err=True,
            )
            return
        with open(activate_this) as f:
            code = compile(f.read(), activate_this, 'exec')
            exec(code, dict(__file__=activate_this))
    # Catch all errors, just in case.
    except Exception:
        click.echo(
            u'{0}: There was an unexpected error while activating your virtualenv. Continuing anyway...'
            ''.format(crayons.red('Warning', bold=True)),
            err=True,
        )


def _do_run_nt(script):
    import subprocess
    command = system_which(script.command)
    options = {'universal_newlines': True}
    if command:     # Try to use CreateProcess directly if possible.
        p = subprocess.Popen([command] + script.args, **options)
    else:   # Command not found, maybe this is a shell built-in?
        p = subprocess.Popen(script.cmdify(), shell=True, **options)
    p.communicate()
    sys.exit(p.returncode)


def _do_run_posix(script, command):
    command_path = system_which(script.command)
    if not command_path:
        if project.has_script(command):
            click.echo(
                '{0}: the command {1} (from {2}) could not be found within {3}.'
                ''.format(
                    crayons.red('Error', bold=True),
                    crayons.red(script.command),
                    crayons.normal(command, bold=True),
                    crayons.normal('PATH', bold=True),
                ),
                err=True,
            )
        else:
            click.echo(
                '{0}: the command {1} could not be found within {2} or Pipfile\'s {3}.'
                ''.format(
                    crayons.red('Error', bold=True),
                    crayons.red(command),
                    crayons.normal('PATH', bold=True),
                    crayons.normal('[scripts]', bold=True),
                ),
                err=True,
            )
        sys.exit(1)
    os.execl(command_path, command_path, *script.args)


def do_run(command, args, three=None, python=False):
    """Attempt to run command either pulling from project or interpreting as executable.

    Args are appended to the command in [scripts] section of project if found.
    """
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)
    load_dot_env()
    # Activate virtualenv under the current interpreter's environment
    _inline_activate_virtualenv()
    try:
        script = project.build_script(command, args)
    except ScriptEmptyError:
        click.echo("Can't run script {0!r}-it's empty?", err=True)
    if os.name == 'nt':
        _do_run_nt(script)
    else:
        _do_run_posix(script, command=command)
