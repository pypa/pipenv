from typing import Optional

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
