import os

# Shell compatibility mode, for mis-configured shells.
PIPENV_SHELL_COMPAT = os.environ.get('PIPENV_SHELL_COMPAT')

# Create the virtualenv in the project, isntead of with pew.
PIPENV_VENV_IN_PROJECT = os.environ.get('PIPENV_SHELL_COMPAT')

# No color mode, for unfun people.
PIPENV_COLORBLIND = os.environ.get('PIPENV_COLORBLIND')

# User-configuraable max-depth for Pipfile searching.
PIPENV_MAX_DEPTH = int(os.environ.get('PIPENV_MAX_DEPTH', '3'))

# Use shell compatibility mode when using venv in project mode.
if PIPENV_VENV_IN_PROJECT:
    PIPENV_SHELL_COMPAT = True