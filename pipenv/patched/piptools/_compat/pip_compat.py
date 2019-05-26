# -*- coding=utf-8 -*-
__all__ = [
    "InstallRequirement",
    "parse_requirements",
    "RequirementSet",
    "FAVORITE_HASH",
    "is_file_url",
    "path_to_url",
    "url_to_path",
    "PackageFinder",
    "FormatControl",
    "Wheel",
    "Command",
    "cmdoptions",
    "get_installed_distributions",
    "PyPI",
    "stdlib_pkgs",
    "DEV_PKGS",
    "install_req_from_line",
    "install_req_from_editable",
    "user_cache_dir",
    "SafeFileCache",
    "InstallationError"
]

import os
os.environ["PIP_SHIMS_BASE_MODULE"] = str("pipenv.patched.notpip")

from pip_shims.shims import (
    InstallRequirement,
    parse_requirements,
    RequirementSet,
    FAVORITE_HASH,
    is_file_url,
    path_to_url,
    url_to_path,
    PackageFinder,
    FormatControl,
    Wheel,
    Command,
    cmdoptions,
    get_installed_distributions,
    PyPI,
    stdlib_pkgs,
    DEV_PKGS,
    install_req_from_line,
    install_req_from_editable,
    USER_CACHE_DIR as user_cache_dir,
    SafeFileCache,
    InstallationError
)
