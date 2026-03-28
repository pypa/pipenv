from __future__ import annotations

from typing import TYPE_CHECKING

from pipenv.vendor.packaging.version import InvalidVersion, Version

from .direct_url import ArchiveInfo, VcsInfo, get_direct_url
from .editable import find_egg_link, read_egg_link_location, url_to_path
from .vcs import VcsError, VcsResult, get_vcs_requirement

if TYPE_CHECKING:
    from importlib.metadata import Distribution

    from .direct_url import DirectUrl


def distribution_to_specifier(distribution: Distribution) -> str:
    """
    Convert distribution to requirement specifier string.

    Handles regular packages (PEP 440 version specifiers), editable installs (PEP 610 direct_url.json and legacy
    .egg-link), and direct URL installs (PEP 440 direct references for VCS, archive, directory).

    For editable installs, probes filesystem for VCS information (git/hg/svn/bzr) to generate full VCS URL with commit
    hash, falling back to local path with diagnostic comment if VCS not detected or extraction fails.

    See:
    - PEP 440: https://peps.python.org/pep-0440/
    - PEP 610: https://peps.python.org/pep-0610/

    :param distribution: Distribution to convert
    :returns: Requirement specifier string
    """
    direct_url = get_direct_url(distribution)
    if direct_url:
        if direct_url.is_editable():
            location = url_to_path(direct_url.url)
            return _format_editable(location, distribution.metadata["Name"], distribution.version)
        return format_requirement(direct_url, distribution.metadata["Name"])
    if egg_link := find_egg_link(distribution.metadata["Name"]):
        location = read_egg_link_location(egg_link)
        return _format_editable(location, distribution.metadata["Name"], distribution.version)
    name = distribution.metadata["Name"]
    try:
        Version(distribution.version)
    except InvalidVersion:
        return f"{name}==={distribution.version}"
    else:
        return f"{name}=={distribution.version}"


def _format_editable(location: str, package_name: str, version: str) -> str:
    """
    Format editable install requirement with VCS detection and diagnostic comments.

    Probes location for VCS (git/hg/svn/bzr) and generates VCS URL if detected,
    otherwise uses local path with pip-compatible diagnostic comment.
    """
    vcs_result = get_vcs_requirement(location, package_name)
    if vcs_result.requirement:
        return f"-e {vcs_result.requirement}"
    comment = _diagnostic_comment(vcs_result, package_name, version)
    if comment:
        return f"{comment}\n-e {location}"
    return f"-e {location}"


_DIAGNOSTIC_TEMPLATES: dict[VcsError, str] = {
    VcsError.NO_VCS: "# Editable install with no version control ({package_name}=={version})",
    VcsError.NO_REMOTE: "# Editable {vcs_name} install with no remote ({package_name}=={version})",
    VcsError.INVALID_REMOTE: (
        "# Editable {vcs_name} install ({package_name}=={version}) with either a deleted local remote or invalid URI:"
    ),
}


def _diagnostic_comment(vcs_result: VcsResult, package_name: str, version: str) -> str | None:
    """Generate pip-compatible diagnostic comment based on VcsResult error."""
    if template := _DIAGNOSTIC_TEMPLATES.get(vcs_result.error):
        return template.format(package_name=package_name, version=version, vcs_name=vcs_result.vcs_name)
    return None


def format_requirement(direct_url: DirectUrl, package_name: str) -> str:
    """
    Format DirectUrl as PEP 440 direct reference requirement.

    Uses redacted_url to strip credentials from URLs.

    :param direct_url: DirectUrl object to format (from PEP 610 direct_url.json)
    :param package_name: Package name to include in requirement string
    :returns: Formatted requirement string
    """
    url = direct_url.redacted_url
    requirement = f"{package_name} @ "
    if isinstance(direct_url.info, VcsInfo):
        requirement += f"{direct_url.info.vcs}+{url}"
        if direct_url.info.commit_id:
            requirement += f"@{direct_url.info.commit_id}"
    elif isinstance(direct_url.info, ArchiveInfo):
        requirement += url
        if direct_url.info.hash:
            requirement += f"#{direct_url.info.hash}"
    else:
        requirement += url
    if direct_url.subdirectory:
        requirement += f"{'&' if '#' in requirement else '#'}subdirectory={direct_url.subdirectory}"
    return requirement


__all__ = [
    "distribution_to_specifier",
    "format_requirement",
]
