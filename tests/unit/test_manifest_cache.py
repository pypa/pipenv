"""Unit tests for :mod:`pipenv.resolver.manifest_cache` (Initiative G phase 1, T14).

Covers the full public + internal surface of ``ParsedManifestCache`` and its
``CachedManifest`` envelope:

* Round-trip + basic API (``put`` / ``get`` / ``invalidate`` / ``clear_all``)
* TTL expiry (immediate + clock-advanced)
* Schema versioning (constructor mismatch + on-disk ``schema_version``)
* Atomic-write semantics under ``os.replace`` failure
* No ``.tmp`` litter on the success path
* Concurrent reader-vs-writer (no partial reads, never raises)
* Concurrent writer-vs-writer (last-rename-wins, no corruption)
* URL hashing isolation (no cross-contamination between distinct URLs)
* Corruption robustness (raw-byte writes, missing keys, wrong-typed keys)
* Candidate (de)serialisation round-trip with every field populated

This module owns the full test surface for ``pipenv/resolver/manifest_cache.py``
and targets >=95% line coverage of that module.

T7 contract notes folded into these tests (per the T7 implementer's hand-off):

* Cache root is caller-supplied (no default), so every test uses ``tmp_path``.
* Full sha256 (64 chars) is used in the on-disk path, not a truncation.
* ``datetime.now(timezone.utc)`` can produce equal timestamps on fast
  hardware, so the writer-vs-writer test asserts "either payload is
  acceptable" rather than "the chronologically-later cached_at wins".
* ``get()`` swallows ``json.JSONDecodeError``, ``UnicodeDecodeError``,
  missing keys, wrong-typed keys, and bad ISO timestamps as misses —
  corruption tests therefore write raw bytes via ``target.write_bytes(...)``
  rather than round-tripping JSON.
* ``put`` failure path may legitimately leave one ``<target>.<rand>.tmp``
  file behind (the docstring documents the cleanup race), so the
  no-litter assertion applies only to the success path.
* Deterministic serialisation: hashes serialise as sorted lists; wheel_tags
  serialise as sorted ``str(tag)`` list; the JSON round-trip uses cached
  ``wheel_tags`` directly so payloads stay bit-stable across
  ``packaging.tags`` upgrades.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pipenv.resolver.candidate import Candidate, Hash
from pipenv.resolver.manifest_cache import (
    CachedManifest,
    ParsedManifestCache,
    _candidate_from_json,
    _candidate_to_json,
    _datetime_from_iso,
    _datetime_to_iso,
)
from pipenv.vendor.packaging.tags import Tag, parse_tag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wheel_candidate(
    name: str = "numpy",
    version: str = "1.26.0",
    *,
    filename: str | None = None,
    url: str | None = None,
    hashes: frozenset[Hash] | None = None,
) -> Candidate:
    """Build a wheel ``Candidate`` via ``from_filename`` (drives wheel_tags)."""
    fn = filename or f"{name}-{version}-py3-none-any.whl"
    return Candidate.from_filename(
        fn,
        name=name,
        version=version,
        url=url or f"https://example.org/simple/{name}/{fn}",
        hashes=hashes if hashes is not None else frozenset(),
        requires_python=">=3.9",
        yanked=False,
        yanked_reason=None,
        upload_time=None,
    )


def _make_sdist_candidate(
    name: str = "numpy",
    version: str = "1.26.0",
) -> Candidate:
    fn = f"{name}-{version}.tar.gz"
    return Candidate(
        name=name,
        version=version,
        url=f"https://example.org/simple/{name}/{fn}",
        filename=fn,
        hashes=frozenset(),
        requires_python=None,
        yanked=False,
        yanked_reason=None,
        upload_time=None,
        is_wheel=False,
        wheel_tags=None,
    )


# ---------------------------------------------------------------------------
# Round-trip + basic API
# ---------------------------------------------------------------------------


class TestRoundTripBasicAPI:
    def test_put_then_get_returns_equivalent_manifest(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate(
            hashes=frozenset({Hash("sha256", "deadbeef" * 8)}),
        )
        before = datetime.now(timezone.utc)
        cache.put(
            "https://pypi.org/simple",
            "numpy",
            [cand],
            etag='W/"abc123"',
            ttl_seconds=600,
        )
        after = datetime.now(timezone.utc)

        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert isinstance(result, CachedManifest)
        assert result.candidates == (cand,)
        assert result.etag == 'W/"abc123"'
        # cached_at sits between the before/after timestamps we recorded
        # around the put() call.
        assert before <= result.cached_at <= after
        # expires_at == cached_at + ttl_seconds (per docstring).
        assert result.expires_at == result.cached_at + timedelta(seconds=600)

    def test_get_returns_none_when_never_put(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_get_returns_none_after_invalidate(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        assert cache.get("https://pypi.org/simple", "numpy") is not None

        cache.invalidate("https://pypi.org/simple", "numpy")
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_invalidate_missing_entry_is_a_noop(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        # No put performed.  Must not raise.
        cache.invalidate("https://pypi.org/simple", "numpy")

    def test_clear_all_removes_entire_versioned_subtree(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        cache.put("https://pypi.org/simple", "requests", [cand], etag=None)

        versioned_root = tmp_path / f"manifests-v{ParsedManifestCache.SCHEMA_VERSION}"
        assert versioned_root.exists()

        cache.clear_all()
        assert not versioned_root.exists()

        # And put() afterwards must succeed (parent dir recreated).
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        assert cache.get("https://pypi.org/simple", "numpy") is not None

    def test_clear_all_on_empty_cache_is_a_noop(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cache.clear_all()  # must not raise even when nothing exists

    def test_put_overwrites_previous_entry(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        c1 = _make_wheel_candidate(name="numpy", version="1.26.0")
        c2 = _make_wheel_candidate(name="numpy", version="1.27.0")
        cache.put("https://pypi.org/simple", "numpy", [c1], etag="v1")
        cache.put("https://pypi.org/simple", "numpy", [c2], etag="v2")

        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert result.candidates == (c2,)
        assert result.etag == "v2"

    def test_canonicalises_package_name_on_path(self, tmp_path):
        """``Foo_Bar`` and ``foo-bar`` map to the same on-disk file."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate(name="foo-bar", version="1.0")
        cache.put("https://pypi.org/simple", "Foo_Bar", [cand], etag=None)
        # Round-trip with a differently-spelt package name resolves to
        # the same file via canonicalize_name.
        result = cache.get("https://pypi.org/simple", "foo-bar")
        assert result is not None
        assert result.candidates == (cand,)

    def test_etag_none_round_trips(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert result.etag is None


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


class TestTTLExpiry:
    def test_ttl_negative_immediately_expires(self, tmp_path):
        """``ttl_seconds=-1`` => expires_at < cached_at, get returns None."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put(
            "https://pypi.org/simple", "numpy", [cand], etag=None, ttl_seconds=-1,
        )
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_ttl_zero_immediately_expires(self, tmp_path):
        """``ttl_seconds=0`` => expires_at == cached_at, get returns None.

        The contract in ``get`` checks ``now >= expires_at``, so a
        zero-TTL payload is unreadable on the very next call regardless
        of clock granularity (``now`` is strictly later or equal).
        """
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put(
            "https://pypi.org/simple", "numpy", [cand], etag=None, ttl_seconds=0,
        )
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_ttl_within_window_returns_manifest(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put(
            "https://pypi.org/simple", "numpy", [cand], etag=None, ttl_seconds=600,
        )
        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert result.candidates == (cand,)

    def test_ttl_expires_after_clock_advances(self, tmp_path, monkeypatch):
        """Advance ``datetime.now`` past ``expires_at`` => get returns None."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put(
            "https://pypi.org/simple", "numpy", [cand], etag=None, ttl_seconds=60,
        )
        # Read back: still fresh.
        assert cache.get("https://pypi.org/simple", "numpy") is not None

        # Now patch ``datetime.now`` inside the module to return a value
        # 1 hour in the future, well past the 60-second TTL.
        import pipenv.resolver.manifest_cache as mc

        future = datetime.now(timezone.utc) + timedelta(hours=1)

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return future

        monkeypatch.setattr(mc, "datetime", _FakeDatetime)
        assert cache.get("https://pypi.org/simple", "numpy") is None


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------


class TestSchemaVersioning:
    def test_different_schema_version_uses_different_root(self, tmp_path):
        """v1 and v2 caches do not share an on-disk path."""
        c1 = ParsedManifestCache(tmp_path, schema_version=1)
        c2 = ParsedManifestCache(tmp_path, schema_version=2)
        cand = _make_wheel_candidate()
        c1.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        # v2 cache cannot see v1's entry.
        assert c2.get("https://pypi.org/simple", "numpy") is None
        # And v1 cache can still see its own entry.
        assert c1.get("https://pypi.org/simple", "numpy") is not None

    def test_on_disk_schema_mismatch_returns_none(self, tmp_path):
        """A payload with ``schema_version=99`` is silently treated as a miss."""
        cache = ParsedManifestCache(tmp_path, schema_version=1)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        # Locate the on-disk file and rewrite its schema_version field.
        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        payload["schema_version"] = 99
        target.write_text(json.dumps(payload))

        assert cache.get("https://pypi.org/simple", "numpy") is None


# ---------------------------------------------------------------------------
# Atomic write under failure
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_os_replace_failure_preserves_previous_payload(
        self, tmp_path, monkeypatch,
    ):
        cache = ParsedManifestCache(tmp_path)
        original = _make_wheel_candidate(name="numpy", version="1.26.0")
        cache.put("https://pypi.org/simple", "numpy", [original], etag="orig")
        before = cache.get("https://pypi.org/simple", "numpy")
        assert before is not None and before.candidates == (original,)

        # Patch os.replace inside the module to always raise OSError.
        import pipenv.resolver.manifest_cache as mc

        def _boom(src, dst):  # noqa: ARG001
            raise OSError("simulated rename failure")

        monkeypatch.setattr(mc.os, "replace", _boom)

        new = _make_wheel_candidate(name="numpy", version="1.27.0")
        with pytest.raises(OSError, match="simulated rename failure"):
            cache.put("https://pypi.org/simple", "numpy", [new], etag="new")

        # Previous payload is still readable and unchanged.
        after = cache.get("https://pypi.org/simple", "numpy")
        assert after is not None
        assert after.candidates == (original,)
        assert after.etag == "orig"

    def test_os_replace_failure_then_unlink_failure_still_propagates(
        self, tmp_path, monkeypatch,
    ):
        """Cleanup ``os.unlink`` failure must not mask the original OSError.

        Exercises the ``except OSError: pass`` branch in put()'s cleanup.
        """
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()

        import pipenv.resolver.manifest_cache as mc

        def _boom_replace(src, dst):  # noqa: ARG001
            raise OSError("replace failed")

        def _boom_unlink(path):  # noqa: ARG001
            raise OSError("unlink also failed")

        monkeypatch.setattr(mc.os, "replace", _boom_replace)
        monkeypatch.setattr(mc.os, "unlink", _boom_unlink)

        with pytest.raises(OSError, match="replace failed"):
            cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

    def test_no_tmp_litter_on_success_path(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        for i in range(100):
            cand = _make_wheel_candidate(name=f"pkg{i}", version=f"1.{i}.0")
            cache.put("https://pypi.org/simple", f"pkg{i}", [cand], etag=None)

        versioned_root = tmp_path / f"manifests-v{ParsedManifestCache.SCHEMA_VERSION}"
        tmp_files = list(versioned_root.rglob("*.tmp*"))
        assert tmp_files == [], f"unexpected tmp litter: {tmp_files}"


# ---------------------------------------------------------------------------
# Concurrent reader-vs-writer
# ---------------------------------------------------------------------------


class TestConcurrentReaderVsWriter:
    def test_reader_never_sees_partial_payload(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        # Pre-seed so reads can succeed before the first write completes.
        seed = _make_wheel_candidate(name="numpy", version="0.0.0")
        cache.put("https://pypi.org/simple", "numpy", [seed], etag="seed")

        stop_event = threading.Event()
        reader_errors: list[BaseException] = []
        reads_succeeded = [0]

        # Build a few distinct payloads the writer will cycle through.
        writer_payloads = [
            [_make_wheel_candidate(name="numpy", version=f"1.{i}.0")]
            for i in range(20)
        ]

        def writer():
            try:
                while not stop_event.is_set():
                    for payload in writer_payloads:
                        if stop_event.is_set():
                            return
                        cache.put(
                            "https://pypi.org/simple",
                            "numpy",
                            payload,
                            etag=f"v-{payload[0].version}",
                        )
                        time.sleep(0.001)
            except BaseException as exc:  # pragma: no cover
                reader_errors.append(exc)

        def reader():
            try:
                while not stop_event.is_set():
                    got = cache.get("https://pypi.org/simple", "numpy")
                    # Reader either sees None (briefly, if a write
                    # interleaved oddly) or a fully-valid CachedManifest.
                    if got is not None:
                        assert isinstance(got, CachedManifest)
                        # Touch each field to ensure full parse worked.
                        assert isinstance(got.candidates, tuple)
                        assert all(
                            isinstance(c, Candidate) for c in got.candidates
                        )
                        reads_succeeded[0] += 1
            except BaseException as exc:
                reader_errors.append(exc)

        threads = [
            threading.Thread(target=writer, daemon=True),
            threading.Thread(target=reader, daemon=True),
        ]
        for t in threads:
            t.start()
        time.sleep(0.1)  # ~100ms of concurrent activity
        stop_event.set()
        for t in threads:
            t.join(timeout=5)

        assert reader_errors == []
        assert reads_succeeded[0] > 0, (
            "reader should have completed at least one successful read"
        )


# ---------------------------------------------------------------------------
# Concurrent writer-vs-writer
# ---------------------------------------------------------------------------


class TestConcurrentWriterVsWriter:
    def test_simultaneous_writes_yield_one_of_two_payloads(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand_a = _make_wheel_candidate(name="numpy", version="1.26.0")
        cand_b = _make_wheel_candidate(name="numpy", version="1.27.0")

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def writer(cand: Candidate, etag: str):
            try:
                barrier.wait(timeout=5)
                cache.put(
                    "https://pypi.org/simple", "numpy", [cand], etag=etag,
                )
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(cand_a, "etag-a")),
            threading.Thread(target=writer, args=(cand_b, "etag-b")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []

        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        # The final on-disk state must be exactly one of the two payloads
        # (last-os.replace-wins — but we cannot observe ordering, so
        # either is acceptable per T7's hand-off note).
        assert result.candidates in {(cand_a,), (cand_b,)}
        assert result.etag in {"etag-a", "etag-b"}

        # The candidates and etag must come from the same write
        # (no Frankenstein payload).
        if result.candidates == (cand_a,):
            assert result.etag == "etag-a"
        else:
            assert result.etag == "etag-b"

        # No .tmp litter on the success path.
        versioned_root = tmp_path / f"manifests-v{ParsedManifestCache.SCHEMA_VERSION}"
        tmp_files = list(versioned_root.rglob("*.tmp*"))
        assert tmp_files == [], f"unexpected tmp litter: {tmp_files}"


# ---------------------------------------------------------------------------
# URL hashing
# ---------------------------------------------------------------------------


class TestURLHashing:
    def test_two_distinct_urls_have_distinct_on_disk_paths(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand_a = _make_wheel_candidate(name="numpy", version="1.26.0")
        cand_b = _make_wheel_candidate(name="numpy", version="1.27.0")

        cache.put("https://pypi.org/simple", "numpy", [cand_a], etag="a")
        cache.put(
            "https://internal.example.com/simple", "numpy", [cand_b], etag="b",
        )

        path_a = cache._path_for("https://pypi.org/simple", "numpy")
        path_b = cache._path_for(
            "https://internal.example.com/simple", "numpy",
        )
        assert path_a != path_b

        ra = cache.get("https://pypi.org/simple", "numpy")
        rb = cache.get("https://internal.example.com/simple", "numpy")
        assert ra is not None and ra.candidates == (cand_a,) and ra.etag == "a"
        assert rb is not None and rb.candidates == (cand_b,) and rb.etag == "b"

    def test_identical_url_resolves_to_identical_path(self, tmp_path):
        """Two cache instances rooted at the same dir agree on path."""
        c1 = ParsedManifestCache(tmp_path)
        c2 = ParsedManifestCache(tmp_path)
        assert c1._path_for("https://pypi.org/simple", "numpy") == c2._path_for(
            "https://pypi.org/simple", "numpy",
        )

    def test_full_sha256_used_in_path(self, tmp_path):
        """Path uses full 64-char sha256 digest, not a truncation."""
        import hashlib

        cache = ParsedManifestCache(tmp_path)
        url = "https://pypi.org/simple"
        path = cache._path_for(url, "numpy")
        expected_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        # The digest is a path component (the parent directory name).
        assert expected_digest in path.parts
        assert len(expected_digest) == 64


# ---------------------------------------------------------------------------
# Corruption robustness (per T7's "swallow" contract)
# ---------------------------------------------------------------------------


class TestCorruptionRobustness:
    def test_raw_garbage_bytes_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        target = cache._path_for("https://pypi.org/simple", "numpy")
        target.write_bytes(b"not json")  # raw bytes per T7 contract

        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_invalid_utf8_bytes_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        target = cache._path_for("https://pypi.org/simple", "numpy")
        target.write_bytes(b"\xff\xfe\xfd not valid utf-8")
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_payload_not_a_dict_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        target = cache._path_for("https://pypi.org/simple", "numpy")
        target.write_text(json.dumps(["not", "a", "dict"]))
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_missing_expires_at_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        del payload["expires_at"]
        target.write_text(json.dumps(payload))

        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_missing_cached_at_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        del payload["cached_at"]
        target.write_text(json.dumps(payload))
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_expires_at_wrong_type_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        payload["expires_at"] = 1234  # int, not str
        target.write_text(json.dumps(payload))

        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_bad_iso_timestamp_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        payload["expires_at"] = "not-an-iso-timestamp"
        target.write_text(json.dumps(payload))
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_candidates_field_missing_treated_as_miss(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)
        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        del payload["candidates"]
        target.write_text(json.dumps(payload))
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_candidate_entry_malformed_treated_as_miss(self, tmp_path):
        """A single bad candidate makes the whole manifest a miss."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        # Drop a required key from the single candidate.
        del payload["candidates"][0]["filename"]
        target.write_text(json.dumps(payload))

        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_etag_wrong_type_falls_back_to_none(self, tmp_path):
        """Non-string ``etag`` field is sanitised to ``None`` rather than miss."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag="valid")

        target = cache._path_for("https://pypi.org/simple", "numpy")
        payload = json.loads(target.read_text())
        payload["etag"] = 12345  # int, not str
        target.write_text(json.dumps(payload))

        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert result.etag is None
        assert result.candidates == (cand,)

    def test_get_swallows_os_error_on_read(self, tmp_path, monkeypatch):
        """Permission-denied (or similar OSError) on read is treated as miss."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        original_read_bytes = Path.read_bytes

        def _boom_read(self):
            # Only blow up for the cached target; let other callers
            # (test plumbing, etc) proceed.
            if self.name == "numpy.json":
                raise OSError("simulated permission denied")
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _boom_read)
        assert cache.get("https://pypi.org/simple", "numpy") is None

    def test_invalidate_swallows_os_error(self, tmp_path, monkeypatch):
        """``invalidate`` swallows non-FileNotFoundError OSError too."""
        cache = ParsedManifestCache(tmp_path)
        cand = _make_wheel_candidate()
        cache.put("https://pypi.org/simple", "numpy", [cand], etag=None)

        original_unlink = Path.unlink

        def _boom_unlink(self, *args, **kwargs):
            if self.name == "numpy.json":
                raise PermissionError("simulated permission denied")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _boom_unlink)
        # Must not raise.
        cache.invalidate("https://pypi.org/simple", "numpy")


# ---------------------------------------------------------------------------
# Candidate (de)serialization round-trip
# ---------------------------------------------------------------------------


class TestCandidateSerialization:
    def test_fully_populated_candidate_round_trips(self, tmp_path):
        """Wheel candidate with every field non-default survives the cache."""
        cache = ParsedManifestCache(tmp_path)
        original = Candidate.from_filename(
            "numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            name="numpy",
            version="1.26.0",
            url="https://files.pythonhosted.org/.../numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            hashes=frozenset({
                Hash("sha256", "a" * 64),
                Hash("sha384", "b" * 96),
            }),
            requires_python=">=3.9,<4",
            yanked=True,
            yanked_reason="superseded by 1.26.1",
            upload_time=datetime(2026, 1, 15, 12, 30, 45, tzinfo=timezone.utc),
        )
        cache.put(
            "https://pypi.org/simple", "numpy", [original], etag='W/"xyz"',
        )

        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert len(result.candidates) == 1
        got = result.candidates[0]

        assert got == original
        assert got.name == original.name
        assert got.version == original.version
        assert got.url == original.url
        assert got.filename == original.filename
        assert got.hashes == original.hashes
        assert got.requires_python == original.requires_python
        assert got.yanked is True
        assert got.yanked_reason == "superseded by 1.26.1"
        assert got.upload_time == original.upload_time
        assert got.is_wheel is True
        assert got.wheel_tags == original.wheel_tags

    def test_sdist_candidate_round_trips(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        original = _make_sdist_candidate("numpy", "1.26.0")
        cache.put("https://pypi.org/simple", "numpy", [original], etag=None)
        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert result.candidates == (original,)
        assert result.candidates[0].is_wheel is False
        assert result.candidates[0].wheel_tags is None

    def test_multiple_candidates_round_trip_in_order(self, tmp_path):
        cache = ParsedManifestCache(tmp_path)
        cands = [
            _make_wheel_candidate(name="numpy", version=f"1.{i}.0")
            for i in range(5)
        ]
        cache.put("https://pypi.org/simple", "numpy", cands, etag=None)
        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        # Order preserved (list -> tuple, no re-sorting).
        assert result.candidates == tuple(cands)

    def test_candidate_with_naive_upload_time_round_trips(self, tmp_path):
        """Naive ``upload_time`` survives the round-trip (T7 docstring)."""
        cache = ParsedManifestCache(tmp_path)
        naive = datetime(2026, 1, 15, 12, 30, 45)  # no tzinfo
        original = Candidate.from_filename(
            "numpy-1.26.0-py3-none-any.whl",
            name="numpy",
            version="1.26.0",
            url="https://example.org/numpy-1.26.0-py3-none-any.whl",
            hashes=frozenset(),
            requires_python=None,
            yanked=False,
            yanked_reason=None,
            upload_time=naive,
        )
        cache.put("https://pypi.org/simple", "numpy", [original], etag=None)
        result = cache.get("https://pypi.org/simple", "numpy")
        assert result is not None
        assert result.candidates[0].upload_time == naive
        assert result.candidates[0].upload_time.tzinfo is None


# ---------------------------------------------------------------------------
# Direct helper coverage (datetime + candidate JSON helpers)
# ---------------------------------------------------------------------------


class TestSerialisationHelpers:
    def test_datetime_to_iso_aware_round_trips(self):
        dt = datetime(2026, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        s = _datetime_to_iso(dt)
        assert _datetime_from_iso(s) == dt

    def test_datetime_to_iso_naive_round_trips(self):
        dt = datetime(2026, 1, 15, 12, 30, 45)
        s = _datetime_to_iso(dt)
        assert _datetime_from_iso(s) == dt

    def test_candidate_to_json_hashes_sorted_deterministically(self):
        c = _make_wheel_candidate(
            hashes=frozenset({
                Hash("sha512", "z" * 128),
                Hash("sha256", "a" * 64),
                Hash("md5", "f" * 32),
            }),
        )
        payload_1 = _candidate_to_json(c)
        payload_2 = _candidate_to_json(c)
        assert payload_1["hashes"] == payload_2["hashes"]
        # Sorted lexically: md5 < sha256 < sha512.
        assert payload_1["hashes"][0][0] == "md5"
        assert payload_1["hashes"][-1][0] == "sha512"

    def test_candidate_to_json_wheel_tags_sorted_deterministically(self):
        c = _make_wheel_candidate(
            filename="pkg-1.0-py3-none-any.whl",
        )
        payload = _candidate_to_json(c)
        assert payload["wheel_tags"] is not None
        # Sorted str(tag) for determinism.
        assert payload["wheel_tags"] == sorted(payload["wheel_tags"])

    def test_candidate_from_json_falls_back_to_filename_when_wheel_tags_missing(
        self,
    ):
        """Forward-compat: older payloads without ``wheel_tags`` re-derive."""
        c = _make_wheel_candidate(filename="numpy-1.26.0-py3-none-any.whl")
        payload = _candidate_to_json(c)
        # Strip wheel_tags to simulate a pre-field payload.
        del payload["wheel_tags"]
        # is_wheel is also stripped in older payloads (it's derived too);
        # ``Candidate.from_filename`` will re-derive both.
        del payload["is_wheel"]
        rebuilt = _candidate_from_json(payload)
        assert rebuilt.is_wheel is True
        assert rebuilt.wheel_tags == parse_tag("py3-none-any")

    def test_candidate_from_json_uses_cached_wheel_tags_over_filename(self):
        """Cached ``wheel_tags`` win over filename-derived (per T7 docstring)."""
        c = _make_wheel_candidate(filename="numpy-1.26.0-py3-none-any.whl")
        payload = _candidate_to_json(c)
        # Inject an unrelated tag-string that wouldn't come from the
        # filename — verifies the cached field is trusted.
        payload["wheel_tags"] = ["cp99-cp99-fakeplat"]
        rebuilt = _candidate_from_json(payload)
        # The rebuilt wheel_tags reflect what was cached, not the filename.
        assert Tag("cp99", "cp99", "fakeplat") in rebuilt.wheel_tags

    def test_candidate_from_json_wheel_tags_present_is_wheel_missing(self):
        """When ``is_wheel`` is missing but ``wheel_tags`` is present, derive from filename."""
        c = _make_wheel_candidate(filename="numpy-1.26.0-py3-none-any.whl")
        payload = _candidate_to_json(c)
        del payload["is_wheel"]
        rebuilt = _candidate_from_json(payload)
        assert rebuilt.is_wheel is True

    def test_candidate_from_json_sdist_when_wheel_tags_present(self):
        """sdist payload with ``wheel_tags=None`` falls into the fallback branch.

        Since ``wheel_tags is None``, ``_candidate_from_json`` will go
        through ``Candidate.from_filename`` (the else branch).
        """
        sdist = _make_sdist_candidate("numpy", "1.26.0")
        payload = _candidate_to_json(sdist)
        assert payload["wheel_tags"] is None
        rebuilt = _candidate_from_json(payload)
        assert rebuilt == sdist
