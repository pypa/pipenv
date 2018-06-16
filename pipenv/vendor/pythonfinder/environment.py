# -*- coding=utf-8 -*-
import os
import platform
import sys

PYENV_INSTALLED = bool(os.environ.get("PYENV_SHELL")) or bool(
    os.environ.get("PYENV_ROOT")
)
PYENV_ROOT = os.path.expandvars(os.environ.get("PYENV_ROOT", "~/.pyenv"))
IS_64BIT_OS = None
SYSTEM_ARCH = platform.architecture()[0]

if sys.maxsize > 2 ** 32:
    IS_64BIT_OS = platform.machine() == "AMD64"
else:
    IS_64BIT_OS = False
