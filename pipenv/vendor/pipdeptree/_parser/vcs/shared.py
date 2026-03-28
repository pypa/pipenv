from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path


class VcsError(Enum):
    NONE = auto()
    NO_VCS = auto()
    NO_REMOTE = auto()
    INVALID_REMOTE = auto()
    COMMAND_NOT_FOUND = auto()


@dataclass
class VcsResult:
    requirement: str | None
    vcs_name: str | None = None
    error: VcsError = VcsError.NONE


def build_vcs_result(  # noqa: PLR0913, PLR0917
    vcs_name: str,
    remote_url: str,
    commit_id: str,
    package_name: str,
    location: str,
    repo_root: str,
    *,
    always_prefix: bool,
    include_subdirectory: bool = True,
) -> VcsResult:
    """Build VcsResult with requirement string from components."""
    safe_package_name = _normalize_egg_name(package_name)
    if always_prefix or not remote_url.lower().startswith(f"{vcs_name}:"):
        url = f"{vcs_name}+{remote_url}"
    else:
        url = remote_url
    quoted_commit_id = urllib.parse.quote(commit_id, "/")
    result = f"{url}@{quoted_commit_id}#egg={safe_package_name}"
    if include_subdirectory and (subdirectory := _find_project_root(location, repo_root)):
        result += f"&subdirectory={subdirectory}"
    return VcsResult(result, vcs_name=vcs_name)


def _normalize_egg_name(name: str) -> str:
    return name.replace("-", "_")


def _find_project_root(location: str, repo_root: str) -> str | None:
    """
    Walk up from location to find the installable project root.

    Matches pip's find_path_to_project_root_from_repo_root:
    walks UP from location looking for pyproject.toml or setup.py.
    """
    current = Path(location).resolve()
    abs_root = Path(repo_root).resolve()
    while not _is_installable_dir(current):
        parent = Path(current).parent
        if parent == current:
            return None
        current = parent
    try:
        if Path(abs_root).samefile(current):
            return None
    except (ValueError, OSError):
        return None
    return os.path.relpath(current, abs_root)


def _is_installable_dir(path: str | Path) -> bool:
    resolved = Path(path)
    return resolved.is_dir() and ((resolved / "pyproject.toml").is_file() or (resolved / "setup.py").is_file())


def is_local_path(path: str) -> bool:
    """Check if path is a local filesystem path (starts with os.sep or has drive letter)."""
    if path.startswith(os.sep):
        return True
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()


__all__ = [
    "VcsError",
    "VcsResult",
    "build_vcs_result",
    "is_local_path",
]
