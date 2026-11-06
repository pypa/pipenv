"""Check direct URL dependencies declared by PyPI distributions."""

from __future__ import annotations

import urllib.parse

from pipenv.patched.pip._vendor.packaging.requirements import InvalidRequirement, Requirement

from pipenv.patched.pip._internal.exceptions import InstallationError
from pipenv.patched.pip._internal.metadata.base import BaseDistribution
from pipenv.patched.pip._internal.models.index import PyPI, TestPyPI
from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.utils.packaging import get_requirement


def check_pypi_direct_references(
    distribution: BaseDistribution,
    source_link: Link,
) -> None:
    """Reject direct URL dependencies declared by a PyPI distribution."""
    # ``hostname`` removes credentials and ports and normalizes case.
    hostname = urllib.parse.urlsplit(source_link.url).hostname
    if hostname not in {
        PyPI.file_storage_domain,
        TestPyPI.file_storage_domain,
    }:
        return

    dependency = _first_direct_reference(distribution)
    if dependency is None:
        return

    raise InstallationError(
        "Distributions from PyPI cannot declare direct URL dependencies.\n"
        f"{distribution.raw_name} depends on {dependency} "
    )


def _first_direct_reference(
    distribution: BaseDistribution,
) -> Requirement | None:
    """Return the first direct URL dependency declared in raw metadata."""
    for raw_dependency in distribution.iter_raw_dependencies():
        try:
            # A folded metadata header may retain a leading newline.
            dependency = get_requirement(raw_dependency.strip())
        except InvalidRequirement:
            continue
        if dependency.url is not None:
            return dependency
    return None
