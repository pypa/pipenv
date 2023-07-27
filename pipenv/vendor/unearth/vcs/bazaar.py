from __future__ import annotations

import logging
from pathlib import Path

from pipenv.vendor.unearth.errors import UnpackError
from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.utils import display_path, path_to_url
from pipenv.vendor.unearth.vcs.base import HiddenText, VersionControl, vcs_support

logger = logging.getLogger(__name__)


@vcs_support.register
class Bazaar(VersionControl):
    name = "bzr"
    dir_name = ".bzr"

    def get_rev_args(self, rev: str | None) -> list[str]:
        return ["-r", rev] if rev is not None else []

    def fetch_new(
        self,
        location: Path,
        url: HiddenText,
        rev: str | None,
        args: list[str | HiddenText],
    ) -> None:
        rev_display = f" (revision: {rev})" if rev else ""
        logger.info("Checking out %s%s to %s", url, rev_display, display_path(location))
        if self.verbosity <= 0:
            flag = "--quiet"
        elif self.verbosity == 1:
            flag = ""
        else:
            flag = f"-{'v'*self.verbosity}"
        cmd_args = ["branch", flag, *self.get_rev_args(rev), url, str(location)]
        self.run_command(cmd_args)  # type: ignore

    def update(
        self, location: Path, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        self.run_command(["pull", "-q", *self.get_rev_args(rev)], cwd=location)

    def get_remote_url(self, location: Path) -> str:
        urls = self.run_command(
            ["info"], log_output=False, stdout_only=True, cwd=location
        ).stdout
        for line in urls.splitlines():
            line = line.strip()
            for x in ("checkout of branch: ", "parent branch: "):
                if line.startswith(x):
                    repo = line.split(x)[1]
                    if self._is_local_repository(repo):
                        return path_to_url(repo)
                    return repo
        raise UnpackError(f"Remote not found for {display_path(location)}")

    def get_revision(self, location: Path) -> str:
        revision = self.run_command(
            ["revno"], log_output=False, stdout_only=True, cwd=location
        ).stdout
        return revision.splitlines()[-1]

    def get_url_and_rev_options(
        self, link: Link
    ) -> tuple[HiddenText, str | None, list[str | HiddenText]]:
        """Re-add bzr+ to the ssh:// URL"""
        hidden_url, rev, args = super().get_url_and_rev_options(link)
        if hidden_url.secret.startswith("ssh://"):
            hidden_url.secret = f"bzr+{hidden_url.secret}"
            hidden_url.redacted = f"bzr+{hidden_url.redacted}"
        return hidden_url, rev, args
