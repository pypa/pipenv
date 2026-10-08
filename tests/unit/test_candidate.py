"""Smoke tests for :mod:`pipenv.resolver.candidate` (Initiative G phase 1, T1).

Full coverage of :class:`Candidate` is owned by T11 in the Initiative G
phase-1 plan.  This file is the RED-then-GREEN evidence for T1 only —
it pins the acceptance-criteria surface (construction, frozen
enforcement, :meth:`Candidate.from_filename` wheel/sdist branching, and
:class:`Hash` namedtuple equality / frozenset membership) and is
deliberately kept smoke-level so T11 can grow the suite without
clashing.
"""
from __future__ import annotations

import dataclasses

import pytest


# ---------------------------------------------------------------------------
# Construction + frozen enforcement
# ---------------------------------------------------------------------------


class TestCandidateConstruction:
    def test_construct_with_all_required_kwargs(self):
        from pipenv.resolver.candidate import Candidate

        c = Candidate(
            name="numpy",
            version="1.26.0",
            url="https://example.org/numpy.whl",
            filename="numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            hashes=frozenset(),
            requires_python=">=3.9",
            yanked=False,
            yanked_reason=None,
            upload_time=None,
            is_wheel=True,
            wheel_tags=None,
        )
        assert c.name == "numpy"
        assert c.version == "1.26.0"
        assert c.url == "https://example.org/numpy.whl"
        assert c.filename == "numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl"
        assert c.hashes == frozenset()
        assert c.requires_python == ">=3.9"
        assert c.yanked is False
        assert c.yanked_reason is None
        assert c.upload_time is None
        assert c.is_wheel is True
        assert c.wheel_tags is None

    def test_frozen_mutation_raises(self):
        from pipenv.resolver.candidate import Candidate

        c = Candidate(
            name="six",
            version="1.16.0",
            url="https://example.org/six.whl",
            filename="six-1.16.0-py2.py3-none-any.whl",
            hashes=frozenset(),
            requires_python=None,
            yanked=False,
            yanked_reason=None,
            upload_time=None,
            is_wheel=True,
            wheel_tags=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.name = "seven"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Candidate.from_filename
# ---------------------------------------------------------------------------


class TestFromFilename:
    def test_wheel_branch_populates_tags(self):
        from pipenv.resolver.candidate import Candidate

        filename = "numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl"
        c = Candidate.from_filename(
            filename,
            name="numpy",
            version="1.26.0",
            url="https://example.org/numpy.whl",
            filename=filename,
            hashes=frozenset(),
            requires_python=">=3.9",
            yanked=False,
            yanked_reason=None,
            upload_time=None,
        )
        assert c.is_wheel is True
        assert c.wheel_tags is not None
        assert len(c.wheel_tags) >= 1

    def test_pure_python_wheel_tags_parsed(self):
        from pipenv.resolver.candidate import Candidate

        filename = "six-1.16.0-py2.py3-none-any.whl"
        c = Candidate.from_filename(
            filename,
            name="six",
            version="1.16.0",
            url="https://example.org/six.whl",
            filename=filename,
            hashes=frozenset(),
            requires_python=None,
            yanked=False,
            yanked_reason=None,
            upload_time=None,
        )
        assert c.is_wheel is True
        assert c.wheel_tags is not None
        # py2.py3-none-any has 2 compressed pythons -> 2 tags after expansion
        assert len(c.wheel_tags) == 2

    def test_sdist_branch_no_tags(self):
        from pipenv.resolver.candidate import Candidate

        filename = "tablib-3.5.0.tar.gz"
        c = Candidate.from_filename(
            filename,
            name="tablib",
            version="3.5.0",
            url="https://example.org/tablib.tar.gz",
            filename=filename,
            hashes=frozenset(),
            requires_python=">=3.8",
            yanked=False,
            yanked_reason=None,
            upload_time=None,
        )
        assert c.is_wheel is False
        assert c.wheel_tags is None


# ---------------------------------------------------------------------------
# Hash namedtuple
# ---------------------------------------------------------------------------


class TestHashNamedTuple:
    def test_equality(self):
        from pipenv.resolver.candidate import Hash

        a = Hash(algo="sha256", value="abc123")
        b = Hash(algo="sha256", value="abc123")
        c = Hash(algo="sha256", value="def456")
        assert a == b
        assert a != c

    def test_frozenset_membership(self):
        from pipenv.resolver.candidate import Hash

        h1 = Hash("sha256", "aaa")
        h2 = Hash("sha256", "bbb")
        h1_dup = Hash("sha256", "aaa")
        s = frozenset([h1, h2, h1_dup])
        assert len(s) == 2
        assert Hash("sha256", "aaa") in s
        assert Hash("sha256", "ccc") not in s

    def test_positional_construction(self):
        from pipenv.resolver.candidate import Hash

        h = Hash("sha256", "feedface")
        assert h.algo == "sha256"
        assert h.value == "feedface"
        # Tuple-compatible
        assert h[0] == "sha256"
        assert h[1] == "feedface"


# ---------------------------------------------------------------------------
# T11 additions — full coverage of pipenv/resolver/candidate.py
# ---------------------------------------------------------------------------
#
# These tests EXTEND the 8 smoke tests above to drive coverage of
# ``pipenv/resolver/candidate.py`` to >=95 %.  They cover:
#
#   1. All-fields construction (every field non-default, round-tripped).
#   2. Equality semantics (frozen dataclass auto-eq) + hash equality.
#   3. Hashability for set / dict use.
#   4. ``Hash`` equality with plain tuples + frozenset symmetry.
#   5. ``Candidate.from_filename`` wheel-tag derivation across every
#      platform-tag form pipenv users encounter (manylinux1/2014, PEP 600
#      manylinux_X_Y, musllinux, macosx, win_amd64, pure-Python,
#      cp311-abi3, non-manylinux linux).
#   6. ``Candidate.from_filename`` sdist branch for ``.tar.gz`` and
#      ``.zip`` artifacts.
#   7. Edge cases (malformed wheel filename, requires_python=None,
#      yanked=True with yanked_reason=None).
#
# Test style matches T1: class-grouped, plain pytest asserts, no
# ``pip._internal`` imports.  All ``packaging`` imports come from
# :mod:`pipenv.vendor.packaging` (vendored, not patched pip).


# ---------------------------------------------------------------------------
# 1. All-fields construction
# ---------------------------------------------------------------------------


class TestAllFieldsConstruction:
    def test_all_fields_non_default_round_trip(self):
        """Every field set to a non-default value survives attribute
        access (no silent coercion, no field swap)."""
        from datetime import datetime, timezone

        from pipenv.vendor.packaging.tags import Tag

        from pipenv.resolver.candidate import Candidate, Hash

        hashes = frozenset({Hash("sha256", "abc"), Hash("sha512", "def")})
        wheel_tags = frozenset(
            {Tag("cp311", "cp311", "manylinux_2_17_x86_64")}
        )
        upload = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        c = Candidate(
            name="numpy",
            version="1.26.0",
            url="https://example.org/numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            filename="numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            hashes=hashes,
            requires_python=">=3.10",
            yanked=True,
            yanked_reason="security advisory",
            upload_time=upload,
            is_wheel=True,
            wheel_tags=wheel_tags,
        )

        assert c.name == "numpy"
        assert c.version == "1.26.0"
        assert c.url == (
            "https://example.org/numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl"
        )
        assert c.filename == "numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl"
        assert c.hashes is hashes
        assert c.requires_python == ">=3.10"
        assert c.yanked is True
        assert c.yanked_reason == "security advisory"
        assert c.upload_time == upload
        assert c.is_wheel is True
        assert c.wheel_tags is wheel_tags


# ---------------------------------------------------------------------------
# 2. Equality semantics
# ---------------------------------------------------------------------------


def _candidate_kwargs():
    """Helper: kwargs for two byte-identical candidates."""
    from pipenv.resolver.candidate import Hash

    return dict(
        name="numpy",
        version="1.26.0",
        url="https://example.org/numpy.whl",
        filename="numpy-1.26.0-cp311-cp311-manylinux_2_17_x86_64.whl",
        hashes=frozenset({Hash("sha256", "abc")}),
        requires_python=">=3.9",
        yanked=False,
        yanked_reason=None,
        upload_time=None,
        is_wheel=True,
        wheel_tags=None,
    )


class TestEqualitySemantics:
    def test_identical_fields_are_equal_and_hash_equal(self):
        """Two ``Candidate``s with identical field values are ``==``
        AND produce the same ``hash(c)``.  Pinned explicitly so a future
        field-order or ``@dataclass`` flag change can't silently break
        set / dict semantics."""
        from pipenv.resolver.candidate import Candidate

        c1 = Candidate(**_candidate_kwargs())
        c2 = Candidate(**_candidate_kwargs())
        assert c1 == c2
        assert hash(c1) == hash(c2)

    def test_one_field_different_means_unequal(self):
        from pipenv.resolver.candidate import Candidate

        kwargs = _candidate_kwargs()
        c1 = Candidate(**kwargs)
        kwargs["version"] = "1.26.1"
        c2 = Candidate(**kwargs)
        assert c1 != c2

    def test_name_difference_means_unequal(self):
        from pipenv.resolver.candidate import Candidate

        kwargs = _candidate_kwargs()
        c1 = Candidate(**kwargs)
        kwargs["name"] = "scipy"
        c2 = Candidate(**kwargs)
        assert c1 != c2


# ---------------------------------------------------------------------------
# 3. Hashability for set / dict use
# ---------------------------------------------------------------------------


class TestHashabilityForSetDictUse:
    def test_set_dedupes_equal_candidates(self):
        from pipenv.resolver.candidate import Candidate

        c1 = Candidate(**_candidate_kwargs())
        c1_copy = Candidate(**_candidate_kwargs())
        s = {c1, c1_copy}
        assert len(s) == 1

    def test_candidate_usable_as_dict_key(self):
        from pipenv.resolver.candidate import Candidate

        c = Candidate(**_candidate_kwargs())
        c_copy = Candidate(**_candidate_kwargs())
        d = {c: "value"}
        assert d[c_copy] == "value"


# ---------------------------------------------------------------------------
# 4. Hash equality with plain tuples + frozenset symmetry
# ---------------------------------------------------------------------------


class TestHashTupleEquality:
    def test_hash_equals_plain_tuple(self):
        """NamedTuple ↔ tuple structural equality — important for
        callers that pin Pipfile hashes as plain ``(algo, value)``
        pairs and want O(1) frozenset intersection against
        ``Candidate.hashes``."""
        from pipenv.resolver.candidate import Hash

        assert Hash("sha256", "abc") == ("sha256", "abc")

    def test_hash_in_frozenset_via_value_equality(self):
        from pipenv.resolver.candidate import Hash

        assert Hash("sha256", "abc") in frozenset({Hash("sha256", "abc")})


# ---------------------------------------------------------------------------
# 5. from_filename wheel-tag derivation across platform variants
# ---------------------------------------------------------------------------


def _build_wheel_candidate(filename: str):
    """Helper: invoke ``Candidate.from_filename`` with arbitrary but
    valid kwargs for every non-derived field.  We only care about
    ``is_wheel`` + ``wheel_tags`` for these tests."""
    from pipenv.resolver.candidate import Candidate

    return Candidate.from_filename(
        filename,
        name="example",
        version="1.0.0",
        url=f"https://example.org/{filename}",
        filename=filename,
        hashes=frozenset(),
        requires_python=None,
        yanked=False,
        yanked_reason=None,
        upload_time=None,
    )


class TestFromFilenameWheelTagVariants:
    """One assert per platform-tag form pipenv users encounter.  For
    each form we re-derive the expected ``frozenset[Tag]`` via
    :func:`pipenv.vendor.packaging.tags.parse_tag` (the same call site
    ``Candidate.from_filename`` uses) so the test pins the contract
    symmetrically without re-implementing tag expansion."""

    def test_legacy_manylinux2014(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-cp311-cp311-manylinux2014_x86_64.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("cp311-cp311-manylinux2014_x86_64")
        first = next(iter(c.wheel_tags))
        assert first.interpreter == "cp311"
        assert first.abi == "cp311"
        assert first.platform == "manylinux2014_x86_64"

    def test_pep600_manylinux_2_17(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-cp311-cp311-manylinux_2_17_x86_64.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("cp311-cp311-manylinux_2_17_x86_64")
        first = next(iter(c.wheel_tags))
        assert first.platform == "manylinux_2_17_x86_64"

    def test_musllinux(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-cp311-cp311-musllinux_1_2_x86_64.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("cp311-cp311-musllinux_1_2_x86_64")
        first = next(iter(c.wheel_tags))
        assert first.platform == "musllinux_1_2_x86_64"

    def test_macosx_arm64(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-cp311-cp311-macosx_11_0_arm64.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("cp311-cp311-macosx_11_0_arm64")
        first = next(iter(c.wheel_tags))
        assert first.platform == "macosx_11_0_arm64"

    def test_win_amd64(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-cp311-cp311-win_amd64.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("cp311-cp311-win_amd64")
        first = next(iter(c.wheel_tags))
        assert first.platform == "win_amd64"

    def test_pure_python_py3_none_any(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-py3-none-any.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("py3-none-any")
        first = next(iter(c.wheel_tags))
        assert first.interpreter == "py3"
        assert first.abi == "none"
        assert first.platform == "any"

    def test_stable_abi_abi3(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-cp311-abi3-manylinux_2_17_x86_64.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("cp311-abi3-manylinux_2_17_x86_64")
        first = next(iter(c.wheel_tags))
        assert first.abi == "abi3"

    def test_non_manylinux_linux(self):
        from pipenv.vendor.packaging.tags import parse_tag

        filename = "example-1.0.0-cp311-cp311-linux_x86_64.whl"
        c = _build_wheel_candidate(filename)
        assert c.is_wheel is True
        assert c.wheel_tags == parse_tag("cp311-cp311-linux_x86_64")
        first = next(iter(c.wheel_tags))
        assert first.platform == "linux_x86_64"

    def test_wheel_tags_is_nonempty_frozenset_for_every_variant(self):
        """Belt-and-braces: every platform form above yields a
        non-empty ``frozenset[Tag]`` (i.e. ``Candidate.from_filename``
        does not silently produce empty tag sets)."""
        for filename in [
            "example-1.0.0-cp311-cp311-manylinux2014_x86_64.whl",
            "example-1.0.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            "example-1.0.0-cp311-cp311-musllinux_1_2_x86_64.whl",
            "example-1.0.0-cp311-cp311-macosx_11_0_arm64.whl",
            "example-1.0.0-cp311-cp311-win_amd64.whl",
            "example-1.0.0-py3-none-any.whl",
            "example-1.0.0-cp311-abi3-manylinux_2_17_x86_64.whl",
            "example-1.0.0-cp311-cp311-linux_x86_64.whl",
        ]:
            c = _build_wheel_candidate(filename)
            assert c.is_wheel is True
            assert c.wheel_tags is not None
            assert isinstance(c.wheel_tags, frozenset)
            assert len(c.wheel_tags) >= 1


# ---------------------------------------------------------------------------
# 6. from_filename sdist branch
# ---------------------------------------------------------------------------


class TestFromFilenameSdist:
    def test_tar_gz_sdist(self):
        from pipenv.resolver.candidate import Candidate

        filename = "numpy-1.26.0.tar.gz"
        c = Candidate.from_filename(
            filename,
            name="numpy",
            version="1.26.0",
            url=f"https://example.org/{filename}",
            filename=filename,
            hashes=frozenset(),
            requires_python=">=3.9",
            yanked=False,
            yanked_reason=None,
            upload_time=None,
        )
        assert c.is_wheel is False
        assert c.wheel_tags is None

    def test_zip_sdist(self):
        from pipenv.resolver.candidate import Candidate

        filename = "tablib-3.6.0.zip"
        c = Candidate.from_filename(
            filename,
            name="tablib",
            version="3.6.0",
            url=f"https://example.org/{filename}",
            filename=filename,
            hashes=frozenset(),
            requires_python=">=3.8",
            yanked=False,
            yanked_reason=None,
            upload_time=None,
        )
        assert c.is_wheel is False
        assert c.wheel_tags is None


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_malformed_wheel_filename_raises_value_error(self):
        """Contract pinned by T1 (see ``pipenv/resolver/candidate.py``
        lines 153–172): wheel filenames that lack the
        ``<python>-<abi>-<platform>`` tag triple raise
        :class:`ValueError` rather than producing a tag-less
        ``Candidate``.  T1 chose option (a) — propagate / raise
        explicitly — on the grounds that a malformed wheel filename
        is a parser-side bug (T4/T5 must filter these before reaching
        here) and silently producing a tag-less wheel candidate would
        hide that bug downstream.  This test pins option (a)."""
        from pipenv.resolver.candidate import Candidate

        with pytest.raises(ValueError, match="malformed wheel filename"):
            Candidate.from_filename(
                "malformed.whl",
                name="malformed",
                version="0",
                url="https://example.org/malformed.whl",
                filename="malformed.whl",
                hashes=frozenset(),
                requires_python=None,
                yanked=False,
                yanked_reason=None,
                upload_time=None,
            )

    def test_requires_python_none_accepted(self):
        """Most candidates carry no ``requires_python`` — the field
        legitimately accepts ``None`` (e.g. legacy artifacts on PyPI)."""
        from pipenv.resolver.candidate import Candidate

        c = Candidate(
            name="example",
            version="1.0.0",
            url="https://example.org/example-1.0.0-py3-none-any.whl",
            filename="example-1.0.0-py3-none-any.whl",
            hashes=frozenset(),
            requires_python=None,
            yanked=False,
            yanked_reason=None,
            upload_time=None,
            is_wheel=True,
            wheel_tags=None,
        )
        assert c.requires_python is None

    def test_yanked_true_with_reason_none_accepted(self):
        """A candidate can be yanked without a reason — PEP 592 allows
        the bool form.  This pins that ``yanked=True`` and
        ``yanked_reason=None`` is a valid combination, not an
        invariant violation."""
        from pipenv.resolver.candidate import Candidate

        c = Candidate(
            name="example",
            version="1.0.0",
            url="https://example.org/example-1.0.0-py3-none-any.whl",
            filename="example-1.0.0-py3-none-any.whl",
            hashes=frozenset(),
            requires_python=None,
            yanked=True,
            yanked_reason=None,
            upload_time=None,
            is_wheel=True,
            wheel_tags=None,
        )
        assert c.yanked is True
        assert c.yanked_reason is None

    def test_from_filename_positional_drives_tag_derivation(self):
        """The positional ``__filename`` parameter is what drives
        wheel-tag derivation; if a caller also passes a ``filename``
        kwarg it wins for the STORED field but the positional is what
        :func:`parse_tag` sees.  This pins the contract documented in
        the method docstring."""
        from pipenv.resolver.candidate import Candidate

        # Positional is a real wheel filename; kwarg overrides the
        # stored value with a cosmetic alternative.  We assert the
        # stored filename matches the kwarg and that wheel_tags were
        # derived from the positional (i.e. populated, not None).
        c = Candidate.from_filename(
            "example-1.0.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            name="example",
            version="1.0.0",
            url="https://example.org/example.whl",
            filename="example-stored-name.whl",
            hashes=frozenset(),
            requires_python=None,
            yanked=False,
            yanked_reason=None,
            upload_time=None,
        )
        assert c.filename == "example-stored-name.whl"
        assert c.is_wheel is True
        assert c.wheel_tags is not None
        assert len(c.wheel_tags) >= 1


# ---------------------------------------------------------------------------
# T_M1 — Requires-Python end-to-end preservation (Initiative G Phase 3b)
# ---------------------------------------------------------------------------
#
# T_M3 emits ``markers="python_version >= '3.10'"`` on a ``LockedRequirement``
# whenever the resolved candidate carries a Requires-Python specifier.
# That round-trip depends on ``Candidate.requires_python`` flowing
# unchanged from the PEP 691 simple-API parse, through the candidate
# cache, into the resolver.  T_M1's audit confirmed the field already
# survives end-to-end (smoke: ``click 8.3.3`` came out with
# ``requires_python=">=3.10"``); the test below pins that behaviour so
# a future refactor cannot silently regress the field.


class TestRequiresPythonPreservation:
    """Pin :attr:`Candidate.requires_python` preservation through the
    PEP 691 simple-API parse — T_M3 emits its marker output from this
    field."""

    def test_candidate_requires_python_preserved_from_pep691_parse(self):
        """A synthetic PEP 691 JSON page with ``requires-python: ">=3.10"``
        on a single wheel entry yields a :class:`Candidate` whose
        :attr:`requires_python` equals the original string verbatim.

        Covers the parse-side of the T_M3 marker-emission dependency:
        the in-tree resolver reads ``candidate.requires_python``, so if
        the simple-API parser ever drops or normalises the field, the
        lockfile-marker output regresses silently.
        """
        import json

        from pipenv.resolver.pep691 import _parse_pep691_json

        page = {
            "meta": {"api-version": "1.0"},
            "name": "click",
            "files": [
                {
                    "filename": (
                        "click-8.3.3-py3-none-any.whl"
                    ),
                    "url": (
                        "https://files.pythonhosted.org/packages/ab/cd/"
                        "click-8.3.3-py3-none-any.whl"
                    ),
                    "hashes": {"sha256": "0" * 64},
                    "requires-python": ">=3.10",
                    "yanked": False,
                }
            ],
        }
        body = json.dumps(page).encode("utf-8")
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/click/"
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.name == "click"
        assert candidate.version == "8.3.3"
        # The exact string is what T_M3 will convert into
        # ``python_version >= '3.10'`` on the LockedRequirement entry.
        assert candidate.requires_python == ">=3.10"

    def test_candidate_requires_python_none_preserved_from_pep691_parse(
        self,
    ):
        """A PEP 691 page entry without ``requires-python`` produces
        :attr:`Candidate.requires_python` ``= None`` — T_M3 omits a
        ``python_version`` marker clause in that case."""
        import json

        from pipenv.resolver.pep691 import _parse_pep691_json

        page = {
            "meta": {"api-version": "1.0"},
            "name": "six",
            "files": [
                {
                    "filename": "six-1.16.0-py2.py3-none-any.whl",
                    "url": (
                        "https://files.pythonhosted.org/packages/ef/gh/"
                        "six-1.16.0-py2.py3-none-any.whl"
                    ),
                    "hashes": {"sha256": "1" * 64},
                    "yanked": False,
                }
            ],
        }
        body = json.dumps(page).encode("utf-8")
        candidates = _parse_pep691_json(
            body, "https://pypi.org/simple/six/"
        )

        assert len(candidates) == 1
        assert candidates[0].requires_python is None
