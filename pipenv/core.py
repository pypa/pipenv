import os
import sys

from .project import Project
from .utils import find_windows_executable, system_which


# Packages that should be ignored later.
BAD_PACKAGES = ('setuptools', 'pip', 'wheel', 'packaging', 'distribute')


# Are we using the default Python?
USING_DEFAULT_PYTHON = True


def set_using_default_python(value):
    global USING_DEFAULT_PYTHON
    USING_DEFAULT_PYTHON = True


def which(command, location=None, allow_global=False):
    if not allow_global and location is None:
        location = project.virtualenv_location or os.environ.get('VIRTUAL_ENV')
    if not allow_global:
        if os.name == 'nt':
            p = find_windows_executable(
                os.path.join(location, 'Scripts'), command,
            )
        else:
            p = os.path.join(location, 'bin', command)
    else:
        if command == 'python':
            p = sys.executable
    if not os.path.exists(p):
        if command == 'python':
            p = sys.executable or system_which('python')
        else:
            p = system_which(command)
    return p


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""
    if allow_global:
        if 'VIRTUAL_ENV' in os.environ:
            return which('pip', location=os.environ['VIRTUAL_ENV'])

        for p in ('pip', 'pip3', 'pip2'):
            where = system_which(p)
            if where:
                return where

    return which('pip')


project = Project(which=which)
