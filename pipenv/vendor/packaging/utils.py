# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the BSD License. See the LICENSE file in the root of this repository
# for complete details.

from __future__ import annotations

import re
from typing import NewType, Union, cast

from .tags import InvalidTag, Tag, UnsortedTagsError, parse_tag
from .version import InvalidVersion, Version, _TrimmedRelease

__all__ = [
    "BuildTag",
    "InvalidName",
    "InvalidSdistFilename",
    "InvalidWheelFilename",
    "NormalizedName",
    "canonicalize_name",
    "canonicalize_version",
    "is_normalized_name",
    "parse_sdist_filename",
    "parse_wheel_filename",
]


def __dir__() -> list[str]:
    return __all__


BuildTag = Union[tuple[()], tuple[int, str]]
"""
A wheel build tag: an empty tuple, or a ``(build number, build tag suffix)`` pair.

.. versionadded:: 20.9
"""

NormalizedName = NewType("NormalizedName", str)
"""
A :class:`typing.NewType` of :class:`str`, representing a normalized name.

.. versionadded:: 20.4
"""


class InvalidName(ValueError):
    """
    An invalid distribution name; users should refer to the packaging user guide.

    .. versionadded:: 23.2
    """


class InvalidWheelFilename(ValueError):
    """
    An invalid wheel filename was found, users should refer to PEP 427.

    .. versionadded:: 20.9
    """


class InvalidSdistFilename(ValueError):
    """
    An invalid sdist filename was found, users should refer to the packaging user guide.

    .. versionadded:: 20.9
    """


# Core metadata spec for `Name`
_validate_regex = re.compile(
    r"[a-z0-9]|[a-z0-9][a-z0-9._-]*[a-z0-9]", re.IGNORECASE | re.ASCII
)
_normalized_regex = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.ASCII)
# PEP 427: The build number must start with a digit.
_build_tag_regex = re.compile(r"(\d+)(.*)", re.ASCII)
# PEP 427: Valid characters for an escaped project name in a wheel filename.
# Requires at least one character so an empty project name is rejected.
_wheel_name_regex = re.compile(r"^[\w._]+\Z", re.UNICODE)


def canonicalize_name(name: str, *, validate: bool = False) -> NormalizedName:
    """
    This function takes a valid Python package or extra name, and returns the
    normalized form of it.

    The return type is typed as :class:`NormalizedName`. This allows type
    checkers to help require that a string has passed through this function
    before use.

    If **validate** is true, then the function will check if **name** is a valid
    distribution name before normalizing.

    :param str name: The name to normalize.
    :param bool validate: Check whether the name is a valid distribution name.
    :raises InvalidName: If **validate** is true and the name is not an
        acceptable distribution name.

    >>> from packaging.utils import canonicalize_name
    >>> canonicalize_name("Django")
    'django'
    >>> canonicalize_name("oslo.concurrency")
    'oslo-concurrency'
    >>> canonicalize_name("requests")
    'requests'

    .. versionadded:: 16.2

    .. versionchanged:: 20.4
       The return type was changed to :class:`NormalizedName`.

    .. versionchanged:: 23.2
       Added the *validate* keyword parameter.
    """
    if validate and not _validate_regex.fullmatch(name):
        raise InvalidName(f"name is invalid: {name!r}")
    # Ensure all ``.`` and ``_`` are ``-``
    # Emulates ``re.sub(r"[-_.]+", "-", name).lower()`` from PEP 503
    # Much faster than re, and even faster than str.translate
    value = name.lower().replace("_", "-").replace(".", "-")
    # Condense repeats (faster than regex)
    while "--" in value:
        value = value.replace("--", "-")
    return cast("NormalizedName", value)


def is_normalized_name(name: str) -> bool:
    """
    Check if a name is a normalized project name (i.e. a valid name that
    :func:`canonicalize_name` would roundtrip to the same value).

    The roundtrip only characterizes normalized names for *valid* names. A name
    must start and end with an ASCII letter or digit, which
    :func:`canonicalize_name` does not enforce: it leaves a leading or trailing
    hyphen in place, so such a name roundtrips without being normalized.

    :param str name: The name to check.

    >>> from packaging.utils import canonicalize_name, is_normalized_name
    >>> is_normalized_name("requests")
    True
    >>> is_normalized_name("Django")
    False
    >>> canonicalize_name("_not_legal")
    '-not-legal'
    >>> is_normalized_name("-not-legal")  # roundtrips, but not a valid name
    False

    .. versionadded:: 23.2
    """
    return _normalized_regex.fullmatch(name) is not None


def canonicalize_version(
    version: Version | str, *, strip_trailing_zero: bool = True
) -> str:
    """Return a canonical form of a version as a string.

    This function takes a string representing a package version (or a
    :class:`~packaging.version.Version` instance), and returns the
    normalized form of it. By default, it strips trailing zeros from
    the release segment.

    >>> from packaging.utils import canonicalize_version
    >>> canonicalize_version('1.0.1')
    '1.0.1'

    Per PEP 625, versions may have multiple canonical forms, differing
    only by trailing zeros.

    >>> canonicalize_version('1.0.0')
    '1'
    >>> canonicalize_version('1.0.0', strip_trailing_zero=False)
    '1.0.0'

    Invalid versions are returned unaltered.

    >>> canonicalize_version('foo bar baz')
    'foo bar baz'

    >>> canonicalize_version('1.4.0.0.0')
    '1.4'

    .. versionadded:: 17.1

    .. versionchanged:: 21.0
       The return type was narrowed to :class:`str`.

    .. versionchanged:: 22.0
       Added the *strip_trailing_zero* keyword parameter.
    """
    if isinstance(version, str):
        try:
            version = Version(version)
        except InvalidVersion:
            return str(version)
    return str(_TrimmedRelease(version) if strip_trailing_zero else version)


def parse_wheel_filename(
    filename: str,
    *,
    validate_order: bool = False,
) -> tuple[NormalizedName, Version, BuildTag, frozenset[Tag]]:
    """
    This function takes the filename of a wheel file, and parses it,
    returning a tuple of name, version, build number, and tags.

    The name part of the tuple is normalized and typed as
    :class:`NormalizedName`. The version portion is an instance of
    :class:`~packaging.version.Version`. The build number is ``()`` if
    there is no build number in the wheel filename, otherwise a
    two-item tuple of an integer for the leading digits and
    a string for the rest of the build number. The tags portion is a
    frozen set of :class:`~packaging.tags.Tag` instances (as the tag
    string format allows multiple tags to be combined into a single
    string).

    If **validate_order** is true, compressed tag set components are
    checked to be in sorted order as required by PEP 425.

    :param str filename: The name of the wheel file.
    :param bool validate_order: Check whether compressed tag set components
        are in sorted order.
    :raises InvalidWheelFilename: If the filename in question
        does not follow the :ref:`wheel specification
        <pypug:binary-distribution-format>`.

    >>> from packaging.utils import parse_wheel_filename
    >>> from packaging.tags import Tag
    >>> from packaging.version import Version
    >>> name, ver, build, tags = parse_wheel_filename("foo-1.0-py3-none-any.whl")
    >>> name
    'foo'
    >>> ver == Version('1.0')
    True
    >>> tags == {Tag("py3", "none", "any")}
    True
    >>> not build
    True

    .. versionadded:: 20.9

    .. versionchanged:: 23.2
       Raises :class:`InvalidWheelFilename` when the version component is invalid.

    .. versionadded:: 26.1
       The *validate_order* parameter.

    .. versionchanged:: 26.3
       Raises :class:`InvalidWheelFilename` when an interpreter component is
       not an identifier, a tag set component is empty, or the project name is
       empty.
    """
    if not filename.endswith(".whl"):
        raise InvalidWheelFilename(
            f"Invalid wheel filename (extension must be '.whl'): {filename!r}"
        )

    filename = filename[:-4]
    dashes = filename.count("-")
    if dashes not in (4, 5):
        raise InvalidWheelFilename(
            f"Invalid wheel filename (wrong number of parts): {filename!r}"
        )

    parts = filename.split("-", dashes - 2)
    name_part = parts[0]
    # See PEP 427 for the rules on escaping the project name.
    if "__" in name_part or _wheel_name_regex.match(name_part) is None:
        raise InvalidWheelFilename(f"Invalid project name: {filename!r}")
    name = canonicalize_name(name_part)

    try:
        version = Version(parts[1])
    except InvalidVersion as e:
        raise InvalidWheelFilename(
            f"Invalid wheel filename (invalid version): {filename!r}"
        ) from e

    if dashes == 5:
        build_part = parts[2]
        build_match = _build_tag_regex.match(build_part)
        if build_match is None:
            raise InvalidWheelFilename(
                f"Invalid build number: {build_part} in {filename!r}"
            )
        build = cast("BuildTag", (int(build_match.group(1)), build_match.group(2)))
    else:
        build = ()
    tag_str = parts[-1]
    try:
        tags = parse_tag(tag_str, validate_order=validate_order)
    except UnsortedTagsError:
        raise InvalidWheelFilename(
            f"Invalid wheel filename (compressed tag set components must be in "
            f"sorted order per PEP 425): {filename!r}"
        ) from None
    except InvalidTag:
        raise InvalidWheelFilename(
            f"Invalid wheel filename (invalid tag component): {filename!r}"
        ) from None
    return (name, version, build, tags)


def parse_sdist_filename(filename: str) -> tuple[NormalizedName, Version]:
    """
    This function takes the filename of a sdist file (as specified
    in the `Source distribution format`_ documentation), and parses
    it, returning a tuple of the normalized name and version as
    represented by an instance of :class:`~packaging.version.Version`.

    :param str filename: The name of the sdist file.
    :raises InvalidSdistFilename: If the filename does not end
        with an sdist extension (``.zip`` or ``.tar.gz``), if it does not
        contain a dash separating the name and the version of the distribution,
        if the project name is empty, or if the version portion is not a valid
        version.

    >>> from packaging.utils import parse_sdist_filename
    >>> from packaging.version import Version
    >>> name, ver = parse_sdist_filename("foo-1.0.tar.gz")
    >>> name
    'foo'
    >>> ver == Version('1.0')
    True

    .. versionadded:: 20.9

    .. versionchanged:: 21.0
       Added support for ``.zip`` source distributions.

    .. versionchanged:: 23.2
       Raises :class:`InvalidSdistFilename` when the version component is invalid.

    .. versionchanged:: 26.3
       Raises :class:`InvalidSdistFilename` on an empty project name.

    .. _Source distribution format: https://packaging.python.org/specifications/source-distribution-format/#source-distribution-file-name
    """
    if filename.endswith(".tar.gz"):
        file_stem = filename[: -len(".tar.gz")]
    elif filename.endswith(".zip"):
        file_stem = filename[: -len(".zip")]
    else:
        raise InvalidSdistFilename(
            f"Invalid sdist filename (extension must be '.tar.gz' or '.zip'):"
            f" {filename!r}"
        )

    # We are requiring a PEP 440 version, which cannot contain dashes,
    # so we split on the last dash.
    name_part, sep, version_part = file_stem.rpartition("-")
    if not sep:
        raise InvalidSdistFilename(f"Invalid sdist filename: {filename!r}")
    if not name_part:
        raise InvalidSdistFilename(
            f"Invalid sdist filename (empty project name): {filename!r}"
        )

    name = canonicalize_name(name_part)

    try:
        version = Version(version_part)
    except InvalidVersion as e:
        raise InvalidSdistFilename(
            f"Invalid sdist filename (invalid version): {filename!r}"
        ) from e

    return (name, version)
