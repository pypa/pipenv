import glob
import os
import pathlib
import re
import sys

from pipenv.patched.pip._vendor.platformdirs import user_cache_dir
from pipenv.utils.fileutils import normalize_drive
from pipenv.utils.shell import env_to_bool, is_env_truthy, isatty

# HACK: avoid resolver.py uses the wrong byte code files.
# I hope I can remove this one day.

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def get_from_env(arg, prefix="PIPENV", check_for_negation=True, default=None):
    """
    Check the environment for a variable, returning its truthy or stringified value

    For example, setting ``PIPENV_NO_RESOLVE_VCS=1`` would mean that
    ``get_from_env("RESOLVE_VCS", prefix="PIPENV")`` would return ``False``.

    :param str arg: The name of the variable to look for
    :param str prefix: The prefix to attach to the variable, defaults to "PIPENV"
    :param bool check_for_negation: Whether to check for ``<PREFIX>_NO_<arg>``, defaults
        to True
    :param Optional[Union[str, bool]] default: The value to return if the environment variable does
        not exist, defaults to None
    :return: The value from the environment if available
    :rtype: Optional[Union[str, bool]]
    """
    negative_lookup = f"NO_{arg}"
    positive_lookup = arg
    if prefix:
        positive_lookup = f"{prefix}_{arg}"
        negative_lookup = f"{prefix}_{negative_lookup}"
    if positive_lookup in os.environ:
        value = os.environ[positive_lookup]
        try:
            return env_to_bool(value)
        except ValueError:
            return value
    if check_for_negation and negative_lookup in os.environ:
        value = os.environ[negative_lookup]
        try:
            return not env_to_bool(value)
        except ValueError:
            return value
    return default


def normalize_pipfile_path(p):
    if p is None:
        return None
    loc = pathlib.Path(p)
    try:
        loc = loc.resolve()
    except OSError:
        loc = loc.absolute()
    # Recase the path properly on Windows. From https://stackoverflow.com/a/35229734/5043728
    if os.name == "nt":
        matches = glob.glob(re.sub(r"([^:/\\])(?=[/\\]|$)", r"[\1]", str(loc)))
        path_str = matches and matches[0] or str(loc)
    else:
        path_str = str(loc)
    return normalize_drive(os.path.abspath(path_str))


# HACK: Prevent invalid shebangs with Homebrew-installed Python:
# https://bugs.python.org/issue22490
os.environ.pop("__PYVENV_LAUNCHER__", None)
# Internal, to tell whether the command line session is interactive.
SESSION_IS_INTERACTIVE = isatty(sys.stdout)

# TF_BUILD indicates to Azure pipelines it is a build step
PIPENV_IS_CI = get_from_env("CI", prefix="", check_for_negation=False) or is_env_truthy(
    "TF_BUILD"
)


NO_COLOR = False
if os.getenv("NO_COLOR") or os.getenv("PIPENV_COLORBLIND"):
    NO_COLOR = True
    from pipenv.utils.shell import style_no_color
    from pipenv.vendor import click

    click.original_style = click.style
    click.style = style_no_color

PIPENV_HIDE_EMOJIS = (
    os.environ.get("PIPENV_HIDE_EMOJIS") is None
    and (os.name == "nt" or PIPENV_IS_CI)
    or is_env_truthy("PIPENV_HIDE_EMOJIS")
)
"""Disable emojis in output.

Default is to show emojis. This is automatically set on Windows.
"""


class Setting:
    """
    Control various settings of pipenv via environment variables.
    """

    def __init__(self) -> None:
        self.USING_DEFAULT_PYTHON = True
        """Use the default Python"""

        #: Location for Pipenv to store it's package cache.
        #: Default is to use appdir's user cache directory.
        self.PIPENV_CACHE_DIR = get_from_env(
            "CACHE_DIR", check_for_negation=False, default=user_cache_dir("pipenv")
        )

        # Tells Pipenv which Python to default to, when none is provided.
        self.PIPENV_DEFAULT_PYTHON_VERSION = get_from_env(
            "DEFAULT_PYTHON_VERSION", check_for_negation=False
        )
        """Use this Python version when creating new virtual environments by default.

        This can be set to a version string, e.g. ``3.9``, or a path. Default is to use
        whatever Python Pipenv is installed under (i.e. ``sys.executable``). Command
        line flags (e.g. ``--python``) are prioritized over
        this configuration.
        """

        self.PIPENV_DONT_LOAD_ENV = bool(
            get_from_env("DONT_LOAD_ENV", check_for_negation=False)
        )
        """If set, Pipenv does not load the ``.env`` file.

        Default is to load ``.env`` for ``run`` and ``shell`` commands.
        """

        self.PIPENV_DONT_USE_PYENV = bool(
            get_from_env("DONT_USE_PYENV", check_for_negation=False)
        )
        """If set, Pipenv does not attempt to install Python with pyenv.

        Default is to install Python automatically via pyenv when needed, if possible.
        """

        self.PIPENV_DONT_USE_ASDF = bool(
            get_from_env("DONT_USE_ASDF", check_for_negation=False)
        )
        """If set, Pipenv does not attempt to install Python with asdf.

        Default is to install Python automatically via asdf when needed, if possible.
        """

        self.PIPENV_DOTENV_LOCATION = get_from_env(
            "DOTENV_LOCATION", check_for_negation=False
        )
        """If set, Pipenv loads the ``.env`` file at the specified location.

        Default is to load ``.env`` from the project root, if found.
        """

        self.PIPENV_EMULATOR = get_from_env("EMULATOR", default="")
        """If set, the terminal emulator's name for ``pipenv shell`` to use.

        Default is to detect emulators automatically. This should be set if your
        emulator, e.g. Cmder, cannot be detected correctly.
        """

        self.PIPENV_IGNORE_VIRTUALENVS = bool(get_from_env("IGNORE_VIRTUALENVS"))
        """If set, Pipenv will always assign a virtual environment for this project.

        By default, Pipenv tries to detect whether it is run inside a virtual
        environment, and reuses it if possible. This is usually the desired behavior,
        and enables the user to use any user-built environments with Pipenv.
        """

        self.PIPENV_INSTALL_TIMEOUT = int(
            get_from_env("INSTALL_TIMEOUT", default=60 * 15)
        )
        """Max number of seconds to wait for package installation.

        Defaults to 900 (15 minutes), a very long arbitrary time.
        """

        # NOTE: +1 because of a temporary bug in Pipenv.
        self.PIPENV_MAX_DEPTH = int(get_from_env("MAX_DEPTH", default=10)) + 1
        """Maximum number of directories to recursively search for a Pipfile.

        Default is 3. See also ``PIPENV_NO_INHERIT``.
        """

        self.PIPENV_MAX_RETRIES = (
            int(get_from_env("MAX_RETRIES", default=1)) if PIPENV_IS_CI else 0
        )
        """Specify how many retries Pipenv should attempt for network requests.

        Default is 0. Automatically set to 1 on CI environments for robust testing.
        """

        self.PIPENV_NO_INHERIT = bool(
            get_from_env("NO_INHERIT", check_for_negation=False)
        )
        """Tell Pipenv not to inherit parent directories.

        This is useful for deployment to avoid using the wrong current directory.
        Overwrites ``PIPENV_MAX_DEPTH``.
        """
        if self.PIPENV_NO_INHERIT:
            self.PIPENV_MAX_DEPTH = 2

        self.PIPENV_NOSPIN = bool(get_from_env("NOSPIN", check_for_negation=False))
        """If set, disable terminal spinner.

        This can make the logs cleaner. Automatically set on Windows, and in CI
        environments.
        """
        if PIPENV_IS_CI:
            self.PIPENV_NOSPIN = True

        if self.PIPENV_NOSPIN:
            from pipenv.patched.pip._vendor.rich import _spinners

            _spinners.SPINNERS[None] = {"interval": 80, "frames": "   "}
            self.PIPENV_SPINNER = None
        else:
            pipenv_spinner = "bouncingBar" if os.name == "nt" else "dots"
            self.PIPENV_SPINNER = get_from_env(
                "SPINNER", check_for_negation=False, default=pipenv_spinner
            )
        """Sets the default spinner type.

        You can see which spinners are available by running::

            $ python -m pipenv.patched.pip._vendor.rich.spinner
        """

        pipenv_pipfile = get_from_env("PIPFILE", check_for_negation=False)
        if pipenv_pipfile:
            if not os.path.isfile(pipenv_pipfile):
                raise RuntimeError("Given PIPENV_PIPFILE is not found!")

            else:
                pipenv_pipfile = normalize_pipfile_path(pipenv_pipfile)
                # Overwrite environment variable so that subprocesses can get the correct path.
                # See https://github.com/pypa/pipenv/issues/3584
                os.environ["PIPENV_PIPFILE"] = pipenv_pipfile
        self.PIPENV_PIPFILE = pipenv_pipfile
        """If set, this specifies a custom Pipfile location.

        When running pipenv from a location other than the same directory where the
        Pipfile is located, instruct pipenv to find the Pipfile in the location
        specified by this environment variable.

        Default is to find Pipfile automatically in the current and parent directories.
        See also ``PIPENV_MAX_DEPTH``.
        """

        self.PIPENV_PYPI_MIRROR = get_from_env("PYPI_MIRROR", check_for_negation=False)
        """If set, tells pipenv to override PyPI index urls with a mirror.

        Default is to not mirror PyPI, i.e. use the real one, pypi.org. The
        ``--pypi-mirror`` command line flag overwrites this.
        """

        self.PIPENV_QUIET = bool(get_from_env("QUIET", check_for_negation=False))
        """If set, makes Pipenv quieter.

        Default is unset, for normal verbosity. ``PIPENV_VERBOSE`` overrides this.
        """

        self.PIPENV_SHELL_EXPLICIT = get_from_env("SHELL", check_for_negation=False)
        """An absolute path to the preferred shell for ``pipenv shell``.

        Default is to detect automatically what shell is currently in use.
        """
        # Hack because PIPENV_SHELL is actually something else. Internally this
        # variable is called PIPENV_SHELL_EXPLICIT instead.

        self.PIPENV_SHELL_FANCY = bool(get_from_env("SHELL_FANCY"))
        """If set, always use fancy mode when invoking ``pipenv shell``.

        Default is to use the compatibility shell if possible.
        """

        self.PIPENV_TIMEOUT = int(
            get_from_env("TIMEOUT", check_for_negation=False, default=120)
        )
        """Max number of seconds Pipenv will wait for virtualenv creation to complete.

        Default is 120 seconds, an arbitrary number that seems to work.
        """

        self.PIPENV_REQUESTS_TIMEOUT = int(
            get_from_env("REQUESTS_TIMEOUT", check_for_negation=False, default=10)
        )
        """Timeout setting for requests.

        Default is 10 seconds.

        For more information on the role of Timeout in Requests, see
        [Requests docs](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts).
        """

        self.PIPENV_VENV_IN_PROJECT = get_from_env("VENV_IN_PROJECT")
        """ When set True, will create or use the ``.venv`` in your project directory.
        When Set False, will ignore the .venv in your project directory even if it exists.
        If unset (default), will use the .venv of project directory should it exist, otherwise
        will create new virtual environments in a global location.
        """

        self.PIPENV_VERBOSE = bool(get_from_env("VERBOSE", check_for_negation=False))
        """If set, makes Pipenv more wordy.

        Default is unset, for normal verbosity. This takes precedence over
        ``PIPENV_QUIET``.
        """

        self.PIPENV_YES = bool(get_from_env("YES"))
        """If set, Pipenv automatically assumes "yes" at all prompts.

        Default is to prompt the user for an answer if the current command line session
        if interactive.
        """

        self.PIPENV_SKIP_LOCK = bool(get_from_env("SKIP_LOCK"))
        """If set, Pipenv won't lock dependencies automatically.

        This might be desirable if a project has large number of dependencies,
        because locking is an inherently slow operation.

        Default is to lock dependencies and update ``Pipfile.lock`` on each run.

        Usage: `export PIPENV_SKIP_LOCK=true` OR `export PIPENV_SKIP_LOCK=1` to skip automatic locking

        NOTE: This only affects the ``install`` and ``uninstall`` commands.
        """

        self.PIP_EXISTS_ACTION = get_from_env(
            "EXISTS_ACTION", prefix="PIP", check_for_negation=False, default="w"
        )
        """Specifies the value for pip's --exists-action option

        Defaults to ``(w)ipe``
        """

        self.PIPENV_RESOLVE_VCS = bool(get_from_env("RESOLVE_VCS", default=True))
        """Tells Pipenv whether to resolve all VCS dependencies in full.

        As of Pipenv 2018.11.26, only editable VCS dependencies were resolved in full.
        To retain this behavior and avoid handling any conflicts that arise from the new
        approach, you may disable this.
        """

        self.PIPENV_CUSTOM_VENV_NAME = get_from_env(
            "CUSTOM_VENV_NAME", check_for_negation=False
        )
        """Tells Pipenv whether to name the venv something other than the default dir name."""

        self.PIPENV_VIRTUALENV_CREATOR = get_from_env(
            "VIRTUALENV_CREATOR", check_for_negation=False
        )
        """Tells Pipenv to use the virtualenv --creator= argument with the user specified value."""

        self.PIPENV_VIRTUALENV_COPIES = get_from_env(
            "VIRTUALENV_COPIES", check_for_negation=True
        )
        """Tells Pipenv to use the virtualenv --copies to prevent symlinks when specified as Truthy."""

        self.PIPENV_PYUP_API_KEY = get_from_env("PYUP_API_KEY", check_for_negation=False)

        # Internal, support running in a different Python from sys.executable.
        self.PIPENV_PYTHON = get_from_env("PYTHON", check_for_negation=False)

        # Internal, overwrite all index functionality.
        self.PIPENV_TEST_INDEX = get_from_env("TEST_INDEX", check_for_negation=False)

        # Internal, for testing the resolver without using subprocess
        self.PIPENV_RESOLVER_PARENT_PYTHON = get_from_env("RESOLVER_PARENT_PYTHON")

        # Internal, tells Pipenv about the surrounding environment.
        self.PIPENV_USE_SYSTEM = False
        self.PIPENV_VIRTUALENV = None
        if "PIPENV_ACTIVE" not in os.environ and not self.PIPENV_IGNORE_VIRTUALENVS:
            self.PIPENV_VIRTUALENV = os.environ.get("VIRTUAL_ENV")

        # Internal, tells Pipenv to skip case-checking (slow internet connections).
        # This is currently always set to True for performance reasons.
        self.PIPENV_SKIP_VALIDATION = True

        # Internal, the default shell to use if shell detection fails.
        self.PIPENV_SHELL = (
            os.environ.get("SHELL")
            or os.environ.get("PYENV_SHELL")
            or os.environ.get("COMSPEC")
        )

        # Internal, consolidated verbosity representation as an integer. The default
        # level is 0, increased for wordiness and decreased for terseness.
        try:
            self.PIPENV_VERBOSITY = int(get_from_env("VERBOSITY"))
        except (ValueError, TypeError):
            if self.PIPENV_VERBOSE:
                self.PIPENV_VERBOSITY = 1
            elif self.PIPENV_QUIET:
                self.PIPENV_VERBOSITY = -1
            else:
                self.PIPENV_VERBOSITY = 0
        del self.PIPENV_QUIET
        del self.PIPENV_VERBOSE

    def is_verbose(self, threshold=1):
        return threshold <= self.PIPENV_VERBOSITY

    def is_quiet(self, threshold=-1):
        return threshold >= self.PIPENV_VERBOSITY


def is_using_venv() -> bool:
    """Check for venv-based virtual environment which sets sys.base_prefix"""
    if getattr(sys, "real_prefix", None) is not None:
        # virtualenv venvs
        result = True
    else:
        # PEP 405 venvs
        result = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    return result


def is_in_virtualenv():
    """
    Check virtualenv membership dynamically

    :return: True or false depending on whether we are in a regular virtualenv or not
    :rtype: bool
    """

    pipenv_active = os.environ.get("PIPENV_ACTIVE", False)
    virtual_env = bool(os.environ.get("VIRTUAL_ENV"))
    ignore_virtualenvs = bool(get_from_env("IGNORE_VIRTUALENVS"))
    return virtual_env and not (pipenv_active or ignore_virtualenvs)


PIPENV_SPINNER_FAIL_TEXT = "✘ {0}" if not PIPENV_HIDE_EMOJIS else "{0}"
PIPENV_SPINNER_OK_TEXT = "✔ {0}" if not PIPENV_HIDE_EMOJIS else "{0}"
