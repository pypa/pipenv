import os
import sys
from appdirs import user_cache_dir
from .vendor.vistir.misc import fs_str


# HACK: avoid resolver.py uses the wrong byte code files.
# I hope I can remove this one day.
os.environ["PYTHONDONTWRITEBYTECODE"] = fs_str("1")

# HACK: Prevent invalid shebangs with Homebrew-installed Python:
# https://bugs.python.org/issue22490
os.environ.pop("__PYVENV_LAUNCHER__", None)

# Load patched pip instead of system pip
os.environ["PIP_SHIMS_BASE_MODULE"] = fs_str("pipenv.patched.notpip")

PIPENV_CACHE_DIR = os.environ.get("PIPENV_CACHE_DIR", user_cache_dir("pipenv"))
"""Location for Pipenv to store it's package cache.

Default is to use appdir's user cache directory.
"""

PIPENV_COLORBLIND = bool(os.environ.get("PIPENV_COLORBLIND"))
"""If set, disable terminal colors.

Some people don't like colors in their terminals, for some reason. Default is
to show colors.
"""

# Tells Pipenv which Python to default to, when none is provided.
PIPENV_DEFAULT_PYTHON_VERSION = os.environ.get("PIPENV_DEFAULT_PYTHON_VERSION")
"""Use this Python version when creating new virtual environments by default.

This can be set to a version string, e.g. ``3.6``, or a path. Default is to use
whatever Python Pipenv is installed under (i.e. ``sys.executable``). Command
line flags (e.g. ``--python``, ``--three``, and ``--two``) are prioritized over
this configuration.
"""

PIPENV_DONT_LOAD_ENV = bool(os.environ.get("PIPENV_DONT_LOAD_ENV"))
"""If set, Pipenv does not load the ``.env`` file.

Default is to load ``.env`` for ``run`` and ``shell`` commands.
"""

PIPENV_DONT_USE_PYENV = bool(os.environ.get("PIPENV_DONT_USE_PYENV"))
"""If set, Pipenv does not attempt to install Python with pyenv.

Default is to install Python automatically via pyenv when needed, if possible.
"""

PIPENV_DOTENV_LOCATION = os.environ.get("PIPENV_DOTENV_LOCATION")
"""If set, Pipenv loads the ``.env`` file at the specified location.

Default is to load ``.env`` from the project root, if found.
"""

PIPENV_EMULATOR = os.environ.get("PIPENV_EMULATOR", "")
"""If set, the terminal emulator's name for ``pipenv shell`` to use.

Default is to detect emulators automatically. This should be set if your
emulator, e.g. Cmder, cannot be detected correctly.
"""

PIPENV_HIDE_EMOJIS = bool(os.environ.get("PIPENV_HIDE_EMOJIS"))
"""Disable emojis in output.

Default is to show emojis. This is automatically set on Windows.
"""
if os.name == "nt":
    PIPENV_HIDE_EMOJIS = True

PIPENV_IGNORE_VIRTUALENVS = bool(os.environ.get("PIPENV_IGNORE_VIRTUALENVS"))
"""If set, Pipenv will always assign a virtual environment for this project.

By default, Pipenv tries to detect whether it is run inside a virtual
environment, and reuses it if possible. This is usually the desired behavior,
and enables the user to use any user-built environments with Pipenv.
"""

PIPENV_INSTALL_TIMEOUT = 60 * 15
"""Max number of seconds to wait for package installation.

Defaults to 900 (15 minutes), a very long arbitrary time.
"""

# NOTE: +1 because of a temporary bug in Pipenv.
PIPENV_MAX_DEPTH = int(os.environ.get("PIPENV_MAX_DEPTH", "3")) + 1
"""Maximum number of directories to recursively search for a Pipfile.

Default is 3. See also ``PIPENV_NO_INHERIT``.
"""

PIPENV_MAX_RETRIES = int(os.environ.get(
    "PIPENV_MAX_RETRIES",
    "1" if "CI" in os.environ else "0",
))
"""Specify how many retries Pipenv should attempt for network requests.

Default is 0. Automatically set to 1 on CI environments for robust testing.
"""

PIPENV_MAX_ROUNDS = int(os.environ.get("PIPENV_MAX_ROUNDS", "16"))
"""Tells Pipenv how many rounds of resolving to do for Pip-Tools.

Default is 16, an arbitrary number that works most of the time.
"""

PIPENV_MAX_SUBPROCESS = int(os.environ.get("PIPENV_MAX_SUBPROCESS", "16"))
"""How many subprocesses should Pipenv use when installing.

Default is 16, an arbitrary number that seems to work.
"""

PIPENV_NO_INHERIT = "PIPENV_NO_INHERIT" in os.environ
"""Tell Pipenv not to inherit parent directories.

This is useful for deployment to avoid using the wrong current directory.
Overwrites ``PIPENV_MAX_DEPTH``.
"""
if PIPENV_NO_INHERIT:
    PIPENV_MAX_DEPTH = 2

PIPENV_NOSPIN = bool(os.environ.get("PIPENV_NOSPIN"))
"""If set, disable terminal spinner.

This can make the logs cleaner. Automatically set on Windows, and in CI
environments.
"""
if os.name == "nt" or "CI" in os.environ:
    PIPENV_NOSPIN = True

PIPENV_PIPFILE = os.environ.get("PIPENV_PIPFILE")
"""If set, this specifies a custom Pipfile location.

When running pipenv from a location other than the same directory where the
Pipfile is located, instruct pipenv to find the Pipfile in the location
specified by this environment variable.

Default is to find Pipfile automatically in the current and parent directories.
See also ``PIPENV_MAX_DEPTH``.
"""

PIPENV_PYPI_MIRROR = os.environ.get("PIPENV_PYPI_MIRROR")
"""If set, tells pipenv to override PyPI index urls with a mirror.

Default is to not mirror PyPI, i.e. use the real one, pypi.org. The
``--pypi-mirror`` command line flag overwrites this.
"""

PIPENV_QUIET = bool(os.environ.get("PIPENV_QUIET"))
"""If set, makes Pipenv quieter.

Default is unset, for normal verbosity. ``PIPENV_VERBOSE`` overrides this.
"""

PIPENV_SHELL = os.environ.get("PIPENV_SHELL")
"""An absolute path to the preferred shell for ``pipenv shell``.

Default is to detect automatically what shell is currently in use.
"""
# Hack because PIPENV_SHELL is actually something else. Internally this
# variable is called PIPENV_SHELL_EXPLICIT instead.
PIPENV_SHELL_EXPLICIT = PIPENV_SHELL
del PIPENV_SHELL

PIPENV_SHELL_FANCY = bool(os.environ.get("PIPENV_SHELL_FANCY"))
"""If set, always use fancy mode when invoking ``pipenv shell``.

Default is to use the compatibility shell if possible.
"""

PIPENV_TIMEOUT = int(os.environ.get("PIPENV_TIMEOUT", 120))
"""Max number of seconds Pipenv will wait for virtualenv creation to complete.

Default is 120 seconds, an arbitrary number that seems to work.
"""

PIPENV_VENV_IN_PROJECT = bool(os.environ.get("PIPENV_VENV_IN_PROJECT"))
"""If set, creates ``.venv`` in your project directory.

Default is to create new virtual environments in a global location.
"""

PIPENV_VERBOSE = bool(os.environ.get("PIPENV_VERBOSE"))
"""If set, makes Pipenv more wordy.

Default is unset, for normal verbosity. This takes precedence over
``PIPENV_QUIET``.
"""

PIPENV_YES = bool(os.environ.get("PIPENV_YES"))
"""If set, Pipenv automatically assumes "yes" at all prompts.

Default is to prompt the user for an answer if the current command line session
if interactive.
"""


# Internal, support running in a different Python from sys.executable.
PIPENV_PYTHON = os.environ.get("PIPENV_PYTHON")

# Internal, overwrite all index funcitonality.
PIPENV_TEST_INDEX = os.environ.get("PIPENV_TEST_INDEX")

# Internal, tells Pipenv about the surrounding environment.
PIPENV_USE_SYSTEM = False
PIPENV_VIRTUALENV = None
if "PIPENV_ACTIVE" not in os.environ and not PIPENV_IGNORE_VIRTUALENVS:
    PIPENV_VIRTUALENV = os.environ.get("VIRTUAL_ENV")
    PIPENV_USE_SYSTEM = bool(PIPENV_VIRTUALENV)

# Internal, tells Pipenv to skip case-checking (slow internet connections).
# This is currently always set to True for performance reasons.
PIPENV_SKIP_VALIDATION = True

# Internal, the default shell to use if shell detection fails.
PIPENV_SHELL = (
    os.environ.get("SHELL") or
    os.environ.get("PYENV_SHELL") or
    os.environ.get("COMSPEC")
)

# Internal, to tell whether the command line session is interactive.
SESSION_IS_INTERACTIVE = bool(os.isatty(sys.stdout.fileno()))


# Internal, consolidated verbosity representation as an integer. The default
# level is 0, increased for wordiness and decreased for terseness.
PIPENV_VERBOSITY = os.environ.get("PIPENV_VERBOSITY", "")
if PIPENV_VERBOSITY.isdigit():
    PIPENV_VERBOSITY = int(PIPENV_VERBOSITY)
else:
    if PIPENV_VERBOSE:
        PIPENV_VERBOSITY = 1
    elif PIPENV_QUIET:
        PIPENV_VERBOSITY = -1
    else:
        PIPENV_VERBOSITY = 0
del PIPENV_QUIET
del PIPENV_VERBOSE


def is_verbose(threshold=1):
    return PIPENV_VERBOSITY >= threshold


def is_quiet(threshold=-1):
    return PIPENV_VERBOSITY <= threshold
