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

    The T_C.7 inline ``RoutineContext.from_cli(...)`` bridge that this
    function used to construct for its ``do_init`` / ``do_install_dependencies``
    calls collapses into a single ``dataclasses.replace`` of the
    incoming ``ctx`` so the downstream contract (``ignore_pipfile=True``,
    ``skip_lock=True``) is still pinned without re-materializing the
    whole context.
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

    # Pin the historical sync-time policy: don't validate Pipfile<->lock and
    # never re-lock. Carried via ``dataclasses.replace`` so the rest of the
    # caller-supplied ctx (target_env, dev, categories, extra_pip_args, bare)
    # flows through unchanged.
    sync_ctx = replace(
        ctx,
        install_policy=replace(
            policy,
            ignore_pipfile=True,  # Don't check if Pipfile and lock match.
            skip_lock=True,  # Don't re-lock.
        ),
    )
    do_init(project, sync_ctx)
    do_install_dependencies(project, sync_ctx, requirements_dir)
    if not exec_opts.bare and not project.s.is_quiet():
        console.print("[green]All dependencies are now up-to-date![/green]")
