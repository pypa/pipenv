from __future__ import annotations

import subprocess  # noqa: S404
import xml.etree.ElementTree as ET  # noqa: S405
from pathlib import Path

from .shared import VcsError, VcsResult, build_vcs_result


def get_svn_requirement(location: str, package_name: str, repo_root: str) -> VcsResult:
    try:
        svn_info = _get_svn_info(location)
    except FileNotFoundError:
        return VcsResult(None, vcs_name="svn", error=VcsError.COMMAND_NOT_FOUND)
    if svn_info is None:
        entries = _get_svn_entries_fallback(location)
        if entries is None:
            return VcsResult(None, vcs_name="svn", error=VcsError.NO_REMOTE)
        remote_url, revision = entries
    else:
        remote_url, revision = svn_info
    return build_vcs_result(
        vcs_name="svn",
        remote_url=remote_url,
        commit_id=revision,
        package_name=package_name,
        location=location,
        repo_root=repo_root,
        always_prefix=True,
        include_subdirectory=False,
    )


def _get_svn_info(location: str) -> tuple[str, str] | None:
    """Parse svn info --xml to extract URL and revision."""
    try:
        xml_output = subprocess.run(
            ["svn", "info", "--xml"],  # noqa: S607
            cwd=location,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    try:
        root = ET.fromstring(xml_output)  # noqa: S314
    except ET.ParseError:
        return None
    entry = root.find(".//entry")
    if entry is None:
        return None
    revision = entry.get("revision", "")
    url_elem = entry.find("url")
    if url_elem is None or not url_elem.text:
        return None
    return url_elem.text, revision


def _get_svn_entries_fallback(location: str) -> tuple[str, str] | None:
    """Parse legacy .svn/entries file (pre-1.7 SVN) for URL and revision."""
    entries_path = Path(location) / ".svn" / "entries"
    if not entries_path.is_file():
        return None
    try:
        data = entries_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if data.startswith("<?xml"):
        return None
    lines = data.splitlines()
    if len(lines) < 5:
        return None
    revision = lines[3].strip()
    url = lines[4].strip()
    if not url:
        return None
    return url, revision


__all__ = [
    "get_svn_requirement",
]
