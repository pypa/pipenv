from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from pipenv.vendor.unearth.errors import UnpackError
from pipenv.vendor.unearth.utils import display_path, split_auth_from_netloc
from pipenv.vendor.unearth.vcs.base import HiddenText, VersionControl, vcs_support

logger = logging.getLogger(__name__)

_svn_xml_url_re = re.compile('url="([^"]+)"')
_svn_rev_re = re.compile(r'committed-rev="(\d+)"')
_svn_info_xml_rev_re = re.compile(r'\s*revision="(\d+)"')
_svn_info_xml_url_re = re.compile(r"<url>(.*)</url>")


def is_installable_dir(path: Path) -> bool:
    for project_file in ("pyproject.toml", "setup.py"):
        if (path / project_file).exists():
            return True
    return False


@vcs_support.register
class Subversion(VersionControl):
    name = "svn"
    dir_name = ".svn"

    def get_netloc_and_auth(
        self, netloc: str, scheme: str
    ) -> tuple[str, str | None, str | None]:
        if scheme == "ssh":
            return netloc, None, None
        user_pass, netloc = split_auth_from_netloc(netloc)
        if not user_pass:
            return netloc, None, None
        return netloc, user_pass[0], user_pass[1]

    def get_rev_args(self, rev: str | None) -> list[str]:
        return ["-r", rev] if rev is not None else []

    def make_auth_args(
        self, user: str | None, password: HiddenText | None
    ) -> list[str | HiddenText]:
        args: list[str | HiddenText] = []
        if user is not None:
            args.extend(["--username", user])
        if password is not None:
            args.extend(["--password", password])
        return args

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
        else:
            flag = ""
        cmd_args = [
            "checkout",
            flag,
            "--non-interactive",
            *self.get_rev_args(rev),
            url,
            str(location),
        ]
        self.run_command(cmd_args)  # type: ignore

    def update(
        self, location: Path, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        cmd_args = [
            "update",
            "--non-interactive",
            *self.get_rev_args(rev),
            str(location),
        ]
        self.run_command(cmd_args)  # type: ignore

    def get_remote_url(self, location: Path) -> str:
        orig_location = location
        while not is_installable_dir(location):
            last_location = location
            location = location.parent
            if location == last_location:
                # We've traversed up to the root of the filesystem without
                # finding a Python project.
                raise UnpackError(
                    f"Could not find Python project for directory {orig_location} "
                    "(tried all parent directories)",
                )

        url, _ = self._get_svn_url_rev(location)
        if url is None:
            raise UnpackError(f"Remote not found for {location}")

        return url

    def get_revision(self, location: Path) -> str:
        revision = 0

        for base, dirs, _ in os.walk(location):
            if self.dir_name not in dirs:
                dirs[:] = []
                continue  # no sense walking uncontrolled subdirs
            dirs.remove(self.dir_name)
            entries_fn = os.path.join(base, self.dir_name, "entries")
            if not os.path.exists(entries_fn):
                # FIXME: should we warn?
                continue

            dirurl, localrev = self._get_svn_url_rev(Path(base))

            if Path(base) == location:
                assert dirurl is not None
                base = dirurl + "/"  # save the root url
            elif not dirurl or not dirurl.startswith(base):
                dirs[:] = []
                continue  # not part of the same svn tree, skip it
            revision = max(revision, localrev)
        return str(revision)

    def _get_svn_url_rev(self, location: Path) -> tuple[str | None, int]:
        entries_path = os.path.join(location, self.dir_name, "entries")
        if os.path.exists(entries_path):
            with open(entries_path) as f:
                data = f.read()
        else:  # subversion >= 1.7 does not have the 'entries' file
            data = ""

        url = None
        if data.startswith("8") or data.startswith("9") or data.startswith("10"):
            entries = list(map(str.splitlines, data.split("\n\x0c\n")))
            del entries[0][0]  # get rid of the '8'
            url = entries[0][3]
            revs = [int(d[9]) for d in entries if len(d) > 9 and d[9]] + [0]
        elif data.startswith("<?xml"):
            match = _svn_xml_url_re.search(data)
            if not match:
                raise ValueError(f"Badly formatted data: {data!r}")
            url = match.group(1)  # get repository URL
            revs = [int(m.group(1)) for m in _svn_rev_re.finditer(data)] + [0]
        else:
            try:
                # subversion >= 1.7
                # Note that using get_remote_call_options is not necessary here
                # because `svn info` is being run against a local directory.
                # We don't need to worry about making sure interactive mode
                # is being used to prompt for passwords, because passwords
                # are only potentially needed for remote server requests.
                xml = self.run_command(
                    ["info", "--xml", str(location)],
                    log_output=False,
                    stdout_only=True,
                ).stdout
                match = _svn_info_xml_url_re.search(xml)
                assert match is not None
                url = match.group(1)
                revs = [int(m.group(1)) for m in _svn_info_xml_rev_re.finditer(xml)]
            except UnpackError:
                url, revs = None, []

        if revs:
            rev = max(revs)
        else:
            rev = 0

        return url, rev
