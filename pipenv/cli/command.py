"""Pipenv CLI command definitions using argparse."""

import os
import sys
from pathlib import Path

from pipenv import environments
from pipenv.__version__ import __version__
from pipenv.cli.options import (
    State,
    add_common_options,
    add_deploy_option,
    add_general_options,
    add_install_options,
    add_lock_options,
    add_pypi_mirror_option,
    add_python_option,
    add_site_packages_option,
    add_sync_options,
    add_system_option,
    add_uninstall_options,
    add_upgrade_options,
    add_verbose_option,
    parse_categories,
    populate_state,
)
from pipenv.cli.parser import PipenvArgumentParser
from pipenv.utils import console, err
from pipenv.utils.environment import load_dot_env
from pipenv.utils.processes import subprocess_run


def _apply_default_categories(args, state):
    """Apply default categories from PIPENV_DEFAULT_CATEGORIES if no explicit categories."""
    # Check if categories or dev were explicitly set
    categories_val = getattr(args, "categories", "")
    dev_val = getattr(args, "dev", False)

    # If explicitly provided on command line or via env, do not override
    categories_env = os.environ.get("PIPENV_CATEGORIES")
    dev_env = os.environ.get("PIPENV_DEV")

    if categories_val or dev_val or categories_env or dev_env:
        return

    if state.installstate.categories:
        return

    default_categories = parse_categories(state.project.s.PIPENV_DEFAULT_CATEGORIES)
    if default_categories:
        state.installstate.categories = default_categories


def build_parser():
    """Build the main pipenv argument parser with all subcommands."""
    parser = PipenvArgumentParser(
        prog="pipenv",
        description="Python Development Workflow for Humans.",
        add_help=True,
    )

    # Root-level options
    parser.add_argument(
        "--where",
        action="store_true",
        default=False,
        help="Output project home information.",
    )
    parser.add_argument(
        "--venv",
        action="store_true",
        default=False,
        help="Output virtualenv information.",
    )
    parser.add_argument(
        "--py",
        action="store_true",
        default=False,
        help="Output Python interpreter information.",
    )
    parser.add_argument(
        "--envs",
        action="store_true",
        default=False,
        help="Output Environment Variable options.",
    )
    parser.add_argument(
        "--rm",
        action="store_true",
        default=False,
        help="Remove the virtualenv. [deprecated: use `pipenv remove` instead]",
    )
    parser.add_argument(
        "--bare", action="store_true", default=False, help="Minimal output."
    )
    parser.add_argument(
        "--man", action="store_true", default=False, help="Display manpage."
    )
    parser.add_argument(
        "--support",
        action="store_true",
        default=False,
        help="Output diagnostic information for use in GitHub issues.",
    )
    parser.add_argument(
        "--version", action="version", version=f"pipenv, version {__version__}"
    )

    # General options on root
    add_general_options(parser)

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands:")

    def _add_subparser(name, **kwargs):
        """Add a subparser with conflict_handler='resolve' for overlapping options."""
        return subparsers.add_parser(name, conflict_handler="resolve", **kwargs)

    # --- install ---
    _install_help = (
        "Installs provided packages and adds them to Pipfile, "
        "or (if no packages are given), installs all packages from Pipfile."
    )
    p_install = _add_subparser(
        "install",
        help=_install_help,
        description=_install_help,
    )
    add_system_option(p_install)
    add_deploy_option(p_install)
    add_site_packages_option(p_install)
    add_install_options(p_install)
    p_install.set_defaults(func=cmd_install)

    # --- remove ---
    p_remove = _add_subparser(
        "remove",
        help="Removes the virtualenv for the current project.",
        description="Removes the virtualenv for the current project.",
    )
    p_remove.set_defaults(func=cmd_remove)

    # --- upgrade ---
    p_upgrade = _add_subparser(
        "upgrade",
        help="Resolves provided packages and adds them to Pipfile, or (if no packages are given), merges results to Pipfile.lock",
        description="Resolves provided packages and adds them to Pipfile, or (if no packages are given), merges results to Pipfile.lock",
    )
    add_system_option(p_upgrade)
    add_site_packages_option(p_upgrade)
    add_install_options(p_upgrade)
    add_upgrade_options(p_upgrade)
    p_upgrade.set_defaults(func=cmd_upgrade)

    # --- uninstall ---
    p_uninstall = _add_subparser(
        "uninstall",
        help="Uninstalls a provided package and removes it from Pipfile.",
        description="Uninstalls a provided package and removes it from Pipfile.",
    )
    p_uninstall.add_argument(
        "--all-dev",
        action="store_true",
        default=False,
        help="Uninstall all package from [dev-packages].",
    )
    p_uninstall.add_argument(
        "--all",
        dest="uninstall_all",
        action="store_true",
        default=False,
        help="Purge all package(s) from virtualenv. Does not edit Pipfile.",
    )
    add_uninstall_options(p_uninstall)
    p_uninstall.set_defaults(func=cmd_uninstall)

    # --- lock ---
    p_lock = _add_subparser(
        "lock",
        help="Generates Pipfile.lock.",
        description="Generates Pipfile.lock.",
    )
    add_lock_options(p_lock)
    p_lock.set_defaults(func=cmd_lock)

    # --- shell ---
    p_shell = _add_subparser(
        "shell",
        help="Spawns a shell within the virtualenv.",
        description="Spawns a shell within the virtualenv.",
    )
    p_shell.add_argument(
        "--fancy", action="store_true", default=False, help="Run in shell in fancy mode."
    )
    p_shell.add_argument(
        "--anyway",
        action="store_true",
        default=False,
        help="Always spawn a sub-shell, even if one is already spawned.",
    )
    p_shell.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Quiet standard output, except vulnerability report.",
    )
    p_shell.add_argument(
        "shell_args", nargs="*", default=[], help="Arguments to pass to the shell."
    )
    add_pypi_mirror_option(p_shell)
    add_python_option(p_shell)
    p_shell.set_defaults(func=cmd_shell)

    # --- activate ---
    p_activate = _add_subparser(
        "activate",
        help="Outputs the activation command for the virtualenv.",
        description="Outputs the shell command to activate the virtualenv.",
    )
    add_pypi_mirror_option(p_activate)
    add_python_option(p_activate)
    p_activate.set_defaults(func=cmd_activate)

    # --- run ---
    p_run = _add_subparser(
        "run",
        help="Spawns a command installed into the virtualenv.",
        description="Spawns a command installed into the virtualenv.",
    )
    add_system_option(p_run)
    add_common_options(p_run)
    p_run.add_argument("run_command", metavar="command", help="Command to run.")
    p_run.add_argument(
        "run_args",
        nargs="*",
        metavar="args",
        default=[],
        help="Arguments to pass to the command.",
    )
    p_run.set_defaults(func=cmd_run)

    # --- check ---
    _check_desc = (
        "DEPRECATED: Checks for PyUp Safety security vulnerabilities "
        "and against PEP 508 markers provided in Pipfile. "
        "Use 'pipenv audit' instead."
    )
    p_check = _add_subparser(
        "check",
        help="DEPRECATED: Checks for PyUp Safety security vulnerabilities.",
        description=_check_desc,
    )
    p_check.add_argument(
        "--db",
        default=lambda: os.environ.get("PIPENV_SAFETY_DB"),
        help="Path or URL to a PyUp Safety vulnerabilities database.",
    )
    p_check.add_argument(
        "--ignore",
        "-i",
        action="append",
        default=[],
        help="Ignore specified vulnerability during PyUp Safety checks.",
    )
    p_check.add_argument(
        "--output",
        default="default",
        choices=["default", "json", "full-report", "bare", "screen", "text", "minimal"],
        help="Output format.",
    )
    p_check.add_argument("--key", default=None, help="Safety API key from PyUp.io.")
    p_check.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Quiet standard output, except vulnerability report.",
    )
    p_check.add_argument(
        "--policy-file", default="", help="Define the policy file to be used"
    )
    p_check.add_argument(
        "--exit-code",
        action="store_true",
        default=True,
        help="Output standard exit codes. Default: --exit-code",
    )
    p_check.add_argument(
        "--continue-on-error",
        action="store_true",
        default=False,
        help="Continue on error.",
    )
    p_check.add_argument(
        "--audit-and-monitor",
        action="store_true",
        default=True,
        help="Send results back to pyup.io.",
    )
    p_check.add_argument(
        "--disable-audit-and-monitor",
        action="store_true",
        default=False,
        help="Disable sending results back to pyup.io.",
    )
    p_check.add_argument(
        "--project",
        default=None,
        dest="safety_project",
        help="Project to associate this scan with on pyup.io.",
    )
    p_check.add_argument(
        "--save-json", default="", help="Path to where output file will be placed."
    )
    p_check.add_argument(
        "--use-installed",
        action="store_true",
        default=False,
        help="Whether to use the lockfile as input to check.",
    )
    p_check.add_argument(
        "--categories",
        default="",
        dest="check_categories",
        help="Use the specified categories from the lockfile.",
    )
    p_check.add_argument(
        "--auto-install",
        action="store_true",
        default=False,
        help="Automatically install safety if not already installed.",
    )
    p_check.add_argument(
        "--scan",
        action="store_true",
        default=False,
        help="Use the new scan command instead of the deprecated check command.",
    )
    add_common_options(p_check)
    add_system_option(p_check)
    p_check.set_defaults(func=cmd_check)

    # --- audit ---
    p_audit = _add_subparser(
        "audit",
        help="Audits packages for security vulnerabilities using pip-audit.",
        description="Audit packages for known security vulnerabilities using pip-audit.",
    )
    p_audit.add_argument(
        "--output",
        "-f",
        default="columns",
        choices=["columns", "json", "cyclonedx-json", "cyclonedx-xml", "markdown"],
        help="Output format for audit results.",
    )
    p_audit.add_argument(
        "--vulnerability-service",
        "-s",
        default="pypi",
        choices=["pypi", "osv"],
        help="Vulnerability service to query.",
    )
    p_audit.add_argument(
        "--ignore",
        "-i",
        action="append",
        default=[],
        help="Ignore a specific vulnerability by ID.",
    )
    p_audit.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Automatically upgrade packages with known vulnerabilities.",
    )
    p_audit.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Collect dependencies but do not audit.",
    )
    p_audit.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Fail if dependency collection fails on any dependency.",
    )
    p_audit.add_argument(
        "--skip-editable",
        action="store_true",
        default=False,
        help="Skip auditing editable packages.",
    )
    p_audit.add_argument(
        "--no-deps",
        action="store_true",
        default=False,
        help="Don't perform dependency resolution.",
    )
    p_audit.add_argument(
        "--local",
        action="store_true",
        default=False,
        help="Only audit packages in the local environment.",
    )
    p_audit.add_argument(
        "--desc",
        action="store_true",
        default=False,
        help="Include descriptions for each vulnerability.",
    )
    p_audit.add_argument(
        "--aliases",
        action="store_true",
        default=False,
        help="Include alias IDs (CVE, GHSA) for each vulnerability.",
    )
    p_audit.add_argument(
        "--output-file", "-o", default=None, help="Output results to the given file."
    )
    p_audit.add_argument(
        "--quiet", action="store_true", default=False, help="Quiet mode - minimal output."
    )
    p_audit.add_argument(
        "--locked",
        action="store_true",
        default=False,
        help="Audit lockfiles instead of the environment.",
    )
    add_common_options(p_audit)
    add_system_option(p_audit)
    p_audit.set_defaults(func=cmd_audit)

    # --- update ---
    p_update = _add_subparser(
        "update",
        help="Runs lock, then sync.",
        description="Runs lock when no packages are specified, or upgrade, and then sync.",
    )
    p_update.add_argument(
        "--bare", action="store_true", default=False, help="Minimal output."
    )
    p_update.add_argument(
        "--outdated",
        action="store_true",
        default=False,
        help="List out-of-date dependencies.",
    )
    p_update.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="List packages that would be updated without actually updating.",
    )
    add_system_option(p_update)
    add_install_options(p_update)
    add_upgrade_options(p_update)
    p_update.set_defaults(func=cmd_update)

    # --- graph ---
    p_graph = _add_subparser(
        "graph",
        help="Displays currently-installed dependency graph information.",
        description="Displays currently-installed dependency graph information.",
    )
    p_graph.add_argument(
        "--bare", action="store_true", default=False, help="Minimal output."
    )
    p_graph.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="json_output",
        help="Output JSON.",
    )
    p_graph.add_argument(
        "--json-tree",
        action="store_true",
        default=False,
        help="Output JSON in nested tree.",
    )
    p_graph.add_argument(
        "--reverse", action="store_true", default=False, help="Reversed dependency graph."
    )
    p_graph.set_defaults(func=cmd_graph)

    # --- open ---
    p_open = _add_subparser(
        "open",
        help="View a given module in your editor.",
        description="View a given module in your editor. Uses the EDITOR environment variable.",
    )
    add_common_options(p_open)
    p_open.add_argument("module", help="Module name to open.")
    p_open.set_defaults(func=cmd_open)

    # --- sync ---
    p_sync = _add_subparser(
        "sync",
        help="Installs all packages specified in Pipfile.lock.",
        description="Installs all packages specified in Pipfile.lock.",
    )
    add_system_option(p_sync)
    p_sync.add_argument(
        "--bare", action="store_true", default=False, help="Minimal output."
    )
    add_sync_options(p_sync)
    add_site_packages_option(p_sync)
    p_sync.set_defaults(func=cmd_sync)

    # --- clean ---
    p_clean = _add_subparser(
        "clean",
        help="Uninstalls all packages not specified in Pipfile.lock.",
        description="Uninstalls all packages not specified in Pipfile.lock.",
    )
    p_clean.add_argument(
        "--bare", action="store_true", default=False, help="Minimal output."
    )
    p_clean.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Just output unneeded packages.",
    )
    add_verbose_option(p_clean)
    add_python_option(p_clean)
    p_clean.set_defaults(func=cmd_clean)

    # --- scripts ---
    p_scripts = _add_subparser(
        "scripts",
        help="Lists scripts in current environment config.",
        description="Lists scripts in current environment config.",
    )
    add_common_options(p_scripts)
    p_scripts.set_defaults(func=cmd_scripts)

    # --- verify ---
    p_verify = _add_subparser(
        "verify",
        help="Verify the hash in Pipfile.lock is up-to-date.",
        description="Verify the hash in Pipfile.lock is up-to-date.",
    )
    p_verify.set_defaults(func=cmd_verify)

    # --- requirements ---
    p_requirements = _add_subparser(
        "requirements",
        help="Generate a requirements.txt from Pipfile.lock.",
        description="Generate a requirements.txt from Pipfile.lock.",
    )
    p_requirements.add_argument(
        "--dev",
        action="store_true",
        default=False,
        help="Also add development requirements.",
    )
    p_requirements.add_argument(
        "--dev-only",
        action="store_true",
        default=False,
        help="Only add development requirements.",
    )
    p_requirements.add_argument(
        "--hash",
        action="store_true",
        default=False,
        dest="include_hash",
        help="Add package hashes.",
    )
    p_requirements.add_argument(
        "--exclude-markers", action="store_true", default=False, help="Exclude markers."
    )
    p_requirements.add_argument(
        "--exclude-index",
        action="store_true",
        default=False,
        help="Exclude index URLs from the output.",
    )
    p_requirements.add_argument(
        "--categories",
        default="",
        dest="req_categories",
        help="Only add requirement of the specified categories.",
    )
    p_requirements.add_argument(
        "--from-pipfile",
        action="store_true",
        default=False,
        help="Only include dependencies from Pipfile.",
    )
    p_requirements.add_argument(
        "--no-lock",
        action="store_true",
        default=False,
        help="Use version specifiers from Pipfile instead of locked versions.",
    )
    p_requirements.set_defaults(func=cmd_requirements)

    # --- pylock ---
    p_pylock = _add_subparser(
        "pylock",
        help="Manage PEP 751 pylock.toml files.",
        description="Generate, validate, or convert pylock.toml files.",
    )
    p_pylock.add_argument(
        "--generate",
        action="store_true",
        default=False,
        help="Generate pylock.toml from Pipfile.lock.",
    )
    p_pylock.add_argument(
        "--from-pyproject",
        action="store_true",
        default=False,
        help="Generate pylock.toml skeleton from pyproject.toml.",
    )
    p_pylock.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help="Validate an existing pylock.toml file.",
    )
    p_pylock.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path (default: pylock.toml in project directory).",
    )
    p_pylock.add_argument(
        "--dev-groups",
        default="dev",
        help="Comma-separated list of dependency group names for dev packages.",
    )
    add_common_options(p_pylock)
    p_pylock.set_defaults(func=cmd_pylock)

    return parser


# --- Command implementations ---


def cmd_install(args, state):
    """Installs provided packages and adds them to Pipfile."""
    from pipenv.routines.install import do_install

    if state.installstate.all_categories:
        state.installstate.categories = state.project.get_package_categories()
    else:
        _apply_default_categories(args, state)

    do_install(
        state.project,
        dev=state.installstate.dev,
        python=state.python,
        pypi_mirror=state.pypi_mirror,
        system=state.system,
        ignore_pipfile=state.installstate.ignore_pipfile,
        requirementstxt=state.installstate.requirementstxt,
        pre=state.installstate.pre,
        deploy=state.installstate.deploy,
        index=state.index,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        site_packages=state.site_packages,
        extra_pip_args=state.installstate.extra_pip_args,
        pipfile_categories=state.installstate.categories,
        skip_lock=state.installstate.skip_lock,
    )


def cmd_remove(args, state):
    """Removes the virtualenv for the current project."""
    from pipenv.utils.virtualenv import cleanup_virtualenv

    if state.project.s.PIPENV_USE_SYSTEM or environments.is_in_virtualenv():
        console.print(
            "You are attempting to remove a virtualenv that "
            "Pipenv did not create. Aborting.",
            style="red",
        )
        sys.exit(1)
    if state.project.virtualenv_exists:
        loc = state.project.virtualenv_location
        console.print(f"[bold]Removing virtualenv[/bold] ([green]{loc}[/green])...")
        with console.status("Running..."):
            cleanup_virtualenv(state.project, bare=True)
        return 0
    else:
        err.print(
            "No virtualenv has been created for this project yet!",
            style="red bold",
        )
        sys.exit(1)


def cmd_upgrade(args, state):
    from pipenv.routines.update import upgrade
    from pipenv.utils.project import ensure_project

    if state.installstate.all_categories:
        state.installstate.categories = state.project.get_package_categories()
    else:
        _apply_default_categories(args, state)

    ensure_project(
        state.project,
        python=state.python,
        pypi_mirror=state.pypi_mirror,
        warn=(not state.quiet),
        site_packages=state.site_packages,
        clear=state.clear,
    )

    upgrade(
        state.project,
        pre=state.installstate.pre,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        categories=state.installstate.categories,
        index_url=state.index,
        dev=state.installstate.dev,
        system=state.system,
        lock_only=state.installstate.lock_only,
        extra_pip_args=state.installstate.extra_pip_args,
    )


def cmd_uninstall(args, state):
    """Uninstalls a provided package and removes it from Pipfile."""
    from pipenv.routines.uninstall import do_uninstall

    _apply_default_categories(args, state)

    pre = state.installstate.pre

    retcode = do_uninstall(
        state.project,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        python=state.python,
        system=state.system,
        lock=False,
        all_dev=args.all_dev,
        all=args.uninstall_all,
        pre=pre,
        pypi_mirror=state.pypi_mirror,
        categories=state.installstate.categories,
    )
    if retcode:
        sys.exit(retcode)


def cmd_lock(args, state):
    """Generates Pipfile.lock."""
    from pipenv.routines.lock import do_lock
    from pipenv.utils.project import ensure_project

    _apply_default_categories(args, state)

    ensure_project(
        state.project,
        python=state.python,
        pypi_mirror=state.pypi_mirror,
        warn=(not state.quiet),
        site_packages=state.site_packages,
    )
    pre = state.installstate.pre
    do_lock(
        state.project,
        clear=state.clear,
        pre=pre,
        pypi_mirror=state.pypi_mirror,
        write=True,
        quiet=state.quiet,
        categories=state.installstate.categories,
    )


def cmd_shell(args, state):
    """Spawns a shell within the virtualenv."""
    from pipenv.routines.shell import do_shell

    fancy = args.fancy
    shell_args = tuple(args.shell_args) if args.shell_args else None
    anyway = args.anyway
    quiet = args.quiet

    if "PIPENV_ACTIVE" in os.environ:
        venv_name = os.environ.get("VIRTUAL_ENV", "UNKNOWN_VIRTUAL_ENVIRONMENT")
        if not anyway:
            err.print(
                f"Shell for [green bold]{venv_name}[/green bold] "
                "[bold]already activated[/bold].\n"
                "New shell not activated to avoid nested environments."
            )
            sys.exit(1)

    if (
        os.name == "nt"
        or Path(os.environ.get("PIPENV_SHELL") or "").name == "pwsh"
        or Path(os.environ.get("SHELL") or "").name == "pwsh"
        or os.environ.get("POSH_THEME")
    ):
        fancy = True
    do_shell(
        state.project,
        python=state.python,
        fancy=fancy,
        shell_args=shell_args,
        pypi_mirror=state.pypi_mirror,
        quiet=quiet,
    )


def cmd_activate(args, state):
    """Outputs the activation command for the virtualenv."""
    from pipenv.shells import ShellDetectionFailure, _get_activate_script, detect_info
    from pipenv.utils.project import ensure_project

    ensure_project(
        state.project,
        python=state.python,
        validate=False,
        pypi_mirror=state.pypi_mirror,
    )

    if not state.project.virtualenv_exists:
        err.print(
            "No virtualenv has been created for this project yet!\n"
            "Run [green bold]pipenv install[/green bold] to create one.",
            style="red bold",
        )
        sys.exit(1)

    try:
        shell_type, shell_cmd = detect_info(state.project)
    except ShellDetectionFailure:
        err.print(
            "Unable to detect shell. Set PIPENV_SHELL environment variable.",
            style="red bold",
        )
        sys.exit(1)

    venv_path = state.project.virtualenv_location
    activate_cmd = _get_activate_script(shell_cmd, venv_path)
    print(activate_cmd.strip())


def cmd_run(args, state):
    """Spawns a command installed into the virtualenv."""
    from pipenv.routines.shell import do_run

    do_run(
        state.project,
        command=args.run_command,
        args=tuple(args.run_args),
        python=state.python,
        pypi_mirror=state.pypi_mirror,
        system=state.system,
    )


def cmd_check(args, state):
    """Checks for PyUp Safety security vulnerabilities."""
    from pipenv.routines.check import do_check

    # Resolve the callable default for --db
    db_val = args.db
    if callable(db_val):
        db_val = db_val()

    # Handle exit-code / continue-on-error
    exit_code = True
    if hasattr(args, "continue_on_error") and args.continue_on_error:
        exit_code = False

    # Handle audit-and-monitor / disable-audit-and-monitor
    audit_and_monitor = True
    if hasattr(args, "disable_audit_and_monitor") and args.disable_audit_and_monitor:
        audit_and_monitor = False

    do_check(
        state.project,
        python=state.python,
        system=state.system,
        db=db_val,
        ignore=args.ignore,
        output=args.output,
        key=args.key,
        quiet=args.quiet,
        verbose=state.verbose,
        exit_code=exit_code,
        policy_file=args.policy_file,
        save_json=args.save_json,
        audit_and_monitor=audit_and_monitor,
        safety_project=args.safety_project,
        pypi_mirror=state.pypi_mirror,
        use_installed=args.use_installed,
        categories=args.check_categories,
        auto_install=args.auto_install,
        scan=args.scan,
    )


def cmd_audit(args, state):
    """Audit packages for known security vulnerabilities using pip-audit."""
    from pipenv.routines.audit import do_audit

    do_audit(
        state.project,
        python=state.python,
        system=state.system,
        output=args.output,
        quiet=args.quiet,
        verbose=state.verbose,
        strict=args.strict,
        ignore=args.ignore,
        fix=args.fix,
        dry_run=args.dry_run,
        skip_editable=args.skip_editable,
        no_deps=args.no_deps,
        local_only=args.local,
        vulnerability_service=args.vulnerability_service,
        descriptions=args.desc,
        aliases=args.aliases,
        output_file=args.output_file,
        pypi_mirror=state.pypi_mirror,
        use_lockfile=args.locked,
    )


def cmd_update(args, state):
    """Runs lock when no packages are specified, or upgrade, and then sync."""
    from pipenv.routines.update import do_update

    if state.installstate.all_categories:
        state.installstate.categories = state.project.get_package_categories()
    else:
        _apply_default_categories(args, state)

    do_update(
        state.project,
        python=state.python,
        site_packages=state.site_packages,
        clear=state.clear,
        pre=state.installstate.pre,
        pypi_mirror=state.pypi_mirror,
        system=state.system,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        dev=state.installstate.dev,
        bare=args.bare,
        extra_pip_args=state.installstate.extra_pip_args,
        categories=state.installstate.categories,
        index_url=state.index,
        quiet=state.quiet,
        dry_run=args.dry_run,
        outdated=args.outdated,
        lock_only=state.installstate.lock_only,
    )


def cmd_graph(args, state):
    """Displays currently-installed dependency graph information."""
    from pipenv.routines.graph import do_graph

    do_graph(
        state.project,
        bare=args.bare,
        json=args.json_output,
        json_tree=args.json_tree,
        reverse=args.reverse,
    )


def cmd_open(args, state):
    """View a given module in your editor."""
    from pipenv.utils.project import ensure_project
    from pipenv.utils.virtualenv import inline_activate_virtual_environment

    ensure_project(
        state.project,
        python=state.python,
        validate=False,
        pypi_mirror=state.pypi_mirror,
    )
    c = subprocess_run(
        [
            state.project._which("python"),
            "-c",
            f"import {args.module}; print({args.module}.__file__)",
        ]
    )
    if c.returncode:
        console.print("Module not found!", style="red")
        sys.exit(1)
    if "__init__.py" in c.stdout:
        p = Path(c.stdout.strip().rstrip("cdo")).parent
    else:
        p = c.stdout.strip().rstrip("cdo")
    console.print(f"Opening {p!r} in your EDITOR.", style="bold")
    inline_activate_virtual_environment(state.project)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR", "vi")
    os.system(f'{editor} "{p}"')
    return 0


def cmd_sync(args, state):
    """Installs all packages specified in Pipfile.lock."""
    from pipenv.routines.sync import do_sync

    if state.installstate.all_categories:
        state.installstate.categories = state.project.get_package_categories()
    else:
        _apply_default_categories(args, state)

    retcode = do_sync(
        state.project,
        dev=state.installstate.dev,
        python=state.python,
        bare=args.bare,
        clear=state.clear,
        pypi_mirror=state.pypi_mirror,
        system=state.system,
        extra_pip_args=state.installstate.extra_pip_args,
        categories=state.installstate.categories,
        site_packages=state.site_packages,
    )
    if retcode:
        sys.exit(1)


def cmd_clean(args, state):
    """Uninstalls all packages not specified in Pipfile.lock."""
    from pipenv.routines.clean import do_clean

    do_clean(
        state.project,
        python=state.python,
        dry_run=args.dry_run,
        system=state.system,
    )


def cmd_scripts(args, state):
    """Lists scripts in current environment config."""
    if not state.project.pipfile_exists:
        err.print("No Pipfile present at project home.")
        sys.exit(1)
    scripts = state.project.parsed_pipfile.get("scripts", {})
    first_column_width = max(len(word) for word in ["Command"] + list(scripts))
    second_column_width = max(len(word) for word in ["Script"] + list(scripts.values()))
    lines = [f"{command:<{first_column_width}}  Script" for command in ["Command"]]
    lines.append(f"{'-' * first_column_width}  {'-' * second_column_width}")
    lines.extend(
        f"{name:<{first_column_width}}  {script}" for name, script in scripts.items()
    )
    console.print("\n".join(line for line in lines))


def cmd_verify(args, state):
    """Verify the hash in Pipfile.lock is up-to-date."""
    if not state.project.pipfile_exists:
        err.print("No Pipfile present at project home.")
        sys.exit(1)
    if state.project.get_lockfile_hash() != state.project.calculate_pipfile_hash():
        err.print(
            "Pipfile.lock is out-of-date. Run [yellow bold]$ pipenv lock[/yellow bold] to update."
        )
        sys.exit(1)
    console.print("Pipfile.lock is up-to-date.", style="green")
    sys.exit(0)


def cmd_requirements(args, state):
    from pipenv.routines.requirements import generate_requirements

    no_lock = args.no_lock
    from_pipfile = args.from_pipfile

    if no_lock:
        from_pipfile = True

    generate_requirements(
        project=state.project,
        dev=args.dev,
        dev_only=args.dev_only,
        include_hashes=args.include_hash,
        include_markers=not args.exclude_markers,
        categories=args.req_categories,
        from_pipfile=from_pipfile,
        no_lock=no_lock,
        include_index=not args.exclude_index,
    )


def cmd_pylock(args, state):
    """Manage PEP 751 pylock.toml files."""
    from pipenv.utils.pylock import PylockFile, PylockFormatError, PylockVersionError

    project = state.project
    groups = [g.strip() for g in args.dev_groups.split(",") if g.strip()]

    if args.generate:
        if not project.lockfile_exists:
            err.print("[bold red]No Pipfile.lock found.[/bold red]")
            sys.exit(1)

        try:
            output_path = args.output or project.pylock_output_path
            pylock_file = PylockFile.from_lockfile(
                lockfile_path=project.lockfile_location,
                pylock_path=output_path,
                dev_groups=groups,
            )
            pylock_file.write()
            console.print(
                f"[bold green]Generated pylock.toml at {output_path}[/bold green]"
            )
        except Exception as e:
            err.print(f"[bold red]Error generating pylock.toml: {e}[/bold red]")
            sys.exit(1)

    elif args.from_pyproject:
        pyproject_path = Path(project.project_directory) / "pyproject.toml"
        if not pyproject_path.exists():
            err.print("[bold red]No pyproject.toml found.[/bold red]")
            sys.exit(1)

        try:
            output_path = args.output or project.pylock_output_path
            pylock_file = PylockFile.from_pyproject(
                pyproject_path=pyproject_path,
                pylock_path=output_path,
            )
            pylock_file.write()
            console.print(
                f"[bold green]Generated pylock.toml skeleton at {output_path}[/bold green]"
            )
            console.print(
                "[yellow]Note: This is a skeleton file. Package versions and hashes "
                "need to be resolved by running 'pipenv lock'.[/yellow]"
            )
        except Exception as e:
            err.print(f"[bold red]Error generating pylock.toml: {e}[/bold red]")
            sys.exit(1)

    elif args.validate:
        pylock_path = project.pylock_location
        if not pylock_path:
            err.print("[bold red]No pylock.toml found.[/bold red]")
            sys.exit(1)

        try:
            pylock_file = PylockFile.from_path(pylock_path)
            console.print(
                f"[bold green]✓ Valid pylock.toml (version {pylock_file.lock_version})[/bold green]"
            )
            console.print(f"  Created by: {pylock_file.created_by}")
            console.print(f"  Packages: {len(pylock_file.packages)}")
            if pylock_file.requires_python:
                console.print(f"  Requires Python: {pylock_file.requires_python}")
            if pylock_file.extras:
                console.print(f"  Extras: {', '.join(pylock_file.extras)}")
            if pylock_file.dependency_groups:
                console.print(
                    f"  Dependency Groups: {', '.join(pylock_file.dependency_groups)}"
                )
        except PylockVersionError as e:
            err.print(f"[bold red]Version error: {e}[/bold red]")
            sys.exit(1)
        except PylockFormatError as e:
            err.print(f"[bold red]Format error: {e}[/bold red]")
            sys.exit(1)
        except Exception as e:
            err.print(f"[bold red]Error validating pylock.toml: {e}[/bold red]")
            sys.exit(1)

    else:
        pylock_path = project.pylock_location
        if pylock_path:
            try:
                pylock_file = PylockFile.from_path(pylock_path)
                console.print(f"[bold]pylock.toml[/bold]: {pylock_path}")
                console.print(f"  Version: {pylock_file.lock_version}")
                console.print(f"  Created by: {pylock_file.created_by}")
                console.print(f"  Packages: {len(pylock_file.packages)}")
            except Exception as e:
                err.print(f"[yellow]Found pylock.toml but could not parse: {e}[/yellow]")
        else:
            console.print("[dim]No pylock.toml found.[/dim]")
            console.print(
                "Use [bold]pipenv pylock --generate[/bold] to create one from Pipfile.lock"
            )
            console.print(
                "Use [bold]pipenv pylock --from-pyproject[/bold] to create from pyproject.toml"
            )


def do_py(project, system=False, bare=False):
    if not project.virtualenv_exists:
        err.print(
            "[red]No virtualenv has been created for this project[/red] "
            f"[yellow bold]{project.project_directory}[/yellow bold] "
            "[red] yet![/red]"
        )
        sys.exit(1)

    try:
        (print if bare else console.print)(project._which("python", allow_global=system))
    except AttributeError:
        console.print("No project found!", style="red")
        sys.exit(1)


def cli(argv=None):
    """Main CLI entry point."""
    from pipenv.utils.shell import system_which

    parser = build_parser()
    args = parser.parse_args(argv)

    # Create state and populate from args
    state = State()
    state = populate_state(args, state)

    load_dot_env(state.project, quiet=state.quiet)

    from pipenv.routines.clear import do_clear
    from pipenv.utils.project import ensure_project
    from pipenv.utils.virtualenv import do_where, warn_in_virtualenv

    if "PIPENV_COLORBLIND" in os.environ:
        err.print(
            "PIPENV_COLORBLIND is deprecated, use NO_COLOR"
            " per https://no-color.org/ instead",
        )

    # Handle root-level flags (when no subcommand is given)
    if args.command is None:
        if args.man:
            if system_which("man"):
                path = Path(__file__).parent.parent / "pipenv.1"
                os.execle(system_which("man"), "man", str(path), os.environ)
                return 0
            else:
                err.print(
                    "man does not appear to be available on your system.",
                    style="bold yellow",
                )
                return 1
        if args.envs:
            console.print(
                "The following environment variables can be set, to do various things:\n"
            )
            for key in state.project.s.__dict__:
                if key.startswith("PIPENV"):
                    console.print(f"  - {key}", style="bold")
            console.print(
                "\nYou can learn more at:\n   "
                "[green]https://pipenv.pypa.io/en/latest/advanced/#configuration-with-environment-variables[/green]",
            )
            return 0
        warn_in_virtualenv(state.project)
        if args.where:
            do_where(state.project, bare=True)
            return 0
        elif args.py:
            do_py(state.project, bare=True)
            return 0
        elif args.support:
            from pipenv.help import get_pipenv_diagnostics

            get_pipenv_diagnostics(state.project)
            return 0
        elif state.clear:
            do_clear(state.project)
            return 0
        elif args.venv:
            if not state.project.virtualenv_exists:
                err.print(
                    "[red]No virtualenv has been created for this project[/red]"
                    f"[bold]{state.project.project_directory}[/bold]"
                    " [red]yet![/red]"
                )
                sys.exit(1)
            else:
                print(state.project.virtualenv_location)
                return 0
        elif args.rm:
            err.print(
                "Warning: [yellow]--rm[/yellow] is deprecated and will be removed in a future release. "
                "Use [green]`pipenv remove`[/green] instead.",
            )
            cmd_remove(args, state)
            return 0

        # --python or --site-packages passed without subcommand
        if state.python or state.site_packages:
            ensure_project(
                state.project,
                python=state.python,
                warn=True,
                site_packages=state.site_packages,
                pypi_mirror=state.pypi_mirror,
                clear=state.clear,
            )
        else:
            # No flags and no subcommand: print help
            parser.print_help()
        return 0

    # Handle subcommand
    warn_in_virtualenv(state.project)
    args.func(args, state)


if __name__ == "__main__":
    cli()
