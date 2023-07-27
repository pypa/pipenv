"""Evaluate the links based on the given environment."""
from __future__ import annotations

import dataclasses as dc
import hashlib
import logging
import sys
from typing import Any

from pipenv.patched.pip._vendor.packaging.requirements import Requirement
from pipenv.patched.pip._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
from pipenv.patched.pip._vendor.packaging.tags import Tag
from pipenv.patched.pip._vendor.packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from pipenv.patched.pip._vendor.packaging.version import InvalidVersion, Version
from pipenv.patched.pip._vendor.requests import Session

from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.pep425tags import get_supported
from pipenv.vendor.unearth.utils import (
    ARCHIVE_EXTENSIONS,
    fix_legacy_specifier,
    splitext,
    strip_extras,
)

logger = logging.getLogger(__name__)


def is_equality_specifier(specifier: SpecifierSet) -> bool:
    return any(s.operator in ("==", "===") for s in specifier)


def parse_version_from_egg_info(egg_info: str, canonical_name: str) -> str | None:
    for i, c in enumerate(egg_info):
        if canonicalize_name(egg_info[:i]) == canonical_name and c in {"-", "_"}:
            return egg_info[i + 1 :]
    return None


class LinkMismatchError(ValueError):
    pass


@dc.dataclass
class TargetPython:
    """Target Python to get the candidates.

    Attributes:
        py_ver: Python version tuple, e.g. ``(3, 9)``.
        platforms: List of platforms, e.g. ``['linux_x86_64']``.
        impl: Implementation, e.g. ``'cp'``.
        abis: List of ABIs, e.g. ``['cp39']``.
    """

    py_ver: tuple[int, ...] | None = None
    abis: list[str] | None = None
    impl: str | None = None
    platforms: list[str] | None = None

    def __post_init__(self) -> None:
        self._valid_tags: list[Tag] | None = None

    def supported_tags(self) -> list[Tag]:
        if self._valid_tags is None:
            if self.py_ver is None:
                py_version = None
            else:
                py_version = "".join(map(str, self.py_ver[:2]))
            self._valid_tags = get_supported(
                py_version, self.platforms, self.impl, self.abis
            )
        return self._valid_tags


@dc.dataclass(frozen=True)
class Package:
    """A package instance has a name, version, and link that can be downloaded
    or unpacked.

    Attributes:
        name: The name of the package.
        version: The version of the package, or ``None`` if the requirement is a link.
        link: The link to the package.
    """

    name: str
    version: str | None
    link: Link = dc.field(repr=False)

    def as_json(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the package."""
        return {
            "name": self.name,
            "version": self.version,
            "link": self.link.as_json(),
        }


@dc.dataclass(frozen=True)
class FormatControl:
    only_binary: bool = False
    no_binary: bool = False

    def __post_init__(self):
        if self.only_binary and self.no_binary:
            raise ValueError(
                "Not allowed to set only_binary and no_binary at the same time."
            )

    def check_format(self, link: Link, project_name: str) -> None:
        if self.only_binary:
            if not link.is_wheel:
                raise LinkMismatchError(f"only binaries are allowed for {project_name}")
        if self.no_binary:
            if link.is_wheel:
                raise LinkMismatchError(f"no binary is allowed for {project_name}")
        return


@dc.dataclass
class Evaluator:
    """Evaluate the links based on the given environment.

    Args:
        package_name (str): The links must match the package name
        target_python (TargetPython): The links must match the target Python
        ignore_compatibility (bool): Whether to ignore the compatibility check
        allow_yanked (bool): Whether to allow yanked candidates
        format_control (bool): Format control flags
    """

    package_name: str
    target_python: TargetPython = dc.field(default_factory=TargetPython)
    ignore_compatibility: bool = False
    allow_yanked: bool = False
    format_control: FormatControl = dc.field(default_factory=FormatControl)

    def __post_init__(self) -> None:
        self._canonical_name = canonicalize_name(self.package_name)

    def check_yanked(self, link: Link) -> None:
        if link.yank_reason is not None and not self.allow_yanked:
            yank_reason = f"due to {link.yank_reason}" if link.yank_reason else ""
            raise LinkMismatchError(f"Yanked {yank_reason}")

    def check_requires_python(self, link: Link) -> None:
        if not self.ignore_compatibility and link.requires_python:
            py_ver = self.target_python.py_ver or sys.version_info[:2]
            py_version = ".".join(str(v) for v in py_ver)
            try:
                requires_python = SpecifierSet(
                    fix_legacy_specifier(link.requires_python)
                )
            except InvalidSpecifier:
                raise LinkMismatchError(
                    f"Invalid requires-python: {link.requires_python}"
                )
            if not requires_python.contains(py_version, True):
                raise LinkMismatchError(
                    "The target python version({}) doesn't match "
                    "the requires-python specifier {}".format(
                        py_version, link.requires_python
                    ),
                )

    def evaluate_link(self, link: Link) -> Package | None:
        """
        Evaluate the link and return the package if it matches or None if it doesn't.
        """
        try:
            self.format_control.check_format(link, self.package_name)
            self.check_yanked(link)
            self.check_requires_python(link)
            version: str | None = None
            if link.is_wheel:
                try:
                    wheel_info = parse_wheel_filename(link.filename)
                except (InvalidWheelFilename, InvalidVersion) as e:
                    raise LinkMismatchError(str(e))
                if self._canonical_name != wheel_info[0]:
                    raise LinkMismatchError(
                        f"The package name doesn't match {wheel_info[0]}"
                    )
                if not self.ignore_compatibility and wheel_info[3].isdisjoint(
                    self.target_python.supported_tags()
                ):
                    raise LinkMismatchError(
                        "none of the wheel tags({}) are compatible".format(
                            ", ".join(sorted(str(tag) for tag in wheel_info[3]))
                        ),
                    )
                version = str(wheel_info[1])
            else:
                if link._fragment_dict.get("egg"):
                    egg_info = strip_extras(link._fragment_dict["egg"])
                else:
                    egg_info, ext = splitext(link.filename)
                    if not ext:
                        raise LinkMismatchError(f"Not a file: {link.filename}")
                    if ext not in ARCHIVE_EXTENSIONS:
                        raise LinkMismatchError(
                            f"Unsupported archive format: {link.filename}"
                        )
                version = parse_version_from_egg_info(egg_info, self._canonical_name)
                if version is None:
                    raise LinkMismatchError(
                        f"Missing version in the filename {egg_info}"
                    )
                try:
                    Version(version)
                except InvalidVersion:
                    raise LinkMismatchError(
                        f"Invalid version in the filename {egg_info}: {version}"
                    )
        except LinkMismatchError as e:
            logger.debug("Skipping link %s: %s", link, e)
            return None
        return Package(name=self.package_name, version=version, link=link)


def evaluate_package(
    package: Package,
    requirement: Requirement,
    allow_prereleases: bool | None = None,
) -> bool:
    """Evaluate the package based on the requirement.

    Args:
        package (Package): The package to evaluate
        requirement: The requirement to evaluate against
        allow_prerelease (bool|None): Whether to allow prereleases,
            or None to infer from the specifier.
    Returns:
        bool: True if the package matches the requirement, False otherwise
    """
    if requirement.name:
        if canonicalize_name(package.name) != canonicalize_name(requirement.name):
            logger.debug(
                "Skipping package %s: name doesn't match %s", package, requirement.name
            )
            return False

    if package.version and not requirement.specifier.contains(
        package.version, prereleases=allow_prereleases
    ):
        logger.debug(
            "Skipping package %s: version doesn't match %s",
            package,
            requirement.specifier,
        )
        return False
    return True


def _get_hash(link: Link, hash_name: str, session: Session) -> str:
    resp = session.get(link.normalized, stream=True)
    hasher = hashlib.new(hash_name)
    for chunk in resp.iter_content(chunk_size=1024 * 8):
        hasher.update(chunk)
    digest = hasher.hexdigest()
    if not link.hashes:
        link.hashes = {}
    link.hashes[hash_name] = digest
    return digest


def validate_hashes(
    package: Package, hashes: dict[str, list[str]], session: Session
) -> bool:
    if not hashes:
        return True
    link = package.link
    link_hashes = link.hash_option
    if link_hashes:
        for hash_name, allowed_hashes in hashes.items():
            if hash_name in link_hashes:
                given_hash = link_hashes[hash_name][0]
                if given_hash not in allowed_hashes:
                    return False
                return True

    hash_name, allowed_hashes = next(iter(hashes.items()))
    given_hash = _get_hash(link, hash_name, session)
    return given_hash in allowed_hashes
