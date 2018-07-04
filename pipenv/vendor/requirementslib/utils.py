# -*- coding=utf-8 -*-
from __future__ import absolute_import
import logging
import os
import posixpath
import six

from itertools import product

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path

VCS_LIST = ("git", "svn", "hg", "bzr")
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")


def setup_logger():
    logger = logging.getLogger("requirementslib")
    loglevel = logging.DEBUG
    handler = logging.StreamHandler()
    handler.setLevel(loglevel)
    logger.addHandler(handler)
    logger.setLevel(loglevel)
    return logger


log = setup_logger()


def is_vcs(pipfile_entry):
    """Determine if dictionary entry from Pipfile is for a vcs dependency."""
    if hasattr(pipfile_entry, "keys"):
        return any(key for key in pipfile_entry.keys() if key in VCS_LIST)

    elif isinstance(pipfile_entry, six.string_types):
        vcs_starts = product(
            ("git+", "hg+", "svn+", "bzr+"),
            ("file", "ssh", "https", "http", "svn", "sftp", ""),
        )

        return next(
            (
                v
                for v in (
                    pipfile_entry.startswith("{0}{1}".format(vcs, scheme))
                    for vcs, scheme in vcs_starts
                )
                if v
            ),
            False,
        )

    return False


def get_converted_relative_path(path, relative_to=os.curdir):
    """Convert `path` to be relative.

    Given a vague relative path, return the path relative to the given
    location.

    This performs additional conversion to ensure the result is of POSIX form,
    and starts with `./`, or is precisely `.`.
    """
    start = Path(relative_to)
    try:
        start = start.resolve()
    except OSError:
        start = start.absolute()
    path = start.joinpath(path).relative_to(start)

    relpath_s = posixpath.normpath(path.as_posix())
    if not (relpath_s == "." or relpath_s.startswith("./")):
        relpath_s = posixpath.join(".", relpath_s)
    return relpath_s


def multi_split(s, split):
    """Splits on multiple given separators."""
    for r in split:
        s = s.replace(r, "|")
    return [i for i in s.split("|") if len(i) > 0]


def is_star(val):
    return isinstance(val, six.string_types) and val == "*"


def is_installable_file(path):
    """Determine if a path can potentially be installed"""
    from ._compat import is_installable_dir, is_archive_file
    from packaging import specifiers

    if hasattr(path, "keys") and any(
        key for key in path.keys() if key in ["file", "path"]
    ):
        path = urlparse(path["file"]).path if "file" in path else path["path"]
    if not isinstance(path, six.string_types) or path == "*":
        return False

    # If the string starts with a valid specifier operator, test if it is a valid
    # specifier set before making a path object (to avoid breaking windows)
    if any(path.startswith(spec) for spec in "!=<>~"):
        try:
            specifiers.SpecifierSet(path)
        # If this is not a valid specifier, just move on and try it as a path
        except specifiers.InvalidSpecifier:
            pass
        else:
            return False

    parsed = urlparse(path)
    if parsed.scheme == "file":
        path = parsed.path

    if not os.path.exists(os.path.abspath(path)):
        return False

    lookup_path = Path(path)
    absolute_path = "{0}".format(lookup_path.absolute())
    if lookup_path.is_dir() and is_installable_dir(absolute_path):
        return True

    elif lookup_path.is_file() and is_archive_file(absolute_path):
        return True

    return False


def is_valid_url(url):
    """Checks if a given string is an url"""
    pieces = urlparse(url)
    return all([pieces.scheme, any([pieces.netloc, pieces.path])])


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    name = name.lower()
    if any(i not in name for i in (VCS_LIST + SCHEME_LIST)):
        return name.replace("_", "-")

    else:
        return name


def prepare_pip_source_args(sources, pip_args=None):
    if pip_args is None:
        pip_args = []
    if sources:
        # Add the source to pip9.
        pip_args.extend(["-i", sources[0]["url"]])
        # Trust the host if it's not verified.
        if not sources[0].get("verify_ssl", True):
            pip_args.extend(
                ["--trusted-host", urlparse(sources[0]["url"]).hostname]
            )
        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                pip_args.extend(["--extra-index-url", source["url"]])
                # Trust the host if it's not verified.
                if not source.get("verify_ssl", True):
                    pip_args.extend(
                        ["--trusted-host", urlparse(source["url"]).hostname]
                    )
    return pip_args
