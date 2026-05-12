"""Routine-context dataclass for pipenv.routines.

Bundles the user-facing inputs that travel together across the
install / update / lock / sync / uninstall call chains. See
docs/dev/initiative-c-design.md for rationale.

This module is purely additive scaffolding (introduced in T_C.4). No
existing routine signature consumes ``RoutineContext`` yet; subsequent
tasks (T_C.5+) migrate routines one at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class TargetEnv:
    """Which Python and where to install.

    Sourced from the ``target_env`` semantic group in T_C.2 (50 rows).
    Every routine but the arg-builders carries ``pypi_mirror`` and
    ``system``; most carry ``python`` and a subset carry
    ``site_packages`` and ``allow_global``.
    """

    system: bool = False
    allow_global: bool = False
    python: str | None = None
    pypi_mirror: str | None = None
    site_packages: bool | None = None


@dataclass(frozen=True)
class InstallPolicy:
    """Flags governing install / lock behaviour.

    Sourced from the ``install_policy`` semantic group in T_C.2 (36
    rows). These flags travel as a packet through the
    install / init / lock chain.
    """

    pre: bool = False
    deploy: bool = False
    skip_lock: bool = False
    ignore_pipfile: bool = False
    clear: bool = False
    lock_only: bool = False
    lock: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class PackageSelection:
    """Which packages a routine should act on.

    Sourced from the ``package_selection`` semantic group in T_C.2 (54
    rows). The trio (``packages``, ``editable_packages``,
    ``categories``) appears verbatim in ``do_install`` / ``do_update``
    / ``do_uninstall`` / ``upgrade`` and in five helpers.

    Notes on aliases / collapses (see design doc section 2):

    * ``pipfile_categories`` and ``categories`` collapse to
      ``categories``. Translation between Pipfile-section names and
      lockfile-section names happens at routine-internal boundaries
      (see helpers in ``pipenv.utils.dependencies``).
    * ``index_url`` and ``index`` collapse to ``index``.
    * ``package_args`` is derived (see the property below), not
      stored, because it is a combined view of ``packages`` and
      ``editable_packages``.
    * The ``all`` / ``all_dev`` / ``dev_only`` flags are
      uninstall-specific but live here because they are semantically
      "which packages to act on". Placement deferred per design doc
      section 9 decision 6.
    """

    packages: Sequence[str] = ()
    editable_packages: Sequence[str] = ()
    categories: Sequence[str] = ()
    dev: bool = False
    dev_only: bool = False
    all: bool = False
    all_dev: bool = False
    index: str | None = None
    index_name: str | None = None
    requirementstxt: str | None = None

    @property
    def package_args(self) -> tuple[str, ...]:
        """Combined positional + editable list used by validators."""
        return tuple(p for p in self.packages if p) + tuple(
            p for p in self.editable_packages if p
        )


@dataclass(frozen=True)
class ExecutionOptions:
    """How to run a routine: passthrough flags, output, paths.

    Sourced from the ``execution_options`` semantic group in T_C.2 (57
    rows). Includes pip passthrough (``extra_pip_args``), output
    formatting (``bare``, ``quiet``, ``verbose``) and resolver-time
    behaviour toggles (``no_deps``, ``ignore_hashes``, ``use_pep517``).

    Notes:

    * ``requirements_directory`` and ``requirements_dir`` collapse to
      ``requirements_directory``.
    * ``write`` (consumed by ``do_lock``) defaults to ``True`` because
      the historical default is "write the lockfile to disk";
      ``do_lock``'s return-a-dict mode is the non-default override.
    * Audit / scan / check output knobs (``output``, ``save_json``,
      ``output_file``, ``policy_file``) are deliberately NOT in
      ``ExecutionOptions`` — they belong to the audit / scan routines,
      which are not really "dependency-management" calls (design doc
      sections 3 and 8.5).
    * ``resolver`` (T_F.5) carries the ``--resolver NAME`` selection
      from the CLI down to the resolver-call layer.  ``None`` is the
      "not specified" sentinel; the dispatcher in
      ``pipenv.resolver.core`` falls through to PIPENV_RESOLVER /
      ``[pipenv] resolver`` / default.
    """

    extra_pip_args: Sequence[str] = ()
    requirements_directory: str | None = None
    no_deps: bool = False
    ignore_hashes: bool = False
    use_pep517: bool = True
    bare: bool = False
    quiet: bool = False
    verbose: bool = False
    write: bool = True
    resolver: str | None = None


@dataclass(frozen=True)
class RoutineContext:
    """Top-level routine context.

    Composed of four nested frozen dataclasses. Constructed once at the
    CLI boundary via ``RoutineContext.from_cli(...)``; mutated
    downstream via ``dataclasses.replace``.
    """

    target_env: TargetEnv = field(default_factory=TargetEnv)
    install_policy: InstallPolicy = field(default_factory=InstallPolicy)
    package_selection: PackageSelection = field(
        default_factory=PackageSelection
    )
    execution_options: ExecutionOptions = field(
        default_factory=ExecutionOptions
    )

    @classmethod
    def from_cli(  # noqa: PLR0913 — single CLI-defaults materialization point; see design doc section 4
        cls,
        *,
        # target_env
        system: bool = False,
        allow_global: bool | None = None,
        python: str | None = None,
        pypi_mirror: str | None = None,
        site_packages: bool | None = None,
        # install_policy
        pre: bool = False,
        deploy: bool = False,
        skip_lock: bool = False,
        ignore_pipfile: bool = False,
        clear: bool = False,
        lock_only: bool = False,
        lock: bool = False,
        dry_run: bool = False,
        # package_selection
        packages: Sequence[str] = (),
        editable_packages: Sequence[str] = (),
        categories: Sequence[str] = (),
        dev: bool = False,
        dev_only: bool = False,
        all: bool = False,
        all_dev: bool = False,
        index: str | None = None,
        index_name: str | None = None,
        requirementstxt: str | None = None,
        # execution_options
        extra_pip_args: Sequence[str] = (),
        requirements_directory: str | None = None,
        no_deps: bool = False,
        ignore_hashes: bool = False,
        use_pep517: bool = True,
        bare: bool = False,
        quiet: bool = False,
        verbose: bool = False,
        write: bool = True,
        resolver: str | None = None,
    ) -> RoutineContext:
        """Single materialization point for CLI defaults.

        ``allow_global`` defaults to ``None`` here so we can default it
        to ``system`` when unspecified (the historical pattern in
        ``do_install``: ``allow_global=system``). Callers may override
        by passing ``allow_global=`` explicitly.

        Sequence-typed inputs (``packages``, ``editable_packages``,
        ``categories``, ``extra_pip_args``) are tuple-coerced so the
        resulting dataclasses stay genuinely immutable even if the
        caller hands in a list.
        """
        if allow_global is None:
            allow_global = system
        return cls(
            target_env=TargetEnv(
                system=system,
                allow_global=allow_global,
                python=python,
                pypi_mirror=pypi_mirror,
                site_packages=site_packages,
            ),
            install_policy=InstallPolicy(
                pre=pre,
                deploy=deploy,
                skip_lock=skip_lock,
                ignore_pipfile=ignore_pipfile,
                clear=clear,
                lock_only=lock_only,
                lock=lock,
                dry_run=dry_run,
            ),
            package_selection=PackageSelection(
                packages=tuple(packages),
                editable_packages=tuple(editable_packages),
                categories=tuple(categories),
                dev=dev,
                dev_only=dev_only,
                all=all,
                all_dev=all_dev,
                index=index,
                index_name=index_name,
                requirementstxt=requirementstxt,
            ),
            execution_options=ExecutionOptions(
                extra_pip_args=tuple(extra_pip_args),
                requirements_directory=requirements_directory,
                no_deps=no_deps,
                ignore_hashes=ignore_hashes,
                use_pep517=use_pep517,
                bare=bare,
                quiet=quiet,
                verbose=verbose,
                write=write,
                resolver=resolver,
            ),
        )
