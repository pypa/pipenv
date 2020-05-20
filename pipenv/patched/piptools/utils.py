# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from collections import OrderedDict
from itertools import chain, groupby

import six
from click.utils import LazyFile
from ._compat import install_req_from_line
from six.moves import shlex_quote
from pipenv.vendor.packaging.specifiers import SpecifierSet, InvalidSpecifier
from pipenv.vendor.packaging.version import Version, InvalidVersion, parse as parse_version
from pipenv.vendor.packaging.markers import Marker, Op, Value, Variable


from ._compat import PIP_VERSION
from .click import style

UNSAFE_PACKAGES = {"setuptools", "distribute", "pip"}
COMPILE_EXCLUDE_OPTIONS = {
    "--dry-run",
    "--quiet",
    "--rebuild",
    "--upgrade",
    "--upgrade-package",
    "--verbose",
    "--cache-dir",
}


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
    new_ireq = install_req_from_line(format_requirement(ireq))
    if ireq.constraint:
        new_ireq.constraint = ireq.constraint
    return new_ireq


def clean_requires_python(candidates):
    """Get a cleaned list of all the candidates with valid specifiers in the `requires_python` attributes."""
    all_candidates = []
    py_version = parse_version(os.environ.get('PIPENV_REQUESTED_PYTHON_VERSION', '.'.join(map(str, sys.version_info[:3]))))
    for c in candidates:
        if getattr(c, "requires_python", None):
            # Old specifications had people setting this to single digits
            # which is effectively the same as '>=digit,<digit+1'
            if len(c.requires_python) == 1 and c.requires_python in ("2", "3"):
                c.requires_python = '>={0},<{1!s}'.format(c.requires_python, int(c.requires_python) + 1)
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
    if hasattr(req, "key"):
        # from pkg_resources, such as installed dists for pip-sync
        key = req.key
    else:
        # from packaging, such as install requirements from requirements.txt
        key = req.name

    key = key.replace("_", "-").lower()
    return key


def comment(text):
    return style(text, fg="green")


def make_install_requirement(name, version, extras, markers, constraint=False):
    # If no extras are specified, the extras string is blank
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


def _requirement_to_str_lowercase_name(requirement):
    """
    Formats a packaging.requirements.Requirement with a lowercase name.

    This is simply a copy of
    https://github.com/pypa/pipenv/patched/packaging/blob/pipenv/patched/16.8/packaging/requirements.py#L109-L124
    modified to lowercase the dependency name.

    Previously, we were invoking the original Requirement.__str__ method and
    lowercasing the entire result, which would lowercase the name, *and* other,
    important stuff that should not be lowercased (such as the marker). See
    this issue for more information: https://github.com/pypa/pipenv/patched/pipenv/issues/2113.
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


def is_url_requirement(ireq):
    """
    Return True if requirement was specified as a path or URL.
    ireq.original_link will have been set by InstallRequirement.__init__
    """
    return bool(ireq.original_link)


def format_requirement(ireq, marker=None, hashes=None):
    """
    Generic formatter for pretty printing InstallRequirements to the terminal
    in a less verbose way than using its `__str__` method.
    """
    if ireq.editable:
        line = "-e {}".format(ireq.link.url)
    elif ireq.link and ireq.link.is_vcs:
        line = str(ireq.req)
    elif is_url_requirement(ireq):
        line = ireq.link.url
    else:
        line = _requirement_to_str_lowercase_name(ireq.req)

    if marker and ';' not in line:
        line = "{}; {}".format(line, marker)

    if hashes:
        for hash_ in sorted(hashes):
            line += " \\\n    --hash={}".format(hash_)

    return line


def format_specifier(ireq):
    """
    Generic formatter for pretty printing the specifier part of
    InstallRequirements to the terminal.
    """
    # TODO: Ideally, this is carried over to the pip library itself
    specs = ireq.specifier._specs if ireq.req is not None else []
    specs = sorted(specs, key=lambda x: x._spec[1])
    return ",".join(str(s) for s in specs) or "<any>"


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

    if ireq.req is None or len(ireq.specifier._specs) != 1:
        return False

    op, version = next(iter(ireq.specifier._specs))._spec
    return (op == "==" or op == "===") and not version.endswith(".*")


def as_tuple(ireq):
    """
    Pulls out the (name: str, version:str, extras:(str)) tuple from
    the pinned InstallRequirement.
    """
    if not is_pinned_requirement(ireq):
        raise TypeError("Expected a pinned InstallRequirement, got {}".format(ireq))

    name = key_from_ireq(ireq)
    version = next(iter(ireq.specifier._specs))._spec[1]
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

    For the values represented as lists, set use_lists=True:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0],
    ...     use_lists=True) == {
    ...     'b': ['bar', 'baz'],
    ...     'f': ['foo'],
    ...     'q': ['qux', 'quux']
    ... }

    The values of the resulting lookup table will be lists, not sets.

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

            def keyval(v):
                return v

        else:

            def keyval(v):
                return (key(v), v)

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
    order-preserved.
    """
    return iter(OrderedDict.fromkeys(iterable))


def name_from_req(req):
    """Get the name of the requirement"""
    if hasattr(req, "project_name"):
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

    :type string: str|unicode
    :rtype: str
    """
    if isinstance(string, str):
        return string
    if isinstance(string, bytes):
        raise AssertionError
    return string.encode(_fs_encoding)


_fs_encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()


def get_hashes_from_ireq(ireq):
    """
    Given an InstallRequirement, return a list of string hashes in
    the format "{algorithm}:{hash}". Return an empty list if there are no hashes
    in the requirement options.
    """
    result = []
    if PIP_VERSION[:2] <= (20, 0):
        ireq_hashes = ireq.options.get("hashes", {})
    else:
        ireq_hashes = ireq.hash_options
    for algorithm, hexdigests in ireq_hashes.items():
        for hash_ in hexdigests:
            result.append("{}:{}".format(algorithm, hash_))
    return result


def force_text(s):
    """
    Return a string representing `s`.
    """
    if s is None:
        return ""
    if not isinstance(s, six.string_types):
        return six.text_type(s)
    return s


def get_compile_command(click_ctx):
    """
    Returns a normalized compile command depending on cli context.

    The command will be normalized by:
        - expanding options short to long
        - removing values that are already default
        - sorting the arguments
        - removing one-off arguments like '--upgrade'
        - removing arguments that don't change build behaviour like '--verbose'
    """
    from piptools.scripts.compile import cli

    # Map of the compile cli options (option name -> click.Option)
    compile_options = {option.name: option for option in cli.params}

    left_args = []
    right_args = []

    for option_name, value in click_ctx.params.items():
        option = compile_options[option_name]

        # Get the latest option name (usually it'll be a long name)
        option_long_name = option.opts[-1]

        # Collect variadic args separately, they will be added
        # at the end of the command later
        if option.nargs < 0:
            # These will necessarily be src_files
            # Re-add click-stripped '--' if any start with '-'
            if any(val.startswith("-") and val != "-" for val in value):
                right_args.append("--")
            right_args.extend([shlex_quote(force_text(val)) for val in value])
            continue

        # Exclude one-off options (--upgrade/--upgrade-package/--rebuild/...)
        # or options that don't change compile behaviour (--verbose/--dry-run/...)
        if option_long_name in COMPILE_EXCLUDE_OPTIONS:
            continue

        # Skip options without a value
        if option.default is None and not value:
            continue

        # Skip options with a default value
        if option.default == value:
            continue

        # Use a file name for file-like objects
        if isinstance(value, LazyFile):
            value = value.name

        # Convert value to the list
        if not isinstance(value, (tuple, list)):
            value = [value]

        for val in value:
            # Flags don't have a value, thus add to args true or false option long name
            if option.is_flag:
                # If there are false-options, choose an option name depending on a value
                if option.secondary_opts:
                    # Get the latest false-option
                    secondary_option_long_name = option.secondary_opts[-1]
                    arg = option_long_name if val else secondary_option_long_name
                # There are no false-options, use true-option
                else:
                    arg = option_long_name
                left_args.append(shlex_quote(arg))
            # Append to args the option with a value
            else:
                if option.name == "pip_args":
                    # shlex_quote would produce functional but noisily quoted results,
                    # e.g. --pip-args='--cache-dir='"'"'/tmp/with spaces'"'"''
                    # Instead, we try to get more legible quoting via repr:
                    left_args.append(
                        "{option}={value}".format(
                            option=option_long_name, value=repr(fs_str(force_text(val)))
                        )
                    )
                else:
                    left_args.append(
                        "{option}={value}".format(
                            option=option_long_name, value=shlex_quote(force_text(val))
                        )
                    )

    return " ".join(["pip-compile"] + sorted(left_args) + sorted(right_args))
