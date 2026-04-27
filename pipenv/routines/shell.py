import os
import subprocess
import sys

from pipenv.utils import err
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import cmd_list_to_shell, safe_expandvars, system_which
from pipenv.utils.virtualenv import virtualenv_scripts_dir


def do_shell(
    project, python=False, fancy=False, shell_args=None, pypi_mirror=None, quiet=False
):
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
    # Respect both --quiet flag and PIPENV_QUIET environment variable
    # See: https://github.com/pypa/pipenv/issues/5954
    quiet = quiet or project.s.is_quiet()
    if not quiet:
        err.print("Launching subshell in virtual environment...")

    fork_args = (
        project.virtualenv_location,
        project.project_directory,
        shell_args,
    )

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # otherwise its value will be changed
    os.environ["PIPENV_ACTIVE"] = "1"

    # Set PIPENV_PROJECT_DIR to the project root directory.
    # This allows scripts to reference project-relative paths regardless of
    # the current working directory. See: https://github.com/pypa/pipenv/issues/2241
    os.environ["PIPENV_PROJECT_DIR"] = str(project.project_directory)

    if fancy:
        shell.fork(*fork_args)
        return

    try:
        shell.fork_compat(*fork_args, quiet=quiet)
    except (AttributeError, ImportError):
        err.print(
            "Compatibility mode not supported. "
            "Trying to continue as well-configured shell..."
        )
        shell.fork(*fork_args)


def do_run(project, command, args, python=False, pypi_mirror=None, system=False):
    """Attempt to run command either pulling from project or interpreting as executable.

    Args are appended to the command in [scripts] section of project if found.

    When system=True, skip virtualenv creation and use system Python directly.
    This is useful in Docker environments where packages are installed with
    `pipenv install --system` and users want to run scripts from [scripts] section.

    If the script is defined as a TOML array of command strings, each command
    is executed in order; the sequence stops at the first non-zero exit code
    (equivalent to shell ``&&`` chaining).
    """

    from pipenv.cmdparse import ScriptEmptyError

    env = os.environ.copy()

    # Handle --system flag
    if system:
        project.s.PIPENV_USE_SYSTEM = True
        os.environ["PIPENV_USE_SYSTEM"] = "1"

    # Ensure that virtualenv is available (unless --system is used).
    ensure_project(
        project,
        python=python,
        validate=False,
        pypi_mirror=pypi_mirror,
        system=system,
    )

    path = env.get("PATH", "")
    # Only modify PATH for virtualenv if not using --system
    if not system and project.virtualenv_location:
        # Get the exact string representation of virtualenv_location
        virtualenv_location = str(project.virtualenv_location)

        new_path = str(virtualenv_scripts_dir(virtualenv_location))

        # Update PATH
        paths = path.split(os.pathsep)
        paths.insert(0, new_path)
        path = os.pathsep.join(paths)

        # Set VIRTUAL_ENV to the exact string representation
        env["VIRTUAL_ENV"] = virtualenv_location
    env["PATH"] = path

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # such as in inline_activate_virtual_environment
    # otherwise its value will be changed
    env["PIPENV_ACTIVE"] = "1"

    # Set PIPENV_PROJECT_DIR to the project root directory.
    # This allows scripts to reference project-relative paths regardless of
    # the current working directory. See: https://github.com/pypa/pipenv/issues/2241
    env["PIPENV_PROJECT_DIR"] = str(project.project_directory)

    try:
        script = project.build_script(command, args)
    except ScriptEmptyError:
        err.print("Can't run script {0!r}-it's empty?")
        return

    # Extract any inline env var assignments that prefix the real command,
    # e.g. `pipenv run FOO=bar cmd` or a [scripts] entry `FOO='a b' cmd`.
    # They are added directly to *env* so the child process inherits them.
    script, inline_env = script.with_extracted_env_vars()
    env.update(inline_env)

    if script.is_sequence:
        _run_script_sequence(script, env, verbose=project.s.is_verbose())
        return  # _run_script_sequence always calls sys.exit

    cmd_string = cmd_list_to_shell([script.command] + script.args)
    if project.s.is_verbose():
        err.print(f"$ {cmd_string}", style="cyan")

    run_args = [project, script]
    run_kwargs = {"env": env}
    if os.name == "nt":
        run_fn = do_run_nt
    else:
        run_fn = do_run_posix
        run_kwargs.update({"command": command})
    run_fn(*run_args, **run_kwargs)


def _run_script_sequence(script, env, verbose=False):
    """Run each sub-script in a sequence, stopping on the first failure.

    Unlike single-command execution (which uses ``os.execve`` on POSIX to
    replace the process), sequential commands are run via ``subprocess.run``
    so that control can return here between steps.

    The process exits with the return code of the first failed command, or 0
    if all commands succeeded.
    """
    string_env = {k: str(v) for k, v in env.items() if v is not None}
    path = env.get("PATH", "")

    for sub in script._sequence:
        # Inline env vars are scoped to each individual sub-command so they
        # don't bleed into subsequent steps.
        sub, sub_inline_env = sub.with_extracted_env_vars()
        sub_string_env = {**string_env, **sub_inline_env}

        expanded_args = [safe_expandvars(arg, env=sub_string_env) for arg in sub.args]
        cmd_args = [sub.command] + expanded_args
        if verbose:
            err.print(f"$ {cmd_list_to_shell(cmd_args)}", style="cyan")

        if os.name == "nt":
            # On Windows mirror _launch_windows_subprocess: try direct
            # CreateProcess first, fall back to shell=True.
            command_path = system_which(sub.command, path=path)
            sub.cmd_args[1:] = expanded_args
            if command_path:
                try:
                    result = subprocess.run(
                        [command_path] + sub.args, env=sub_string_env, check=False
                    )
                except OSError as exc:
                    if exc.winerror != 193:
                        raise
                    result = subprocess.run(
                        sub.cmdify(), shell=True, env=sub_string_env, check=False
                    )
            else:
                result = subprocess.run(
                    sub.cmdify(), shell=True, env=sub_string_env, check=False
                )
        else:
            command_path = system_which(sub.command, path=path)
            if command_path:
                result = subprocess.run(
                    [command_path, *expanded_args],
                    env=sub_string_env,
                    check=False,
                )
            else:
                result = subprocess.run(
                    cmd_list_to_shell(cmd_args),
                    shell=True,
                    env=sub_string_env,
                    check=False,
                )

        if result.returncode != 0:
            sys.exit(result.returncode)

    sys.exit(0)


def do_run_posix(project, script, command, env):
    path = env.get("PATH")
    command_path = system_which(script.command, path=path)

    # Ensure all environment variables are strings
    string_env = {k: str(v) for k, v in env.items() if v is not None}
    expanded_args = [safe_expandvars(arg, env=string_env) for arg in script.args]

    if command_path:
        # Command found in PATH, use os.execve for direct execution
        os.execve(
            command_path,
            [command_path, *expanded_args],
            string_env,
        )
    else:
        # Command not found in PATH, maybe it's a shell builtin (cd, echo, export, etc.)
        # Fall back to running through the shell, similar to Windows behavior.
        # See: https://github.com/pypa/pipenv/issues/6186
        cmd_args = [script.command] + expanded_args
        cmd_string = cmd_list_to_shell(cmd_args)
        result = subprocess.run(cmd_string, shell=True, env=string_env, check=False)
        sys.exit(result.returncode)


def do_run_nt(project, script, env):
    p = _launch_windows_subprocess(script, env)
    p.communicate()
    sys.exit(p.returncode)


def _launch_windows_subprocess(script, env):
    path = env.get("PATH", "")
    command = system_which(script.command, path=path)

    # Ensure all environment variables are strings
    string_env = {k: str(v) for k, v in env.items() if v is not None}
    options = {"universal_newlines": True, "env": string_env}
    script.cmd_args[1:] = [safe_expandvars(arg, env=string_env) for arg in script.args]

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
