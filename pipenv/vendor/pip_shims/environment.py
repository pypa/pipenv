# -*- coding=utf-8 -*-
"""
Module with functionality to learn about the environment.
"""
from __future__ import absolute_import

import importlib
import os


def get_base_import_path():
    base_import_path = os.environ.get("PIP_SHIMS_BASE_MODULE", "pip")
    return base_import_path


BASE_IMPORT_PATH = get_base_import_path()


def get_pip_version(import_path=BASE_IMPORT_PATH):
    try:
        pip = importlib.import_module(import_path)
    except ImportError:
        if import_path != "pip":
            return get_pip_version(import_path="pip")
        else:
            import subprocess

            version = subprocess.check_output(["pip", "--version"])
            if version:
                version = version.decode("utf-8").split()[1]
                return version
            return "0.0.0"
    version = getattr(pip, "__version__", None)
    return version


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


MYPY_RUNNING = os.environ.get("MYPY_RUNNING", is_type_checking())
