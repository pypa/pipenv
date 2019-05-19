from __future__ import absolute_import

import logging
import sys
from email.parser import FeedParser

from pipenv.patched.notpip._vendor import pkg_resources
from pipenv.patched.notpip._vendor.packaging import specifiers, version

from pipenv.patched.notpip._internal import exceptions
from pipenv.patched.notpip._internal.utils.misc import display_path
from pipenv.patched.notpip._internal.utils.typing import MYPY_CHECK_RUNNING

if MYPY_CHECK_RUNNING:
    from typing import Optional  # noqa: F401
    from email.message import Message  # noqa: F401
    from pipenv.patched.notpip._vendor.pkg_resources import Distribution  # noqa: F401


logger = logging.getLogger(__name__)


def check_requires_python(requires_python):
    # type: (Optional[str]) -> bool
    """
    Check if the python version in use match the `requires_python` specifier.

    Returns `True` if the version of python in use matches the requirement.
    Returns `False` if the version of python in use does not matches the
    requirement.

    Raises an InvalidSpecifier if `requires_python` have an invalid format.
    """
    if requires_python is None:
        # The package provides no information
        return True
    requires_python_specifier = specifiers.SpecifierSet(requires_python)

    # We only use major.minor.micro
    python_version = version.parse('{0}.{1}.{2}'.format(*sys.version_info[:3]))
    return python_version in requires_python_specifier


def get_metadata(dist):
    # type: (Distribution) -> Message
    if (isinstance(dist, pkg_resources.DistInfoDistribution) and
            dist.has_metadata('METADATA')):
        metadata = dist.get_metadata('METADATA')
    elif dist.has_metadata('PKG-INFO'):
        metadata = dist.get_metadata('PKG-INFO')
    else:
        logger.warning("No metadata found in %s", display_path(dist.location))
        metadata = ''

    feed_parser = FeedParser()
    feed_parser.feed(metadata)
    return feed_parser.close()


def check_dist_requires_python(dist, absorb=False):
    pkg_info_dict = get_metadata(dist)
    requires_python = pkg_info_dict.get('Requires-Python')
    if absorb:
        return requires_python
    try:
        if not check_requires_python(requires_python):
            raise exceptions.UnsupportedPythonVersion(
                "%s requires Python '%s' but the running Python is %s" % (
                    dist.project_name,
                    requires_python,
                    '.'.join(map(str, sys.version_info[:3])),)
            )
    except specifiers.InvalidSpecifier as e:
        logger.warning(
            "Package %s has an invalid Requires-Python entry %s - %s",
            dist.project_name, requires_python, e,
        )
        return


def get_installer(dist):
    # type: (Distribution) -> str
    if dist.has_metadata('INSTALLER'):
        for line in dist.get_metadata_lines('INSTALLER'):
            if line.strip():
                return line.strip()
    return ''
