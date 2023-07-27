"""A package should contain a link to the actual file."""
from __future__ import annotations

import functools
import itertools
import os
import re
import sys
import urllib.parse as parse
import warnings
from pathlib import Path
from typing import Iterable, Iterator, Sequence, TypeVar
from urllib.request import pathname2url, url2pathname

WINDOWS = sys.platform == "win32"


def parse_query(query: str) -> dict[str, str]:
    """Parse the query string of a url."""
    return {k: v[0] for k, v in parse.parse_qs(query).items()}


def add_ssh_scheme_to_git_uri(uri: str) -> str:
    """Cleans VCS uris from pip format"""
    # Add scheme for parsing purposes, this is also what pip does
    if "://" not in uri:
        uri = "ssh://" + uri
        parsed = parse.urlparse(uri)
        if ":" in parsed.netloc:
            netloc, _, path_start = parsed.netloc.rpartition(":")
            path = "/{0}{1}".format(path_start, parsed.path)
            uri = parse.urlunparse(parsed._replace(netloc=netloc, path=path))
    return uri


def strip_extras(name: str) -> str:
    """Strip the extras part following package name."""
    return name.split("[", 1)[0]


def build_url_from_netloc(netloc: str, scheme: str = "https") -> str:
    """
    Build a full URL from a netloc.
    """
    if netloc.count(":") >= 2 and "@" not in netloc and "[" not in netloc:
        # It must be a bare IPv6 address, so wrap it with brackets.
        netloc = f"[{netloc}]"
    return f"{scheme}://{netloc}"


def parse_netloc(netloc: str) -> tuple[str, int | None]:
    """
    Return the host-port pair from a netloc.
    """
    url = build_url_from_netloc(netloc)
    parsed = parse.urlparse(url)
    return parsed.hostname or "", parsed.port


def url_to_path(url: str) -> str:
    """
    Convert a file: URL to a path.
    """
    assert url.startswith(
        "file:"
    ), f"You can only turn file: urls into filenames (not {url!r})"

    _, netloc, path, _, _ = parse.urlsplit(url)

    if not netloc or netloc == "localhost":
        # According to RFC 8089, same as empty authority.
        netloc = ""
    elif WINDOWS:
        # If we have a UNC path, prepend UNC share notation.
        netloc = "\\\\" + netloc
    else:
        raise ValueError(
            f"non-local file URIs are not supported on this platform: {url!r}"
        )

    path = url2pathname(netloc + path)

    # On Windows, urlsplit parses the path as something like "/C:/Users/foo".
    # This creates issues for path-related functions like io.open(), so we try
    # to detect and strip the leading slash.
    if (
        WINDOWS
        and not netloc  # Not UNC.
        and len(path) >= 3
        and path[0] == "/"  # Leading slash to strip.
        and path[1].isalpha()  # Drive letter.
        and path[2:4] in (":", ":/")  # Colon + end of string, or colon + absolute path.
    ):
        path = path[1:]

    return path


def path_to_url(path: str) -> str:
    """
    Convert a path to a file: URL.  The path will be made absolute and have
    quoted path parts.
    """
    path = os.path.normpath(os.path.abspath(path))
    url = parse.urljoin("file:", pathname2url(path))
    return url


WHEEL_EXTENSION = ".whl"
BZ2_EXTENSIONS = (".tar.bz2", ".tbz")
XZ_EXTENSIONS = (
    ".tar.xz",
    ".txz",
    ".tlz",
    ".tar.lz",
    ".tar.lzma",
)
ZIP_EXTENSIONS = (".zip", WHEEL_EXTENSION)
TAR_EXTENSIONS = (".tar.gz", ".tgz", ".tar")
ARCHIVE_EXTENSIONS = ZIP_EXTENSIONS + BZ2_EXTENSIONS + TAR_EXTENSIONS + XZ_EXTENSIONS


def is_archive_file(name: str) -> bool:
    """Return True if `name` is a considered as an archive file."""
    ext = splitext(name)[1].lower()
    return ext in ARCHIVE_EXTENSIONS


def split_auth_from_netloc(netloc: str) -> tuple[tuple[str, str | None] | None, str]:
    auth, has_auth, host = netloc.rpartition("@")
    if not has_auth:
        return None, host
    user, has_pass, password = auth.partition(":")
    return (parse.unquote(user), parse.unquote(password) if has_pass else None), host


@functools.lru_cache(maxsize=128)
def split_auth_from_url(url: str) -> tuple[tuple[str, str | None] | None, str]:
    """Return a tuple of ((username, password), url_without_auth)"""
    parsed = parse.urlparse(url)
    auth, netloc = split_auth_from_netloc(parsed.netloc)
    if auth is None:
        return None, url
    return auth, parse.urlunparse(parsed._replace(netloc=netloc))


@functools.lru_cache(maxsize=128)
def compare_urls(left: str, right: str) -> bool:
    """
    Compare two urls, ignoring the ending slash.
    """
    return parse.unquote(left).rstrip("/") == parse.unquote(right).rstrip("/")


def display_path(path: Path) -> str:
    """Show the path relative to cwd if possible"""
    if not path.is_absolute():
        return str(path)
    try:
        relative = path.absolute().relative_to(Path.cwd())
    except ValueError:
        return str(path)
    else:
        return str(relative)


def splitext(path: str) -> tuple[str, str]:
    """Like os.path.splitext but also takes off the .tar part"""
    base, ext = os.path.splitext(path)
    if base.lower().endswith(".tar"):
        ext = base[-4:] + ext
        base = base[:-4]
    return base, ext


def format_size(size: str) -> str:
    try:
        int_size = int(size)
    except (TypeError, ValueError):
        return "size unknown"
    if int_size > 1000 * 1000:
        return f"{int_size / 1000.0 / 1000:.1f} MB"
    elif int_size > 10 * 1000:
        return f"{int(int_size / 1000)} kB"
    elif int_size > 1000:
        return f"{int_size / 1000.0:.1f} kB"
    else:
        return f"{int(int_size)} bytes"


T = TypeVar("T", covariant=True)


class LazySequence(Sequence[T]):
    """A sequence that is lazily evaluated."""

    def __init__(self, data: Iterable[T]) -> None:
        self._inner = data

    def __iter__(self) -> Iterator[T]:
        self._inner, this = itertools.tee(self._inner)
        return this

    def __len__(self) -> int:
        i = 0
        for _ in self:
            i += 1
        return i

    def __bool__(self) -> bool:
        for _ in self:
            return True
        return False

    def __getitem__(self, index: int) -> T:  # type: ignore[override]
        if index < 0:
            raise IndexError("Negative indices are not supported")
        for i, item in enumerate(self):
            if i == index:
                return item
        raise IndexError("Index out of range")


_legacy_specifier_re = re.compile(r"(==|!=|<=|>=|<|>)(\s*)([^,;\s)]*)")


@functools.lru_cache()
def fix_legacy_specifier(specifier: str) -> str:
    """Since packaging 22.0, legacy specifiers like '>=4.*' are no longer
    supported. We try to normalize them to the new format.
    """

    def fix_wildcard(match: re.Match[str]) -> str:
        operator, _, version = match.groups()
        if operator in ("==", "!="):
            return match.group(0)
        if ".*" in version:
            warnings.warn(
                ".* suffix can only be used with `==` or `!=` operators",
                FutureWarning,
                stacklevel=4,
            )
            version = version.replace(".*", ".0")
            if operator in ("<", "<="):  # <4.* and <=4.* are equivalent to <4.0
                operator = "<"
            elif operator in (">", ">="):  # >4.* and >=4.* are equivalent to >=4.0
                operator = ">="
        elif "+" in version:  # Drop the local version
            warnings.warn(
                "Local version label can only be used with `==` or `!=` operators",
                FutureWarning,
                stacklevel=4,
            )
            version = version.split("+")[0]
        return f"{operator}{version}"

    return _legacy_specifier_re.sub(fix_wildcard, specifier)
