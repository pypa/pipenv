"""Flag-routing tests for ``do_install`` consuming ``RoutineContext``.

Pins the T_C.5 migration: every flag the CLI passes via
``RoutineContext.from_cli`` must reach the right helper kwarg with the
right value. Helpers are mocked so the tests stay in-process and do
not touch the network / filesystem (apart from the temp-dir scaffold
that ``do_install`` creates unconditionally via ``fileutils``).

See ``docs/dev/initiative-c-design.md`` sections 2 and 6, and the
T_C.5 task description in ``docs/dev/modernization-plan.md``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from pipenv.routines.context import RoutineContext


@pytest.fixture
def project_stub():
    """Minimal project stub: only attributes ``do_install`` interrogates.

    The mocked helpers below absorb everything else, so all
    ``do_install`` needs from ``project`` is settings hooks for failure
    handlers (none triggered in the happy path).
    """
    proj = mock.MagicMock()
    proj.s.PIPENV_USE_SYSTEM = False
    proj.pipfile.exists = True
    return proj


@pytest.fixture
def patch_install_pipeline(monkeypatch):
    """Replace every helper ``do_install`` calls with a MagicMock.

    Also patches ``sys.exit`` so the routine returns normally instead of
    terminating the test process. Returns the dict of patched mocks for
    assertions.
    """
    patches: dict[str, mock.MagicMock] = {}
    for name in (
        "ensure_project",
        "do_install_validations",
        "do_init",
        "handle_new_packages",
        "do_install_dependencies",
    ):
        m = mock.MagicMock()
        # handle_new_packages historically returns (new_packages, _).
        if name == "handle_new_packages":
            m.return_value = ([], False)
        monkeypatch.setattr(f"pipenv.routines.install.{name}", m)
        patches[name] = m
    # Don't let sys.exit terminate pytest.
    monkeypatch.setattr("pipenv.routines.install.sys.exit", mock.MagicMock())
    return patches


class TestDoInstallSignature:
    """The migrated do_install has a two-parameter shape."""

    def test_signature_is_project_then_ctx(self):
        import inspect

        from pipenv.routines.install import do_install

        sig = inspect.signature(do_install)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestDoInstallFlagRouting:
    """Each field of ``ctx`` routes to the expected helper kwarg."""

    def test_defaults_route_to_packages_category(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli()
        do_install(project_stub, ctx)

        # ensure_project receives the defaults.
        ep = patch_install_pipeline["ensure_project"]
        ep_kwargs = ep.call_args.kwargs
        assert ep_kwargs["system"] is False
        assert ep_kwargs["python"] is None
        assert ep_kwargs["pypi_mirror"] is None
        assert ep_kwargs["site_packages"] is None
        assert ep_kwargs["deploy"] is False
        assert ep_kwargs["lockfile_only"] is False
        # Default category is "packages" when dev=False and user passed none.
        assert ep_kwargs["pipfile_categories"] == ["packages"]

    def test_dev_defaults_to_dev_packages_category(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(dev=True)
        do_install(project_stub, ctx)

        ep = patch_install_pipeline["ensure_project"]
        assert ep.call_args.kwargs["pipfile_categories"] == ["dev-packages"]

        # Post T_C.7: do_install_dependencies receives a context whose
        # package_selection carries both categories under --dev and dev=True.
        did = patch_install_pipeline["do_install_dependencies"]
        deps_ctx = did.call_args.args[1]
        assert deps_ctx.package_selection.categories == (
            "packages",
            "dev-packages",
        )
        assert deps_ctx.package_selection.dev is True

    def test_explicit_categories_override_default(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(categories=("custom-cat",))
        do_install(project_stub, ctx)

        ep = patch_install_pipeline["ensure_project"]
        assert ep.call_args.kwargs["pipfile_categories"] == ["custom-cat"]

    def test_target_env_fields_route_to_helpers(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(
            system=True,
            python="3.12",
            pypi_mirror="https://mirror.example.org/simple",
            site_packages=True,
        )
        do_install(project_stub, ctx)

        ep_kwargs = patch_install_pipeline["ensure_project"].call_args.kwargs
        assert ep_kwargs["system"] is True
        assert ep_kwargs["python"] == "3.12"
        assert ep_kwargs["pypi_mirror"] == "https://mirror.example.org/simple"
        assert ep_kwargs["site_packages"] is True

        # Post T_C.7: do_init takes (project, ctx); target_env fields
        # travel via ctx.target_env. allow_global defaults to system.
        di_ctx = patch_install_pipeline["do_init"].call_args.args[1]
        assert di_ctx.target_env.system is True
        assert di_ctx.target_env.allow_global is True
        assert (
            di_ctx.target_env.pypi_mirror == "https://mirror.example.org/simple"
        )

    def test_install_policy_fields_route_to_helpers(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(
            pre=True,
            deploy=True,
            skip_lock=True,
            ignore_pipfile=True,
        )
        do_install(project_stub, ctx)

        # ensure_project sees deploy and ignore_pipfile-as-lockfile_only.
        ep = patch_install_pipeline["ensure_project"].call_args.kwargs
        assert ep["deploy"] is True
        assert ep["lockfile_only"] is True

        # Post T_C.7: do_install_validations / do_init / do_install_dependencies
        # all take (project, ctx, ...) — every install_policy field travels
        # via ctx.install_policy.
        div_ctx = patch_install_pipeline["do_install_validations"].call_args.args[1]
        assert div_ctx.install_policy.pre is True
        assert div_ctx.install_policy.deploy is True
        assert div_ctx.install_policy.skip_lock is True
        assert div_ctx.install_policy.ignore_pipfile is True

        di_ctx = patch_install_pipeline["do_init"].call_args.args[1]
        assert di_ctx.install_policy.deploy is True
        assert di_ctx.install_policy.skip_lock is True
        assert di_ctx.install_policy.ignore_pipfile is True

        # deploy=True suppresses handle_new_packages entirely.
        assert not patch_install_pipeline["handle_new_packages"].called

        # do_install_dependencies sees skip_lock via ctx.install_policy.
        did_ctx = patch_install_pipeline["do_install_dependencies"].call_args.args[1]
        assert did_ctx.install_policy.skip_lock is True

    def test_deploy_false_runs_handle_new_packages(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(
            packages=("requests",),
            index="https://pypi.example.org/simple",
        )
        do_install(project_stub, ctx)

        hnp = patch_install_pipeline["handle_new_packages"]
        assert hnp.called
        # Post T_C.6: handle_new_packages takes (project, ctx, *,
        # perform_upgrades). The user-facing fields (packages, index,
        # categories) travel via ctx.
        positional = hnp.call_args.args
        assert positional[0] is project_stub
        hnp_ctx = positional[1]
        assert hnp_ctx.package_selection.packages == ("requests",)
        assert hnp_ctx.package_selection.editable_packages == ()
        assert hnp_ctx.package_selection.index == "https://pypi.example.org/simple"
        assert hnp_ctx.package_selection.categories == ("packages",)
        kwargs = hnp.call_args.kwargs
        assert kwargs["perform_upgrades"] is True  # skip_lock=False default

    def test_skip_lock_disables_upgrades_in_handle_new_packages(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(
            packages=("requests",),
            skip_lock=True,
        )
        do_install(project_stub, ctx)

        hnp = patch_install_pipeline["handle_new_packages"].call_args.kwargs
        assert hnp["perform_upgrades"] is False

    def test_extra_pip_args_threaded_through(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(
            packages=("requests",),
            extra_pip_args=("--no-build-isolation",),
        )
        do_install(project_stub, ctx)

        # Post T_C.6: handle_new_packages reads extra_pip_args via ctx.
        hnp_ctx = patch_install_pipeline["handle_new_packages"].call_args.args[1]
        assert hnp_ctx.execution_options.extra_pip_args == ("--no-build-isolation",)
        # Post T_C.7: do_install_dependencies reads extra_pip_args via ctx.
        did_ctx = patch_install_pipeline["do_install_dependencies"].call_args.args[1]
        assert did_ctx.execution_options.extra_pip_args == (
            "--no-build-isolation",
        )

    def test_requirementstxt_routed_to_validations(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(requirementstxt="reqs.txt")
        do_install(project_stub, ctx)

        # Post T_C.7: do_install_validations takes (project, ctx, requirements_dir);
        # requirementstxt travels via ctx.package_selection.
        div_ctx = patch_install_pipeline["do_install_validations"].call_args.args[1]
        assert div_ctx.package_selection.requirementstxt == "reqs.txt"

    def test_editable_packages_are_normalised(
        self, project_stub, patch_install_pipeline
    ):
        """``do_install`` runs editable paths through
        ``normalize_editable_path_for_pip`` before handing them to
        ``handle_new_packages``. The exact transform is the
        normaliser's contract; here we only assert the helper sees a
        non-empty editable list via ``ctx.package_selection``.
        """
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(editable_packages=("./local-pkg",))
        do_install(project_stub, ctx)

        # Post T_C.6: editables travel via ctx.package_selection.
        hnp_ctx = patch_install_pipeline["handle_new_packages"].call_args.args[1]
        editables = hnp_ctx.package_selection.editable_packages
        assert editables  # non-empty
        assert len(editables) == 1


class TestHandleNewPackagesSignature:
    """Post T_C.6 the helper takes (project, ctx, *, perform_upgrades)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import handle_new_packages

        sig = inspect.signature(handle_new_packages)
        params = list(sig.parameters)
        assert params == ["project", "ctx", "perform_upgrades"]
        assert (
            sig.parameters["perform_upgrades"].kind
            == inspect.Parameter.KEYWORD_ONLY
        )


class TestHandleLockfileSignature:
    """Post T_C.6 the helper takes (project, ctx)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import handle_lockfile

        sig = inspect.signature(handle_lockfile)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestDoInitSignature:
    """Post T_C.7 the helper takes (project, ctx)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import do_init

        sig = inspect.signature(do_init)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestDoInstallValidationsSignature:
    """Post T_C.7 the helper takes (project, ctx, requirements_directory)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import do_install_validations

        sig = inspect.signature(do_install_validations)
        params = list(sig.parameters)
        assert params == ["project", "ctx", "requirements_directory"]


class TestDoInstallDependenciesSignature:
    """Post T_C.7 the helper takes (project, ctx, requirements_dir)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import do_install_dependencies

        sig = inspect.signature(do_install_dependencies)
        params = list(sig.parameters)
        assert params == ["project", "ctx", "requirements_dir"]


class TestHandleOutdatedLockfileSignature:
    """Post T_C.7 the helper takes (project, ctx, *, old_hash, new_hash)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import handle_outdated_lockfile

        sig = inspect.signature(handle_outdated_lockfile)
        params = list(sig.parameters)
        assert params == ["project", "ctx", "old_hash", "new_hash"]
        assert (
            sig.parameters["old_hash"].kind == inspect.Parameter.KEYWORD_ONLY
        )
        assert (
            sig.parameters["new_hash"].kind == inspect.Parameter.KEYWORD_ONLY
        )


class TestHandleMissingLockfileSignature:
    """Post T_C.7 the helper takes (project, ctx)."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import handle_missing_lockfile

        sig = inspect.signature(handle_missing_lockfile)
        params = list(sig.parameters)
        assert params == ["project", "ctx"]


class TestBatchInstallSignature:
    """Post T_C.7 the helper takes a ctx plus only data-flow args.

    Per design doc section 3, ``deps_list`` / ``lockfile_section`` / ``procs`` /
    ``requirements_dir`` / ``sequential_deps`` are batch-install bookkeeping
    and stay as direct parameters rather than going on ``RoutineContext``.
    """

    def test_signature(self):
        import inspect

        from pipenv.routines.install import batch_install

        sig = inspect.signature(batch_install)
        params = list(sig.parameters)
        assert params == [
            "project",
            "ctx",
            "deps_list",
            "lockfile_section",
            "procs",
            "requirements_dir",
            "sequential_deps",
        ]
        assert (
            sig.parameters["sequential_deps"].kind
            == inspect.Parameter.KEYWORD_ONLY
        )


class TestBatchInstallIterationSignature:
    """Post T_C.7 the helper takes a ctx plus only data-flow args."""

    def test_signature(self):
        import inspect

        from pipenv.routines.install import batch_install_iteration

        sig = inspect.signature(batch_install_iteration)
        params = list(sig.parameters)
        assert params == [
            "project",
            "ctx",
            "deps_to_install",
            "sources",
            "procs",
            "requirements_dir",
        ]
