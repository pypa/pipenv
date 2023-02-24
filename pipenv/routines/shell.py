import os
import subprocess
import sys
from os.path import expandvars

from pipenv import environments
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import cmd_list_to_shell, system_which
from pipenv.vendor import click


def do_shell(project, python=False, fancy=False, shell_args=None, pypi_mirror=None):
    # Ensure that virtualenv is available.
    ensure_project(
        project,
        python=python,
        validate=False,
        pypi_mirror=pypi_mirror,
    )

    # Support shell compatibility mode.
    if project.s.PIPENV_SHELL_FANCY:
        fancy = True

    from pipenv.shells import choose_shell

    shell = choose_shell(project)
    click.echo("Launching subshell in virtual environment...", err=True)

    fork_args = (
        project.virtualenv_location,
        project.project_directory,
        shell_args,
    )

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # otherwise its value will be changed
    os.environ["PIPENV_ACTIVE"] = "1"

    if fancy:
        shell.fork(*fork_args)
        return

    try:
        shell.fork_compat(*fork_args)
    except (AttributeError, ImportError):
        click.echo(
            "Compatibility mode not supported. "
            "Trying to continue as well-configured shell...",
            err=True,
        )
        shell.fork(*fork_args)


def do_run(project, command, args, python=False, pypi_mirror=None):
    """Attempt to run command either pulling from project or interpreting as executable.

    Args are appended to the command in [scripts] section of project if found.
    """
    from pipenv.cmdparse import ScriptEmptyError

    env = os.environ.copy()

    # Ensure that virtualenv is available.
    ensure_project(
        project,
        python=python,
        validate=False,
        pypi_mirror=pypi_mirror,
    )

    path = env.get("PATH", "")
    if project.virtualenv_location:
        new_path = os.path.join(
            project.virtualenv_location, "Scripts" if os.name == "nt" else "bin"
        )
        paths = path.split(os.pathsep)
        paths.insert(0, new_path)
        path = os.pathsep.join(paths)
        env["VIRTUAL_ENV"] = project.virtualenv_location
    env["PATH"] = path

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # such as in inline_activate_virtual_environment
    # otherwise its value will be changed
    env["PIPENV_ACTIVE"] = "1"

    try:
        script = project.build_script(command, args)
        cmd_string = cmd_list_to_shell([script.command] + script.args)
        if project.s.is_verbose():
            click.echo(click.style(f"$ {cmd_string}"), err=True)
    except ScriptEmptyError:
        click.echo("Can't run script {0!r}-it's empty?", err=True)
    run_args = [project, script]
    run_kwargs = {"env": env}
    # We're using `do_run_nt` on CI (even if we're running on a non-nt machine)
    # as a workaround for https://github.com/pypa/pipenv/issues/4909.
    if os.name == "nt" or environments.PIPENV_IS_CI:
        run_fn = do_run_nt
    else:
        run_fn = do_run_posix
        run_kwargs.update({"command": command})
    run_fn(*run_args, **run_kwargs)


def do_run_posix(project, script, command, env):
    path = env.get("PATH")
    command_path = system_which(script.command, path=path)
    if not command_path:
        if project.has_script(command):
            click.echo(
                "{}: the command {} (from {}) could not be found within {}."
                "".format(
                    click.style("Error", fg="red", bold=True),
                    click.style(script.command, fg="yellow"),
                    click.style(command, bold=True),
                    click.style("PATH", bold=True),
                ),
                err=True,
            )
        else:
            click.echo(
                "{}: the command {} could not be found within {} or Pipfile's {}."
                "".format(
                    click.style("Error", fg="red", bold=True),
                    click.style(command, fg="yellow"),
                    click.style("PATH", bold=True),
                    click.style("[scripts]", bold=True),
                ),
                err=True,
            )
        sys.exit(1)
    os.execve(
        command_path,
        [command_path, *(os.path.expandvars(arg) for arg in script.args)],
        env,
    )


def do_run_nt(project, script, env):
    p = _launch_windows_subprocess(script, env)
    p.communicate()
    sys.exit(p.returncode)


def _launch_windows_subprocess(script, env):
    path = env.get("PATH", "")
    command = system_which(script.command, path=path)

    options = {"universal_newlines": True, "env": env}
    script.cmd_args[1:] = [expandvars(arg) for arg in script.args]

    # Command not found, maybe this is a shell built-in?
    if not command:
        return subprocess.Popen(script.cmdify(), shell=True, **options)

    # Try to use CreateProcess directly if possible. Specifically catch
    # Windows error 193 "Command is not a valid Win32 application" to handle
    # a "command" that is non-executable. See pypa/pipenv#2727.
    try:
        return subprocess.Popen([command] + script.args, **options)
    except OSError as e:
        if e.winerror != 193:
            raise

    # Try shell mode to use Windows's file association for file launch.
    return subprocess.Popen(script.cmdify(), shell=True, **options)
