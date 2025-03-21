from __future__ import annotations

import os
import re
import subprocess
from builtins import TimeoutError
from typing import TYPE_CHECKING, Any

from pipenv.vendor.packaging.version import InvalidVersion

if TYPE_CHECKING:
    from pathlib import Path

from ..exceptions import InvalidPythonVersion

# Regular expression for parsing Python version strings
version_re_str = (
    r"(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>(?<=\.)[0-9]+))?\.?"
    r"(?:(?P<prerel>[abc]|rc)(?:(?P<prerelversion>\d+(?:\.\d+)*))?)"
    r"?(?P<postdev>(\.post(?P<post>\d+))?(\.dev(?P<dev>\d+))?)?"
)
version_re = re.compile(version_re_str)


def get_python_version(path: str | Path) -> str:
    """
    Get python version string using subprocess from a given path.

    Args:
        path: Path to the Python executable.

    Returns:
        The Python version string.

    Raises:
        InvalidPythonVersion: If the path is not a valid Python executable.
    """
    version_cmd = [
        str(path),
        "-c",
        "import sys; print('.'.join([str(i) for i in sys.version_info[:3]]))",
    ]
    subprocess_kwargs = {
        "env": os.environ.copy(),
        "universal_newlines": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }

    try:
        c = subprocess.Popen(version_cmd, **subprocess_kwargs)
        try:
            out, _ = c.communicate(timeout=5)  # 5 second timeout
        except TypeError:  # For Python versions or mocks that don't support timeout
            out, _ = c.communicate()
    except (SystemExit, KeyboardInterrupt, TimeoutError, subprocess.TimeoutExpired):
        raise InvalidPythonVersion(f"{path} is not a valid python path (timeout)")
    except OSError:
        raise InvalidPythonVersion(f"{path} is not a valid python path")

    if not out:
        raise InvalidPythonVersion(f"{path} is not a valid python path")

    return out.strip()


def parse_python_version(version_str: str) -> dict[str, Any]:
    """
    Parse a Python version string into a dictionary of version components.

    Args:
        version_str: The version string to parse.

    Returns:
        A dictionary containing the parsed version components.

    Raises:
        InvalidPythonVersion: If the version string is not a valid Python version.
    """
    from pipenv.vendor.packaging.version import parse as parse_version

    is_debug = False
    if version_str.endswith("-debug"):
        is_debug = True
        version_str, _, _ = version_str.rpartition("-")

    match = version_re.match(version_str)
    if not match:
        raise InvalidPythonVersion(f"{version_str} is not a python version")

    version_dict = match.groupdict()
    major = int(version_dict.get("major", 0)) if version_dict.get("major") else None
    minor = int(version_dict.get("minor", 0)) if version_dict.get("minor") else None
    patch = int(version_dict.get("patch", 0)) if version_dict.get("patch") else None
    # Initialize release type flags
    is_prerelease = False
    is_devrelease = False
    is_postrelease = False

    try:
        version = parse_version(version_str)
        # Use packaging.version's properties to determine release type
        is_devrelease = version.is_devrelease

        # Check if this is a prerelease
        # A version is a prerelease if:
        # 1. It has a prerelease component (a, b, c, rc) but is not ONLY a dev release
        # 2. For complex versions with both prerelease and dev components, we consider them prereleases
        has_prerelease_component = hasattr(version, "pre") and version.pre is not None
        is_prerelease = has_prerelease_component or (
            version.is_prerelease and not is_devrelease
        )
        # Check for post-release by examining the version string and the version object
        is_postrelease = (hasattr(version, "post") and version.post is not None) or (
            version_dict.get("post") is not None
        )
    except (TypeError, InvalidVersion):
        # If packaging.version can't parse it, try to construct a version string
        # that it can parse
        v_dict = version_dict.copy()
        pre = ""
        if v_dict.get("prerel") and v_dict.get("prerelversion"):
            pre = v_dict.pop("prerel")
            pre = f"{pre}{v_dict.pop('prerelversion')}"
        v_dict["pre"] = pre
        keys = ["major", "minor", "patch", "pre", "postdev", "post", "dev"]
        values = [v_dict.get(val) for val in keys]
        version_str = ".".join([str(v) for v in values if v])
        try:
            version = parse_version(version_str)
            # Update release type flags based on the parsed version
            is_devrelease = version.is_devrelease

            # Check if this is a prerelease
            # A version is a prerelease if:
            # 1. It has a prerelease component (a, b, c, rc) but is not ONLY a dev release
            # 2. For complex versions with both prerelease and dev components, we consider them prereleases
            has_prerelease_component = hasattr(version, "pre") and version.pre is not None
            is_prerelease = has_prerelease_component or (
                version.is_prerelease and not is_devrelease
            )
            # Check for post-release by examining the version string and the version object
            is_postrelease = (hasattr(version, "post") and version.post is not None) or (
                version_dict.get("post") is not None
            )
        except (TypeError, InvalidVersion):
            version = None

    return {
        "major": major,
        "minor": minor,
        "patch": patch,
        "is_postrelease": is_postrelease,
        "is_prerelease": is_prerelease,
        "is_devrelease": is_devrelease,
        "is_debug": is_debug,
        "version": version,
    }


def guess_company(path: str) -> str | None:
    """
    Given a path to python, guess the company who created it.

    Args:
        path: The path to guess about.

    Returns:
        The guessed company name, or "PythonCore" if no match is found.
    """
    from .path_utils import PYTHON_IMPLEMENTATIONS

    non_core_pythons = [impl for impl in PYTHON_IMPLEMENTATIONS if impl != "python"]
    return next(
        iter(impl for impl in non_core_pythons if impl in path.lower()), "PythonCore"
    )


def parse_pyenv_version_order(filename: str = "version") -> list[str]:
    """
    Parse the pyenv version order from the specified file.

    Args:
        filename: The name of the file to parse.

    Returns:
        A list of version strings in the order specified by pyenv.
    """
    from .path_utils import resolve_path

    pyenv_root = os.path.expanduser(
        os.path.expandvars(os.environ.get("PYENV_ROOT", "~/.pyenv"))
    )
    version_order_file = resolve_path(os.path.join(pyenv_root, filename))

    if os.path.exists(version_order_file) and os.path.isfile(version_order_file):
        with open(version_order_file, encoding="utf-8") as fh:
            contents = fh.read()
        version_order = [v for v in contents.splitlines()]
        return version_order

    return []


def parse_asdf_version_order(filename: str = ".tool-versions") -> list[str]:
    """
    Parse the asdf version order from the specified file.

    Args:
        filename: The name of the file to parse.

    Returns:
        A list of version strings in the order specified by asdf.
    """
    from .path_utils import resolve_path

    version_order_file = resolve_path(os.path.join("~", filename))

    if os.path.exists(version_order_file) and os.path.isfile(version_order_file):
        with open(version_order_file, encoding="utf-8") as fh:
            contents = fh.read()
        python_section = next(
            iter(line for line in contents.splitlines() if line.startswith("python")),
            None,
        )
        if python_section:
            # python_key, _, versions
            _, _, versions = python_section.partition(" ")
            if versions:
                return versions.split()

    return []
