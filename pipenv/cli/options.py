"""CLI options and state management for pipenv using argparse."""

import argparse
import os
import re
from pathlib import Path

from pipenv.project import Project
from pipenv.utils import err
from pipenv.utils.internet import is_valid_url

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "auto_envvar_prefix": "PIPENV"}


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


def validate_python_path(value):
    """Validate that an absolute Python path exists."""
    if isinstance(value, (str, bytes)):
        path = Path(value)
        if path.is_absolute() and not path.is_file():
            err.print(f"Error: Expected Python at path {value} does not exist", style="red")
            raise SystemExit(2)
    return value


def validate_pypi_mirror(value):
    if value and not is_valid_url(value):
        err.print(f"Error: Invalid PyPI mirror URL: {value}", style="red")
        raise SystemExit(2)
    return value


def _get_envvar(name, prefix="PIPENV"):
    """Get environment variable value with optional prefix."""
    full_name = f"{prefix}_{name}" if prefix else name
    return os.environ.get(full_name)


def _get_envvar_bool(name, prefix="PIPENV", default=False):
    """Get boolean environment variable."""
    val = _get_envvar(name, prefix)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes")


# --- Option registration functions ---
# Each function adds arguments to a parser.
# They mirror the old click option decorators.

def add_index_option(parser):
    parser.add_argument(
        "-i", "--index",
        default=os.environ.get("PIP_INDEX_URL"),
        help="Specify target package index by url or index name from Pipfile.",
    )


def add_editable_option(parser):
    parser.add_argument(
        "-e", "--editable",
        action="append",
        default=[],
        metavar="PATH",
        help="An editable Python package URL or path, often to a VCS repository.",
    )


def add_ignore_pipfile_option(parser):
    parser.add_argument(
        "--ignore-pipfile",
        action="store_true",
        default=_get_envvar_bool("IGNORE_PIPFILE"),
        help="Ignore Pipfile when installing, using the Pipfile.lock.",
    )


def add_dev_option(parser, help_text="Install both develop and default packages"):
    parser.add_argument(
        "--dev", "-d",
        action="store_true",
        default=_get_envvar_bool("DEV"),
        help=help_text,
    )


def add_categories_option(parser):
    parser.add_argument(
        "--categories",
        default="",
        help="Specify package categories.",
    )


def add_extras_option(parser):
    parser.add_argument(
        "--extras",
        default="",
        help="Install optional extra categories alongside default packages.",
    )


def add_all_categories_option(parser):
    parser.add_argument(
        "--all",
        dest="all_categories",
        action="store_true",
        default=False,
        help="Install packages from all categories defined in the Pipfile.",
    )


def add_pre_option(parser):
    parser.add_argument(
        "--pre",
        action="store_true",
        default=False,
        help="Allow pre-releases.",
    )


def add_package_arg(parser):
    parser.add_argument(
        "packages",
        nargs="*",
        default=[],
        help="Packages to install/uninstall.",
    )


def add_extra_pip_args(parser):
    parser.add_argument(
        "--extra-pip-args",
        default="",
        help="Extra arguments to pass to pip.",
    )


def add_python_option(parser):
    parser.add_argument(
        "--python",
        default="",
        help="Specify which version of Python virtualenv should use.",
    )


def add_pypi_mirror_option(parser):
    parser.add_argument(
        "--pypi-mirror",
        default=None,
        help="Specify a PyPI mirror.",
    )


def add_verbose_option(parser):
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Verbose mode.",
    )


def add_quiet_option(parser):
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Quiet mode.",
    )


def add_site_packages_option(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--site-packages",
        action="store_true",
        default=None,
        help="Enable site-packages for the virtualenv.",
    )
    group.add_argument(
        "--no-site-packages",
        action="store_true",
        default=None,
        help="Disable site-packages for the virtualenv.",
    )


def add_clear_option(parser):
    parser.add_argument(
        "--clear",
        action="store_true",
        default=_get_envvar_bool("CLEAR"),
        help="Clears caches (pipenv, pip).",
    )


def add_system_option(parser):
    parser.add_argument(
        "--system",
        action="store_true",
        default=_get_envvar_bool("SYSTEM"),
        help="System pip management.",
    )


def add_requirementstxt_option(parser):
    parser.add_argument(
        "--requirements", "-r",
        dest="requirementstxt",
        default="",
        help="Import a requirements.txt file.",
    )


def add_dev_only_flag(parser):
    parser.add_argument(
        "--dev-only",
        action="store_true",
        default=False,
        help="Emit development dependencies *only* (overrides --dev)",
    )


def add_deploy_option(parser):
    parser.add_argument(
        "--deploy",
        action="store_true",
        default=False,
        help="Abort if the Pipfile.lock is out-of-date, or Python version is wrong.",
    )


def add_lock_only_option(parser):
    parser.add_argument(
        "--lock-only",
        action="store_true",
        default=False,
        help="Only update lock file (specifiers not added to Pipfile).",
    )


def add_skip_lock_option(parser):
    parser.add_argument(
        "--skip-lock",
        action="store_true",
        default=_get_envvar_bool("SKIP_LOCK"),
        help="Install from Pipfile bypassing lock mechanisms.",
    )


def add_keep_outdated_option(parser):
    """Removed option - shows deprecation warning if used."""
    parser.add_argument(
        "--keep-outdated",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )


def add_selective_upgrade_option(parser):
    """Removed option - shows deprecation warning if used."""
    parser.add_argument(
        "--selective-upgrade",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )


# --- Composite option groups ---

def add_common_options(parser):
    add_pypi_mirror_option(parser)
    add_verbose_option(parser)
    add_quiet_option(parser)
    add_clear_option(parser)
    add_python_option(parser)


def add_install_base_options(parser):
    add_common_options(parser)
    add_pre_option(parser)
    add_extra_pip_args(parser)
    add_keep_outdated_option(parser)


def add_uninstall_options(parser):
    add_install_base_options(parser)
    add_categories_option(parser)
    add_extras_option(parser)
    add_dev_option(parser, "Uninstall packages from dev-packages.")
    add_editable_option(parser)
    add_package_arg(parser)
    add_skip_lock_option(parser)


def add_lock_options(parser):
    add_install_base_options(parser)
    add_dev_option(parser, "Generate both develop and default requirements")
    add_dev_only_flag(parser)
    add_categories_option(parser)


def add_sync_options(parser):
    add_install_base_options(parser)
    add_dev_option(parser, "Install both develop and default packages")
    add_categories_option(parser)
    add_extras_option(parser)
    add_all_categories_option(parser)


def add_install_options(parser):
    add_sync_options(parser)
    add_index_option(parser)
    add_requirementstxt_option(parser)
    add_ignore_pipfile_option(parser)
    add_editable_option(parser)
    add_package_arg(parser)
    add_skip_lock_option(parser)
    add_selective_upgrade_option(parser)


def add_upgrade_options(parser):
    add_lock_only_option(parser)


def add_general_options(parser):
    add_common_options(parser)
    add_site_packages_option(parser)



def setup_verbosity(state):
    """Configure verbosity on the state's project settings."""
    if state.verbose:
        state.project.s.PIPENV_VERBOSITY = 1
    elif state.quiet:
        state.project.s.PIPENV_VERBOSITY = -1


def populate_state(args, state=None):
    """Populate a State object from parsed argparse args."""
    if state is None:
        state = State()

    # Common options
    if hasattr(args, "index") and args.index:
        state.index = args.index
    if hasattr(args, "verbose") and args.verbose:
        state.verbose = True
    if hasattr(args, "quiet") and args.quiet:
        state.quiet = True
    if state.verbose and state.quiet:
        err.print(
            "Error: --verbose and --quiet are mutually exclusive! Please choose one!",
            style="red",
        )
        raise SystemExit(2)

    if hasattr(args, "pypi_mirror") and args.pypi_mirror:
        state.pypi_mirror = validate_pypi_mirror(args.pypi_mirror)
    elif state.project.s.PIPENV_PYPI_MIRROR:
        state.pypi_mirror = validate_pypi_mirror(state.project.s.PIPENV_PYPI_MIRROR)

    if hasattr(args, "python") and args.python:
        state.python = validate_python_path(args.python)
    if hasattr(args, "clear") and args.clear:
        state.clear = True
    if hasattr(args, "system") and args.system:
        state.system = True

    # Site packages handling
    if hasattr(args, "site_packages") and args.site_packages:
        state.site_packages = True
    elif hasattr(args, "no_site_packages") and args.no_site_packages:
        state.site_packages = False

    # Install state
    if hasattr(args, "dev") and args.dev:
        state.installstate.dev = True
    if hasattr(args, "pre") and args.pre:
        state.installstate.pre = True
    if hasattr(args, "ignore_pipfile") and args.ignore_pipfile:
        state.installstate.ignore_pipfile = True
    if hasattr(args, "deploy") and args.deploy:
        state.installstate.deploy = True
    if hasattr(args, "packages") and args.packages:
        state.installstate.packages = list(args.packages)
    if hasattr(args, "editable") and args.editable:
        state.installstate.editables = list(args.editable)
    if hasattr(args, "extra_pip_args") and args.extra_pip_args:
        state.installstate.extra_pip_args = args.extra_pip_args.split(" ")
    if hasattr(args, "requirementstxt") and args.requirementstxt:
        state.installstate.requirementstxt = args.requirementstxt
    if hasattr(args, "skip_lock") and args.skip_lock:
        err.print(
            "The flag --skip-lock has been reintroduced (but is not recommended).  "
            "Without the lock resolver it is difficult to manage multiple package indexes, "
            "and hash checking is not provided.  "
            "However it can help manage installs with current deficiencies in locking across platforms.",
            style="yellow bold",
        )
        state.installstate.skip_lock = True
    if hasattr(args, "all_categories") and args.all_categories:
        state.installstate.all_categories = True
    if hasattr(args, "lock_only") and args.lock_only:
        state.installstate.lock_only = True

    # Categories
    if hasattr(args, "categories") and args.categories:
        state.installstate.categories += parse_categories(args.categories)

    # Extras
    if hasattr(args, "extras") and args.extras:
        extras = parse_categories(args.extras)
        if "packages" not in state.installstate.categories:
            state.installstate.categories.insert(0, "packages")
        state.installstate.categories += extras

    # Lock options
    if hasattr(args, "dev_only") and args.dev_only:
        state.lockoptions.dev_only = True

    # Removed options - show deprecation warnings
    if hasattr(args, "keep_outdated") and args.keep_outdated:
        err.print(
            "The flag --keep-outdated has been removed.  "
            "The flag did not respect package resolver results and lead to inconsistent lock files.  "
            "Consider using the `pipenv upgrade` command to selectively upgrade packages.",
            style="yellow bold",
        )
        raise SystemExit(1)

    if hasattr(args, "selective_upgrade") and args.selective_upgrade:
        err.print(
            "The flag --selective-upgrade has been removed.  "
            "The flag was buggy and lead to inconsistent lock files.  "
            "Consider using the `pipenv upgrade` command to selectively upgrade packages.",
            style="yellow bold",
        )
        raise SystemExit(1)

    setup_verbosity(state)
    return state


# Track which options were explicitly set on the command line
class ParameterSourceTracker:
    """Tracks whether parameters came from CLI, env, or defaults."""

    def __init__(self, args, parser):
        self._explicit = set()
        # Check which arguments were explicitly provided on the command line
        # by comparing against defaults
        defaults = vars(parser.parse_args([]))  # Parse empty to get defaults
        parsed = vars(args)
        for key, value in parsed.items():
            default_val = defaults.get(key)
            if value != default_val:
                self._explicit.add(key)
        # Also check env vars
        self._from_env = set()
        for key in parsed:
            envvar_name = f"PIPENV_{key.upper()}"
            if os.environ.get(envvar_name) is not None:
                self._from_env.add(key)

    def is_explicit(self, name):
        """Check if a parameter was explicitly set (CLI or env)."""
        return name in self._explicit or name in self._from_env

    def is_default(self, name):
        """Check if a parameter was left at its default."""
        return not self.is_explicit(name)
