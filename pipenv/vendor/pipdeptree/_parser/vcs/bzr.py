from __future__ import annotations

import subprocess  # noqa: S404
from pathlib import Path

from .shared import VcsError, VcsResult, build_vcs_result, is_local_path


def get_bzr_requirement(location: str, package_name: str, repo_root: str) -> VcsResult:
    try:
        remote_url = _get_bzr_remote_url(repo_root)
        if remote_url is None:
            return VcsResult(None, vcs_name="bzr", error=VcsError.NO_REMOTE)
        if is_local_path(remote_url):
            remote_url = Path(remote_url).as_uri()
        if not (revision := _get_bzr_revision(repo_root)):
            return VcsResult(None, vcs_name="bzr", error=VcsError.NO_REMOTE)
    except FileNotFoundError:
        return VcsResult(None, vcs_name="bzr", error=VcsError.COMMAND_NOT_FOUND)
    return build_vcs_result(
        vcs_name="bzr",
        remote_url=remote_url,
        commit_id=revision,
        package_name=package_name,
        location=location,
        repo_root=repo_root,
        always_prefix=False,
        include_subdirectory=False,
    )


def _get_bzr_remote_url(repo_root: str) -> str | None:
    """Parse `bzr info` output for checkout/parent branch URL."""
    try:
        output = subprocess.run(
            ["bzr", "info"],  # noqa: S607
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    for line in output.splitlines():
        stripped = line.strip()
        for prefix in ("checkout of branch: ", "parent branch: "):
            if stripped.startswith(prefix):
                return stripped[len(prefix) :].strip() or None
    return None


def _get_bzr_revision(repo_root: str) -> str | None:
    try:
        output = subprocess.run(
            ["bzr", "revno"],  # noqa: S607
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    lines = output.splitlines()
    return lines[-1].strip() if lines else None


__all__ = [
    "get_bzr_requirement",
]
