import os
import sys
from appdirs import user_cache_dir

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

# Prevent invalid shebangs with Homebrew-installed Python:
# https://bugs.python.org/issue22490
os.environ.pop('__PYVENV_LAUNCHER__', None)
# Shell compatibility mode, for mis-configured shells.
PIPENV_SHELL_FANCY = bool(os.environ.get('PIPENV_SHELL_FANCY'))
# Support for both Python 2 and Python 3 at the same time.
PIPENV_PYTHON = os.environ.get('PIPENV_PYTHON')
# Create the virtualenv in the project, instead of with pew.
PIPENV_VENV_IN_PROJECT = bool(
    os.environ.get('PIPENV_VENV_IN_PROJECT')
)
# Overwrite all index funcitonality.
PIPENV_TEST_INDEX = os.environ.get('PIPENV_TEST_INDEX')
# No color mode, for unfun people.
PIPENV_COLORBLIND = bool(os.environ.get('PIPENV_COLORBLIND'))
# Disable spinner for better test and deploy logs (for the unworthy).
PIPENV_NOSPIN = bool(os.environ.get('PIPENV_NOSPIN'))
# Tells Pipenv how many rounds of resolving to do for Pip-Tools.
PIPENV_MAX_ROUNDS = int(os.environ.get('PIPENV_MAX_ROUNDS', '16'))
# Specify a custom Pipfile location.
PIPENV_PIPFILE = os.environ.get('PIPENV_PIPFILE')
# Tells Pipenv which Python to default to, when none is provided.
PIPENV_DEFAULT_PYTHON_VERSION = os.environ.get('PIPENV_DEFAULT_PYTHON_VERSION')
# Tells Pipenv to not load .env files.
PIPENV_DONT_LOAD_ENV = bool(os.environ.get('PIPENV_DONT_LOAD_ENV'))
# Tell Pipenv to default to yes at all prompts.
PIPENV_YES = bool(os.environ.get('PIPENV_YES'))
# Tells Pipenv how many subprocesses to use when installing.
PIPENV_MAX_SUBPROCESS = int(os.environ.get('PIPENV_MAX_SUBPROCESS', '16'))
# User-configurable max-depth for Pipfile searching.
# Note: +1 because of a temporary bug in Pipenv.
PIPENV_MAX_DEPTH = int(os.environ.get('PIPENV_MAX_DEPTH', '3')) + 1
# Tell Pipenv not to inherit parent directories (for development, mostly).
PIPENV_NO_INHERIT = 'PIPENV_NO_INHERIT' in os.environ
if PIPENV_NO_INHERIT:
    PIPENV_MAX_DEPTH = 2
# Tells Pipenv to use the virtualenv-provided pip instead.
PIPENV_VIRTUALENV = None
PIPENV_USE_SYSTEM = False
if 'PIPENV_ACTIVE' not in os.environ:
    if 'PIPENV_IGNORE_VIRTUALENVS' not in os.environ:
        PIPENV_VIRTUALENV = os.environ.get('VIRTUAL_ENV')
        PIPENV_USE_SYSTEM = bool(os.environ.get('VIRTUAL_ENV'))
# Tells Pipenv to use hashing mode.
PIPENV_USE_HASHES = True
# Tells Pipenv to skip case-checking (slow internet connections).
PIPENV_SKIP_VALIDATION = True
# Tells Pipenv where to load .env from.
PIPENV_DOTENV_LOCATION = os.environ.get('PIPENV_DOTENV_LOCATION')
# Disable spinner on Windows.
if os.name == 'nt':
    PIPENV_NOSPIN = True
# Disable the spinner on Travis-Ci (and friends).
if 'CI' in os.environ:
    PIPENV_NOSPIN = True
PIPENV_HIDE_EMOJIS = bool(os.environ.get('PIPENV_HIDE_EMOJIS'))
if os.name == 'nt':
    PIPENV_HIDE_EMOJIS = True
# Tells Pipenv how long to wait for virtualenvs to be created in seconds.
PIPENV_TIMEOUT = int(os.environ.get('PIPENV_TIMEOUT', 120))
PIPENV_INSTALL_TIMEOUT = 60 * 15
PIPENV_DONT_USE_PYENV = os.environ.get('PIPENV_DONT_USE_PYENV')
PYENV_ROOT = os.environ.get('PYENV_ROOT', os.path.expanduser('~/.pyenv'))
PYENV_INSTALLED = (
    bool(os.environ.get('PYENV_SHELL')) or bool(os.environ.get('PYENV_ROOT'))
)
SESSION_IS_INTERACTIVE = bool(os.isatty(sys.stdout.fileno()))
PIPENV_SHELL = os.environ.get('SHELL') or os.environ.get('PYENV_SHELL')
PIPENV_CACHE_DIR = os.environ.get('PIPENV_CACHE_DIR', user_cache_dir('pipenv'))
