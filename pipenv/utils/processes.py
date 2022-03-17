import contextlib
import os
import signal
import subprocess

import crayons
from click import echo as click_echo
from pipenv.vendor.vistir import run

from pipenv.exceptions import PipenvCmdError
from pipenv import environments

if environments.MYPY_RUNNING:
    from typing import Any, Dict, List, Optional, Text, Tuple, Union


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

    from pipenv._compat import decode_for_output
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
        click_echo(f"Running command: $ {cmd.cmdify()}")
    c = subprocess_run(command, *args, **kwargs)
    if is_verbose:
        click_echo("Command output: {}".format(
            crayons.cyan(decode_for_output(c.stdout))
        ), err=True)
    if c.returncode and catch_exceptions:
        raise PipenvCmdError(cmd.cmdify(), c.stdout, c.stderr, c.returncode)
    return c


@contextlib.contextmanager
def interrupt_handled_subprocess(
    cmd, verbose=False, return_object=True, write_to_stdout=False, combine_stderr=True,
    block=True, nospin=True, env=None
):
    """Given a :class:`subprocess.Popen` instance, wrap it in exception handlers.

    Terminates the subprocess when and if a `SystemExit` or `KeyboardInterrupt` are
    processed.

    Arguments:
        :param str cmd: A command to run
        :param bool verbose: Whether to run with verbose mode enabled, default False
        :param bool return_object: Whether to return a subprocess instance or a 2-tuple, default True
        :param bool write_to_stdout: Whether to write directly to stdout, default False
        :param bool combine_stderr: Whether to combine stdout and stderr, default True
        :param bool block: Whether the subprocess should be a blocking subprocess, default True
        :param bool nospin: Whether to suppress the spinner with the subprocess, default True
        :param Optional[Dict[str, str]] env: A dictionary to merge into the subprocess environment
        :return: A subprocess, wrapped in exception handlers, as a context manager
        :rtype: :class:`subprocess.Popen` obj: An instance of a running subprocess
    """
    obj = run(
        cmd, verbose=verbose, return_object=True, write_to_stdout=False,
        combine_stderr=False, block=True, nospin=True, env=env,
    )
    try:
        yield obj
    except (SystemExit, KeyboardInterrupt):
        if os.name == "nt":
            os.kill(obj.pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(obj.pid, signal.SIGINT)
        obj.wait()
        raise


def subprocess_run(
    args, *, block=True, text=True, capture_output=True,
    encoding="utf-8", env=None, **other_kwargs
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
        other_kwargs['stdout'] = subprocess.PIPE
        other_kwargs['stderr'] = subprocess.PIPE
    if block:
        return subprocess.run(
            args, universal_newlines=text,
            encoding=encoding, **other_kwargs
        )
    else:
        return subprocess.Popen(
            args, universal_newlines=text,
            encoding=encoding, **other_kwargs
        )


