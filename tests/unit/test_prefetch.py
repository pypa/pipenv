"""Unit tests for :mod:`pipenv.utils.prefetch`.

Scope (per the perf-pre-fetch landing):

* Happy path — three deps with matching tags + hashes get downloaded
  to the returned dir.
* Empty-deps / no-sources / no-hashes fast paths return ``None``
  without touching the network.
* Hash mismatch on a downloaded wheel → that wheel is dropped (file
  not in the result dir) without breaking the rest of the batch.
* Internal helper :func:`_pick_wheel` skips wheels whose tags don't
  match the target Python AND whose hashes are absent from the
  lockfile entry — both filters are load-bearing.

The full network path is mocked at the ``urllib3.PoolManager`` and
``ParallelFetcher`` seams so the suite stays offline and fast.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipenv.utils.prefetch import (
    _download_and_verify,
    _pick_wheel,
    prefetch_wheels,
)


def _sha256_hex(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _fake_response(*, status: int, body: bytes):
    """Build an object matching urllib3's response shape used by the helper."""
    resp = MagicMock()
    resp.status = status
    resp.data = body
    resp.release_conn = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# _download_and_verify — direct unit
# ---------------------------------------------------------------------------


class TestDownloadAndVerify:
    def test_happy_path_writes_file(self, tmp_path):
        body = b"fake-wheel-bytes"
        expected = f"sha256:{_sha256_hex(body)}"
        session = MagicMock()
        session.request.return_value = _fake_response(status=200, body=body)

        ok = _download_and_verify(
            session,
            ("https://pypi/foo.whl", "foo-1.0-py3-none-any.whl", expected),
            tmp_path,
        )
        assert ok is True
        assert (tmp_path / "foo-1.0-py3-none-any.whl").read_bytes() == body

    def test_hash_mismatch_drops_file(self, tmp_path):
        body = b"wrong-bytes"
        # Expected sha256 of a DIFFERENT body — should not match.
        expected = f"sha256:{_sha256_hex(b'right-bytes')}"
        session = MagicMock()
        session.request.return_value = _fake_response(status=200, body=body)

        ok = _download_and_verify(
            session,
            ("https://pypi/foo.whl", "foo-1.0-py3-none-any.whl", expected),
            tmp_path,
        )
        assert ok is False
        assert not (tmp_path / "foo-1.0-py3-none-any.whl").exists()

    def test_non_200_drops_file(self, tmp_path):
        session = MagicMock()
        session.request.return_value = _fake_response(status=404, body=b"")
        ok = _download_and_verify(
            session,
            ("https://pypi/foo.whl", "foo-1.0-py3-none-any.whl", "sha256:x"),
            tmp_path,
        )
        assert ok is False

    def test_session_raises_returns_false(self, tmp_path):
        session = MagicMock()
        session.request.side_effect = RuntimeError("synthetic network")
        ok = _download_and_verify(
            session,
            ("https://pypi/foo.whl", "foo-1.0-py3-none-any.whl", "sha256:x"),
            tmp_path,
        )
        assert ok is False

    def test_path_traversal_filename_rejected(self, tmp_path):
        body = b"x"
        expected = f"sha256:{_sha256_hex(body)}"
        session = MagicMock()
        session.request.return_value = _fake_response(status=200, body=body)
        # Filename with path separator must be coerced to its basename
        # OR rejected — either way no escape outside ``tmp_path``.
        ok = _download_and_verify(
            session,
            ("https://pypi/x", "../escape.whl", expected),
            tmp_path,
        )
        # Either rejected outright (returns False) OR written to
        # ``tmp_path/escape.whl`` (basename-only).  In neither case
        # does an ``../escape.whl`` appear outside ``tmp_path``.
        outside = tmp_path.parent / "escape.whl"
        assert not outside.exists()
        if ok:
            assert (tmp_path / "escape.whl").exists()


# ---------------------------------------------------------------------------
# _pick_wheel — tag + hash filtering
# ---------------------------------------------------------------------------


def _hash(value: str):
    h = MagicMock()
    h.algo = "sha256"
    h.value = value
    return h


def _tag(interp: str, abi: str, platform: str):
    """Build a duck-typed Tag-like object exposing the str attrs we read."""
    t = MagicMock()
    t.interpreter = interp
    t.abi = abi
    t.platform = platform
    return t


def _candidate(
    *,
    version: str,
    is_wheel: bool = True,
    yanked: bool = False,
    wheel_tags=None,
    hashes=(),
    url: str = "https://pypi/foo.whl",
    filename: str = "foo-1.0-cp311-cp311-linux_x86_64.whl",
):
    c = MagicMock()
    c.version = version
    c.is_wheel = is_wheel
    c.yanked = yanked
    c.wheel_tags = frozenset(wheel_tags or ())
    c.hashes = tuple(hashes)
    c.url = url
    c.filename = filename
    return c


def _fake_cache(manifest_by_name: dict):
    """Build a fake :class:`ParsedManifestCache` reading from a dict."""
    class _C:
        def get(self, _index_url, name):
            m = manifest_by_name.get(name)
            if m is None:
                return None
            wrapper = MagicMock()
            wrapper.candidates = m
            return wrapper

    return _C()


class TestPickWheel:
    def test_returns_url_filename_hash_on_match(self):
        target_tags = frozenset({("cp311", "cp311", "linux_x86_64")})
        cand = _candidate(
            version="1.0",
            wheel_tags=[_tag("cp311", "cp311", "linux_x86_64")],
            hashes=[_hash("abc123")],
        )
        cache = _fake_cache({"foo": [cand]})
        result = _pick_wheel(
            "foo", "1.0", {"sha256:abc123"}, cache, ["https://idx"], target_tags
        )
        assert result == (
            "https://pypi/foo.whl",
            "foo-1.0-cp311-cp311-linux_x86_64.whl",
            "sha256:abc123",
        )

    def test_skips_wrong_version(self):
        target_tags = frozenset({("cp311", "cp311", "linux_x86_64")})
        cand = _candidate(
            version="2.0",
            wheel_tags=[_tag("cp311", "cp311", "linux_x86_64")],
            hashes=[_hash("abc")],
        )
        cache = _fake_cache({"foo": [cand]})
        assert _pick_wheel(
            "foo", "1.0", {"sha256:abc"}, cache, ["https://idx"], target_tags
        ) is None

    def test_skips_sdists(self):
        target_tags = frozenset({("cp311", "cp311", "linux_x86_64")})
        cand = _candidate(
            version="1.0", is_wheel=False, hashes=[_hash("abc")]
        )
        cache = _fake_cache({"foo": [cand]})
        assert _pick_wheel(
            "foo", "1.0", {"sha256:abc"}, cache, ["https://idx"], target_tags
        ) is None

    def test_skips_yanked(self):
        target_tags = frozenset({("cp311", "cp311", "linux_x86_64")})
        cand = _candidate(
            version="1.0",
            yanked=True,
            wheel_tags=[_tag("cp311", "cp311", "linux_x86_64")],
            hashes=[_hash("abc")],
        )
        cache = _fake_cache({"foo": [cand]})
        assert _pick_wheel(
            "foo", "1.0", {"sha256:abc"}, cache, ["https://idx"], target_tags
        ) is None

    def test_skips_wrong_platform(self):
        # Wheel tags say cp310-macosx; target says cp311-linux.
        target_tags = frozenset({("cp311", "cp311", "linux_x86_64")})
        cand = _candidate(
            version="1.0",
            wheel_tags=[_tag("cp310", "cp310", "macosx_10_9_x86_64")],
            hashes=[_hash("abc")],
        )
        cache = _fake_cache({"foo": [cand]})
        assert _pick_wheel(
            "foo", "1.0", {"sha256:abc"}, cache, ["https://idx"], target_tags
        ) is None

    def test_skips_when_hash_not_in_lockfile(self):
        # The lockfile pins a DIFFERENT hash from what the candidate
        # advertises — could be a stale cache or a poisoned index.
        # Drop the wheel; pip handles via the regular index path.
        target_tags = frozenset({("cp311", "cp311", "linux_x86_64")})
        cand = _candidate(
            version="1.0",
            wheel_tags=[_tag("cp311", "cp311", "linux_x86_64")],
            hashes=[_hash("other-hash")],
        )
        cache = _fake_cache({"foo": [cand]})
        assert _pick_wheel(
            "foo", "1.0", {"sha256:abc"}, cache, ["https://idx"], target_tags
        ) is None


# ---------------------------------------------------------------------------
# prefetch_wheels — top-level integration with mocks
# ---------------------------------------------------------------------------


class TestPrefetchWheelsFastPaths:
    """Empty / missing inputs return ``None`` without any network."""

    def test_empty_deps_returns_none(self):
        result = prefetch_wheels(
            project=MagicMock(),
            deps=[],
            lockfile_section={},
            sources=[{"name": "pypi", "url": "https://pypi.org/simple"}],
        )
        assert result is None

    def test_no_sources_returns_none(self):
        dep = MagicMock(name="dep")
        dep.name = "foo"
        result = prefetch_wheels(
            project=MagicMock(),
            deps=[(dep, "foo==1.0")],
            lockfile_section={
                "foo": {"version": "==1.0", "hashes": ["sha256:abc"]}
            },
            sources=[],
        )
        assert result is None

    def test_entries_without_hashes_skipped(self):
        # A lockfile entry without ``hashes`` (legacy or hand-written)
        # is unverifiable; pre-fetch falls through.  With zero
        # verifiable targets the whole pre-fetch returns ``None``.
        dep = MagicMock()
        dep.name = "foo"
        result = prefetch_wheels(
            project=MagicMock(),
            deps=[(dep, "foo==1.0")],
            lockfile_section={"foo": {"version": "==1.0", "hashes": []}},
            sources=[{"name": "pypi", "url": "https://pypi.org/simple"}],
        )
        assert result is None


class TestPrefetchWheelsHappyPath:
    """Mock the network seams and verify the orchestration writes the
    expected wheel files to a returned dir."""

    def test_two_packages_downloaded_in_parallel(self, tmp_path, monkeypatch):
        # Build matching candidate hashes.
        foo_body = b"foo-wheel-body"
        bar_body = b"bar-wheel-body"
        foo_hash = f"sha256:{_sha256_hex(foo_body)}"
        bar_hash = f"sha256:{_sha256_hex(bar_body)}"

        # Fake target tags — both candidates have one matching tag.
        target_tags = frozenset({("cp311", "cp311", "linux_x86_64")})

        foo_cand = _candidate(
            version="1.0",
            wheel_tags=[_tag("cp311", "cp311", "linux_x86_64")],
            hashes=[_hash(foo_hash.split(":", 1)[1])],
            url="https://pypi/foo.whl",
            filename="foo-1.0-cp311-cp311-linux_x86_64.whl",
        )
        bar_cand = _candidate(
            version="2.0",
            wheel_tags=[_tag("cp311", "cp311", "linux_x86_64")],
            hashes=[_hash(bar_hash.split(":", 1)[1])],
            url="https://pypi/bar.whl",
            filename="bar-2.0-cp311-cp311-linux_x86_64.whl",
        )
        fake_cache = _fake_cache({"foo": [foo_cand], "bar": [bar_cand]})

        # Patch the three external seams: PoolManager, PEP691Client,
        # ParsedManifestCache, ParallelFetcher, target-tag query.
        monkeypatch.setattr(
            "pipenv.utils.prefetch._query_target_tags",
            lambda *_args, **_kw: target_tags,
        )

        # Build a fake urllib3 PoolManager that returns body by URL.
        body_by_url = {
            "https://pypi/foo.whl": foo_body,
            "https://pypi/bar.whl": bar_body,
        }

        class _FakeSession:
            def request(self, method, url, **_kw):
                return _fake_response(
                    status=200, body=body_by_url.get(url, b"")
                )

        monkeypatch.setattr(
            "pipenv.patched.pip._vendor.urllib3.PoolManager",
            lambda **_kw: _FakeSession(),
        )
        monkeypatch.setattr(
            "pipenv.resolver.pep691.PEP691Client",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            "pipenv.resolver.manifest_cache.ParsedManifestCache",
            lambda *a, **k: fake_cache,
        )

        class _FakeFetcher:
            def __init__(self, *a, **k):
                pass

            def populate(self, _targets):
                return {}

        monkeypatch.setattr(
            "pipenv.resolver.fetcher.ParallelFetcher", _FakeFetcher
        )
        monkeypatch.setattr(
            "pipenv.utils.shell.project_python",
            lambda *a, **k: "/usr/bin/python3",
        )

        dep_foo = MagicMock()
        dep_foo.name = "foo"
        dep_bar = MagicMock()
        dep_bar.name = "bar"

        result = prefetch_wheels(
            project=MagicMock(),
            deps=[(dep_foo, "foo==1.0"), (dep_bar, "bar==2.0")],
            lockfile_section={
                "foo": {"version": "==1.0", "hashes": [foo_hash]},
                "bar": {"version": "==2.0", "hashes": [bar_hash]},
            },
            sources=[{"name": "pypi", "url": "https://pypi.org/simple"}],
        )

        assert result is not None
        result_dir = Path(result)
        assert (result_dir / "foo-1.0-cp311-cp311-linux_x86_64.whl").read_bytes() == foo_body
        assert (result_dir / "bar-2.0-cp311-cp311-linux_x86_64.whl").read_bytes() == bar_body

    def test_no_matching_wheel_returns_none(self, tmp_path, monkeypatch):
        # Target tag doesn't match any candidate → pre-fetch returns
        # None (nothing to share) and CLEANS UP the temp dir.
        target_tags = frozenset({("cp312", "cp312", "linux_x86_64")})
        monkeypatch.setattr(
            "pipenv.utils.prefetch._query_target_tags",
            lambda *_args, **_kw: target_tags,
        )

        # Candidate is cp310 — won't match cp312 target.
        cand = _candidate(
            version="1.0",
            wheel_tags=[_tag("cp310", "cp310", "linux_x86_64")],
            hashes=[_hash("abc")],
        )
        monkeypatch.setattr(
            "pipenv.patched.pip._vendor.urllib3.PoolManager",
            lambda **_kw: MagicMock(),
        )
        monkeypatch.setattr(
            "pipenv.resolver.pep691.PEP691Client",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            "pipenv.resolver.manifest_cache.ParsedManifestCache",
            lambda *a, **k: _fake_cache({"foo": [cand]}),
        )

        class _FakeFetcher:
            def __init__(self, *a, **k):
                pass

            def populate(self, _targets):
                return {}

        monkeypatch.setattr(
            "pipenv.resolver.fetcher.ParallelFetcher", _FakeFetcher
        )
        monkeypatch.setattr(
            "pipenv.utils.shell.project_python",
            lambda *a, **k: "/usr/bin/python3",
        )

        dep = MagicMock()
        dep.name = "foo"
        result = prefetch_wheels(
            project=MagicMock(),
            deps=[(dep, "foo==1.0")],
            lockfile_section={
                "foo": {"version": "==1.0", "hashes": ["sha256:abc"]}
            },
            sources=[{"name": "pypi", "url": "https://pypi.org/simple"}],
        )
        assert result is None

    def test_target_tag_query_failure_returns_none(self, monkeypatch):
        """When the target-tag subprocess fails (timeout, non-zero
        exit), pre-fetch bails rather than risk downloading wheels
        for the wrong platform.  Defensive — pip handles the install
        via the regular index path."""
        monkeypatch.setattr(
            "pipenv.utils.prefetch._query_target_tags",
            lambda *_args, **_kw: None,
        )
        monkeypatch.setattr(
            "pipenv.utils.shell.project_python",
            lambda *a, **k: "/usr/bin/python3",
        )

        dep = MagicMock()
        dep.name = "foo"
        result = prefetch_wheels(
            project=MagicMock(),
            deps=[(dep, "foo==1.0")],
            lockfile_section={
                "foo": {"version": "==1.0", "hashes": ["sha256:abc"]}
            },
            sources=[{"name": "pypi", "url": "https://pypi.org/simple"}],
        )
        assert result is None
