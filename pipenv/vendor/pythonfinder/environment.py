from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

# Environment variables and constants
PYENV_ROOT = os.path.expanduser(
    os.path.expandvars(os.environ.get("PYENV_ROOT", "~/.pyenv"))
)
PYENV_ROOT = Path(PYENV_ROOT)
PYENV_INSTALLED = shutil.which("pyenv") is not None

ASDF_DATA_DIR = os.path.expanduser(
    os.path.expandvars(os.environ.get("ASDF_DATA_DIR", "~/.asdf"))
)
ASDF_INSTALLED = shutil.which("asdf") is not None

SYSTEM_ARCH = platform.architecture()[0]
IS_64BIT_OS = None

if sys.maxsize > 2**32:
    IS_64BIT_OS = platform.machine() == "AMD64"
else:
    IS_64BIT_OS = False

IGNORE_UNSUPPORTED = bool(os.environ.get("PYTHONFINDER_IGNORE_UNSUPPORTED", False))
SUBPROCESS_TIMEOUT = int(os.environ.get("PYTHONFINDER_SUBPROCESS_TIMEOUT", 5))


def get_python_paths() -> list[str]:
    """
    Get a list of paths where Python executables might be found.

    Returns:
        A list of paths to search for Python executables.
    """
    paths = []

    # Add paths from PATH environment variable
    if "PATH" in os.environ:
        paths.extend(os.environ["PATH"].split(os.pathsep))

    # Add pyenv paths if installed
    if PYENV_INSTALLED:
        pyenv_paths = get_pyenv_paths()
        paths.extend(pyenv_paths)

    # Add asdf paths if installed
    if ASDF_INSTALLED:
        asdf_paths = get_asdf_paths()
        paths.extend(asdf_paths)

    # Add Windows registry paths if on Windows
    if os.name == "nt":
        from .finders.windows_registry import get_registry_python_paths

        registry_paths = get_registry_python_paths()
        paths.extend(registry_paths)

    return paths


def get_pyenv_paths() -> list[str]:
    """
    Get a list of paths where pyenv Python executables might be found.

    Returns:
        A list of paths to search for pyenv Python executables.
    """
    paths = []
    python_versions = os.path.join(PYENV_ROOT, "versions")
    is_windows = os.name == "nt"

    try:
        # Get a list of all files and directories in the given path
        all_files_and_dirs = os.listdir(python_versions)
        # Filter out files and keep only directories
        for name in all_files_and_dirs:
            version_path = os.path.join(python_versions, name)
            if os.path.isdir(version_path):
                if not is_windows:
                    version_path = os.path.join(version_path, "bin")
                paths.append(version_path)
    except FileNotFoundError:
        pass

    return paths


def get_asdf_paths() -> list[str]:
    """
    Get a list of paths where asdf Python executables might be found.

    Returns:
        A list of paths to search for asdf Python executables.
    """
    paths = []
    python_versions = os.path.join(ASDF_DATA_DIR, "installs", "python")

    try:
        # Get a list of all files and directories in the given path
        all_files_and_dirs = os.listdir(python_versions)
        # Filter out files and keep only directories
        for name in all_files_and_dirs:
            version_path = os.path.join(python_versions, name)
            if os.path.isdir(version_path):
                bin_path = os.path.join(version_path, "bin")
                paths.append(bin_path)
    except FileNotFoundError:
        pass

    return paths
