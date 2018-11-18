# -*- coding=utf-8 -*-

__all__ = [
    "InstallRequirement",
    "parse_requirements",
    "RequirementSet",
    "user_cache_dir",
    "FAVORITE_HASH",
    "is_file_url",
    "url_to_path",
    "PackageFinder",
    "FormatControl",
    "Wheel",
    "Command",
    "cmdoptions",
    "get_installed_distributions",
    "PyPI",
    "SafeFileCache",
    "InstallationError",
    "parse_version",
    "pip_version",
    "install_req_from_editable",
    "install_req_from_line",
    "user_cache_dir"
]

from pipenv.vendor.appdirs import user_cache_dir
from pip_shims.shims import (
    InstallRequirement,
    parse_requirements,
    RequirementSet,
    FAVORITE_HASH,
    is_file_url,
    url_to_path,
    PackageFinder,
    FormatControl,
    Wheel,
    Command,
    cmdoptions,
    get_installed_distributions,
    PyPI,
    SafeFileCache,
    InstallationError,
    parse_version,
    pip_version,
)

# pip 18.1 has refactored InstallRequirement constructors use by pip-tools.
if parse_version(pip_version) < parse_version('18.1'):
    install_req_from_line = InstallRequirement.from_line
    install_req_from_editable = InstallRequirement.from_editable
else:
    from pip_shims.shims import (
        install_req_from_editable, install_req_from_line
    )
