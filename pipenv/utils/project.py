import os
from functools import lru_cache

from pipenv import exceptions
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
from pipenv.patched.pip._vendor.pkg_resources import Requirement, get_distribution
from pipenv.utils.dependencies import python_version
from pipenv.utils.pipfile import ensure_pipfile
from pipenv.utils.shell import shorten_path
from pipenv.utils.virtualenv import ensure_virtualenv
from pipenv.vendor import click


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
    categories=None,
):
    """Ensures both Pipfile and virtualenv exist for the project."""

    # Automatically use an activated virtualenv.
    if project.s.PIPENV_USE_SYSTEM or project.virtualenv_exists:
        system_or_exists = True
    else:
        system_or_exists = system  # default to False
    if not project.pipfile_exists and deploy:
        raise exceptions.PipfileNotFound
    # Skip virtualenv creation when --system was used.
    if not system_or_exists:
        ensure_virtualenv(
            project,
            python=python,
            site_packages=site_packages,
            pypi_mirror=pypi_mirror,
        )
        if warn:
            # Warn users if they are using the wrong version of Python.
            if project.required_python_version:
                path_to_python = project._which("python") or project._which("py")
                if path_to_python and project.required_python_version not in (
                    python_version(path_to_python) or ""
                ):
                    click.echo(
                        "{}: Your Pipfile requires {} {}, "
                        "but you are using {} ({}).".format(
                            click.style("Warning", fg="red", bold=True),
                            click.style("python_version", bold=True),
                            click.style(project.required_python_version, fg="cyan"),
                            click.style(
                                python_version(path_to_python) or "unknown", fg="cyan"
                            ),
                            click.style(shorten_path(path_to_python), fg="green"),
                        ),
                        err=True,
                    )
                    click.echo(
                        "  {} and rebuilding the virtual environment "
                        "may resolve the issue.".format(
                            click.style("$ pipenv --rm", fg="green")
                        ),
                        err=True,
                    )
                    if not deploy:
                        click.echo(
                            "  {} will surely fail."
                            "".format(click.style("$ pipenv check", fg="yellow")),
                            err=True,
                        )
                    else:
                        raise exceptions.DeployException
    # Ensure the Pipfile exists.
    ensure_pipfile(
        project,
        validate=validate,
        skip_requirements=skip_requirements,
        system=system,
        categories=categories,
    )
    os.environ["PIP_PYTHON_PATH"] = project.python(system=system)


@lru_cache()
def get_setuptools_version():
    # type: () -> Optional[STRING_TYPE]

    setuptools_dist = get_distribution(Requirement("setuptools"))
    return getattr(setuptools_dist, "version", None)


def get_default_pyproject_backend():
    # type: () -> STRING_TYPE
    st_version = get_setuptools_version()
    if st_version is not None:
        parsed_st_version = parse_version(st_version)
        if parsed_st_version >= parse_version("40.8.0"):
            return "setuptools.build_meta:__legacy__"
    return "setuptools.build_meta"
