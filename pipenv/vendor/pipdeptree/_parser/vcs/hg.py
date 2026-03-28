from __future__ import annotations

import subprocess  # noqa: S404
from pathlib import Path

from .shared import VcsError, VcsResult, build_vcs_result, is_local_path


def get_hg_requirement(location: str, package_name: str, repo_root: str) -> VcsResult:
    try:
        remote_url = _get_hg_remote_url(repo_root)
        if remote_url is None:
            return VcsResult(None, vcs_name="hg", error=VcsError.NO_REMOTE)
        if is_local_path(remote_url):
            remote_url = Path(remote_url).as_uri()
        if not (commit_id := _get_hg_commit_id(repo_root)):
            return VcsResult(None, vcs_name="hg", error=VcsError.NO_REMOTE)
    except FileNotFoundError:
        return VcsResult(None, vcs_name="hg", error=VcsError.COMMAND_NOT_FOUND)
    return build_vcs_result(
        vcs_name="hg",
        remote_url=remote_url,
        commit_id=commit_id,
        package_name=package_name,
        location=location,
        repo_root=repo_root,
        always_prefix=False,
    )


def _get_hg_remote_url(repo_root: str) -> str | None:
    try:
        url = subprocess.run(
            ["hg", "showconfig", "paths.default"],  # noqa: S607
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    else:
        return url or None


def _get_hg_commit_id(repo_root: str) -> str | None:
    try:
        commit_id = subprocess.run(
            ["hg", "parents", "--template={node}"],  # noqa: S607
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    else:
        return commit_id or None


__all__ = [
    "get_hg_requirement",
]
