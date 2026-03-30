import os
from typing import TYPE_CHECKING, Optional

from pipenv import exceptions
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
from pipenv.utils import err
from pipenv.utils.dependencies import python_version
from pipenv.utils.pipfile import ensure_pipfile
from pipenv.utils.shell import shorten_path
from pipenv.utils.virtualenv import ensure_virtualenv, find_a_system_python
from pipenv.vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet

if TYPE_CHECKING:
    STRING_TYPE = str

import importlib.metadata as importlib_metadata


def _python_version_matches_required(actual_ver_str, required_ver_str):
    """Return True if *actual_ver_str* satisfies *required_ver_str*.

    ``required_ver_str`` comes from the Pipfile ``[requires]`` section and may
    be either:

    * A PEP 440 version specifier string like ``">=3.8"`` or ``">=3.9,<4"``
      (the ``python_version`` field contains an operator).
    * A plain ``"X.Y"`` (major.minor) or ``"X.Y.Z"`` (full version) string.

    ``actual_ver_str`` is the full version string reported by the Python
    interpreter (e.g. ``"3.13.1"``).
    """
    if not actual_ver_str or not required_ver_str:
        return False

    # If the required string contains a PEP 440 operator, treat it as a
    # SpecifierSet (e.g. ">=3.8", ">=3.9,<4").
    if any(op in required_ver_str for op in (">=", "<=", "!=", "~=", ">", "<")):
        try:
            spec = SpecifierSet(required_ver_str)
            return actual_ver_str in spec
        except InvalidSpecifier:
            pass

    try:
        actual = parse_version(actual_ver_str)
        required = parse_version(required_ver_str)
        if len(required_ver_str.split(".")) >= 3:
            # python_full_version specified — must match exactly.
            return actual == required
        else:
            # python_version (major.minor only) — compare only those components.
            return actual.major == required.major and actual.minor == required.minor
    except Exception:
        # Fallback for any unparseable version strings.
        return actual_ver_str == required_ver_str


def ensure_project(
    project,
    python=None,
    validate=True,
    system=False,
    warn=True,
    site_packages=None,
    deploy=False,
    skip_requirements=False,
    pypi_mirror=None,
    clear=False,
    pipfile_categories=None,
    lockfile_only=False,
):
    """Ensures both Pipfile and virtualenv exist for the project."""

    # Automatically use an activated virtualenv.
    if project.s.PIPENV_USE_SYSTEM or project.virtualenv_exists:
        system_or_exists = True
    else:
        system_or_exists = system  # default to False
    if not project.pipfile_exists and deploy:
        raise exceptions.PipfileNotFound

    # When --system is used with --python, validate that the Python can be found
    # and store the resolved path so pip uses the correct interpreter.
    if system and python:
        path_to_python = find_a_system_python(
            python, pyenv_only=project.s.PIPENV_PYENV_ONLY
        )
        if not path_to_python:
            raise exceptions.PipenvUsageError(
                message=f"Python version '{python}' was not found on your system. "
                "Please ensure Python is installed and available in PATH.",
            )
        # Store the resolved Python path so project_python() and
        # get_environment() can use the correct interpreter for --system
        # installs targeting a specific Python (#3593).
        os.environ["PIP_PYTHON_PATH"] = path_to_python
        project.s.PIPENV_PYTHON = path_to_python

    # If --python was explicitly specified and the existing virtualenv uses a different
    # Python version, allow ensure_virtualenv to handle recreation.
    if (
        python
        and project.virtualenv_exists
        and not system
        and not project.s.PIPENV_USE_SYSTEM
    ):
        try:
            venv_python_path = project._which("python") or project._which("py")
            if venv_python_path:
                venv_python_ver = python_version(str(venv_python_path))
                if os.path.isabs(python):
                    # python is an absolute path; get its version for comparison.
                    requested_ver = python_version(python)
                else:
                    # python is a version specifier like "3.12".
                    requested_ver = python
                if (
                    venv_python_ver
                    and requested_ver
                    and not _python_version_matches_required(
                        venv_python_ver, requested_ver
                    )
                ):
                    system_or_exists = False
        except Exception:
            pass  # If version detection fails, fall through to default behavior

    # Skip virtualenv creation when --system was used.
    if not system_or_exists:
        ensure_virtualenv(
            project,
            python=python,
            site_packages=site_packages,
            pypi_mirror=pypi_mirror,
        )

    # Warn users if they are using the wrong version of Python.
    # This check applies to both virtualenv and --system installations.
    if warn and project.required_python_version:
        if system or project.s.PIPENV_USE_SYSTEM:
            # For --system, check the system Python
            path_to_python = (
                find_a_system_python(python, pyenv_only=project.s.PIPENV_PYENV_ONLY)
                if python
                else None
            )
            if not path_to_python:
                from pipenv.utils.shell import system_which

                path_to_python = system_which("python3") or system_which("python")
        else:
            path_to_python = project._which("python") or project._which("py")

        if path_to_python and not _python_version_matches_required(
            python_version(path_to_python) or "", project.required_python_version
        ):
            err.print(
                f"[red][bold]Warning[/bold][/red]: Your Pipfile requires "
                f'[bold]"python_version"[/bold] [cyan]{project.required_python_version}[/cyan], '
                f"but you are using [cyan]{python_version(path_to_python)}[/cyan] "
                f"from [green]{shorten_path(path_to_python)}[/green]."
            )
            if not (system or project.s.PIPENV_USE_SYSTEM):
                err.print(
                    "[green]$ pipenv --rm[/green] and rebuilding the virtual environment "
                    "may resolve the issue."
                )
            if not deploy:
                err.print("[yellow]$ pipenv check[/yellow] will surely fail.")
            else:
                raise exceptions.DeployException

    # Ensure the Pipfile exists (skip when installing from lockfile only,
    # e.g. ``pipenv sync`` — we don't need or want to create a blank Pipfile).
    if not lockfile_only:
        ensure_pipfile(
            project,
            validate=validate,
            skip_requirements=skip_requirements,
            system=system,
            pipfile_categories=pipfile_categories,
        )
    os.environ["PIP_PYTHON_PATH"] = project.python(system=system)


def get_setuptools_version() -> Optional["STRING_TYPE"]:
    try:
        setuptools_dist = importlib_metadata.distribution("setuptools")
        return str(setuptools_dist.version)
    except ImportError:
        return None


def get_default_pyproject_backend():
    # type: () -> STRING_TYPE
    st_version = get_setuptools_version()
    if st_version is not None:
        parsed_st_version = parse_version(st_version)
        if parsed_st_version >= parse_version("40.8.0"):
            return "setuptools.build_meta:__legacy__"
    return "setuptools.build_meta"
