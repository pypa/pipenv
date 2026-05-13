"""Focused RED→GREEN tests for :class:`PurePythonProvider` methods
(Initiative G phase 3, T3 + T4 + T5).

Scope: T3 (``identify``) + T4 (``find_matches``) + T5
(``get_preference``).  T13 will extend this file with full per-method
coverage of ``is_satisfied_by`` and ``get_dependencies`` (T6 + T7
deliverables).

T3 bullets:

1. ``identify(Requirement(name="django", extras=frozenset({"argon2"}), ...))``
   returns ``("django", frozenset({"argon2"}))``.
2. ``identify(Candidate(name="django", ...))`` returns
   ``("django", frozenset())``.
3. Round-trip equality — two requirements with the same name + extras
   produce equal ``identify`` outputs (this is the ``resolvelib``
   contract: same identifier = same identity bucket).

T4 bullets (per ``initiative-g-phase3-plan.md`` T4 validation matrix):

1. Mock cache returns 5 :class:`Candidate`\\ s for ``django``;
   ``find_matches`` with specifier ``>=4.0`` returns only those with
   version ≥ 4.0, highest first.
2. Mock cache returns 0 candidates; ``find_matches`` returns an empty
   iterable without raising.
3. ``incompatibilities`` filter: pass one of the returned candidates as
   incompatible; it is excluded from the output.
4. ``requires_python`` filter: a candidate whose ``requires_python`` is
   incompatible with ``target_env["python_version"]`` is excluded.

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


def _make_provider(
    *,
    cache: Any = None,
    fetcher: Any = None,
    metadata_fetcher: Any = None,
    target_env: Any = None,
    index_urls: list[str] | None = None,
    allow_prereleases: bool = False,
):
    """Construct a :class:`PurePythonProvider` with dummy dependencies.

    T3 doesn't touch the cache / fetcher / metadata_fetcher / target_env
    fields (later tasks will), so simple sentinels suffice.  T4 adds
    ``index_urls`` + ``allow_prereleases`` keyword arguments — both
    default to a one-element list (``["https://pypi.org/simple"]``) and
    ``False`` so existing T3 tests construct without changes."""
    from pipenv.resolver.pure_python_provider import PurePythonProvider

    return PurePythonProvider(
        cache=object() if cache is None else cache,
        fetcher=object() if fetcher is None else fetcher,
        metadata_fetcher=(
            object() if metadata_fetcher is None else metadata_fetcher
        ),
        target_env={} if target_env is None else target_env,
        index_urls=(
            ["https://pypi.org/simple"] if index_urls is None else index_urls
        ),
        allow_prereleases=allow_prereleases,
    )


# ---------------------------------------------------------------------------
# T4 helpers — fake cache + fetcher
# ---------------------------------------------------------------------------


class _FakeCache:
    """In-memory stand-in for :class:`ParsedManifestCache`.

    Behaves like the real ``cache.get(index_url, package_name)``: returns
    ``None`` on miss, a tiny stand-in for :class:`CachedManifest`
    (anything exposing ``.candidates``) on hit.

    Tests seed ``_data`` directly with ``{(index_url, name): tuple(cands)}``.
    """

    class _Manifest:
        __slots__ = ("candidates",)

        def __init__(self, candidates):
            self.candidates = tuple(candidates)

    def __init__(self, data=None):
        self._data: dict[tuple[str, str], tuple] = dict(data or {})
        self.get_calls: list[tuple[str, str]] = []

    def get(self, index_url: str, package_name: str):
        self.get_calls.append((index_url, package_name))
        cands = self._data.get((index_url, package_name))
        if cands is None:
            return None
        return self._Manifest(cands)

    def seed(self, index_url: str, package_name: str, candidates) -> None:
        self._data[(index_url, package_name)] = tuple(candidates)


class _FakeFetcher:
    """In-memory stand-in for :class:`ParallelFetcher`.

    ``populate(targets)`` records the targets it was asked to fetch and
    seeds the linked cache from a pre-supplied ``_payload`` map of
    ``{(index_url, name): tuple(cands)}``.  T4's find_matches will call
    ``self._fetcher.populate(...)`` on cache miss; the test asserts on
    ``populate_calls`` and on the post-call cache contents.
    """

    def __init__(self, cache: _FakeCache, payload=None):
        self._cache = cache
        self._payload: dict[tuple[str, str], tuple] = dict(payload or {})
        self.populate_calls: list[list[tuple[str, str]]] = []

    def populate(self, targets):
        target_list = list(targets)
        self.populate_calls.append(target_list)
        for index_url, name in target_list:
            cands = self._payload.get((index_url, name))
            if cands is not None:
                self._cache.seed(index_url, name, cands)
        return {}


def _cand(
    *,
    name: str = "django",
    version: str = "4.2.0",
    requires_python: str | None = None,
    is_wheel: bool = True,
    extras: frozenset[str] = frozenset(),
):
    """Build a :class:`Candidate` for T4 tests with the four fields
    ``find_matches`` actually reads (``name``, ``version``,
    ``requires_python``, ``extras``) parameterised and the rest pinned
    to inert defaults."""
    from pipenv.resolver.candidate import Candidate

    suffix = "py3-none-any.whl" if is_wheel else "tar.gz"
    filename = f"{name}-{version}-{suffix}" if is_wheel else f"{name}-{version}.tar.gz"
    return Candidate(
        name=name,
        version=version,
        url=f"https://example.org/{filename}",
        filename=filename,
        hashes=frozenset(),
        requires_python=requires_python,
        yanked=False,
        yanked_reason=None,
        upload_time=None,
        is_wheel=is_wheel,
        wheel_tags=None,
        extras=extras,
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


# ---------------------------------------------------------------------------
# T4 validation matrix — one test per bullet
# ---------------------------------------------------------------------------


_INDEX = "https://pypi.org/simple"


class TestFindMatchesSpecifierFilter:
    """Bullet 1: with 5 cached candidates and a ``>=4.0`` specifier,
    only the candidates with version ≥ 4.0 are returned, ordered
    highest-version-first."""

    def test_specifier_filter_returns_high_version_first(self):
        cands = [
            _cand(name="django", version="3.2.0"),
            _cand(name="django", version="4.0.0"),
            _cand(name="django", version="4.1.0"),
            _cand(name="django", version="4.2.0"),
            _cand(name="django", version="5.0.0"),
        ]
        cache = _FakeCache({(_INDEX, "django"): tuple(cands)})
        provider = _make_provider(cache=cache, index_urls=[_INDEX])

        identifier = ("django", frozenset())
        req = _make_requirement(name="django", spec=">=4.0")
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={},
            )
        )

        versions = [c.version for c in result]
        # 3.2.0 is filtered; remaining four returned high-version-first.
        assert versions == ["5.0.0", "4.2.0", "4.1.0", "4.0.0"]


class TestFindMatchesEmpty:
    """Bullet 2: with an empty cache (zero candidates), ``find_matches``
    returns an empty iterable and does not raise.

    The cache lookup miss path triggers ``fetcher.populate`` — which we
    stub to also return zero candidates so the second cache read also
    misses.  No exception."""

    def test_empty_cache_returns_empty_without_raise(self):
        cache = _FakeCache()
        fetcher = _FakeFetcher(cache, payload={})
        provider = _make_provider(
            cache=cache, fetcher=fetcher, index_urls=[_INDEX]
        )

        identifier = ("django", frozenset())
        req = _make_requirement(name="django", spec=">=4.0")
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={},
            )
        )
        assert result == []
        # ``populate`` was invoked because the cache was cold.
        assert fetcher.populate_calls == [[(_INDEX, "django")]]


class TestFindMatchesIncompatibilitiesFilter:
    """Bullet 3: a candidate listed in ``incompatibilities`` is excluded
    from the result.

    Match keys on ``(name, version, filename)`` so the incompatible
    candidate doesn't need to be the same Python object as the cached
    one — same identity tuple is enough.
    """

    def test_incompatible_candidate_excluded(self):
        cands = [
            _cand(name="django", version="4.0.0"),
            _cand(name="django", version="4.1.0"),
            _cand(name="django", version="4.2.0"),
        ]
        cache = _FakeCache({(_INDEX, "django"): tuple(cands)})
        provider = _make_provider(cache=cache, index_urls=[_INDEX])

        identifier = ("django", frozenset())
        req = _make_requirement(name="django", spec=">=4.0")
        # Use the same candidate object so dedup keys line up.
        incompat = cands[1]  # 4.1.0
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={identifier: iter([incompat])},
            )
        )
        versions = [c.version for c in result]
        assert versions == ["4.2.0", "4.0.0"]


class TestFindMatchesRequiresPythonFilter:
    """Bonus bullet: a candidate whose ``requires_python`` excludes the
    target ``python_version`` is filtered out.

    Target env is ``python_version="3.12"``; candidate advertises
    ``requires_python=">=4.0"`` so it should be dropped.  A second
    candidate with no ``requires_python`` advertisement remains.
    """

    def test_requires_python_incompatible_excluded(self):
        cands = [
            _cand(name="django", version="5.0.0", requires_python=">=4.0"),
            _cand(name="django", version="4.2.0", requires_python=None),
            _cand(name="django", version="4.0.0", requires_python=">=3.10"),
        ]
        cache = _FakeCache({(_INDEX, "django"): tuple(cands)})
        provider = _make_provider(
            cache=cache,
            index_urls=[_INDEX],
            target_env={"python_version": "3.12"},
        )

        identifier = ("django", frozenset())
        req = _make_requirement(name="django", spec=">=4.0")
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={},
            )
        )
        versions = [c.version for c in result]
        # 5.0.0 is excluded (requires_python=">=4.0" rejects "3.12").
        # 4.2.0 (no requires_python) and 4.0.0 (>=3.10 accepts 3.12) remain.
        assert versions == ["4.2.0", "4.0.0"]


# ---------------------------------------------------------------------------
# T5 — get_preference (Q-C strict mirror of pip's tuple shape)
# ---------------------------------------------------------------------------


def _ri(requirement, parent=None):
    """Build a ``RequirementInformation`` namedtuple as ``resolvelib``
    hands one to ``get_preference``.

    The vendored ``resolvelib.structs.RequirementInformation`` is a
    ``namedtuple("RequirementInformation", ["requirement", "parent"])``
    — we instantiate the vendored type so the tests exercise the same
    shape ``resolvelib.Resolver`` produces at runtime.
    """
    from pipenv.patched.pip._vendor.resolvelib.structs import (
        RequirementInformation,
    )

    return RequirementInformation(requirement=requirement, parent=parent)


class TestGetPreferencePinnedVsRange:
    """Bullet 1 (per plan T5 validation matrix): a pinned requirement
    (``==4.0.1``) sorts before a range requirement (``>=4.0``).

    Q-C strict mirror: in pip's tuple, ``not pinned`` is one of the
    leading components — ``False < True``, so pinned (False) sorts
    before non-pinned (True).  Our mirror keeps the same ordering.
    """

    def test_pinned_sorts_before_range(self):
        provider = _make_provider()
        pinned_id = ("alpha", frozenset())
        range_id = ("beta", frozenset())
        pinned_req = _make_requirement(name="alpha", spec="==4.0.1")
        range_req = _make_requirement(name="beta", spec=">=4.0")
        information = {
            pinned_id: iter([_ri(pinned_req)]),
            range_id: iter([_ri(range_req)]),
        }
        pref_pinned = provider.get_preference(
            pinned_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        # Rebuild information — iterators are one-shot.
        information = {
            pinned_id: iter([_ri(pinned_req)]),
            range_id: iter([_ri(range_req)]),
        }
        pref_range = provider.get_preference(
            range_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        assert pref_pinned < pref_range

    def test_wildcard_eq_is_not_pinned(self):
        """``==4.*`` is a wildcard equality — pip treats it as
        upper-bounded, not pinned.  Mirror that: a wildcard-equality
        requirement does NOT get the pinned-first preference."""
        provider = _make_provider()
        wildcard_id = ("alpha", frozenset())
        pinned_id = ("beta", frozenset())
        wildcard_req = _make_requirement(name="alpha", spec="==4.*")
        pinned_req = _make_requirement(name="beta", spec="==4.0.1")
        information = {
            wildcard_id: iter([_ri(wildcard_req)]),
            pinned_id: iter([_ri(pinned_req)]),
        }
        pref_wildcard = provider.get_preference(
            wildcard_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        information = {
            wildcard_id: iter([_ri(wildcard_req)]),
            pinned_id: iter([_ri(pinned_req)]),
        }
        pref_pinned = provider.get_preference(
            pinned_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        # Pinned (==4.0.1, no wildcard) sorts before wildcard (==4.*).
        assert pref_pinned < pref_wildcard


class TestGetPreferencePipfileVsTransitive:
    """Bullet 2: a Pipfile-direct requirement sorts before a transitive
    requirement on the same axis.

    Note on Q-C strict mirror: pip's "direct" component refers to
    ``ExplicitRequirement`` (URL-based / direct-reference requirements),
    NOT Pipfile-direct.  Our typed :class:`Requirement` doesn't model
    URL-direct yet (T1 only encodes ``source`` ∈
    ``{"pipfile", "transitive", "constraint"}``), so we mirror pip's
    "direct" slot by treating ``source == "pipfile"`` as the
    closest-available analog — this is the design-doc summary's
    rendering of the same idea (see plan T5 + design §5.3).  When T1
    gains a URL-direct shape (Phase 4 work), the parity-divergence
    note in the T5 plan entry tracks the upgrade.
    """

    def test_pipfile_sorts_before_transitive(self):
        provider = _make_provider()
        pipfile_id = ("alpha", frozenset())
        transitive_id = ("beta", frozenset())
        pipfile_req = _make_requirement(
            name="alpha", spec=">=1.0", source="pipfile"
        )
        transitive_req = _make_requirement(
            name="beta",
            spec=">=1.0",
            source="transitive",
            parent="some-parent",
        )
        information = {
            pipfile_id: iter([_ri(pipfile_req)]),
            transitive_id: iter([_ri(transitive_req)]),
        }
        pref_pipfile = provider.get_preference(
            pipfile_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        information = {
            pipfile_id: iter([_ri(pipfile_req)]),
            transitive_id: iter([_ri(transitive_req)]),
        }
        pref_transitive = provider.get_preference(
            transitive_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        assert pref_pipfile < pref_transitive


class TestGetPreferenceBacktrackCount:
    """Bullet 3: an identifier appearing 3 times in ``backtrack_causes``
    sorts AFTER one appearing 0 times.

    Q-C strict mirror caveat: pip itself doesn't put the raw count in
    its preference tuple — it uses a separate ``_conflict_promoted``
    set populated by ``narrow_requirement_selection`` and exposes the
    boolean ``not conflict_promoted`` at the head of the tuple.  We
    don't ship ``narrow_requirement_selection`` yet (no T-task assigned
    in Phase 3), so we render the same ordering signal directly off
    the ``backtrack_causes`` arg.  Recorded in the parity-divergence
    bullet on the T5 plan entry.
    """

    def test_more_backtracks_sorts_later(self):
        provider = _make_provider()
        causing_id = ("alpha", frozenset())
        clean_id = ("beta", frozenset())
        causing_req = _make_requirement(name="alpha", spec=">=1.0")
        clean_req = _make_requirement(name="beta", spec=">=1.0")
        # ``alpha`` shows up 3x in backtrack_causes; ``beta`` 0x.
        backtrack_causes = (
            _ri(causing_req),
            _ri(causing_req),
            _ri(causing_req),
        )
        information = {
            causing_id: iter([_ri(causing_req)]),
            clean_id: iter([_ri(clean_req)]),
        }
        pref_causing = provider.get_preference(
            causing_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=backtrack_causes,
        )
        information = {
            causing_id: iter([_ri(causing_req)]),
            clean_id: iter([_ri(clean_req)]),
        }
        pref_clean = provider.get_preference(
            clean_id,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=backtrack_causes,
        )
        # Backtrack-causing identifier sorts AFTER the clean one.
        assert pref_clean < pref_causing


class TestGetPreferenceLexicographicTieBreak:
    """Bonus bullet: identifiers that tie on every other axis fall
    back to alphabetical name order — same as pip's tuple's trailing
    ``identifier`` component.  Stable order across runs is what makes
    lockfile output deterministic (the Q-C parity gate's eventual
    requirement)."""

    def test_alphabetical_order_on_full_tie(self):
        provider = _make_provider()
        id_a = ("alpha", frozenset())
        id_b = ("beta", frozenset())
        req_a = _make_requirement(name="alpha", spec=">=1.0")
        req_b = _make_requirement(name="beta", spec=">=1.0")
        information = {
            id_a: iter([_ri(req_a)]),
            id_b: iter([_ri(req_b)]),
        }
        pref_a = provider.get_preference(
            id_a,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        information = {
            id_a: iter([_ri(req_a)]),
            id_b: iter([_ri(req_b)]),
        }
        pref_b = provider.get_preference(
            id_b,
            resolutions={},
            candidates={},
            information=information,
            backtrack_causes=(),
        )
        assert pref_a < pref_b


class TestGetPreferenceEmptyInformation:
    """Defensive: ``get_preference`` is callable with no information for
    the identifier (``resolvelib`` can do this transiently between
    state transitions).  Should not raise, should return a sortable
    tuple whose pinned / direct flags reflect "unknown" (treated as
    not-pinned / not-direct, matching pip's ``has_information=False``
    branch)."""

    def test_no_information_returns_sortable_tuple(self):
        provider = _make_provider()
        identifier = ("alpha", frozenset())
        # Empty iterator — same shape pip's ``has_information`` branch
        # protects against.
        pref = provider.get_preference(
            identifier,
            resolutions={},
            candidates={},
            information={identifier: iter([])},
            backtrack_causes=(),
        )
        # Just confirm we got a tuple back that's orderable against
        # another preference tuple (same shape).
        other_id = ("beta", frozenset())
        other_req = _make_requirement(name="beta", spec="==1.0")
        other_pref = provider.get_preference(
            other_id,
            resolutions={},
            candidates={},
            information={other_id: iter([_ri(other_req)])},
            backtrack_causes=(),
        )
        # Comparison must succeed (orderable).  The pinned-beta sorts
        # before the unknown-alpha.
        assert other_pref < pref
