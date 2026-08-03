"""Tests for pipenv.routines.context — the additive RoutineContext scaffold.

Covers construction, frozen-ness, dataclasses.replace propagation through
nested types, from_cli defaults / keyword-only enforcement, and sequence
coercion (list -> tuple). Pins the contract that T_C.5+ migrations will
lean on.

See docs/dev/initiative-c-design.md sections 2 and 9.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from pipenv.routines.context import (
    ExecutionOptions,
    InstallPolicy,
    PackageSelection,
    RoutineContext,
    TargetEnv,
)


class TestConstructionDefaults:
    """Each nested dataclass and RoutineContext instantiates with defaults."""

    def test_target_env_defaults(self):
        env = TargetEnv()
        assert env.system is False
        assert env.allow_global is False
        assert env.python is None
        assert env.pypi_mirror is None
        assert env.site_packages is None

    def test_install_policy_defaults(self):
        policy = InstallPolicy()
        assert policy.pre is False
        assert policy.deploy is False
        assert policy.skip_lock is False
        assert policy.ignore_pipfile is False
        assert policy.clear is False
        assert policy.lock_only is False
        assert policy.lock is False
        assert policy.dry_run is False

    def test_package_selection_defaults(self):
        sel = PackageSelection()
        assert sel.packages == ()
        assert sel.editable_packages == ()
        assert sel.categories == ()
        assert sel.dev is False
        assert sel.dev_only is False
        assert sel.all is False
        assert sel.all_dev is False
        assert sel.index is None
        assert sel.index_name is None
        assert sel.requirementstxt is None

    def test_execution_options_defaults(self):
        opts = ExecutionOptions()
        assert opts.extra_pip_args == ()
        assert opts.requirements_directory is None
        assert opts.no_deps is False
        assert opts.ignore_hashes is False
        assert opts.use_pep517 is True
        assert opts.bare is False
        assert opts.quiet is False
        assert opts.verbose is False
        assert opts.write is True

    def test_routine_context_defaults(self):
        ctx = RoutineContext()
        assert isinstance(ctx.target_env, TargetEnv)
        assert isinstance(ctx.install_policy, InstallPolicy)
        assert isinstance(ctx.package_selection, PackageSelection)
        assert isinstance(ctx.execution_options, ExecutionOptions)
        # The default factories must produce *fresh* instances, not share
        # them across RoutineContext() calls.
        ctx_other = RoutineContext()
        assert ctx.target_env == ctx_other.target_env


class TestConstructionNonDefaults:
    """Non-default values flow through construction correctly."""

    def test_target_env_non_defaults(self):
        env = TargetEnv(
            system=True,
            allow_global=True,
            python="3.12",
            pypi_mirror="https://mirror.example.org/simple",
            site_packages=True,
        )
        assert env.system is True
        assert env.allow_global is True
        assert env.python == "3.12"
        assert env.pypi_mirror == "https://mirror.example.org/simple"
        assert env.site_packages is True

    def test_package_selection_non_defaults(self):
        sel = PackageSelection(
            packages=("requests",),
            editable_packages=("./local",),
            categories=("dev-packages",),
            dev=True,
            index="https://pypi.org/simple",
        )
        assert sel.packages == ("requests",)
        assert sel.editable_packages == ("./local",)
        assert sel.categories == ("dev-packages",)
        assert sel.dev is True
        assert sel.index == "https://pypi.org/simple"

    def test_routine_context_with_nested_values(self):
        ctx = RoutineContext(
            target_env=TargetEnv(system=True),
            install_policy=InstallPolicy(skip_lock=True, pre=True),
        )
        assert ctx.target_env.system is True
        assert ctx.install_policy.skip_lock is True
        assert ctx.install_policy.pre is True
        # Unspecified nested defaults to its own zero-value.
        assert ctx.package_selection.packages == ()


class TestFrozenness:
    """Attempting to mutate any field raises FrozenInstanceError."""

    def test_target_env_is_frozen(self):
        env = TargetEnv()
        with pytest.raises(FrozenInstanceError):
            env.system = True  # type: ignore[misc]

    def test_install_policy_is_frozen(self):
        policy = InstallPolicy()
        with pytest.raises(FrozenInstanceError):
            policy.skip_lock = True  # type: ignore[misc]

    def test_package_selection_is_frozen(self):
        sel = PackageSelection()
        with pytest.raises(FrozenInstanceError):
            sel.packages = ("requests",)  # type: ignore[misc]

    def test_execution_options_is_frozen(self):
        opts = ExecutionOptions()
        with pytest.raises(FrozenInstanceError):
            opts.bare = True  # type: ignore[misc]

    def test_routine_context_is_frozen(self):
        ctx = RoutineContext()
        with pytest.raises(FrozenInstanceError):
            ctx.target_env = TargetEnv(system=True)  # type: ignore[misc]


class TestReplaceMutation:
    """dataclasses.replace propagates correctly through nested types."""

    def test_replace_install_policy_through_top_level(self):
        ctx = RoutineContext.from_cli()
        ctx2 = replace(
            ctx,
            install_policy=replace(ctx.install_policy, skip_lock=True),
        )
        assert ctx2.install_policy.skip_lock is True
        # Original is untouched.
        assert ctx.install_policy.skip_lock is False
        # Other nested groups are shared (frozen, so identity is fine).
        assert ctx.target_env == ctx2.target_env

    def test_replace_package_selection_categories(self):
        ctx = RoutineContext.from_cli()
        ctx2 = replace(
            ctx,
            package_selection=replace(
                ctx.package_selection,
                categories=("packages", "dev-packages"),
            ),
        )
        assert ctx2.package_selection.categories == (
            "packages",
            "dev-packages",
        )
        assert ctx.package_selection.categories == ()

    def test_replace_on_nested_only(self):
        env = TargetEnv(system=False)
        env2 = replace(env, system=True)
        assert env2.system is True
        assert env.system is False

    def test_replace_does_not_mutate_unspecified_nested(self):
        ctx = RoutineContext.from_cli(python="3.11")
        ctx2 = replace(
            ctx,
            install_policy=replace(ctx.install_policy, deploy=True),
        )
        # target_env is preserved verbatim.
        assert ctx2.target_env.python == "3.11"
        assert ctx2.install_policy.deploy is True
        assert ctx.install_policy.deploy is False


class TestFromCliDefaults:
    """from_cli's defaults match the values baked into the dataclasses."""

    def test_from_cli_no_args(self):
        ctx = RoutineContext.from_cli()
        # target_env
        assert ctx.target_env.system is False
        assert ctx.target_env.allow_global is False  # mirrors system
        assert ctx.target_env.python is None
        assert ctx.target_env.pypi_mirror is None
        assert ctx.target_env.site_packages is None
        # install_policy
        assert ctx.install_policy.pre is False
        assert ctx.install_policy.deploy is False
        assert ctx.install_policy.skip_lock is False
        assert ctx.install_policy.ignore_pipfile is False
        assert ctx.install_policy.clear is False
        assert ctx.install_policy.lock_only is False
        assert ctx.install_policy.lock is False
        assert ctx.install_policy.dry_run is False
        # package_selection
        assert ctx.package_selection.packages == ()
        assert ctx.package_selection.editable_packages == ()
        assert ctx.package_selection.categories == ()
        assert ctx.package_selection.dev is False
        assert ctx.package_selection.dev_only is False
        assert ctx.package_selection.all is False
        assert ctx.package_selection.all_dev is False
        assert ctx.package_selection.index is None
        assert ctx.package_selection.index_name is None
        assert ctx.package_selection.requirementstxt is None
        # execution_options
        assert ctx.execution_options.extra_pip_args == ()
        assert ctx.execution_options.requirements_directory is None
        assert ctx.execution_options.no_deps is False
        assert ctx.execution_options.ignore_hashes is False
        assert ctx.execution_options.use_pep517 is True
        assert ctx.execution_options.bare is False
        assert ctx.execution_options.quiet is False
        assert ctx.execution_options.verbose is False
        assert ctx.execution_options.write is True

    def test_from_cli_allow_global_defaults_to_system(self):
        # When system=True and allow_global unspecified, allow_global
        # mirrors system (the historical do_install pattern).
        ctx = RoutineContext.from_cli(system=True)
        assert ctx.target_env.system is True
        assert ctx.target_env.allow_global is True

    def test_from_cli_allow_global_explicit_override(self):
        # Caller can explicitly pass allow_global=False even when
        # system=True.
        ctx = RoutineContext.from_cli(system=True, allow_global=False)
        assert ctx.target_env.system is True
        assert ctx.target_env.allow_global is False

    def test_from_cli_routes_values_to_correct_groups(self):
        ctx = RoutineContext.from_cli(
            system=True,
            python="3.11",
            pypi_mirror="https://mirror.example.org/simple",
            pre=True,
            skip_lock=True,
            packages=("requests", "flask"),
            dev=True,
            categories=("dev-packages",),
            extra_pip_args=("--no-build-isolation",),
            verbose=True,
        )
        assert ctx.target_env.python == "3.11"
        assert ctx.target_env.pypi_mirror == "https://mirror.example.org/simple"
        assert ctx.install_policy.pre is True
        assert ctx.install_policy.skip_lock is True
        assert ctx.package_selection.packages == ("requests", "flask")
        assert ctx.package_selection.dev is True
        assert ctx.package_selection.categories == ("dev-packages",)
        assert ctx.execution_options.extra_pip_args == (
            "--no-build-isolation",
        )
        assert ctx.execution_options.verbose is True


class TestFromCliKeywordOnly:
    """from_cli rejects positional arguments."""

    def test_from_cli_positional_raises(self):
        # The first positional after cls would land on `system`.
        with pytest.raises(TypeError):
            RoutineContext.from_cli(True)  # type: ignore[misc]

    def test_from_cli_two_positionals_raises(self):
        with pytest.raises(TypeError):
            RoutineContext.from_cli(True, False)  # type: ignore[misc]


class TestSequenceCoercion:
    """Sequence-typed fields coerce lists to tuples through from_cli."""

    def test_packages_list_coerced_to_tuple(self):
        ctx = RoutineContext.from_cli(packages=["requests", "flask"])
        assert ctx.package_selection.packages == ("requests", "flask")
        assert isinstance(ctx.package_selection.packages, tuple)

    def test_editable_packages_list_coerced_to_tuple(self):
        ctx = RoutineContext.from_cli(editable_packages=["./local"])
        assert ctx.package_selection.editable_packages == ("./local",)
        assert isinstance(ctx.package_selection.editable_packages, tuple)

    def test_categories_list_coerced_to_tuple(self):
        ctx = RoutineContext.from_cli(categories=["packages", "dev-packages"])
        assert ctx.package_selection.categories == (
            "packages",
            "dev-packages",
        )
        assert isinstance(ctx.package_selection.categories, tuple)

    def test_extra_pip_args_list_coerced_to_tuple(self):
        ctx = RoutineContext.from_cli(
            extra_pip_args=["--no-build-isolation", "--no-cache-dir"],
        )
        assert ctx.execution_options.extra_pip_args == (
            "--no-build-isolation",
            "--no-cache-dir",
        )
        assert isinstance(ctx.execution_options.extra_pip_args, tuple)


class TestPackageArgsProperty:
    """package_args derives combined positional+editable list."""

    def test_package_args_empty_by_default(self):
        ctx = RoutineContext.from_cli()
        assert ctx.package_selection.package_args == ()

    def test_package_args_combines_packages_and_editables(self):
        ctx = RoutineContext.from_cli(
            packages=["requests"],
            editable_packages=["./local"],
        )
        assert ctx.package_selection.package_args == ("requests", "./local")

    def test_package_args_filters_falsy_entries(self):
        # The property guards against empty-string sentinels that
        # historically appeared in pipenv's "list-or-False" pattern.
        sel = PackageSelection(
            packages=("requests", ""),
            editable_packages=("", "./local"),
        )
        assert sel.package_args == ("requests", "./local")
