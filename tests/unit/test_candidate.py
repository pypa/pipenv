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
