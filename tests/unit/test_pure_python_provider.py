"""Focused RED→GREEN tests for :class:`PurePythonProvider` methods
(Initiative G phase 3, T3 + T4).

Scope: T3 (``identify``) + T4 (``find_matches``).  T13 will extend this
file with full per-method coverage of ``get_preference``,
``is_satisfied_by``, and ``get_dependencies`` (T5–T7 deliverables).

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
