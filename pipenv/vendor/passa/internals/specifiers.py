# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import itertools
import operator

from packaging.specifiers import SpecifierSet, Specifier
from vistir.misc import dedup


def _tuplize_version(version):
    return tuple(int(x) for x in version.split("."))


def _format_version(version):
    return ".".join(str(i) for i in version)


# Prefer [x,y) ranges.
REPLACE_RANGES = {">": ">=", "<=": "<"}


def _format_pyspec(specifier):
    if isinstance(specifier, str):
        if not any(op in specifier for op in Specifier._operators.keys()):
            specifier = "=={0}".format(specifier)
        specifier = Specifier(specifier)
    if specifier.operator == "==" and specifier.version.endswith(".*"):
        specifier = Specifier("=={0}".format(specifier.version[:-2]))
    try:
        op = REPLACE_RANGES[specifier.operator]
    except KeyError:
        return specifier
    version = specifier.version.replace(".*", "")
    curr_tuple = _tuplize_version(version)
    try:
        next_tuple = (curr_tuple[0], curr_tuple[1] + 1)
    except IndexError:
        next_tuple = (curr_tuple[0], 1)
    specifier = Specifier("{0}{1}".format(op, _format_version(next_tuple)))
    return specifier


def _get_specs(specset):
    if isinstance(specset, Specifier):
        specset = str(specset)
    if isinstance(specset, str):
        specset = SpecifierSet(specset.replace(".*", ""))
    return [
        (spec._spec[0], _tuplize_version(spec._spec[1]))
        for spec in getattr(specset, "_specs", [])
    ]


def _group_by_op(specs):
    specs = [_get_specs(x) for x in list(specs)]
    flattened = [(op, version) for spec in specs for op, version in spec]
    specs = sorted(flattened, key=operator.itemgetter(1))
    grouping = itertools.groupby(specs, key=operator.itemgetter(0))
    return grouping


def cleanup_pyspecs(specs, joiner="or"):
    specs = {_format_pyspec(spec) for spec in specs}
    # for != operator we want to group by version
    # if all are consecutive, join as a list
    results = set()
    for op, versions in _group_by_op(specs):
        versions = [version[1] for version in versions]
        versions = sorted(dedup(versions))
        # if we are doing an or operation, we need to use the min for >=
        # this way OR(>=2.6, >=2.7, >=3.6) picks >=2.6
        # if we do an AND operation we need to use MAX to be more selective
        if op in (">", ">="):
            if joiner == "or":
                results.add((op, _format_version(min(versions))))
            else:
                results.add((op, _format_version(max(versions))))
        # we use inverse logic here so we will take the max value if we are
        # using OR but the min value if we are using AND
        elif op in ("<=", "<"):
            if joiner == "or":
                results.add((op, _format_version(max(versions))))
            else:
                results.add((op, _format_version(min(versions))))
        # leave these the same no matter what operator we use
        elif op in ("!=", "==", "~="):
            version_list = sorted(
                "{0}".format(_format_version(version))
                for version in versions
            )
            version = ", ".join(version_list)
            if len(version_list) == 1:
                results.add((op, version))
            elif op == "!=":
                results.add(("not in", version))
            elif op == "==":
                results.add(("in", version))
            else:
                specifier = SpecifierSet(",".join(sorted(
                    "{0}".format(op, v) for v in version_list
                )))._specs
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


def pyspec_from_markers(marker):
    if marker._markers[0][0] != 'python_version':
        return
    op = marker._markers[0][1].value
    version = marker._markers[0][2].value
    specset = set()
    if op == "in":
        specset.update(
            Specifier("=={0}".format(v.strip()))
            for v in version.split(",")
        )
    elif op == "not in":
        specset.update(
            Specifier("!={0}".format(v.strip()))
            for v in version.split(",")
        )
    else:
        specset.add(Specifier("".join([op, version])))
    if specset:
        return specset
    return None
