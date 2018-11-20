# -*- coding=utf-8 -*-
from __future__ import print_function, absolute_import
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

if sys.maxsize > 2 ** 32:
    IS_64BIT_OS = platform.machine() == "AMD64"
else:
    IS_64BIT_OS = False


IGNORE_UNSUPPORTED = bool(os.environ.get("PYTHONFINDER_IGNORE_UNSUPPORTED", False))
MYPY_RUNNING = os.environ.get("MYPY_RUNNING", is_type_checking())
