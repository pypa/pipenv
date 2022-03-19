# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import os
import platform
import sys


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


PYENV_INSTALLED = bool(os.environ.get("PYENV_SHELL")) or bool(
    os.environ.get("PYENV_ROOT")
)
ASDF_INSTALLED = bool(os.environ.get("ASDF_DIR"))
PYENV_ROOT = os.path.expanduser(
    os.path.expandvars(os.environ.get("PYENV_ROOT", "~/.pyenv"))
)
ASDF_DATA_DIR = os.path.expanduser(
    os.path.expandvars(os.environ.get("ASDF_DATA_DIR", "~/.asdf"))
)
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


def get_shim_paths():
    shim_paths = []
    if ASDF_INSTALLED:
        shim_paths.append(os.path.join(ASDF_DATA_DIR, "shims"))
    if PYENV_INSTALLED:
        shim_paths.append(os.path.join(PYENV_ROOT, "shims"))
    return [os.path.normpath(os.path.normcase(p)) for p in shim_paths]


SHIM_PATHS = get_shim_paths()
