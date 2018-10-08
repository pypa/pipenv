# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals


def identify_requirment(r):
    """Produce an identifier for a requirement to use in the resolver.

    Note that we are treating the same package with different extras as
    distinct. This allows semantics like "I only want this extra in
    development, not production".

    This also makes the resolver's implementation much simpler, with the minor
    costs of possibly needing a few extra resolution steps if we happen to have
    the same package apprearing multiple times.
    """
    return "{0}{1}".format(r.normalized_name, r.extras_as_pip)


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


def is_pinned(ireq):
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


def filter_sources(requirement, sources):
    """Returns a filtered list of sources for this requirement.

    This considers the index specified by the requirement, and returns only
    matching source entries if there is at least one.
    """
    if not sources or not requirement.index:
        return sources
    filtered_sources = [
        source for source in sources
        if source.get("name") == requirement.index
    ]
    return filtered_sources or sources


def get_allow_prereleases(requirement, global_setting):
    # TODO: Implement per-package prereleases flag. (pypa/pipenv#1696)
    return global_setting


def are_requirements_equal(this, that):
    return (
        this.as_line(include_hashes=False) ==
        that.as_line(include_hashes=False)
    )


def strip_extras(requirement):
    """Returns a new requirement object with extras removed.
    """
    line = requirement.as_line()
    new = type(requirement).from_line(line)
    new.extras = None
    return new
