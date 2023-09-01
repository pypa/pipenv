import contextlib
import os
import shutil
import sys
from pathlib import Path

from pipenv import environments, exceptions
from pipenv.patched.pip._vendor import rich
from pipenv.utils.dependencies import python_version
from pipenv.utils.environment import ensure_environment
from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import find_python, shorten_path
from pipenv.vendor import click

console = rich.console.Console()
err = rich.console.Console(stderr=True)


def warn_in_virtualenv(project):
    # Only warn if pipenv isn't already active.
    if environments.is_in_virtualenv() and not project.s.is_quiet():
        click.echo(
            "{}: Pipenv found itself running within a virtual environment, "
            "so it will automatically use that environment, instead of "
            "creating its own for any project. You can set "
            "{} to force pipenv to ignore that environment and create "
            "its own instead. You can set {} to suppress this "
            "warning.".format(
                click.style("Courtesy Notice", fg="green"),
                click.style("PIPENV_IGNORE_VIRTUALENVS=1", bold=True),
                click.style("PIPENV_VERBOSITY=-1", bold=True),
            ),
            err=True,
        )


def do_create_virtualenv(project, python=None, site_packages=None, pypi_mirror=None):
    """Creates a virtualenv."""

    click.secho("Creating a virtualenv for this project...", bold=True, err=True)

    click.echo(
        "Pipfile: " + click.style(project.pipfile_location, fg="yellow", bold=True),
        err=True,
    )

    # Default to using sys.executable, if Python wasn't provided.
    using_string = "Using"
    if not python:
        python = sys.executable
        using_string = "Using default python from"
    click.echo(
        "{} {} {} {}".format(
            click.style(using_string, bold=True),
            click.style(python, fg="yellow", bold=True),
            click.style(f"({python_version(python)})", fg="green"),
            click.style("to create virtualenv...", bold=True),
        ),
        err=True,
    )

    if site_packages:
        click.secho("Making site-packages available...", bold=True, err=True)

    if pypi_mirror:
        pip_config = {"PIP_INDEX_URL": pypi_mirror}
    else:
        pip_config = {}

    error = None
    with console.status(
        "Creating virtual environment...", spinner=project.s.PIPENV_SPINNER
    ):
        cmd = _create_virtualenv_cmd(project, python, site_packages=site_packages)
        c = subprocess_run(cmd, env=pip_config)
        click.secho(f"{c.stdout}", fg="cyan", err=True)
        if c.returncode != 0:
            error = (
                c.stderr if project.s.is_verbose() else exceptions.prettify_exc(c.stderr)
            )
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
        raise exceptions.VirtualenvCreationException(
            extra=click.style(f"{error}", fg="red")
        )

    # Associate project directory with the environment.
    project_file_name = os.path.join(project.virtualenv_location, ".project")
    with open(project_file_name, "w") as f:
        f.write(project.project_directory)
    from pipenv.environment import Environment

    sources = project.pipfile_sources()
    # project.get_location_for_virtualenv is only for if we are creating a new virtualenv
    # whereas virtualenv_location is for the current path to the runtime
    project._environment = Environment(
        prefix=project.virtualenv_location,
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


def ensure_virtualenv(project, python=None, site_packages=None, pypi_mirror=None):
    """Creates a virtualenv, if one doesn't exist."""

    def abort():
        sys.exit(1)

    if not project.virtualenv_exists:
        try:
            # Ensure environment variables are set properly.
            ensure_environment()
            # Ensure Python is available.
            python = ensure_python(project, python=python)
            if python is not None and not isinstance(python, str):
                python = python.path.as_posix()
            # Create the virtualenv.
            # Abort if --system (or running in a virtualenv).
            if project.s.PIPENV_USE_SYSTEM:
                click.secho(
                    "You are attempting to re–create a virtualenv that "
                    "Pipenv did not create. Aborting.",
                    fg="red",
                )
                sys.exit(1)
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
            python = python.path.as_posix()

        click.secho("Virtualenv already exists!", fg="red", err=True)
        # If VIRTUAL_ENV is set, there is a possibility that we are
        # going to remove the active virtualenv that the user cares
        # about, so confirm first.
        if "VIRTUAL_ENV" in os.environ and not (
            project.s.PIPENV_YES
            or click.confirm("Use existing virtualenv?", default=True)
        ):
            abort()
        click.echo(click.style("Using existing virtualenv...", bold=True), err=True)
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
        click.secho("Environment creation aborted.", fg="red")
    try:
        # Delete the virtualenv.
        shutil.rmtree(project.virtualenv_location)
    except OSError as e:
        click.echo(
            "{} An error occurred while removing {}!".format(
                click.style("Error: ", fg="red", bold=True),
                click.style(project.virtualenv_location, fg="green"),
            ),
            err=True,
        )
        click.secho(e, fg="cyan", err=True)


def ensure_python(project, python=None):
    # Runtime import is necessary due to the possibility that the environments module may have been reloaded.
    if project.s.PIPENV_PYTHON and not python:
        python = project.s.PIPENV_PYTHON

    def abort(msg=""):
        click.echo(
            "{}\nYou can specify specific versions of Python with:\n{}".format(
                click.style(msg, fg="red"),
                click.style(
                    "$ pipenv --python {}".format(os.sep.join(("path", "to", "python"))),
                    fg="yellow",
                ),
            ),
            err=True,
        )
        sys.exit(1)

    project.s.USING_DEFAULT_PYTHON = not python
    # Find out which python is desired.
    if not python:
        python = project.required_python_version
    if not python:
        python = project.s.PIPENV_DEFAULT_PYTHON_VERSION
    path_to_python = find_a_system_python(python)
    if project.s.is_verbose():
        click.echo(f"Using python: {python}", err=True)
        click.echo(f"Path to python: {path_to_python}", err=True)
    if not path_to_python and python is not None:
        # We need to install Python.
        click.echo(
            "{}: Python {} {}".format(
                click.style("Warning", fg="red", bold=True),
                click.style(python, fg="cyan"),
                "was not found on your system...",
            ),
            err=True,
        )
        # check for python installers
        from pipenv.installers import Asdf, InstallerError, InstallerNotFound, Pyenv

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

        if not installer:
            abort("Neither 'pyenv' nor 'asdf' could be found to install Python.")
        else:
            if environments.SESSION_IS_INTERACTIVE or project.s.PIPENV_YES:
                try:
                    version = installer.find_version_to_install(python)
                except ValueError:
                    abort()
                except InstallerError as e:
                    abort(f"Something went wrong while installing Python:\n{e.err}")
                s = "{} {} {}".format(
                    "Would you like us to install",
                    click.style(f"CPython {version}", fg="green"),
                    f"with {installer}?",
                )
                # Prompt the user to continue...
                if not (project.s.PIPENV_YES or click.confirm(s, default=True)):
                    abort()
                else:
                    # Tell the user we're installing Python.
                    click.echo(
                        "{} {} {} {}{}".format(
                            click.style("Installing", bold=True),
                            click.style(f"CPython {version}", bold=True, fg="green"),
                            click.style(f"with {installer.cmd}", bold=True),
                            click.style("(this may take a few minutes)"),
                            click.style("...", bold=True),
                        )
                    )
                    with console.status(
                        "Installing python...", spinner=project.s.PIPENV_SPINNER
                    ):
                        try:
                            c = installer.install(version)
                        except InstallerError as e:
                            err.print(
                                environments.PIPENV_SPINNER_FAIL_TEXT.format("Failed...")
                            )
                            click.echo("Something went wrong...", err=True)
                            click.secho(e.err, fg="cyan", err=True)
                        else:
                            console.print(
                                environments.PIPENV_SPINNER_OK_TEXT.format("Success!")
                            )
                            # Print the results, in a beautiful blue...
                            click.secho(c.stdout, fg="cyan", err=True)
                    # Find the newly installed Python, hopefully.
                    version = str(version)
                    path_to_python = find_a_system_python(version)
                    try:
                        assert python_version(path_to_python) == version
                    except AssertionError:
                        click.echo(
                            "{}: The Python you just installed is not available on your {}, apparently."
                            "".format(
                                click.style("Warning", fg="red", bold=True),
                                click.style("PATH", bold=True),
                            ),
                            err=True,
                        )
                        sys.exit(1)
    return path_to_python


def find_a_system_python(line):
    """Find a Python installation from a given line.

    This tries to parse the line in various of ways:

    * Looks like an absolute path? Use it directly.
    * Looks like a py.exe call? Use py.exe to get the executable.
    * Starts with "py" something? Looks like a python command. Try to find it
      in PATH, and use it directly.
    * Search for "python" and "pythonX.Y" executables in PATH to find a match.
    * Nothing fits, return None.
    """

    from pipenv.vendor.pythonfinder import Finder

    finder = Finder(system=False, global_search=True)
    if not line:
        return next(iter(finder.find_all_python_versions()), None)
    # Use the windows finder executable
    if (line.startswith(("py ", "py.exe "))) and os.name == "nt":
        line = line.split(" ", 1)[1].lstrip("-")
    python_entry = find_python(finder, line)
    return python_entry


def do_where(project, virtualenv=False, bare=True):
    """Executes the where functionality."""
    if not virtualenv:
        if not project.pipfile_exists:
            click.echo(
                "No Pipfile present at project home. Consider running "
                "{} first to automatically generate a Pipfile for you."
                "".format(click.style("`pipenv install`", fg="green")),
                err=True,
            )
            return
        location = project.pipfile_location
        # Shorten the virtual display of the path to the virtualenv.
        if not bare:
            location = shorten_path(location)
            click.echo(
                "Pipfile found at {}.\n  Considering this to be the project home."
                "".format(click.style(location, fg="green")),
                err=True,
            )
        else:
            click.echo(project.project_directory)
    else:
        location = project.virtualenv_location
        if not bare:
            click.secho(f"Virtualenv location: {location}", fg="green", err=True)
        else:
            click.echo(location)


def inline_activate_virtual_environment(project):
    root = project.virtualenv_location
    if os.path.exists(os.path.join(root, "pyvenv.cfg")):
        _inline_activate_venv(project)
    else:
        _inline_activate_virtualenv(project)
    if "VIRTUAL_ENV" not in os.environ:
        os.environ["VIRTUAL_ENV"] = root


def _inline_activate_venv(project):
    """Built-in venv doesn't have activate_this.py, but doesn't need it anyway.

    As long as we find the correct executable, built-in venv sets up the
    environment automatically.

    See: https://bugs.python.org/issue21496#msg218455
    """
    components = []
    for name in ("bin", "Scripts"):
        bindir = os.path.join(project.virtualenv_location, name)
        if os.path.exists(bindir):
            components.append(bindir)
    if "PATH" in os.environ:
        components.append(os.environ["PATH"])
    os.environ["PATH"] = os.pathsep.join(components)


def _inline_activate_virtualenv(project):
    try:
        activate_this = project._which("activate_this.py")
        if not activate_this or not os.path.exists(activate_this):
            raise exceptions.VirtualenvActivationException()
        with open(activate_this) as f:
            code = compile(f.read(), activate_this, "exec")
            exec(code, {"__file__": activate_this})
    # Catch all errors, just in case.
    except Exception:
        click.echo(
            "{}: There was an unexpected error while activating your "
            "virtualenv. Continuing anyway...".format(
                click.style("Warning", fg="red", bold=True)
            ),
            err=True,
        )
