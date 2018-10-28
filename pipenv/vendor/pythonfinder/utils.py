# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import itertools
import locale
import os
import subprocess
import sys

from fnmatch import fnmatch
from itertools import chain

import attr
import six

import vistir

from .exceptions import InvalidPythonVersion

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache

six.add_move(six.MovedAttribute("Iterable", "collections", "collections.abc"))
from six.moves import Iterable


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


def path_and_exists(path):
    return attr.validators.instance_of(vistir.compat.Path) and path.exists()


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


@lru_cache(maxsize=128)
def path_is_python(path):
    return path_is_executable(path) and looks_like_python(path.name)


@lru_cache(maxsize=1024)
def ensure_path(path):
    """Given a path (either a string or a Path object), expand variables and return a Path object.

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


@lru_cache(maxsize=128)
def filter_pythons(path):
    """Return all valid pythons in a given path"""
    if not isinstance(path, vistir.compat.Path):
        path = vistir.compat.Path(str(path))
    if not path.is_dir():
        return path if path_is_python(path) else None
    return filter(lambda x: path_is_python(x), path.iterdir())


# def unnest(item):
#     if isinstance(next((i for i in item), None), (list, tuple)):
#         return chain(*filter(None, item))
#     return chain(filter(None, item))


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
