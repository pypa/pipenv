# -*- coding=utf-8 -*-
import os
import re
import sys

from .utils import get_python_executable_version, system_which


def parse_python_version(output):
    """Parse a Python version output returned by `python --version`.

    Return a dict with three keys: major, minor, and micro. Each value is a
    string containing a version part.

    Note: The micro part would be `'0'` if it's missing from the input string.
    """
    version_line = output.split('\n', 1)[0]
    version_pattern = re.compile(r'''
        ^                   # Beginning of line.
        Python              # Literally "Python".
        \s                  # Space.
        (?P<major>\d+)      # Major = one or more digits.
        \.                  # Dot.
        (?P<minor>\d+)      # Minor = one or more digits.
        (?:                 # Unnamed group for dot-micro.
            \.              # Dot.
            (?P<micro>\d+)  # Micro = one or more digit.
        )?                  # Micro is optional because pypa/pipenv#1893.
        .*                  # Trailing garbage.
        $                   # End of line.
    ''', re.VERBOSE)

    match = version_pattern.match(version_line)
    if not match:
        return None
    return match.groupdict(default='0')


def find_python_from_py(python):
    """Find a Python executable from on Windows.

    Ask py.exe for its opinion.
    """
    py = system_which('py')
    if not py:
        return None

    version_args = ['-{0}'.format(python[0])]
    if len(python) >= 2:
        version_args.append('-{0}.{1}'.format(python[0], python[2]))
    import subprocess

    for ver_arg in reversed(version_args):
        try:
            python_exe = subprocess.check_output(
                [py, ver_arg, '-c', 'import sys; print(sys.executable)']
            )
        except subprocess.CalledProcessError:
            continue

        if not isinstance(python_exe, str):
            python_exe = python_exe.decode(sys.getdefaultencoding())
        python_exe = python_exe.strip()
        version = get_python_executable_version(python_exe)
        if (version or '').startswith(python):
            return python_exe


def find_python_in_path(python):
    """Find a Python executable from a version number.

    This uses the PATH environment variable to locate an appropriate Python.
    """
    possibilities = ['python', 'python{0}'.format(python[0])]
    if len(python) >= 2:
        possibilities.extend(
            [
                'python{0}{1}'.format(python[0], python[2]),
                'python{0}.{1}'.format(python[0], python[2]),
                'python{0}.{1}m'.format(python[0], python[2]),
            ]
        )
    # Reverse the list, so we find specific ones first.
    possibilities = reversed(possibilities)
    for possibility in possibilities:
        # Windows compatibility.
        if os.name == 'nt':
            possibility = '{0}.exe'.format(possibility)
        pythons = system_which(possibility, mult=True)
        for p in pythons:
            version = get_python_executable_version(p)
            if (version or '').startswith(python):
                return p


def find_a_system_python(python):
    """Finds system python from version (e.g. 2 / 2.7 / 3.6.2) or full path.
    """
    if python.startswith('py'):
        return system_which(python)

    elif os.path.isabs(python):
        return python

    python_from_py = find_python_from_py(python)
    if python_from_py:
        return python_from_py

    return find_python_in_path(python)
