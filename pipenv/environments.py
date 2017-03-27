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

# The root directory of your project
PIPENV_ROOT = os.environ.get('PIPENV_ROOT', False)

# Use shell compatibility mode when using venv in project mode.
if PIPENV_VENV_IN_PROJECT:
    PIPENV_SHELL_COMPAT = True

# Disable spinner on windows.
if os.name == 'nt':
    PIPENV_NOSPIN = True
