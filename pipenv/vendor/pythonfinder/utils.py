# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import itertools
import os

from fnmatch import fnmatch

import attr
import io
import six

import vistir

from .environment import PYENV_ROOT, ASDF_DATA_DIR
from .exceptions import InvalidPythonVersion

six.add_move(six.MovedAttribute("Iterable", "collections", "collections.abc"))
from six.moves import Iterable

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache


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


@lru_cache(maxsize=128)
def get_python_version(path):
    """Get python version string using subprocess from a given path."""
    version_cmd = [path, "-c", "import sys; print(sys.version.split()[0])"]
    try:
        c = vistir.misc.run(version_cmd, block=True, nospin=True, return_object=True,
                                combine_stderr=False)
    except OSError:
        raise InvalidPythonVersion("%s is not a valid python path" % path)
    if not c.out:
        raise InvalidPythonVersion("%s is not a valid python path" % path)
    return c.out.strip()


def optional_instance_of(cls):
    return attr.validators.optional(attr.validators.instance_of(cls))


def path_is_executable(path):
    return os.access(str(path), os.X_OK)


@lru_cache(maxsize=1024)
def path_is_known_executable(path):
    return (
        path_is_executable(path)
        or os.access(str(path), os.R_OK)
        and path.suffix in KNOWN_EXTS
    )


@lru_cache(maxsize=1024)
def looks_like_python(name):
    if not any(name.lower().startswith(py_name) for py_name in PYTHON_IMPLEMENTATIONS):
        return False
    return any(fnmatch(name, rule) for rule in MATCH_RULES)


@lru_cache(maxsize=1024)
def path_is_python(path):
    return path_is_executable(path) and looks_like_python(path.name)


@lru_cache(maxsize=1024)
def ensure_path(path):
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
    if v:
        return True
    return False


# TODO: Reimplement in vistir
def normalize_path(path):
    return os.path.normpath(os.path.normcase(
        os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))
    ))


@lru_cache(maxsize=1024)
def filter_pythons(path):
    """Return all valid pythons in a given path"""
    if not isinstance(path, vistir.compat.Path):
        path = vistir.compat.Path(str(path))
    if not path.is_dir():
        return path if path_is_python(path) else None
    return filter(path_is_python, path.iterdir())


# TODO: Port to vistir
def unnest(item):
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
    version_order_file = normalize_path(os.path.join(PYENV_ROOT, filename))
    if os.path.exists(version_order_file) and os.path.isfile(version_order_file):
        with io.open(version_order_file, encoding="utf-8") as fh:
            contents = fh.read()
        version_order = [v for v in contents.splitlines()]
        return version_order


def parse_asdf_version_order(filename=".tool-versions"):
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


# TODO: Reimplement in vistir
def is_in_path(path, parent):
    return normalize_path(str(path)).startswith(normalize_path(str(parent)))
