# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import itertools
import os

from fnmatch import fnmatch

import attr
import io
import re
import six

import vistir

from packaging.version import LegacyVersion, Version

from .environment import PYENV_ROOT, ASDF_DATA_DIR, MYPY_RUNNING
from .exceptions import InvalidPythonVersion

six.add_move(six.MovedAttribute("Iterable", "collections", "collections.abc"))
from six.moves import Iterable

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache

if MYPY_RUNNING:
    from typing import Any, Union, List, Callable, Iterable, Set, Tuple, Dict, Optional
    from attr.validators import _OptionalValidator


version_re = re.compile(r"(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>(?<=\.)[0-9]+))?\.?"
                        r"(?:(?P<prerel>[abc]|rc|dev)(?:(?P<prerelversion>\d+(?:\.\d+)*))?)"
                        r"?(?P<postdev>(\.post(?P<post>\d+))?(\.dev(?P<dev>\d+))?)?")


PYTHON_IMPLEMENTATIONS = (
    "python", "ironpython", "jython", "pypy", "anaconda", "miniconda",
    "stackless", "activepython", "micropython"
)
RULES_BASE = ["*{0}", "*{0}?", "*{0}?.?", "*{0}?.?m"]
RULES = [rule.format(impl) for impl in PYTHON_IMPLEMENTATIONS for rule in RULES_BASE]

KNOWN_EXTS = {"exe", "py", "fish", "sh", ""}
KNOWN_EXTS = KNOWN_EXTS | set(
    filter(None, os.environ.get("PATHEXT", "").split(os.pathsep))
)

MATCH_RULES = []
for rule in RULES:
    MATCH_RULES.extend(
        [
            "{0}.{1}".format(rule, ext) if ext else "{0}".format(rule)
            for ext in KNOWN_EXTS
        ]
    )


@lru_cache(maxsize=1024)
def get_python_version(path):
    # type: (str) -> str
    """Get python version string using subprocess from a given path."""
    version_cmd = [path, "-c", "import sys; print(sys.version.split()[0])"]
    try:
        c = vistir.misc.run(version_cmd, block=True, nospin=True, return_object=True,
                            combine_stderr=False, write_to_stdout=False)
    except OSError:
        raise InvalidPythonVersion("%s is not a valid python path" % path)
    if not c.out:
        raise InvalidPythonVersion("%s is not a valid python path" % path)
    return c.out.strip()


@lru_cache(maxsize=1024)
def parse_python_version(version_str):
    # type: (str) -> Dict[str, Union[str, int, Version]]
    from packaging.version import parse as parse_version
    is_debug = False
    if version_str.endswith("-debug"):
        is_debug = True
        version_str, _, _ = version_str.rpartition("-")
    match = version_re.match(version_str)
    if not match:
        raise InvalidPythonVersion("%s is not a python version" % version_str)
    version_dict = match.groupdict()  # type: Dict[str, str]
    major = int(version_dict.get("major", 0)) if version_dict.get("major") else None
    minor = int(version_dict.get("minor", 0)) if version_dict.get("minor") else None
    patch = int(version_dict.get("patch", 0)) if version_dict.get("patch") else None
    is_postrelease = True if version_dict.get("post") else False
    is_prerelease = True if version_dict.get("prerel") else False
    is_devrelease = True if version_dict.get("dev") else False
    if patch:
        patch = int(patch)
    version = None  # type: Optional[Union[Version, LegacyVersion]]
    try:
        version = parse_version(version_str)
    except TypeError:
        version = None
    if isinstance(version, LegacyVersion) or version is None:
        v_dict = version_dict.copy()
        pre = ""
        if v_dict.get("prerel") and v_dict.get("prerelversion"):
            pre = v_dict.pop("prerel")
            pre = "{0}{1}".format(pre, v_dict.pop("prerelversion"))
        v_dict["pre"] = pre
        keys = ["major", "minor", "patch", "pre", "postdev", "post", "dev"]
        values = [v_dict.get(val) for val in keys]
        version_str = ".".join([str(v) for v in values if v])
        version = parse_version(version_str)
    return {
        "major": major,
        "minor": minor,
        "patch": patch,
        "is_postrelease": is_postrelease,
        "is_prerelease": is_prerelease,
        "is_devrelease": is_devrelease,
        "is_debug": is_debug,
        "version": version
    }


def optional_instance_of(cls):
    # type: (Any) -> _OptionalValidator
    """
    Return an validator to determine whether an input is an optional instance of a class.

    :return: A validator to determine optional instance membership.
    :rtype: :class:`~attr.validators._OptionalValidator`
    """

    return attr.validators.optional(attr.validators.instance_of(cls))


def path_is_executable(path):
    # type: (str) -> bool
    """
    Determine whether the supplied path is executable.

    :return: Whether the provided path is executable.
    :rtype: bool
    """

    return os.access(str(path), os.X_OK)


@lru_cache(maxsize=1024)
def path_is_known_executable(path):
    # type: (vistir.compat.Path) -> bool
    """
    Returns whether a given path is a known executable from known executable extensions
    or has the executable bit toggled.

    :param path: The path to the target executable.
    :type path: :class:`~vistir.compat.Path`
    :return: True if the path has chmod +x, or is a readable, known executable extension.
    :rtype: bool
    """

    return (
        path_is_executable(path)
        or os.access(str(path), os.R_OK)
        and path.suffix in KNOWN_EXTS
    )


@lru_cache(maxsize=1024)
def looks_like_python(name):
    # type: (str) -> bool
    """
    Determine whether the supplied filename looks like a possible name of python.

    :param str name: The name of the provided file.
    :return: Whether the provided name looks like python.
    :rtype: bool
    """

    if not any(name.lower().startswith(py_name) for py_name in PYTHON_IMPLEMENTATIONS):
        return False
    return any(fnmatch(name, rule) for rule in MATCH_RULES)


@lru_cache(maxsize=1024)
def path_is_python(path):
    # type: (vistir.compat.Path) -> bool
    """
    Determine whether the supplied path is executable and looks like a possible path to python.

    :param path: The path to an executable.
    :type path: :class:`~vistir.compat.Path`
    :return: Whether the provided path is an executable path to python.
    :rtype: bool
    """

    return path_is_executable(path) and looks_like_python(path.name)


@lru_cache(maxsize=1024)
def ensure_path(path):
    # type: (Union[vistir.compat.Path, str]) -> bool
    """
    Given a path (either a string or a Path object), expand variables and return a Path object.

    :param path: A string or a :class:`~pathlib.Path` object.
    :type path: str or :class:`~pathlib.Path`
    :return: A fully expanded Path object.
    :rtype: :class:`~pathlib.Path`
    """

    if isinstance(path, vistir.compat.Path):
        return path
    path = vistir.compat.Path(os.path.expandvars(path))
    return path.absolute()


def _filter_none(k, v):
    # type: (Any, Any) -> bool
    if v:
        return True
    return False


# TODO: Reimplement in vistir
def normalize_path(path):
    # type: (str) -> str
    return os.path.normpath(os.path.normcase(
        os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))
    ))


@lru_cache(maxsize=1024)
def filter_pythons(path):
    # type: (Union[str, vistir.compat.Path]) -> Iterable
    """Return all valid pythons in a given path"""
    if not isinstance(path, vistir.compat.Path):
        path = vistir.compat.Path(str(path))
    if not path.is_dir():
        return path if path_is_python(path) else None
    return filter(path_is_python, path.iterdir())


# TODO: Port to vistir
def unnest(item):
    # type: (Any) -> Iterable[Any]
    target = None  # type: Optional[Iterable]
    if isinstance(item, Iterable) and not isinstance(item, six.string_types):
        item, target = itertools.tee(item, 2)
    else:
        target = item
    for el in target:
        if isinstance(el, Iterable) and not isinstance(el, six.string_types):
            el, el_copy = itertools.tee(el, 2)
            for sub in unnest(el_copy):
                yield sub
        else:
            yield el


def parse_pyenv_version_order(filename="version"):
    # type: (str) -> List[str]
    version_order_file = normalize_path(os.path.join(PYENV_ROOT, filename))
    if os.path.exists(version_order_file) and os.path.isfile(version_order_file):
        with io.open(version_order_file, encoding="utf-8") as fh:
            contents = fh.read()
        version_order = [v for v in contents.splitlines()]
        return version_order
    return []


def parse_asdf_version_order(filename=".tool-versions"):
    # type: (str) -> List[str]
    version_order_file = normalize_path(os.path.join("~", filename))
    if os.path.exists(version_order_file) and os.path.isfile(version_order_file):
        with io.open(version_order_file, encoding="utf-8") as fh:
            contents = fh.read()
        python_section = next(iter(
            line for line in contents.splitlines() if line.startswith("python")
        ), None)
        if python_section:
            python_key, _, versions = python_section.partition(" ")
            if versions:
                return versions.split()
    return []


# TODO: Reimplement in vistir
def is_in_path(path, parent):
    return normalize_path(str(path)).startswith(normalize_path(str(parent)))
