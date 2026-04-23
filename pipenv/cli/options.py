import argparse
import os
import re
from pathlib import Path

from pipenv.project import Project
from pipenv.utils.internet import is_valid_url

# Use SUPPRESS as default for options shared between the root parser and
# subparsers.  This prevents subparser defaults from overwriting values
# already parsed by the root parser (e.g. ``pipenv --python 3.11 sync``).
_SHARED_DEFAULT = argparse.SUPPRESS


class State:
    def __init__(self):
        self.index = None
        self.verbose = False
        self.quiet = False
        self.pypi_mirror = None
        self.python = None
        self.site_packages = None
        self.clear = False
        self.system = False
        self.project = Project()
        self.installstate = InstallState()
        self.lockoptions = LockOptions()


class InstallState:
    def __init__(self):
        self.dev = False
        self.pre = False
        self.ignore_pipfile = False
        self.code = False
        self.requirementstxt = None
        self.deploy = False
        self.packages = []
        self.editables = []
        self.extra_pip_args = []
        self.categories = []
        self.skip_lock = False
        self.all_categories = False


class LockOptions:
    def __init__(self):
        self.dev_only = False


def parse_categories(value):
    if not value:
        return []
    return [category for category in re.split(r", *| ", value) if category]


def setup_verbosity(state, value):
    if not value:
        return
    state.project.s.PIPENV_VERBOSITY = value


def validate_python_path(value):
    if isinstance(value, (str, bytes)):
        path = Path(value)
        if path.is_absolute() and not path.is_file():
            raise ValueError(f"Expected Python at path {value} does not exist")
    return value


def validate_bool_or_none(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    from pipenv.utils.shell import env_to_bool

    try:
        return env_to_bool(str(value))
    except ValueError:
        return bool(value)


def validate_pypi_mirror(value):
    if value and not is_valid_url(value):
        raise ValueError(f"Invalid PyPI mirror URL: {value}")
    return value


# ── Argument-adder functions (argparse) ──────────────────────────────────────

# ── Individual argument-adder functions ──────────────────────────────────────


def _add_index_option(p):
    p.add_argument(
        "-i",
        "--index",
        dest="index",
        default=None,
        metavar="URL",
        help="Specify target package index by url or index name from Pipfile.",
    )


def _add_editable_option(p):
    p.add_argument(
        "-e",
        "--editable",
        dest="editables",
        action="append",
        default=None,
        metavar="PATH",
        help="An editable Python package URL or path.",
    )


def _add_ignore_pipfile_option(p):
    p.add_argument(
        "--ignore-pipfile",
        dest="ignore_pipfile",
        action="store_true",
        default=None,
        help="Ignore Pipfile when installing, using the Pipfile.lock.",
    )


def _add_dev_option(p, help_text="Install both develop and default packages."):
    p.add_argument(
        "--dev", "-d", dest="dev", action="store_true", default=None, help=help_text
    )


def _add_categories_option(p):
    p.add_argument(
        "--categories",
        dest="categories",
        default=None,
        help="Space/comma-separated list of dependency categories.",
    )


def _add_extras_option(p):
    p.add_argument(
        "--extras",
        dest="extras",
        default=None,
        help="Install optional extra categories alongside default packages.",
    )


def _add_all_categories_option(p):
    p.add_argument(
        "--all",
        dest="all_categories",
        action="store_true",
        default=None,
        help="Install packages from all categories defined in the Pipfile.",
    )


def _add_pre_option(p):
    p.add_argument(
        "--pre", dest="pre", action="store_true", default=None, help="Allow pre-releases."
    )


def _add_package_arg(p):
    p.add_argument("packages", nargs="*", default=[], help="Package(s) to operate on.")


def _add_extra_pip_args(p):
    p.add_argument(
        "--extra-pip-args",
        dest="extra_pip_args",
        default=None,
        help="Additional arguments passed directly to pip.",
    )


def _add_python_option(p):
    p.add_argument(
        "--python",
        dest="python",
        default=_SHARED_DEFAULT,
        help="Specify which version of Python virtualenv should use.",
    )


def _add_pypi_mirror_option(p):
    p.add_argument(
        "--pypi-mirror", dest="pypi_mirror", default=_SHARED_DEFAULT, help="Specify a PyPI mirror."
    )


def _add_verbose_option(p):
    p.add_argument(
        "--verbose",
        "-v",
        dest="verbose",
        action="store_true",
        default=_SHARED_DEFAULT,
        help="Verbose mode.",
    )


def _add_quiet_option(p):
    p.add_argument(
        "--quiet",
        "-q",
        dest="quiet",
        action="store_true",
        default=_SHARED_DEFAULT,
        help="Quiet mode.",
    )


def _add_site_packages_option(p):
    p.set_defaults(site_packages=None)
    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--site-packages",
        dest="site_packages",
        action="store_true",
        help="Enable site-packages for the virtualenv.",
    )
    grp.add_argument(
        "--no-site-packages",
        dest="site_packages",
        action="store_false",
        help="Disable site-packages for the virtualenv.",
    )


def _add_clear_option(p):
    p.add_argument(
        "--clear",
        dest="clear",
        action="store_true",
        default=_SHARED_DEFAULT,
        help="Clears caches (pipenv, pip).",
    )


def _add_system_option(p):
    p.add_argument(
        "--system",
        dest="system",
        action="store_true",
        default=_SHARED_DEFAULT,
        help="System pip management.",
    )


def _add_requirementstxt_option(p):
    p.add_argument(
        "--requirements",
        "-r",
        dest="requirementstxt",
        default=None,
        metavar="FILE",
        help="Import a requirements.txt file.",
    )


def _add_dev_only_flag(p):
    p.add_argument(
        "--dev-only",
        dest="dev_only",
        action="store_true",
        default=None,
        help="Emit development dependencies *only* (overrides --dev).",
    )


def _add_deploy_option(p):
    p.add_argument(
        "--deploy",
        dest="deploy",
        action="store_true",
        default=None,
        help="Abort if the Pipfile.lock is out-of-date, or Python version is wrong.",
    )


def _add_lock_only_option(p):
    p.add_argument(
        "--lock-only",
        dest="lock_only",
        action="store_true",
        default=None,
        help="Only update lock file (specifiers not added to Pipfile).",
    )


def _add_skip_lock_option(p):
    p.add_argument(
        "--skip-lock",
        dest="skip_lock",
        action="store_true",
        default=None,
        help="Install from Pipfile bypassing lock mechanisms.",
    )


# ── Option group composers ────────────────────────────────────────────────────


def _add_common_options(p):
    _add_pypi_mirror_option(p)
    _add_verbose_option(p)
    _add_quiet_option(p)
    _add_clear_option(p)
    _add_python_option(p)


def _add_general_options(p):
    _add_common_options(p)
    _add_site_packages_option(p)


def _add_install_base_options(p):
    _add_common_options(p)
    _add_pre_option(p)
    _add_extra_pip_args(p)


def _add_sync_options(p):
    _add_install_base_options(p)
    _add_dev_option(p)
    _add_categories_option(p)
    _add_extras_option(p)
    _add_all_categories_option(p)


def _add_install_options(p):
    _add_sync_options(p)
    _add_index_option(p)
    _add_requirementstxt_option(p)
    _add_ignore_pipfile_option(p)
    _add_editable_option(p)
    _add_package_arg(p)
    _add_skip_lock_option(p)


def _add_lock_options(p):
    _add_install_base_options(p)
    _add_dev_option(p, help_text="Generate both develop and default requirements.")
    _add_dev_only_flag(p)
    _add_categories_option(p)


def _add_uninstall_options(p):
    _add_install_base_options(p)
    _add_categories_option(p)
    _add_extras_option(p)
    _add_dev_option(p, help_text="Uninstall packages from dev-packages.")
    _add_editable_option(p)
    _add_package_arg(p)
    _add_skip_lock_option(p)


def _add_upgrade_options(p):
    _add_lock_only_option(p)


# ── PIPENV_ environment variable overlay ─────────────────────────────────────

# Destination names for boolean (store_true) arguments — needed to apply the
# right type conversion when reading PIPENV_* env vars.
_BOOL_DESTS = frozenset(
    {
        "verbose",
        "quiet",
        "clear",
        "system",
        "dev",
        "pre",
        "ignore_pipfile",
        "deploy",
        "lock_only",
        "skip_lock",
        "dev_only",
        "all_categories",
    }
)

# Destinations that use a non-standard env var name.
_EXPLICIT_ENV_VARS = {
    "index": "PIP_INDEX_URL",
    "skip_lock": "PIPENV_SKIP_LOCK",
}


def apply_env_vars(namespace):
    """Overlay PIPENV_* environment variables onto a parsed argparse Namespace.

    For each attribute still set to None (not explicitly provided on the CLI),
    check for a corresponding ``PIPENV_<DEST>`` environment variable and apply
    it.  This replicates click's ``auto_envvar_prefix="PIPENV"`` behaviour.
    """
    from pipenv.utils.shell import env_to_bool

    for dest in vars(namespace):
        if getattr(namespace, dest) is not None:
            continue  # CLI value takes precedence

        env_key = _EXPLICIT_ENV_VARS.get(dest, f"PIPENV_{dest.upper()}")
        raw = os.environ.get(env_key)
        if raw is None:
            continue

        if dest in _BOOL_DESTS:
            try:
                setattr(namespace, dest, env_to_bool(raw))
            except ValueError:
                pass
        else:
            setattr(namespace, dest, raw)


# ── Main parser factory ───────────────────────────────────────────────────────


class _PipenvArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that appends 'Did you mean …?' suggestions
    when the user types an unrecognised subcommand name."""

    def error(self, message: str) -> None:
        import difflib
        import re

        m = re.search(r"invalid choice: '([^']+)'", message)
        if m:
            attempted = m.group(1)
            # Collect known subcommand names from the registered choices.
            known: list[str] = []
            for action in self._actions:
                if isinstance(action, argparse._SubParsersAction):
                    known = list(action.choices)
                    break
            suggestions = difflib.get_close_matches(attempted, known, n=1, cutoff=0.6)
            if suggestions:
                message += f"  Did you mean '{suggestions[0]}'?"
        super().error(message)


def build_parser():
    """Build and return the top-level ArgumentParser for pipenv.

    This is the argparse replacement for the click ``@group`` + ``@command``
    structure in cli/command.py.  Command implementations are wired up in
    Phase 3.
    """
    from pipenv.__version__ import __version__

    parser = _PipenvArgumentParser(
        prog="pipenv",
        description="Python Development Workflow for Humans.",
        add_help=False,
    )

    # Root-level flags (replaces the cli() group body)
    parser.add_argument(
        "-h",
        "--help",
        dest="help",
        action="store_true",
        default=False,
        help="Show this message and exit.",
    )
    parser.add_argument(
        "--version", action="version", version=f"pipenv, version {__version__}"
    )
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
        help="Remove the virtualenv. [deprecated: use `pipenv remove`]",
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
    _add_general_options(parser)

    subs = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── install ──────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "install",
        add_help=False,
        help="Install provided packages and add them to Pipfile.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_system_option(p)
    _add_deploy_option(p)
    _add_site_packages_option(p)
    _add_install_options(p)

    # ── remove ───────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "remove", add_help=False, help="Remove the virtualenv for the current project."
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)

    # ── upgrade ──────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "upgrade",
        add_help=False,
        help="Resolve provided packages and add them to Pipfile.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_system_option(p)
    _add_site_packages_option(p)
    _add_install_options(p)
    _add_upgrade_options(p)

    # ── uninstall ─────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "uninstall",
        add_help=False,
        help="Uninstall a provided package and remove it from Pipfile.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument(
        "--all-dev",
        dest="all_dev",
        action="store_true",
        default=False,
        help="Uninstall all packages from [dev-packages].",
    )
    p.add_argument(
        "--all",
        dest="all",
        action="store_true",
        default=False,
        help="Purge all packages from virtualenv. Does not edit Pipfile.",
    )
    _add_uninstall_options(p)

    # ── lock ─────────────────────────────────────────────────────────────────
    p = subs.add_parser("lock", add_help=False, help="Generate Pipfile.lock.")
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_lock_options(p)

    # ── shell ─────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "shell", add_help=False, help="Spawn a shell within the virtualenv."
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument(
        "--fancy", action="store_true", default=False, help="Run shell in fancy mode."
    )
    p.add_argument(
        "--anyway",
        action="store_true",
        default=False,
        help="Always spawn a sub-shell, even if one is already spawned.",
    )
    p.add_argument(
        "--quiet",
        "-q",
        dest="quiet",
        action="store_true",
        default=False,
        help="Quiet standard output.",
    )
    p.add_argument("shell_args", nargs="*", default=[])
    _add_pypi_mirror_option(p)
    _add_python_option(p)

    # ── activate ──────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "activate",
        add_help=False,
        help="Output the activation command for the virtualenv.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_pypi_mirror_option(p)
    _add_python_option(p)

    # ── run ───────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "run", add_help=False, help="Spawn a command installed into the virtualenv."
    )
    # Only -h/--help and --system are intentionally kept on the run subparser:
    #   -h/--help — needed so ``pipenv run --help`` shows run-specific help.
    #     -h/--help placed *before* run_command triggers help; anything after
    #     the command name is captured by ``run_args`` (nargs=REMAINDER) so
    #     e.g. ``pipenv run psql -h host`` passes -h through to psql. See #6641.
    #   --system  — pipenv-specific flag used by do_run() to skip venv creation.
    #
    # Do NOT add _add_common_options here.  The run subparser must not
    # recognise flags like --verbose / -v / --quiet / --python because they
    # would be consumed by argparse instead of being passed through to the
    # user's command.  Use ``pipenv --verbose run …`` for pipenv verbosity.
    # See: https://github.com/pypa/pipenv/issues/6626
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_system_option(p)
    #
    # Use dest="run_command" to avoid overwriting the subparser dest ("command").
    # ``run_args`` uses argparse.REMAINDER so that every argument after the
    # command name — including flags that happen to collide with pipenv's own
    # options like ``-h`` — is captured verbatim and passed through unchanged.
    p.add_argument(
        "run_command", metavar="command", nargs="?", default=None, help="Command to run."
    )
    p.add_argument(
        "run_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS
    )

    # ── check ─────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "check",
        add_help=False,
        help="[DEPRECATED] Check for PyUp Safety security vulnerabilities.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument(
        "--db",
        dest="db",
        default=None,
        help="Path or URL to a PyUp Safety vulnerabilities database.",
    )
    p.add_argument(
        "--ignore",
        "-i",
        dest="ignore",
        action="append",
        default=None,
        help="Ignore specified vulnerability during PyUp Safety checks.",
    )
    p.add_argument(
        "--output",
        dest="output",
        choices=["default", "json", "full-report", "bare", "screen", "text", "minimal"],
        default="default",
        help="Output format.",
    )
    p.add_argument("--key", dest="key", default=None, help="Safety API key from PyUp.io.")
    p.add_argument("--policy-file", dest="policy_file", default="")
    p.add_argument("--exit-code", dest="exit_code", action="store_true", default=True)
    p.add_argument("--continue-on-error", dest="exit_code", action="store_false")
    p.add_argument(
        "--audit-and-monitor", dest="audit_and_monitor", action="store_true", default=True
    )
    p.add_argument(
        "--disable-audit-and-monitor", dest="audit_and_monitor", action="store_false"
    )
    p.add_argument("--project", dest="project", default=None)
    p.add_argument("--save-json", dest="save_json", default="")
    p.add_argument(
        "--use-installed", dest="use_installed", action="store_true", default=False
    )
    p.add_argument("--categories", dest="categories", default="")
    p.add_argument(
        "--auto-install", dest="auto_install", action="store_true", default=False
    )
    p.add_argument(
        "--scan",
        dest="scan",
        action="store_true",
        default=False,
        help="Use the new scan command instead of the deprecated check command.",
    )
    _add_common_options(p)
    _add_system_option(p)

    # ── audit ─────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "audit",
        add_help=False,
        help="Audit packages for security vulnerabilities using pip-audit.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument(
        "--output",
        "-f",
        dest="output",
        choices=["columns", "json", "cyclonedx-json", "cyclonedx-xml", "markdown"],
        default="columns",
    )
    p.add_argument(
        "--vulnerability-service",
        "-s",
        dest="vulnerability_service",
        choices=["pypi", "osv"],
        default="pypi",
    )
    p.add_argument("--ignore", "-i", dest="ignore", action="append", default=None)
    p.add_argument("--fix", dest="fix", action="store_true", default=False)
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
    p.add_argument("--strict", dest="strict", action="store_true", default=False)
    p.add_argument(
        "--skip-editable", dest="skip_editable", action="store_true", default=False
    )
    p.add_argument("--no-deps", dest="no_deps", action="store_true", default=False)
    p.add_argument("--local", dest="local", action="store_true", default=False)
    p.add_argument("--desc", dest="desc", action="store_true", default=False)
    p.add_argument("--aliases", dest="aliases", action="store_true", default=False)
    p.add_argument("--output-file", "-o", dest="output_file", default=None)
    p.add_argument("--locked", dest="locked", action="store_true", default=False)
    _add_common_options(p)
    _add_system_option(p)

    # ── update ────────────────────────────────────────────────────────────────
    p = subs.add_parser("update", add_help=False, help="Run lock, then sync.")
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument("--bare", dest="bare", action="store_true", default=False)
    p.add_argument("--outdated", dest="outdated", action="store_true", default=False)
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="List packages that would be updated without updating.",
    )
    _add_system_option(p)
    _add_install_options(p)
    _add_upgrade_options(p)

    # ── graph ─────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "graph",
        add_help=False,
        help="Display currently-installed dependency graph information.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument("--bare", action="store_true", default=False)
    p.add_argument("--json", action="store_true", default=False)
    p.add_argument("--json-tree", dest="json_tree", action="store_true", default=False)
    p.add_argument("--reverse", action="store_true", default=False)

    # ── open ──────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "open", add_help=False, help="View a given module in your editor."
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_common_options(p)
    p.add_argument("module", help="Module to open.")

    # ── sync ──────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "sync", add_help=False, help="Install all packages specified in Pipfile.lock."
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_system_option(p)
    p.add_argument("--bare", action="store_true", default=False)
    _add_sync_options(p)
    _add_site_packages_option(p)

    # ── clean ─────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "clean",
        add_help=False,
        help="Uninstall all packages not specified in Pipfile.lock.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument("--bare", action="store_true", default=False)
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
    _add_verbose_option(p)
    _add_python_option(p)

    # ── scripts ───────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "scripts", add_help=False, help="List scripts in current environment config."
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    _add_common_options(p)

    # ── verify ────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "verify", add_help=False, help="Verify the hash in Pipfile.lock is up-to-date."
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)

    # ── requirements ──────────────────────────────────────────────────────────
    p = subs.add_parser(
        "requirements",
        add_help=False,
        help="Generate a requirements.txt from Pipfile.lock.",
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument("--dev", dest="dev", action="store_true", default=False)
    p.add_argument("--dev-only", dest="dev_only", action="store_true", default=False)
    p.add_argument("--hash", dest="hash", action="store_true", default=False)
    p.add_argument(
        "--exclude-markers", dest="exclude_markers", action="store_true", default=False
    )
    p.add_argument(
        "--exclude-index", dest="exclude_index", action="store_true", default=False
    )
    p.add_argument("--categories", dest="categories", default="")
    p.add_argument(
        "--from-pipfile", dest="from_pipfile", action="store_true", default=False
    )
    p.add_argument("--no-lock", dest="no_lock", action="store_true", default=False)

    # ── pylock ────────────────────────────────────────────────────────────────
    p = subs.add_parser(
        "pylock", add_help=False, help="Manage PEP 751 pylock.toml files."
    )
    p.add_argument("-h", "--help", dest="help", action="store_true", default=False)
    p.add_argument("--generate", action="store_true", default=False)
    p.add_argument(
        "--from-pyproject", dest="from_pyproject", action="store_true", default=False
    )
    p.add_argument("--validate", action="store_true", default=False)
    p.add_argument("--output", "-o", dest="output", default=None)
    p.add_argument("--dev-groups", dest="dev_groups", default="dev")
    _add_common_options(p)

    return parser


# ── State builder (argparse Namespace → State) ────────────────────────────────


def build_state(args):
    """Construct a :class:`State` object from a parsed argparse :class:`~argparse.Namespace`.

    Call :func:`apply_env_vars` on *args* before calling this function so that
    ``PIPENV_*`` environment variables are already reflected in the namespace.

    Performs the same validation and verbosity setup that the click callbacks
    formerly handled inline.
    """
    state = State()

    # ── Global / common fields ───────────────────────────────────────────────
    state.index = getattr(args, "index", None)
    state.pypi_mirror = getattr(args, "pypi_mirror", None)
    state.python = getattr(args, "python", None) or ""
    state.site_packages = getattr(args, "site_packages", None)
    state.clear = bool(getattr(args, "clear", None))
    state.system = bool(getattr(args, "system", None))
    state.verbose = bool(getattr(args, "verbose", None))
    state.quiet = bool(getattr(args, "quiet", None))

    # ── Validation ───────────────────────────────────────────────────────────
    if state.python:
        try:
            state.python = validate_python_path(state.python)
        except ValueError as e:
            from pipenv.exceptions import PipenvUsageError

            raise PipenvUsageError(str(e))

    if state.pypi_mirror:
        try:
            state.pypi_mirror = validate_pypi_mirror(state.pypi_mirror)
        except ValueError as e:
            from pipenv.exceptions import PipenvUsageError

            raise PipenvUsageError(str(e))

    # ── Verbosity ────────────────────────────────────────────────────────────
    if state.verbose and state.quiet:
        from pipenv.exceptions import PipenvUsageError

        raise PipenvUsageError(
            "--verbose and --quiet are mutually exclusive! Please choose one!"
        )
    if state.verbose:
        setup_verbosity(state, 1)
    elif state.quiet:
        setup_verbosity(state, -1)

    # ── InstallState ─────────────────────────────────────────────────────────
    state.installstate.dev = bool(getattr(args, "dev", None))
    state.installstate.pre = bool(getattr(args, "pre", None))
    state.installstate.ignore_pipfile = bool(getattr(args, "ignore_pipfile", None))
    state.installstate.deploy = bool(getattr(args, "deploy", None))
    state.installstate.skip_lock = bool(getattr(args, "skip_lock", None))
    state.installstate.lock_only = bool(getattr(args, "lock_only", None))
    state.installstate.all_categories = bool(getattr(args, "all_categories", None))
    state.installstate.requirementstxt = getattr(args, "requirementstxt", None)

    raw_extra_pip_args = getattr(args, "extra_pip_args", None)
    if raw_extra_pip_args:
        state.installstate.extra_pip_args = raw_extra_pip_args.split()

    state.installstate.packages = list(getattr(args, "packages", []))
    state.installstate.editables = list(getattr(args, "editables", None) or [])

    raw_categories = getattr(args, "categories", None)
    if raw_categories:
        state.installstate.categories = parse_categories(raw_categories)

    # ── LockOptions ──────────────────────────────────────────────────────────
    state.lockoptions.dev_only = bool(getattr(args, "dev_only", None))

    return state


def apply_default_categories(args, state):
    """Apply ``PIPENV_DEFAULT_CATEGORIES`` when no explicit categories were set.

    Argparse equivalent of ``_apply_default_categories()`` in cli/command.py.
    In the click version, ``ParameterSource`` was used to distinguish explicit
    CLI/env-var values from defaults.  With our sentinel approach (``None``
    means "not provided"), the same distinction is made by checking whether
    ``args.categories`` and ``args.dev`` are still ``None`` *after*
    :func:`apply_env_vars` has run.
    """
    if getattr(args, "categories", None) is not None:
        return  # --categories was explicitly set
    if getattr(args, "dev", None) is not None:
        return  # --dev was explicitly set
    if state.installstate.categories:
        return  # already populated
    default_categories = parse_categories(state.project.s.PIPENV_DEFAULT_CATEGORIES)
    if default_categories:
        state.installstate.categories = default_categories
