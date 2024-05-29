from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

PYENV_ROOT = os.path.expanduser(
    os.path.expandvars(os.environ.get("PYENV_ROOT", "~/.pyenv"))
)
PYENV_ROOT = Path(PYENV_ROOT)
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
                    os.environ["PATH"] = asdf_path + os.pathsep + os.environ["PATH"]
        except FileNotFoundError:
            pass


def set_pyenv_paths():
    if PYENV_INSTALLED:
        python_versions = os.path.join(PYENV_ROOT, "versions")
        is_windows = os.name == "nt"
        try:
            # Get a list of all files and directories in the given path
            all_files_and_dirs = os.listdir(python_versions)
            # Filter out files and keep only directories
            for name in all_files_and_dirs:
                if os.path.isdir(os.path.join(python_versions, name)):
                    pyenv_path = os.path.join(python_versions, name)
                    if not is_windows:
                        pyenv_path = os.path.join(pyenv_path, "bin")
                    os.environ["PATH"] = pyenv_path + os.pathsep + os.environ["PATH"]
        except FileNotFoundError:
            pass
