"""Flag-routing tests for ``do_update`` consuming ``RoutineContext``.

Pins the T_C.8 migration: every flag the CLI passes via
``RoutineContext.from_cli`` must reach the right helper kwarg with the
right value. Helpers (``do_sync``, ``upgrade``, ``do_outdated``) are
mocked so the tests stay in-process and do not touch the network /
filesystem.

See ``docs/dev/initiative-c-design.md`` sections 2 and 6, and the
T_C.8 task description in ``docs/dev/modernization-plan.md``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from pipenv.routines.context import RoutineContext


@pytest.fixture
def project_stub():
    """Minimal project stub: only attributes ``do_update`` interrogates."""
    proj = mock.MagicMock()
    proj.s.PIPENV_USE_SYSTEM = False
    proj.any_lockfile_exists = True
    return proj


@pytest.fixture
def patch_update_pipeline(monkeypatch):
    """Replace every helper ``do_update`` calls with a MagicMock.

    Returns the dict of patched mocks for assertions.
    """
    patches: dict[str, mock.MagicMock] = {}
    for name in ("ensure_project", "do_sync", "upgrade", "do_outdated"):
        m = mock.MagicMock()
        monkeypatch.setattr(f"pipenv.routines.update.{name}", m)
        patches[name] = m
    return patches


class TestDoUpdateSignature:
    """The migrated do_update has a two-parameter shape."""

    def test_signature_is_project_then_ctx(self):
        import inspect

        from pipenv.routines.update import do_update

        sig = inspect.signature(do_update)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestProcessPackageArgsSignature:
    """Post T_C.8 the helper takes (project, ctx, *, ...) keyword-only."""

    def test_signature(self):
        import inspect

        from pipenv.routines.update import _process_package_args

        sig = inspect.signature(_process_package_args)
        params = list(sig.parameters)
        assert params == [
            "project",
            "ctx",
            "package_args",
            "pipfile_category",
            "index_name",
            "reverse_deps",
            "explicitly_requested",
            "category",
            "has_package_args",
            "requested_packages",
        ]
        # Everything after ctx is keyword-only.
        for name in params[2:]:
            assert (
                sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
            ), f"{name} must be keyword-only"


class TestResolveAndUpdateLockfileSignature:
    """Post T_C.8 the helper takes (project, ctx, *, ...) keyword-only."""

    def test_signature(self):
        import inspect

        from pipenv.routines.update import _resolve_and_update_lockfile

        sig = inspect.signature(_resolve_and_update_lockfile)
        params = list(sig.parameters)
        assert params == [
            "project",
            "ctx",
            "requested_packages",
            "pipfile_category",
            "category",
            "package_args",
            "lockfile",
            "resolved_default_deps",
        ]
        # Everything after ctx is keyword-only.
        for name in params[2:]:
            assert (
                sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
            ), f"{name} must be keyword-only"


class TestDoUpdateFlagRouting:
    """Each field of ``ctx`` routes to the expected helper kwarg."""

    def test_defaults_route_to_ensure_project_and_upgrade(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli()
        do_update(project_stub, ctx)

        ep = patch_update_pipeline["ensure_project"].call_args.kwargs
        assert ep["system"] is False
        assert ep["python"] is None
        assert ep["pypi_mirror"] is None
        assert ep["site_packages"] is None
        assert ep["clear"] is False
        # warn=(not quiet), default quiet=False -> warn=True
        assert ep["warn"] is True

        # outdated defaults to False -> upgrade runs, do_outdated skipped.
        assert patch_update_pipeline["upgrade"].called
        assert not patch_update_pipeline["do_outdated"].called

        upgrade_kwargs = patch_update_pipeline["upgrade"].call_args.kwargs
        assert upgrade_kwargs["pre"] is False
        assert upgrade_kwargs["system"] is False
        assert upgrade_kwargs["packages"] == []
        assert upgrade_kwargs["editable_packages"] == []
        assert upgrade_kwargs["pypi_mirror"] is None
        assert upgrade_kwargs["categories"] is None
        assert upgrade_kwargs["index_url"] is None
        assert upgrade_kwargs["dev"] is False
        assert upgrade_kwargs["lock_only"] is False
        # extra_pip_args defaults to () -> None passed through
        assert upgrade_kwargs["extra_pip_args"] is None

    def test_target_env_fields_route_to_helpers(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(
            system=True,
            python="3.12",
            pypi_mirror="https://mirror.example.org/simple",
            site_packages=True,
        )
        do_update(project_stub, ctx)

        ep = patch_update_pipeline["ensure_project"].call_args.kwargs
        assert ep["system"] is True
        assert ep["python"] == "3.12"
        assert ep["pypi_mirror"] == "https://mirror.example.org/simple"
        assert ep["site_packages"] is True

        # do_sync gets sandwiched around upgrade.
        sync_kwargs = patch_update_pipeline["do_sync"].call_args.kwargs
        assert sync_kwargs["system"] is True
        assert sync_kwargs["python"] == "3.12"
        assert sync_kwargs["pypi_mirror"] == "https://mirror.example.org/simple"

        up_kwargs = patch_update_pipeline["upgrade"].call_args.kwargs
        assert up_kwargs["system"] is True
        assert up_kwargs["pypi_mirror"] == "https://mirror.example.org/simple"

    def test_install_policy_fields_route_to_helpers(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(
            pre=True,
            clear=True,
            lock_only=True,
        )
        do_update(project_stub, ctx)

        ep = patch_update_pipeline["ensure_project"].call_args.kwargs
        assert ep["clear"] is True

        up_kwargs = patch_update_pipeline["upgrade"].call_args.kwargs
        assert up_kwargs["pre"] is True
        assert up_kwargs["lock_only"] is True

        sync_kwargs = patch_update_pipeline["do_sync"].call_args.kwargs
        assert sync_kwargs["clear"] is True

    def test_packages_and_editables_routed_to_upgrade(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(
            packages=("requests==2.31.0", ""),  # empty filtered out
            editable_packages=("./local-pkg", ""),
            index="https://pypi.example.org/simple",
        )
        do_update(project_stub, ctx)

        up_kwargs = patch_update_pipeline["upgrade"].call_args.kwargs
        assert up_kwargs["packages"] == ["requests==2.31.0"]
        assert up_kwargs["editable_packages"] == ["./local-pkg"]
        assert up_kwargs["index_url"] == "https://pypi.example.org/simple"

    def test_categories_routed_to_helpers(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(
            categories=("packages", "docs"),
            dev=True,
        )
        do_update(project_stub, ctx)

        # categories is normalised list inside do_update.
        up_kwargs = patch_update_pipeline["upgrade"].call_args.kwargs
        assert up_kwargs["categories"] == ["packages", "docs"]
        assert up_kwargs["dev"] is True

        sync_kwargs = patch_update_pipeline["do_sync"].call_args.kwargs
        assert sync_kwargs["categories"] == ["packages", "docs"]
        assert sync_kwargs["dev"] is True

    def test_extra_pip_args_routed_to_upgrade_and_sync(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(
            extra_pip_args=("--no-build-isolation",),
        )
        do_update(project_stub, ctx)

        up_kwargs = patch_update_pipeline["upgrade"].call_args.kwargs
        assert up_kwargs["extra_pip_args"] == ["--no-build-isolation"]

        sync_kwargs = patch_update_pipeline["do_sync"].call_args.kwargs
        assert sync_kwargs["extra_pip_args"] == ["--no-build-isolation"]

    def test_quiet_inverts_warn_flag(self, project_stub, patch_update_pipeline):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(quiet=True)
        do_update(project_stub, ctx)

        ep = patch_update_pipeline["ensure_project"].call_args.kwargs
        assert ep["warn"] is False

    def test_bare_routed_to_sync(self, project_stub, patch_update_pipeline):
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(bare=True)
        do_update(project_stub, ctx)

        sync_kwargs = patch_update_pipeline["do_sync"].call_args.kwargs
        assert sync_kwargs["bare"] is True

    def test_dry_run_routes_to_do_outdated(
        self, project_stub, patch_update_pipeline
    ):
        """``--dry-run`` / ``--outdated`` collapse to a single intent and
        select ``do_outdated`` over the sync+upgrade path."""
        from pipenv.routines.update import do_update

        ctx = RoutineContext.from_cli(
            dry_run=True,
            pre=True,
            clear=True,
            pypi_mirror="https://mirror.example.org/simple",
        )
        do_update(project_stub, ctx)

        # do_outdated took the call, upgrade did not.
        assert patch_update_pipeline["do_outdated"].called
        assert not patch_update_pipeline["upgrade"].called
        # do_sync should not be called when outdated path is taken.
        assert not patch_update_pipeline["do_sync"].called

        outdated_kwargs = patch_update_pipeline["do_outdated"].call_args.kwargs
        assert outdated_kwargs["clear"] is True
        assert outdated_kwargs["pre"] is True
        assert (
            outdated_kwargs["pypi_mirror"]
            == "https://mirror.example.org/simple"
        )

    def test_pre_sync_skipped_when_no_lockfile(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        project_stub.any_lockfile_exists = False
        ctx = RoutineContext.from_cli()
        do_update(project_stub, ctx)

        # No pre-sync call; only the post-upgrade sync should fire.
        # do_sync is called exactly once (the post-upgrade one).
        assert patch_update_pipeline["do_sync"].call_count == 1

    def test_use_system_env_flag_promotes_system(
        self, project_stub, patch_update_pipeline
    ):
        from pipenv.routines.update import do_update

        project_stub.s.PIPENV_USE_SYSTEM = True
        ctx = RoutineContext.from_cli(system=False)
        do_update(project_stub, ctx)

        ep = patch_update_pipeline["ensure_project"].call_args.kwargs
        assert ep["system"] is True
        up_kwargs = patch_update_pipeline["upgrade"].call_args.kwargs
        assert up_kwargs["system"] is True
