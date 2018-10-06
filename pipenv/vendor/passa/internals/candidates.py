# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import packaging.specifiers
import packaging.version
import requirementslib

from ._pip import find_installation_candidates, get_vcs_ref


def _filter_matching_python_requirement(candidates, required_python):
    # TODO: This should also takes the parent's python_version and
    # python_full_version markers, and only return matches with valid
    # intersections. For example, if parent requires `python_version >= '3.0'`,
    # this should not return entries with "Requires-Python: <3".
    for c in candidates:
        try:
            requires_python = c.requires_python
        except AttributeError:
            requires_python = c.location.requires_python
        if required_python and requires_python:
            # Old specifications had people setting this to single digits
            # which is effectively the same as '>=digit,<digit+1'
            if requires_python.isdigit():
                requires_python = '>={0},<{1}'.format(
                    requires_python, int(requires_python) + 1,
                )
            try:
                specset = packaging.specifiers.SpecifierSet(requires_python)
            except packaging.specifiers.InvalidSpecifier:
                continue
            if not specset.contains(required_python):
                continue
        yield c


def _copy_requirement(requirement):
    # Markers are intentionally dropped here. They will be added to candidates
    # after resolution, so we can perform marker aggregation.
    new = requirement.copy()
    new.markers = None
    return new


def _requirement_from_metadata(name, version, extras, index):
    # Markers are intentionally dropped here. They will be added to candidates
    # after resolution, so we can perform marker aggregation.
    r = requirementslib.Requirement.from_metadata(name, version, extras, None)
    r.index = index
    return r


def find_candidates(requirement, sources, requires_python, allow_prereleases):
    # A non-named requirement has exactly one candidate that is itself. For
    # VCS, we also lock the requirement to an exact ref.
    if not requirement.is_named:
        candidate = _copy_requirement(requirement)
        if candidate.is_vcs:
            candidate.req.ref = get_vcs_ref(candidate)
        return [candidate]

    ireq = requirement.as_ireq()
    icans = find_installation_candidates(ireq, sources)

    if requires_python:
        matching_icans = list(_filter_matching_python_requirement(
            icans, packaging.version.parse(requires_python),
        ))
        icans = matching_icans or icans

    versions = sorted(ireq.specifier.filter(
        (c.version for c in icans), allow_prereleases,
    ))
    if not allow_prereleases and not versions:
        versions = sorted(ireq.specifier.filter(
            (c.version for c in icans), True,
        ))

    name = requirement.normalized_name
    extras = requirement.extras
    index = requirement.index
    return [
        _requirement_from_metadata(name, version, extras, index)
        for version in versions
    ]
