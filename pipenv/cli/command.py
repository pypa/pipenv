import os
import sys

from pipenv import environments
from pipenv.__version__ import __version__
from pipenv.cli.options import (
    CONTEXT_SETTINGS,
    PipenvGroup,
    common_options,
    deploy_option,
    general_options,
    install_options,
    lock_options,
    pass_state,
    pypi_mirror_option,
    python_option,
    site_packages_option,
    sync_options,
    system_option,
    uninstall_options,
    upgrade_options,
    verbose_option,
)
from pipenv.utils import console, err
from pipenv.utils.environment import load_dot_env
from pipenv.utils.processes import subprocess_run
from pipenv.vendor.click import (
    Choice,
    argument,
    edit,
    group,
    option,
    pass_context,
    version_option,
)

with console.capture() as capture:
    console.print("[bold]pipenv[/bold]", end="")

prog_name = capture.get()

subcommand_context = CONTEXT_SETTINGS.copy()
subcommand_context.update({"ignore_unknown_options": True, "allow_extra_args": True})
subcommand_context_no_interspersion = subcommand_context.copy()
subcommand_context_no_interspersion["allow_interspersed_args"] = False


@group(cls=PipenvGroup, invoke_without_command=True, context_settings=CONTEXT_SETTINGS)
@option("--where", is_flag=True, default=False, help="Output project home information.")
@option("--venv", is_flag=True, default=False, help="Output virtualenv information.")
@option(
    "--py", is_flag=True, default=False, help="Output Python interpreter information."
)
@option(
    "--envs", is_flag=True, default=False, help="Output Environment Variable options."
)
@option("--rm", is_flag=True, default=False, help="Remove the virtualenv.")
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option("--man", is_flag=True, default=False, help="Display manpage.")
@option(
    "--support",
    is_flag=True,
    help="Output diagnostic information for use in GitHub issues.",
)
@general_options
@version_option(prog_name=prog_name, version=__version__)
@pass_state
@pass_context
def cli(
    ctx,
    state,
    where=False,
    venv=False,
    py=False,
    envs=False,
    rm=False,
    bare=False,
    man=False,
    support=None,
    help=False,
    site_packages=None,
    **kwargs,
):
    from pipenv.utils.shell import system_which

    load_dot_env(state.project, quiet=state.quiet)

    from pipenv.routines.clear import do_clear
    from pipenv.utils.display import format_help
    from pipenv.utils.project import ensure_project
    from pipenv.utils.virtualenv import cleanup_virtualenv, do_where, warn_in_virtualenv

    if "PIPENV_COLORBLIND" in os.environ:
        err.print(
            "PIPENV_COLORBLIND is deprecated, use NO_COLOR"
            " per https://no-color.org/ instead",
        )

    if man:
        if system_which("man"):
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pipenv.1")
            os.execle(system_which("man"), "man", path, os.environ)
            return 0
        else:
            err.print(
                "man does not appear to be available on your system.", style="bold yellow"
            )
            return 1
    if envs:
        console.print(
            "The following environment variables can be set, to do various things:\n"
        )
        for key in state.project.__dict__:
            if key.startswith("PIPENV"):
                console.print(f"  - {key}", style="bold")
        console.print(
            "\nYou can learn more at:\n   "
            "[green]https://pipenv.pypa.io/en/latest/advanced/#configuration-with-environment-variables[/green]",
        )
        return 0
    warn_in_virtualenv(state.project)
    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            do_where(state.project, bare=True)
            return 0
        elif py:
            do_py(state.project, ctx=ctx, bare=True)
            return 0
        # --support was passed...
        elif support:
            from ..help import get_pipenv_diagnostics

            get_pipenv_diagnostics(state.project)
            return 0
        # --clear was passed...
        elif state.clear:
            do_clear(state.project)
            return 0
        # --venv was passed...
        elif venv:
            # There is no virtualenv yet.
            if not state.project.virtualenv_exists:
                err.print(
                    "[red]No virtualenv has been created for this project[/red]"
                    f"[bold]{state.project.project_directory}[/bold]"
                    " [red]yet![/red]"
                )
                ctx.abort()
            else:
                print(state.project.virtualenv_location)
                return 0
        # --rm was passed...
        elif rm:
            # Abort if --system (or running in a virtualenv).
            if state.project.s.PIPENV_USE_SYSTEM or environments.is_in_virtualenv():
                console.print(
                    "You are attempting to remove a virtualenv that "
                    "Pipenv did not create. Aborting.",
                    style="red",
                )
                ctx.abort()
            if state.project.virtualenv_exists:
                loc = state.project.virtualenv_location
                console.print(
                    f"[bold]Removing virtualenv[/bold] ([green]{loc}[green])..."
                )

                with console.status("Running..."):
                    # Remove the virtualenv.
                    cleanup_virtualenv(state.project, bare=True)
                return 0
            else:
                err.print(
                    "No virtualenv has been created for this project yet!",
                    style="red bold",
                )
                ctx.abort()
    # --python was passed...
    if (state.python) or state.site_packages:
        ensure_project(
            state.project,
            python=state.python,
            warn=True,
            site_packages=state.site_packages,
            pypi_mirror=state.pypi_mirror,
            clear=state.clear,
        )
    elif ctx.invoked_subcommand is None:
        console.print(format_help(ctx.get_help()))


@cli.command(
    short_help="Installs provided packages and adds them to Pipfile, or (if no packages are given), installs all packages from Pipfile.",
    context_settings=subcommand_context,
)
@system_option
@deploy_option
@site_packages_option
@install_options
@pass_state
def install(state, **kwargs):
    """Installs provided packages and adds them to Pipfile,
    or (if no packages are given), installs all packages from Pipfile."""
    from pipenv.routines.install import do_install

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
        categories=state.installstate.categories,
        skip_lock=state.installstate.skip_lock,
    )


@cli.command(
    short_help="Resolves provided packages and adds them to Pipfile, or (if no packages are given), merges results to Pipfile.lock",
    context_settings=subcommand_context,
)
@system_option
@site_packages_option
@install_options
@upgrade_options
@pass_state
def upgrade(state, **kwargs):
    from pipenv.routines.update import upgrade
    from pipenv.utils.project import ensure_project

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


@cli.command(
    short_help="Uninstalls a provided package and removes it from Pipfile.",
    context_settings=subcommand_context,
)
@option(
    "--all-dev",
    is_flag=True,
    default=False,
    help="Uninstall all package from [dev-packages].",
)
@option(
    "--all",
    is_flag=True,
    default=False,
    help="Purge all package(s) from virtualenv. Does not edit Pipfile.",
)
@uninstall_options
@pass_state
@pass_context
def uninstall(ctx, state, all_dev=False, all=False, **kwargs):
    """Uninstalls a provided package and removes it from Pipfile."""
    from pipenv.routines.uninstall import do_uninstall

    pre = state.installstate.pre

    retcode = do_uninstall(
        state.project,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        python=state.python,
        system=state.system,
        lock=False,
        all_dev=all_dev,
        all=all,
        pre=pre,
        pypi_mirror=state.pypi_mirror,
        categories=state.installstate.categories,
        ctx=ctx,
    )
    if retcode:
        sys.exit(retcode)


LOCK_HEADER = """\
#
# These requirements were autogenerated by pipenv
# To regenerate from the project's Pipfile, run:
#
#    pipenv requirements {options}
#
"""


LOCK_DEV_NOTE = """\
# Note: in pipenv 2020.x, "--dev" changed to emit both default and development
# requirements. To emit only development requirements, pass "--dev-only".
"""


@cli.command(short_help="Generates Pipfile.lock.", context_settings=CONTEXT_SETTINGS)
@lock_options
@pass_state
@pass_context
def lock(ctx, state, **kwargs):
    """Generates Pipfile.lock."""
    from pipenv.routines.lock import do_lock
    from pipenv.utils.project import ensure_project

    # Ensure that virtualenv is available.
    # Note that we don't pass clear on to ensure_project as it is also
    # handled in do_lock
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


@cli.command(
    short_help="Spawns a shell within the virtualenv.",
    context_settings=subcommand_context,
)
@option(
    "--fancy",
    is_flag=True,
    default=False,
    help="Run in shell in fancy mode. Make sure the shell have no path manipulating"
    " scripts. Run $pipenv shell for issues with compatibility mode.",
)
@option(
    "--anyway",
    is_flag=True,
    default=False,
    help="Always spawn a sub-shell, even if one is already spawned.",
)
@option(
    "--quiet", is_flag=True, help="Quiet standard output, except vulnerability report."
)
@argument("shell_args", nargs=-1)
@pypi_mirror_option
@python_option
@pass_state
def shell(state, fancy=False, shell_args=None, anyway=False, quiet=False):
    """Spawns a shell within the virtualenv."""
    from pipenv.routines.shell import do_shell

    # Prevent user from activating nested environments.
    if "PIPENV_ACTIVE" in os.environ:
        # If PIPENV_ACTIVE is set, VIRTUAL_ENV should always be set too.
        venv_name = os.environ.get("VIRTUAL_ENV", "UNKNOWN_VIRTUAL_ENVIRONMENT")
        if not anyway:
            err.print(
                f"Shell for [green bold]{venv_name}[/green bold] "
                "[bold]already activated[/bold].\n"
                "New shell not activated to avoid nested environments."
            )
            sys.exit(1)

    # Use fancy mode for Windows or pwsh on *nix.
    if (
        os.name == "nt"
        or (os.environ.get("PIPENV_SHELL") or "").split(os.path.sep)[-1] == "pwsh"
        or (os.environ.get("SHELL") or "").split(os.path.sep)[-1] == "pwsh"
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


@cli.command(
    short_help="Spawns a command installed into the virtualenv.",
    context_settings=subcommand_context_no_interspersion,
)
@common_options
@argument("command")
@argument("args", nargs=-1)
@pass_state
def run(state, command, args):
    """Spawns a command installed into the virtualenv."""
    from pipenv.routines.shell import do_run

    do_run(
        state.project,
        command=command,
        args=args,
        python=state.python,
        pypi_mirror=state.pypi_mirror,
    )


@cli.command(
    short_help="Checks for PyUp Safety security vulnerabilities and against"
    " PEP 508 markers provided in Pipfile.",
    context_settings=subcommand_context,
)
@option(
    "--db",
    nargs=1,
    default=lambda: os.environ.get("PIPENV_SAFETY_DB"),
    help="Path or URL to a PyUp Safety vulnerabilities database."
    " Default: ENV PIPENV_SAFETY_DB or None.",
)
@option(
    "--ignore",
    "-i",
    multiple=True,
    help="Ignore specified vulnerability during PyUp Safety checks.",
)
@option(
    "--output",
    type=Choice(["default", "json", "full-report", "bare", "screen", "text", "minimal"]),
    default="default",
    help="Translates to --json, --full-report or --bare from PyUp Safety check",
)
@option(
    "--key",
    help="Safety API key from PyUp.io for scanning dependencies against a live"
    " vulnerabilities database. Leave blank for scanning against a"
    " database that only updates once a month.",
)
@option(
    "--quiet", is_flag=True, help="Quiet standard output, except vulnerability report."
)
@option("--policy-file", default="", help="Define the policy file to be used")
@option(
    "--exit-code/--continue-on-error",
    default=True,
    help="Output standard exit codes. Default: --exit-code",
)
@option(
    "--audit-and-monitor/--disable-audit-and-monitor",
    default=True,
    help="Send results back to pyup.io for viewing on your dashboard. Requires an API key.",
)
@option(
    "--project",
    default=None,
    help="Project to associate this scan with on pyup.io. Defaults to a canonicalized github style name if available, otherwise unknown",
)
@option(
    "--save-json",
    default="",
    help="Path to where output file will be placed, if the path is a directory, "
    "Safety will use safety-report.json as filename. Default: empty",
)
@option(
    "--use-installed",
    is_flag=True,
    help="Whether to use the lockfile as input to check (instead of result from pip list).",
)
@option(
    "--categories",
    is_flag=False,
    default="",
    help="Use the specified categories from the lockfile as input to check.",
)
@common_options
@system_option
@pass_state
def check(
    state,
    db=None,
    ignore=None,
    output="screen",
    key=None,
    quiet=False,
    exit_code=True,
    policy_file="",
    save_json="",
    audit_and_monitor=True,
    project=None,
    use_installed=False,
    categories="",
    **kwargs,
):
    """Checks for PyUp Safety security vulnerabilities and against PEP 508 markers provided in Pipfile."""
    from pipenv.routines.check import do_check

    do_check(
        state.project,
        python=state.python,
        system=state.system,
        db=db,
        ignore=ignore,
        output=output,
        key=key,
        quiet=quiet,
        verbose=state.verbose,
        exit_code=exit_code,
        policy_file=policy_file,
        save_json=save_json,
        audit_and_monitor=audit_and_monitor,
        safety_project=project,
        pypi_mirror=state.pypi_mirror,
        use_installed=use_installed,
        categories=categories,
    )


@cli.command(short_help="Runs lock, then sync.", context_settings=CONTEXT_SETTINGS)
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option("--outdated", is_flag=True, default=False, help="List out-of-date dependencies.")
@option("--dry-run", is_flag=True, default=None, help="List out-of-date dependencies.")
@install_options
@upgrade_options
@pass_state
@pass_context
def update(ctx, state, bare=False, dry_run=None, outdated=False, **kwargs):
    """Runs lock when no packages are specified, or upgrade, and then sync."""
    from pipenv.routines.update import do_update

    do_update(
        state.project,
        python=state.python,
        site_packages=state.site_packages,
        clear=state.clear,
        pre=state.installstate.pre,
        pypi_mirror=state.pypi_mirror,
        system=False,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        dev=state.installstate.dev,
        bare=bare,
        extra_pip_args=state.installstate.extra_pip_args,
        categories=state.installstate.categories,
        index_url=state.index,
        quiet=state.quiet,
        dry_run=dry_run,
        outdated=outdated,
        lock_only=state.installstate.lock_only,
    )


@cli.command(
    short_help="Displays currently-installed dependency graph information.",
    context_settings=CONTEXT_SETTINGS,
)
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option("--json", is_flag=True, default=False, help="Output JSON.")
@option("--json-tree", is_flag=True, default=False, help="Output JSON in nested tree.")
@option("--reverse", is_flag=True, default=False, help="Reversed dependency graph.")
@pass_state
def graph(state, bare=False, json=False, json_tree=False, reverse=False):
    """Displays currently-installed dependency graph information."""
    from pipenv.routines.graph import do_graph

    do_graph(state.project, bare=bare, json=json, json_tree=json_tree, reverse=reverse)


@cli.command(
    short_help="View a given module in your editor.",
    name="open",
    context_settings=CONTEXT_SETTINGS,
)
@common_options
@argument("module", nargs=1)
@pass_state
def run_open(state, module, *args, **kwargs):
    """View a given module in your editor.

    This uses the EDITOR environment variable. You can temporarily override it,
    for example:

        EDITOR=atom pipenv open requests
    """
    from pipenv.utils.project import ensure_project
    from pipenv.utils.virtualenv import inline_activate_virtual_environment

    # Ensure that virtualenv is available.
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
            f"import {module}; print({module}.__file__)",
        ]
    )
    if c.returncode:
        console.print("Module not found!", style="red")
        sys.exit(1)
    if "__init__.py" in c.stdout:
        p = os.path.dirname(c.stdout.strip().rstrip("cdo"))
    else:
        p = c.stdout.strip().rstrip("cdo")
    console.print(f"Opening {p!r} in your EDITOR.", style="bold")
    inline_activate_virtual_environment(state.project)
    edit(filename=p)
    return 0


@cli.command(
    short_help="Installs all packages specified in Pipfile.lock.",
    context_settings=CONTEXT_SETTINGS,
)
@system_option
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@sync_options
@site_packages_option
@pass_state
@pass_context
def sync(ctx, state, bare=False, user=False, unused=False, **kwargs):
    """Installs all packages specified in Pipfile.lock."""
    from pipenv.routines.sync import do_sync

    retcode = do_sync(
        state.project,
        dev=state.installstate.dev,
        python=state.python,
        bare=bare,
        clear=state.clear,
        pypi_mirror=state.pypi_mirror,
        system=state.system,
        extra_pip_args=state.installstate.extra_pip_args,
        categories=state.installstate.categories,
        site_packages=state.site_packages,
    )
    if retcode:
        ctx.abort()


@cli.command(
    short_help="Uninstalls all packages not specified in Pipfile.lock.",
    context_settings=CONTEXT_SETTINGS,
)
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option("--dry-run", is_flag=True, default=False, help="Just output unneeded packages.")
@verbose_option
@python_option
@pass_state
def clean(state, dry_run=False, bare=False, user=False):
    """Uninstalls all packages not specified in Pipfile.lock."""
    from pipenv.routines.clean import do_clean

    do_clean(
        state.project,
        python=state.python,
        dry_run=dry_run,
        system=state.system,
    )


@cli.command(
    short_help="Lists scripts in current environment config.",
    context_settings=subcommand_context_no_interspersion,
)
@common_options
@pass_state
def scripts(state):
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


@cli.command(
    short_help="Verify the hash in Pipfile.lock is up-to-date.",
    context_settings=CONTEXT_SETTINGS,
)
@pass_state
def verify(state):
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


@cli.command(
    short_help="Generate a requirements.txt from Pipfile.lock.",
    context_settings=CONTEXT_SETTINGS,
)
@option("--dev", is_flag=True, default=False, help="Also add development requirements.")
@option(
    "--dev-only", is_flag=True, default=False, help="Only add development requirements."
)
@option("--hash", is_flag=True, default=False, help="Add package hashes.")
@option("--exclude-markers", is_flag=True, default=False, help="Exclude markers.")
@option(
    "--categories",
    is_flag=False,
    default="",
    help="Only add requirement of the specified categories.",
)
@option(
    "--from-pipfile",
    is_flag=True,
    default=False,
    help="Only include dependencies from Pipfile.",
)
@pass_state
def requirements(
    state,
    dev=False,
    dev_only=False,
    hash=False,
    exclude_markers=False,
    categories="",
    from_pipfile=False,
):
    from pipenv.routines.requirements import generate_requirements

    generate_requirements(
        project=state.project,
        dev=dev,
        dev_only=dev_only,
        include_hashes=hash,
        include_markers=not exclude_markers,
        categories=categories,
        from_pipfile=from_pipfile,
    )


if __name__ == "__main__":
    cli()


def do_py(project, ctx=None, system=False, bare=False):
    if not project.virtualenv_exists:
        err.print(
            "[red]No virtualenv has been created for this project[/red] "
            f"[yellow bold]{project.project_directory}[/yellow bold] "
            "[red] yet![/red]"
        )
        ctx.abort()

    try:
        (print if bare else console.print)(project._which("python", allow_global=system))
    except AttributeError:
        console.print("No project found!", style="red")
        ctx.abort()
