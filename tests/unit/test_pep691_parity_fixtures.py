"""Parity tests: our parser output vs pip's ``Link.from_json`` / ``Link.from_element``.

This is the load-bearing Phase-1 acceptance test for Initiative G:
that :mod:`pipenv.resolver.pep691`'s parsers produce the same
``Candidate`` information as pip's existing ``Link`` path for the
same simple-API response.  Live-PyPI parity across 20 real packages
is deferred to Phase 3 per design §7.4; here we pin parity against
the T2 fixture suite (4 real-PyPI snapshots + synthetics).

Divergences from pip's output are EXPECTED to be zero on these
fixtures.  Any divergence MUST be documented in
``test_pep691_parity_known_diffs.md`` with a written justification
(e.g. "pip does X for backcompat with pre-PEP-691 indexes; we
don't").  Silent skips are forbidden.

T10 — Initiative G phase 1.
"""
from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

# Deliberate ``pip._internal`` import — the whole point of this test
# is parity vs pip's parser.  The T17 pre-commit grep gate scopes to
# ``pipenv/resolver/`` so this test file is exempt by path.  The
# trailing ``parity-test-by-design`` marker exists for human review-
# readability — no actual noqa rule needed (ruff/etc. don't flag this
# import).
from pipenv.patched.pip._internal.models.link import Link  # parity-test-by-design

from pipenv.resolver.pep691 import _parse_pep691_json, _parse_pep503_html


FIXTURE_DIR = Path(__file__).parent / "fixtures"
JSON_FIXTURES = sorted(p.name for p in (FIXTURE_DIR / "pep691").glob("*.json"))
HTML_FIXTURES = sorted(p.name for p in (FIXTURE_DIR / "pep503").glob("*.html"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _PipAnchorCollector(HTMLParser):
    """Collect anchor attribute dicts the way pip's ``Link.from_element``
    expects them.

    ``Link.from_element`` takes a ``dict[str, str | None]`` of anchor
    attributes.  ``HTMLParser.handle_starttag`` already yields
    ``list[tuple[str, str | None]]``; we just dict-ify each anchor.

    This mirrors the structure of :class:`pipenv.resolver.pep691._AnchorCollector`
    so both sides see the same raw input — i.e., any divergence the
    test catches is in *parsing*, not in *attribute collection*.
    Note: our internal collector normalises ``None`` → ``""`` to
    preserve presence-vs-empty distinction; pip keeps ``None``.  Since
    ``Link.from_element`` reads via ``attrs.get(...)`` (which returns
    ``None`` for both "absent" and "explicitly None"), this difference
    does not affect pip's output — and we test the eventual Candidate
    output, not the intermediate dict.
    """

    def __init__(self) -> None:
        super().__init__()
        self.anchor_attribs: list[dict[str, str | None]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "a":
            self.anchor_attribs.append(dict(attrs))


def _pip_link_hashes(link: Link) -> list[tuple[str, str]]:
    """Extract ``(algo, hex)`` tuples from a pip ``Link``, matching our
    ``Hash`` representation.

    pip's PEP 691 path stores the JSON ``hashes`` mapping in
    ``link._hashes`` (a plain ``dict[str, str]``).  pip's PEP 503 path
    likewise parses the ``#<algo>=<hex>`` URL fragment into the same
    attribute.  We lower-case the algo on the pip side to match our
    parser's normalisation (T4/T5 both call ``algo.lower()``); on real
    fixtures both sides are already lower-case so this is a no-op
    today, but it makes the comparison robust against future indexes
    that return ``"SHA256"``.
    """
    hashes = getattr(link, "_hashes", None) or {}
    return [(algo.lower(), value) for algo, value in hashes.items()]


def _normalise_pip_requires_python(link: Link) -> str | None:
    """pip stores ``requires_python = pyrequire if pyrequire else None``
    in ``Link.__init__`` (see ``pipenv/patched/pip/_internal/models/link.py``
    around the constructor).  So pip's value is already canonicalised
    to ``None`` for missing/empty inputs — our :class:`Candidate` uses
    the same convention.  Re-applying ``or None`` here is defensive
    against any future change in pip's behaviour.
    """
    return link.requires_python or None


def _normalise_pip_yanked_reason(link: Link) -> str | None:
    """Translate pip's ``yanked_reason`` to our ``yanked_reason`` semantics.

    pip's JSON path (``Link.from_json``):
      - ``yanked: false`` → ``yanked_reason = None`` (not yanked).
      - ``yanked: true``  → ``yanked_reason = ""`` (yanked, no reason).
      - ``yanked: str``   → ``yanked_reason = str`` (yanked w/ reason).

    pip's HTML path (``Link.from_element``):
      - ``data-yanked`` absent → ``yanked_reason = None``.
      - ``data-yanked=""``     → ``yanked_reason = ""`` (yanked).
      - ``data-yanked="text"`` → ``yanked_reason = "text"``.

    Our ``Candidate.yanked_reason`` is ``None`` for both "not yanked"
    and "yanked-with-no-reason"; the distinguishing signal is the
    ``Candidate.yanked`` boolean.  So to compare reasons we collapse
    pip's ``""`` to ``None`` whenever the link is yanked, and the
    not-yanked side trivially compares ``None == None``.
    """
    if not link.is_yanked:
        return None
    return link.yanked_reason or None


# ---------------------------------------------------------------------------
# PEP 691 JSON parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", JSON_FIXTURES)
def test_pep691_json_parity_with_pip(fixture_name: str) -> None:
    """Our PEP 691 JSON parser output equals pip's ``Link.from_json``
    output, field-by-field, for every fixture in the T2 set.
    """
    package = fixture_name.rsplit(".", 1)[0]
    page_url = f"https://pypi.org/simple/{package}/"
    body = (FIXTURE_DIR / "pep691" / fixture_name).read_bytes()
    data = json.loads(body)

    our_candidates = _parse_pep691_json(body, page_url)

    pip_links: list[Link] = []
    for file_entry in data["files"]:
        link = Link.from_json(file_entry, page_url)
        if link is not None:
            pip_links.append(link)

    our_by_filename = {c.filename: c for c in our_candidates}
    pip_by_filename = {link.filename: link for link in pip_links}

    # 1. Filename-set parity.  This is the load-bearing assertion:
    # both parsers see the same artifact set on the same body.
    assert set(our_by_filename) == set(pip_by_filename), (
        f"Filename-set mismatch for {fixture_name}: "
        f"ours - pip = {sorted(set(our_by_filename) - set(pip_by_filename))[:5]}; "
        f"pip - ours = {sorted(set(pip_by_filename) - set(our_by_filename))[:5]}"
    )

    # 2. Per-file field parity: url, hashes, requires_python, yanked,
    # yanked_reason.  We deliberately do NOT compare ``upload_time``
    # against pip — pip uses its own ``parse_iso_datetime`` helper that
    # may yield a different tzinfo flavour from ``datetime.fromisoformat``;
    # T12 pins upload-time on our side directly against the fixture
    # string, which is the load-bearing assertion for that field.
    for filename, c in our_by_filename.items():
        link = pip_by_filename[filename]

        assert c.url == link.url_without_fragment, (
            f"{fixture_name}/{filename}: url diff — "
            f"ours={c.url!r} pip={link.url_without_fragment!r}"
        )

        our_hashes = sorted((h.algo, h.value) for h in c.hashes)
        pip_hashes = sorted(_pip_link_hashes(link))
        assert our_hashes == pip_hashes, (
            f"{fixture_name}/{filename}: hash diff — "
            f"ours={our_hashes} pip={pip_hashes}"
        )

        assert c.requires_python == _normalise_pip_requires_python(link), (
            f"{fixture_name}/{filename}: requires_python diff — "
            f"ours={c.requires_python!r} pip={link.requires_python!r}"
        )

        assert c.yanked == bool(link.is_yanked), (
            f"{fixture_name}/{filename}: yanked diff — "
            f"ours={c.yanked} pip={link.is_yanked} "
            f"(pip yanked_reason={link.yanked_reason!r})"
        )

        assert c.yanked_reason == _normalise_pip_yanked_reason(link), (
            f"{fixture_name}/{filename}: yanked_reason diff — "
            f"ours={c.yanked_reason!r} pip={link.yanked_reason!r}"
        )


# ---------------------------------------------------------------------------
# PEP 503 HTML parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", HTML_FIXTURES)
def test_pep503_html_parity_with_pip(fixture_name: str) -> None:
    """Our PEP 503 HTML parser output equals pip's ``Link.from_element``
    output, field-by-field, for every fixture in the T2 set.

    Fields with parity: ``filename``, ``url_without_fragment``,
    ``hashes``, ``requires_python``, ``is_yanked``, ``yanked_reason``.
    HTML carries no ``upload-time`` equivalent — both we and pip have
    it as ``None`` on this path, so no assertion needed.
    """
    package = fixture_name.rsplit(".", 1)[0]
    page_url = f"https://pypi.org/simple/{package}/"
    body = (FIXTURE_DIR / "pep503" / fixture_name).read_bytes()

    our_candidates = _parse_pep503_html(body, page_url)

    collector = _PipAnchorCollector()
    collector.feed(body.decode("utf-8"))
    collector.close()

    pip_links: list[Link] = []
    for anchor_attribs in collector.anchor_attribs:
        # pip's ``from_element`` takes ``(anchor_attribs, page_url, base_url)``;
        # for a simple-index page with no ``<base href>`` element the
        # base_url equals the page_url.  Our T2 fixtures don't include
        # ``<base>`` (PyPI doesn't emit one), so this is the correct
        # call for parity.
        link = Link.from_element(anchor_attribs, page_url, page_url)
        if link is not None:
            pip_links.append(link)

    our_by_filename = {c.filename: c for c in our_candidates}
    pip_by_filename = {link.filename: link for link in pip_links}

    # 1. Filename-set parity.
    assert set(our_by_filename) == set(pip_by_filename), (
        f"Filename-set mismatch for {fixture_name}: "
        f"ours - pip = {sorted(set(our_by_filename) - set(pip_by_filename))[:5]}; "
        f"pip - ours = {sorted(set(pip_by_filename) - set(our_by_filename))[:5]}"
    )

    # 2. Per-file field parity.
    for filename, c in our_by_filename.items():
        link = pip_by_filename[filename]

        assert c.url == link.url_without_fragment, (
            f"{fixture_name}/{filename}: url diff — "
            f"ours={c.url!r} pip={link.url_without_fragment!r}"
        )

        our_hashes = sorted((h.algo, h.value) for h in c.hashes)
        pip_hashes = sorted(_pip_link_hashes(link))
        assert our_hashes == pip_hashes, (
            f"{fixture_name}/{filename}: hash diff — "
            f"ours={our_hashes} pip={pip_hashes}"
        )

        assert c.requires_python == _normalise_pip_requires_python(link), (
            f"{fixture_name}/{filename}: requires_python diff — "
            f"ours={c.requires_python!r} pip={link.requires_python!r}"
        )

        assert c.yanked == bool(link.is_yanked), (
            f"{fixture_name}/{filename}: yanked diff — "
            f"ours={c.yanked} pip={link.is_yanked} "
            f"(pip yanked_reason={link.yanked_reason!r})"
        )

        assert c.yanked_reason == _normalise_pip_yanked_reason(link), (
            f"{fixture_name}/{filename}: yanked_reason diff — "
            f"ours={c.yanked_reason!r} pip={link.yanked_reason!r}"
        )
