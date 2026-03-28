from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .bzr import get_bzr_requirement
from .git import get_git_repo_root, get_git_requirement
from .hg import get_hg_requirement
from .shared import VcsError, VcsResult
from .svn import get_svn_requirement

if TYPE_CHECKING:
    from collections.abc import Callable


def get_vcs_requirement(location: str, package_name: str) -> VcsResult:
    """
    Detect VCS and generate requirement string for editable install.

    Probes directory for git/hg/svn/bzr repositories (including parent directories),
    picks the innermost repo root (matching pip's get_backend_for_dir logic).

    :param location: Filesystem path to source directory
    :param package_name: Package name for egg fragment
    :returns: VcsResult with requirement string and diagnostic info
    """
    roots: dict[str, Callable[[str, str, str], VcsResult]] = {}
    if git_root := get_git_repo_root(location):
        roots[git_root] = get_git_requirement
    if hg_root := _find_marker_root(location, ".hg", dir_only=False):
        roots[hg_root] = get_hg_requirement
    if svn_root := _find_marker_root(location, ".svn"):
        roots[svn_root] = get_svn_requirement
    if bzr_root := _find_marker_root(location, ".bzr"):
        roots[bzr_root] = get_bzr_requirement
    if not roots:
        return VcsResult(None, error=VcsError.NO_VCS)
    innermost = ""
    for root in roots:
        if len(root) > len(innermost):
            innermost = root
    return roots[innermost](location, package_name, innermost)


def _find_marker_root(location: str, marker: str, *, dir_only: bool = True) -> str | None:
    """Walk up from location looking for a directory containing marker (e.g. .hg, .svn, .bzr)."""
    current = Path(location).resolve()
    check = Path.is_dir if dir_only else Path.exists
    while True:
        if check(current / marker):
            return str(current)
        parent = current.parent
        if parent == current:
            return None
        current = parent


__all__ = [
    "VcsError",
    "VcsResult",
    "get_vcs_requirement",
]
