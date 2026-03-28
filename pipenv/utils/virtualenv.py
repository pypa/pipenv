import contextlib
import os
import re
import shutil
import sys
import sysconfig
from pathlib import Path

from pipenv import environments, exceptions
from pipenv.utils import Confirm, console, err
from pipenv.utils.dependencies import python_version
from pipenv.utils.environment import ensure_environment
from pipenv.utils.fileutils import create_tracked_tempdir
from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import find_python, shorten_path


def virtualenv_scripts_dir(b):
    """returns a system-dependent scripts path

    POSIX environments (including Cygwin/MinGW64) will result in
    `{base}/bin/`, native Windows environments will result in
    `{base}/Scripts/`.

    :param b: base path
    :type b: str
    :returns: pathlib.Path
    """
    return Path(f"{b}/{Path(sysconfig.get_path('scripts')).name}")


def warn_in_virtualenv(project):
    # Only warn if pipenv isn't already active.
    if environments.is_in_virtualenv() and not project.s.is_quiet():
        err.print("[green]Courtesy Notice[/green]:")
        err.print(
            "Pipenv found itself running within a virtual environment, ",
            "so it will automatically use that environment, instead of ",
            "creating its own for any project. You can set",
        )
        err.print(
            "[bold]PIPENV_IGNORE_VIRTUALENVS=1[/bold]",
            "to force pipenv to ignore that environment and create ",
            "its own instead.",
        )
        err.print(
            "You can set [bold]PIPENV_VERBOSITY=-1[/bold] to suppress this warning."
        )


def do_create_virtualenv(project, python=None, site_packages=None, pypi_mirror=None):
    """Creates a virtualenv."""
    err.print("[bold]Creating a virtualenv for this project[/bold]")
    err.print(f"Pipfile: [bold][yellow]{project.pipfile_location}[/yellow][/bold]")

    # Default to using sys.executable, if Python wasn't provided.
    using_string = "Using"
    if not python:
        python = sys.executable
        using_string = "Using default python from"

    err.print(
        f"[bold]{using_string}[/bold] [bold][yellow]{python}[/yellow][/bold] "
        f"[green]{python_version(python)}[/green] "
        "[bold]to create virtualenv...[/bold]"
    )

    if site_packages:
        err.print("[bold]Making site-packages available...[/bold]")

    if pypi_mirror:
        pip_config = {"PIP_INDEX_URL": pypi_mirror}
    else:
        pip_config = {}

    error = None
    with console.status(
        "Creating virtual environment...", spinner=project.s.PIPENV_SPINNER
    ):
        cmd = _create_virtualenv_cmd(project, python, site_packages=site_packages)

        # Issue: https://github.com/pypa/pipenv/issues/6568
        # Run virtualenv from an empty temporary directory to prevent PYTHONPATH pollution.
        # Once we drop support for python3.10 we can add a -P to the `python -m virtualenv` call to avoid this workaround
        temp_dir = create_tracked_tempdir()
        c = subprocess_run(cmd, env=pip_config, cwd=temp_dir)

        err.print(f"[cyan]{c.stdout}[/cyan]")
        if c.returncode != 0:
            virtualenv_error = (
                c.stderr if project.s.is_verbose() else exceptions.prettify_exc(c.stderr)
            )
            # Issue: https://github.com/pypa/pipenv/issues/5601
            # virtualenv may not support alternative Python implementations (e.g.
            # RustPython, GraalPy). Fall back to the target interpreter's own
            # built-in `venv` module, which those implementations are more likely
            # to ship. Only attempt the fallback when the user has not explicitly
            # chosen a virtualenv creator via PIPENV_VIRTUALENV_CREATOR.
            if not project.s.PIPENV_VIRTUALENV_CREATOR:
                err.print(
                    "[yellow]virtualenv failed; retrying with the interpreter's "
                    "built-in venv module...[/yellow]"
                )
                fallback_cmd = _create_builtin_venv_cmd(
                    project, python, site_packages=site_packages
                )
                c2 = subprocess_run(fallback_cmd, env=pip_config, cwd=temp_dir)
                err.print(f"[cyan]{c2.stdout}[/cyan]")
                if c2.returncode == 0:
                    err.print(
                        environments.PIPENV_SPINNER_OK_TEXT.format(
                            "Successfully created virtual environment!"
                        )
                    )
                    err.print(
                        "[bold yellow]Note:[/bold yellow] Created using the interpreter's "
                        "built-in [bold]venv[/bold] module because [bold]virtualenv[/bold] "
                        "was not able to use this interpreter directly. "
                        "Some virtualenv features (e.g. [bold]--copies[/bold]) may not be available."
                    )
                else:
                    # Both strategies failed — surface the original virtualenv error
                    # plus the venv error so the user has full context.
                    venv_error = (
                        c2.stderr
                        if project.s.is_verbose()
                        else exceptions.prettify_exc(c2.stderr)
                    )
                    error = f"{virtualenv_error}\n\nvenv fallback error:\n{venv_error}"
                    err.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Failed creating virtual environment"
                        )
                    )
            else:
                error = virtualenv_error
                err.print(
                    environments.PIPENV_SPINNER_FAIL_TEXT.format(
                        "Failed creating virtual environment"
                    )
                )
        else:
            err.print(
                environments.PIPENV_SPINNER_OK_TEXT.format(
                    "Successfully created virtual environment!"
                )
            )
    if error is not None:
        raise exceptions.VirtualenvCreationException(extra=f"[red]{error}[/red]")

    # Associate project directory with the environment.
    virtualenv_path = Path(project.virtualenv_location)
    project_file_path = virtualenv_path / ".project"
    project_file_path.write_text(project.project_directory)

    from pipenv.environment import Environment

    sources = project.pipfile_sources()
    # project.get_location_for_virtualenv is only for if we are creating a new virtualenv
    # whereas virtualenv_location is for the current path to the runtime
    project._environment = Environment(
        prefix=str(virtualenv_path),
        is_venv=True,
        sources=sources,
        pipfile=project.parsed_pipfile,
        project=project,
    )
    # Say where the virtualenv is.
    do_where(project, virtualenv=True, bare=False)


def _create_virtualenv_cmd(project, python, site_packages=False):
    cmd = [
        Path(sys.executable).absolute().as_posix(),
        "-m",
        "virtualenv",
    ]
    if project.s.PIPENV_VIRTUALENV_CREATOR:
        cmd.append(f"--creator={project.s.PIPENV_VIRTUALENV_CREATOR}")
    cmd.append(f"--prompt={project.name}")
    cmd.append(f"--python={python}")
    cmd.append(project.get_location_for_virtualenv())
    if project.s.PIPENV_VIRTUALENV_COPIES:
        cmd.append("--copies")

    # Pass site-packages flag to virtualenv, if desired...
    if site_packages:
        cmd.append("--system-site-packages")

    return cmd


def _create_builtin_venv_cmd(project, python, site_packages=False):
    """Build a command that uses the *target* interpreter's own built-in venv
    module (``python -m venv``).

    This is the fallback used when ``virtualenv`` fails for a given interpreter
    (e.g. RustPython, GraalPy) because those implementations may ship their own
    ``venv`` module even if they don't support all the C-extension hooks that
    virtualenv probes for.  See: https://github.com/pypa/pipenv/issues/5601
    """
    cmd = [
        python,
        "-m",
        "venv",
        f"--prompt={project.name}",
    ]
    if site_packages:
        cmd.append("--system-site-packages")
    cmd.append(project.get_location_for_virtualenv())
    return cmd


def ensure_virtualenv(project, python=None, site_packages=None, pypi_mirror=None):
    """Creates a virtualenv, if one doesn't exist."""

    # When --system is used, skip virtualenv creation entirely.
    # The user explicitly wants to install to the system Python.
    if project.s.PIPENV_USE_SYSTEM:
        return

    if not project.virtualenv_exists:
        try:
            # Ensure environment variables are set properly.
            ensure_environment()
            # Ensure Python is available.
            python = ensure_python(project, python=python)
            if python is not None and not isinstance(python, str):
                if hasattr(python, "path"):  # It's a PythonInfo object
                    python = python.path.as_posix()
                else:  # It's a Path object
                    python = python.as_posix()
            do_create_virtualenv(
                project,
                python=python,
                site_packages=site_packages,
                pypi_mirror=pypi_mirror,
            )
        except KeyboardInterrupt:
            # If interrupted, cleanup the virtualenv.
            cleanup_virtualenv(project, bare=False)
            sys.exit(1)
    # If --python or was passed...
    elif (python) or (site_packages is not None):
        project.s.USING_DEFAULT_PYTHON = False
        # Ensure python is installed before deleting existing virtual env
        python = ensure_python(project, python=python)
        if python is not None and not isinstance(python, str):
            if hasattr(python, "path"):  # It's a PythonInfo object
                python = python.path.as_posix()
            else:  # It's a Path object
                python = python.as_posix()

        err.print(
            "[bold yellow]Virtualenv already exists but Python version differs. "
            "Recreating virtualenv...[/bold yellow]"
        )
        # If VIRTUAL_ENV is set, there is a possibility that we are
        # going to remove the active virtualenv that the user cares
        # about, so confirm first.
        if "VIRTUAL_ENV" in os.environ and not (
            project.s.PIPENV_YES
            or Confirm.ask("Recreate existing virtualenv?", default=True)
        ):
            sys.exit(1)
        # Remove the virtualenv.
        cleanup_virtualenv(project, bare=True)
        # Call this function again.
        ensure_virtualenv(
            project,
            python=python,
            site_packages=site_packages,
            pypi_mirror=pypi_mirror,
        )


def cleanup_virtualenv(project, bare=True):
    """Removes the virtualenv directory from the system."""
    if not bare:
        console.print("[red]Environment creation aborted.[/red]")
    try:
        # Delete the virtualenv.
        shutil.rmtree(project.virtualenv_location)
    except OSError as e:
        err.print(
            f"[bold][red]Error:[/red][/bold] An error occurred while removing [green]{project.virtualenv_location}[/green]!"
        )
        err.print(f"[cyan]{e}[/cyan]")


def ensure_python(project, python=None):
    # Runtime import is necessary due to the possibility that the environments module may have been reloaded.
    if project.s.PIPENV_PYTHON and not python:
        python = project.s.PIPENV_PYTHON

    def abort(msg=""):
        err.print(f"[red]{msg}[/red]")
        err.print("You can specify specific versions of Python with:")
        err.print(
            f"[yellow]$ pipenv --python {os.sep.join(['path', 'to', 'python'])}[/yellow]"
        )
        sys.exit(1)

    project.s.USING_DEFAULT_PYTHON = not python
    # Find out which python is desired.
    if not python:
        python = project.required_python_version
        if python:
            range_pattern = r"^[<>]=?|!="
            if re.search(range_pattern, python):
                # PEP 440 specifier like ">=3.8" — find the best installed match.
                path_to_python = _find_python_for_specifier(
                    python, pyenv_only=project.s.PIPENV_PYENV_ONLY
                )
                if path_to_python:
                    err.print(
                        f"Found Python satisfying [cyan]{python}[/cyan]: [green]{path_to_python}[/green]"
                    )
                    return path_to_python
                else:
                    err.print(
                        f"[bold red]Error[/bold red]: No installed Python satisfies [cyan]{python}[/cyan]. "
                        "[yellow]Install a compatible Python via pyenv or asdf first.[/yellow]"
                    )
                    sys.exit(1)

    if not python:
        python = project.s.PIPENV_DEFAULT_PYTHON_VERSION
    # When no Python was explicitly requested and no default is configured,
    # return None so that do_create_virtualenv falls back to sys.executable
    # (the Python that is running pipenv).  Calling find_a_system_python(None)
    # would pick the *newest* Python on the system, which may differ from the
    # pipenv runner and produces non-deterministic behaviour across machines.
    if not python:
        return None
    # Try to find Python using system registry and default paths first
    path_to_python = find_a_system_python(python, pyenv_only=project.s.PIPENV_PYENV_ONLY)

    if project.s.is_verbose():
        err.print(f"Using python: {python}")
        err.print(f"Path to python: {path_to_python}")

    # If not found and we're on Windows, try using the py launcher
    if (
        not path_to_python
        and os.name == "nt"
        and python is not None
        and (python[0].isdigit() or python.startswith("python"))
    ):
        # Extract version number if it's in format like "python3.11" or "python_version = 3.11"
        if python.startswith("python"):
            version_match = re.search(r"(\d+\.\d+)", python)
            if version_match:
                python_version_str = version_match.group(1)
            else:
                python_version_str = python
        else:
            python_version_str = python

        python_path = find_python_from_py_launcher(python_version_str)
        if python_path:
            if project.s.is_verbose():
                err.print(f"Found Python using py launcher: {python_path}")
            return python_path

    if not path_to_python and python is not None:
        # We need to install Python.
        err.print(
            "[bold][red]Warning:[/red][/bold] "
            f"Python [cyan]{python}[/cyan] "
            "was not found on your system..."
        )
        # check for python installers
        from pipenv.installers import (
            Asdf,
            InstallerError,
            InstallerNotFound,
            Pyenv,
            PyManager,
        )

        # prefer pyenv if both pyenv and asdf are installed as it's
        # dedicated to python installs so probably the preferred
        # method of the user for new python installs.
        installer = None
        if not project.s.PIPENV_DONT_USE_PYENV:
            with contextlib.suppress(InstallerNotFound):
                installer = Pyenv(project)

        if installer is None and not project.s.PIPENV_DONT_USE_ASDF:
            with contextlib.suppress(InstallerNotFound):
                installer = Asdf(project)

        # On Windows, fall back to the Python Install Manager (pymanager) if
        # neither pyenv nor asdf are available. pymanager is the tool recommended
        # by the Python documentation for installing Python on Windows.
        # See: https://docs.python.org/3/using/windows.html#python-install-manager
        if (
            installer is None
            and os.name == "nt"
            and not project.s.PIPENV_DONT_USE_PYMANAGER
        ):
            with contextlib.suppress(InstallerNotFound):
                installer = PyManager(project)

        if not installer:
            if os.name == "nt":
                abort(
                    "Python was not found on your system and none of 'pyenv', 'asdf', "
                    "or 'pymanager' (Python Install Manager) could be found to install Python. "
                    "Install pymanager from https://www.python.org/downloads/ or via the Microsoft Store."
                )
            else:
                abort("Neither 'pyenv' nor 'asdf' could be found to install Python.")
        else:
            try:
                version = installer.find_version_to_install(python)
            except ValueError:
                abort()
            except InstallerError as e:
                abort(f"Something went wrong while installing Python:\n{e.err}")

            s = (
                "Would you like us to install ",
                f"[green]CPython {version}[/green] ",
                f"with {installer}?",
            )

            # Prompt the user to continue...
            # PIPENV_PYENV_AUTO_INSTALL allows automatic installation without prompting
            auto_install = project.s.PIPENV_YES or project.s.PIPENV_PYENV_AUTO_INSTALL
            if environments.SESSION_IS_INTERACTIVE:
                if not (auto_install or Confirm.ask("".join(s), default=True)):
                    abort()
            elif not auto_install:
                # Non-interactive session without auto-install enabled, aborting
                abort()

            # Tell the user we're installing Python.
            console.print(
                f"[bold]Installing [green]CPython[/green] {version} with {installer.cmd}[/bold]"
            )
            console.print("(this may take a few minutes)[bold]...[/bold]")
            with console.status("Installing python...", spinner=project.s.PIPENV_SPINNER):
                try:
                    c = installer.install(version)
                except InstallerError as e:
                    err.print(environments.PIPENV_SPINNER_FAIL_TEXT.format("Failed..."))
                    err.print("Something went wrong...")
                    err.print(f"[cyan]{e.err}[/cyan]")
                else:
                    console.print(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
                    # Print the results, in a beautiful blue...
                    err.print(f"[cyan]{c.stdout}[/cyan]")
            # Find the newly installed Python, hopefully.
            version = str(version)
            path_to_python = find_a_system_python(
                version, pyenv_only=project.s.PIPENV_PYENV_ONLY
            )
            try:
                assert python_version(path_to_python) == version
            except AssertionError:
                err.print(
                    "[bold][red]Warning:[/red][/bold]"
                    " The Python you just installed is not available "
                    "on your [bold]PATH[/bold], apparently."
                )
                sys.exit(1)
    return path_to_python


def _find_python_for_specifier(specifier_str, pyenv_only=False):
    """Return the path to the highest installed Python satisfying *specifier_str*.

    *specifier_str* is a PEP 440 version-specifier string such as ``">=3.8"``
    or ``">=3.9,<4"``.  Returns ``None`` when no installed Python satisfies the
    constraint.
    """
    from pipenv.vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
    from pipenv.vendor.pythonfinder import Finder

    try:
        spec = SpecifierSet(specifier_str)
    except InvalidSpecifier:
        return None

    finder = Finder(system=True, global_search=True, pyenv_only=pyenv_only)
    all_versions = finder.find_all_python_versions()

    candidates = []
    for python_info in all_versions:
        ver_str = python_info.version_str
        if ver_str:
            try:
                if ver_str in spec:
                    candidates.append(python_info)
            except Exception:
                pass

    if not candidates:
        return None

    # find_all_python_versions already sorts descending; pick first.
    best = sorted(candidates, key=lambda x: x.version_sort, reverse=True)[0]
    path = (
        best.path if best.path else (Path(best.executable) if best.executable else None)
    )
    return str(path) if path else None


def find_python_from_py_launcher(version):
    """Find a Python installation using the Windows py launcher.

    This uses the py --list-paths command to find Python installations on Windows.

    Args:
        version: A version string like "3.9" or "3.9.0"

    Returns:
        The path to the Python executable, or None if not found
    """
    if os.name != "nt":
        return None

    # Normalize version to major.minor format
    if version and version[0].isdigit():
        version_parts = version.split(".")
        if len(version_parts) >= 2:
            version = f"{version_parts[0]}.{version_parts[1]}"
        else:
            version = version_parts[0]
    else:
        return None

    try:
        # Run py --list-paths to get all installed Python versions
        c = subprocess_run(["py", "--list-paths"], capture_output=True, text=True)
        if c.returncode != 0:
            return None

        # Parse the output to find the requested version.
        # The format from `py --list-paths` is one of:
        #   -V:3.12 *        C:\...\python.exe   (default version, has *)
        #   -V:3.11          C:\...\python.exe   (non-default, no *)
        # split(None, 2) gives 3 parts for default entries and only 2 parts
        # for non-default entries, so we must NOT require exactly 3 parts.
        for line in c.stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split(None, 2)
            if len(parts) < 2:
                continue

            # Extract version from -V:X.Y
            v_part = parts[0]
            if not v_part.startswith("-V:"):
                continue

            v = v_part[3:]  # Remove -V: prefix
            # Path is always the last token regardless of whether * is present
            path = parts[-1]
            if v == version:
                return path
    except Exception:
        # If anything goes wrong, fall back to other methods
        pass

    return None


def find_a_system_python(line, pyenv_only=False):
    """Find a Python installation from a given line.

    This tries to parse the line in various of ways:

    * Looks like an absolute path? Use it directly.
    * Looks like a py.exe call? Use py.exe to get the executable.
    * Starts with "py" something? Looks like a python command. Try to find it
      in PATH, and use it directly.
    * Search for "python" and "pythonX.Y" executables in PATH to find a match.
    * Nothing fits, return None.

    Note: The Windows py launcher is handled separately in ensure_python.

    Args:
        line: The python version or path string to search for.
        pyenv_only: If True, only search for pyenv-managed Python installations.
    """

    from pipenv.vendor.pythonfinder import Finder

    # Short-circuit: if an absolute path was given and it exists, use it
    # directly without scanning PATH (avoids PermissionError on restricted
    # Windows system directories such as C:\WINDOWS\system32\config\...).
    if line and os.path.isabs(line):
        path_obj = Path(line)
        if path_obj.is_file() and os.access(str(path_obj), os.X_OK):
            return str(path_obj)

    finder = Finder(system=True, global_search=True, pyenv_only=pyenv_only)
    if not line:
        return next(iter(finder.find_all_python_versions()), None)
    # Use the windows finder executable
    if (line.startswith(("py ", "py.exe "))) and os.name == "nt":
        line = line.split(" ", 1)[1].lstrip("-")

    # Try to find Python using the regular methods
    python_entry = find_python(finder, line)
    return python_entry


def do_where(project, virtualenv=False, bare=True):
    """Executes the where functionality."""
    if not virtualenv:
        if not project.pipfile_exists:
            err.print(
                "No Pipfile present at project home. Consider running "
                "[green]`pipenv install`[/green] first to automatically generate a Pipfile for you."
            )
            sys.exit(1)
        location = project.pipfile_location
        # Shorten the virtual display of the path to the virtualenv.
        if not bare:
            location = shorten_path(location)
            err.print(
                f"Pipfile found at [green]{location}[/green].\nConsidering this to be the project home."
            )
        else:
            console.print(project.project_directory)
    else:
        location = project.virtualenv_location
        if not bare:
            _width = err.width
            err.width = 1000
            err.print(f"[green]Virtualenv location: {location}[/green]")
            err.width = _width
        else:
            console.print(location)


def inline_activate_virtual_environment(project):
    root = project.virtualenv_location
    virtualenv_path = Path(root)

    if (virtualenv_path / "pyvenv.cfg").exists():
        _inline_activate_venv(project)
    else:
        _inline_activate_virtualenv(project)

    if "VIRTUAL_ENV" not in os.environ:
        os.environ["VIRTUAL_ENV"] = str(virtualenv_path)


def _inline_activate_venv(project):
    """Built-in venv doesn't have activate_this.py, but doesn't need it anyway.

    As long as we find the correct executable, built-in venv sets up the
    environment automatically.

    See: https://bugs.python.org/issue21496#msg218455
    """
    virtualenv_path = Path(project.virtualenv_location)
    components = []

    for name in ("bin", "Scripts"):
        bindir = virtualenv_path / name
        if bindir.exists():
            components.append(str(bindir))

    if "PATH" in os.environ:
        components.append(os.environ["PATH"])

    os.environ["PATH"] = os.pathsep.join(components)


def _inline_activate_virtualenv(project):
    try:
        activate_this = project._which("activate_this.py")
        activate_path = Path(activate_this) if activate_this else None

        if not activate_path or not activate_path.exists():
            raise exceptions.VirtualenvActivationException()

        code = compile(activate_path.read_text(), str(activate_path), "exec")
        exec(code, {"__file__": str(activate_path)})

    # Catch all errors, just in case.
    except Exception:
        err.print(
            "[bold][red]Warning: [/red][/bold]"
            "There was an unexpected error while activating your "
            "virtualenv. Continuing anyway..."
        )
