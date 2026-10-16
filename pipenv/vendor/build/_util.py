from __future__ import annotations


__lazy_modules__ = {'packaging', 'packaging.requirements', f'{__spec__.parent}._compat'}

import sys

import packaging.requirements

from ._compat import importlib


TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Set as AbstractSet


def check_dependency(
    req_string: str, ancestral_req_strings: tuple[str, ...] = (), parent_extras: AbstractSet[str] = frozenset()
) -> Iterator[tuple[str, ...]]:
    """
    Verify that a dependency and all of its dependencies are met.

    :param req_string: Requirement string
    :param parent_extras: Extras (eg. "test" in myproject[test])
    :yields: Unmet dependencies
    """
    yield from _check_dependency(req_string, ancestral_req_strings, parent_extras, set())


def _check_dependency(
    req_string: str, ancestral_req_strings: tuple[str, ...], parent_extras: AbstractSet[str], seen: set[str]
) -> Iterator[tuple[str, ...]]:
    req = packaging.requirements.Requirement(req_string)
    normalised_req_string = str(req)

    # ``seen`` holds requirements already verified as fully satisfied (nothing
    # yielded), so shared subtrees of a diamond dependency graph are walked once.
    if normalised_req_string in seen:
        return

    # ``Requirement`` doesn't implement ``__eq__`` so we cannot compare reqs for
    # equality directly but the string representation is stable.
    if normalised_req_string in ancestral_req_strings:
        # cyclical dependency, already checked.
        return

    if req.marker:
        extras = frozenset(('',)).union(parent_extras)
        # a requirement can have multiple extras but ``evaluate`` can
        # only check one at a time.
        if all(not req.marker.evaluate(environment={'extra': e}) for e in extras):
            # if the marker conditions are not met, we pretend that the
            # dependency is satisfied.
            return

    try:
        dist = importlib.metadata.distribution(req.name)
    except importlib.metadata.PackageNotFoundError:
        # dependency is not installed in the environment.
        yield (*ancestral_req_strings, normalised_req_string)
        return

    if req.specifier and not req.specifier.contains(dist.version, prereleases=True):
        # the installed version is incompatible.
        yield (*ancestral_req_strings, normalised_req_string)
        return

    satisfied = True
    for other_req_string in dist.requires or ():
        # yields transitive dependencies that are not satisfied.
        for unmet in _check_dependency(other_req_string, (*ancestral_req_strings, normalised_req_string), req.extras, seen):
            satisfied = False
            yield unmet

    # unmet requirements are not memoised: they must be reported once per
    # dependency chain that reaches them.
    if satisfied:
        seen.add(normalised_req_string)


def format_unmet_dependencies(unmet: AbstractSet[tuple[str, ...]]) -> str:
    body = ''.join(_format_missing_dependency(chain) for chain in sorted(unmet))
    return f'Unmet dependencies (checked against {sys.executable}):{body}'


def _format_missing_dependency(dep_chain: tuple[str, ...]) -> str:
    requirement = packaging.requirements.Requirement(dep_chain[-1])
    try:
        found = importlib.metadata.distribution(requirement.name).version
    except importlib.metadata.PackageNotFoundError:
        found = 'not installed'
    wanted = str(requirement.specifier) if requirement.specifier else 'any'
    return f'\n\t{_format_dep_chain(dep_chain)}\n\t\twanted: {wanted}\n\t\tfound: {found}'


def _format_dep_chain(dep_chain: tuple[str, ...]) -> str:
    return ' -> '.join(dep.partition(';')[0].strip() for dep in dep_chain)
