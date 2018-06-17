# -*- coding=utf-8 -*-
import attr
import locale
import os
import subprocess
from fnmatch import fnmatch

try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path


PYTHON_IMPLEMENTATIONS = ("python", "ironpython", "jython", "pypy")

KNOWN_EXTS = {"exe", "py", "fish", "sh", ""}
KNOWN_EXTS = KNOWN_EXTS | set(
    filter(None, os.environ.get("PATHEXT", "").split(os.pathsep))
)


def _run(cmd):
    """Use `subprocess.check_output` to get the output of a command and decode it.

    :param list cmd: A list representing the command you want to run.
    :returns: A 2-tuple of (output, error)
    """
    encoding = locale.getdefaultlocale()[1] or "utf-8"
    env = os.environ.copy()
    c = subprocess.Popen(
        cmd,
        encoding=encoding,
        env=env,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, err = c.communicate()
    return output.strip(), err.strip()


def get_python_version(path):
    """Get python version string using subprocess from a given path."""
    version_cmd = [path, "-c", "import sys; print(sys.version.split()[0])"]
    return _run(version_cmd)


def optional_instance_of(cls):
    return attr.validators.optional(attr.validators.instance_of(cls))


def path_and_exists(path):
    return attr.validators.instance_of(Path) and path.exists()


def path_is_executable(path):
    return os.access(str(path), os.X_OK)


def path_is_known_executable(path):
    return (
        path_is_executable(path)
        or os.access(str(path), os.R_OK)
        and path.suffix in KNOWN_EXTS
    )


def is_python_name(name):
    rules = ["*python", "*python?", "*python?.?", "*python?.?m"]
    match_rules = []
    for rule in rules:
        match_rules.extend(
            [
                "{0}.{1}".format(rule, ext) if ext else "{0}".format(rule)
                for ext in KNOWN_EXTS
            ]
        )
    if not any(name.lower().startswith(py_name) for py_name in PYTHON_IMPLEMENTATIONS):
        return False
    return any(fnmatch(name, rule) for rule in match_rules)


def path_is_python(path):
    return path_is_executable(path) and is_python_name(path.name)


def ensure_path(path):
    """Given a path (either a string or a Path object), expand variables and return a Path object.

    :param path: A string or a :class:`~pathlib.Path` object.
    :type path: str or :class:`~pathlib.Path`
    :return: A fully expanded Path object.
    :rtype: :class:`~pathlib.Path`
    """

    if isinstance(path, Path):
        return Path(os.path.expandvars(path.as_posix()))
    return Path(os.path.expandvars(path))


def _filter_none(k, v):
    if v:
        return True
    return False


def filter_pythons(path):
    """Return all valid pythons in a given path"""
    if not isinstance(path, Path):
        path = Path(str(path))
    if not path.is_dir():
        return path if path_is_python(path) else None
    return filter(lambda x: path_is_python(x), path.iterdir())
