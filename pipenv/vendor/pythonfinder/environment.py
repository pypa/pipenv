from __future__ import annotations

import os
import platform
import sys
import posixpath
import ntpath
import re
import shutil


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


def possibly_convert_to_windows_style_path(path):
    if not isinstance(path, str):
        path = str(path)
    # Check if the path is in Unix-style (Git Bash)
    if os.name == 'nt':
        if path.startswith('/'):
            drive, tail = re.match(r"^/([a-zA-Z])/(.*)", path).groups()
            revised_path = drive.upper() + ":\\" + tail.replace('/', '\\')
            return revised_path
        elif path.startswith('\\'):
            drive, tail = re.match(r"^\\([a-zA-Z])\\(.*)", path).groups()
            revised_path = drive.upper() + ":\\" + tail.replace('\\', '\\')
            return revised_path

    return path


PYENV_ROOT = os.path.expanduser(
    os.path.expandvars(os.environ.get("PYENV_ROOT", "~/.pyenv"))
)
PYENV_ROOT = possibly_convert_to_windows_style_path(PYENV_ROOT)
PYENV_INSTALLED = shutil.which("pyenv") != None
ASDF_DATA_DIR = os.path.expanduser(
    os.path.expandvars(os.environ.get("ASDF_DATA_DIR", "~/.asdf"))
)
ASDF_INSTALLED = shutil.which("asdf") != None
IS_64BIT_OS = None
SYSTEM_ARCH = platform.architecture()[0]

if sys.maxsize > 2**32:
    IS_64BIT_OS = platform.machine() == "AMD64"
else:
    IS_64BIT_OS = False


IGNORE_UNSUPPORTED = bool(os.environ.get("PYTHONFINDER_IGNORE_UNSUPPORTED", False))
MYPY_RUNNING = os.environ.get("MYPY_RUNNING", is_type_checking())
SUBPROCESS_TIMEOUT = os.environ.get("PYTHONFINDER_SUBPROCESS_TIMEOUT", 5)
"""The default subprocess timeout for determining python versions

Set to **5** by default.
"""


def join_path_for_platform(path, path_parts):
    # If we're on Unix or Unix-like system
    if os.name == 'posix' or sys.platform == 'linux':
        return posixpath.join(path, *path_parts)
    # If we're on Windows
    elif os.name == 'nt' or sys.platform == 'win32':
        return ntpath.join(path, *path_parts)
    else:
        raise Exception("Unknown environment")


def set_asdf_paths():
    if ASDF_INSTALLED:
        python_versions = join_path_for_platform(ASDF_DATA_DIR, ["installs", "python"])
        try:
            # Get a list of all files and directories in the given path
            all_files_and_dirs = os.listdir(python_versions)
            # Filter out files and keep only directories
            for name in all_files_and_dirs:
                if os.path.isdir(os.path.join(python_versions, name)):
                    asdf_path = os.path.join(python_versions, name)
                    asdf_path = os.path.join(asdf_path, "bin")
                    os.environ['PATH'] = asdf_path + os.pathsep + os.environ['PATH']
        except FileNotFoundError:
            pass


def set_pyenv_paths():
    if PYENV_INSTALLED:
        is_windows = False
        if os.name == "nt":
            python_versions = join_path_for_platform(PYENV_ROOT, ["pyenv-win", "versions"])
            is_windows = True
        else:
            python_versions = join_path_for_platform(PYENV_ROOT, ["versions"])
        try:
            # Get a list of all files and directories in the given path
            all_files_and_dirs = os.listdir(python_versions)
            # Filter out files and keep only directories
            for name in all_files_and_dirs:
                if os.path.isdir(os.path.join(python_versions, name)):
                    pyenv_path = os.path.join(python_versions, name)
                    if not is_windows:
                        pyenv_path = os.path.join(pyenv_path, "bin")
                    os.environ['PATH'] = pyenv_path + os.pathsep + os.environ['PATH']
        except FileNotFoundError:
            pass
