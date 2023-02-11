import os
import subprocess

from pipenv.exceptions import PipenvCmdError
from pipenv.utils.constants import MYPY_RUNNING
from pipenv.vendor import click

if MYPY_RUNNING:
    from typing import Tuple  # noqa


def run_command(cmd, *args, is_verbose=False, **kwargs):
    """
    Take an input command and run it, handling exceptions and error codes and returning
    its stdout and stderr.

    :param cmd: The list of command and arguments.
    :type cmd: list
    :returns: A 2-tuple of the output and error from the command
    :rtype: Tuple[str, str]
    :raises: exceptions.PipenvCmdError
    """

    from pipenv.cmdparse import Script

    catch_exceptions = kwargs.pop("catch_exceptions", True)
    if isinstance(cmd, ((str,), list, tuple)):
        cmd = Script.parse(cmd)
    if not isinstance(cmd, Script):
        raise TypeError("Command input must be a string, list or tuple")
    if "env" not in kwargs:
        kwargs["env"] = os.environ.copy()
    kwargs["env"]["PYTHONIOENCODING"] = "UTF-8"
    command = [cmd.command, *cmd.args]
    if is_verbose:
        click.echo(f"Running command: $ {cmd.cmdify()}")
    c = subprocess_run(command, *args, **kwargs)
    if is_verbose:
        click.echo(
            "Command output: {}".format(click.style(c.stdout, fg="cyan")),
            err=True,
        )
    if c.returncode and catch_exceptions:
        raise PipenvCmdError(cmd.cmdify(), c.stdout, c.stderr, c.returncode)
    return c


def subprocess_run(
    args,
    *,
    block=True,
    text=True,
    capture_output=True,
    encoding="utf-8",
    env=None,
    **other_kwargs,
):
    """A backward compatible version of subprocess.run().

    It outputs text with default encoding, and store all outputs in the returned object instead of
    printing onto stdout.
    """
    _env = os.environ.copy()
    _env["PYTHONIOENCODING"] = encoding
    if env:
        _env.update(env)
    other_kwargs["env"] = _env
    if capture_output:
        other_kwargs["stdout"] = subprocess.PIPE
        other_kwargs["stderr"] = subprocess.PIPE
    if block:
        return subprocess.run(
            args, universal_newlines=text, encoding=encoding, **other_kwargs
        )
    else:
        return subprocess.Popen(
            args, universal_newlines=text, encoding=encoding, **other_kwargs
        )
