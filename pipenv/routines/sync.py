import os

from pipenv import exceptions
from pipenv.routines.context import RoutineContext
from pipenv.routines.install import do_init, do_install_dependencies
from pipenv.utils import console, fileutils
from pipenv.utils.project import ensure_project


def do_sync(
    project,
    dev=False,
    python=None,
    bare=False,
    clear=False,
    pypi_mirror=None,
    system=False,
    deploy=False,
    extra_pip_args=None,
    categories=None,
    site_packages=False,
):
    # The lock file needs to exist because sync won't write to it.
    # Accept either Pipfile.lock or pylock.toml.
    if not project.any_lockfile_exists:
        raise exceptions.LockfileNotFound("Pipfile.lock")

    # Ensure that virtualenv is available if not system.
    # sync only needs the lockfile, so skip Pipfile creation.
    ensure_project(
        project,
        python=python,
        validate=False,
        system=system,
        deploy=deploy,
        pypi_mirror=pypi_mirror,
        clear=clear,
        site_packages=site_packages,
        lockfile_only=True,
    )

    # Install everything.
    requirements_dir = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    if system:
        project.s.PIPENV_USE_SYSTEM = True
        os.environ["PIPENV_USE_SYSTEM"] = "1"

    # T_C.7 migrated do_init / do_install_dependencies to RoutineContext.
    # do_sync itself is migrated by T_C.9; until then, build a ctx at the
    # call boundary so behaviour is preserved exactly.
    sync_ctx = RoutineContext.from_cli(
        system=system,
        pypi_mirror=pypi_mirror,
        deploy=deploy,
        ignore_pipfile=True,  # Don't check if Pipfile and lock match.
        skip_lock=True,  # Don't re-lock.
        dev=dev,
        categories=tuple(categories) if categories else (),
        extra_pip_args=tuple(extra_pip_args) if extra_pip_args else (),
        bare=bare,
    )
    do_init(project, sync_ctx)
    do_install_dependencies(project, sync_ctx, requirements_dir)
    if not bare and not project.s.is_quiet():
        console.print("[green]All dependencies are now up-to-date![/green]")
