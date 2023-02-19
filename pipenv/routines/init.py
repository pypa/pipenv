import os
import sys

from pipenv import exceptions
from pipenv.utils.pipfile import ensure_pipfile
from pipenv.utils.virtualenv import do_create_virtualenv, cleanup_virtualenv
from pipenv.routines.install import do_install_dependencies
from pipenv.routines.lock import do_lock
from pipenv.vendor import vistir, click


def do_init(
    project,
    dev=False,
    dev_only=False,
    allow_global=False,
    ignore_pipfile=False,
    skip_lock=False,
    system=False,
    deploy=False,
    pre=False,
    keep_outdated=False,
    requirements_dir=None,
    pypi_mirror=None,
    extra_pip_args=None,
    categories=None,
):
    """Executes the init functionality."""
    python = None
    if project.s.PIPENV_PYTHON is not None:
        python = project.s.PIPENV_PYTHON
    elif project.s.PIPENV_DEFAULT_PYTHON_VERSION is not None:
        python = project.s.PIPENV_DEFAULT_PYTHON_VERSION
    if categories is None:
        categories = []

    if not system and not project.s.PIPENV_USE_SYSTEM:
        if not project.virtualenv_exists:
            try:
                do_create_virtualenv(project, python=python, pypi_mirror=pypi_mirror)
            except KeyboardInterrupt:
                cleanup_virtualenv(project, bare=False)
                sys.exit(1)
    # Ensure the Pipfile exists.
    if not deploy:
        ensure_pipfile(project, system=system)
    if not requirements_dir:
        requirements_dir = vistir.path.create_tracked_tempdir(
            suffix="-requirements", prefix="pipenv-"
        )
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if (project.lockfile_exists and not ignore_pipfile) and not skip_lock:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            if deploy:
                click.secho(
                    "Your Pipfile.lock ({}) is out of date. Expected: ({}).".format(
                        old_hash[-6:], new_hash[-6:]
                    ),
                    fg="red",
                )
                raise exceptions.DeployException
            elif (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
                click.secho(
                    "Pipfile.lock ({}) out of date, but installation "
                    "uses {} re-building lockfile must happen in "
                    "isolation. Please rebuild lockfile in a virtualenv. "
                    "Continuing anyway...".format(old_hash[-6:], "--system"),
                    fg="yellow",
                    err=True,
                )
            else:
                if old_hash:
                    msg = "Pipfile.lock ({0}) out of date, updating to ({1})..."
                else:
                    msg = "Pipfile.lock is corrupt, replaced with ({1})..."
                click.secho(
                    msg.format(old_hash[-6:], new_hash[-6:]),
                    fg="yellow",
                    bold=True,
                    err=True,
                )
                do_lock(
                    project,
                    system=system,
                    pre=pre,
                    keep_outdated=keep_outdated,
                    write=True,
                    pypi_mirror=pypi_mirror,
                    categories=categories,
                )
    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists and not skip_lock:
        # Unless we're in a virtualenv not managed by pipenv, abort if we're
        # using the system's python.
        if (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
            raise exceptions.PipenvOptionsError(
                "--system",
                "--system is intended to be used for Pipfile installation, "
                "not installation of specific packages. Aborting.\n"
                "See also: --deploy flag.",
            )
        else:
            click.secho(
                "Pipfile.lock not found, creating...",
                bold=True,
                err=True,
            )
            do_lock(
                project,
                system=system,
                pre=pre,
                keep_outdated=keep_outdated,
                write=True,
                pypi_mirror=pypi_mirror,
                categories=categories,
            )
    do_install_dependencies(
        project,
        dev=dev,
        dev_only=dev_only,
        allow_global=allow_global,
        skip_lock=skip_lock,
        requirements_dir=requirements_dir,
        pypi_mirror=pypi_mirror,
        extra_pip_args=extra_pip_args,
        categories=categories,
    )

    # Hint the user what to do to activate the virtualenv.
    if not allow_global and not deploy and "PIPENV_ACTIVE" not in os.environ:
        click.echo(
            "To activate this project's virtualenv, run {}.\n"
            "Alternatively, run a command "
            "inside the virtualenv with {}.".format(
                click.style("pipenv shell", fg="yellow"),
                click.style("pipenv run", fg="yellow"),
            )
        )
