"""Unit tests for :mod:`pipenv.resolver.pure_python_sdist`
(Initiative G Phase 3b, T_S1).

Coverage matrix from the plan brief:

1. Happy path with a hand-built synthetic sdist + setuptools legacy backend.
2. Cache round-trip (second call hits cache, not HTTP).
3. HTTP failure → ``SdistBuildError`` with ``download`` in the message.
4. Corrupt archive bytes → ``SdistBuildError`` with ``corrupt``.
5. Pyproject pointing at a non-existent build backend → ``SdistBuildError``
   with ``build backend failed``.
6. Sdist without pyproject.toml → legacy fallback path succeeds.
7. Path-traversal protection on tar member names.

The "happy path" tests really invoke setuptools, so they're a touch
slower than the wheel-METADATA unit tests; the repo has no ``slow``
marker convention so we accept the ~5 s runtime.

The session is a duck-typed :class:`unittest.mock.MagicMock` matching
the urllib3 shape :mod:`pipenv.resolver.pure_python_metadata` uses
(``.status`` / ``.data`` / ``.headers``).
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(*, status: int = 200, data: bytes = b"") -> MagicMock:
    """Build a urllib3-response-shaped mock."""
    response = MagicMock()
    response.status = status
    response.data = data
    response.headers = {}
    return response


def _make_session(response_bytes: bytes, *, status: int = 200) -> MagicMock:
    """Session whose ``request("GET", url, ...)`` returns ``response_bytes``."""
    session = MagicMock()
    session.request = MagicMock(
        return_value=_make_response(status=status, data=response_bytes)
    )
    return session


def _make_candidate(filename: str, *, url: str | None = None) -> SimpleNamespace:
    """Minimal candidate-shaped object — ``.url`` + ``.filename`` only."""
    actual_url = url or f"https://example.test/sdists/{filename}"
    return SimpleNamespace(url=actual_url, filename=filename)


def _build_sdist_tarball(
    *,
    pkg_name: str,
    version: str,
    pyproject_toml: bytes | None,
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    """Build a tar.gz sdist in memory.

    The archive contains a single top-level ``{pkg_name}-{version}/``
    directory.  When ``pyproject_toml`` is ``None`` the
    ``pyproject.toml`` is omitted (forcing the legacy fallback).
    """
    top = f"{pkg_name}-{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def add(name: str, payload: bytes) -> None:
            info = tarfile.TarInfo(name=f"{top}/{name}")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

        if pyproject_toml is not None:
            add("pyproject.toml", pyproject_toml)

        # PKG-INFO is what setuptools' legacy backend reads to extract
        # name/version when no setup.py is invoked; including it makes
        # the synthetic sdist a valid PEP 643 sdist.
        add(
            "PKG-INFO",
            (
                f"Metadata-Version: 2.1\n"
                f"Name: {pkg_name}\n"
                f"Version: {version}\n"
                f"Summary: synthetic test sdist\n"
            ).encode(),
        )

        # A setup.py is required by the legacy setuptools backend; for
        # PEP 517 backends that aren't legacy, callers can pass a
        # pyproject and skip setup.py via extra_files.
        if extra_files is None or "setup.py" not in extra_files:
            add(
                "setup.py",
                (
                    "from setuptools import setup\n"
                    f"setup(name={pkg_name!r}, version={version!r}, "
                    f"description='synthetic test sdist')\n"
                ).encode(),
            )

        # Source dir so the build doesn't produce an empty wheel.
        add(f"{pkg_name.replace('-', '_')}/__init__.py", b"")

        for name, payload in (extra_files or {}).items():
            add(name, payload)

    return buf.getvalue()


def _build_traversal_tarball() -> bytes:
    """Build a tarball containing a ``../etc/passwd`` member."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # First a normal directory so the archive looks plausible.
        info = tarfile.TarInfo(name="malicious-1.0/")
        info.type = tarfile.DIRTYPE
        tf.addfile(info)
        # Then the bad member.
        info = tarfile.TarInfo(name="../etc/passwd")
        payload = b"pwned"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Happy path — pyproject + setuptools.build_meta:__legacy__
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_extracts_metadata_via_setuptools_legacy_backend(self):
        from pipenv.resolver.pure_python_sdist import (
            extract_metadata_from_sdist,
        )

        # No pyproject — exercises the legacy fallback inside
        # _resolve_build_backend AND the legacy setuptools backend
        # itself (the most common shape for old PyPI sdists).
        sdist = _build_sdist_tarball(
            pkg_name="mypkg",
            version="1.0",
            pyproject_toml=None,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("mypkg-1.0.tar.gz")

        result = extract_metadata_from_sdist(candidate, session)

        assert result.name == "mypkg"
        assert result.version == "1.0"
        # Build-backend produces a real METADATA so Summary survives.
        assert result.summary == "synthetic test sdist"

    def test_extracts_metadata_from_zip_sdist(self):
        from pipenv.resolver.pure_python_sdist import (
            extract_metadata_from_sdist,
        )

        # Build a zip-format sdist (some legacy projects publish them).
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "zippkg-2.0/PKG-INFO",
                "Metadata-Version: 2.1\nName: zippkg\nVersion: 2.0\n",
            )
            zf.writestr(
                "zippkg-2.0/setup.py",
                "from setuptools import setup\nsetup(name='zippkg', version='2.0')\n",
            )
            zf.writestr("zippkg-2.0/zippkg/__init__.py", "")
        sdist = buf.getvalue()
        session = _make_session(sdist)
        candidate = _make_candidate("zippkg-2.0.zip")

        result = extract_metadata_from_sdist(candidate, session)

        assert result.name == "zippkg"
        assert result.version == "2.0"


# ---------------------------------------------------------------------------
# 2. Cache round-trip
# ---------------------------------------------------------------------------


class TestCacheRoundTrip:
    def test_second_call_hits_cache_not_http(self, tmp_path: Path):
        from pipenv.resolver.pure_python_metadata import MetadataCache
        from pipenv.resolver.pure_python_sdist import (
            extract_metadata_from_sdist,
        )

        sdist = _build_sdist_tarball(
            pkg_name="cachekit",
            version="0.1",
            pyproject_toml=None,
        )
        candidate = _make_candidate("cachekit-0.1.tar.gz")
        cache = MetadataCache(tmp_path / "metacache")

        # First call: real session + real build.
        session1 = _make_session(sdist)
        first = extract_metadata_from_sdist(candidate, session1, cache=cache)
        assert first.name == "cachekit"
        assert session1.request.call_count == 1

        # Second call: cache hit, the HTTP session should NEVER be
        # touched.  We pass a mock whose .request raises so any
        # accidental call would fail loudly.
        session2 = MagicMock()
        session2.request.side_effect = AssertionError("HTTP must not be called")
        second = extract_metadata_from_sdist(candidate, session2, cache=cache)
        assert second.name == "cachekit"
        assert second.version == "0.1"
        assert session2.request.call_count == 0


# ---------------------------------------------------------------------------
# 3. HTTP failure
# ---------------------------------------------------------------------------


class TestHttpFailure:
    def test_non_2xx_raises_sdist_build_error(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        session = _make_session(b"", status=404)
        candidate = _make_candidate("missing-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "download failed" in str(excinfo.value).lower()
        assert "404" in str(excinfo.value)

    def test_no_response_raises_sdist_build_error(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        # Session.request raises → _http_request swallows and returns None.
        session = MagicMock()
        session.request.side_effect = ConnectionError("boom")
        candidate = _make_candidate("offline-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "no response" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# 4. Corrupt archive
# ---------------------------------------------------------------------------


class TestCorruptArchive:
    def test_bogus_tarball_bytes_raise_corrupt(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        session = _make_session(b"this is not a tarball")
        candidate = _make_candidate("garbage-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "corrupt" in str(excinfo.value).lower()

    def test_unknown_extension_raises_corrupt(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        session = _make_session(b"random bytes that aren't an archive")
        candidate = _make_candidate("weird-1.0.weirdext")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "corrupt" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# 5. Build backend failure (non-existent backend)
# ---------------------------------------------------------------------------


class TestBackendFailure:
    def test_nonexistent_backend_raises(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        pyproject = (
            b"[build-system]\n"
            b"requires = []\n"
            b"build-backend = \"definitely_not_a_real_backend.module\"\n"
        )
        sdist = _build_sdist_tarball(
            pkg_name="badbackend",
            version="0.0.1",
            pyproject_toml=pyproject,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("badbackend-0.0.1.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        msg = str(excinfo.value).lower()
        assert "build backend failed" in msg
        # The backend name should appear in the error so users can
        # debug pyproject typos without re-extracting the sdist.
        assert "definitely_not_a_real_backend.module" in str(excinfo.value)

    def test_malformed_pyproject_raises(self, tmp_path: Path):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        # Invalid TOML — unclosed string.
        pyproject = b"[build-system\nrequires = ["
        sdist = _build_sdist_tarball(
            pkg_name="badtoml",
            version="0.1",
            pyproject_toml=pyproject,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("badtoml-0.1.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "pyproject.toml" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 6. No pyproject.toml → legacy fallback succeeds
# ---------------------------------------------------------------------------


class TestLegacyFallback:
    def test_pyproject_with_no_build_backend_uses_legacy(self):
        from pipenv.resolver.pure_python_sdist import (
            extract_metadata_from_sdist,
        )

        # pyproject.toml exists but declares no build-backend → PEP
        # 517 §10 says use legacy setuptools.  This is a separate
        # branch in _resolve_build_backend from "no pyproject at all".
        pyproject = b"[tool.somethingelse]\nkey = \"value\"\n"
        sdist = _build_sdist_tarball(
            pkg_name="legacypkg",
            version="3.2.1",
            pyproject_toml=pyproject,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("legacypkg-3.2.1.tar.gz")

        result = extract_metadata_from_sdist(candidate, session)
        assert result.name == "legacypkg"
        assert result.version == "3.2.1"


# ---------------------------------------------------------------------------
# 7. Path traversal protection
# ---------------------------------------------------------------------------


class TestPathTraversalProtection:
    def test_tar_member_with_dotdot_is_rejected(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        sdist = _build_traversal_tarball()
        session = _make_session(sdist)
        candidate = _make_candidate("malicious-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        msg = str(excinfo.value).lower()
        # Either "traversal" wording from our validator, or "corrupt"
        # if a later stage trips first — both surface a SdistBuildError
        # which is the contract.
        assert "corrupt" in msg or "traversal" in msg

    def test_absolute_path_member_is_rejected(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="/etc/passwd_steal")
            payload = b"steal"
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        sdist = buf.getvalue()
        session = _make_session(sdist)
        candidate = _make_candidate("absroot-1.0.tar.gz")

        with pytest.raises(SdistBuildError):
            extract_metadata_from_sdist(candidate, session)

    def test_zip_member_with_dotdot_is_rejected(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../escape.txt", "pwned")
        sdist = buf.getvalue()
        session = _make_session(sdist)
        candidate = _make_candidate("zipescape-1.0.zip")

        with pytest.raises(SdistBuildError):
            extract_metadata_from_sdist(candidate, session)


# ---------------------------------------------------------------------------
# Extra coverage: extraction-shape edge cases
# ---------------------------------------------------------------------------


class TestExtractionShape:
    def test_archive_with_no_top_level_dir_rejected(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        # A tarball that puts files at the root (no top-level dir) is
        # not a well-formed sdist.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="loose.txt")
            payload = b"not in a directory"
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        sdist = buf.getvalue()
        session = _make_session(sdist)
        candidate = _make_candidate("flat-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "corrupt" in str(excinfo.value).lower()

    def test_archive_with_multiple_top_level_dirs_rejected(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for d in ("first-1.0", "second-1.0"):
                info = tarfile.TarInfo(name=f"{d}/marker.txt")
                payload = b"hi"
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
        sdist = buf.getvalue()
        session = _make_session(sdist)
        candidate = _make_candidate("dual-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "exactly one" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Extra coverage: timeout via patched BuildBackendHookCaller
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_hook_caller_timeout_raises_sdist_build_error(self, monkeypatch):
        """Patch ``BuildBackendHookCaller`` to hang past the timeout."""
        from pipenv.resolver import pure_python_sdist
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        # Shrink the timeout dramatically so we don't pay 5 minutes.
        monkeypatch.setattr(pure_python_sdist, "_BUILD_TIMEOUT_SECONDS", 0.2)

        class _HangingCaller:
            def __init__(self, *args, **kwargs):
                pass

            def prepare_metadata_for_build_wheel(self, *args, **kwargs):
                import time

                # Sleep well past the timeout.
                time.sleep(5)
                return "never-returned"

        monkeypatch.setattr(
            pure_python_sdist, "BuildBackendHookCaller", _HangingCaller
        )

        sdist = _build_sdist_tarball(
            pkg_name="hangy",
            version="0.1",
            pyproject_toml=None,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("hangy-0.1.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "timed out" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Extra coverage: filename fallback when candidate has no .filename
# ---------------------------------------------------------------------------


class TestFilenameFallback:
    def test_candidate_without_filename_uses_url_tail(self):
        from pipenv.resolver.pure_python_sdist import (
            extract_metadata_from_sdist,
        )

        sdist = _build_sdist_tarball(
            pkg_name="urlpkg",
            version="0.5",
            pyproject_toml=None,
        )
        session = _make_session(sdist)
        candidate = SimpleNamespace(
            url="https://example.test/sdists/urlpkg-0.5.tar.gz",
            filename=None,
        )

        result = extract_metadata_from_sdist(candidate, session)
        assert result.name == "urlpkg"

    def test_filename_from_url_strips_query_string(self):
        from pipenv.resolver.pure_python_sdist import _filename_from_url

        assert (
            _filename_from_url("https://x.test/foo-1.0.tar.gz?token=abc")
            == "foo-1.0.tar.gz"
        )

    def test_filename_from_url_handles_empty_tail(self):
        from pipenv.resolver.pure_python_sdist import _filename_from_url

        # Trailing slash → empty tail → default fallback name.
        assert _filename_from_url("https://x.test/path/") == "sdist.tar.gz"


# ---------------------------------------------------------------------------
# Extra coverage: defensive error branches
# ---------------------------------------------------------------------------


class TestDefensiveBranches:
    def test_empty_response_body_raises(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        # Build a response whose .data attribute is None — _response_body
        # returns None and the download step bails out cleanly.
        response = MagicMock()
        response.status = 200
        response.data = None
        response.headers = {}
        # Strip .content too so the body helper can't fall back to it.
        del response.content
        session = MagicMock()
        session.request = MagicMock(return_value=response)
        candidate = _make_candidate("empty-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "empty body" in str(excinfo.value)

    def test_pyproject_with_non_string_backend_falls_back_to_legacy(
        self, tmp_path: Path
    ):
        from pipenv.resolver.pure_python_sdist import _resolve_build_backend

        # build-backend is an int — _resolve_build_backend should
        # return the legacy fallback rather than raise.
        (tmp_path / "pyproject.toml").write_bytes(
            b"[build-system]\nrequires=[]\nbuild-backend = 0\n"
        )
        backend, backend_path = _resolve_build_backend(tmp_path)
        assert backend == "setuptools.build_meta:__legacy__"
        assert backend_path is None

    def test_pyproject_with_backend_path_list_is_preserved(
        self, tmp_path: Path
    ):
        from pipenv.resolver.pure_python_sdist import _resolve_build_backend

        (tmp_path / "pyproject.toml").write_bytes(
            b'[build-system]\n'
            b'requires=[]\n'
            b'build-backend = "my.backend"\n'
            b'backend-path = ["sub"]\n'
        )
        (tmp_path / "sub").mkdir()
        backend, backend_path = _resolve_build_backend(tmp_path)
        assert backend == "my.backend"
        assert backend_path == ["sub"]

    def test_pyproject_with_invalid_backend_path_type_is_ignored(
        self, tmp_path: Path
    ):
        from pipenv.resolver.pure_python_sdist import _resolve_build_backend

        # backend-path is a string, not a list — we ignore it
        # defensively rather than crashing.
        (tmp_path / "pyproject.toml").write_bytes(
            b'[build-system]\n'
            b'requires=[]\n'
            b'build-backend = "my.backend"\n'
            b'backend-path = "not_a_list"\n'
        )
        backend, backend_path = _resolve_build_backend(tmp_path)
        assert backend == "my.backend"
        assert backend_path is None

    def test_empty_member_name_in_zip_rejected(self):
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        # Hand-craft a zip with an empty filename entry.  ZipFile lets
        # us write that.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("", b"empty name member")
        session = _make_session(buf.getvalue())
        candidate = _make_candidate("emptyname-1.0.zip")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "corrupt" in str(excinfo.value).lower()

    def test_build_backend_returns_missing_metadata_file(self, monkeypatch):
        """Patch the caller to claim success but produce no METADATA."""
        from pipenv.resolver import pure_python_sdist
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        class _LyingCaller:
            def __init__(self, *args, **kwargs):
                pass

            def prepare_metadata_for_build_wheel(self, metadata_directory):
                # Return a dist-info path that doesn't actually exist
                # on disk.  The post-call read will fail.
                return "ghost-1.0.dist-info"

        monkeypatch.setattr(
            pure_python_sdist, "BuildBackendHookCaller", _LyingCaller
        )

        sdist = _build_sdist_tarball(
            pkg_name="ghost",
            version="1.0",
            pyproject_toml=None,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("ghost-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "METADATA file not produced" in str(excinfo.value)

    def test_build_backend_emits_non_utf8_metadata(self, monkeypatch, tmp_path):
        """Patch the caller to produce a non-UTF-8 METADATA blob."""
        from pipenv.resolver import pure_python_sdist
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        class _BadEncodingCaller:
            def __init__(self, *args, **kwargs):
                pass

            def prepare_metadata_for_build_wheel(self, metadata_directory):
                dist_info = Path(metadata_directory) / "bad-1.0.dist-info"
                dist_info.mkdir()
                # 0xFF is not valid UTF-8 in a header position.
                (dist_info / "METADATA").write_bytes(b"\xff\xfe not utf-8")
                return "bad-1.0.dist-info"

        monkeypatch.setattr(
            pure_python_sdist, "BuildBackendHookCaller", _BadEncodingCaller
        )

        sdist = _build_sdist_tarball(
            pkg_name="bad",
            version="1.0",
            pyproject_toml=None,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("bad-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "not" in str(excinfo.value).lower() and "utf-8" in str(excinfo.value).lower()

    def test_cache_write_oserror_is_non_fatal(self, monkeypatch, tmp_path):
        """A failing cache write must not poison a successful build."""
        from pipenv.resolver.pure_python_metadata import MetadataCache
        from pipenv.resolver.pure_python_sdist import (
            extract_metadata_from_sdist,
        )

        sdist = _build_sdist_tarball(
            pkg_name="cachefail",
            version="0.1",
            pyproject_toml=None,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("cachefail-0.1.tar.gz")
        cache = MetadataCache(tmp_path / "metacache")

        def _explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(cache, "put", _explode)

        # The result is still returned despite the cache.put OSError.
        result = extract_metadata_from_sdist(candidate, session, cache=cache)
        assert result.name == "cachefail"

    def test_archive_write_oserror_surfaces_as_sdist_build_error(
        self, monkeypatch
    ):
        """Disk write failure during sdist download → SdistBuildError."""
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        sdist = _build_sdist_tarball(
            pkg_name="diskfull",
            version="0.1",
            pyproject_toml=None,
        )
        session = _make_session(sdist)
        candidate = _make_candidate("diskfull-0.1.tar.gz")

        real_write_bytes = Path.write_bytes

        def _explode(self: Path, data):
            if self.name == "diskfull-0.1.tar.gz":
                raise OSError("disk full")
            return real_write_bytes(self, data)

        monkeypatch.setattr(Path, "write_bytes", _explode)

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        assert "could not write" in str(excinfo.value)

    def test_tar_member_with_device_type_is_rejected(self):
        """Tar containing a block/char/fifo member → SdistBuildError."""
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            top = tarfile.TarInfo(name="evil-1.0/")
            top.type = tarfile.DIRTYPE
            tf.addfile(top)
            dev = tarfile.TarInfo(name="evil-1.0/devnull")
            dev.type = tarfile.CHRTYPE
            dev.devmajor = 1
            dev.devminor = 3
            tf.addfile(dev)

        session = _make_session(buf.getvalue())
        candidate = _make_candidate("evil-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        msg = str(excinfo.value).lower()
        assert "corrupt" in msg and "non-regular" in msg

    def test_tar_member_symlink_with_traversal_linkname_rejected(self):
        """Tar symlink whose linkname escapes the root → rejected."""
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            extract_metadata_from_sdist,
        )

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            top = tarfile.TarInfo(name="symlinky-1.0/")
            top.type = tarfile.DIRTYPE
            tf.addfile(top)
            link = tarfile.TarInfo(name="symlinky-1.0/bad")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../../etc/passwd"
            tf.addfile(link)

        session = _make_session(buf.getvalue())
        candidate = _make_candidate("symlinky-1.0.tar.gz")

        with pytest.raises(SdistBuildError) as excinfo:
            extract_metadata_from_sdist(candidate, session)
        # Path-traversal validation catches the linkname.
        assert "traversal" in str(excinfo.value).lower() or "absolute" in str(excinfo.value).lower()

    def test_archive_extracts_to_nothing_rejected(self, monkeypatch):
        """An archive that extracts to zero entries → SdistBuildError."""
        from pipenv.resolver.pure_python_sdist import (
            SdistBuildError,
            _locate_source_root,
        )

        # _locate_source_root inspects the destination dir; we hand it
        # an empty dir to exercise the "extracted to nothing" branch.
        empty = Path("/dev/shm/nonexistent-dir-for-empty-test")
        if empty.exists():
            for p in empty.iterdir():
                p.unlink()
        else:
            empty.mkdir(parents=True)
        try:
            with pytest.raises(SdistBuildError) as excinfo:
                _locate_source_root(empty, "empty-1.0.tar.gz")
            assert "extracted to nothing" in str(excinfo.value)
        finally:
            empty.rmdir()
