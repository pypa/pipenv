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
    proj.pipfile_exists = True
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

        # And do_install_dependencies receives BOTH categories under --dev.
        did = patch_install_pipeline["do_install_dependencies"]
        assert did.call_args.kwargs["categories"] == ["packages", "dev-packages"]
        assert did.call_args.kwargs["dev"] is True

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

        # do_init mirrors system through to allow_global.
        di_kwargs = patch_install_pipeline["do_init"].call_args.kwargs
        assert di_kwargs["system"] is True
        assert di_kwargs["allow_global"] is True
        assert di_kwargs["pypi_mirror"] == "https://mirror.example.org/simple"

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

        # do_install_validations sees all four.
        div = patch_install_pipeline["do_install_validations"].call_args.kwargs
        assert div["pre"] is True
        assert div["deploy"] is True
        assert div["skip_lock"] is True
        assert div["ignore_pipfile"] is True

        # do_init sees deploy / skip_lock / ignore_pipfile.
        di = patch_install_pipeline["do_init"].call_args.kwargs
        assert di["deploy"] is True
        assert di["skip_lock"] is True
        assert di["ignore_pipfile"] is True

        # deploy=True suppresses handle_new_packages entirely.
        assert not patch_install_pipeline["handle_new_packages"].called

        # do_install_dependencies sees skip_lock.
        did = patch_install_pipeline["do_install_dependencies"].call_args.kwargs
        assert did["skip_lock"] is True

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
        # packages and editables come through as positional args 2 and 3
        # in the current handle_new_packages signature.
        positional = hnp.call_args.args
        assert positional[1] == ["requests"]
        assert positional[2] == []
        kwargs = hnp.call_args.kwargs
        assert kwargs["index"] == "https://pypi.example.org/simple"
        assert kwargs["perform_upgrades"] is True  # skip_lock=False default
        assert kwargs["pipfile_categories"] == ["packages"]

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

        hnp = patch_install_pipeline["handle_new_packages"].call_args.kwargs
        did = patch_install_pipeline["do_install_dependencies"].call_args.kwargs
        assert hnp["extra_pip_args"] == ["--no-build-isolation"]
        assert did["extra_pip_args"] == ["--no-build-isolation"]

    def test_requirementstxt_routed_to_validations(
        self, project_stub, patch_install_pipeline
    ):
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(requirementstxt="reqs.txt")
        do_install(project_stub, ctx)

        div = patch_install_pipeline["do_install_validations"].call_args.kwargs
        assert div["requirementstxt"] == "reqs.txt"

    def test_editable_packages_are_normalised(
        self, project_stub, patch_install_pipeline
    ):
        """``do_install`` runs editable paths through
        ``normalize_editable_path_for_pip`` before handing them to
        ``handle_new_packages``. The exact transform is the
        normaliser's contract; here we only assert the helper is
        invoked with a non-empty editable list when the user passed
        editables in.
        """
        from pipenv.routines.install import do_install

        ctx = RoutineContext.from_cli(editable_packages=("./local-pkg",))
        do_install(project_stub, ctx)

        hnp = patch_install_pipeline["handle_new_packages"].call_args
        # positional[2] is the editable_packages list.
        editables = hnp.args[2]
        assert editables  # non-empty
        assert len(editables) == 1
