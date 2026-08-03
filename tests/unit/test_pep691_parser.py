"""Full-coverage tests for the PEP 691 (JSON) + PEP 503 (HTML) parsers
in :mod:`pipenv.resolver.pep691` (Initiative G phase 1, T12).

Scope: both ``_parse_pep691_json`` and ``_parse_pep503_html`` plus every
private helper in the module (``_extract_version``, ``_normalize_yanked``,
``_normalize_hashes``, ``_strip_archive_suffix``, ``_parse_upload_time``,
``_normalize_yanked_html``, ``_split_href_hash``,
``_package_name_from_page_url``, ``_AnchorCollector``, ``_build_candidate``,
``_build_candidate_from_html``).

The ``PEP691Client`` class (HTTP layer) is T13's territory and is not
exercised here.

Test pinning notes
------------------
* **Yanked-empty-string divergence (intentional):**
  - JSON ``"yanked": ""`` → NOT yanked (conservative — a misbehaving
    index can't accidentally mark every release yanked).
  - HTML ``data-yanked=""`` → yanked-with-no-reason (the *presence* of
    the attribute is the unambiguous signal).
  Both contracts are pinned in this file.
* **Relative URL resolution semantics:** ``urljoin`` pops one path
  segment per ``..``.  To reach ``/files/`` from
  ``/simple/foo/`` you need ``../../files/``.
* **PEP 658 metadata fields ignored:** ``data-core-metadata`` /
  ``data-dist-info-metadata`` are observed by the HTML parser but not
  threaded into the :class:`Candidate` in Phase 1.
* **Anchor text vs href filename:** when they disagree, the parser
  uses the anchor's inner text (with the href filename as fallback if
  the anchor had no text).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipenv.resolver.candidate import Candidate, Hash
from pipenv.resolver.pep691 import (
    _AnchorCollector,
    _build_candidate,
    _build_candidate_from_html,
    _extract_version,
    _normalize_hashes,
    _normalize_yanked,
    _normalize_yanked_html,
    _package_name_from_page_url,
    _parse_pep503_html,
    _parse_pep691_json,
    _parse_upload_time,
    _split_href_hash,
    _strip_archive_suffix,
)

FIXTURES_JSON = Path(__file__).parent / "fixtures" / "pep691"
FIXTURES_HTML = Path(__file__).parent / "fixtures" / "pep503"


# ---------------------------------------------------------------------------
# JSON parser — fixture round-trips
# ---------------------------------------------------------------------------


class TestPep691JsonFixtures:
    """Each curated T2 JSON fixture parses cleanly with the expected count."""

    @pytest.mark.parametrize(
        "name,expected_count",
        [
            ("six", 48),
            ("django", 781),
            ("cryptography", 3496),
            ("tablib", 68),
            ("yanked-pkg", 4),
            ("missing-hash", 2),
        ],
    )
    def test_fixture_round_trip_count(self, name, expected_count):
        body = (FIXTURES_JSON / f"{name}.json").read_bytes()
        candidates = _parse_pep691_json(body, f"https://pypi.org/simple/{name}/")
        assert len(candidates) == expected_count
        # Every candidate has a non-empty name/version/url.
        for c in candidates:
            assert c.name
            assert c.version
            assert c.url.startswith("https://")

    def test_six_has_both_wheels_and_sdists(self):
        """``six.json`` is the canonical wheel-vs-sdist branch validator."""
        body = (FIXTURES_JSON / "six.json").read_bytes()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/six/")
        wheels = [c for c in candidates if c.is_wheel]
        sdists = [c for c in candidates if not c.is_wheel]
        assert wheels, "expected at least one wheel candidate"
        assert sdists, "expected at least one sdist candidate"
        # Wheels carry parsed tags; sdists do not.
        for c in wheels:
            assert c.wheel_tags is not None
            assert len(c.wheel_tags) >= 1
        for c in sdists:
            assert c.wheel_tags is None

    def test_six_name_is_canonical(self):
        body = (FIXTURES_JSON / "six.json").read_bytes()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/six/")
        assert all(c.name == "six" for c in candidates)


# ---------------------------------------------------------------------------
# JSON parser — synthetic edge cases
# ---------------------------------------------------------------------------


class TestPep691JsonSynthetic:
    def _minimal_payload(self, **overrides):
        payload = {
            "meta": {"api-version": "1.0"},
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {"sha256": "ABCDEF"},
                    "yanked": False,
                }
            ],
        }
        payload.update(overrides)
        return json.dumps(payload).encode()

    def test_api_version_1_0_parses_non_empty(self):
        body = self._minimal_payload()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1

    def test_api_version_2_0_does_not_raise_returns_candidates(self):
        """Per T4's contract: unknown major logs (or just passes) and
        continues parsing — never raises."""
        payload = {
            "meta": {"api-version": "2.0"},
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {"sha256": "ABC"},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].filename == "foo-1.0-py3-none-any.whl"

    def test_api_version_non_string_is_tolerated(self):
        """``meta.api-version`` of unexpected type just falls through."""
        payload = {
            "meta": {"api-version": 1.0},  # non-string
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1

    def test_missing_meta_block_is_tolerated(self):
        """Some mirrors omit ``meta``; we just parse on."""
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1

    def test_relative_url_resolves_against_page_url(self):
        """``urljoin`` pops one segment per ``..``.  To reach ``/files/``
        from ``/simple/foo/`` you need ``../../files/``."""
        payload = {
            "meta": {"api-version": "1.0"},
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "../../files/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].url == "https://pypi.org/files/foo-1.0-py3-none-any.whl"

    def test_top_level_array_returns_empty_tuple(self):
        """A JSON top-level array is not a PEP 691 page."""
        body = b"[1, 2, 3]"
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_top_level_string_returns_empty_tuple(self):
        body = b'"not a page"'
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_missing_name_returns_empty(self):
        body = json.dumps({"files": []}).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_empty_name_returns_empty(self):
        body = json.dumps({"name": "", "files": []}).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_non_string_name_returns_empty(self):
        body = json.dumps({"name": 123, "files": []}).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_missing_files_returns_empty(self):
        body = json.dumps({"name": "foo"}).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_files_not_list_returns_empty(self):
        body = json.dumps({"name": "foo", "files": "not-a-list"}).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_non_dict_file_entries_skipped(self):
        """File entries that aren't dicts are silently skipped."""
        payload = {
            "name": "foo",
            "files": [
                "not-a-dict",
                12345,
                None,
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                },
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1

    def test_malformed_filename_entry_skipped(self):
        """A file entry with an unparseable filename is silently skipped
        while well-formed siblings still appear."""
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "unparseable",  # no version, no archive suffix
                    "url": "https://x/unparseable",
                    "hashes": {},
                },
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                },
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].filename == "foo-1.0-py3-none-any.whl"

    def test_malformed_wheel_filename_skipped(self):
        """A wheel filename missing the PEP 427 tag triple is skipped
        (Candidate.from_filename raises ValueError; _build_candidate
        catches and returns None)."""
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0.whl",  # missing tag triple
                    "url": "https://x/foo-1.0.whl",
                    "hashes": {},
                },
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                },
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        # well-formed wheel survives; malformed sibling is dropped
        names = {c.filename for c in candidates}
        assert "foo-1.0-py3-none-any.whl" in names
        assert "foo-1.0.whl" not in names

    def test_entry_missing_filename_skipped(self):
        payload = {
            "name": "foo",
            "files": [
                {"url": "https://x/foo.whl", "hashes": {}},  # no filename
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                },
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1

    def test_entry_missing_url_skipped(self):
        payload = {
            "name": "foo",
            "files": [
                {"filename": "foo-1.0-py3-none-any.whl", "hashes": {}},  # no url
                {
                    "filename": "foo-2.0-py3-none-any.whl",
                    "url": "https://x/foo-2.0-py3-none-any.whl",
                    "hashes": {},
                },
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].version == "2.0"

    def test_entry_empty_filename_skipped(self):
        payload = {
            "name": "foo",
            "files": [
                {"filename": "", "url": "https://x/foo.whl", "hashes": {}},
            ],
        }
        body = json.dumps(payload).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_entry_empty_url_skipped(self):
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "",
                    "hashes": {},
                },
            ],
        }
        body = json.dumps(payload).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_entry_non_string_filename_skipped(self):
        payload = {
            "name": "foo",
            "files": [
                {"filename": 12345, "url": "https://x/foo.whl", "hashes": {}},
            ],
        }
        body = json.dumps(payload).encode()
        assert _parse_pep691_json(body, "https://pypi.org/simple/foo/") == ()

    def test_invalid_json_body_raises(self):
        """The parser raises on a body that isn't decodable JSON at all
        so the T8 client can map to FetchError(transient)."""
        with pytest.raises(json.JSONDecodeError):
            _parse_pep691_json(b"not json", "https://pypi.org/simple/foo/")


# ---------------------------------------------------------------------------
# JSON parser — yanked variants
# ---------------------------------------------------------------------------


class TestPep691JsonYanked:
    """Pins all four ``yanked`` value branches via the yanked-pkg fixture
    + a synthetic empty-string case."""

    def test_yanked_pkg_fixture_decodes(self):
        body = (FIXTURES_JSON / "yanked-pkg.json").read_bytes()
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/yanked-pkg/"
        )
        assert len(candidates) == 4

    def test_yanked_false_branch(self):
        body = (FIXTURES_JSON / "yanked-pkg.json").read_bytes()
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/yanked-pkg/"
        )
        # The 1.0.0 sdist has "yanked": false
        target = next(c for c in candidates if c.version == "1.0.0")
        assert target.yanked is False
        assert target.yanked_reason is None

    def test_yanked_true_branch(self):
        body = (FIXTURES_JSON / "yanked-pkg.json").read_bytes()
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/yanked-pkg/"
        )
        # 1.1.0 sdist + wheel have "yanked": true
        targets = [c for c in candidates if c.version == "1.1.0"]
        assert len(targets) == 2
        for t in targets:
            assert t.yanked is True
            assert t.yanked_reason is None

    def test_yanked_string_reason_branch(self):
        body = (FIXTURES_JSON / "yanked-pkg.json").read_bytes()
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/yanked-pkg/"
        )
        # 1.2.0 wheel has "yanked": "security-advisory-CVE-2024-99999"
        target = next(c for c in candidates if c.version == "1.2.0")
        assert target.yanked is True
        assert target.yanked_reason == "security-advisory-CVE-2024-99999"

    def test_yanked_empty_string_is_not_yanked_json(self):
        """T4's contract: JSON ``"yanked": ""`` is NOT yanked
        (conservative — opposite of the HTML side)."""
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "yanked": "",
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].yanked is False
        assert candidates[0].yanked_reason is None

    def test_yanked_missing_field_is_not_yanked(self):
        """``yanked`` field absent → not yanked."""
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert candidates[0].yanked is False


# ---------------------------------------------------------------------------
# JSON parser — missing-hash + requires-python branches
# ---------------------------------------------------------------------------


class TestPep691JsonHashesAndRequiresPython:
    def test_missing_hash_fixture(self):
        """The first entry in ``missing-hash.json`` has ``"hashes": {}``."""
        body = (FIXTURES_JSON / "missing-hash.json").read_bytes()
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/missing-hash/"
        )
        empty_hash_entry = next(
            c for c in candidates if c.filename.endswith(".tar.gz")
        )
        assert empty_hash_entry.hashes == frozenset()
        # The other entry has a real sha256.
        wheel_entry = next(c for c in candidates if c.is_wheel)
        assert any(h.algo == "sha256" for h in wheel_entry.hashes)

    def test_missing_hashes_field_entirely(self):
        """Entry with no ``hashes`` key at all → empty frozenset."""
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert candidates[0].hashes == frozenset()

    def test_requires_python_present(self):
        body = (FIXTURES_JSON / "missing-hash.json").read_bytes()
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/missing-hash/"
        )
        # Both entries declare ``requires-python = ">=3.8"``.
        assert all(c.requires_python == ">=3.8" for c in candidates)

    def test_requires_python_empty_string_normalised_to_none(self):
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "requires-python": "",
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert candidates[0].requires_python is None

    def test_requires_python_non_string_ignored(self):
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "requires-python": 3.8,
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert candidates[0].requires_python is None


# ---------------------------------------------------------------------------
# JSON parser — upload-time
# ---------------------------------------------------------------------------


class TestPep691JsonUploadTime:
    def test_upload_time_parses_for_fixture(self):
        body = (FIXTURES_JSON / "yanked-pkg.json").read_bytes()
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/yanked-pkg/"
        )
        assert all(c.upload_time is not None for c in candidates)

    def test_upload_time_missing_yields_none(self):
        payload = {
            "name": "foo",
            "files": [
                {
                    "filename": "foo-1.0-py3-none-any.whl",
                    "url": "https://x/foo-1.0-py3-none-any.whl",
                    "hashes": {},
                }
            ],
        }
        body = json.dumps(payload).encode()
        candidates = _parse_pep691_json(body, "https://pypi.org/simple/foo/")
        assert candidates[0].upload_time is None


# ---------------------------------------------------------------------------
# HTML parser — fixture round-trips
# ---------------------------------------------------------------------------


class TestPep503HtmlFixtures:
    @pytest.mark.parametrize(
        "name,expected_count",
        [
            ("six", 48),
            ("django", 781),
            ("cryptography", 3496),
            ("yanked-pkg", 4),
        ],
    )
    def test_html_fixture_round_trip_count(self, name, expected_count):
        body = (FIXTURES_HTML / f"{name}.html").read_bytes()
        candidates = _parse_pep503_html(body, f"https://pypi.org/simple/{name}/")
        assert len(candidates) == expected_count

    def test_six_html_has_wheels_and_sdists(self):
        body = (FIXTURES_HTML / "six.html").read_bytes()
        candidates = _parse_pep503_html(body, "https://pypi.org/simple/six/")
        wheels = [c for c in candidates if c.is_wheel]
        sdists = [c for c in candidates if not c.is_wheel]
        assert wheels
        assert sdists


# ---------------------------------------------------------------------------
# HTML parser — synthetic inline tests
# ---------------------------------------------------------------------------


def _wrap_html(anchors_inner: str) -> bytes:
    return (
        b"<!DOCTYPE html><html><head></head><body>"
        + anchors_inner.encode()
        + b"</body></html>"
    )


class TestPep503HtmlSynthetic:
    def test_hash_fragment_extracted(self):
        html = _wrap_html(
            '<a href="https://x/foo-1.0.tar.gz#sha256=ABCDEF">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].hashes == frozenset({Hash("sha256", "ABCDEF")})

    def test_hash_algo_lowercased(self):
        html = _wrap_html(
            '<a href="https://x/foo-1.0.tar.gz#SHA256=ABCDEF">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert candidates[0].hashes == frozenset({Hash("sha256", "ABCDEF")})

    def test_requires_python_html_unescaped(self):
        html = _wrap_html(
            '<a href="https://x/foo-1.0.tar.gz" '
            'data-requires-python="&gt;=3.10">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].requires_python == ">=3.10"

    def test_relative_url_resolves(self):
        """Same urljoin semantics as the JSON parser — one segment per ``..``."""
        html = _wrap_html(
            '<a href="../../files/foo-1.0.tar.gz">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].url == "https://pypi.org/files/foo-1.0.tar.gz"

    def test_anchor_without_href_skipped(self):
        html = _wrap_html(
            '<a>orphan</a>'
            '<a href="https://x/foo-1.0.tar.gz">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].filename == "foo-1.0.tar.gz"

    def test_anchor_without_text_falls_back_to_href_filename(self):
        """If the anchor has no text, the parser falls back to the
        href's basename."""
        html = _wrap_html('<a href="https://x/foo-1.0.tar.gz"></a>')
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].filename == "foo-1.0.tar.gz"

    def test_anchor_text_used_when_present(self):
        """Per the parser's actual contract: anchor inner text wins
        when it's present.  (PEP 503 says the text *is* the filename;
        we trust it.)"""
        html = _wrap_html(
            '<a href="https://x/whatever">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].filename == "foo-1.0.tar.gz"

    def test_pep_658_metadata_attrs_ignored(self):
        """``data-core-metadata`` and ``data-dist-info-metadata`` must not
        break parsing in Phase 1 (PEP 658 deferred)."""
        html = _wrap_html(
            '<a href="https://x/foo-1.0-py3-none-any.whl" '
            'data-core-metadata="sha256=ABC" '
            'data-dist-info-metadata="true">foo-1.0-py3-none-any.whl</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].filename == "foo-1.0-py3-none-any.whl"

    def test_unparseable_page_url_returns_empty(self):
        """A page URL with no path segment cannot give us a canonical
        package name → empty tuple."""
        html = _wrap_html(
            '<a href="https://x/foo-1.0-py3-none-any.whl">foo-1.0-py3-none-any.whl</a>'
        )
        assert _parse_pep503_html(html, "https://pypi.org/") == ()

    def test_unparseable_filename_anchor_skipped(self):
        html = _wrap_html(
            '<a href="https://x/garbage">garbage</a>'
            '<a href="https://x/foo-1.0.tar.gz">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert len(candidates) == 1
        assert candidates[0].filename == "foo-1.0.tar.gz"

    def test_malformed_wheel_anchor_skipped(self):
        """Wheel filename missing the tag triple → silently skipped."""
        html = _wrap_html(
            '<a href="https://x/foo-1.0.whl">foo-1.0.whl</a>'
            '<a href="https://x/foo-1.0-py3-none-any.whl">'
            'foo-1.0-py3-none-any.whl</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        names = {c.filename for c in candidates}
        assert "foo-1.0-py3-none-any.whl" in names
        assert "foo-1.0.whl" not in names

    def test_html_body_lenient_to_garbage(self):
        """HTMLParser is lenient — non-HTML body yields no anchors,
        which becomes an empty tuple (does NOT raise)."""
        candidates = _parse_pep503_html(
            b"this is not html at all",
            "https://pypi.org/simple/foo/",
        )
        assert candidates == ()

    def test_utf8_mojibake_recovered(self):
        """Invalid UTF-8 byte must not raise — the parser falls back to
        replacement decoding."""
        body = (
            b'<a href="https://x/foo-1.0.tar.gz">foo-1.0.tar.gz</a>'
            b'\xff'  # invalid UTF-8 byte
        )
        candidates = _parse_pep503_html(body, "https://pypi.org/simple/foo/")
        # No raise; we recover the well-formed anchor.
        assert len(candidates) == 1


# ---------------------------------------------------------------------------
# HTML parser — yanked variants
# ---------------------------------------------------------------------------


class TestPep503HtmlYanked:
    def test_yanked_absent_attribute(self):
        html = _wrap_html(
            '<a href="https://x/foo-1.0.tar.gz">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert candidates[0].yanked is False
        assert candidates[0].yanked_reason is None

    def test_yanked_empty_attribute_is_yanked_html(self):
        """T5's HTML contract — *opposite* of T4's JSON empty-string
        contract: HTML ``data-yanked=""`` is yanked-with-no-reason."""
        html = _wrap_html(
            '<a href="https://x/foo-1.0.tar.gz" data-yanked="">'
            'foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert candidates[0].yanked is True
        assert candidates[0].yanked_reason is None

    def test_yanked_with_reason(self):
        html = _wrap_html(
            '<a href="https://x/foo-1.0.tar.gz" '
            'data-yanked="security-advisory-CVE-2024-99999">'
            'foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert candidates[0].yanked is True
        assert candidates[0].yanked_reason == "security-advisory-CVE-2024-99999"

    def test_yanked_reason_html_unescaped(self):
        html = _wrap_html(
            '<a href="https://x/foo-1.0.tar.gz" '
            'data-yanked="see https://x/a&amp;b">foo-1.0.tar.gz</a>'
        )
        candidates = _parse_pep503_html(html, "https://pypi.org/simple/foo/")
        assert candidates[0].yanked_reason == "see https://x/a&b"

    def test_yanked_fixture_full_matrix(self):
        body = (FIXTURES_HTML / "yanked-pkg.html").read_bytes()
        candidates = _parse_pep503_html(
            body, "https://pypi.org/simple/yanked-pkg/"
        )
        by_version = {c.filename: c for c in candidates}
        # 1.0.0 sdist: no data-yanked → not yanked
        c100 = by_version["yanked-pkg-1.0.0.tar.gz"]
        assert c100.yanked is False
        # 1.1.0 wheel + sdist: empty data-yanked → yanked-with-no-reason
        c110w = by_version["yanked-pkg-1.1.0-py3-none-any.whl"]
        assert c110w.yanked is True
        assert c110w.yanked_reason is None
        c110s = by_version["yanked-pkg-1.1.0.tar.gz"]
        assert c110s.yanked is True
        assert c110s.yanked_reason is None
        # 1.2.0 wheel: data-yanked has reason → yanked w/ reason
        c120 = by_version["yanked-pkg-1.2.0-py3-none-any.whl"]
        assert c120.yanked is True
        assert c120.yanked_reason == "security-advisory-CVE-2024-99999"


# ---------------------------------------------------------------------------
# Cross-format parity (formal)
# ---------------------------------------------------------------------------


class TestCrossFormatParity:
    """For every JSON/HTML fixture pair, the filename sets must match."""

    @pytest.mark.parametrize(
        "name,page_path",
        [
            ("six", "/simple/six/"),
            ("django", "/simple/django/"),
            ("cryptography", "/simple/cryptography/"),
            ("yanked-pkg", "/simple/yanked-pkg/"),
        ],
    )
    def test_filename_sets_equal(self, name, page_path):
        json_body = (FIXTURES_JSON / f"{name}.json").read_bytes()
        html_body = (FIXTURES_HTML / f"{name}.html").read_bytes()
        page_url = f"https://pypi.org{page_path}"
        json_candidates = _parse_pep691_json(json_body, page_url)
        html_candidates = _parse_pep503_html(html_body, page_url)
        json_filenames = {c.filename for c in json_candidates}
        html_filenames = {c.filename for c in html_candidates}
        assert json_filenames == html_filenames

    def test_hashes_match_for_yanked_pkg(self):
        """Synthetic yanked-pkg pair was hand-aligned: same hashes."""
        json_body = (FIXTURES_JSON / "yanked-pkg.json").read_bytes()
        html_body = (FIXTURES_HTML / "yanked-pkg.html").read_bytes()
        page = "https://pypi.org/simple/yanked-pkg/"
        json_by_file = {
            c.filename: c.hashes for c in _parse_pep691_json(json_body, page)
        }
        html_by_file = {
            c.filename: c.hashes for c in _parse_pep503_html(html_body, page)
        }
        assert json_by_file == html_by_file


# ---------------------------------------------------------------------------
# Private helpers — direct tests for coverage
# ---------------------------------------------------------------------------


class TestExtractVersion:
    def test_canonical_match(self):
        assert _extract_version("foo-1.0-py3-none-any.whl", "foo") == "1.0"

    def test_sdist(self):
        assert _extract_version("foo-1.0.tar.gz", "foo") == "1.0"

    def test_django_case_variant(self):
        """``Django-5.0.0...`` vs canonical ``django``."""
        assert (
            _extract_version("Django-5.0.0-py3-none-any.whl", "django") == "5.0.0"
        )

    def test_underscore_dash_variant(self):
        """``python_dateutil-2.8.0.tar.gz`` for canonical ``python-dateutil``."""
        assert (
            _extract_version("python_dateutil-2.8.0.tar.gz", "python-dateutil")
            == "2.8.0"
        )

    def test_unparseable_returns_none(self):
        assert _extract_version("totally-unparseable.unknown", "foo") is None

    def test_unknown_suffix_returns_none(self):
        """No recognised archive suffix → None."""
        assert _extract_version("foo-1.0.exe", "foo") is None

    def test_prefix_mismatch_returns_none(self):
        """Filename's dist doesn't match the canonical name → None."""
        assert _extract_version("bar-1.0-py3-none-any.whl", "foo") is None

    def test_empty_remainder_returns_none(self):
        """Filename is exactly ``<name>-.tar.gz`` — empty version."""
        # Prefix stripping yields ``""`` → None.
        assert _extract_version("foo-.tar.gz", "foo") is None

    def test_build_tag_wheel(self):
        """Wheel with a build tag: ``foo-1.0-1-py3-none-any.whl``.
        The first ``-``-chunk after the dist prefix is the version."""
        assert (
            _extract_version("foo-1.0-1-py3-none-any.whl", "foo") == "1.0"
        )

    def test_tgz_suffix(self):
        assert _extract_version("foo-1.0.tgz", "foo") == "1.0"

    def test_zip_suffix(self):
        assert _extract_version("foo-1.0.zip", "foo") == "1.0"

    def test_tar_bz2_suffix(self):
        assert _extract_version("foo-1.0.tar.bz2", "foo") == "1.0"


class TestStripArchiveSuffix:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("foo-1.0.tar.gz", "foo-1.0"),
            ("foo-1.0.tar.bz2", "foo-1.0"),
            ("foo-1.0.whl", "foo-1.0"),
            ("foo-1.0.zip", "foo-1.0"),
            ("foo-1.0.tgz", "foo-1.0"),
        ],
    )
    def test_recognised_suffix(self, filename, expected):
        assert _strip_archive_suffix(filename) == expected

    def test_unknown_suffix_returned_unchanged(self):
        assert _strip_archive_suffix("foo-1.0.exe") == "foo-1.0.exe"

    def test_no_suffix_returned_unchanged(self):
        assert _strip_archive_suffix("foo-1.0") == "foo-1.0"


class TestNormalizeYanked:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (True, (True, None)),
            (False, (False, None)),
            ("reason", (True, "reason")),
            ("", (False, None)),  # empty-string → NOT yanked (JSON contract)
            (None, (False, None)),
            (123, (False, None)),
            ([], (False, None)),
            ({}, (False, None)),
        ],
    )
    def test_branches(self, raw, expected):
        assert _normalize_yanked(raw) == expected


class TestNormalizeYankedHtml:
    def test_absent(self):
        assert _normalize_yanked_html({}) == (False, None)

    def test_empty_value(self):
        """HTML contract: empty value → yanked-with-no-reason (opposite
        of JSON)."""
        assert _normalize_yanked_html({"data-yanked": ""}) == (True, None)

    def test_non_empty_value(self):
        assert _normalize_yanked_html({"data-yanked": "why"}) == (True, "why")

    def test_html_entities_unescaped(self):
        assert _normalize_yanked_html({"data-yanked": "a&amp;b"}) == (
            True,
            "a&b",
        )


class TestNormalizeHashes:
    def test_empty_dict(self):
        assert _normalize_hashes({}) == frozenset()

    def test_non_dict(self):
        assert _normalize_hashes("not a dict") == frozenset()
        assert _normalize_hashes(None) == frozenset()
        assert _normalize_hashes(42) == frozenset()

    def test_single_algo(self):
        assert _normalize_hashes({"sha256": "abc"}) == frozenset(
            {Hash("sha256", "abc")}
        )

    def test_multiple_algos(self):
        result = _normalize_hashes({"sha256": "abc", "md5": "def"})
        assert Hash("sha256", "abc") in result
        assert Hash("md5", "def") in result
        assert len(result) == 2

    def test_algo_lowercased(self):
        assert _normalize_hashes({"SHA256": "ABC"}) == frozenset(
            {Hash("sha256", "ABC")}
        )

    def test_non_string_keys_or_values_filtered(self):
        assert _normalize_hashes({"sha256": 12345}) == frozenset()
        assert _normalize_hashes({123: "abc"}) == frozenset()


class TestParseUploadTime:
    def test_none_returns_none(self):
        assert _parse_upload_time(None) is None

    def test_empty_returns_none(self):
        assert _parse_upload_time("") is None

    def test_non_string_returns_none(self):
        assert _parse_upload_time(12345) is None

    def test_full_microseconds_with_z(self):
        result = _parse_upload_time("2024-01-15T12:34:56.789012Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.microsecond == 789012

    def test_z_no_microseconds(self):
        result = _parse_upload_time("2024-01-15T12:34:56Z")
        assert result is not None
        assert result.second == 56

    def test_no_z_naive(self):
        """Without ``Z`` Python's fromisoformat handles it directly."""
        result = _parse_upload_time("2024-01-15T12:34:56")
        assert result is not None
        assert result.tzinfo is None

    def test_garbage_returns_none(self):
        assert _parse_upload_time("not a date") is None

    def test_malformed_with_z_returns_none(self):
        """Has a ``Z`` but the rest is malformed → falls into fallback,
        fails again, returns None."""
        assert _parse_upload_time("garbageZ") is None


class TestSplitHrefHash:
    def test_no_fragment(self):
        assert _split_href_hash("https://x/foo.whl") == (
            "https://x/foo.whl",
            frozenset(),
        )

    def test_fragment_without_equals(self):
        assert _split_href_hash("https://x/foo.whl#sha256") == (
            "https://x/foo.whl",
            frozenset(),
        )

    def test_normal_fragment(self):
        base, hashes = _split_href_hash("https://x/foo.whl#sha256=ABC")
        assert base == "https://x/foo.whl"
        assert hashes == frozenset({Hash("sha256", "ABC")})

    def test_empty_algo(self):
        assert _split_href_hash("https://x/foo.whl#=ABC") == (
            "https://x/foo.whl",
            frozenset(),
        )

    def test_empty_value(self):
        assert _split_href_hash("https://x/foo.whl#sha256=") == (
            "https://x/foo.whl",
            frozenset(),
        )

    def test_algo_lowercased(self):
        _, hashes = _split_href_hash("https://x/foo.whl#SHA256=ABC")
        assert hashes == frozenset({Hash("sha256", "ABC")})

    def test_empty_fragment(self):
        """``#`` followed by nothing."""
        assert _split_href_hash("https://x/foo.whl#") == (
            "https://x/foo.whl",
            frozenset(),
        )


class TestPackageNameFromPageUrl:
    def test_trailing_slash(self):
        assert _package_name_from_page_url("https://pypi.org/simple/six/") == "six"

    def test_no_trailing_slash(self):
        assert _package_name_from_page_url("https://pypi.org/simple/six") == "six"

    def test_canonicalised(self):
        """``Django`` (capitalised) canonicalises to ``django``."""
        assert (
            _package_name_from_page_url("https://pypi.org/simple/Django/")
            == "django"
        )

    def test_underscore_canonicalised(self):
        assert (
            _package_name_from_page_url(
                "https://pypi.org/simple/Python_Dateutil/"
            )
            == "python-dateutil"
        )

    def test_no_path_segments(self):
        assert _package_name_from_page_url("https://pypi.org/") is None

    def test_empty_url(self):
        assert _package_name_from_page_url("") is None


class TestAnchorCollector:
    def test_collects_attrs_and_text(self):
        collector = _AnchorCollector()
        collector.feed(
            '<a href="https://x/foo.whl" data-yanked="">my-foo</a>'
            '<a href="https://x/bar.whl">bar</a>'
        )
        collector.close()
        assert len(collector.entries) == 2
        attrs1, text1 = collector.entries[0]
        assert attrs1["href"] == "https://x/foo.whl"
        assert attrs1["data-yanked"] == ""
        assert text1 == "my-foo"
        attrs2, text2 = collector.entries[1]
        assert attrs2["href"] == "https://x/bar.whl"
        assert text2 == "bar"

    def test_bare_attribute_normalised_to_empty_string(self):
        """A bare attribute (``data-yanked`` with no value) becomes
        ``""`` in the collected dict, distinguishable from ``"key not in dict"``."""
        collector = _AnchorCollector()
        collector.feed('<a href="https://x/foo.whl" data-yanked>foo</a>')
        collector.close()
        attrs, _ = collector.entries[0]
        assert attrs["data-yanked"] == ""
        # And distinguishable from absent:
        assert "data-yanked" in attrs

    def test_non_anchor_tags_ignored(self):
        collector = _AnchorCollector()
        collector.feed("<div>not an anchor</div><br/>")
        collector.close()
        assert collector.entries == []

    def test_chunked_text_concatenated(self):
        """HTMLParser may split text into multiple ``handle_data`` calls;
        the collector must concatenate them."""
        collector = _AnchorCollector()
        # Use an entity reference; HTMLParser delivers entity + surrounding
        # text in separate callbacks.
        collector.feed('<a href="https://x">foo&amp;bar</a>')
        collector.close()
        assert len(collector.entries) == 1
        _, text = collector.entries[0]
        # Text is concatenated; HTMLParser auto-resolves &amp; in data.
        assert "foo" in text and "bar" in text

    def test_handle_data_outside_anchor_ignored(self):
        """Top-level text content is not collected (current_attrs is None)."""
        collector = _AnchorCollector()
        collector.feed("loose text<a href=\"https://x\">in-anchor</a>more loose")
        collector.close()
        assert len(collector.entries) == 1


# ---------------------------------------------------------------------------
# _build_candidate / _build_candidate_from_html direct tests
# ---------------------------------------------------------------------------


class TestBuildCandidate:
    """Direct tests of ``_build_candidate`` (covers paths the higher-level
    JSON parser exercises but ensures direct coverage too)."""

    def test_success(self):
        c = _build_candidate(
            {
                "filename": "foo-1.0-py3-none-any.whl",
                "url": "https://x/foo-1.0-py3-none-any.whl",
                "hashes": {"sha256": "abc"},
            },
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert isinstance(c, Candidate)
        assert c.version == "1.0"

    def test_filename_not_string(self):
        assert (
            _build_candidate(
                {"filename": 123, "url": "https://x/foo.whl"},
                canonical_name="foo",
                page_url="https://pypi.org/simple/foo/",
            )
            is None
        )

    def test_url_not_string(self):
        assert (
            _build_candidate(
                {"filename": "foo-1.0-py3-none-any.whl", "url": 123},
                canonical_name="foo",
                page_url="https://pypi.org/simple/foo/",
            )
            is None
        )

    def test_returns_none_on_unparseable_version(self):
        assert (
            _build_candidate(
                {"filename": "unparseable", "url": "https://x/u"},
                canonical_name="foo",
                page_url="https://pypi.org/simple/foo/",
            )
            is None
        )


class TestBuildCandidateFromHtml:
    def test_success(self):
        c = _build_candidate_from_html(
            {
                "href": "https://x/foo-1.0-py3-none-any.whl",
                "data-requires-python": ">=3.10",
            },
            "foo-1.0-py3-none-any.whl",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert isinstance(c, Candidate)
        assert c.requires_python == ">=3.10"

    def test_no_href(self):
        c = _build_candidate_from_html(
            {},
            "foo-1.0-py3-none-any.whl",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert c is None

    def test_empty_href(self):
        c = _build_candidate_from_html(
            {"href": ""},
            "foo-1.0-py3-none-any.whl",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert c is None

    def test_href_non_string(self):
        # Defensive: the collector always stores strings, but the helper
        # guards anyway.
        c = _build_candidate_from_html(
            {"href": 12345},  # type: ignore[arg-type]
            "foo-1.0-py3-none-any.whl",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert c is None

    def test_empty_text_falls_back_to_href_basename(self):
        c = _build_candidate_from_html(
            {"href": "https://x/foo-1.0.tar.gz"},
            "",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert c is not None
        assert c.filename == "foo-1.0.tar.gz"

    def test_empty_text_and_no_basename_returns_none(self):
        """If both anchor text and href basename are empty, no filename
        can be derived → None."""
        c = _build_candidate_from_html(
            {"href": "https://x/"},
            "",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert c is None

    def test_unparseable_filename_returns_none(self):
        c = _build_candidate_from_html(
            {"href": "https://x/garbage"},
            "garbage",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert c is None

    def test_malformed_wheel_returns_none(self):
        c = _build_candidate_from_html(
            {"href": "https://x/foo-1.0.whl"},
            "foo-1.0.whl",
            canonical_name="foo",
            page_url="https://pypi.org/simple/foo/",
        )
        assert c is None
