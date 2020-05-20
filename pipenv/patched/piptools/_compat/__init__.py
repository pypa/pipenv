# coding: utf-8
# flake8: noqa
from __future__ import absolute_import, division, print_function, unicode_literals

import six

from .pip_compat import (
    DEV_PKGS,
    FAVORITE_HASH,
    PIP_VERSION,
    FormatControl,
    InstallationCandidate,
    InstallCommand,
    InstallationError,
    InstallRequirement,
    Link,
    PackageFinder,
    PyPI,
    RequirementSet,
    RequirementTracker,
    Resolver,
    SafeFileCache,
    VcsSupport,
    Wheel,
    WheelCache,
    cmdoptions,
    get_installed_distributions,
    install_req_from_editable,
    install_req_from_line,
    parse_requirements,
    path_to_url,
    pip_version,
    stdlib_pkgs,
    url_to_path,
    user_cache_dir,
    normalize_path,
)

if six.PY2:
    from .tempfile import TemporaryDirectory
else:
    from tempfile import TemporaryDirectory
