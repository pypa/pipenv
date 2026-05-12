import os
from dataclasses import replace

from pipenv import exceptions
from pipenv.routines.context import RoutineContext
from pipenv.routines.install import do_init, do_install_dependencies
from pipenv.utils import console, fileutils
from pipenv.utils.project import ensure_project


def do_sync(project, ctx: RoutineContext):
    """Install packages from the lockfile into the virtualenv.

    Per T_C.9: consumes :class:`~pipenv.routines.context.RoutineContext`
    for every user-facing input (``dev`` / ``python`` / ``bare`` /
    ``clear`` / ``pypi_mirror`` / ``system`` / ``deploy`` /
    ``extra_pip_args`` / ``categories`` / ``site_packages``).

    Two distinct policies are wired below: ``do_init`` runs with
    ``ignore_pipfile=True`` + ``skip_lock=True`` (historical sync-time
    contract); ``do_install_dependencies`` runs with the caller-supplied
    policy unchanged so it reads resolved entries from the lockfile
    rather than the Pipfile.
    """
    target = ctx.target_env
    policy = ctx.install_policy
    exec_opts = ctx.execution_options

    # The lock file needs to exist because sync won't write to it.
    # Accept either Pipfile.lock or pylock.toml.
    if not project.any_lockfile_exists:
        raise exceptions.LockfileNotFound("Pipfile.lock")

    # Ensure that virtualenv is available if not system.
    # sync only needs the lockfile, so skip Pipfile creation.
    ensure_project(
        project,
        python=target.python,
        validate=False,
        system=target.system,
        deploy=policy.deploy,
        pypi_mirror=target.pypi_mirror,
        clear=policy.clear,
        site_packages=target.site_packages,
        lockfile_only=True,
    )

    # Install everything.
    requirements_dir = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    if target.system:
        project.s.PIPENV_USE_SYSTEM = True
        os.environ["PIPENV_USE_SYSTEM"] = "1"

    # ``do_init`` gets the historical sync-time pin (don't validate
    # Pipfile<->lock; don't re-lock). ``do_install_dependencies`` MUST
    # keep ``skip_lock=False`` so it reads resolved entries from the
    # lockfile — passing ``skip_lock=True`` here drives it through
    # ``install_req_from_pipfile``, which mangles file:// URLs, extras
    # on URL packages, and editable VCS specs.
    init_ctx = replace(
        ctx,
        install_policy=replace(
            policy,
            ignore_pipfile=True,
            skip_lock=True,
        ),
    )
    do_init(project, init_ctx)
    do_install_dependencies(project, ctx, requirements_dir)
    if not exec_opts.bare and not project.s.is_quiet():
        console.print("[green]All dependencies are now up-to-date![/green]")
