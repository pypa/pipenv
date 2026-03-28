from __future__ import annotations

import locale
import os
import re
import site
import string
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .direct_url import get_direct_url

if TYPE_CHECKING:
    from importlib.metadata import Distribution


def get_editable_location(distribution: Distribution) -> str | None:
    """
    Get source location for an editable installation.

    Tries modern PEP 610 direct_url.json first, then falls back to legacy .egg-link files.
    See: https://peps.python.org/pep-0610/

    :param distribution: Distribution to check
    :returns: Path to editable source location, or None if package is not editable
    """
    if (direct_url := get_direct_url(distribution)) and direct_url.is_editable():
        return url_to_path(direct_url.url)
    if egg_link := find_egg_link(distribution.metadata["Name"]):
        return read_egg_link_location(egg_link)
    return None


def url_to_path(url: str) -> str:
    """
    Convert file:// URL to filesystem path.

    Handles localhost URLs, UNC paths on Windows, and Windows drive letter corrections.
    Matches pip's url_to_path implementation for compatibility.

    :param url: URL to convert (must have file:// scheme)
    :returns: Filesystem path
    :raises ValueError: If URL doesn't use file:// scheme or is non-local on non-Windows platforms
    """
    if not url.startswith("file:"):
        msg = f"You can only turn file: urls into filenames (not {url!r})"
        raise ValueError(msg)
    _, netloc, path, _, _ = urlsplit(url)
    if not netloc or netloc == "localhost":
        netloc = ""
    elif os.name == "nt":
        netloc = "\\\\" + netloc  # pragma: win32 cover
    else:
        msg = f"non-local file URIs are not supported on this platform: {url!r}"
        raise ValueError(msg)
    path = url2pathname(netloc + path)
    if (
        os.name == "nt"  # noqa: PLR0916
        and not netloc
        and len(path) >= 3
        and path[0] == "/"
        and path[1] in string.ascii_letters
        and path[2:4] in {":", ":/"}
    ):
        path = path[1:]  # pragma: win32 cover
    return path


def find_egg_link(package_name: str) -> Path | None:
    """
    Find .egg-link file for legacy editable installations.

    Matches pip's egg_link_path_from_sys_path: searches sys.path entries first,
    then falls back to site-packages and user site-packages.

    :param package_name: Name of package to search for
    :returns: Path to .egg-link file if found, None otherwise
    """
    candidates = _egg_link_names(package_name)
    for search_dir in sys.path:
        for name in candidates:
            if (egg_link := Path(search_dir) / name).is_file():
                return egg_link
    site_dirs = site.getsitepackages() if hasattr(site, "getsitepackages") else []
    if user_site := site.getusersitepackages():
        site_dirs.append(user_site)
    for site_dir in site_dirs:
        for name in candidates:
            if (egg_link := Path(site_dir) / name).is_file():
                return egg_link
    return None


def _egg_link_names(package_name: str) -> list[str]:
    """Generate candidate egg-link filenames: safe-name normalized and raw."""
    safe_name = re.sub(r"[^A-Za-z0-9.]+", "-", package_name)
    candidates = [f"{safe_name}.egg-link"]
    if safe_name != package_name:
        candidates.append(f"{package_name}.egg-link")
    return candidates


def read_egg_link_location(egg_link_path: Path) -> str:
    """
    Read source directory path from .egg-link file.

    The first line of an .egg-link file contains the absolute path to the source directory.

    :param egg_link_path: Path to .egg-link file
    :returns: Source directory path
    """
    with egg_link_path.open("r", encoding=locale.getpreferredencoding(do_setlocale=False)) as f:
        return f.readline().rstrip()


__all__ = [
    "find_egg_link",
    "get_editable_location",
    "read_egg_link_location",
    "url_to_path",
]
