import os


# Prevent invalid shebangs with Homebrew-installed Python:
# https://bugs.python.org/issue22490
os.environ.pop('__PYVENV_LAUNCHER__', None)


# Shell compatibility mode, for mis-configured shells.
PIPENV_SHELL_COMPAT = os.environ.get('PIPENV_SHELL_COMPAT')

# Create the virtualenv in the project, isntead of with pew.
PIPENV_VENV_IN_PROJECT = os.environ.get('PIPENV_VENV_IN_PROJECT')

# No color mode, for unfun people.
PIPENV_COLORBLIND = os.environ.get('PIPENV_COLORBLIND')

# Disable spinner for better test and deploy logs (for the unworthy).
PIPENV_NOSPIN = os.environ.get('PIPENV_NOSPIN')

# User-configuraable max-depth for Pipfile searching.
# Note: +1 because of a temporary bug in Pipenv.
PIPENV_MAX_DEPTH = int(os.environ.get('PIPENV_MAX_DEPTH', '3')) + 1

# Tells Pipenv to use the virtualenv-provided pip instead.
PIPENV_USE_SYSTEM = os.environ.get('VIRTUAL_ENV') if 'PIPENV_IGNORE_VIRTUALENVS' not in os.environ else False

# Tells Pipenv to use hashing mode.
PIPENV_USE_HASHES = True

# Tells pipenv to skip case-checking (slow internet connections).
PIPENV_SKIP_VALIDATION = True

# Use shell compatibility mode when using venv in project mode.
if PIPENV_VENV_IN_PROJECT:
    PIPENV_SHELL_COMPAT = True

# Disable spinner on windows.
if os.name == 'nt':
    PIPENV_NOSPIN = True

if 'CI' in os.environ:
    PIPENV_NOSPIN = True

PIPENV_HIDE_EMOJIS = os.environ.get('PIPENV_HIDE_EMOJIS')
if os.name == 'nt':
    PIPENV_HIDE_EMOJIS = True

# Tells pipenv how long to wait for virtualenvs to be created in seconds
PIPENV_TIMEOUT = int(os.environ.get('PIPENV_TIMEOUT', 120))

PIPENV_INSTALL_TIMEOUT = 60 * 15

PYENV_INSTALLED = os.environ.get('PYENV_ROOT')