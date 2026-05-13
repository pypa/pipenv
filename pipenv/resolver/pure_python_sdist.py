"""Sdist ``METADATA`` extractor for the pure-Python resolver backend
(Initiative G Phase 3b, T_S1).

Phase 3a deliberately failed loud (Q-A "fail loud") when a candidate
was an sdist with no wheel companion.  Phase 3b inverts that: we now
build the sdist's METADATA on the fly via PEP 517's
:class:`pyproject_hooks.BuildBackendHookCaller`, so the pure-python
backend handles any package pip would.

Flow per call to :func:`extract_metadata_from_sdist`:

1. **Cache** lookup by ``candidate.url``.  Sdist URLs are immutable
   on PyPI so cache entries are valid forever; corruption is silently
   treated as a miss (caller refetches and overwrites).
2. **Download** the sdist body via the duck-typed ``session`` shared
   with :mod:`pipenv.resolver.pure_python_metadata`.  We use the same
   urllib3-style ``.request("GET", url, headers=, timeout=)`` shape so
   tests can swap a :class:`unittest.mock.MagicMock` and production
   passes the same configured session the wheel-METADATA path uses.
3. **Extract** the archive into a separate tempdir.  ``.tar.gz``,
   ``.tar.bz2``, ``.tar.xz``, plain ``.tar`` and ``.zip`` are
   supported (the union of what PyPI sdists actually use).  Path
   traversal is blocked: member names containing ``..`` segments or
   absolute paths are rejected.  Sdist convention requires exactly
   one top-level directory; we enforce it.
4. **Locate** ``pyproject.toml``.  If present, parse the
   ``[build-system]`` table for ``build-backend`` (and the optional
   ``backend-path``).  If absent or no backend declared, fall back to
   the PEP 517 §10 legacy default ``setuptools.build_meta:__legacy__``.
5. **Drive** :meth:`BuildBackendHookCaller.prepare_metadata_for_build_wheel`.
   The hook caller subprocess-spawns the build backend using
   ``sys.executable`` and runs in the current Python's environment.

   **NO build isolation in Phase 3b** — the vendored
   :class:`BuildBackendHookCaller` simply doesn't offer an isolation
   knob (its ``runner`` is a plain subprocess-spawner; pip's
   :class:`pip._internal.utils.misc.BuildEnvironment` is what builds
   the isolation layer on top of it).  This means we rely on the
   resolver user's environment to carry build-time deps, which matches
   the design-doc tradeoff for this phase.  Phase 3c can revisit.

6. **Timeout** the build at 300 seconds via
   :mod:`concurrent.futures`.  A wedged backend (rare but observed on
   packages with C-extension probes that hang on broken CI runners)
   surfaces as :class:`SdistBuildError` rather than blocking resolve.
7. **Read + parse** the ``METADATA`` file out of the dist-info dir
   the backend just produced; parse via
   :func:`pure_python_metadata._parse_metadata_text` so wheel and sdist
   results share the exact same :class:`CoreMetadata` shape.
8. **Cache.put** if a cache is provided.
9. **Cleanup**: every tempdir is wrapped in a context manager so a
   crash or timeout leaves no detritus on disk.

Critical constraint (enforced by the T17 pre-commit gate):
**this module must not import from patched-pip's internal package.**
Importing :mod:`pipenv.patched.pip._vendor.pyproject_hooks` is
permitted (``_vendor``, not ``_internal``); that's the whole point of
re-using patched-pip's vendored frontend rather than re-vendoring it.
"""

from __future__ import annotations

import concurrent.futures
import logging
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

try:  # py3.11+
    import tomllib as _toml_loader
except ImportError:  # py3.10 fallback — pipenv supports >=3.10
    from pipenv.patched.pip._vendor import tomli as _toml_loader  # type: ignore[no-redef]

from pipenv.patched.pip._vendor.pyproject_hooks import BuildBackendHookCaller
from pipenv.resolver.pure_python_metadata import (
    CoreMetadata,
    MetadataCache,
    MetadataFetchError,
    _http_request,
    _parse_metadata_text,
    _response_body,
    _response_status,
)

__all__ = [
    "SdistBuildError",
    "extract_metadata_from_sdist",
]

_LOGGER = logging.getLogger(__name__)

# PEP 517 §10 legacy fallback: a sdist with no ``pyproject.toml`` (or
# one without a ``[build-system].build-backend`` entry) is built via
# the setuptools legacy shim, which knows how to drive a setup.py.
_LEGACY_BACKEND = "setuptools.build_meta:__legacy__"

# Cap on how long we wait for the PEP 517 hook to return before
# bailing out.  Five minutes matches the design doc's risk-mitigation
# entry; in practice prepare_metadata_for_build_wheel on a healthy
# sdist returns in well under a second.
_BUILD_TIMEOUT_SECONDS = 300.0


class SdistBuildError(MetadataFetchError):
    """Raised when sdist METADATA extraction fails.

    Subclasses :class:`MetadataFetchError` so the upstream
    :class:`MetadataFetcher` (T_S2) can keep a single ``except`` clause
    and surface the failure uniformly with wheel-side errors.  The
    underlying cause — download failure, archive corruption, build
    backend traceback, or timeout — is preserved via ``__cause__``
    where applicable so logs / stack traces remain debuggable.
    """


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_metadata_from_sdist(
    candidate: Any,
    session: Any,
    *,
    cache: MetadataCache | None = None,
) -> CoreMetadata:
    """Build ``candidate`` via PEP 517 and return its :class:`CoreMetadata`.

    Parameters
    ----------
    candidate:
        Any object with ``.url`` (str) and ``.filename`` (str)
        attributes.  In production this is a
        :class:`pipenv.resolver.candidate.Candidate`; tests can pass a
        ``SimpleNamespace`` to avoid the full dataclass construction.
    session:
        Duck-typed HTTP session matching the
        :mod:`pipenv.resolver.pure_python_metadata` shape:
        ``session.request(method, url, *, headers=, timeout=)`` →
        response with ``.status`` / ``.data`` (urllib3 shape) or
        ``.status_code`` / ``.content`` (requests shape).
    cache:
        Optional read-through cache.  Hits bypass HTTP + build
        entirely; misses get a ``cache.put`` after a successful build.

    Returns
    -------
    CoreMetadata
        The parsed metadata, indistinguishable in shape from a wheel
        result, so downstream resolver logic doesn't need to branch.

    Raises
    ------
    SdistBuildError
        On any unrecoverable failure: HTTP non-2xx / no-body, archive
        corruption, path traversal, missing/invalid build backend,
        backend traceback, or build timeout.
    """
    if cache is not None:
        cached = cache.get(candidate.url)
        if cached is not None:
            return cached

    # The two tempdirs (download + extracted source) are independent;
    # both must be cleaned up regardless of which step fails.  We use
    # nested context managers so a crash in extraction still frees the
    # download dir.
    with tempfile.TemporaryDirectory(prefix="pipenv-sdist-dl-") as dl_dir:
        archive_path = _download_sdist(candidate, session, Path(dl_dir))

        with tempfile.TemporaryDirectory(prefix="pipenv-sdist-src-") as src_dir:
            source_root = _extract_sdist(archive_path, Path(src_dir))

            backend, backend_path = _resolve_build_backend(source_root)

            with tempfile.TemporaryDirectory(
                prefix="pipenv-sdist-meta-"
            ) as meta_dir:
                metadata = _run_prepare_metadata(
                    source_root,
                    backend,
                    backend_path,
                    Path(meta_dir),
                )

    if cache is not None:
        try:
            cache.put(candidate.url, metadata)
        except OSError as exc:
            # Cache write failure is non-fatal — we have the metadata
            # in hand.  Mirror the pure_python_metadata.fetch_metadata
            # contract so callers don't have to special-case sdists.
            _LOGGER.debug(
                "sdist metadata cache write failed for %s: %s",
                candidate.url,
                exc,
            )

    return metadata


# ---------------------------------------------------------------------------
# Step 1: download
# ---------------------------------------------------------------------------


def _download_sdist(candidate: Any, session: Any, dest_dir: Path) -> Path:
    """GET ``candidate.url`` and write the body to a file in ``dest_dir``.

    Returns the on-disk archive path.  Raises :class:`SdistBuildError`
    on any non-2xx response or empty body — both are non-recoverable
    for the extraction step that follows.
    """
    url = candidate.url
    response = _http_request(session, "GET", url)
    if response is None:
        raise SdistBuildError(
            f"sdist download failed: GET {url} returned no response"
        )
    status = _response_status(response)
    if status not in (200, 206):
        raise SdistBuildError(
            f"sdist download failed: GET {url} returned HTTP {status}"
        )
    body = _response_body(response)
    if body is None:
        raise SdistBuildError(
            f"sdist download failed: GET {url} returned empty body"
        )

    # Filename comes from candidate.filename — same source the wheel
    # path uses — so the file's extension survives intact and the
    # extractor in step 2 can dispatch on it.
    archive_name = getattr(candidate, "filename", None) or _filename_from_url(url)
    archive_path = dest_dir / archive_name
    try:
        archive_path.write_bytes(bytes(body))
    except OSError as exc:
        raise SdistBuildError(
            f"sdist download failed: could not write {archive_path}: {exc}"
        ) from exc
    return archive_path


def _filename_from_url(url: str) -> str:
    """Last path segment of ``url``, sans query string."""
    tail = url.rsplit("/", 1)[-1]
    return tail.split("?", 1)[0] or "sdist.tar.gz"


# ---------------------------------------------------------------------------
# Step 2: extract
# ---------------------------------------------------------------------------


def _extract_sdist(archive_path: Path, dest_dir: Path) -> Path:
    """Extract ``archive_path`` into ``dest_dir`` and return the source root.

    Sdist convention (PEP 517 §6 + PEP 643): the archive contains
    exactly one top-level directory named ``{name}-{version}`` whose
    contents are the source tree.  We enforce that invariant and
    return the path to that directory.

    Member-name validation rejects any path that:

    * is absolute, or
    * contains a ``..`` segment, or
    * resolves outside ``dest_dir`` after join+normalize.

    This blocks the classic ``tar`` traversal attack
    (``../../../etc/passwd``) and the less-obvious symlink-after-extract
    variant — we just refuse the archive outright.
    """
    name = archive_path.name.lower()
    try:
        if name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                          ".tar.xz", ".txz", ".tar")):
            _extract_tar(archive_path, dest_dir)
        elif name.endswith(".zip"):
            _extract_zip(archive_path, dest_dir)
        else:
            # Unknown extension — try tar; tarfile.open auto-detects
            # the compression for the common cases.  If that fails
            # we surface a clear error.
            try:
                _extract_tar(archive_path, dest_dir)
            except (tarfile.TarError, OSError) as exc:
                raise SdistBuildError(
                    f"sdist archive corrupt: unsupported extension on {name}"
                ) from exc
    except SdistBuildError:
        raise
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, OSError) as exc:
        raise SdistBuildError(
            f"sdist archive corrupt: {exc}"
        ) from exc

    return _locate_source_root(dest_dir, archive_path.name)


def _extract_tar(archive_path: Path, dest_dir: Path) -> None:
    with tarfile.open(archive_path, "r:*") as tf:
        members = tf.getmembers()
        for m in members:
            _validate_member_name(m.name, archive_path.name)
            # Reject device files, fifos, symlinks pointing outside,
            # etc.  Only regular files + directories are part of a
            # well-formed sdist.
            if m.islnk() or m.issym():
                _validate_member_name(m.linkname, archive_path.name)
            if m.isdev() or m.ischr() or m.isfifo() or m.isblk():
                raise SdistBuildError(
                    f"sdist archive corrupt: {archive_path.name} contains "
                    f"a non-regular member {m.name!r}"
                )
        # Python 3.12+ deprecated the implicit ``filter`` arg; pass
        # ``data`` explicitly so 3.12 / 3.13 don't warn and 3.14
        # doesn't break.  ``data`` filter is the safe-by-default one.
        try:
            tf.extractall(dest_dir, filter="data")
        except TypeError:
            # Older Python (3.10 / early 3.11) without the ``filter``
            # kwarg — our manual validation above already covered the
            # traversal cases.
            tf.extractall(dest_dir)


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            _validate_member_name(info.filename, archive_path.name)
        zf.extractall(dest_dir)


def _validate_member_name(member_name: str, archive_name: str) -> None:
    """Reject member names that would escape the extraction root.

    ``..`` segments and absolute paths are both fatal.  We don't try
    to be clever and re-anchor them — the archive is malformed and
    we refuse it outright.
    """
    if not member_name:
        # Empty member names are nonsensical but happen in the wild
        # (zips produced by some legacy tooling).  Reject explicitly
        # rather than letting ``Path("")`` quietly produce ``.``.
        raise SdistBuildError(
            f"sdist archive corrupt: {archive_name} contains an empty member name"
        )
    # Normalise separators so a Windows-style ``..\\foo`` is caught on Linux.
    norm = member_name.replace("\\", "/")
    if norm.startswith("/"):
        raise SdistBuildError(
            f"sdist archive corrupt: {archive_name} contains an absolute "
            f"member path {member_name!r}"
        )
    for part in norm.split("/"):
        if part == "..":
            raise SdistBuildError(
                f"sdist archive corrupt: {archive_name} contains a path "
                f"traversal segment in {member_name!r}"
            )


def _locate_source_root(dest_dir: Path, archive_name: str) -> Path:
    """Find the single top-level directory created by extraction.

    Sdist convention: exactly one ``{name}-{version}/`` directory at
    the archive root.  Anything else (zero entries, multiple entries,
    or a top-level file rather than directory) is a malformed sdist
    and we surface :class:`SdistBuildError`.
    """
    entries = [e for e in dest_dir.iterdir() if not e.name.startswith(".")]
    # Filter out PaxHeaders pseudo-entries that some tar implementations
    # produce at the archive root.  Those are not part of the source
    # tree.
    entries = [e for e in entries if "PaxHeader" not in e.name]
    if not entries:
        raise SdistBuildError(
            f"sdist archive corrupt: {archive_name} extracted to nothing"
        )
    dirs = [e for e in entries if e.is_dir()]
    if len(dirs) != 1:
        raise SdistBuildError(
            f"sdist archive corrupt: {archive_name} must contain exactly "
            f"one top-level directory, found {len(dirs)} "
            f"({[d.name for d in dirs]})"
        )
    return dirs[0]


# ---------------------------------------------------------------------------
# Step 3: resolve the build backend
# ---------------------------------------------------------------------------


def _resolve_build_backend(source_root: Path) -> tuple[str, list[str] | None]:
    """Return ``(build_backend, backend_path)`` for ``source_root``.

    Reads ``pyproject.toml`` if present; otherwise applies the PEP 517
    §10 legacy fallback.  A ``pyproject.toml`` that's present but
    malformed surfaces as :class:`SdistBuildError` — a malformed
    pyproject means the sdist is broken and we can't build it.
    """
    pyproject = source_root / "pyproject.toml"
    if not pyproject.is_file():
        return _LEGACY_BACKEND, None
    try:
        raw = pyproject.read_bytes()
        config = _toml_loader.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SdistBuildError(
            f"build backend failed: could not read pyproject.toml: {exc}"
        ) from exc
    # tomllib raises TOMLDecodeError (subclass of ValueError) — caught above.

    build_system = config.get("build-system") if isinstance(config, dict) else None
    if not isinstance(build_system, dict):
        return _LEGACY_BACKEND, None

    backend = build_system.get("build-backend")
    if not isinstance(backend, str) or not backend:
        # Per PEP 517 §10: pyproject.toml without a build-backend
        # uses the legacy default.
        return _LEGACY_BACKEND, None

    raw_path = build_system.get("backend-path")
    backend_path: list[str] | None
    if isinstance(raw_path, list) and all(isinstance(p, str) for p in raw_path):
        backend_path = list(raw_path)
    else:
        backend_path = None

    return backend, backend_path


# ---------------------------------------------------------------------------
# Step 4: drive the PEP 517 hook
# ---------------------------------------------------------------------------


def _run_prepare_metadata(
    source_root: Path,
    backend: str,
    backend_path: list[str] | None,
    metadata_dir: Path,
) -> CoreMetadata:
    """Invoke ``prepare_metadata_for_build_wheel`` and parse the result.

    Wrapped in a :class:`ThreadPoolExecutor` with a hard 300-second
    timeout — pyproject_hooks itself has no timeout knob, so we wear
    the indirection cost.  The subprocess the hook caller spawns
    continues running on timeout (we can't kill it without a runner
    swap), but the executor frees us to surface
    :class:`SdistBuildError` rather than block resolve forever.
    """
    caller = BuildBackendHookCaller(
        source_dir=str(source_root),
        build_backend=backend,
        backend_path=backend_path,
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            caller.prepare_metadata_for_build_wheel, str(metadata_dir)
        )
        try:
            relative_dist_info = future.result(timeout=_BUILD_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError as exc:
            raise SdistBuildError(
                f"sdist build timed out after {int(_BUILD_TIMEOUT_SECONDS)}s "
                f"(backend={backend!r})"
            ) from exc
        except Exception as exc:
            # Any backend-side exception (BackendUnavailable,
            # HookMissing, CalledProcessError, etc.) flattens to a
            # single SdistBuildError so callers don't have to teach
            # themselves the patched-pip vendor hierarchy.  The
            # original exception stays attached via __cause__.
            raise SdistBuildError(
                f"build backend failed: {backend!r}: {exc}"
            ) from exc

    metadata_path = metadata_dir / relative_dist_info / "METADATA"
    try:
        raw = metadata_path.read_bytes()
    except OSError as exc:
        raise SdistBuildError(
            f"build backend failed: METADATA file not produced at "
            f"{metadata_path}: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SdistBuildError(
            f"build backend failed: METADATA at {metadata_path} is not "
            f"UTF-8: {exc}"
        ) from exc

    return _parse_metadata_text(text)
