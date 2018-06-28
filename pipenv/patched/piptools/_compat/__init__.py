# coding: utf-8
# flake8: noqa
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import six

if six.PY2:
    from .tempfile import TemporaryDirectory
    from .contextlib import ExitStack
else:
    from tempfile import TemporaryDirectory
    from contextlib import ExitStack

from .pip_compat import (
    InstallRequirement,
    parse_requirements,
    RequirementSet,
    user_cache_dir,
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
)
