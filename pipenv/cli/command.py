import os
import sys

from pipenv import environments
from pipenv.__version__ import __version__
from pipenv._compat import fix_utf8
from pipenv.cli.options import (
    CONTEXT_SETTINGS, PipenvGroup, code_option, common_options, deploy_option,
    general_options, install_options, lock_options, pass_state,
    pypi_mirror_option, python_option, site_packages_option, skip_lock_option,
    sync_options, system_option, three_option, uninstall_options, verbose_option
)
from pipenv.exceptions import PipenvOptionsError
from pipenv.patched import crayons
from pipenv.utils import subprocess_run
from pipenv.vendor.click import (
    Choice, argument, echo, edit, group, option, pass_context, secho, types,
    version_option
)


subcommand_context = CONTEXT_SETTINGS.copy()
subcommand_context.update({
    "ignore_unknown_options": True,
    "allow_extra_args": True
})
subcommand_context_no_interspersion = subcommand_context.copy()
subcommand_context_no_interspersion["allow_interspersed_args"] = False


@group(cls=PipenvGroup, invoke_without_command=True, context_settings=CONTEXT_SETTINGS)
@option("--where", is_flag=True, default=False, help="Output project home information.")
@option("--venv", is_flag=True, default=False, help="Output virtualenv information.")
@option("--py", is_flag=True, default=False, help="Output Python interpreter information.")
@option("--envs", is_flag=True, default=False, help="Output Environment Variable options.")
@option("--rm", is_flag=True, default=False, help="Remove the virtualenv.")
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option("--man", is_flag=True, default=False, help="Display manpage.")
@option(
    "--support",
    is_flag=True,
    help="Output diagnostic information for use in GitHub issues.",
)
@general_options
@version_option(prog_name=crayons.normal("pipenv", bold=True), version=__version__)
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
    **kwargs
):
    from ..core import (
        cleanup_virtualenv, do_clear, do_py, do_where, ensure_project,
        format_help, system_which, warn_in_virtualenv
    )
    from ..utils import create_spinner

    if man:
        if system_which("man"):
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pipenv.1")
            os.execle(system_which("man"), "man", path, os.environ)
            return 0
        else:
            secho("man does not appear to be available on your system.", fg="yellow", bold=True, err=True)
            return 1
    if envs:
        echo("The following environment variables can be set, to do various things:\n")
        for key in state.project.__dict__:
            if key.startswith("PIPENV"):
                echo(f"  - {crayons.normal(key, bold=True)}")
        echo(
            "\nYou can learn more at:\n   {}".format(
                crayons.green(
                    "https://pipenv.pypa.io/en/latest/advanced/#configuration-with-environment-variables"
                )
            )
        )
        return 0
    warn_in_virtualenv(state.project)
    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            do_where(state.project, bare=True)
            return 0
        elif py:
            do_py(state.project, ctx=ctx)
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
                echo(
                    "{}({}){}".format(
                        crayons.red("No virtualenv has been created for this project"),
                        crayons.normal(state.project.project_directory, bold=True),
                        crayons.red(" yet!")
                    ),
                    err=True,
                )
                ctx.abort()
            else:
                echo(state.project.virtualenv_location)
                return 0
        # --rm was passed...
        elif rm:
            # Abort if --system (or running in a virtualenv).
            if state.project.s.PIPENV_USE_SYSTEM or environments.is_in_virtualenv():
                echo(
                    crayons.red(
                        "You are attempting to remove a virtualenv that "
                        "Pipenv did not create. Aborting."
                    )
                )
                ctx.abort()
            if state.project.virtualenv_exists:
                loc = state.project.virtualenv_location
                echo(
                    crayons.normal(
                        "{} ({})...".format(
                            crayons.normal("Removing virtualenv", bold=True),
                            crayons.green(loc),
                        )
                    )
                )
                with create_spinner(text="Running...", setting=state.project.s):
                    # Remove the virtualenv.
                    cleanup_virtualenv(state.project, bare=True)
                return 0
            else:
                echo(
                    crayons.red(
                        "No virtualenv has been created for this project yet!",
                        bold=True,
                    ),
                    err=True,
                )
                ctx.abort()
    # --two / --three was passed...
    if (state.python or state.three is not None) or state.site_packages:
        ensure_project(
            state.project,
            three=state.three,
            python=state.python,
            warn=True,
            site_packages=state.site_packages,
            pypi_mirror=state.pypi_mirror,
            clear=state.clear,
        )
    # Check this again before exiting for empty ``pipenv`` command.
    elif ctx.invoked_subcommand is None:
        # Display help to user, if no commands were passed.
        echo(format_help(ctx.get_help()))


@cli.command(
    short_help="Installs provided packages and adds them to Pipfile, or (if no packages are given), installs all packages from Pipfile.",
    context_settings=subcommand_context,
)
@system_option
@code_option
@deploy_option
@site_packages_option
@skip_lock_option
@install_options
@pass_state
def install(
    state,
    **kwargs
):
    """Installs provided packages and adds them to Pipfile, or (if no packages are given), installs all packages from Pipfile."""
    from ..core import do_install

    do_install(
        state.project,
        dev=state.installstate.dev,
        three=state.three,
        python=state.python,
        pypi_mirror=state.pypi_mirror,
        system=state.system,
        lock=not state.installstate.skip_lock,
        ignore_pipfile=state.installstate.ignore_pipfile,
        skip_lock=state.installstate.skip_lock,
        requirementstxt=state.installstate.requirementstxt,
        sequential=state.installstate.sequential,
        pre=state.installstate.pre,
        code=state.installstate.code,
        deploy=state.installstate.deploy,
        keep_outdated=state.installstate.keep_outdated,
        selective_upgrade=state.installstate.selective_upgrade,
        index_url=state.index,
        extra_index_url=state.extra_index_urls,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        site_packages=state.site_packages
    )


@cli.command(
    short_help="Uninstalls a provided package and removes it from Pipfile.",
    context_settings=subcommand_context
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
def uninstall(
    ctx,
    state,
    all_dev=False,
    all=False,
    **kwargs
):
    """Uninstalls a provided package and removes it from Pipfile."""
    from ..core import do_uninstall
    retcode = do_uninstall(
        state.project,
        packages=state.installstate.packages,
        editable_packages=state.installstate.editables,
        three=state.three,
        python=state.python,
        system=state.system,
        lock=not state.installstate.skip_lock,
        all_dev=all_dev,
        all=all,
        keep_outdated=state.installstate.keep_outdated,
        pypi_mirror=state.pypi_mirror,
        ctx=ctx
    )
    if retcode:
        sys.exit(retcode)


LOCK_HEADER = """\
#
# These requirements were autogenerated by pipenv
# To regenerate from the project's Pipfile, run:
#
#    pipenv lock {options}
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
def lock(
    ctx,
    state,
    **kwargs
):
    """Generates Pipfile.lock."""
    from ..core import do_init, do_lock, ensure_project

    # Ensure that virtualenv is available.
    # Note that we don't pass clear on to ensure_project as it is also
    # handled in do_lock
    ensure_project(
        state.project, three=state.three, python=state.python, pypi_mirror=state.pypi_mirror,
        warn=(not state.quiet), site_packages=state.site_packages,
    )
    emit_requirements = state.lockoptions.emit_requirements
    dev = state.installstate.dev
    dev_only = state.lockoptions.dev_only
    pre = state.installstate.pre
    if emit_requirements:
        # Emit requirements file header (unless turned off with --no-header)
        if state.lockoptions.emit_requirements_header:
            header_options = ["--requirements"]
            if dev_only:
                header_options.append("--dev-only")
            elif dev:
                header_options.append("--dev")
            echo(LOCK_HEADER.format(options=" ".join(header_options)))
            # TODO: Emit pip-compile style header
            if dev and not dev_only:
                echo(LOCK_DEV_NOTE)
        # Setting "emit_requirements=True" means do_init() just emits the
        # install requirements file to stdout, it doesn't install anything
        do_init(
            state.project,
            dev=dev,
            dev_only=dev_only,
            emit_requirements=emit_requirements,
            pypi_mirror=state.pypi_mirror,
            pre=pre,
        )
    elif state.lockoptions.dev_only:
        raise PipenvOptionsError(
            "--dev-only",
            "--dev-only is only permitted in combination with --requirements. "
            "Aborting."
        )
    do_lock(
        state.project,
        ctx=ctx,
        clear=state.clear,
        pre=pre,
        keep_outdated=state.installstate.keep_outdated,
        pypi_mirror=state.pypi_mirror,
        write=not state.quiet,
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
@argument("shell_args", nargs=-1)
@pypi_mirror_option
@three_option
@python_option
@pass_state
def shell(
    state,
    fancy=False,
    shell_args=None,
    anyway=False,
):
    """Spawns a shell within the virtualenv."""
    from ..core import do_shell, load_dot_env

    # Prevent user from activating nested environments.
    if "PIPENV_ACTIVE" in os.environ:
        # If PIPENV_ACTIVE is set, VIRTUAL_ENV should always be set too.
        venv_name = os.environ.get("VIRTUAL_ENV", "UNKNOWN_VIRTUAL_ENVIRONMENT")
        if not anyway:
            echo(
                "{} {} {}\nNo action taken to avoid nested environments.".format(
                    crayons.normal("Shell for"),
                    crayons.green(venv_name, bold=True),
                    crayons.normal("already activated.", bold=True),
                ),
                err=True,
            )
            sys.exit(1)
    # Load .env file.
    load_dot_env(state.project)
    # Use fancy mode for Windows.
    if os.name == "nt":
        fancy = True
    do_shell(
        state.project,
        three=state.three,
        python=state.python,
        fancy=fancy,
        shell_args=shell_args,
        pypi_mirror=state.pypi_mirror,
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
    from ..core import do_run
    do_run(
        state.project, command=command, args=args, three=state.three, python=state.python, pypi_mirror=state.pypi_mirror
    )


@cli.command(
    short_help="Checks for PyUp Safety security vulnerabilities and against"
               " PEP 508 markers provided in Pipfile.",
    context_settings=subcommand_context
)
@option(
    "--unused",
    nargs=1,
    default="",
    type=types.STRING,
    help="Given a code path, show potentially unused dependencies.",
)
@option(
    "--db",
    nargs=1,
    default=lambda: os.environ.get('PIPENV_SAFETY_DB'),
    help="Path to a local PyUp Safety vulnerabilities database."
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
    type=Choice(["default", "json", "full-report", "bare"]),
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
    "--quiet",
    is_flag=True,
    help="Quiet standard output, except vulnerability report."
)
@common_options
@system_option
@argument("args", nargs=-1)
@pass_state
def check(
    state,
    unused=False,
    db=None,
    style=False,
    ignore=None,
    output="default",
    key=None,
    quiet=False,
    args=None,
    **kwargs
):
    """Checks for PyUp Safety security vulnerabilities and against PEP 508 markers provided in Pipfile."""
    from ..core import do_check

    do_check(
        state.project,
        three=state.three,
        python=state.python,
        system=state.system,
        unused=unused,
        db=db,
        ignore=ignore,
        output=output,
        key=key,
        quiet=quiet,
        args=args,
        pypi_mirror=state.pypi_mirror,
    )


@cli.command(short_help="Runs lock, then sync.", context_settings=CONTEXT_SETTINGS)
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option(
    "--outdated", is_flag=True, default=False, help="List out-of-date dependencies."
)
@option("--dry-run", is_flag=True, default=None, help="List out-of-date dependencies.")
@install_options
@pass_state
@pass_context
def update(
    ctx,
    state,
    bare=False,
    dry_run=None,
    outdated=False,
    **kwargs
):
    """Runs lock, then sync."""
    from ..core import do_lock, do_outdated, do_sync, ensure_project
    ensure_project(
        state.project, three=state.three, python=state.python, pypi_mirror=state.pypi_mirror,
        warn=(not state.quiet), site_packages=state.site_packages, clear=state.clear
    )
    if not outdated:
        outdated = bool(dry_run)
    if outdated:
        do_outdated(state.project, clear=state.clear, pre=state.installstate.pre, pypi_mirror=state.pypi_mirror)
    packages = [p for p in state.installstate.packages if p]
    editable = [p for p in state.installstate.editables if p]
    if not packages:
        echo(
            "{} {} {} {}{}".format(
                crayons.normal("Running", bold=True),
                crayons.yellow("$ pipenv lock", bold=True),
                crayons.normal("then", bold=True),
                crayons.yellow("$ pipenv sync", bold=True),
                crayons.normal(".", bold=True),
            )
        )
    else:
        for package in packages + editable:
            if package not in state.project.all_packages:
                echo(
                    "{}: {} was not found in your Pipfile! Aborting."
                    "".format(
                        crayons.red("Warning", bold=True),
                        crayons.green(package, bold=True),
                    ),
                    err=True,
                )
                ctx.abort()
    do_lock(
        state.project,
        ctx=ctx,
        clear=state.clear,
        pre=state.installstate.pre,
        keep_outdated=state.installstate.keep_outdated,
        pypi_mirror=state.pypi_mirror,
        write=not state.quiet,
    )
    do_sync(
        state.project,
        dev=state.installstate.dev,
        three=state.three,
        python=state.python,
        bare=bare,
        dont_upgrade=not state.installstate.keep_outdated,
        user=False,
        clear=state.clear,
        unused=False,
        sequential=state.installstate.sequential,
        pypi_mirror=state.pypi_mirror,
    )


@cli.command(
    short_help="Displays currently-installed dependency graph information.",
    context_settings=CONTEXT_SETTINGS
)
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option("--json", is_flag=True, default=False, help="Output JSON.")
@option("--json-tree", is_flag=True, default=False, help="Output JSON in nested tree.")
@option("--reverse", is_flag=True, default=False, help="Reversed dependency graph.")
@pass_state
def graph(state, bare=False, json=False, json_tree=False, reverse=False):
    """Displays currently-installed dependency graph information."""
    from ..core import do_graph

    do_graph(state.project, bare=bare, json=json, json_tree=json_tree, reverse=reverse)


@cli.command(
    short_help="View a given module in your editor.", name="open",
    context_settings=CONTEXT_SETTINGS
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
    from ..core import ensure_project, inline_activate_virtual_environment

    # Ensure that virtualenv is available.
    ensure_project(
        state.project, three=state.three, python=state.python,
        validate=False, pypi_mirror=state.pypi_mirror,
    )
    c = subprocess_run(
        [state.project._which("python"), "-c", "import {0}; print({0}.__file__)".format(module)]
    )
    if c.returncode:
        echo(crayons.red("Module not found!"))
        sys.exit(1)
    if "__init__.py" in c.stdout:
        p = os.path.dirname(c.stdout.strip().rstrip("cdo"))
    else:
        p = c.stdout.strip().rstrip("cdo")
    echo(crayons.normal(f"Opening {p!r} in your EDITOR.", bold=True))
    inline_activate_virtual_environment(state.project)
    edit(filename=p)
    return 0


@cli.command(
    short_help="Installs all packages specified in Pipfile.lock.",
    context_settings=CONTEXT_SETTINGS
)
@system_option
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@sync_options
@pass_state
@pass_context
def sync(
    ctx,
    state,
    bare=False,
    user=False,
    unused=False,
    **kwargs
):
    """Installs all packages specified in Pipfile.lock."""
    from ..core import do_sync

    retcode = do_sync(
        state.project,
        dev=state.installstate.dev,
        three=state.three,
        python=state.python,
        bare=bare,
        dont_upgrade=(not state.installstate.keep_outdated),
        user=user,
        clear=state.clear,
        unused=unused,
        sequential=state.installstate.sequential,
        pypi_mirror=state.pypi_mirror,
        system=state.system
    )
    if retcode:
        ctx.abort()


@cli.command(
    short_help="Uninstalls all packages not specified in Pipfile.lock.",
    context_settings=CONTEXT_SETTINGS
)
@option("--bare", is_flag=True, default=False, help="Minimal output.")
@option("--dry-run", is_flag=True, default=False, help="Just output unneeded packages.")
@verbose_option
@three_option
@python_option
@pass_state
def clean(state, dry_run=False, bare=False, user=False):
    """Uninstalls all packages not specified in Pipfile.lock."""
    from ..core import do_clean
    do_clean(state.project, three=state.three, python=state.python, dry_run=dry_run,
             system=state.system)


@cli.command(
    short_help="Lists scripts in current environment config.",
    context_settings=subcommand_context_no_interspersion,
)
@common_options
@pass_state
def scripts(state):
    """Lists scripts in current environment config."""
    if not state.project.pipfile_exists:
        echo("No Pipfile present at project home.", err=True)
        sys.exit(1)
    scripts = state.project.parsed_pipfile.get('scripts', {})
    first_column_width = max(len(word) for word in ["Command"] + list(scripts))
    second_column_width = max(len(word) for word in ["Script"] + list(scripts.values()))
    lines = ["{0:<{width}}  Script".format("Command", width=first_column_width)]
    lines.append("{}  {}".format("-" * first_column_width, "-" * second_column_width))
    lines.extend(
        "{0:<{width}}  {1}".format(name, script, width=first_column_width)
        for name, script in scripts.items()
    )
    echo("\n".join(fix_utf8(line) for line in lines))


if __name__ == "__main__":
    cli()
