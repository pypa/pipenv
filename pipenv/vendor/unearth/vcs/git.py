from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from pipenv.vendor.unearth.errors import UnpackError
from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.utils import add_ssh_scheme_to_git_uri, display_path, path_to_url
from pipenv.vendor.unearth.vcs.base import HiddenText, VersionControl, vcs_support

logger = logging.getLogger(__name__)


@vcs_support.register
class Git(VersionControl):
    name = "git"
    dir_name = ".git"

    def get_git_version(self) -> tuple[int, ...]:
        result = self.run_command(["version"], stdout_only=True, log_output=False)
        output = result.stdout.strip()
        match = re.match(r"git version (\d+)\.(\d+)(?:\.(\d+))?", output)
        if not match:
            raise UnpackError(f"Failed to get git version: {output}")
        return tuple(int(part) for part in match.groups())

    def fetch_new(
        self,
        location: Path,
        url: HiddenText,
        rev: str | None,
        args: list[str | HiddenText],
    ) -> None:
        rev_display = f" (revision: {rev})" if rev else ""
        logger.info("Cloning %s%s to %s", url, rev_display, display_path(location))
        env = None
        if self.verbosity <= 0:
            flags: tuple[str, ...] = ("--quiet",)
            env = {"GIT_TERMINAL_PROMPT": "0"}
        elif self.verbosity == 1:
            flags = ()
        else:
            flags = ("--verbose", "--progress")
        if self.get_git_version() >= (2, 17):
            # Git added support for partial clone in 2.17
            # https://git-scm.com/docs/partial-clone
            # Speeds up cloning by functioning without a complete copy of repository
            self.run_command(
                ["clone", "--filter=blob:none", *flags, url, str(location)],
                extra_env=env,
            )
        else:
            self.run_command(["clone", *flags, url, str(location)], extra_env=env)

        if rev is not None:
            self.run_command(["checkout", "-q", rev], cwd=location)
        revision = self.get_revision(location)
        logger.info("Resolved %s to commit %s", url, revision)
        self._update_submodules(location)

    def _update_submodules(self, location: Path) -> None:
        if not location.joinpath(".gitmodules").exists():
            return
        self.run_command(
            ["submodule", "update", "--init", "-q", "--recursive"], cwd=location
        )

    def update(
        self, location: Path, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        self.run_command(["fetch", "-q", "--tags"], cwd=location)
        if rev is None:
            rev = "HEAD"
        try:
            # try as if the rev is a branch name or HEAD
            resolved = self._resolve_revision(location, f"origin/{rev}")
        except UnpackError:
            resolved = self._resolve_revision(location, rev)
        logger.info("Updating %s to commit %s", display_path(location), resolved)
        self.run_command(["reset", "--hard", "-q", resolved], cwd=location)

    def get_remote_url(self, location: Path) -> str:
        result = self.run_command(
            ["config", "--get-regexp", r"remote\..*\.url"],
            extra_ok_returncodes=(1,),
            cwd=location,
            stdout_only=True,
            log_output=False,
        )
        remotes = result.stdout.splitlines()
        try:
            found_remote = remotes[0]
        except IndexError:
            raise UnpackError(f"Remote not found for {display_path(location)}")

        for remote in remotes:
            if remote.startswith("remote.origin.url "):
                found_remote = remote
                break
        url = found_remote.split(" ")[1]
        return self._git_remote_to_pip_url(url.strip())

    def _git_remote_to_pip_url(self, url: str) -> str:
        if "://" in url:
            return url
        if os.path.exists(url):
            return path_to_url(os.path.abspath(url))
        else:
            return add_ssh_scheme_to_git_uri(url)

    def _resolve_revision(self, location: Path, rev: str | None) -> str:
        if rev is None:
            rev = "HEAD"
        result = self.run_command(
            ["rev-parse", rev],
            cwd=location,
            stdout_only=True,
            log_output=False,
        )
        return result.stdout.strip()

    def get_revision(self, location: Path) -> str:
        return self._resolve_revision(location, None)

    def is_commit_hash_equal(self, location: Path, rev: str | None) -> bool:
        return rev is not None and self.get_revision(location) == rev

    def is_immutable_revision(self, location: Path, link: Link) -> bool:
        _, rev, _ = self.get_url_and_rev_options(link)
        if rev is None:
            return False
        return self.is_commit_hash_equal(location, rev)
