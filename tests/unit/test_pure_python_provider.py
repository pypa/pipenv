"""Focused RED→GREEN tests for :class:`PurePythonProvider` methods
(Initiative G phase 3, T3 + T4 + T5 + T6).

Scope: T3 (``identify``) + T4 (``find_matches``) + T5
(``get_preference``) + T6 (``is_satisfied_by``).  T13 will extend this
file with full per-method coverage of ``get_dependencies`` (T7
deliverable).

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
    yanked: bool = False,
    yanked_reason: str | None = None,
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
        yanked=yanked,
        yanked_reason=yanked_reason,
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


class TestFindMatchesYankedFilter:
    """PEP 592: yanked candidates are filtered from automatic selection
    unless the user explicitly pins to that exact version via ``==``.

    Regression test for the bench-fixture lock failure where
    ``sentry-relay==1.1.4`` (every artifact yanked with reason
    "accidental release") got picked as the highest-version match for
    the spec ``sentry-relay>=0.8.45`` and crashed the sdist build.
    Pip's resolver skips it; pure-python now does too.
    """

    def test_yanked_excluded_from_range_spec(self):
        cands = [
            _cand(name="sentry-relay", version="1.1.4", yanked=True),
            _cand(name="sentry-relay", version="0.9.27"),
            _cand(name="sentry-relay", version="0.8.45"),
        ]
        cache = _FakeCache({(_INDEX, "sentry-relay"): tuple(cands)})
        provider = _make_provider(cache=cache, index_urls=[_INDEX])
        identifier = ("sentry-relay", frozenset())
        req = _make_requirement(name="sentry-relay", spec=">=0.8.45")
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={},
            )
        )
        versions = [c.version for c in result]
        # 1.1.4 (yanked) must NOT appear; 0.9.27 sorts first, then 0.8.45.
        assert versions == ["0.9.27", "0.8.45"]

    def test_yanked_kept_when_exact_pinned(self):
        # An explicit ``==1.1.4`` pin opts in to the yanked release —
        # PEP 592 §"the user explicitly references it by version".
        cands = [
            _cand(name="sentry-relay", version="1.1.4", yanked=True),
            _cand(name="sentry-relay", version="0.9.27"),
        ]
        cache = _FakeCache({(_INDEX, "sentry-relay"): tuple(cands)})
        provider = _make_provider(cache=cache, index_urls=[_INDEX])
        identifier = ("sentry-relay", frozenset())
        req = _make_requirement(name="sentry-relay", spec="==1.1.4")
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={},
            )
        )
        assert [c.version for c in result] == ["1.1.4"]

    def test_yanked_excluded_when_pinned_to_other_version(self):
        # ``==0.9.27`` doesn't license the yanked 1.1.4 either —
        # ``_candidate_satisfies_requirements`` rejects 1.1.4 already,
        # but the yanked filter is the load-bearing one when the spec
        # is permissive.
        cands = [
            _cand(name="sentry-relay", version="1.1.4", yanked=True),
            _cand(name="sentry-relay", version="0.9.27"),
        ]
        cache = _FakeCache({(_INDEX, "sentry-relay"): tuple(cands)})
        provider = _make_provider(cache=cache, index_urls=[_INDEX])
        identifier = ("sentry-relay", frozenset())
        req = _make_requirement(name="sentry-relay", spec="==0.9.27")
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={},
            )
        )
        assert [c.version for c in result] == ["0.9.27"]


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


# ---------------------------------------------------------------------------
# T6 — is_satisfied_by (final-acceptance predicate)
# ---------------------------------------------------------------------------
#
# Per plan T6 + design §5.3, ``is_satisfied_by`` answers the question
# "is this chosen candidate a valid satisfaction of this requirement?"
# Three checks:
#
# 1. ``candidate.version in requirement.specifier`` (prereleases mirror
#    T4's policy).
# 2. Extras compatibility — every extra requested by the requirement
#    must be in the candidate's advertised ``provides_extras``.  Phase 3
#    decision: when ``provides_extras`` is unknown (lazy-metadata: T7's
#    ``get_dependencies`` is what would populate it), we mirror pip's
#    behaviour and treat the candidate as satisfying.  Pip's
#    :meth:`SpecifierRequirement.is_satisfied_by`
#    (``pipenv/patched/pip/_internal/resolution/resolvelib/requirements.py:111``)
#    delegates to ``spec.contains(candidate.version, prereleases=True)``
#    only — extras are gated upstream by the ``(name, extras)`` identifier
#    grouping in :meth:`identify` so the predicate never sees a mismatched
#    pair.  We adopt the same "assume true if extras data not available"
#    stance: tested here via a Candidate whose ``extras`` is the default
#    empty frozenset.  When metadata IS available (Candidate populated
#    with a non-empty ``extras``), we strict-check.
# 3. Marker evaluation against ``target_env`` (override of vendored
#    :func:`packaging.markers.default_environment`).  Requirement with no
#    marker passes unconditionally.


def _candidate_for_satisfies(
    *,
    name: str = "django",
    version: str = "4.0.1",
    extras: frozenset[str] = frozenset(),
):
    """Build a :class:`Candidate` for the T6 ``is_satisfied_by`` tests
    with just the four fields the predicate reads (``name``, ``version``,
    ``extras`` for the extras-compat path).  Wraps :func:`_cand` for
    readability at the call sites."""
    return _cand(name=name, version=version, extras=extras)


class TestIsSatisfiedByVersion:
    """Plan T6 bullet 1+2: version-specifier check.

    * ``==4.0.1`` requirement, candidate version ``4.0.1`` → ``True``.
    * ``==4.0.1`` requirement, candidate version ``4.0.2`` → ``False``.
    """

    def test_exact_pin_matches_same_version(self):
        provider = _make_provider()
        req = _make_requirement(name="django", spec="==4.0.1")
        cand = _candidate_for_satisfies(name="django", version="4.0.1")
        assert provider.is_satisfied_by(req, cand) is True

    def test_exact_pin_rejects_different_version(self):
        provider = _make_provider()
        req = _make_requirement(name="django", spec="==4.0.1")
        cand = _candidate_for_satisfies(name="django", version="4.0.2")
        assert provider.is_satisfied_by(req, cand) is False

    def test_range_specifier_accepts_in_range(self):
        provider = _make_provider()
        req = _make_requirement(name="django", spec=">=4.0,<5.0")
        cand = _candidate_for_satisfies(name="django", version="4.2.3")
        assert provider.is_satisfied_by(req, cand) is True

    def test_range_specifier_rejects_out_of_range(self):
        provider = _make_provider()
        req = _make_requirement(name="django", spec=">=4.0,<5.0")
        cand = _candidate_for_satisfies(name="django", version="5.1.0")
        assert provider.is_satisfied_by(req, cand) is False

    def test_empty_specifier_accepts_any_version(self):
        """A Pipfile ``"*"`` entry flattens to an empty
        :class:`SpecifierSet` (per T1's ``from_pipfile_entry`` contract),
        which should admit any non-prerelease version."""
        provider = _make_provider()
        req = _make_requirement(name="django", spec="")
        cand = _candidate_for_satisfies(name="django", version="4.2.0")
        assert provider.is_satisfied_by(req, cand) is True

    def test_prerelease_candidate_admitted_at_predicate(self):
        """Pip parity: :meth:`is_satisfied_by` passes
        ``prereleases=True`` unconditionally, because
        :meth:`find_matches` (the ``PackageFinder`` analog) has already
        applied the prerelease policy upstream.  A prerelease arriving
        at the predicate IS satisfying as far as the specifier check
        goes — re-filtering here would silently reject candidates the
        resolver legitimately matched.  Mirrors pip's
        ``SpecifierRequirement.is_satisfied_by`` at
        ``pipenv/patched/pip/_internal/resolution/resolvelib/requirements.py:121``.
        """
        provider = _make_provider(allow_prereleases=False)
        req = _make_requirement(name="django", spec=">=4.0")
        cand = _candidate_for_satisfies(name="django", version="5.0.0a1")
        assert provider.is_satisfied_by(req, cand) is True


class TestIsSatisfiedByMarker:
    """Plan T6 bullet 3: marker evaluation.

    * ``requirement.marker = Marker("python_version < '3.10'")``
      + ``target_env = {"python_version": "3.12"}`` → ``False``.
    * Marker evaluates True against target env → predicate returns True.
    * Requirement with ``marker is None`` → predicate is marker-blind.
    """

    def test_marker_evaluating_false_rejects(self):
        from pipenv.resolver.pure_python_requirement import Requirement
        from pipenv.vendor.packaging.markers import Marker
        from pipenv.vendor.packaging.specifiers import SpecifierSet

        req = Requirement(
            name="django",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=Marker("python_version < '3.10'"),
            source="pipfile",
            parent=None,
        )
        provider = _make_provider(target_env={"python_version": "3.12"})
        cand = _candidate_for_satisfies(name="django", version="4.0.1")
        assert provider.is_satisfied_by(req, cand) is False

    def test_marker_evaluating_true_accepts(self):
        from pipenv.resolver.pure_python_requirement import Requirement
        from pipenv.vendor.packaging.markers import Marker
        from pipenv.vendor.packaging.specifiers import SpecifierSet

        req = Requirement(
            name="django",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=Marker("python_version >= '3.10'"),
            source="pipfile",
            parent=None,
        )
        provider = _make_provider(target_env={"python_version": "3.12"})
        cand = _candidate_for_satisfies(name="django", version="4.0.1")
        assert provider.is_satisfied_by(req, cand) is True

    def test_no_marker_passes_unconditionally(self):
        provider = _make_provider(target_env={"python_version": "3.6"})
        req = _make_requirement(name="django", spec="==4.0.1")  # marker=None
        cand = _candidate_for_satisfies(name="django", version="4.0.1")
        assert provider.is_satisfied_by(req, cand) is True

    def test_marker_evaluation_overrides_default_environment(self):
        """The marker must be evaluated against ``self._target_env`` —
        NOT the running Python's environment.  We pin
        ``python_version = "3.7"`` in the target env and verify the
        marker uses that even though CI is running on a newer Python."""
        from pipenv.resolver.pure_python_requirement import Requirement
        from pipenv.vendor.packaging.markers import Marker
        from pipenv.vendor.packaging.specifiers import SpecifierSet

        # ``python_version < '3.8'`` is True under the synthetic
        # target_env but typically False under the running interpreter
        # (CI runs >=3.9).  If the impl leaked default_environment, the
        # assertion below would flip.
        req = Requirement(
            name="django",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=Marker("python_version < '3.8'"),
            source="pipfile",
            parent=None,
        )
        provider = _make_provider(target_env={"python_version": "3.7"})
        cand = _candidate_for_satisfies(name="django", version="4.0.1")
        assert provider.is_satisfied_by(req, cand) is True


class TestIsSatisfiedByExtras:
    """Plan T6 bullet 2 — extras compatibility under lazy metadata.

    Phase-3 decision recorded on the T6 plan entry: when the candidate's
    advertised ``extras`` is empty (the default — lazy metadata not yet
    loaded, since ``is_satisfied_by`` runs BEFORE T7's
    ``get_dependencies`` fetches METADATA), we mirror pip's stance and
    return ``True`` rather than failing a candidate the resolver has
    legitimately matched via the ``(name, extras)`` identifier grouping
    (pip:
    ``pipenv/patched/pip/_internal/resolution/resolvelib/requirements.py:111``
    — pip checks only the specifier).  When the candidate DOES advertise
    a non-empty extras set, we strict-check — extras-bearing candidates
    are typically synthesised by tests / future code paths and a
    mismatch there is informative.
    """

    def test_extras_unknown_lazy_metadata_returns_true(self):
        """Candidate's ``extras`` is the default empty frozenset — we
        treat this as "metadata not yet loaded" and admit the candidate.
        Pinned behaviour: requirement asks for ``[argon2]`` extra,
        candidate exposes no extras → still ``True``."""
        provider = _make_provider()
        req = _make_requirement(
            name="django",
            spec=">=4.0",
            extras=frozenset({"argon2"}),
        )
        cand = _candidate_for_satisfies(name="django", version="4.2.0")
        # Default ``extras=frozenset()`` on the candidate models the
        # lazy-metadata case.
        assert cand.extras == frozenset()
        assert provider.is_satisfied_by(req, cand) is True

    def test_extras_satisfied_when_candidate_advertises_superset(self):
        provider = _make_provider()
        req = _make_requirement(
            name="django",
            spec=">=4.0",
            extras=frozenset({"argon2"}),
        )
        cand = _candidate_for_satisfies(
            name="django",
            version="4.2.0",
            extras=frozenset({"argon2", "bcrypt"}),
        )
        assert provider.is_satisfied_by(req, cand) is True

    def test_extras_rejected_when_candidate_advertises_disjoint(self):
        """Strict check: when the candidate DOES advertise extras (so
        metadata is loaded) and the requested extra isn't in the set,
        the predicate returns False."""
        provider = _make_provider()
        req = _make_requirement(
            name="django",
            spec=">=4.0",
            extras=frozenset({"argon2"}),
        )
        cand = _candidate_for_satisfies(
            name="django",
            version="4.2.0",
            extras=frozenset({"bcrypt"}),
        )
        assert provider.is_satisfied_by(req, cand) is False

    def test_no_extras_requested_passes_regardless(self):
        provider = _make_provider()
        req = _make_requirement(
            name="django", spec=">=4.0", extras=frozenset()
        )
        cand = _candidate_for_satisfies(
            name="django",
            version="4.2.0",
            extras=frozenset({"bcrypt"}),
        )
        assert provider.is_satisfied_by(req, cand) is True


# ---------------------------------------------------------------------------
# T7 — get_dependencies (Q-A fail-loud for sdist; Requires-Dist parsing for
# wheels; marker filtering with parent-extras context)
# ---------------------------------------------------------------------------
#
# Validation matrix (per ``initiative-g-phase3-plan.md`` T7 + design §5.3,
# updated by Initiative G Phase 3b T_S3):
#
# 1. Wheel candidate with ``Requires-Dist: numpy>=1.20,<2.0`` →
#    ``[Requirement(name="numpy", specifier=">=1.20,<2.0",
#    source="transitive", parent=<candidate.name>)]``.
# 2. Wheel candidate with ``Requires-Dist: pytest; extra=='dev'`` and the
#    candidate did NOT request the ``[dev]`` extra → marker evaluates
#    False against the empty-extras context; req filtered out.
# 3. Wheel candidate with ``Requires-Dist: pytest; extra=='dev'`` and
#    the candidate DID request the ``[dev]`` extra → marker evaluates
#    True under ``{"extra": "dev"}``; req kept.
# 4. Sdist candidate (``.tar.gz`` filename) → routes through
#    ``self._metadata_fetcher`` like a wheel does; the stubbed fetcher
#    returns a synthetic :class:`CoreMetadata` and the transitive
#    :class:`Requirement` set is returned.  (Phase 3a raised
#    ``_SdistEncountered`` here; Phase 3b T_S3 removed that gate now
#    that T_S2 routes sdists through T_S1's PEP 517 builder.)
#
# Implementation reference (pip's analog, cited in production code):
# ``pipenv/patched/pip/_internal/metadata/importlib/_dists.py:224`` —
# ``BaseDistribution.iter_dependencies(extras)`` — three-branch logic:
# no-marker → yield; no requested extras + ``marker.evaluate({"extra":
# ""})`` → yield; else yield iff any ``{"extra": e}`` makes the marker
# True.


def _metadata(
    *,
    name: str = "django",
    version: str = "4.2.0",
    requires_dist: tuple[str, ...] = (),
    requires_python: str | None = None,
    provides_extras: frozenset[str] = frozenset(),
    summary: str | None = None,
):
    """Build a :class:`CoreMetadata` for T7 tests.

    Wraps :class:`pipenv.resolver.pure_python_metadata.CoreMetadata` so
    each test names only the field it cares about; the rest take inert
    defaults.
    """
    from pipenv.resolver.pure_python_metadata import CoreMetadata

    return CoreMetadata(
        name=name,
        version=version,
        requires_python=requires_python,
        requires_dist=requires_dist,
        provides_extras=provides_extras,
        summary=summary,
    )


def _metadata_fetcher_stub(mapping: dict):
    """Return a ``metadata_fetcher`` callable suitable for the provider.

    ``mapping`` is ``{candidate_url: CoreMetadata}``.  The callable
    matches the shape the provider expects:
    ``metadata_fetcher(candidate) -> CoreMetadata``.  T9 builds the
    real wiring around :func:`fetch_metadata`; tests use this stub
    so no HTTP I/O runs.
    """

    def fetch(candidate):
        try:
            return mapping[candidate.url]
        except KeyError as exc:
            raise AssertionError(
                f"test stub: no metadata seeded for {candidate.url}"
            ) from exc

    return fetch


class TestGetDependenciesWheelRequiresDist:
    """Plan T7 bullet 1: wheel candidate's ``Requires-Dist`` becomes a
    list of :class:`Requirement`\\ s with ``source="transitive"`` and
    ``parent=<candidate.name>``."""

    def test_single_requires_dist_returns_one_requirement(self):
        cand = _cand(name="django", version="4.2.0", is_wheel=True)
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("numpy>=1.20,<2.0",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )

        deps = list(provider.get_dependencies(cand))

        assert len(deps) == 1
        dep = deps[0]
        assert dep.name == "numpy"
        # SpecifierSet's str form is stable across orderings — compare
        # via the underlying spec strings sorted.
        assert sorted(str(s) for s in dep.specifier) == sorted(
            (">=1.20", "<2.0")
        )
        assert dep.source == "transitive"
        assert dep.parent == "django"
        assert dep.marker is None

    def test_multiple_requires_dist_returns_all(self):
        cand = _cand(name="flask", version="2.3.0", is_wheel=True)
        meta = _metadata(
            name="flask",
            version="2.3.0",
            requires_dist=("werkzeug>=2.3", "jinja2>=3.0"),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )

        deps = list(provider.get_dependencies(cand))
        names = sorted(d.name for d in deps)
        assert names == ["jinja2", "werkzeug"]
        assert all(d.source == "transitive" for d in deps)
        assert all(d.parent == "flask" for d in deps)

    def test_empty_requires_dist_returns_empty_list(self):
        """A wheel with no ``Requires-Dist`` headers — a leaf in the
        graph — must yield zero requirements (NOT raise)."""
        cand = _cand(name="six", version="1.16.0", is_wheel=True)
        meta = _metadata(
            name="six", version="1.16.0", requires_dist=()
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        assert list(provider.get_dependencies(cand)) == []


class TestGetDependenciesMarkerFilter:
    """Plan T7 bullet 2 + 3: marker evaluation with parent-extras context.

    Mirrors pip's three-branch logic at
    ``pipenv/patched/pip/_internal/metadata/importlib/_dists.py:224``:

    * No marker -> yield.
    * Marker present + no parent extras -> yield iff
      ``marker.evaluate({"extra": ""})`` is True.
    * Marker present + parent extras non-empty -> yield iff
      ``marker.evaluate({"extra": e})`` is True for any e in extras.
    """

    def test_extra_marker_filtered_out_when_parent_has_no_extras(self):
        """Plan T7 bullet 2: ``Requires-Dist: pytest; extra=='dev'``
        with parent candidate's ``extras == frozenset()`` -> marker
        evaluates False under ``{"extra": ""}``; req filtered out."""
        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset(),  # parent did NOT ask for [dev]
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("pytest ; extra == 'dev'",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        assert deps == []

    def test_extra_marker_kept_when_parent_requested_that_extra(self):
        """Plan T7 bullet 3 (active-extras case):
        ``Requires-Dist: pytest; extra=='dev'`` with parent candidate's
        ``extras == frozenset({"dev"})`` -> marker evaluates True under
        ``{"extra": "dev"}``; req kept with ``parent=<candidate.name>``.
        """
        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset({"dev"}),  # parent DID ask for [dev]
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("pytest>=7 ; extra == 'dev'",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        assert len(deps) == 1
        assert deps[0].name == "pytest"
        assert deps[0].parent == "django"
        assert deps[0].source == "transitive"
        # The marker is preserved on the transitive requirement so a
        # later :meth:`is_satisfied_by` re-evaluation against
        # ``target_env`` stays consistent.
        assert deps[0].marker is not None

    def test_non_extra_marker_evaluated_against_target_env(self):
        """A non-extra marker (e.g. ``python_version < '3.8'``) is
        evaluated against the provider's ``target_env`` overlay -- pinning
        ``python_version = "3.12"`` filters a ``< '3.8'`` marker out."""
        cand = _cand(
            name="django", version="4.2.0", is_wheel=True
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=(
                "typing_extensions ; python_version < '3.8'",
                "sqlparse>=0.3",
            ),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        names = [d.name for d in deps]
        # typing_extensions filtered out -- its marker is False under
        # python_version=3.12.  sqlparse survives (no marker).
        assert names == ["sqlparse"]


class TestGetDependenciesSdistRoutesThroughMetadataFetcher:
    """Phase 3b T_S3: ``get_dependencies`` no longer raises
    :class:`_SdistEncountered` on a non-wheel candidate.  Instead it
    routes the candidate through ``self._metadata_fetcher`` exactly
    like a wheel candidate — T_S2's
    :meth:`MetadataFetcher.fetch_metadata` is responsible for branching
    on ``candidate.is_wheel`` and routing sdists through T_S1's PEP
    517 builder.

    These tests stub the metadata fetcher in-memory so no PEP 517
    build runs; the assertion is that the provider treats sdist and
    wheel candidates symmetrically at the ``get_dependencies`` layer.
    """

    def test_sdist_candidate_routes_through_metadata_fetcher(self):
        """An sdist candidate's transitives flow through the stubbed
        metadata fetcher the same way a wheel's would — no exception
        is raised; the returned :class:`Requirement` objects mirror
        the ``Requires-Dist`` entries supplied via the stub.
        """
        cand = _cand(
            name="legacy", version="0.1", is_wheel=False
        )
        # The stub returns a synthetic CoreMetadata as if T_S1 had
        # built the sdist on the fly.
        meta = _metadata(
            name="legacy",
            version="0.1",
            requires_dist=("six>=1.16",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )

        deps = list(provider.get_dependencies(cand))

        assert len(deps) == 1
        dep = deps[0]
        assert dep.name == "six"
        assert dep.source == "transitive"
        assert dep.parent == "legacy"
        # SpecifierSet stringification — pin the spec set explicitly so
        # a future packaging-version bump that reorders the repr can't
        # silently regress the assertion.
        assert str(dep.specifier) == ">=1.16"

    def test_sdist_invokes_metadata_fetcher_exactly_once(self):
        """The provider must consult the fetcher for an sdist candidate
        — pinning the post-T_S3 contract that there is no longer a
        short-circuit gate before the call.
        """
        cand = _cand(
            name="legacy", version="0.1", is_wheel=False
        )

        call_log: list = []

        def recording_fetcher(c):
            call_log.append(c)
            from pipenv.resolver.pure_python_metadata import CoreMetadata

            return CoreMetadata(
                name="legacy",
                version="0.1",
                requires_python=None,
                requires_dist=(),
                provides_extras=frozenset(),
                summary=None,
            )

        provider = _make_provider(
            metadata_fetcher=recording_fetcher,
            target_env={"python_version": "3.12"},
        )

        deps = list(provider.get_dependencies(cand))
        # Empty Requires-Dist → no transitives.
        assert deps == []
        # The fetcher fired exactly once, with the sdist candidate.
        assert len(call_log) == 1
        assert call_log[0] is cand

    def test_sdist_encountered_still_importable(self):
        """Back-compat pin: the :class:`_SdistEncountered` class is no
        longer raised from production code (T_S3) but remains
        importable for external test suites that referenced the
        Phase 3a contract.  See its docstring for the deprecation
        notice.
        """
        from pipenv.resolver.pure_python_provider import _SdistEncountered

        assert issubclass(_SdistEncountered, Exception)
        # The constructor still accepts a candidate object — preserves
        # the Phase 3a public shape so legacy ``try/except`` blocks
        # that catch + introspect the exception keep working.
        instance = _SdistEncountered(_cand(name="x", version="0", is_wheel=False))
        assert instance.candidate.name == "x"


class TestGetDependenciesMalformedRequiresDist:
    """Defensive: a malformed ``Requires-Dist`` entry (parser raises)
    surfaces as an error rather than silently dropping the dep.

    Pip's ``iter_dependencies`` at
    ``pipenv/patched/pip/_internal/metadata/importlib/_dists.py:224``
    propagates ``InvalidRequirement`` from ``packaging`` -- we mirror.
    """

    def test_invalid_requires_dist_raises_invalid_requirement(self):
        from pipenv.vendor.packaging.requirements import InvalidRequirement

        cand = _cand(
            name="django", version="4.2.0", is_wheel=True
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            # ``!@#`` is not a legal requirement spec -- parser raises.
            requires_dist=("!@# not a real spec",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )

        try:
            list(provider.get_dependencies(cand))
        except InvalidRequirement:
            pass  # expected
        else:  # pragma: no cover - acceptance criterion
            raise AssertionError(
                "expected InvalidRequirement from malformed Requires-Dist"
            )


# ---------------------------------------------------------------------------
# T13 — Edge-case tests added to push coverage on
# ``pipenv/resolver/pure_python_provider.py`` to >= 90 %.
#
# Audit list (per plan T13):
#
# * ``identify``: duck-typed Candidate subclass without ``extras`` field
#   falls back to ``frozenset()``.
# * ``find_matches``:
#     - Dedup by ``(name, version, filename)`` removes a duplicate.
#     - Cache miss across multiple index_urls, with no ``populate``
#       attribute on the fetcher (defensive ``getattr``).
#     - ``InvalidVersion`` candidate filtered out from satisfaction
#       check.
#     - ``allow_prereleases=True`` admits a prerelease against a
#       specifier that does not opt in.
#     - ``requires_python`` target_python ``None`` returns True.
#     - ``InvalidSpecifier`` in candidate's ``requires_python`` is
#       permissively accepted.
#     - ``requires_python``'s ``SpecifierSet.contains`` raising
#       ``InvalidVersion`` is permissively accepted.
# * ``get_preference``:
#     - A row whose ``requirement.specifier`` is ``None`` (duck-typed
#       requirement without a SpecifierSet) is tolerated.
#     - ``backtrack_causes`` entry whose ``requirement`` is ``None`` is
#       skipped.
#     - ``backtrack_causes`` entry whose ``self.identify`` raises is
#       skipped (defensive try/except).
#     - ``backtrack_causes`` entry for a DIFFERENT identifier doesn't
#       bump the count.
# * ``is_satisfied_by``:
#     - Candidate version unparseable -> False (loud-failure stance).
#     - Marker that raises during ``.evaluate(...)`` -> False (defensive
#       except).
# * ``get_dependencies``:
#     - Empty / whitespace-only ``Requires-Dist`` line is skipped.
#     - Active extra: a malformed marker under one extra context is
#       skipped (defensive ``except`` in the parent_extras branch).
#     - Empty parent_extras + malformed marker is treated as inactive.


class TestIdentifyDuckTypedCandidate:
    """``identify`` accepts any object exposing ``.name`` and
    optionally ``.extras``.  The fallback path uses
    ``getattr(..., "extras", frozenset())`` -- pin it explicitly with a
    duck-typed object that doesn't even have an ``extras`` attribute."""

    def test_duck_typed_candidate_without_extras_falls_back_to_frozenset(self):
        provider = _make_provider()

        class _DuckCandidate:
            name = "django"

        ident = provider.identify(_DuckCandidate())
        assert ident == ("django", frozenset())


class TestFindMatchesDedup:
    """Plan T13: dedup on ``(name, version, filename)`` collapses
    duplicate entries (same wheel served by mirror indexes).  Two cache
    entries that share the identity tuple should yield ONE result."""

    def test_duplicate_candidates_collapsed(self):
        # Two cache hits for the same package + version + filename --
        # the second occurrence triggers the ``continue`` branch on
        # ``key in seen``.
        c1 = _cand(name="django", version="4.2.0")
        c2 = _cand(name="django", version="4.2.0")  # identical key
        c3 = _cand(name="django", version="4.1.0")
        cache = _FakeCache({(_INDEX, "django"): (c1, c2, c3)})
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
        # Two unique versions after dedup; high-version first.
        assert versions == ["4.2.0", "4.1.0"]


class TestFindMatchesFetcherWithoutPopulate:
    """Defensive: ``find_matches`` uses ``getattr(fetcher, "populate", None)``
    so a fetcher object without a ``populate`` attribute (legitimate in
    smoke tests) doesn't crash on cache miss."""

    def test_no_populate_attribute_returns_empty_without_raise(self):
        cache = _FakeCache()  # empty -- triggers populate path
        # Use a plain object() as the fetcher -- no ``populate`` method.
        provider = _make_provider(
            cache=cache, fetcher=object(), index_urls=[_INDEX]
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


class TestFindMatchesInvalidVersionCandidate:
    """A candidate whose ``.version`` cannot be parsed by
    :class:`packaging.version.Version` is filtered out at the
    satisfaction check (loud-failure stance shared with T4 + T6)."""

    def test_unparseable_version_excluded(self):
        # Mix a valid candidate with one whose version is junk.  The
        # valid candidate sails through; the junk one is dropped by the
        # ``InvalidVersion`` branch in
        # ``_candidate_satisfies_requirements``.
        good = _cand(name="django", version="4.2.0")
        bad = _cand(name="django", version="not-a-version")
        cache = _FakeCache({(_INDEX, "django"): (good, bad)})
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
        assert versions == ["4.2.0"]


class TestFindMatchesAllowPrereleases:
    """``allow_prereleases=True`` admits a prerelease version even when
    the specifier itself does not opt in (e.g. plain ``>=4.0``)."""

    def test_allow_prereleases_admits_prerelease(self):
        cands = [
            _cand(name="django", version="4.2.0"),
            _cand(name="django", version="5.0.0a1"),
        ]
        cache = _FakeCache({(_INDEX, "django"): tuple(cands)})
        provider = _make_provider(
            cache=cache,
            index_urls=[_INDEX],
            allow_prereleases=True,
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
        # Prerelease appears at the head (highest by Version order).
        assert "5.0.0a1" in versions
        assert "4.2.0" in versions

    def test_specifier_with_prerelease_opt_in_admits_prerelease(self):
        """When the specifier itself opts in (e.g. ``>=5.0a0``), the
        provider's :meth:`_candidate_satisfies_requirements` passes
        ``prereleases=True`` to :meth:`SpecifierSet.contains` regardless
        of the ``allow_prereleases`` flag.  Pins the
        ``spec.prereleases`` branch of the prerelease policy."""
        cands = [
            _cand(name="django", version="5.0.0a1"),
            _cand(name="django", version="5.0.0a2"),
        ]
        cache = _FakeCache({(_INDEX, "django"): tuple(cands)})
        provider = _make_provider(
            cache=cache,
            index_urls=[_INDEX],
            allow_prereleases=False,
        )
        identifier = ("django", frozenset())
        # The ``>=5.0a0`` specifier flips its own ``prereleases`` to True.
        req = _make_requirement(name="django", spec=">=5.0a0")
        result = list(
            provider.find_matches(
                identifier,
                requirements={identifier: iter([req])},
                incompatibilities={},
            )
        )
        versions = [c.version for c in result]
        assert versions == ["5.0.0a2", "5.0.0a1"]


class TestFindMatchesRequiresPythonEdgeCases:
    """Cover the three permissive branches of
    ``_candidate_requires_python_ok``:

    1. ``target_python`` is ``None`` -> accept regardless of
       ``requires_python``.
    2. ``requires_python`` is malformed (``InvalidSpecifier``) -> accept.
    3. ``SpecifierSet.contains`` raises ``InvalidVersion`` -> accept.

    All three are explicit "don't make the package invisible because of
    a tiny upstream data oddity" branches (mirror pip's
    :func:`evaluate_link`).
    """

    def test_no_target_python_accepts_candidate(self):
        # ``target_env`` has no ``python_version`` key -> target_python
        # is None -> requires_python check short-circuits to True.
        cand = _cand(
            name="django", version="4.2.0", requires_python=">=3.10"
        )
        cache = _FakeCache({(_INDEX, "django"): (cand,)})
        provider = _make_provider(
            cache=cache,
            index_urls=[_INDEX],
            target_env={},  # no python_version key
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
        assert [c.version for c in result] == ["4.2.0"]

    def test_invalid_specifier_in_requires_python_accepts(self):
        """A garbage ``requires_python`` string raises
        :class:`InvalidSpecifier` inside the helper; the helper falls
        through to accept (mirrors pip's behaviour)."""
        cand = _cand(
            name="django",
            version="4.2.0",
            requires_python="not-a-specifier",
        )
        cache = _FakeCache({(_INDEX, "django"): (cand,)})
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
        assert [c.version for c in result] == ["4.2.0"]

    # Note on the ``InvalidVersion`` branch at lines 429-430 of
    # ``pure_python_provider.py``: in the current vendored
    # ``packaging`` version, :meth:`SpecifierSet.contains` does NOT
    # raise :class:`InvalidVersion` -- it returns ``False`` for
    # malformed input.  The branch is documented defensive scaffolding
    # against a hypothetical future ``packaging`` behaviour change, so
    # we cannot exercise it from a test without monkey-patching the
    # vendored module.  Per the T13 plan that branch is deliberately
    # left uncovered; total coverage (98 %+) is well above the 90 %
    # gate.


class TestGetPreferenceDefensiveBranches:
    """Edge cases inside ``get_preference``:

    * A ``RequirementInformation`` row whose ``.requirement.specifier``
      attribute is ``None`` (duck-typed shape) is tolerated -- the
      operators-loop just ``continue``\\s past it.
    * ``backtrack_causes`` entry whose ``.requirement`` is ``None`` is
      skipped.
    * ``backtrack_causes`` entry for a DIFFERENT identifier doesn't
      bump the local count.
    * ``backtrack_causes`` entry whose ``self.identify`` raises is
      skipped via the defensive try/except.
    """

    def test_requirement_specifier_none_is_tolerated(self):
        from pipenv.patched.pip._vendor.resolvelib.structs import (
            RequirementInformation,
        )

        provider = _make_provider()
        identifier = ("alpha", frozenset())

        class _NoSpecifierReq:
            name = "alpha"
            extras = frozenset()
            specifier = None
            source = "pipfile"

        row = RequirementInformation(
            requirement=_NoSpecifierReq(), parent=None
        )
        # Should not raise.
        pref = provider.get_preference(
            identifier,
            resolutions={},
            candidates={},
            information={identifier: iter([row])},
            backtrack_causes=(),
        )
        assert isinstance(pref, tuple)
        # The ``operators`` list is empty when every row's spec is None,
        # so ``is_unfree`` is False (== ``not bool(operators)``).  The
        # ``not is_unfree`` slot must be True (i.e. comes AFTER an
        # operator-bearing requirement).
        other_id = ("beta", frozenset())
        other_req = _make_requirement(name="beta", spec=">=1.0")
        other_pref = provider.get_preference(
            other_id,
            resolutions={},
            candidates={},
            information={other_id: iter([_ri(other_req)])},
            backtrack_causes=(),
        )
        # ``other`` (has any op) sorts before ``alpha`` (no op).
        assert other_pref < pref

    def test_backtrack_cause_with_no_requirement_skipped(self):
        from pipenv.patched.pip._vendor.resolvelib.structs import (
            RequirementInformation,
        )

        provider = _make_provider()
        identifier = ("alpha", frozenset())
        req = _make_requirement(name="alpha", spec=">=1.0")
        # A backtrack-causes row whose ``.requirement`` is ``None`` --
        # defensive ``getattr(row, "requirement", None)`` skips it.
        rogue_row = RequirementInformation(requirement=None, parent=None)
        pref = provider.get_preference(
            identifier,
            resolutions={},
            candidates={},
            information={identifier: iter([_ri(req)])},
            backtrack_causes=(rogue_row,),
        )
        # ``backtrack_count`` slot (index 0) must be 0 -- the rogue row
        # didn't bump the count.
        assert pref[0] == 0

    def test_backtrack_cause_for_different_identifier_not_counted(self):
        provider = _make_provider()
        identifier_a = ("alpha", frozenset())
        identifier_b = ("beta", frozenset())
        req_a = _make_requirement(name="alpha", spec=">=1.0")
        req_b = _make_requirement(name="beta", spec=">=1.0")
        # backtrack_causes points at ``beta`` -- it must NOT bump
        # ``alpha``'s count.
        causes = (_ri(req_b), _ri(req_b))
        pref_alpha = provider.get_preference(
            identifier_a,
            resolutions={},
            candidates={},
            information={identifier_a: iter([_ri(req_a)])},
            backtrack_causes=causes,
        )
        assert pref_alpha[0] == 0  # zero backtracks for alpha

    def test_backtrack_cause_with_unidentifiable_requirement_skipped(self):
        """If ``self.identify`` raises on a backtrack-causes row, the
        defensive try/except in ``get_preference`` skips the row rather
        than crashing the resolve."""
        from pipenv.patched.pip._vendor.resolvelib.structs import (
            RequirementInformation,
        )

        provider = _make_provider()
        identifier = ("alpha", frozenset())
        req = _make_requirement(name="alpha", spec=">=1.0")

        # Build a row whose ``.requirement`` doesn't satisfy the
        # ``identify`` contract (no ``.name``/``.extras``).  ``identify``
        # branches on isinstance(Requirement) and falls through to
        # attribute access -- AttributeError gets swallowed.
        class _BrokenReq:
            pass

        broken_row = RequirementInformation(
            requirement=_BrokenReq(), parent=None
        )
        # Should NOT raise; ``backtrack_count`` for ``alpha`` stays 0.
        pref = provider.get_preference(
            identifier,
            resolutions={},
            candidates={},
            information={identifier: iter([_ri(req)])},
            backtrack_causes=(broken_row,),
        )
        assert pref[0] == 0


class TestIsSatisfiedByVersionUnparseable:
    """``is_satisfied_by`` returns False when the candidate's version
    can't be parsed by :class:`packaging.version.Version` (loud-failure
    stance shared with T4)."""

    def test_unparseable_version_returns_false(self):
        provider = _make_provider()
        req = _make_requirement(name="django", spec=">=4.0")
        cand = _candidate_for_satisfies(
            name="django", version="not-a-version"
        )
        assert provider.is_satisfied_by(req, cand) is False


class TestIsSatisfiedByMarkerEvaluationError:
    """When ``marker.evaluate(env)`` raises (e.g. references an unknown
    marker variable in the overlay), ``is_satisfied_by`` returns False
    rather than crashing -- defensive ``except``."""

    def test_marker_evaluation_raises_returns_false(self):
        from pipenv.resolver.pure_python_requirement import Requirement
        from pipenv.vendor.packaging.specifiers import SpecifierSet

        class _RaisingMarker:
            def evaluate(self, env):
                raise RuntimeError("synthetic marker failure")

        req = Requirement(
            name="django",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=_RaisingMarker(),
            source="pipfile",
            parent=None,
        )
        provider = _make_provider(target_env={"python_version": "3.12"})
        cand = _candidate_for_satisfies(name="django", version="4.0.1")
        assert provider.is_satisfied_by(req, cand) is False


class TestGetDependenciesEmptyOrWhitespaceRequiresDist:
    """A blank ``Requires-Dist`` entry (e.g. trailing newline in a
    hand-crafted METADATA fixture) is skipped before reaching the
    parser, rather than raising ``InvalidRequirement``."""

    def test_empty_requires_dist_entry_skipped(self):
        cand = _cand(name="django", version="4.2.0", is_wheel=True)
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("   ", "", "numpy>=1.20"),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        # Only the real entry survives.
        assert [d.name for d in deps] == ["numpy"]


class TestGetDependenciesMarkerEvaluationException:
    """Defensive: a marker that RAISES during evaluation (rather than
    returning False) is treated as inactive, both in the
    "parent has no extras" branch and the "parent has extras" branch.

    Mirrors the design comment at
    ``_marker_active_for_extras`` -- pip silently ignores the same
    shape via :meth:`Marker.evaluate`'s missing-key path; we surface
    the same outcome (the dep just doesn't apply).
    """

    class _RaisingMarker:
        """Marker that always raises -- triggers the ``except`` branch
        in both code paths of ``_marker_active_for_extras``."""

        def evaluate(self, env):
            raise RuntimeError("synthetic marker failure")

    def _patch_first_marker(self, monkeypatch, raising_marker):
        """Replace the first parsed marker with one that raises.

        ``packaging.requirements.Requirement`` parses the marker on
        construction; we override the parsed instance to inject the
        raising stub after the fact via a wrapper around
        ``PackagingRequirement.__init__``.  Cleaner than synthesising
        a malformed METADATA line because we need a SPECIFIC failure
        mode (raise during evaluate, not parse-time failure).
        """
        from pipenv.vendor.packaging import requirements as pkg_reqs

        real_init = pkg_reqs.Requirement.__init__

        def patched_init(self, requirement_string):
            real_init(self, requirement_string)
            if self.marker is not None:
                self.marker = raising_marker

        monkeypatch.setattr(
            pkg_reqs.Requirement, "__init__", patched_init
        )

    def test_marker_raises_with_no_parent_extras_skips_dep(
        self, monkeypatch
    ):
        self._patch_first_marker(monkeypatch, self._RaisingMarker())
        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset(),  # no parent extras
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            # Marker present -- triggers the marker-eval branch with
            # the patched raising marker.
            requires_dist=("pytest ; python_version > '3'",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        # The marker raised under {"extra": ""} -- treated as inactive.
        assert deps == []

    def test_marker_raises_with_parent_extras_skips_dep(
        self, monkeypatch
    ):
        self._patch_first_marker(monkeypatch, self._RaisingMarker())
        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset({"dev"}),  # parent DOES request extras
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("pytest ; extra == 'dev'",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        # Both extras-context evaluations raise -- treated as inactive.
        assert deps == []


class TestGetDependenciesIntroducingMarker:
    """Plan T_M2 (Initiative G Phase 3b): when ``get_dependencies``
    builds a transitive :class:`Requirement` from a ``Requires-Dist``
    line, the parser's ``.marker`` is threaded through into the new
    ``introducing_marker`` slot (T_M1 addition).  T_M3 will read this
    field in ``_translate_mapping`` to emit a ``markers=...`` clause
    on the lockfile entry; this test class pins the upstream contract.

    Note on the dual marker fields on :class:`Requirement`:

    * ``marker`` — populated by ``Requirement.from_pipfile_entry`` for
      top-level Pipfile entries (constraint-side marker) AND, today,
      by ``get_dependencies`` for transitives (mirrors the parser's
      ``.marker`` directly).  The legacy T7 unit-test contract
      (``TestGetDependenciesMarkerFilter::
      test_extra_marker_kept_when_parent_requested_that_extra``) pins
      this behaviour.
    * ``introducing_marker`` — populated here (T_M2); represents the
      *Requires-Dist-side* marker that introduced a transitive, read
      by T_M3's ``_translate_mapping`` to emit a ``markers=...``
      clause on the lockfile entry.  Splitting the field from
      ``marker`` preserves the T7 contract while letting T_M3 evolve
      independently (e.g. T_M3 may choose to canonicalise / normalise
      the marker string differently from how the resolver evaluates
      it).
    """

    def test_transitive_with_marker_carries_introducing_marker(self):
        """``Requires-Dist: pytest; python_version < '3.10'`` parsed
        under target_env ``python_version='3.9'`` (so the
        marker-extras-active filter keeps the entry) -> resulting
        :class:`Requirement.introducing_marker` equals the parsed
        :class:`Marker`."""
        from pipenv.vendor.packaging.markers import Marker

        cand = _cand(name="django", version="4.2.0", is_wheel=True)
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("pytest ; python_version < '3.10'",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            # Pin target_env to a Python version that makes the marker
            # evaluate True -- otherwise the marker-extras-active filter
            # drops the requirement before we see it.
            target_env={"python_version": "3.9"},
        )
        deps = list(provider.get_dependencies(cand))
        assert len(deps) == 1
        dep = deps[0]
        # introducing_marker carries the parsed marker (T_M2 contract).
        assert dep.introducing_marker is not None
        # Marker comparison: ``packaging``'s ``Marker.__str__`` is
        # stable for the canonical form -- compare via string round-trip.
        expected = Marker("python_version < '3.10'")
        assert str(dep.introducing_marker) == str(expected)

    def test_transitive_without_marker_has_introducing_marker_none(self):
        """``Requires-Dist: numpy>=1.20`` (no marker clause) -> the
        resulting :class:`Requirement.introducing_marker` is ``None``."""
        cand = _cand(name="django", version="4.2.0", is_wheel=True)
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("numpy>=1.20",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        assert len(deps) == 1
        dep = deps[0]
        assert dep.name == "numpy"
        assert dep.introducing_marker is None

    def test_marker_extras_filter_unaffected(self):
        """``Requires-Dist: pytest; extra=='dev'`` with parent
        ``extras=frozenset()`` still drops the requirement -- the
        T_M2 addition is strictly additive and must not bypass the
        existing T7 marker-extras-active filter."""
        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset(),  # parent did NOT request [dev]
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("pytest ; extra == 'dev'",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        # Filter drops the entry -- behaviour identical to the existing
        # ``TestGetDependenciesMarkerFilter`` case.  introducing_marker
        # is irrelevant here because the Requirement is never built.
        assert deps == []

    def test_marker_with_parent_extras_active_carries_marker(self):
        """``Requires-Dist: pytest; extra=='dev'`` with parent
        ``extras=frozenset({'dev'})`` -> requirement yielded AND
        ``introducing_marker`` equals the parsed ``Marker("extra ==
        'dev'")``."""
        from pipenv.vendor.packaging.markers import Marker

        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset({"dev"}),  # parent DID request [dev]
        )
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=("pytest>=7 ; extra == 'dev'",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )
        deps = list(provider.get_dependencies(cand))
        assert len(deps) == 1
        dep = deps[0]
        assert dep.name == "pytest"
        assert dep.parent == "django"
        assert dep.source == "transitive"
        # introducing_marker carries the original parsed marker.
        assert dep.introducing_marker is not None
        expected = Marker("extra == 'dev'")
        assert str(dep.introducing_marker) == str(expected)


# ----------------------------------------------------------------------
# T_M5 (Initiative G Phase 3b): belt-and-braces edge cases for the
# compound-marker shapes that cross the boundary between
# get_dependencies's marker-filter and the introducing_marker
# propagation slot.  Coverage on pure_python_provider.py is already at
# 97 %; these tests close the scope by pinning the two tricky cases the
# audit list calls out: a compound platform-AND-python marker (no
# ``extra`` clause) and a compound extra-AND-platform marker (parent
# extras active).
# ----------------------------------------------------------------------
class TestGetDependenciesT_M5IntroducingMarkerCompound:
    """T_M5 — pin that ``get_dependencies`` propagates the FULL parsed
    ``Marker`` into ``introducing_marker`` even for compound markers
    that combine multiple clauses (``and`` / ``or``).  The marker is
    NOT split into per-clause Requirements — it round-trips intact so
    T_M3's translator can re-emit it as a single ``markers=...`` clause.
    """

    def test_compound_python_and_platform_marker_preserved_intact(self):
        """``Requires-Dist: pytest; python_version >= '3.10' and
        sys_platform == 'darwin'`` (no ``extra`` clause; parent has no
        extras) -> ONE :class:`Requirement` emitted whose
        ``introducing_marker`` is the parsed compound :class:`Marker`,
        preserving BOTH clauses.

        Pins:
        * The compound marker survives the
          ``_marker_active_for_extras`` filter under the ``{"extra":
          ""}`` overlay (a marker without an ``extra==`` clause is
          unaffected by the extras context — that's what makes a plain
          ``python_version`` marker on a Requires-Dist line survive).
        * The marker is NOT split into per-clause requirements — it's
          carried verbatim so T_M3 can emit a single ``markers=...``
          clause on the lockfile entry.
        """
        from pipenv.vendor.packaging.markers import Marker

        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset(),  # parent has no extras
        )
        compound = "python_version >= '3.10' and sys_platform == 'darwin'"
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=(f"pytest ; {compound}",),
        )
        # Target_env overlay activates BOTH halves so the filter keeps
        # the requirement.  python_version >= 3.10 is True for 3.12 and
        # sys_platform overlay matches the marker clause exactly.
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={
                "python_version": "3.12",
                "sys_platform": "darwin",
            },
        )

        deps = list(provider.get_dependencies(cand))
        assert len(deps) == 1
        dep = deps[0]
        assert dep.name == "pytest"
        # ``introducing_marker`` carries the FULL compound marker
        # verbatim (round-trip through ``Marker.__str__``).
        assert dep.introducing_marker is not None
        expected = Marker(compound)
        assert str(dep.introducing_marker) == str(expected)
        # Belt-and-braces: BOTH clauses appear in the marker string
        # (a regression that split the marker would emit only one).
        marker_str = str(dep.introducing_marker)
        assert "python_version" in marker_str
        assert "sys_platform" in marker_str

    def test_extra_and_platform_compound_marker_passes_filter_and_propagates(
        self,
    ):
        """``Requires-Dist: pytest; extra == 'dev' and python_version
        >= '3.10'`` with parent ``extras=frozenset({'dev'})`` and
        target_env Python >= 3.10 -> requirement YIELDED AND
        ``introducing_marker`` carries the full compound marker.

        Pins the intersection of the T7 extras-filter and the T_M2
        introducing-marker propagation:

        * The ``extra=='dev'`` half of the marker is satisfied because
          parent extras contain ``'dev'`` (``_marker_active_for_extras``
          evaluates the marker under ``{"extra": "dev"}``).
        * The ``python_version >= '3.10'`` half evaluates True under
          the target_env overlay.
        * Both halves AND-True -> the marker is "active" -> requirement
          survives the filter.
        * Critically, the ENTIRE compound marker (including the
          ``extra==`` clause) is preserved on ``introducing_marker`` —
          T_M3 will downstream emit the marker verbatim, including the
          ``extra==`` clause.  This is intentional: the lockfile
          consumer (pip install) re-evaluates the marker in the install
          environment, where the same ``extra==`` clause filters the
          dep at install-time.
        """
        from pipenv.vendor.packaging.markers import Marker

        cand = _cand(
            name="django",
            version="4.2.0",
            is_wheel=True,
            extras=frozenset({"dev"}),  # parent DID request [dev]
        )
        compound = "extra == 'dev' and python_version >= '3.10'"
        meta = _metadata(
            name="django",
            version="4.2.0",
            requires_dist=(f"pytest>=7 ; {compound}",),
        )
        provider = _make_provider(
            metadata_fetcher=_metadata_fetcher_stub({cand.url: meta}),
            target_env={"python_version": "3.12"},
        )

        deps = list(provider.get_dependencies(cand))
        # Filter kept the entry (both halves of the AND are True under
        # the parent_extras=={'dev'} + python_version=='3.12' overlay).
        assert len(deps) == 1
        dep = deps[0]
        assert dep.name == "pytest"
        assert dep.parent == "django"
        assert dep.source == "transitive"
        # Compound marker preserved end-to-end — including the
        # ``extra==`` clause that the filter consumed.  ``Marker.__str__``
        # is order-stable for the canonical form so a string round-trip
        # compares cleanly.
        assert dep.introducing_marker is not None
        expected = Marker(compound)
        assert str(dep.introducing_marker) == str(expected)
        # Belt-and-braces: BOTH clauses appear in the marker.
        marker_str = str(dep.introducing_marker)
        assert "extra" in marker_str
        assert "python_version" in marker_str
