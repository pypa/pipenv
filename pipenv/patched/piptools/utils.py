# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import six
import os
import sys
from itertools import chain, groupby
from collections import OrderedDict
from contextlib import contextmanager

from ._compat import InstallRequirement

from first import first
from pipenv.patched.notpip._vendor.packaging.specifiers import SpecifierSet, InvalidSpecifier
from pipenv.patched.notpip._vendor.packaging.version import Version, InvalidVersion, parse as parse_version
from pipenv.patched.notpip._vendor.packaging.markers import Marker, Op, Value, Variable
from .click import style


UNSAFE_PACKAGES = {'setuptools', 'distribute', 'pip'}


def simplify_markers(ireq):
    """simplify_markers "This code cleans up markers for a specific :class:`~InstallRequirement`"

    Clean and deduplicate markers.

    :param ireq: An InstallRequirement to clean
    :type ireq: :class:`~pip._internal.req.req_install.InstallRequirement`
    :return: An InstallRequirement with cleaned Markers
    :rtype: :class:`~pip._internal.req.req_install.InstallRequirement`
    """

    if not getattr(ireq, 'markers', None):
        return ireq
    markers = ireq.markers
    marker_list = []
    if isinstance(markers, six.string_types):
        if ';' in markers:
            markers = [Marker(m_str.strip()) for m_str in markers.split(';')]
        else:
            markers = Marker(markers)
    for m in markers._markers:
        _single_marker = []
        if isinstance(m[0], six.string_types):
            continue
        if not isinstance(m[0], (list, tuple)):
            marker_list.append(''.join([_piece.serialize() for _piece in m]))
            continue
        for _marker_part in m:
            if isinstance(_marker_part, six.string_types):
                _single_marker.append(_marker_part)
                continue
            _single_marker.append(''.join([_piece.serialize() for _piece in _marker_part]))
        _single_marker = [_m.strip() for _m in _single_marker]
        marker_list.append(tuple(_single_marker,))
    marker_str = ' and '.join(list(dedup(tuple(marker_list,)))) if marker_list else ''
    new_markers = Marker(marker_str)
    ireq.markers = new_markers
    new_ireq = InstallRequirement.from_line(format_requirement(ireq))
    if ireq.constraint:
        new_ireq.constraint = ireq.constraint
    return new_ireq


def clean_requires_python(candidates):
    """Get a cleaned list of all the candidates with valid specifiers in the `requires_python` attributes."""
    all_candidates = []
    py_version = parse_version(os.environ.get('PIP_PYTHON_VERSION', '.'.join(map(str, sys.version_info[:3]))))
    for c in candidates:
        if c.requires_python:
            # Old specifications had people setting this to single digits
            # which is effectively the same as '>=digit,<digit+1'
            if c.requires_python.isdigit():
                c.requires_python = '>={0},<{1}'.format(c.requires_python, int(c.requires_python) + 1)
            try:
                specifierset = SpecifierSet(c.requires_python)
            except InvalidSpecifier:
                continue
            else:
                if not specifierset.contains(py_version):
                    continue
        all_candidates.append(c)
    return all_candidates


def key_from_ireq(ireq):
    """Get a standardized key for an InstallRequirement."""
    if ireq.req is None and ireq.link is not None:
        return str(ireq.link)
    else:
        return key_from_req(ireq.req)


def key_from_req(req):
    """Get an all-lowercase version of the requirement's name."""
    if hasattr(req, 'key'):
        # from pkg_resources, such as installed dists for pip-sync
        key = req.key
    else:
        # from packaging, such as install requirements from requirements.txt
        key = req.name

    key = key.replace('_', '-').lower()
    return key


def comment(text):
    return style(text, fg='green')


def make_install_requirement(name, version, extras, markers, constraint=False):
    # If no extras are specified, the extras string is blank
    extras_string = ""
    if extras:
        # Sort extras for stability
        extras_string = "[{}]".format(",".join(sorted(extras)))

    if not markers:
        return InstallRequirement.from_line(
            str('{}{}=={}'.format(name, extras_string, version)),
            constraint=constraint)
    else:
        return InstallRequirement.from_line(
            str('{}{}=={}; {}'.format(name, extras_string, version, str(markers))),
            constraint=constraint)


def _requirement_to_str_lowercase_name(requirement):
    """
    Formats a packaging.requirements.Requirement with a lowercase name.

    This is simply a copy of
    https://github.com/pypa/packaging/blob/16.8/packaging/requirements.py#L109-L124
    modified to lowercase the dependency name.

    Previously, we were invoking the original Requirement.__str__ method and
    lowercasing the entire result, which would lowercase the name, *and* other,
    important stuff that should not be lowercased (such as the marker). See
    this issue for more information: https://github.com/pypa/pipenv/issues/2113.
    """
    parts = [requirement.name.lower()]

    if requirement.extras:
        parts.append("[{0}]".format(",".join(sorted(requirement.extras))))

    if requirement.specifier:
        parts.append(str(requirement.specifier))

    if requirement.url:
        parts.append("@ {0}".format(requirement.url))

    if requirement.marker:
        parts.append("; {0}".format(requirement.marker))

    return "".join(parts)


def format_requirement(ireq, marker=None):
    """
    Generic formatter for pretty printing InstallRequirements to the terminal
    in a less verbose way than using its `__str__` method.
    """
    if ireq.editable:
        line = '-e {}'.format(ireq.link)
    else:
        line = _requirement_to_str_lowercase_name(ireq.req)

    if marker and ';' not in line:
        line = '{}; {}'.format(line, marker)

    return line


def format_specifier(ireq):
    """
    Generic formatter for pretty printing the specifier part of
    InstallRequirements to the terminal.
    """
    # TODO: Ideally, this is carried over to the pip library itself
    specs = ireq.specifier._specs if ireq.req is not None else []
    specs = sorted(specs, key=lambda x: x._spec[1])
    return ','.join(str(s) for s in specs) or '<any>'


def is_pinned_requirement(ireq):
    """
    Returns whether an InstallRequirement is a "pinned" requirement.

    An InstallRequirement is considered pinned if:

    - Is not editable
    - It has exactly one specifier
    - That specifier is "=="
    - The version does not contain a wildcard

    Examples:
        django==1.8   # pinned
        django>1.8    # NOT pinned
        django~=1.8   # NOT pinned
        django==1.*   # NOT pinned
    """
    if ireq.editable:
        return False

    if len(ireq.specifier._specs) != 1:
        return False

    op, version = first(ireq.specifier._specs)._spec
    return (op == '==' or op == '===') and not version.endswith('.*')


def as_tuple(ireq):
    """
    Pulls out the (name: str, version:str, extras:(str)) tuple from the pinned InstallRequirement.
    """
    if not is_pinned_requirement(ireq):
        raise TypeError('Expected a pinned InstallRequirement, got {}'.format(ireq))

    name = key_from_req(ireq.req)
    version = first(ireq.specifier._specs)._spec[1]
    extras = tuple(sorted(ireq.extras))
    return name, version, extras


def full_groupby(iterable, key=None):
    """Like groupby(), but sorts the input on the group key first."""
    return groupby(sorted(iterable, key=key), key=key)


def flat_map(fn, collection):
    """Map a function over a collection and flatten the result by one-level"""
    return chain.from_iterable(map(fn, collection))


def lookup_table(values, key=None, keyval=None, unique=False, use_lists=False):
    """
    Builds a dict-based lookup table (index) elegantly.

    Supports building normal and unique lookup tables.  For example:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0]) == {
    ...     'b': {'bar', 'baz'},
    ...     'f': {'foo'},
    ...     'q': {'quux', 'qux'}
    ... }

    For key functions that uniquely identify values, set unique=True:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0],
    ...     unique=True) == {
    ...     'b': 'baz',
    ...     'f': 'foo',
    ...     'q': 'quux'
    ... }

    The values of the resulting lookup table will be values, not sets.

    For extra power, you can even change the values while building up the LUT.
    To do so, use the `keyval` function instead of the `key` arg:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'],
    ...     keyval=lambda s: (s[0], s[1:])) == {
    ...     'b': {'ar', 'az'},
    ...     'f': {'oo'},
    ...     'q': {'uux', 'ux'}
    ... }

    """
    if keyval is None:
        if key is None:
            keyval = (lambda v: v)
        else:
            keyval = (lambda v: (key(v), v))

    if unique:
        return dict(keyval(v) for v in values)

    lut = {}
    for value in values:
        k, v = keyval(value)
        try:
            s = lut[k]
        except KeyError:
            if use_lists:
                s = lut[k] = list()
            else:
                s = lut[k] = set()
        if use_lists:
            s.append(v)
        else:
            s.add(v)
    return dict(lut)


def dedup(iterable):
    """Deduplicate an iterable object like iter(set(iterable)) but
    order-reserved.
    """
    return iter(OrderedDict.fromkeys(iterable))


def name_from_req(req):
    """Get the name of the requirement"""
    if hasattr(req, 'project_name'):
        # from pkg_resources, such as installed dists for pip-sync
        return req.project_name
    else:
        # from packaging, such as install requirements from requirements.txt
        return req.name


def fs_str(string):
    """
    Convert given string to a correctly encoded filesystem string.

    On Python 2, if the input string is unicode, converts it to bytes
    encoded with the filesystem encoding.

    On Python 3 returns the string as is, since Python 3 uses unicode
    paths and the input string shouldn't be bytes.

    >>> fs_str(u'some path component/Something')
    'some path component/Something'
    >>> assert isinstance(fs_str('whatever'), str)
    >>> assert isinstance(fs_str(u'whatever'), str)

    :type string: str|unicode
    :rtype: str
    """
    if isinstance(string, str):
        return string
    assert not isinstance(string, bytes)
    return string.encode(_fs_encoding)


_fs_encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()


# Borrowed from pew to avoid importing pew which imports psutil
# See https://github.com/berdario/pew/blob/master/pew/_utils.py#L82
@contextmanager
def temp_environ():
    """Allow the ability to set os.environ temporarily"""
    environ = dict(os.environ)
    try:
        yield

    finally:
        os.environ.clear()
        os.environ.update(environ)
