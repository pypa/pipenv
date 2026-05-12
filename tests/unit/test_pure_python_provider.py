"""Focused RED→GREEN tests for :class:`PurePythonProvider.identify`
(Initiative G phase 3, T3).

Scope: T3 only.  Each of the three tests below pins exactly one bullet
from the T3 validation matrix in
``initiative-g-phase3-plan.md``:

1. ``identify(Requirement(name="django", extras=frozenset({"argon2"}), ...))``
   returns ``("django", frozenset({"argon2"}))``.
2. ``identify(Candidate(name="django", ...))`` returns
   ``("django", frozenset())``.
3. Round-trip equality — two requirements with the same name + extras
   produce equal ``identify`` outputs (this is the ``resolvelib``
   contract: same identifier = same identity bucket).

T13 extends this file with per-method coverage of ``find_matches``,
``get_preference``, ``is_satisfied_by``, and ``get_dependencies``
(those are T4–T7 deliverables).

All ``packaging`` imports come from :mod:`pipenv.vendor.packaging`
(vendored, not patched pip).  Zero ``pip._internal.*`` imports are
permitted in this test file or the module it exercises — the Phase 1
pre-commit gate enforces the constraint on the module; this file
mirrors the discipline for consistency.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_requirement(
    *,
    name: str = "django",
    spec: str = "",
    extras: frozenset[str] = frozenset(),
    source: str = "pipfile",
    parent: str | None = None,
):
    """Build a :class:`Requirement` with one knob per axis the test
    cares about.  Keeps the test bodies focused on the identifier
    contract rather than on dataclass-construction ceremony.
    """
    from pipenv.resolver.pure_python_requirement import Requirement
    from pipenv.vendor.packaging.specifiers import SpecifierSet

    return Requirement(
        name=name,
        specifier=SpecifierSet(spec),
        extras=extras,
        marker=None,
        source=source,  # type: ignore[arg-type]
        parent=parent,
    )


def _make_candidate(
    *,
    name: str = "django",
    version: str = "4.2.0",
    extras: frozenset[str] | None = None,
):
    """Build a :class:`Candidate` with the minimum-viable fields the
    provider's ``identify`` reads.  ``extras`` is forwarded only when
    the caller supplies a non-``None`` value so we exercise the
    default-factory path (no kwarg) AND the explicit-kwarg path."""
    from pipenv.resolver.candidate import Candidate

    kwargs: dict[str, Any] = {
        "name": name,
        "version": version,
        "url": f"https://example.org/{name}-{version}-py3-none-any.whl",
        "filename": f"{name}-{version}-py3-none-any.whl",
        "hashes": frozenset(),
        "requires_python": None,
        "yanked": False,
        "yanked_reason": None,
        "upload_time": None,
        "is_wheel": True,
        "wheel_tags": None,
    }
    if extras is not None:
        kwargs["extras"] = extras
    return Candidate(**kwargs)


def _make_provider():
    """Construct a :class:`PurePythonProvider` with dummy dependencies.

    T3 doesn't touch the cache / fetcher / metadata_fetcher / target_env
    fields (later tasks will), so simple sentinels suffice.  Recording
    them on the instance is enough to verify ``__init__`` stores them
    without further unit-testing T4–T7 here."""
    from pipenv.resolver.pure_python_provider import PurePythonProvider

    return PurePythonProvider(
        cache=object(),
        fetcher=object(),
        metadata_fetcher=object(),
        target_env={},
    )


# ---------------------------------------------------------------------------
# T3 validation matrix — one test per bullet
# ---------------------------------------------------------------------------


class TestIdentifyRequirement:
    """Bullet 1: ``identify`` on a :class:`Requirement` returns
    ``(canonical_name, frozenset(extras))``."""

    def test_requirement_with_extras_returns_name_and_extras(self):
        provider = _make_provider()
        req = _make_requirement(
            name="django", extras=frozenset({"argon2"})
        )
        assert provider.identify(req) == ("django", frozenset({"argon2"}))

    def test_requirement_without_extras_returns_empty_frozenset(self):
        provider = _make_provider()
        req = _make_requirement(name="requests", extras=frozenset())
        assert provider.identify(req) == ("requests", frozenset())

    def test_requirement_with_multiple_extras_returns_all(self):
        provider = _make_provider()
        req = _make_requirement(
            name="django", extras=frozenset({"argon2", "bcrypt"})
        )
        assert provider.identify(req) == (
            "django",
            frozenset({"argon2", "bcrypt"}),
        )


class TestIdentifyCandidate:
    """Bullet 2: ``identify`` on a :class:`Candidate` returns
    ``(name, frozenset())`` when the candidate carries no extras.

    The Phase 1 ``Candidate`` shape didn't have an ``extras`` field;
    T3 widens it with a default-factory ``frozenset()`` so existing
    construction sites stay non-breaking.  This test pins both paths:
    the default-factory case (no kwarg) and the explicit-empty case."""

    def test_candidate_default_extras_returns_empty_frozenset(self):
        provider = _make_provider()
        cand = _make_candidate(name="django")
        assert provider.identify(cand) == ("django", frozenset())

    def test_candidate_explicit_empty_extras_returns_empty_frozenset(self):
        provider = _make_provider()
        cand = _make_candidate(name="django", extras=frozenset())
        assert provider.identify(cand) == ("django", frozenset())


class TestIdentifyRoundTripEquality:
    """Bullet 3: two requirements with the same name + extras have
    equal ``identify`` outputs.  This is the load-bearing ``resolvelib``
    invariant — same identifier = same identity bucket in the dep graph.

    We also pin the symmetrical claim that a :class:`Requirement` and a
    :class:`Candidate` with the same ``(name, extras)`` produce equal
    identifiers — that's what lets ``resolvelib`` match candidates back
    to requirements via the shared key.
    """

    def test_two_requirements_same_name_same_extras_equal_identify(self):
        provider = _make_provider()
        req1 = _make_requirement(
            name="django", extras=frozenset({"argon2"})
        )
        req2 = _make_requirement(
            name="django",
            spec=">=4.0",  # different specifier — identifier should be
            # spec-agnostic
            extras=frozenset({"argon2"}),
            source="transitive",  # different source — identifier should
            # also be source-agnostic
        )
        assert provider.identify(req1) == provider.identify(req2)

    def test_two_requirements_same_name_different_extras_distinct(self):
        """Different extras → different identifier.  Mirrors pip's
        grouping where ``django`` and ``django[argon2]`` are distinct
        graph nodes."""
        provider = _make_provider()
        req1 = _make_requirement(name="django", extras=frozenset())
        req2 = _make_requirement(
            name="django", extras=frozenset({"argon2"})
        )
        assert provider.identify(req1) != provider.identify(req2)

    def test_requirement_and_candidate_same_name_extras_equal_identify(self):
        """Cross-shape equality: a requirement and a candidate sharing
        the ``(name, extras)`` pair produce the same identifier.  This
        is what lets ``resolvelib`` route a candidate back to the
        requirement bucket that asked for it."""
        provider = _make_provider()
        req = _make_requirement(name="django", extras=frozenset())
        cand = _make_candidate(name="django")
        assert provider.identify(req) == provider.identify(cand)
