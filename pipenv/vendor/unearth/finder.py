"""The main class for the unearth package."""
from __future__ import annotations

import atexit
import functools
import itertools
import os
import pathlib
import warnings
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Iterable, NamedTuple, Sequence
from urllib.parse import urljoin

import packaging.requirements
from pipenv.patched.pip._vendor.packaging.utils import BuildTag, canonicalize_name, parse_wheel_filename
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version

from pipenv.vendor.unearth.collector import collect_links_from_location
from pipenv.vendor.unearth.evaluator import (
    Evaluator,
    FormatControl,
    Package,
    TargetPython,
    evaluate_package,
    is_equality_specifier,
    validate_hashes,
)
from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.preparer import unpack_link
from pipenv.vendor.unearth.session import PyPISession
from pipenv.vendor.unearth.utils import LazySequence

if TYPE_CHECKING:
    from typing import TypedDict

    class Source(TypedDict):
        url: str
        type: str

else:
    Source = dict


class BestMatch(NamedTuple):
    """The best match for a package."""

    #: The best matching package, or None if no match was found.
    best: Package | None
    #: The applicable packages, excluding those with unmatching versions.
    applicable: Sequence[Package]
    #: All candidates found for the requirement.
    candidates: Sequence[Package]


class PackageFinder:
    """The main class for the unearth package.

    Args:
        session (PyPISession|None): The session to use for the finder.
            If not provided, a temporary session will be created.
        index_urls (Iterable[str]): The index URLs to search for packages.
        find_links (Iterable[str]): The links to search for packages.
        trusted_hosts: (Iterable[str]): The trusted hosts.
        target_python (TargetPython): The links must match
            the target Python
        ignore_compatibility (bool): Whether to ignore the compatibility check
        no_binary (Iterable[str]): The names of the packages to disallow wheels
        only_binary (Iterable[str]): The names of the packages to disallow non-wheels
        prefer_binary (Iterable[str]): The names of the packages to prefer binary
            distributions even if newer sdist pacakges exist.
        respect_source_order (bool): If True, packages from the source coming earlier
            are more preferred, even if they have lower versions.
        verbosity (int): The verbosity level.
    """

    def __init__(
        self,
        session: PyPISession | None = None,
        *,
        index_urls: Iterable[str] = (),
        find_links: Iterable[str] = (),
        trusted_hosts: Iterable[str] = (),
        target_python: TargetPython | None = None,
        ignore_compatibility: bool = False,
        no_binary: Iterable[str] = (),
        only_binary: Iterable[str] = (),
        prefer_binary: Iterable[str] = (),
        respect_source_order: bool = False,
        verbosity: int = 0,
    ) -> None:
        self.sources: list[Source] = []
        for url in index_urls:
            self.add_index_url(url)
        for url in find_links:
            self.add_find_links(url)
        self.target_python = target_python or TargetPython()
        self.ignore_compatibility = ignore_compatibility
        self.no_binary = [canonicalize_name(name) for name in no_binary]
        self.only_binary = [canonicalize_name(name) for name in only_binary]
        self.prefer_binary = [canonicalize_name(name) for name in prefer_binary]
        self.trusted_hosts = trusted_hosts
        self._session = session
        self.respect_source_order = respect_source_order
        self.verbosity = verbosity

        self._tag_priorities = {
            tag: i for i, tag in enumerate(self.target_python.supported_tags())
        }

    @property
    def session(self) -> PyPISession:
        if self._session is None:
            index_urls = [
                source["url"] for source in self.sources if source["type"] == "index"
            ]
            session = PyPISession(
                index_urls=index_urls, trusted_hosts=self.trusted_hosts
            )
            atexit.register(session.close)
            self._session = session
        return self._session

    def add_index_url(self, url: str) -> None:
        """Add an index URL to the finder search scope.

        Args:
            url (str): The index URL to add.
        """
        self.sources.append({"url": url, "type": "index"})

    def add_find_links(self, url: str) -> None:
        """Add a find links URL to the finder search scope.

        Args:
            url (str): The find links URL to add.
        """
        self.sources.append({"url": url, "type": "find_links"})

    def build_evaluator(
        self,
        package_name: str,
        allow_yanked: bool = False,
        hashes: dict[str, list[str]] | None = None,
    ) -> Evaluator:
        """Build an evaluator for the given package name.

        Args:
            package_name (str): The desired package name
            allow_yanked (bool): Whether to allow yanked candidates.

        Returns:
            Evaluator: The evaluator for the given package name
        """
        if hashes is not None:
            warnings.warn(
                "The evaluator no longer validates hashes, "
                "please remove the hashes argument",
                FutureWarning,
                stacklevel=2,
            )
        canonical_name = canonicalize_name(package_name)
        format_control = FormatControl(
            no_binary=canonical_name in self.no_binary or ":all:" in self.no_binary,
            only_binary=canonical_name in self.only_binary
            or ":all:" in self.only_binary,
        )
        return Evaluator(
            package_name=package_name,
            target_python=self.target_python,
            ignore_compatibility=self.ignore_compatibility,
            allow_yanked=allow_yanked,
            format_control=format_control,
        )

    def _build_index_page_link(self, index_url: str, package_name: str) -> Link:
        return Link(
            urljoin(index_url.rstrip("/") + "/", canonicalize_name(package_name) + "/")
        )

    def _build_find_link(self, find_link: str) -> Link:
        if os.path.exists(find_link):
            return Link.from_path(os.path.abspath(find_link))
        elif "://" in find_link:
            return Link(find_link)
        raise ValueError(f"Invalid find link or non-existing path: {find_link}")

    def _evaluate_links(
        self, links: Iterable[Link], evaluator: Evaluator
    ) -> Iterable[Package]:
        return filter(None, map(evaluator.evaluate_link, links))

    def _evaluate_packages(
        self,
        packages: Iterable[Package],
        requirement: packaging.requirements.Requirement,
        allow_prereleases: bool | None = None,
    ) -> Iterable[Package]:
        evaluator = functools.partial(
            evaluate_package,
            requirement=requirement,
            allow_prereleases=allow_prereleases,
        )
        return filter(evaluator, packages)

    def _evaluate_hashes(
        self, packages: Iterable[Package], hashes: dict[str, list[str]]
    ) -> Iterable[Package]:
        evaluator = functools.partial(
            validate_hashes, hashes=hashes, session=self.session
        )
        return filter(evaluator, packages)

    def _sort_key(self, package: Package) -> tuple:
        """The key for sort, package with the largest value is the most preferred."""
        link = package.link
        pri = len(self._tag_priorities) + 1  # default priority for sdist.
        build_tag: BuildTag = ()
        prefer_binary = False
        if link.is_wheel:
            *_, build_tag, file_tags = parse_wheel_filename(link.filename)
            pri = min(
                (self._tag_priorities.get(tag, pri - 1) for tag in file_tags),
                default=pri - 1,
            )
            if canonicalize_name(package.name) in self.prefer_binary:
                prefer_binary = True

        return (
            -int(link.is_yanked),
            int(prefer_binary),
            parse_version(package.version) if package.version is not None else 0,
            -pri,
            build_tag,
        )

    def _find_packages(
        self,
        package_name: str,
        allow_yanked: bool = False,
    ) -> Iterable[Package]:
        """Find all packages with the given name.

        Args:
            package_name (str): The desired package name
            allow_yanked (bool): Whether to allow yanked candidates.

        Returns:
            Iterable[Package]: The packages with the given name, sorted by best match.
        """
        evaluator = self.build_evaluator(package_name, allow_yanked)

        def find_one_source(source: Source) -> Iterable[Package]:
            if source["type"] == "index":
                link = self._build_index_page_link(source["url"], package_name)
                result = self._evaluate_links(
                    collect_links_from_location(self.session, link), evaluator
                )
            else:
                link = self._build_find_link(source["url"])
                result = self._evaluate_links(
                    collect_links_from_location(self.session, link, expand=True),
                    evaluator,
                )
            if self.respect_source_order:
                # Sort the result within the individual source.
                return sorted(result, key=self._sort_key, reverse=True)
            return result

        all_packages = itertools.chain.from_iterable(map(find_one_source, self.sources))
        if self.respect_source_order:
            return all_packages
        # Otherwise, sort the result across all sources.
        return sorted(all_packages, key=self._sort_key, reverse=True)

    def find_all_packages(
        self,
        package_name: str,
        allow_yanked: bool = False,
        hashes: dict[str, list[str]] | None = None,
    ) -> Sequence[Package]:
        """Find all packages with the given package name, best match first.

        Args:
            package_name (str): The desired package name
            allow_yanked (bool): Whether to allow yanked candidates.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            Sequence[Package]: The packages list sorted by best match
        """
        return LazySequence(
            self._evaluate_hashes(
                self._find_packages(package_name, allow_yanked), hashes=hashes or {}
            )
        )

    def _find_packages_from_requirement(
        self,
        requirement: packaging.requirements.Requirement,
        allow_yanked: bool | None = None,
    ) -> Iterable[Package]:
        if allow_yanked is None:
            allow_yanked = is_equality_specifier(requirement.specifier)
        if requirement.url:
            yield Package(requirement.name, None, link=Link(requirement.url))
        else:
            yield from self._find_packages(requirement.name, allow_yanked)

    def find_matches(
        self,
        requirement: packaging.requirements.Requirement | str,
        allow_yanked: bool | None = None,
        allow_prereleases: bool | None = None,
        hashes: dict[str, list[str]] | None = None,
    ) -> Sequence[Package]:
        """Find all packages matching the given requirement, best match first.

        Args:
            requirement: A packaging.requirements.Requirement
                instance or a string to construct it.
            allow_yanked (bool|None): Whether to allow yanked candidates,
                or None to infer from the specifier.
            allow_prereleases (bool|None): Whether to allow prereleases,
                or None to infer from the specifier.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            Sequence[Package]: The packages sorted by best match
        """
        if isinstance(requirement, str):
            requirement = packaging.requirements.Requirement(requirement)
        return LazySequence(
            self._evaluate_hashes(
                self._evaluate_packages(
                    self._find_packages_from_requirement(requirement, allow_yanked),
                    requirement,
                    allow_prereleases,
                ),
                hashes=hashes or {},
            )
        )

    def find_best_match(
        self,
        requirement: packaging.requirements.Requirement | str,
        allow_yanked: bool | None = None,
        allow_prereleases: bool | None = None,
        hashes: dict[str, list[str]] | None = None,
    ) -> BestMatch:
        """Find the best match for the given requirement.

        Args:
            requirement: A packaging.requirements.Requirement
                instance or a string to construct it.
            allow_yanked (bool|None): Whether to allow yanked candidates,
                or None to infer from the specifier.
            allow_prereleases (bool|None): Whether to allow prereleases,
                or None to infer from the specifier.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            BestMatch: The best match
        """
        if isinstance(requirement, str):
            requirement = packaging.requirements.Requirement(requirement)
        packages = self._find_packages_from_requirement(requirement, allow_yanked)
        candidates = LazySequence(packages)
        applicable_candidates = LazySequence(
            self._evaluate_hashes(
                self._evaluate_packages(packages, requirement, allow_prereleases),
                hashes=hashes or {},
            )
        )
        best_match = next(iter(applicable_candidates), None)
        return BestMatch(best_match, applicable_candidates, candidates)

    def download_and_unpack(
        self,
        link: Link,
        location: str | pathlib.Path,
        download_dir: str | pathlib.Path | None = None,
        hashes: dict[str, list[str]] | None = None,
    ) -> pathlib.Path:
        """Download and unpack the package at the given link.

        If the link is a remote link, it will be downloaded to the ``download_dir``.
        Then, if the link is a wheel, the path of wheel file will be returned,
        otherwise it will be unpacked to the destination. Specially, if the link refers
        to a local directory, the path will be returned directly, otherwise the unpacked
        source path will be returned. And if the link has a subdirectory fragment, the
        subdirectory will be returned.

        Args:
            link (Link): The link to download
            location: The destination directory
            download_dir: The directory to download to, or None to use a
                temporary directory created by unearth.
            hashes (dict[str, list[str]]|None): The optional hash dict for validation.

        Returns:
            The path to the installable file or directory.
        """
        # Strip the rev part for VCS links
        if hashes is None:
            hashes = link.hash_option
        if download_dir is None:
            download_dir = TemporaryDirectory(prefix="unearth-download-").name
        file = unpack_link(
            self.session,
            link,
            pathlib.Path(download_dir),
            pathlib.Path(location),
            hashes,
            verbosity=self.verbosity,
        )
        return file.joinpath(link.subdirectory) if link.subdirectory else file
