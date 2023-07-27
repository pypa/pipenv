from __future__ import annotations

import os
import platform
import sys
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
    if os.name != 'nt':
        return path
    if os.path.exists(path):
        return path
    match = re.match(r"[/\\]([a-zA-Z])[/\\](.*)", path)
    if match is None:
        return path
    drive, rest_of_path = match.groups()
    rest_of_path = rest_of_path.replace("/", "\\")
    revised_path = f"{drive.upper()}:\\{rest_of_path}"
    if os.path.exists(revised_path):
        return revised_path
    return path


PYENV_ROOT = os.path.expanduser(
    os.path.expandvars(os.environ.get("PYENV_ROOT", "~/.pyenv"))
)
PYENV_ROOT = possibly_convert_to_windows_style_path(PYENV_ROOT)
PYENV_INSTALLED = shutil.which("pyenv") is not None
ASDF_DATA_DIR = os.path.expanduser(
    os.path.expandvars(os.environ.get("ASDF_DATA_DIR", "~/.asdf"))
)
ASDF_INSTALLED = shutil.which("asdf") is not None
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


def set_asdf_paths():
    if ASDF_INSTALLED:
        python_versions = os.path.join(ASDF_DATA_DIR, "installs", "python")
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
            python_versions = os.path.join(PYENV_ROOT, "pyenv-win", "versions")
            is_windows = True
        else:
            python_versions = os.path.join(PYENV_ROOT, "versions")
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
