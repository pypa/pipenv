from collections.abc import Mapping
from typing import Dict, List, Optional, Tuple, TypeVar, Union
from urllib.parse import urlparse, urlsplit, urlunparse

from pipenv.patched.pip._internal.commands.install import InstallCommand
from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.network.download import Downloader
from pipenv.patched.pip._internal.operations.prepare import (
    File,
    _check_download_dir,
    get_file_url,
    unpack_vcs_link,
)
from pipenv.patched.pip._internal.utils.hashes import Hashes
from pipenv.patched.pip._internal.utils.temp_dir import TempDirectory
from pipenv.patched.pip._internal.utils.unpacking import unpack_file
from pipenv.utils.internet import _strip_credentials_from_url, is_valid_url

STRING_TYPE = Union[bytes, str, str]
S = TypeVar("S", bytes, str, str)
PipfileEntryType = Union[STRING_TYPE, bool, Tuple[STRING_TYPE], List[STRING_TYPE]]
PipfileType = Union[STRING_TYPE, Dict[STRING_TYPE, PipfileEntryType]]


VCS_LIST = ("git", "svn", "hg", "bzr")
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")


VCS_SCHEMES = {
    "git",
    "git+http",
    "git+https",
    "git+ssh",
    "git+git",
    "git+file",
    "hg",
    "hg+http",
    "hg+https",
    "hg+ssh",
    "hg+static-http",
    "svn",
    "svn+ssh",
    "svn+http",
    "svn+https",
    "svn+svn",
    "bzr",
    "bzr+http",
    "bzr+https",
    "bzr+ssh",
    "bzr+sftp",
    "bzr+ftp",
    "bzr+lp",
}


def add_ssh_scheme_to_git_uri(uri):
    # type: (S) -> S
    """Cleans VCS uris from pip format."""
    if isinstance(uri, str):
        # Add scheme for parsing purposes, this is also what pip does
        if uri.startswith("git+") and "://" not in uri:
            uri = uri.replace("git+", "git+ssh://", 1)
            parsed = urlparse(uri)
            if ":" in parsed.netloc:
                netloc, _, path_start = parsed.netloc.rpartition(":")
                path = f"/{path_start}{parsed.path}"
                uri = urlunparse(parsed._replace(netloc=netloc, path=path))
    return uri


def is_vcs(pipfile_entry):
    # type: (PipfileType) -> bool
    """Determine if dictionary entry from Pipfile is for a vcs dependency."""
    if isinstance(pipfile_entry, Mapping):
        return any(key for key in pipfile_entry if key in VCS_LIST)

    elif isinstance(pipfile_entry, str):
        if not is_valid_url(pipfile_entry) and pipfile_entry.startswith("git+"):
            pipfile_entry = add_ssh_scheme_to_git_uri(pipfile_entry)

        parsed_entry = urlsplit(pipfile_entry)
        return parsed_entry.scheme in VCS_SCHEMES
    return False


def prepare_pip_source_args(sources, pip_args=None):
    # type: (List[Dict[S, Union[S, bool]]], Optional[List[S]]) -> List[S]
    """Prepare pip arguments for source indexes.

    Userinfo (``user:pass``) embedded in source URLs is stripped before
    being added to the argument list to avoid leaking credentials via
    process listings (GHSA-8xgg-v3jj-95m2).  Pipenv supplies the
    credentials to pip out-of-band via a temporary netrc file.
    """
    if pip_args is None:
        pip_args = []
    if sources:
        primary_url, _ = _strip_credentials_from_url(sources[0]["url"])
        pip_args.extend(["-i", primary_url])  # type: ignore
        # Trust the host if it's not verified.
        hostname = urlparse(sources[0]["url"]).hostname
        if not sources[0].get("verify_ssl", True) and hostname:
            pip_args.extend(["--trusted-host", hostname])  # type: ignore
        # Add additional sources as extra indexes.
        for source in sources[1:]:
            extra_url, _ = _strip_credentials_from_url(source["url"])
            pip_args.extend(["--extra-index-url", extra_url])  # type: ignore
            hostname = urlparse(source["url"]).hostname
            if not source.get("verify_ssl", True) and hostname:
                pip_args.extend(["--trusted-host", hostname])  # type: ignore
    return pip_args


def _merge_into(target, source):
    """Recursively merge ``source`` into ``target`` in place, last-write-wins.

    Mapping-valued keys on both sides are merged recursively; everything
    else (including lists / tomlkit ``Array`` values) is overwritten by
    the value from ``source``. Tomlkit container types
    (``Table``/``InlineTable``) subclass ``dict`` and so are merged like
    any other mapping; the container type already present on ``target``
    is preserved, which is what callers downstream of
    ``tomlkit_value_to_python`` expect.
    """
    for key, value in source.items():
        existing = target.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            _merge_into(existing, value)
        else:
            target[key] = value
    return target


def _new_container_like(mapping):
    """Return a fresh empty mapping that matches ``mapping``'s top-level
    container shape where it's safe to do so.

    Plain dicts (and ``dict`` subclasses that accept a no-arg constructor)
    are recreated as the same class. Tomlkit ``Table``/``InlineTable``
    instances cannot be constructed with no args, so they fall back to
    a plain ``dict`` -- the previous boltons-based implementation also
    handed back a plain dict at the top level for these inputs in the
    real call sites (``dict(packages_table)`` is always taken first).
    """
    cls = mapping.__class__
    if cls is dict:
        return {}
    try:
        return cls()
    except TypeError:
        return {}


def merge_items(target_list, sourced=False):
    """Recursively merge a list of Pipfile-category dicts, last-write-wins.

    Only the ``sourced=False`` path has callers in pipenv; the
    ``sourced=True`` branch is preserved for API parity but is not
    exercised by any in-tree call site.

    For an empty ``target_list``, returns ``None`` to match the
    historical behaviour of the boltons-backed implementation.
    """
    if not target_list:
        return None if not sourced else (None, {})

    iterator = iter(target_list)
    if sourced:
        source_map = {}
        first_name, first = next(iterator)
        merged = _new_container_like(first)
        _merge_into(merged, first)
        for key in merged:
            source_map[(key,)] = first_name
        for t_name, target in iterator:
            _merge_into(merged, target)
            for key in target:
                source_map[(key,)] = t_name
        return merged, source_map

    first = next(iterator)
    merged = _new_container_like(first)
    _merge_into(merged, first)
    for target in iterator:
        _merge_into(merged, target)
    return merged


def get_pip_command() -> InstallCommand:
    """Get pip's InstallCommand for configuration management and defaults."""
    # Use pip's parser for pip.conf management and defaults.
    # General options (find_links, index_url, extra_index_url, trusted_host,
    # and pre) are deferred to pip.
    pip_command = InstallCommand(
        name="InstallCommand", summary="pipenv pip Install command."
    )
    return pip_command


def unpack_url(
    link: Link,
    location: str,
    download: Downloader,
    verbosity: int,
    download_dir: Optional[str] = None,
    hashes: Optional[Hashes] = None,
) -> Optional[File]:
    """Unpack link into location, downloading if required.

    :param hashes: A Hashes object, one of whose embedded hashes must match,
        or HashMismatch will be raised. If the Hashes is empty, no matches are
        required, and unhashable types of requirements (like VCS ones, which
        would ordinarily raise HashUnsupported) are allowed.

    Provenance: forked from
    ``pip._internal.operations.prepare.unpack_url`` (reachable here as
    ``pipenv.patched.pip._internal.operations.prepare.unpack_url``).
    Behavioural divergence from the upstream copy that is load-bearing
    for our one caller (:func:`pipenv.utils.dependencies.determine_package_name`):

    * For VCS links, this fork returns ``File(location, content_type=None)``
      so the caller can treat the unpacked checkout directory as a normal
      ``File`` and run ``find_package_name_from_directory`` on it. Pip's
      version returns ``None`` for VCS links, which would
      ``AttributeError`` on the caller's unconditional ``local_file.path``
      access. The caller's guard
      ``package.link.scheme in REMOTE_SCHEMES`` includes VCS schemes
      (see ``pipenv/utils/constants.py``), so VCS links DO reach this
      function in practice.
    * VCS-link detection uses ``link.scheme in VCS_SCHEMES`` (this
      module's local constant) rather than pip's ``link.is_vcs``
      property. Equivalent in practice but kept as-is.

    Do not replace with the patched-pip version without auditing the
    caller -- see ``docs/dev/initiative-b-triage.md`` for rationale.
    """
    # non-editable vcs urls
    if link.scheme in VCS_SCHEMES:
        unpack_vcs_link(link, location, verbosity=verbosity)
        return File(location, content_type=None)

    assert not link.is_existing_dir()

    # file urls
    if link.is_file:
        file = get_file_url(link, download_dir, hashes=hashes)

    # http urls
    else:
        file = get_http_url(
            link,
            download,
            download_dir,
            hashes=hashes,
        )

    # unpack the archive to the build dir location. even when only downloading
    # archives, they have to be unpacked to parse dependencies, except wheels
    if not link.is_wheel:
        unpack_file(file.path, location, file.content_type)

    return file


def get_http_url(
    link: Link,
    download: Downloader,
    download_dir: Optional[str] = None,
    hashes: Optional[Hashes] = None,
) -> File:
    """Download a file from an HTTP URL.

    Provenance: forked from
    ``pip._internal.operations.prepare.get_http_url`` (reachable here as
    ``pipenv.patched.pip._internal.operations.prepare.get_http_url``).
    Behavioural divergence from the upstream copy: this fork constructs
    ``TempDirectory(..., globally_managed=False)`` while pip uses
    ``globally_managed=True``. Pip's global-management mode hooks the
    temp dir into pip's process-level ``TempDirectoryRegistry`` for
    cleanup at interpreter exit; that registry is the wrong lifetime
    for our caller (:func:`unpack_url` called from
    :func:`pipenv.utils.dependencies.determine_package_name`), whose
    parent ``with TemporaryDirectory() as td:`` block already owns
    cleanup. Used only by :func:`unpack_url` in this module. Do not
    replace with the patched-pip version without auditing the caller.
    """
    temp_dir = TempDirectory(kind="unpack", globally_managed=False)
    # If a download dir is specified, is the file already downloaded there?
    already_downloaded_path = None
    if download_dir:
        already_downloaded_path = _check_download_dir(link, download_dir, hashes)

    if already_downloaded_path:
        from_path = already_downloaded_path
        content_type = None
    else:
        # let's download to a tmp dir
        from_path, content_type = download(link, temp_dir.path)
        if hashes:
            hashes.check_against_path(from_path)

    return File(from_path, content_type)
