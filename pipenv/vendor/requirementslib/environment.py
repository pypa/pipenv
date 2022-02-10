# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import os

from pipenv.vendor.platformdirs import user_cache_dir


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


REQUIREMENTSLIB_CACHE_DIR = os.getenv(
    "REQUIREMENTSLIB_CACHE_DIR", user_cache_dir("pipenv")
)
MYPY_RUNNING = os.environ.get("MYPY_RUNNING", is_type_checking())
