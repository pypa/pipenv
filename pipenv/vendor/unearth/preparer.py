"""Unpack the link to an installed wheel or source."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable, cast

from pipenv.patched.pip._vendor.requests import HTTPError, Session

from pipenv.vendor.unearth.errors import HashMismatchError, UnpackError
from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.utils import (
    BZ2_EXTENSIONS,
    TAR_EXTENSIONS,
    XZ_EXTENSIONS,
    ZIP_EXTENSIONS,
    display_path,
    format_size,
)
from pipenv.vendor.unearth.vcs import vcs_support

READ_CHUNK_SIZE = 8192
logger = logging.getLogger(__name__)


def set_extracted_file_to_default_mode_plus_executable(path: str) -> None:
    """
    Make file present at path have execute for user/group/world
    (chmod +x) is no-op on windows per python docs
    """
    os.chmod(path, (0o777 & ~os.umask(0) | 0o111))


def zip_item_is_executable(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    # if mode and regular file and any execute permissions for
    # user/group/world?
    return bool(mode and stat.S_ISREG(mode) and mode & 0o111)


def is_within_directory(directory: str | Path, path: str | Path) -> bool:
    try:
        Path(path).relative_to(directory)
    except ValueError:
        return False
    return True


def split_leading_dir(path: str) -> list[str]:
    path = path.lstrip("/").lstrip("\\")
    if "/" in path and (
        ("\\" in path and path.find("/") < path.find("\\")) or "\\" not in path
    ):
        return path.split("/", 1)
    elif "\\" in path:
        return path.split("\\", 1)
    else:
        return [path, ""]


def has_leading_dir(paths: Iterable[str]) -> bool:
    """Returns true if all the paths have the same leading path name
    (i.e., everything is in one subdirectory in an archive)"""
    common_prefix = None
    for path in paths:
        prefix, _ = split_leading_dir(path)
        if not prefix:
            return False
        elif common_prefix is None:
            common_prefix = prefix
        elif prefix != common_prefix:
            return False
    return True


class HashValidator:
    """Validate the hashes of a file."""

    def __init__(self, package_link: Link, hashes: dict[str, list[str]] | None) -> None:
        if hashes is not None:
            # Always sort the hash values for better comparison.
            hashes = {k: sorted(value) for k, value in hashes.items()}
        self.allowed = hashes
        self.package_link = package_link
        self.got = {}
        if hashes is not None:
            for name in hashes:
                try:
                    self.got[name] = hashlib.new(name)
                except (TypeError, ValueError):
                    raise UnpackError(f"Unknown hash name: {name!r}") from None

    def update(self, chunk: bytes) -> None:
        for hasher in self.got.values():
            hasher.update(chunk)

    def validate(self) -> None:
        if not self.allowed:
            return
        gots: dict[str, str] = {}
        for name, hash_list in self.allowed.items():
            got = self.got[name].hexdigest()
            if got in hash_list:
                return
            gots[name] = got
        raise HashMismatchError(self.package_link, self.allowed, gots)

    def validate_path(self, path: Path) -> None:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(READ_CHUNK_SIZE), b""):
                self.update(chunk)
        self.validate()


def _check_downloaded(path: Path, hashes: dict[str, list[str]] | None) -> bool:
    """Check if the file has been downloaded."""
    if not path.is_file():
        return False
    try:
        HashValidator(Link.from_path(path), hashes).validate_path(path)
    except HashMismatchError:
        logger.debug("File exists at %s, but the hashes don't match", path)
        path.unlink()
        return False
    logger.debug("The file is already downloaded: %s", path)
    return True


def unpack_archive(archive: Path, dest: Path) -> None:
    content_type = mimetypes.guess_type(str(archive))[0]
    if (
        content_type == "application/zip"
        or zipfile.is_zipfile(archive)
        or archive.suffix.lower() in ZIP_EXTENSIONS
    ):
        _unzip_archive(archive, dest)
    elif (
        content_type == "application/x-gzip"
        or tarfile.is_tarfile(archive)
        or archive.suffix.lower() in (TAR_EXTENSIONS + XZ_EXTENSIONS + BZ2_EXTENSIONS)
    ):
        _untar_archive(archive, dest)
    else:
        raise UnpackError(f"Unknown archive type: {archive.name}")


def _unzip_archive(filename: Path, location: Path) -> None:
    os.makedirs(location, exist_ok=True)
    zipfp = open(filename, "rb")
    with zipfile.ZipFile(zipfp, allowZip64=True) as zip:
        leading = has_leading_dir(zip.namelist())
        for info in zip.infolist():
            name = info.filename
            fn = name
            if leading:
                fn = split_leading_dir(name)[1]
            fn = os.path.join(location, fn)
            dir = os.path.dirname(fn)
            if not is_within_directory(location, fn):
                message = (
                    f"The zip file ({filename}) has a file ({fn}) trying to install "
                    f"outside target directory ({location})"
                )
                raise UnpackError(message)
            if fn.endswith("/") or fn.endswith("\\"):
                # A directory
                os.makedirs(fn, exist_ok=True)
            else:
                os.makedirs(dir, exist_ok=True)
                # Don't use read() to avoid allocating an arbitrarily large
                # chunk of memory for the file's content
                with zip.open(name) as fp, open(fn, "wb") as destfp:
                    shutil.copyfileobj(fp, destfp)

                if zip_item_is_executable(info):
                    set_extracted_file_to_default_mode_plus_executable(fn)


def _untar_archive(filename: Path, location: Path) -> None:
    """Untar the file (with path `filename`) to the destination `location`."""
    os.makedirs(location, exist_ok=True)
    lower_fn = str(filename).lower()
    if lower_fn.endswith(".gz") or lower_fn.endswith(".tgz"):
        mode = "r:gz"
    elif lower_fn.endswith(BZ2_EXTENSIONS):
        mode = "r:bz2"
    elif lower_fn.endswith(XZ_EXTENSIONS):
        mode = "r:xz"
    elif lower_fn.endswith(".tar"):
        mode = "r"
    else:
        logger.warning(
            "Cannot determine compression type for file %s",
            filename,
        )
        mode = "r:*"
    with tarfile.open(filename, mode, encoding="utf-8") as tar:
        leading = has_leading_dir([member.name for member in tar.getmembers()])
        for member in tar.getmembers():
            fn = member.name
            if leading:
                fn = split_leading_dir(fn)[1]
            path = os.path.join(location, fn)
            if not is_within_directory(location, path):
                message = (
                    f"The tar file ({filename}) has a file ({path}) trying to install "
                    f"outside target directory ({location})"
                )
                raise UnpackError(message)
            if member.isdir():
                os.makedirs(path, exist_ok=True)
            elif member.issym():
                try:
                    tar._extract_member(member, path)
                except Exception as exc:
                    # Some corrupt tar files seem to produce this
                    # (specifically bad symlinks)
                    logger.warning(
                        "In the tar file %s the member %s is invalid: %s",
                        filename,
                        member.name,
                        exc,
                    )
                    continue
            else:
                try:
                    fp = tar.extractfile(member)
                except (KeyError, AttributeError) as exc:
                    # Some corrupt tar files seem to produce this
                    # (specifically bad symlinks)
                    logger.warning(
                        "In the tar file %s the member %s is invalid: %s",
                        filename,
                        member.name,
                        exc,
                    )
                    continue
                os.makedirs(os.path.dirname(path), exist_ok=True)
                assert fp is not None
                with open(path, "wb") as destfp:
                    shutil.copyfileobj(fp, destfp)
                fp.close()
                # Update the timestamp (useful for cython compiled files)
                tar.utime(member, path)
                # member have any execute permissions for user/group/world?
                if member.mode & 0o111:
                    set_extracted_file_to_default_mode_plus_executable(path)


def unpack_link(
    session: Session,
    link: Link,
    download_dir: Path,
    location: Path,
    hashes: dict[str, list[str]] | None = None,
    verbosity: int = 0,
) -> Path:
    """Unpack link into location.

    The link can be a VCS link or a file link.

    Args:
        session (Session): the requests session
        link (Link): the link to unpack
        download_dir (Path): the directory to download the file to
        location (Path): the destination directory
        hashes (dict[str, list[str]]|None): Optional hash dict for validation
        progress_bar (bool): whether to show the progress bar

    Returns:
        Path: the path to the unpacked file or directory
    """
    location.parent.mkdir(parents=True, exist_ok=True)
    if link.is_vcs:
        backend = vcs_support.get_backend(cast(str, link.vcs), verbosity=verbosity)
        backend.fetch(link, location)
        return location

    validator = HashValidator(link, hashes)
    if link.is_file:
        if link.file_path.is_dir():
            logger.info(
                "The file %s is a local directory, use it directly",
                display_path(link.file_path),
            )
            return link.file_path
        artifact = link.file_path
        validator.validate_path(artifact)
    else:
        # A remote artfiact link, check the download dir first
        artifact = download_dir / link.filename
        if not _check_downloaded(artifact, hashes):
            resp = session.get(link.normalized, stream=True)
            try:
                resp.raise_for_status()
            except HTTPError as e:
                raise UnpackError(f"Download failed: {e}") from None
            if getattr(resp, "from_cache", False):
                logger.info("Using cached %s", link)
            else:
                size = format_size(resp.headers.get("Content-Length", ""))
                logger.info("Downloading %s (%s)", link, size)
            with artifact.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=READ_CHUNK_SIZE):
                    if chunk:
                        validator.update(chunk)
                        f.write(chunk)
            validator.validate()
    if link.is_wheel:
        if link.is_file:
            # Use the local file directly
            return artifact
        target_file = location / link.filename
        if target_file != artifact:
            # For wheels downloaded from remote locations, move it to the destination.
            os.replace(artifact, target_file)
        return target_file

    unpack_archive(artifact, location)
    return location
