# -*- coding: utf-8 -*-
from __future__ import absolute_import

import io
import os
import sys

from collections import defaultdict
from itertools import chain, groupby
from operator import attrgetter

import six
import tomlkit

from attr import validators
from first import first
from packaging.markers import InvalidMarker, Marker, Op, Value, Variable
from packaging.specifiers import InvalidSpecifier, Specifier, SpecifierSet
from vistir.misc import dedup


from ..utils import SCHEME_LIST, VCS_LIST, is_star, add_ssh_scheme_to_git_uri


HASH_STRING = " --hash={0}"


def filter_none(k, v):
    if v:
        return True
    return False


def optional_instance_of(cls):
    return validators.optional(validators.instance_of(cls))


def create_link(link):
    from pip_shims import Link
    return Link(link)


def init_requirement(name):
    from pkg_resources import Requirement
    req = Requirement.parse(name)
    req.vcs = None
    req.local_file = None
    req.revision = None
    req.path = None
    return req


def extras_to_string(extras):
    """Turn a list of extras into a string"""
    if isinstance(extras, six.string_types):
        if extras.startswith("["):
            return extras

        else:
            extras = [extras]
    return "[{0}]".format(",".join(sorted(extras)))


def parse_extras(extras_str):
    """Turn a string of extras into a parsed extras list"""
    from pkg_resources import Requirement
    extras = Requirement.parse("fakepkg{0}".format(extras_to_string(extras_str))).extras
    return sorted(dedup([extra.lower() for extra in extras]))


def specs_to_string(specs):
    """Turn a list of specifier tuples into a string"""
    if specs:
        if isinstance(specs, six.string_types):
            return specs
        try:
            extras = ",".join(["".join(spec) for spec in specs])
        except TypeError:
            extras = ",".join(["".join(spec._spec) for spec in specs])
        return extras
    return ""


def build_vcs_link(vcs, uri, name=None, ref=None, subdirectory=None, extras=None):
    if extras is None:
        extras = []
    vcs_start = "{0}+".format(vcs)
    if not uri.startswith(vcs_start):
        uri = "{0}{1}".format(vcs_start, uri)
    uri = add_ssh_scheme_to_git_uri(uri)
    if ref:
        uri = "{0}@{1}".format(uri, ref)
    if name:
        uri = "{0}#egg={1}".format(uri, name)
        if extras:
            extras = extras_to_string(extras)
            uri = "{0}{1}".format(uri, extras)
    if subdirectory:
        uri = "{0}&subdirectory={1}".format(uri, subdirectory)
    return create_link(uri)


def get_version(pipfile_entry):
    if str(pipfile_entry) == "{}" or is_star(pipfile_entry):
        return ""

    elif hasattr(pipfile_entry, "keys") and "version" in pipfile_entry:
        if is_star(pipfile_entry.get("version")):
            return ""
        return pipfile_entry.get("version", "")

    if isinstance(pipfile_entry, six.string_types):
        return pipfile_entry
    return ""


def get_pyproject(path):
    from vistir.compat import Path
    if not path:
        return
    if not isinstance(path, Path):
        path = Path(path)
    if not path.is_dir():
        path = path.parent
    pp_toml = path.joinpath("pyproject.toml")
    setup_py = path.joinpath("setup.py")
    if not pp_toml.exists():
        if setup_py.exists():
            return None
    else:
        pyproject_data = {}
        with io.open(pp_toml.as_posix(), encoding="utf-8") as fh:
            pyproject_data = tomlkit.loads(fh.read())
        build_system = pyproject_data.get("build-system", None)
        if build_system is None:
            if setup_py.exists():
                requires = ["setuptools", "wheel"]
                backend = "setuptools.build_meta"
            else:
                requires = ["setuptools>=38.2.5", "wheel"]
                backend = "setuptools.build_meta"
            build_system = {
                "requires": requires,
                "build-backend": backend
            }
            pyproject_data["build_system"] = build_system
        else:
            requires = build_system.get("requires")
            backend = build_system.get("build-backend")
        return (requires, backend)


def split_markers_from_line(line):
    """Split markers from a dependency"""
    if not any(line.startswith(uri_prefix) for uri_prefix in SCHEME_LIST):
        marker_sep = ";"
    else:
        marker_sep = "; "
    markers = None
    if marker_sep in line:
        line, markers = line.split(marker_sep, 1)
        markers = markers.strip() if markers else None
    return line, markers


def split_vcs_method_from_uri(uri):
    """Split a vcs+uri formatted uri into (vcs, uri)"""
    vcs_start = "{0}+"
    vcs = first([vcs for vcs in VCS_LIST if uri.startswith(vcs_start.format(vcs))])
    if vcs:
        vcs, uri = uri.split("+", 1)
    return vcs, uri


def validate_vcs(instance, attr_, value):
    if value not in VCS_LIST:
        raise ValueError("Invalid vcs {0!r}".format(value))


def validate_path(instance, attr_, value):
    if not os.path.exists(value):
        raise ValueError("Invalid path {0!r}".format(value))


def validate_markers(instance, attr_, value):
    try:
        Marker("{0}{1}".format(attr_.name, value))
    except InvalidMarker:
        raise ValueError("Invalid Marker {0}{1}".format(attr_, value))


def validate_specifiers(instance, attr_, value):
    if value == "":
        return True
    try:
        SpecifierSet(value)
    except (InvalidMarker, InvalidSpecifier):
        raise ValueError("Invalid Specifiers {0}".format(value))


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


def format_requirement(ireq):
    """
    Generic formatter for pretty printing InstallRequirements to the terminal
    in a less verbose way than using its `__str__` method.
    """
    if ireq.editable:
        line = '-e {}'.format(ireq.link)
    else:
        line = _requirement_to_str_lowercase_name(ireq.req)

    if str(ireq.req.marker) != str(ireq.markers):
        if not ireq.req.marker:
            line = '{}; {}'.format(line, ireq.markers)
        else:
            name, markers = line.split(";", 1)
            markers = markers.strip()
            line = '{}; ({}) and ({})'.format(name, markers, ireq.markers)

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


def get_pinned_version(ireq):
    """Get the pinned version of an InstallRequirement.

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

    Raises `TypeError` if the input is not a valid InstallRequirement, or
    `ValueError` if the InstallRequirement is not pinned.
    """
    try:
        specifier = ireq.specifier
    except AttributeError:
        raise TypeError("Expected InstallRequirement, not {}".format(
            type(ireq).__name__,
        ))

    if ireq.editable:
        raise ValueError("InstallRequirement is editable")
    if not specifier:
        raise ValueError("InstallRequirement has no version specification")
    if len(specifier._specs) != 1:
        raise ValueError("InstallRequirement has multiple specifications")

    op, version = next(iter(specifier._specs))._spec
    if op not in ('==', '===') or version.endswith('.*'):
        raise ValueError("InstallRequirement not pinned (is {0!r})".format(
            op + version,
        ))

    return version


def is_pinned_requirement(ireq):
    """Returns whether an InstallRequirement is a "pinned" requirement.

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
    try:
        get_pinned_version(ireq)
    except (TypeError, ValueError):
        return False
    return True


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


def name_from_req(req):
    """Get the name of the requirement"""
    if hasattr(req, 'project_name'):
        # from pkg_resources, such as installed dists for pip-sync
        return req.project_name
    else:
        # from packaging, such as install requirements from requirements.txt
        return req.name


def make_install_requirement(name, version, extras, markers, constraint=False):
    """make_install_requirement Generates an :class:`~pip._internal.req.req_install.InstallRequirement`.

    Create an InstallRequirement from the supplied metadata.

    :param name: The requirement's name.
    :type name: str
    :param version: The requirement version (must be pinned).
    :type version: str.
    :param extras: The desired extras.
    :type extras: list[str]
    :param markers: The desired markers, without a preceding semicolon.
    :type markers: str
    :param constraint: Whether to flag the requirement as a constraint, defaults to False.
    :param constraint: bool, optional
    :return: A generated InstallRequirement
    :rtype: :class:`~pip._internal.req.req_install.InstallRequirement`
    """

    # If no extras are specified, the extras string is blank
    from pip_shims.shims import install_req_from_line
    extras_string = ""
    if extras:
        # Sort extras for stability
        extras_string = "[{}]".format(",".join(sorted(extras)))

    if not markers:
        return install_req_from_line(
            str('{}{}=={}'.format(name, extras_string, version)),
            constraint=constraint)
    else:
        return install_req_from_line(
            str('{}{}=={}; {}'.format(name, extras_string, version, str(markers))),
            constraint=constraint)


def version_from_ireq(ireq):
    """version_from_ireq Extract the version from a supplied :class:`~pip._internal.req.req_install.InstallRequirement`

    :param ireq: An InstallRequirement
    :type ireq: :class:`~pip._internal.req.req_install.InstallRequirement`
    :return: The version of the InstallRequirement.
    :rtype: str
    """

    return first(ireq.specifier._specs).version


def clean_requires_python(candidates):
    """Get a cleaned list of all the candidates with valid specifiers in the `requires_python` attributes."""
    all_candidates = []
    sys_version = '.'.join(map(str, sys.version_info[:3]))
    from packaging.version import parse as parse_version
    py_version = parse_version(os.environ.get('PIP_PYTHON_VERSION', sys_version))
    for c in candidates:
        from_location = attrgetter("location.requires_python")
        requires_python = getattr(c, "requires_python", from_location(c))
        if requires_python:
            # Old specifications had people setting this to single digits
            # which is effectively the same as '>=digit,<digit+1'
            if requires_python.isdigit():
                requires_python = '>={0},<{1}'.format(requires_python, int(requires_python) + 1)
            try:
                specifierset = SpecifierSet(requires_python)
            except InvalidSpecifier:
                continue
            else:
                if not specifierset.contains(py_version):
                    continue
        all_candidates.append(c)
    return all_candidates


def fix_requires_python_marker(requires_python):
    from packaging.requirements import Requirement as PackagingRequirement
    marker_str = ''
    if any(requires_python.startswith(op) for op in Specifier._operators.keys()):
        spec_dict = defaultdict(set)
        # We are checking first if we have  leading specifier operator
        # if not, we can assume we should be doing a == comparison
        specifierset = list(SpecifierSet(requires_python))
        # for multiple specifiers, the correct way to represent that in
        # a specifierset is `Requirement('fakepkg; python_version<"3.0,>=2.6"')`
        marker_key = Variable('python_version')
        for spec in specifierset:
            operator, val = spec._spec
            cleaned_val = Value(val).serialize().replace('"', "")
            spec_dict[Op(operator).serialize()].add(cleaned_val)
        marker_str = ' and '.join([
            "{0}{1}'{2}'".format(marker_key.serialize(), op, ','.join(vals))
            for op, vals in spec_dict.items()
        ])
    marker_to_add = PackagingRequirement('fakepkg; {0}'.format(marker_str)).marker
    return marker_to_add


def normalize_name(pkg):
    """Given a package name, return its normalized, non-canonicalized form.

    :param str pkg: The name of a package
    :return: A normalized package name
    :rtype: str
    """

    assert isinstance(pkg, six.string_types)
    return pkg.replace("_", "-").lower()
