"""Regression tests for GHSA-p4qx-p8p6-4gjf — tar hardlink/symlink traversal
through the ``LinkOutsideDestinationError`` fallback in
``pipenv.patched.pip._internal.utils.unpacking.untar_file``.

The fallback exists to work around CPython 3.9.17 / 3.10.12 / 3.11.4 where
``tarfile.data_filter`` falsely reported valid in-bounds links as
out-of-bounds (https://github.com/python/cpython/issues/107845).  The
historical fallback to ``tarfile.tar_filter`` did *not* validate that
hardlink targets stayed inside the destination, which an attacker could
abuse to make extraction create links to (and overwrite) files outside
the install destination.

The fix performs an independent containment check before falling back, so
we test:

* the helper ``_tar_link_target_is_within`` accepts in-bounds links and
  rejects out-of-bounds and absolute-path links;
* on the buggy-CPython code path (simulated via monkeypatch),
  ``untar_file`` raises ``InstallationError`` for an attacker-controlled
  hardlink pointing outside the destination;
* on the buggy-CPython code path, an in-bounds hardlink that triggers a
  false-positive still extracts successfully.
"""

from __future__ import annotations

import io
import sys
import tarfile

import pytest

from pipenv.patched.pip._internal.exceptions import InstallationError
from pipenv.patched.pip._internal.utils import unpacking
from pipenv.patched.pip._internal.utils.unpacking import (
    _tar_link_target_is_within,
    untar_file,
)

# ----------------------------------------------------------------------------
# _tar_link_target_is_within
# ----------------------------------------------------------------------------


def _hardlink_member(name: str, linkname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.LNKTYPE
    info.linkname = linkname
    return info


def _symlink_member(name: str, linkname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.SYMTYPE
    info.linkname = linkname
    return info


@pytest.mark.utils
def test_link_target_is_within_accepts_in_bounds_hardlink(tmp_path):
    member = _hardlink_member("pkg/link", "pkg/real")
    assert _tar_link_target_is_within(member, str(tmp_path)) is True


@pytest.mark.utils
def test_link_target_is_within_rejects_parent_traversal(tmp_path):
    member = _hardlink_member("pkg/link", "../escape")
    assert _tar_link_target_is_within(member, str(tmp_path)) is False


@pytest.mark.utils
def test_link_target_is_within_rejects_deep_parent_traversal(tmp_path):
    member = _hardlink_member("pkg/link", "../../../etc/passwd")
    assert _tar_link_target_is_within(member, str(tmp_path)) is False


@pytest.mark.utils
def test_link_target_is_within_rejects_absolute_path(tmp_path):
    member = _hardlink_member("pkg/link", "/etc/passwd")
    assert _tar_link_target_is_within(member, str(tmp_path)) is False


@pytest.mark.utils
def test_link_target_is_within_rejects_empty_linkname(tmp_path):
    member = _hardlink_member("pkg/link", "")
    assert _tar_link_target_is_within(member, str(tmp_path)) is False


@pytest.mark.utils
def test_link_target_is_within_symlink_in_bounds(tmp_path):
    # Symlink target is resolved relative to the link's own directory, so
    # ``pkg/link -> sibling`` resolves to ``<dest>/pkg/sibling``.
    member = _symlink_member("pkg/link", "sibling")
    assert _tar_link_target_is_within(member, str(tmp_path)) is True


@pytest.mark.utils
def test_link_target_is_within_symlink_out_of_bounds(tmp_path):
    member = _symlink_member("pkg/link", "../../escape")
    assert _tar_link_target_is_within(member, str(tmp_path)) is False


@pytest.mark.utils
def test_link_target_is_within_returns_false_for_non_link(tmp_path):
    info = tarfile.TarInfo(name="pkg/regular")
    info.type = tarfile.REGTYPE
    assert _tar_link_target_is_within(info, str(tmp_path)) is False


# ----------------------------------------------------------------------------
# End-to-end: simulate the buggy CPython data_filter and ensure we fail
# closed for attacker-controlled link members.
# ----------------------------------------------------------------------------


def _build_malicious_tar(tar_path: str, target_dir: str) -> None:
    """Write a tar archive containing:

    * a regular file ``pkg/real`` so a hardlink can point at it, and
    * a hardlink ``pkg/escape`` whose linkname escapes ``target_dir``.
    """
    with tarfile.open(tar_path, "w") as tar:
        # Regular file inside the archive root.
        data = b"benign\n"
        info = tarfile.TarInfo(name="pkg/real")
        info.size = len(data)
        info.type = tarfile.REGTYPE
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))

        # Hardlink that, if extracted, would create a link into the parent
        # of the destination directory.
        link_info = tarfile.TarInfo(name="pkg/escape")
        link_info.type = tarfile.LNKTYPE
        link_info.linkname = "../../etc-passwd-shadow"
        link_info.mode = 0o644
        tar.addfile(link_info)


def _build_in_bounds_tar(tar_path: str) -> None:
    """An archive whose hardlink stays inside the destination."""
    with tarfile.open(tar_path, "w") as tar:
        data = b"benign\n"
        info = tarfile.TarInfo(name="pkg/real")
        info.size = len(data)
        info.type = tarfile.REGTYPE
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))

        link_info = tarfile.TarInfo(name="pkg/inside")
        link_info.type = tarfile.LNKTYPE
        link_info.linkname = "pkg/real"
        link_info.mode = 0o644
        tar.addfile(link_info)


def _force_buggy_cpython(monkeypatch):
    """Make the unpacking module behave as if it were running on the buggy
    CPython patch versions: ``data_filter`` always raises
    ``LinkOutsideDestinationError`` for link members.
    """
    real_data_filter = tarfile.data_filter

    def fake_data_filter(member, dest_path):
        if member.islnk() or member.issym():
            raise tarfile.LinkOutsideDestinationError(member, member.linkname)
        return real_data_filter(member, dest_path)

    monkeypatch.setattr(unpacking.tarfile, "data_filter", fake_data_filter)
    monkeypatch.setattr(
        unpacking.sys, "version_info", (3, 11, 4, "final", 0)
    )


@pytest.mark.utils
def test_untar_file_blocks_escaping_hardlink_on_buggy_cpython(monkeypatch, tmp_path):
    """The core GHSA-p4qx-p8p6-4gjf check: even when ``data_filter`` triggers
    the ``LinkOutsideDestinationError`` fallback, an actually-out-of-bounds
    hardlink must still be rejected.
    """
    tar_path = tmp_path / "malicious.tar"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    _build_malicious_tar(str(tar_path), str(extract_dir))

    _force_buggy_cpython(monkeypatch)

    with pytest.raises(InstallationError) as exc_info:
        untar_file(str(tar_path), str(extract_dir))

    # The file must not have been extracted, and no link must have been
    # created outside the destination.
    assert not (extract_dir / "pkg" / "escape").exists()
    sibling = tmp_path / "etc-passwd-shadow"
    assert not sibling.exists()
    # Error message should mention the offending tarball.
    assert "malicious.tar" in str(exc_info.value)


@pytest.mark.utils
def test_untar_file_allows_in_bounds_hardlink_on_buggy_cpython(
    monkeypatch, tmp_path
):
    """The fallback must still succeed for the false-positive case the
    workaround was originally added for — a hardlink whose target really
    does stay inside the destination.
    """
    tar_path = tmp_path / "benign.tar"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    _build_in_bounds_tar(str(tar_path))

    _force_buggy_cpython(monkeypatch)

    untar_file(str(tar_path), str(extract_dir))

    # ``untar_file`` strips a single leading directory shared by all members
    # (so ``pkg/real`` lands at ``extract_dir/real``).
    assert (extract_dir / "real").is_file()
    # The hardlink must also have been created inside the extraction dir.
    assert (extract_dir / "inside").exists()


@pytest.mark.utils
def test_untar_file_blocks_escaping_hardlink_on_modern_cpython(tmp_path):
    """Sanity check on the platform we're running on: a malicious hardlink
    is rejected by ``data_filter`` itself, without involving the fallback.
    Only run when ``tarfile.data_filter`` is available (CPython ≥ 3.9.17).
    """
    if not hasattr(tarfile, "data_filter"):
        pytest.skip("CPython without tarfile.data_filter")

    tar_path = tmp_path / "malicious.tar"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    _build_malicious_tar(str(tar_path), str(extract_dir))

    # Force the runtime to *not* be considered buggy so the fallback is
    # never reached — exercises the default code path.
    real_version = sys.version_info[:3]
    if real_version in {(3, 9, 17), (3, 10, 12), (3, 11, 4)}:
        pytest.skip("Running on a CPython version with the data_filter bug")

    with pytest.raises(InstallationError):
        untar_file(str(tar_path), str(extract_dir))
    assert not (tmp_path / "etc-passwd-shadow").exists()
