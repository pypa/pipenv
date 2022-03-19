import glob
import os
import pathlib
import re
import sys

from appdirs import user_cache_dir
from vistir.path import normalize_drive

from pipenv._compat import fix_utf8
from pipenv.vendor.vistir.misc import _isatty, fs_str


# HACK: avoid resolver.py uses the wrong byte code files.
# I hope I can remove this one day.
os.environ["PYTHONDONTWRITEBYTECODE"] = fs_str("1")
_false_values = ("0", "false", "no", "off")
_true_values = ("1", "true", "yes", "on")


def env_to_bool(val):
    """
    Convert **val** to boolean, returning True if truthy or False if falsey

    :param Any val: The value to convert
    :return: False if Falsey, True if truthy
    :rtype: bool
    """
    if isinstance(val, bool):
        return val
    if val.lower() in _false_values:
        return False
    if val.lower() in _true_values:
        return True
    raise ValueError(f"Value is not a valid boolean-like: {val}")


def _is_env_truthy(name):
    """An environment variable is truthy if it exists and isn't one of (0, false, no, off)
    """
    if name not in os.environ:
        return False
    return os.environ.get(name).lower() not in _false_values


def get_from_env(arg, prefix="PIPENV", check_for_negation=True):
    """
    Check the environment for a variable, returning its truthy or stringified value

    For example, setting ``PIPENV_NO_RESOLVE_VCS=1`` would mean that
    ``get_from_env("RESOLVE_VCS", prefix="PIPENV")`` would return ``False``.

    :param str arg: The name of the variable to look for
    :param str prefix: The prefix to attach to the variable, defaults to "PIPENV"
    :param bool check_for_negation: Whether to check for ``<PREFIX>_NO_<arg>``, defaults
        to True
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
    return None


def normalize_pipfile_path(p):
    if p is None:
        return None
    loc = pathlib.Path(p)
    try:
        loc = loc.resolve()
    except OSError:
        loc = loc.absolute()
    # Recase the path properly on Windows. From https://stackoverflow.com/a/35229734/5043728
    if os.name == 'nt':
        matches = glob.glob(re.sub(r'([^:/\\])(?=[/\\]|$)', r'[\1]', str(loc)))
        path_str = matches and matches[0] or str(loc)
    else:
        path_str = str(loc)
    return normalize_drive(os.path.abspath(path_str))


# HACK: Prevent invalid shebangs with Homebrew-installed Python:
# https://bugs.python.org/issue22490
os.environ.pop("__PYVENV_LAUNCHER__", None)
# Internal, to tell whether the command line session is interactive.
SESSION_IS_INTERACTIVE = _isatty(sys.stdout)
PIPENV_IS_CI = env_to_bool(os.environ.get('CI') or os.environ.get('TF_BUILD') or False)
PIPENV_COLORBLIND = bool(os.environ.get("PIPENV_COLORBLIND"))
"""If set, disable terminal colors.

Some people don't like colors in their terminals, for some reason. Default is
to show colors.
"""

PIPENV_HIDE_EMOJIS = (
    os.environ.get("PIPENV_HIDE_EMOJIS") is None
    and (os.name == "nt" or PIPENV_IS_CI)
    or _is_env_truthy("PIPENV_HIDE_EMOJIS")
)
"""Disable emojis in output.

Default is to show emojis. This is automatically set on Windows.
"""


class Setting:
    def __init__(self) -> None:
        self.USING_DEFAULT_PYTHON = True
        self.initialize()

    def initialize(self):

        self.PIPENV_CACHE_DIR = os.environ.get("PIPENV_CACHE_DIR", user_cache_dir("pipenv"))
        """Location for Pipenv to store it's package cache.

        Default is to use appdir's user cache directory.
        """

        # Tells Pipenv which Python to default to, when none is provided.
        self.PIPENV_DEFAULT_PYTHON_VERSION = os.environ.get("PIPENV_DEFAULT_PYTHON_VERSION")
        """Use this Python version when creating new virtual environments by default.

        This can be set to a version string, e.g. ``3.9``, or a path. Default is to use
        whatever Python Pipenv is installed under (i.e. ``sys.executable``). Command
        line flags (e.g. ``--python`` and ``--three``) are prioritized over
        this configuration.
        """

        self.PIPENV_DONT_LOAD_ENV = bool(os.environ.get("PIPENV_DONT_LOAD_ENV"))
        """If set, Pipenv does not load the ``.env`` file.

        Default is to load ``.env`` for ``run`` and ``shell`` commands.
        """

        self.PIPENV_DONT_USE_PYENV = bool(os.environ.get("PIPENV_DONT_USE_PYENV"))
        """If set, Pipenv does not attempt to install Python with pyenv.

        Default is to install Python automatically via pyenv when needed, if possible.
        """

        self.PIPENV_DONT_USE_ASDF = bool(os.environ.get("PIPENV_DONT_USE_ASDF"))
        """If set, Pipenv does not attempt to install Python with asdf.

        Default is to install Python automatically via asdf when needed, if possible.
        """

        self.PIPENV_DOTENV_LOCATION = os.environ.get("PIPENV_DOTENV_LOCATION")
        """If set, Pipenv loads the ``.env`` file at the specified location.

        Default is to load ``.env`` from the project root, if found.
        """

        self.PIPENV_EMULATOR = os.environ.get("PIPENV_EMULATOR", "")
        """If set, the terminal emulator's name for ``pipenv shell`` to use.

        Default is to detect emulators automatically. This should be set if your
        emulator, e.g. Cmder, cannot be detected correctly.
        """

        self.PIPENV_IGNORE_VIRTUALENVS = bool(os.environ.get("PIPENV_IGNORE_VIRTUALENVS"))
        """If set, Pipenv will always assign a virtual environment for this project.

        By default, Pipenv tries to detect whether it is run inside a virtual
        environment, and reuses it if possible. This is usually the desired behavior,
        and enables the user to use any user-built environments with Pipenv.
        """

        self.PIPENV_INSTALL_TIMEOUT = int(os.environ.get("PIPENV_INSTALL_TIMEOUT", 60 * 15))
        """Max number of seconds to wait for package installation.

        Defaults to 900 (15 minutes), a very long arbitrary time.
        """

        # NOTE: +1 because of a temporary bug in Pipenv.
        self.PIPENV_MAX_DEPTH = int(os.environ.get("PIPENV_MAX_DEPTH", "3")) + 1
        """Maximum number of directories to recursively search for a Pipfile.

        Default is 3. See also ``PIPENV_NO_INHERIT``.
        """

        self.PIPENV_MAX_RETRIES = int(
            os.environ.get("PIPENV_MAX_RETRIES", "1" if PIPENV_IS_CI else "0")
        )
        """Specify how many retries Pipenv should attempt for network requests.

        Default is 0. Automatically set to 1 on CI environments for robust testing.
        """

        self.PIPENV_MAX_ROUNDS = int(os.environ.get("PIPENV_MAX_ROUNDS", "16"))
        """Tells Pipenv how many rounds of resolving to do for Pip-Tools.

        Default is 16, an arbitrary number that works most of the time.
        """

        self.PIPENV_MAX_SUBPROCESS = int(os.environ.get("PIPENV_MAX_SUBPROCESS", "8"))
        """How many subprocesses should Pipenv use when installing.

        Default is 16, an arbitrary number that seems to work.
        """

        self.PIPENV_NO_INHERIT = "PIPENV_NO_INHERIT" in os.environ
        """Tell Pipenv not to inherit parent directories.

        This is useful for deployment to avoid using the wrong current directory.
        Overwrites ``PIPENV_MAX_DEPTH``.
        """
        if self.PIPENV_NO_INHERIT:
            self.PIPENV_MAX_DEPTH = 2

        self.PIPENV_NOSPIN = bool(os.environ.get("PIPENV_NOSPIN"))
        """If set, disable terminal spinner.

        This can make the logs cleaner. Automatically set on Windows, and in CI
        environments.
        """
        if PIPENV_IS_CI:
            self.PIPENV_NOSPIN = True

        pipenv_spinner = "dots" if not os.name == "nt" else "bouncingBar"
        self.PIPENV_SPINNER = os.environ.get("PIPENV_SPINNER", pipenv_spinner)
        """Sets the default spinner type.

        Spinners are identical to the ``node.js`` spinners and can be found at
        https://github.com/sindresorhus/cli-spinners
        """

        pipenv_pipfile = os.environ.get("PIPENV_PIPFILE")
        if pipenv_pipfile:
            if not os.path.isfile(pipenv_pipfile):
                raise RuntimeError("Given PIPENV_PIPFILE is not found!")

            else:
                pipenv_pipfile = normalize_pipfile_path(pipenv_pipfile)
                # Overwrite environment variable so that subprocesses can get the correct path.
                # See https://github.com/pypa/pipenv/issues/3584
                os.environ['PIPENV_PIPFILE'] = pipenv_pipfile
        self.PIPENV_PIPFILE = pipenv_pipfile
        """If set, this specifies a custom Pipfile location.

        When running pipenv from a location other than the same directory where the
        Pipfile is located, instruct pipenv to find the Pipfile in the location
        specified by this environment variable.

        Default is to find Pipfile automatically in the current and parent directories.
        See also ``PIPENV_MAX_DEPTH``.
        """

        self.PIPENV_PYPI_MIRROR = os.environ.get("PIPENV_PYPI_MIRROR")
        """If set, tells pipenv to override PyPI index urls with a mirror.

        Default is to not mirror PyPI, i.e. use the real one, pypi.org. The
        ``--pypi-mirror`` command line flag overwrites this.
        """

        self.PIPENV_QUIET = bool(os.environ.get("PIPENV_QUIET"))
        """If set, makes Pipenv quieter.

        Default is unset, for normal verbosity. ``PIPENV_VERBOSE`` overrides this.
        """

        self.PIPENV_SHELL_EXPLICIT = os.environ.get("PIPENV_SHELL")
        """An absolute path to the preferred shell for ``pipenv shell``.

        Default is to detect automatically what shell is currently in use.
        """
        # Hack because PIPENV_SHELL is actually something else. Internally this
        # variable is called PIPENV_SHELL_EXPLICIT instead.

        self.PIPENV_SHELL_FANCY = bool(os.environ.get("PIPENV_SHELL_FANCY"))
        """If set, always use fancy mode when invoking ``pipenv shell``.

        Default is to use the compatibility shell if possible.
        """

        self.PIPENV_TIMEOUT = int(os.environ.get("PIPENV_TIMEOUT", 120))
        """Max number of seconds Pipenv will wait for virtualenv creation to complete.

        Default is 120 seconds, an arbitrary number that seems to work.
        """

        self.PIPENV_VENV_IN_PROJECT = bool(os.environ.get("PIPENV_VENV_IN_PROJECT"))
        """If set, creates ``.venv`` in your project directory.

        Default is to create new virtual environments in a global location.
        """

        self.PIPENV_VERBOSE = bool(os.environ.get("PIPENV_VERBOSE"))
        """If set, makes Pipenv more wordy.

        Default is unset, for normal verbosity. This takes precedence over
        ``PIPENV_QUIET``.
        """

        self.PIPENV_YES = bool(os.environ.get("PIPENV_YES"))
        """If set, Pipenv automatically assumes "yes" at all prompts.

        Default is to prompt the user for an answer if the current command line session
        if interactive.
        """

        self.PIPENV_SKIP_LOCK = bool(os.environ.get("PIPENV_SKIP_LOCK", False))
        """If set, Pipenv won't lock dependencies automatically.

        This might be desirable if a project has large number of dependencies,
        because locking is an inherently slow operation.

        Default is to lock dependencies and update ``Pipfile.lock`` on each run.

        Usage: `export PIPENV_SKIP_LOCK=true` OR `export PIPENV_SKIP_LOCK=1` to skip automatic locking

        NOTE: This only affects the ``install`` and ``uninstall`` commands.
        """

        self.PIP_EXISTS_ACTION = os.environ.get("PIP_EXISTS_ACTION", "w")
        """Specifies the value for pip's --exists-action option

        Defaults to ``(w)ipe``
        """

        self.PIPENV_RESOLVE_VCS = (
            os.environ.get("PIPENV_RESOLVE_VCS") is None
            or _is_env_truthy("PIPENV_RESOLVE_VCS")
        )

        """Tells Pipenv whether to resolve all VCS dependencies in full.

        As of Pipenv 2018.11.26, only editable VCS dependencies were resolved in full.
        To retain this behavior and avoid handling any conflicts that arise from the new
        approach, you may set this to '0', 'off', or 'false'.
        """

        self.PIPENV_PYUP_API_KEY = os.environ.get(
            "PIPENV_PYUP_API_KEY", None
        )

        # Internal, support running in a different Python from sys.executable.
        self.PIPENV_PYTHON = os.environ.get("PIPENV_PYTHON")

        # Internal, overwrite all index funcitonality.
        self.PIPENV_TEST_INDEX = os.environ.get("PIPENV_TEST_INDEX")

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
        verbosity = os.environ.get("PIPENV_VERBOSITY", "")
        try:
            self.PIPENV_VERBOSITY = int(verbosity)
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
        return self.PIPENV_VERBOSITY >= threshold

    def is_quiet(self, threshold=-1):
        return self.PIPENV_VERBOSITY <= threshold


def is_using_venv():
    # type: () -> bool
    """Check for venv-based virtual environment which sets sys.base_prefix"""
    if getattr(sys, 'real_prefix', None) is not None:
        # virtualenv venvs
        result = True
    else:
        # PEP 405 venvs
        result = sys.prefix != getattr(sys, 'base_prefix', sys.prefix)
    return result


def is_in_virtualenv():
    """
    Check virtualenv membership dynamically

    :return: True or false depending on whether we are in a regular virtualenv or not
    :rtype: bool
    """

    pipenv_active = os.environ.get("PIPENV_ACTIVE", False)
    virtual_env = bool(os.environ.get("VIRTUAL_ENV"))
    ignore_virtualenvs = bool(os.environ.get("PIPENV_IGNORE_VIRTUALENVS", False))
    return virtual_env and not (pipenv_active or ignore_virtualenvs)


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


MYPY_RUNNING = is_type_checking()
PIPENV_SPINNER_FAIL_TEXT = fix_utf8("✘ {0}") if not PIPENV_HIDE_EMOJIS else "{0}"
PIPENV_SPINNER_OK_TEXT = fix_utf8("✔ {0}") if not PIPENV_HIDE_EMOJIS else "{0}"
