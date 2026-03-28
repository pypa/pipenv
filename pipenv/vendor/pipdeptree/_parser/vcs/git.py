from __future__ import annotations

import os
import re
import subprocess  # noqa: S404
from pathlib import Path
from typing import Final

from .shared import VcsError, VcsResult, build_vcs_result, is_local_path

_SANITIZED_GIT_VARS: Final[frozenset[str]] = frozenset({"GIT_DIR", "GIT_WORK_TREE"})
_SCHEME_RE: Final[re.Pattern[str]] = re.compile(r"\w+://")
_SCP_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    ^
    (?P<user>\w+@)?    # Optional user, e.g. 'git@'
    (?P<host>[^/:]+):  # Server, e.g. 'github.com'
    (?P<path>\w[^:]*)  # Server-side path starting with alphanumeric (not Windows C:)
    $
    """,
    re.VERBOSE,
)


def get_git_repo_root(location: str) -> str | None:
    """Find git repository root from any subdirectory."""
    try:
        repo_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
            cwd=location,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            env=_git_env(),
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    except FileNotFoundError:
        return None
    else:
        return repo_root or None


def get_git_requirement(location: str, package_name: str, repo_root: str) -> VcsResult:
    try:
        remote_url = _get_git_remote_url(repo_root)
        if remote_url is None:
            return VcsResult(None, vcs_name="git", error=VcsError.NO_REMOTE)
        if not (commit_id := _get_git_commit_id(repo_root)):
            return VcsResult(None, vcs_name="git", error=VcsError.NO_REMOTE)
    except FileNotFoundError:
        return VcsResult(None, vcs_name="git", error=VcsError.COMMAND_NOT_FOUND)
    normalized = _normalize_git_url(remote_url, repo_root)
    if normalized is None:
        return VcsResult(None, vcs_name="git", error=VcsError.INVALID_REMOTE)
    return build_vcs_result(
        vcs_name="git",
        remote_url=normalized,
        commit_id=commit_id,
        package_name=package_name,
        location=location,
        repo_root=repo_root,
        always_prefix=True,
    )


def _get_git_remote_url(repo_root: str) -> str | None:
    """Get git remote URL, preferring origin."""
    try:
        remotes_output = subprocess.run(
            ["git", "config", "--get-regexp", r"remote\..*\.url"],  # noqa: S607
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env=_git_env(),
        ).stdout.strip()
        if not remotes_output:
            return None
        remotes = remotes_output.splitlines()
        found_remote = remotes[0]
        for remote in remotes:
            if remote.startswith("remote.origin.url "):
                found_remote = remote
                break
        parts = found_remote.split(" ", 1)
        return parts[1].strip() if len(parts) >= 2 and parts[1].strip() else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _get_git_commit_id(repo_root: str) -> str | None:
    """Get current git commit ID."""
    try:
        commit_id = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            env=_git_env(),
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    else:
        return commit_id or None


def _normalize_git_url(url: str, repo_root: str) -> str | None:
    """
    Normalize git URL to standard format matching pip's behavior.

    Returns None for URLs that don't match any known pattern.
    """
    if _SCHEME_RE.match(url):
        return url
    path = Path(url) if is_local_path(url) else Path(repo_root) / url
    if path.exists():
        return path.resolve().as_uri()
    if match := _SCP_RE.match(url):
        return f"ssh://{match.group('user') or ''}{match.group('host')}/{match.group('path')}"
    return None


def _git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _SANITIZED_GIT_VARS}


__all__ = [
    "get_git_repo_root",
    "get_git_requirement",
]
