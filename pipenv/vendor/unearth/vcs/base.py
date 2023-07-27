from __future__ import annotations

import abc
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Collection, Sequence, Type, TypeVar, cast

from pipenv.vendor.unearth.errors import UnpackError, URLError, VCSBackendError
from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.utils import compare_urls

logger = logging.getLogger(__name__)


class HiddenText:
    """A string that redacts the auth info from the URL."""

    def __init__(self, secret: str, redacted: str) -> None:
        self.secret = secret
        self.redacted = redacted

    def __str__(self) -> str:
        return self.redacted

    def __repr__(self) -> str:
        return f"<URL {str(self)!r}>"


class VersionControl(abc.ABC):
    """The base class for all version control systems.

    Attributes:
        name: the backend name
        dir_name: the backend data directory, such as '.git'
        action: the word to describe the clone action.
    """

    name: str
    dir_name: str

    def __init__(self, verbosity: int = 0) -> None:
        self.verbosity = verbosity

    def run_command(
        self,
        cmd: Sequence[str | HiddenText],
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
        log_output: bool = True,
        stdout_only: bool = False,
        extra_ok_returncodes: Collection[int] = (),
    ) -> subprocess.CompletedProcess[str]:
        """Run the command in the given working directory."""
        env = None
        if extra_env:
            env = dict(os.environ, **extra_env)
        try:
            cmd = [self.name] + cmd  # type: ignore
            display_cmd = subprocess.list2cmdline(map(str, cmd))
            logger.debug("Running command %s", display_cmd)
            result = subprocess.run(
                [v.secret if isinstance(v, HiddenText) else v for v in cmd],
                cwd=str(cwd) if cwd else None,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL if stdout_only else subprocess.STDOUT,
                env=env,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            if e.returncode in extra_ok_returncodes:
                if log_output:
                    logger.debug(e.stdout.rstrip())
                return subprocess.CompletedProcess(e.args, e.returncode, e.stdout)
            raise UnpackError(e.output) from None
        else:
            if log_output:
                logger.debug(result.stdout.rstrip())
            return result

    def _is_local_repository(self, repo: str) -> bool:
        """
        posix absolute paths start with os.path.sep,
        win32 ones start with drive (like c:\\folder)
        """
        drive, _ = os.path.splitdrive(repo)
        return repo.startswith(os.path.sep) or bool(drive)

    def get_url_and_rev_options(
        self, link: Link
    ) -> tuple[HiddenText, str | None, list[str | HiddenText]]:
        """Get the URL and revision options from the link."""
        parsed = link.parsed
        scheme = parsed.scheme.rsplit("+", 1)[-1]
        netloc, user, password = self.get_netloc_and_auth(parsed.netloc, scheme)
        if password is not None:
            password = HiddenText(password, "***")  # type: ignore[assignment]
        replace_dict = {
            "scheme": parsed.scheme.rsplit("+", 1)[-1],
            "netloc": netloc,
            "fragment": "",
        }
        if "@" not in parsed.path:
            rev = None
        else:
            path, _, rev = parsed.path.rpartition("@")
            if not rev:
                raise URLError(
                    f"The url {link.redacted!r} has an empty revision (after @)."
                    "You should specify a revision or remove the @ from the URL."
                )
            replace_dict["path"] = path
        args = self.make_auth_args(user, cast(HiddenText, password))
        url = parsed._replace(**replace_dict).geturl()
        hidden_url = HiddenText(url, Link(url).redacted)
        return hidden_url, rev, args

    def fetch(self, link: Link, location: Path) -> None:
        """Clone the repository to the destination directory, and return
        the path to the local repository.

        Args:
            link (Link): the VCS link to the repository
            location (Path): the destination directory
        """
        url, rev, args = self.get_url_and_rev_options(link)
        if not location.exists():
            return self.fetch_new(location, url, rev, args)

        if not self.is_repository_dir(location) or not compare_urls(
            url.secret, self.get_remote_url(location)
        ):
            if not self.is_repository_dir(location):
                logger.debug(f"{location} is not a repository directory, removing it.")
            else:
                remote_url = self.get_remote_url(location)
                logger.debug(
                    f"{location} is a repository directory, but the remote url "
                    f"{remote_url!r} does not match the url {url!r}."
                )
            shutil.rmtree(location)
            return self.fetch_new(location, url, rev, args)

        if self.is_commit_hash_equal(location, rev):
            logger.debug("Repository %s is already up-to-date", location)
            return
        self.update(location, rev, args)

    @abc.abstractmethod
    def fetch_new(
        self,
        location: Path,
        url: HiddenText,
        rev: str | None,
        args: list[str | HiddenText],
    ) -> None:
        """Fetch the repository from the remote link, as if it is the first time.

        Args:
            location (Path): the repository location
            link (Link): the VCS link to the repository
            rev (str|None): the revision to checkout
            args (list[str | HiddenText]): the arguments to pass to the update command
        """
        pass

    @abc.abstractmethod
    def update(
        self, location: Path, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        """Update the repository to the given revision.

        Args:
            location (Path): the repository location
            rev (str|None): the revision to checkout
            args (list[str | HiddenText]): the arguments to pass to the update command
        """
        pass

    @abc.abstractmethod
    def get_remote_url(self, location: Path) -> str:
        """Get the remote URL of the repository."""
        return ""

    @abc.abstractmethod
    def get_revision(self, location: Path) -> str:
        """Get the commit hash of the repository."""
        pass

    def is_immutable_revision(self, location: Path, link: Link) -> bool:
        """Check if the revision is immutable.
        Always return False if the backend doesn't support immutable revisions.
        """
        return False

    def get_rev_args(self, rev: str | None) -> list[str]:
        """Get the revision arguments for the command."""
        return [rev] if rev is not None else []

    def is_commit_hash_equal(self, location: Path, rev: str | None) -> bool:
        """Always assume the versions don't match"""
        return False

    def is_repository_dir(self, location: Path) -> bool:
        """Check if the given directory is a repository directory."""
        return location.joinpath(self.dir_name).exists()

    def get_netloc_and_auth(
        self, netloc: str, scheme: str
    ) -> tuple[str, str | None, str | None]:
        """Get the auth info and the URL from the link.
        For VCS like git, the auth info must stay in the URL.
        """
        return netloc, None, None

    def make_auth_args(
        self, user: str | None, password: HiddenText | None
    ) -> list[str | HiddenText]:
        """Make the auth args for the URL."""
        return []


_V = TypeVar("_V", bound=Type[VersionControl])


class VcsSupport:
    def __init__(self) -> None:
        self._registry: dict[str, Type[VersionControl]] = {}

    def register(self, vcs: _V) -> _V:
        self._registry[vcs.name] = vcs
        return vcs

    def unregister_all(self) -> None:
        self._registry.clear()

    def get_backend(self, name: str, verbosity: int = 0) -> VersionControl:
        try:
            return self._registry[name](verbosity=verbosity)
        except KeyError:
            raise VCSBackendError(name)


vcs_support = VcsSupport()
