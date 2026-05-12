"""Flag-routing tests for ``do_lock`` / ``do_sync`` / ``do_uninstall`` /
``do_purge`` consuming ``RoutineContext``.

Pins the T_C.9 migration: every flag the CLI passes via
``RoutineContext.from_cli`` reaches the right downstream helper kwarg
with the right value. Heavy helpers (``venv_resolve_deps``,
``ensure_project``, ``do_init``, ``do_install_dependencies``,
``install_build_system_packages``) are mocked so the tests stay
in-process and do not touch the network / filesystem.

See ``docs/dev/initiative-c-design.md`` sections 2 and 6, and the T_C.9
task description in ``docs/dev/modernization-plan.md``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from pipenv.routines.context import RoutineContext


# ----------------------------------------------------------------------
# Signature pin tests
# ----------------------------------------------------------------------


class TestDoLockSignature:
    """The migrated do_lock has a two-parameter shape: (project, ctx)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.lock import do_lock

        sig = inspect.signature(do_lock)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestDoSyncSignature:
    """The migrated do_sync has a two-parameter shape: (project, ctx)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.sync import do_sync

        sig = inspect.signature(do_sync)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestDoUninstallSignature:
    """The migrated do_uninstall has a two-parameter shape: (project, ctx)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.uninstall import do_uninstall

        sig = inspect.signature(do_uninstall)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestDoPurgeSignature:
    """do_purge stays on its pre-migration signature.

    Per T_C.2 the migration threshold is ``> 3`` non-project params;
    ``do_purge`` has exactly 3 (``bare`` / ``downloads`` / ``allow_global``)
    and is only called internally from ``do_uninstall``. It is therefore
    deliberately *not* migrated by T_C.9.
    """

    def test_signature(self):
        import inspect

        from pipenv.routines.uninstall import do_purge

        sig = inspect.signature(do_purge)
        params = list(sig.parameters)
        assert params == ["project", "bare", "downloads", "allow_global"]


# ----------------------------------------------------------------------
# do_lock flag-routing
# ----------------------------------------------------------------------


@pytest.fixture
def lock_project_stub():
    """Minimal project stub for do_lock."""
    proj = mock.MagicMock()
    proj.settings.get.side_effect = lambda key, default=None: {
        "allow_prereleases": None,
        "use_default_constraints": True,
    }.get(key, default)
    proj.get_package_categories.return_value = ["default"]
    proj.pipfile_exists = True
    proj.parsed_pipfile = {"packages": {"requests": "*"}}
    # lockfile() returns a dict-like that supports pop and update.
    proj.lockfile.return_value = {"default": {}, "_meta": {}}
    proj.get_lockfile_meta.return_value = {}
    proj.get_lockfile_hash.return_value = "deadbeef"
    return proj


@pytest.fixture
def patch_lock_pipeline(monkeypatch):
    """Replace the heavy helpers do_lock calls."""
    install_build = mock.MagicMock()
    venv_resolve = mock.MagicMock(return_value=None)
    monkeypatch.setattr(
        "pipenv.routines.install.install_build_system_packages", install_build
    )
    monkeypatch.setattr(
        "pipenv.utils.resolver.venv_resolve_deps", venv_resolve
    )
    return {
        "install_build_system_packages": install_build,
        "venv_resolve_deps": venv_resolve,
    }


class TestDoLockFlagRouting:
    """Each ctx field routes to the expected helper kwarg."""

    def test_target_env_routes_to_resolver_and_build_system(
        self, lock_project_stub, patch_lock_pipeline
    ):
        from pipenv.routines.lock import do_lock

        ctx = RoutineContext.from_cli(
            system=True,
            pypi_mirror="https://mirror.example.org/simple",
        )
        do_lock(lock_project_stub, ctx)

        # install_build_system_packages reads system/pypi_mirror.
        ibs_kwargs = patch_lock_pipeline[
            "install_build_system_packages"
        ].call_args.kwargs
        assert ibs_kwargs["allow_global"] is True
        assert (
            ibs_kwargs["pypi_mirror"] == "https://mirror.example.org/simple"
        )

        # venv_resolve_deps gets the same target_env via kwargs.
        vrd_kwargs = patch_lock_pipeline["venv_resolve_deps"].call_args.kwargs
        assert vrd_kwargs["allow_global"] is True
        assert (
            vrd_kwargs["pypi_mirror"] == "https://mirror.example.org/simple"
        )

    def test_install_policy_flags_route_to_resolver(
        self, lock_project_stub, patch_lock_pipeline
    ):
        from pipenv.routines.lock import do_lock

        ctx = RoutineContext.from_cli(pre=True, clear=True)
        do_lock(lock_project_stub, ctx)

        vrd_kwargs = patch_lock_pipeline["venv_resolve_deps"].call_args.kwargs
        assert vrd_kwargs["pre"] is True
        assert vrd_kwargs["clear"] is True

    def test_extra_pip_args_routed_to_resolver(
        self, lock_project_stub, patch_lock_pipeline
    ):
        from pipenv.routines.lock import do_lock

        ctx = RoutineContext.from_cli(
            extra_pip_args=("--no-build-isolation",),
        )
        do_lock(lock_project_stub, ctx)

        vrd_kwargs = patch_lock_pipeline["venv_resolve_deps"].call_args.kwargs
        assert vrd_kwargs["extra_pip_args"] == ["--no-build-isolation"]

    def test_categories_routed_to_lockfile_selection(
        self, lock_project_stub, patch_lock_pipeline
    ):
        from pipenv.routines.lock import do_lock

        # Pre-populate the lockfile dict with the develop section so the
        # category-pop branch has data to consume.
        lock_project_stub.lockfile.return_value = {"develop": {}, "_meta": {}}
        ctx = RoutineContext.from_cli(categories=("dev-packages",))
        do_lock(lock_project_stub, ctx)

        # When categories supplied, get_package_categories is NOT used to
        # pick the lockfile categories.
        assert not lock_project_stub.get_package_categories.called
        # ``lockfile(categories=...)`` is invoked with the canonical
        # lockfile-section name (``develop``).
        lockfile_call = lock_project_stub.lockfile.call_args
        assert lockfile_call.kwargs["categories"] == ["develop"]

    def test_write_false_returns_lockfile(
        self, lock_project_stub, patch_lock_pipeline
    ):
        from pipenv.routines.lock import do_lock

        ctx = RoutineContext.from_cli(write=False)
        result = do_lock(lock_project_stub, ctx)

        # write=False causes do_lock to return the assembled lockfile.
        assert result is not None
        # And it does NOT write the lockfile to disk.
        assert not lock_project_stub.write_lockfile.called

    def test_write_true_writes_lockfile(
        self, lock_project_stub, patch_lock_pipeline
    ):
        from pipenv.routines.lock import do_lock

        ctx = RoutineContext.from_cli(write=True)
        result = do_lock(lock_project_stub, ctx)

        assert result is None
        assert lock_project_stub.write_lockfile.called


# ----------------------------------------------------------------------
# do_sync flag-routing
# ----------------------------------------------------------------------


@pytest.fixture
def sync_project_stub():
    proj = mock.MagicMock()
    proj.any_lockfile_exists = True
    proj.s.PIPENV_USE_SYSTEM = False
    proj.s.is_quiet.return_value = False
    return proj


@pytest.fixture
def patch_sync_pipeline(monkeypatch):
    patches: dict[str, mock.MagicMock] = {}
    for name in ("ensure_project", "do_init", "do_install_dependencies"):
        m = mock.MagicMock()
        monkeypatch.setattr(f"pipenv.routines.sync.{name}", m)
        patches[name] = m
    return patches


class TestDoSyncFlagRouting:
    """Each ctx field routes to the expected helper."""

    def test_defaults_route_to_helpers(
        self, sync_project_stub, patch_sync_pipeline
    ):
        from pipenv.routines.sync import do_sync

        ctx = RoutineContext.from_cli()
        do_sync(sync_project_stub, ctx)

        ep_kwargs = patch_sync_pipeline["ensure_project"].call_args.kwargs
        assert ep_kwargs["system"] is False
        assert ep_kwargs["python"] is None
        assert ep_kwargs["pypi_mirror"] is None
        assert ep_kwargs["lockfile_only"] is True
        assert ep_kwargs["validate"] is False

    def test_target_env_routes_to_ensure_project_and_downstream(
        self, sync_project_stub, patch_sync_pipeline
    ):
        from pipenv.routines.sync import do_sync

        ctx = RoutineContext.from_cli(
            system=True,
            python="3.12",
            pypi_mirror="https://mirror.example.org/simple",
            site_packages=True,
        )
        do_sync(sync_project_stub, ctx)

        ep_kwargs = patch_sync_pipeline["ensure_project"].call_args.kwargs
        assert ep_kwargs["system"] is True
        assert ep_kwargs["python"] == "3.12"
        assert ep_kwargs["pypi_mirror"] == "https://mirror.example.org/simple"
        assert ep_kwargs["site_packages"] is True

        # Downstream do_init / do_install_dependencies receive ctx with
        # the same target_env (allow_global defaults to system).
        di_ctx = patch_sync_pipeline["do_init"].call_args.args[1]
        assert di_ctx.target_env.system is True
        assert di_ctx.target_env.allow_global is True
        assert (
            di_ctx.target_env.pypi_mirror
            == "https://mirror.example.org/simple"
        )

        did_ctx = patch_sync_pipeline[
            "do_install_dependencies"
        ].call_args.args[1]
        assert did_ctx.target_env.system is True

    def test_sync_pins_ignore_pipfile_and_skip_lock(
        self, sync_project_stub, patch_sync_pipeline
    ):
        """do_sync collapses the T_C.7 inline bridge but must still pin
        ignore_pipfile=True and skip_lock=True for do_init /
        do_install_dependencies."""
        from pipenv.routines.sync import do_sync

        # User did not pass these — sync must inject them.
        ctx = RoutineContext.from_cli()
        do_sync(sync_project_stub, ctx)

        di_ctx = patch_sync_pipeline["do_init"].call_args.args[1]
        assert di_ctx.install_policy.ignore_pipfile is True
        assert di_ctx.install_policy.skip_lock is True

        did_ctx = patch_sync_pipeline[
            "do_install_dependencies"
        ].call_args.args[1]
        assert did_ctx.install_policy.ignore_pipfile is True
        assert did_ctx.install_policy.skip_lock is True

    def test_deploy_routes_to_ensure_project(
        self, sync_project_stub, patch_sync_pipeline
    ):
        from pipenv.routines.sync import do_sync

        ctx = RoutineContext.from_cli(deploy=True)
        do_sync(sync_project_stub, ctx)

        ep_kwargs = patch_sync_pipeline["ensure_project"].call_args.kwargs
        assert ep_kwargs["deploy"] is True

    def test_clear_routes_to_ensure_project(
        self, sync_project_stub, patch_sync_pipeline
    ):
        from pipenv.routines.sync import do_sync

        ctx = RoutineContext.from_cli(clear=True)
        do_sync(sync_project_stub, ctx)

        ep_kwargs = patch_sync_pipeline["ensure_project"].call_args.kwargs
        assert ep_kwargs["clear"] is True

    def test_dev_and_categories_route_to_downstream(
        self, sync_project_stub, patch_sync_pipeline
    ):
        from pipenv.routines.sync import do_sync

        ctx = RoutineContext.from_cli(
            dev=True,
            categories=("packages", "dev-packages"),
        )
        do_sync(sync_project_stub, ctx)

        did_ctx = patch_sync_pipeline[
            "do_install_dependencies"
        ].call_args.args[1]
        assert did_ctx.package_selection.dev is True
        assert tuple(did_ctx.package_selection.categories) == (
            "packages",
            "dev-packages",
        )

    def test_extra_pip_args_route_to_downstream(
        self, sync_project_stub, patch_sync_pipeline
    ):
        from pipenv.routines.sync import do_sync

        ctx = RoutineContext.from_cli(
            extra_pip_args=("--no-build-isolation",),
        )
        do_sync(sync_project_stub, ctx)

        did_ctx = patch_sync_pipeline[
            "do_install_dependencies"
        ].call_args.args[1]
        assert tuple(did_ctx.execution_options.extra_pip_args) == (
            "--no-build-isolation",
        )

    def test_missing_lockfile_raises(
        self, sync_project_stub, patch_sync_pipeline
    ):
        from pipenv import exceptions
        from pipenv.routines.sync import do_sync

        sync_project_stub.any_lockfile_exists = False
        ctx = RoutineContext.from_cli()
        with pytest.raises(exceptions.LockfileNotFound):
            do_sync(sync_project_stub, ctx)


# ----------------------------------------------------------------------
# do_uninstall flag-routing
# ----------------------------------------------------------------------


class TestDoUninstallFlagRouting:
    """do_uninstall reads every user-facing input from ctx."""

    def test_no_packages_raises_usage_error(self):
        from pipenv import exceptions
        from pipenv.routines.uninstall import do_uninstall

        project = mock.MagicMock()
        ctx = RoutineContext.from_cli()  # no packages, no all/all_dev
        with pytest.raises(exceptions.PipenvUsageError):
            do_uninstall(project, ctx)

    def test_all_routes_to_do_purge(self, monkeypatch):
        """When ``all=True`` is set, do_uninstall calls do_purge with
        allow_global derived from system."""
        from pipenv.routines.uninstall import do_uninstall

        project = mock.MagicMock()
        purge = mock.MagicMock()
        monkeypatch.setattr("pipenv.routines.uninstall.do_purge", purge)

        ctx = RoutineContext.from_cli(all=True, system=True)
        do_uninstall(project, ctx)

        purge_kwargs = purge.call_args.kwargs
        assert purge_kwargs["allow_global"] is True
        assert purge_kwargs["downloads"] is False
        assert purge_kwargs["bare"] is False

    def test_all_dev_iterates_dev_packages(self, monkeypatch):
        """``all_dev=True`` triggers the dev-packages-purge branch."""
        from pipenv.routines.uninstall import do_uninstall

        project = mock.MagicMock()
        project.get_pipfile_section.return_value = {"pytest": "*"}
        project.reset_category_in_pipfile.return_value = True
        # lockfile_content needs to be mutable across the routine.
        project.lockfile_content = {"develop": {"pytest": {}}}
        uninstall_env = mock.MagicMock(return_value=True)
        monkeypatch.setattr(
            "pipenv.routines.uninstall._uninstall_from_environment",
            uninstall_env,
        )

        ctx = RoutineContext.from_cli(all_dev=True)
        # all_dev path runs to completion (no sys.exit on this branch
        # before it would hit the package_args loop) — but the empty
        # package_args path WILL fall through to sys.exit. Patch it.
        with mock.patch("pipenv.routines.uninstall.sys.exit") as exit_mock:
            do_uninstall(project, ctx)
        # _uninstall_from_environment called for the single dev package.
        assert uninstall_env.called
        assert uninstall_env.call_args.kwargs["system"] is False
        exit_mock.assert_called()  # final sys.exit(int(failure))

    def test_lock_triggers_post_uninstall_lock(self, monkeypatch):
        """When ``lock=True`` is set in ctx.install_policy, the post-
        uninstall ``do_lock`` call fires with target_env propagated.
        """
        from pipenv.routines.uninstall import do_uninstall

        project = mock.MagicMock()
        project.lockfile_content = {"default": {}}
        do_lock_mock = mock.MagicMock()
        monkeypatch.setattr(
            "pipenv.routines.uninstall.do_lock", do_lock_mock
        )
        monkeypatch.setattr(
            "pipenv.routines.uninstall._uninstall_from_environment",
            mock.MagicMock(return_value=True),
        )
        monkeypatch.setattr(
            "pipenv.routines.uninstall.venv_resolve_deps",
            mock.MagicMock(return_value={}),
        )
        monkeypatch.setattr(
            "pipenv.routines.uninstall.expansive_install_req_from_line",
            mock.MagicMock(return_value=(mock.MagicMock(), None)),
        )
        project.generate_package_pipfile_entry.return_value = (
            "requests",
            "requests",
            {"version": "*"},
        )
        project.remove_package_from_pipfile.return_value = True
        project.get_pipfile_section.return_value = {}
        project.get_lockfile_meta.return_value = {}

        ctx = RoutineContext.from_cli(
            packages=("requests",),
            lock=True,
            system=True,
            pypi_mirror="https://mirror.example.org/simple",
        )
        with mock.patch("pipenv.routines.uninstall.sys.exit"):
            do_uninstall(project, ctx)

        # do_lock was invoked exactly once with (project, ctx).
        assert do_lock_mock.called
        lock_ctx = do_lock_mock.call_args.args[1]
        assert lock_ctx.target_env.system is True
        assert (
            lock_ctx.target_env.pypi_mirror
            == "https://mirror.example.org/simple"
        )
        # The recursive lock pass should NOT carry lock=True onward, to
        # avoid re-entering the post-uninstall lock branch.
        assert lock_ctx.install_policy.lock is False
