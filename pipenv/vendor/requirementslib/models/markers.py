# -*- coding: utf-8 -*-
import itertools
import operator
import re

import attr
import distlib.markers
import packaging.version
import six
from packaging.markers import InvalidMarker, Marker
from packaging.specifiers import Specifier, SpecifierSet
from vistir.compat import Mapping, Set, lru_cache
from vistir.misc import dedup

from ..environment import MYPY_RUNNING
from ..exceptions import RequirementError
from .utils import filter_none, validate_markers

from six.moves import reduce  # isort:skip


if MYPY_RUNNING:
    from typing import Optional, List, Type, Any, Tuple, Union, AnyStr, Text, Iterator

    STRING_TYPE = Union[str, bytes, Text]


MAX_VERSIONS = {1: 7, 2: 7, 3: 11, 4: 0}
DEPRECATED_VERSIONS = ["3.0", "3.1", "3.2", "3.3"]


def is_instance(item, cls):
    # type: (Any, Type) -> bool
    if isinstance(item, cls) or item.__class__.__name__ == cls.__name__:
        return True
    return False


@attr.s
class PipenvMarkers(object):
    """System-level requirements - see PEP508 for more detail"""

    os_name = attr.ib(default=None, validator=attr.validators.optional(validate_markers))
    sys_platform = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_machine = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_python_implementation = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_release = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_system = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    python_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    python_full_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    implementation_name = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    implementation_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )

    @property
    def line_part(self):
        return " and ".join(
            [
                "{0} {1}".format(k, v)
                for k, v in attr.asdict(self, filter=filter_none).items()
            ]
        )

    @property
    def pipfile_part(self):
        return {"markers": self.as_line}

    @classmethod
    def make_marker(cls, marker_string):
        try:
            marker = Marker(marker_string)
        except InvalidMarker:
            raise RequirementError(
                "Invalid requirement: Invalid marker %r" % marker_string
            )
        return marker

    @classmethod
    def from_line(cls, line):
        if ";" in line:
            line = line.rsplit(";", 1)[1].strip()
        marker = cls.make_marker(line)
        return marker

    @classmethod
    def from_pipfile(cls, name, pipfile):
        attr_fields = [field.name for field in attr.fields(cls)]
        found_keys = [k for k in pipfile.keys() if k in attr_fields]
        marker_strings = ["{0} {1}".format(k, pipfile[k]) for k in found_keys]
        if pipfile.get("markers"):
            marker_strings.append(pipfile.get("markers"))
        markers = set()
        for marker in marker_strings:
            markers.add(marker)
        combined_marker = None
        try:
            combined_marker = cls.make_marker(" and ".join(sorted(markers)))
        except RequirementError:
            pass
        else:
            return combined_marker


@lru_cache(maxsize=1024)
def _tuplize_version(version):
    # type: (STRING_TYPE) -> Tuple[int, ...]
    return tuple(int(x) for x in filter(lambda i: i != "*", version.split(".")))


@lru_cache(maxsize=1024)
def _format_version(version):
    # type: (Tuple[int, ...]) -> STRING_TYPE
    if not isinstance(version, six.string_types):
        return ".".join(str(i) for i in version)
    return version


# Prefer [x,y) ranges.
REPLACE_RANGES = {">": ">=", "<=": "<"}


@lru_cache(maxsize=1024)
def _format_pyspec(specifier):
    # type: (Union[STRING_TYPE, Specifier]) -> Specifier
    if isinstance(specifier, str):
        if not any(op in specifier for op in Specifier._operators.keys()):
            specifier = "=={0}".format(specifier)
        specifier = Specifier(specifier)
    version = getattr(specifier, "version", specifier).rstrip()
    if version and version.endswith("*"):
        if version.endswith(".*"):
            version = version[:-2]
        version = version.rstrip("*")
        specifier = Specifier("{0}{1}".format(specifier.operator, version))
    try:
        op = REPLACE_RANGES[specifier.operator]
    except KeyError:
        return specifier
    curr_tuple = _tuplize_version(version)
    try:
        next_tuple = (curr_tuple[0], curr_tuple[1] + 1)
    except IndexError:
        next_tuple = (curr_tuple[0], 1)
    if not next_tuple[1] <= MAX_VERSIONS[next_tuple[0]]:
        if specifier.operator == "<" and curr_tuple[1] <= MAX_VERSIONS[next_tuple[0]]:
            op = "<="
            next_tuple = (next_tuple[0], curr_tuple[1])
        else:
            return specifier
    specifier = Specifier("{0}{1}".format(op, _format_version(next_tuple)))
    return specifier


@lru_cache(maxsize=1024)
def _get_specs(specset):
    if specset is None:
        return
    if is_instance(specset, Specifier):
        new_specset = SpecifierSet()
        specs = set()
        specs.add(specset)
        new_specset._specs = frozenset(specs)
        specset = new_specset
    if isinstance(specset, str):
        specset = SpecifierSet(specset)
    result = []
    for spec in set(specset):
        version = spec.version
        op = spec.operator
        if op in ("in", "not in"):
            versions = version.split(",")
            op = "==" if op == "in" else "!="
            for ver in versions:
                result.append((op, _tuplize_version(ver.strip())))
        else:
            result.append((spec.operator, _tuplize_version(spec.version)))
    return sorted(result, key=operator.itemgetter(1))


# TODO: Rename this to something meaningful
def _group_by_op(specs):
    # type: (Union[Set[Specifier], SpecifierSet]) -> Iterator
    specs = [_get_specs(x) for x in list(specs)]
    flattened = [
        ((op, len(version) > 2), version) for spec in specs for op, version in spec
    ]
    specs = sorted(flattened)
    grouping = itertools.groupby(specs, key=operator.itemgetter(0))
    return grouping


# TODO: rename this to something meaningful
def normalize_specifier_set(specs):
    # type: (Union[str, SpecifierSet]) -> Optional[Set[Specifier]]
    """Given a specifier set, a string, or an iterable, normalize the specifiers

    .. note:: This function exists largely to deal with ``pyzmq`` which handles
        the ``requires_python`` specifier incorrectly, using ``3.7*`` rather than
        the correct form of ``3.7.*``.  This workaround can likely go away if
        we ever introduce enforcement for metadata standards on PyPI.

    :param Union[str, SpecifierSet] specs: Supplied specifiers to normalize
    :return: A new set of specifiers or specifierset
    :rtype: Union[Set[Specifier], :class:`~packaging.specifiers.SpecifierSet`]
    """
    if not specs:
        return None
    if isinstance(specs, set):
        return specs
    # when we aren't dealing with a string at all, we can normalize this as usual
    elif not isinstance(specs, six.string_types):
        return {_format_pyspec(spec) for spec in specs}
    spec_list = []
    for spec in specs.split(","):
        spec = spec.strip()
        if spec.endswith(".*"):
            spec = spec[:-2]
        spec = spec.rstrip("*")
        spec_list.append(spec)
    return normalize_specifier_set(SpecifierSet(",".join(spec_list)))


# TODO: Check if this is used by anything public otherwise make it private
# And rename it to something meaningful
def get_sorted_version_string(version_set):
    # type: (Set[AnyStr]) -> AnyStr
    version_list = sorted(
        "{0}".format(_format_version(version)) for version in version_set
    )
    version = ", ".join(version_list)
    return version


# TODO: Rename this to something meaningful
# TODO: Add a deprecation decorator and deprecate this -- i'm sure it's used
# in other libraries
@lru_cache(maxsize=1024)
def cleanup_pyspecs(specs, joiner="or"):
    specs = normalize_specifier_set(specs)
    # for != operator we want to group by version
    # if all are consecutive, join as a list
    results = {}
    translation_map = {
        # if we are doing an or operation, we need to use the min for >=
        # this way OR(>=2.6, >=2.7, >=3.6) picks >=2.6
        # if we do an AND operation we need to use MAX to be more selective
        (">", ">="): {
            "or": lambda x: _format_version(min(x)),
            "and": lambda x: _format_version(max(x)),
        },
        # we use inverse logic here so we will take the max value if we are
        # using OR but the min value if we are using AND
        ("<", "<="): {
            "or": lambda x: _format_version(max(x)),
            "and": lambda x: _format_version(min(x)),
        },
        # leave these the same no matter what operator we use
        ("!=", "==", "~=", "==="): {
            "or": get_sorted_version_string,
            "and": get_sorted_version_string,
        },
    }
    op_translations = {
        "!=": lambda x: "not in" if len(x) > 1 else "!=",
        "==": lambda x: "in" if len(x) > 1 else "==",
    }
    translation_keys = list(translation_map.keys())
    for op_and_version_type, versions in _group_by_op(tuple(specs)):
        op = op_and_version_type[0]
        versions = [version[1] for version in versions]
        versions = sorted(dedup(versions))
        op_key = next(iter(k for k in translation_keys if op in k), None)
        version_value = versions
        if op_key is not None:
            version_value = translation_map[op_key][joiner](versions)
        if op in op_translations:
            op = op_translations[op](versions)
        results[(op, op_and_version_type[1])] = version_value
    return sorted([(k[0], v) for k, v in results.items()], key=operator.itemgetter(1))


# TODO: Rename this to something meaningful
@lru_cache(maxsize=1024)
def fix_version_tuple(version_tuple):
    # type: (Tuple[AnyStr, AnyStr]) -> Tuple[AnyStr, AnyStr]
    op, version = version_tuple
    max_major = max(MAX_VERSIONS.keys())
    if version[0] > max_major:
        return (op, (max_major, MAX_VERSIONS[max_major]))
    max_allowed = MAX_VERSIONS[version[0]]
    if op == "<" and version[1] > max_allowed and version[1] - 1 <= max_allowed:
        op = "<="
        version = (version[0], version[1] - 1)
    return (op, version)


# TODO: Rename this to something meaningful, deprecate it (See prior function)
@lru_cache(maxsize=128)
def get_versions(specset, group_by_operator=True):
    # type: (Union[Set[Specifier], SpecifierSet], bool) -> List[Tuple[STRING_TYPE, STRING_TYPE]]
    specs = [_get_specs(x) for x in list(tuple(specset))]
    initial_sort_key = lambda k: (k[0], k[1])
    initial_grouping_key = operator.itemgetter(0)
    if not group_by_operator:
        initial_grouping_key = operator.itemgetter(1)
        initial_sort_key = operator.itemgetter(1)
    version_tuples = sorted(
        set((op, version) for spec in specs for op, version in spec), key=initial_sort_key
    )
    version_tuples = [fix_version_tuple(t) for t in version_tuples]
    op_groups = [
        (grp, list(map(operator.itemgetter(1), keys)))
        for grp, keys in itertools.groupby(version_tuples, key=initial_grouping_key)
    ]
    versions = [
        (op, packaging.version.parse(".".join(str(v) for v in val)))
        for op, vals in op_groups
        for val in vals
    ]
    return sorted(versions, key=operator.itemgetter(1))


def _ensure_marker(marker):
    # type: (Union[STRING_TYPE, Marker]) -> Marker
    if not is_instance(marker, Marker):
        return Marker(str(marker))
    return marker


def gen_marker(mkr):
    # type: (List[STRING_TYPE]) -> Marker
    m = Marker("python_version == '1'")
    m._markers.pop()
    m._markers.append(mkr)
    return m


def _strip_extra(elements):
    """Remove the "extra == ..." operands from the list."""

    return _strip_marker_elem("extra", elements)


def _strip_pyversion(elements):
    return _strip_marker_elem("python_version", elements)


def _strip_marker_elem(elem_name, elements):
    """Remove the supplied element from the marker.

    This is not a comprehensive implementation, but relies on an important
    characteristic of metadata generation: The element's operand is always
    associated with an "and" operator. This means that we can simply remove the
    operand and the "and" operator associated with it.
    """

    extra_indexes = []
    preceding_operators = ["and"] if elem_name == "extra" else ["and", "or"]
    for i, element in enumerate(elements):
        if isinstance(element, list):
            cancelled = _strip_marker_elem(elem_name, element)
            if cancelled:
                extra_indexes.append(i)
        elif isinstance(element, tuple) and element[0].value == elem_name:
            extra_indexes.append(i)
    for i in reversed(extra_indexes):
        del elements[i]
        if i > 0 and elements[i - 1] in preceding_operators:
            # Remove the "and" before it.
            del elements[i - 1]
        elif elements:
            # This shouldn't ever happen, but is included for completeness.
            # If there is not an "and" before this element, try to remove the
            # operator after it.
            del elements[0]
    return not elements


def _get_stripped_marker(marker, strip_func):
    """Build a new marker which is cleaned according to `strip_func`"""

    if not marker:
        return None
    marker = _ensure_marker(marker)
    elements = marker._markers
    strip_func(elements)
    if elements:
        return marker
    return None


def get_without_extra(marker):
    """Build a new marker without the `extra == ...` part.

    The implementation relies very deep into packaging's internals, but I don't
    have a better way now (except implementing the whole thing myself).

    This could return `None` if the `extra == ...` part is the only one in the
    input marker.
    """

    return _get_stripped_marker(marker, _strip_extra)


def get_without_pyversion(marker):
    """Built a new marker without the `python_version` part.

    This could return `None` if the `python_version` section is the only section in the
    marker.
    """

    return _get_stripped_marker(marker, _strip_pyversion)


def _markers_collect_extras(markers, collection):
    # Optimization: the marker element is usually appended at the end.
    for el in reversed(markers):
        if isinstance(el, tuple) and el[0].value == "extra" and el[1].value == "==":
            collection.add(el[2].value)
        elif isinstance(el, list):
            _markers_collect_extras(el, collection)


def _markers_collect_pyversions(markers, collection):
    local_collection = []
    marker_format_str = "{0}"
    for i, el in enumerate(reversed(markers)):
        if isinstance(el, tuple) and el[0].value == "python_version":
            new_marker = str(gen_marker(el))
            local_collection.append(marker_format_str.format(new_marker))
        elif isinstance(el, list):
            _markers_collect_pyversions(el, local_collection)
    if local_collection:
        # local_collection = "{0}".format(" ".join(local_collection))
        collection.extend(local_collection)


def _markers_contains_extra(markers):
    # Optimization: the marker element is usually appended at the end.
    return _markers_contains_key(markers, "extra")


def _markers_contains_pyversion(markers):
    return _markers_contains_key(markers, "python_version")


def _markers_contains_key(markers, key):
    for element in reversed(markers):
        if isinstance(element, tuple) and element[0].value == key:
            return True
        elif isinstance(element, list):
            if _markers_contains_key(element, key):
                return True
    return False


@lru_cache(maxsize=128)
def get_contained_extras(marker):
    """Collect "extra == ..." operands from a marker.

    Returns a list of str. Each str is a speficied extra in this marker.
    """
    if not marker:
        return set()
    extras = set()
    marker = _ensure_marker(marker)
    _markers_collect_extras(marker._markers, extras)
    return extras


@lru_cache(maxsize=1024)
def get_contained_pyversions(marker):
    """Collect all `python_version` operands from a marker.
    """

    collection = []
    if not marker:
        return set()
    marker = _ensure_marker(marker)
    # Collect the (Variable, Op, Value) tuples and string joiners from the marker
    _markers_collect_pyversions(marker._markers, collection)
    marker_str = " and ".join(sorted(collection))
    if not marker_str:
        return set()
    # Use the distlib dictionary parser to create a dictionary 'trie' which is a bit
    # easier to reason about
    marker_dict = distlib.markers.parse_marker(marker_str)[0]
    version_set = set()
    pyversions, _ = parse_marker_dict(marker_dict)
    if isinstance(pyversions, set):
        version_set.update(pyversions)
    elif pyversions is not None:
        version_set.add(pyversions)
    # Each distinct element in the set was separated by an "and" operator in the marker
    # So we will need to reduce them with an intersection here rather than a union
    # in order to find the boundaries
    versions = set()
    if version_set:
        versions = reduce(lambda x, y: x & y, version_set)
    return versions


@lru_cache(maxsize=128)
def contains_extra(marker):
    """Check whehter a marker contains an "extra == ..." operand.
    """
    if not marker:
        return False
    marker = _ensure_marker(marker)
    return _markers_contains_extra(marker._markers)


@lru_cache(maxsize=128)
def contains_pyversion(marker):
    """Check whether a marker contains a python_version operand.
    """

    if not marker:
        return False
    marker = _ensure_marker(marker)
    return _markers_contains_pyversion(marker._markers)


def _split_specifierset_str(specset_str, prefix="=="):
    # type: (str, str) -> Set[Specifier]
    """
    Take a specifierset string and split it into a list to join for specifier sets

    :param str specset_str: A string containing python versions, often comma separated
    :param str prefix: A prefix to use when generating the specifier set
    :return: A list of :class:`Specifier` instances generated with the provided prefix
    :rtype: Set[Specifier]
    """
    specifiers = set()
    if "," not in specset_str and " " in specset_str:
        values = [v.strip() for v in specset_str.split()]
    else:
        values = [v.strip() for v in specset_str.split(",")]
    if prefix == "!=" and any(v in values for v in DEPRECATED_VERSIONS):
        values += DEPRECATED_VERSIONS[:]
    for value in sorted(values):
        specifiers.add(Specifier("{0}{1}".format(prefix, value)))
    return specifiers


def _get_specifiers_from_markers(marker_item):
    """
    Given a marker item, get specifiers from the version marker

    :param :class:`~packaging.markers.Marker` marker_sequence: A marker describing a version constraint
    :return: A set of specifiers corresponding to the marker constraint
    :rtype: Set[Specifier]
    """
    specifiers = set()
    if isinstance(marker_item, tuple):
        variable, op, value = marker_item
        if variable.value != "python_version":
            return specifiers
        if op.value == "in":
            specifiers.update(_split_specifierset_str(value.value, prefix="=="))
        elif op.value == "not in":
            specifiers.update(_split_specifierset_str(value.value, prefix="!="))
        else:
            specifiers.add(Specifier("{0}{1}".format(op.value, value.value)))
    elif isinstance(marker_item, list):
        parts = get_specset(marker_item)
        if parts:
            specifiers.update(parts)
    return specifiers


def get_specset(marker_list):
    # type: (List) -> Optional[SpecifierSet]
    specset = set()
    _last_str = "and"
    for marker_parts in marker_list:
        if isinstance(marker_parts, str):
            _last_str = marker_parts  # noqa
        else:
            specset.update(_get_specifiers_from_markers(marker_parts))
    specifiers = SpecifierSet()
    specifiers._specs = frozenset(specset)
    return specifiers


# TODO: Refactor this (reduce complexity)
def parse_marker_dict(marker_dict):
    op = marker_dict["op"]
    lhs = marker_dict["lhs"]
    rhs = marker_dict["rhs"]
    # This is where the spec sets for each side land if we have an "or" operator
    side_spec_list = []
    side_markers_list = []
    finalized_marker = ""
    # And if we hit the end of the parse tree we use this format string to make a marker
    format_string = "{lhs} {op} {rhs}"
    specset = SpecifierSet()
    specs = set()
    # Essentially we will iterate over each side of the parsed marker if either one is
    # A mapping instance (i.e. a dictionary) and recursively parse and reduce the specset
    # Union the "and" specs, intersect the "or"s to find the most appropriate range
    if any(issubclass(type(side), Mapping) for side in (lhs, rhs)):
        for side in (lhs, rhs):
            side_specs = set()
            side_markers = set()
            if issubclass(type(side), Mapping):
                merged_side_specs, merged_side_markers = parse_marker_dict(side)
                side_specs.update(merged_side_specs)
                side_markers.update(merged_side_markers)
            else:
                marker = _ensure_marker(side)
                marker_parts = getattr(marker, "_markers", [])
                if marker_parts[0][0].value == "python_version":
                    side_specs |= set(get_specset(marker_parts))
                else:
                    side_markers.add(str(marker))
            side_spec_list.append(side_specs)
            side_markers_list.append(side_markers)
        if op == "and":
            # When we are "and"-ing things together, it probably makes the most sense
            # to reduce them here into a single PySpec instance
            specs = reduce(lambda x, y: set(x) | set(y), side_spec_list)
            markers = reduce(lambda x, y: set(x) | set(y), side_markers_list)
            if not specs and not markers:
                return specset, finalized_marker
            if markers and isinstance(markers, (tuple, list, Set)):
                finalized_marker = Marker(" and ".join([m for m in markers if m]))
            elif markers:
                finalized_marker = str(markers)
            specset._specs = frozenset(specs)
            return specset, finalized_marker
        # Actually when we "or" things as well we can also just turn them into a reduced
        # set using this logic now
        sides = reduce(lambda x, y: set(x) & set(y), side_spec_list)
        finalized_marker = " or ".join(
            [normalize_marker_str(m) for m in side_markers_list]
        )
        specset._specs = frozenset(sorted(sides))
        return specset, finalized_marker
    else:
        # At the tip of the tree we are dealing with strings all around and they just need
        # to be smashed together
        specs = set()
        if lhs == "python_version":
            format_string = "{lhs}{op}{rhs}"
            marker = Marker(format_string.format(**marker_dict))
            marker_parts = getattr(marker, "_markers", [])
            _set = get_specset(marker_parts)
            if _set:
                specs |= set(_set)
                specset._specs = frozenset(specs)
        return specset, finalized_marker


def _contains_micro_version(version_string):
    return re.search(r"\d+\.\d+\.\d+", version_string) is not None


def format_pyversion(parts):
    op, val = parts
    version_marker = (
        "python_full_version" if _contains_micro_version(val) else "python_version"
    )
    return "{0} {1} '{2}'".format(version_marker, op, val)


def normalize_marker_str(marker):
    # type: (Union[Marker, STRING_TYPE]) -> str
    marker_str = ""
    if not marker:
        return None
    if not is_instance(marker, Marker):
        marker = _ensure_marker(marker)
    pyversion = get_contained_pyversions(marker)
    marker = get_without_pyversion(marker)
    if pyversion:
        parts = cleanup_pyspecs(pyversion)
        marker_str = " and ".join([format_pyversion(pv) for pv in parts])
    if marker:
        if marker_str:
            marker_str = "{0!s} and {1!s}".format(marker_str, marker)
        else:
            marker_str = "{0!s}".format(marker)
    return marker_str.replace('"', "'")


@lru_cache(maxsize=1024)
def marker_from_specifier(spec):
    # type: (STRING_TYPE) -> Marker
    if not any(spec.startswith(k) for k in Specifier._operators.keys()):
        if spec.strip().lower() in ["any", "<any>", "*"]:
            return None
        spec = "=={0}".format(spec)
    elif spec.startswith("==") and spec.count("=") > 3:
        spec = "=={0}".format(spec.lstrip("="))
    if not spec:
        return None
    marker_segments = []
    for marker_segment in cleanup_pyspecs(spec):
        marker_segments.append(format_pyversion(marker_segment))
    marker_str = " and ".join(marker_segments).replace('"', "'")
    return Marker(marker_str)


def merge_markers(m1, m2):
    # type: (Marker, Marker) -> Optional[Marker]
    if not all((m1, m2)):
        return next(iter(v for v in (m1, m2) if v), None)
    m1 = _ensure_marker(m1)
    m2 = _ensure_marker(m2)
    _markers = []  # type: List[Marker]
    for marker in (m1, m2):
        _markers.append(str(marker))
    marker_str = " and ".join([normalize_marker_str(m) for m in _markers if m])
    return _ensure_marker(normalize_marker_str(marker_str))
