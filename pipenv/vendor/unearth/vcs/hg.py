from __future__ import annotations

import logging
from pathlib import Path

from pipenv.vendor.unearth.utils import display_path, path_to_url
from pipenv.vendor.unearth.vcs.base import HiddenText, VersionControl, vcs_support

logger = logging.getLogger(__name__)


@vcs_support.register
class Mercurial(VersionControl):
    name = "hg"
    dir_name = ".hg"

    def fetch_new(
        self,
        location: Path,
        url: HiddenText,
        rev: str | None,
        args: list[str | HiddenText],
    ) -> None:
        rev_display = f" (revision: {rev})" if rev else ""
        logger.info("Cloning hg %s%s to %s", url, rev_display, display_path(location))
        if self.verbosity <= 0:
            flags: tuple[str, ...] = ("--quiet",)
        elif self.verbosity == 1:
            flags = ()
        elif self.verbosity == 2:
            flags = ("--verbose",)
        else:
            flags = ("--verbose", "--debug")
        self.run_command(["clone", "--noupdate", *flags, url, str(location)])
        self.run_command(
            ["update", *flags, *self.get_rev_args(rev)],
            cwd=location,
        )

    def update(
        self, location: Path, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        self.run_command(["pull", "-q"], cwd=location)
        cmd_args = ["update", "-q", *self.get_rev_args(rev)]
        self.run_command(cmd_args, cwd=location)

    def get_revision(self, location: Path) -> str:
        current_revision = self.run_command(
            ["parents", "--template={rev}"],
            log_output=False,
            stdout_only=True,
            cwd=location,
        ).stdout.strip()
        return current_revision

    def get_remote_url(self, location: Path) -> str:
        url = self.run_command(
            ["showconfig", "paths.default"],
            log_output=False,
            stdout_only=True,
            cwd=location,
        ).stdout.strip()
        if self._is_local_repository(url):
            url = path_to_url(url)
        return url.strip()
