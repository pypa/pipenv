# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import itertools
import operator

import vistir

from packaging.specifiers import SpecifierSet, Specifier
from packaging.markers import Marker


PYTHON_BOUNDARIES = {2: 7, 3: 9}


def _strip_extra(elements):
    """Remove the "extra == ..." operands from the list.

    This is not a comprehensive implementation, but relies on an important
    characteristic of metadata generation: The "extra == ..." operand is always
    associated with an "and" operator. This means that we can simply remove the
    operand and the "and" operator associated with it.
    """
    extra_indexes = []
    for i, element in enumerate(elements):
        if isinstance(element, list):
            cancelled = _strip_extra(element)
            if cancelled:
                extra_indexes.append(i)
        elif isinstance(element, tuple) and element[0].value == "extra":
            extra_indexes.append(i)
    for i in reversed(extra_indexes):
        del elements[i]
        if i > 0 and elements[i - 1] == "and":
            # Remove the "and" before it.
            del elements[i - 1]
        elif elements:
            # This shouldn't ever happen, but is included for completeness.
            # If there is not an "and" before this element, try to remove the
            # operator after it.
            del elements[0]
    return (not elements)


def get_without_extra(marker):
    """Build a new marker without the `extra == ...` part.

    The implementation relies very deep into packaging's internals, but I don't
    have a better way now (except implementing the whole thing myself).

    This could return `None` if the `extra == ...` part is the only one in the
    input marker.
    """
    # TODO: Why is this very deep in the internals? Why is a better solution
    # implementing it yourself when someone is already maintaining a codebase
    # for this? It's literally a grammar implementation that is required to
    # meet the demands of a pep... -d
    if not marker:
        return None
    marker = Marker(str(marker))
    elements = marker._markers
    _strip_extra(elements)
    if elements:
        return marker
    return None


def _markers_collect_extras(markers, collection):
    # Optimization: the marker element is usually appended at the end.
    for el in reversed(markers):
        if (isinstance(el, tuple) and
                el[0].value == "extra" and
                el[1].value == "=="):
            collection.add(el[2].value)
        elif isinstance(el, list):
            _markers_collect_extras(el, collection)


def get_contained_extras(marker):
    """Collect "extra == ..." operands from a marker.

    Returns a list of str. Each str is a speficied extra in this marker.
    """
    if not marker:
        return set()
    marker = Marker(str(marker))
    extras = set()
    _markers_collect_extras(marker._markers, extras)
    return extras


def _markers_contains_extra(markers):
    # Optimization: the marker element is usually appended at the end.
    for element in reversed(markers):
        if isinstance(element, tuple) and element[0].value == "extra":
            return True
        elif isinstance(element, list):
            if _markers_contains_extra(element):
                return True
    return False


def contains_extra(marker):
    """Check whehter a marker contains an "extra == ..." operand.
    """
    if not marker:
        return False
    marker = Marker(str(marker))
    return _markers_contains_extra(marker._markers)


def format_pyspec(specifier):
    if isinstance(specifier, str):
        if not any(operator in specifier for operator in Specifier._operators.keys()):
            new_op = "=="
            new_version = specifier
            return Specifier("{0}{1}".format(new_op, new_version))
    version = specifier._coerce_version(specifier.version.replace(".*", ""))
    version_tuple = version._version.release
    if specifier.operator in (">", "<="):
        # Prefer to always pick the operator for version n+1
        if version_tuple[1] < PYTHON_BOUNDARIES.get(version_tuple[0], 0):
            if specifier.operator == ">":
                new_op = ">="
            else:
                new_op = "<"
            new_version = (version_tuple[0], version_tuple[1] + 1)
            specifier = Specifier("{0}{1}".format(new_op, version_to_str(new_version)))
    return specifier


def make_version_tuple(version):
    return tuple([int(x) for x in version.split(".")])


def version_to_str(version):
    return ".".join([str(i) for i in version])


def get_specs(specset):
    if isinstance(specset, Specifier):
        specset = str(specset)
    if isinstance(specset, str):
        specset = SpecifierSet(specset.replace(".*", ""))

    specs = getattr(specset, "_specs", None)
    return [(spec._spec[0], make_version_tuple(spec._spec[1])) for spec in list(specs)]


def group_by_version(versions):
    versions = sorted(map(lambda x: make_version_tuple(x)))
    grouping = itertools.groupby(versions, key=operator.itemgetter(0))
    return grouping


def group_by_op(specs):
    specs = [get_specs(x) for x in list(specs)]
    flattened = [(op, version) for spec in specs for op, version in spec]
    specs = sorted(flattened, key=operator.itemgetter(1))
    grouping = itertools.groupby(specs, key=operator.itemgetter(0))
    return grouping


def marker_to_spec(marker):
    if marker._markers[0][0] != 'python_version':
        return
    operator = marker._markers[0][1].value
    version = marker._markers[0][2].value
    specset = set()
    if operator in ("in", "not in"):
        op = "==" if operator == "in" else "!="
        specset |= set([Specifier("{0}{1}".format(op, v.strip())) for v in version.split(",")])
    else:
        spec = Specifier("".join([operator, version]))
        specset.add(spec)
    if specset:
        return specset
    return None


def cleanup_specs(specs, operator="or"):
    specs = {format_pyspec(spec) for spec in specs}
    # for != operator we want to group by version
    # if all are consecutive, join as a list
    results = set()
    for op, versions in group_by_op(specs):
        versions = [version[1] for version in versions]
        versions = sorted(vistir.misc.dedup(versions))
        # if we are doing an or operation, we need to use the min for >=
        # this way OR(>=2.6, >=2.7, >=3.6) picks >=2.6
        # if we do an AND operation we need to use MAX to be more selective
        if op in (">", ">="):
            if operator == "or":
                results.add((op, version_to_str(min(versions))))
            else:
                results.add((op, version_to_str(max(versions))))
        # we use inverse logic here so we will take the max value if we are using OR
        # but the min value if we are using AND
        elif op in ("<=", "<"):
            if operator == "or":
                results.add((op, version_to_str(max(versions))))
            else:
                results.add((op, version_to_str(min(versions))))
        # leave these the same no matter what operator we use
        elif op in ("!=", "==", "~="):
            version_list = sorted(["{0}".format(version_to_str(version)) for version in versions])
            version = ", ".join(version_list)
            if len(version_list) == 1:
                results.add((op, version))
            else:
                if op == "!=":
                    results.add(("not in", version))
                elif op == "==":
                    results.add(("in", version))
                else:
                    version = ", ".join(sorted(["{0}".format(op, v) for v in version_list]))
                    specifier = SpecifierSet(version)._specs
                    for s in specifier:
                        results &= (specifier._spec[0], specifier._spec[1])
        else:
            if len(version) == 1:
                results.add((op, version))
            else:
                specifier = SpecifierSet("{0}".format(version))._specs
                for s in specifier:
                    results |= (specifier._spec[0], specifier._spec[1])
    return results
