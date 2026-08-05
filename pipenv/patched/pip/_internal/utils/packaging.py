from __future__ import annotations

import functools
import logging

from pipenv.patched.pip._vendor.packaging import specifiers, version
from pipenv.patched.pip._vendor.packaging.requirements import Requirement

logger = logging.getLogger(__name__)


def is_prerelease_of_satisfying_lower_bound(
    specifier: specifiers.BaseSpecifier,
    candidate_version: str | version.Version,
) -> bool:
    """Return whether a prerelease can stand in for its final lower bound.

    A prerelease such as ``2.11rc3`` sorts before the ``2.11`` lower bound in
    ``~=2.11``. During prerelease fallback, treat it as matching when its
    corresponding final version satisfies the complete specifier and the only
    clauses it misses are inclusive lower bounds. Exact pins and exclusions
    continue to apply to the prerelease itself.
    """
    if not isinstance(candidate_version, version.Version):
        try:
            candidate_version = version.Version(candidate_version)
        except version.InvalidVersion:
            return False
    if not candidate_version.is_prerelease:
        return False

    final_version = version.Version(candidate_version.base_version)
    if not specifier.contains(final_version, prereleases=True):
        return False

    if isinstance(specifier, specifiers.SpecifierSet):
        clauses = tuple(specifier)
    elif isinstance(specifier, specifiers.Specifier):
        clauses = (specifier,)
    else:
        return False

    return bool(clauses) and all(
        clause.contains(candidate_version, prereleases=True)
        or (
            clause.operator in {">=", "~="}
            and clause.contains(final_version, prereleases=True)
        )
        for clause in clauses
    )


@functools.lru_cache(maxsize=32)
def check_requires_python(
    requires_python: str | None, version_info: tuple[int, ...]
) -> bool:
    """
    Check if the given Python version matches a "Requires-Python" specifier.

    :param version_info: A 3-tuple of ints representing a Python
        major-minor-micro version to check (e.g. `sys.version_info[:3]`).

    :return: `True` if the given Python version satisfies the requirement.
        Otherwise, return `False`.

    :raises InvalidSpecifier: If `requires_python` has an invalid format.
    """
    if requires_python is None:
        # The package provides no information
        return True
    requires_python_specifier = specifiers.SpecifierSet(requires_python)

    python_version = version.parse(".".join(map(str, version_info)))
    return python_version in requires_python_specifier


@functools.lru_cache(maxsize=10000)
def get_requirement(req_string: str) -> Requirement:
    """Construct a packaging.Requirement object with caching"""
    # Parsing requirement strings is expensive, and is also expected to happen
    # with a low diversity of different arguments (at least relative the number
    # constructed). This method adds a cache to requirement object creation to
    # minimize repeated parsing of the same string to construct equivalent
    # Requirement objects.
    return Requirement(req_string)
