"""Integration smoke tests for :class:`PurePythonProvider` driving
``resolvelib.Resolver`` end-to-end (Initiative G phase 3, T8).

Scope: this file is the integration-smoke gate for the full
:class:`PurePythonProvider` (T3 through T7).  It wires the provider into
``resolvelib.Resolver`` against a synthetic in-memory cache + a
metadata-fetcher stub and asserts on the resulting resolution.

Two scenarios per the plan T8 validation matrix:

1. **Happy path** — three-package resolve
   (``requests`` + ``certifi`` + ``urllib3``) against a synthetic cache
   where each package has 2-3 versions; assert the expected pins
   (``2.32.0`` / ``2024.2.2`` / ``2.2.0``) land in the resolved mapping.

2. **Conflict** — ``a`` requires ``b<2``; ``c`` requires ``b>=2``;
   assert :class:`ResolutionImpossible` raises with BOTH causes
   (``b<2`` from ``a`` and ``b>=2`` from ``c``) present in the
   exception's ``.causes`` list.

These tests intentionally exercise the helper
:func:`pipenv.resolver.pure_python_provider._drive_resolver` — a
module-level wrapper around ``resolvelib.Resolver`` that T9's
``PurePythonBackend`` will reuse in production.  Keeping the wiring
behind one helper means tests and the backend can share the same call
path.

Critical constraint (matches the module under test): no
``pip._internal.*`` imports in this file.  All ``packaging`` /
``resolvelib`` paths route through ``pipenv.vendor.*`` /
``pipenv.patched.pip._vendor.*`` accordingly.
"""
from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Synthetic infrastructure
# ---------------------------------------------------------------------------


_INDEX = "https://pypi.org/simple"


class _FakeCache:
    """In-memory stand-in for :class:`ParsedManifestCache`.

    Behaves like the real ``cache.get(index_url, package_name)``:
    returns ``None`` on miss, a tiny stand-in for
    :class:`CachedManifest` (anything exposing ``.candidates``) on hit.

    Mirrors the ``_FakeCache`` in ``test_pure_python_provider.py`` but
    is duplicated here rather than imported across test files — the
    contract is small and a copy keeps both test modules independent
    (T13 may extend the original; T8 should not be perturbed by that).
    """

    class _Manifest:
        __slots__ = ("candidates",)

        def __init__(self, candidates: tuple) -> None:
            self.candidates = candidates

    def __init__(self, mapping: dict[tuple[str, str], tuple]) -> None:
        # mapping: {(index_url, name): (Candidate, ...)}
        self._mapping = dict(mapping)

    def get(self, index_url: str, package_name: str):
        cands = self._mapping.get((index_url, package_name))
        if cands is None:
            return None
        return self._Manifest(cands)


def _wheel_candidate(
    name: str,
    version: str,
    *,
    requires_python: str | None = None,
):
    """Build a wheel :class:`Candidate` with inert defaults for the
    fields T8 doesn't care about.

    ``name`` is already canonical (lowercase) for every fixture below —
    the provider's :meth:`identify` assumes canonical names.
    """
    from pipenv.resolver.candidate import Candidate, Hash

    filename = f"{name}-{version}-py3-none-any.whl"
    return Candidate(
        name=name,
        version=version,
        url=f"https://pypi.org/simple/{name}/{filename}",
        filename=filename,
        hashes=frozenset({Hash("sha256", "0" * 64)}),
        requires_python=requires_python,
        yanked=False,
        yanked_reason=None,
        upload_time=None,
        is_wheel=True,
        wheel_tags=None,
        extras=frozenset(),
    )


def _metadata_fetcher_stub(deps_by_candidate: dict[tuple[str, str], list[str]]):
    """Return a ``metadata_fetcher`` callable suitable for the provider.

    ``deps_by_candidate`` is ``{(name, version): [raw_requires_dist, ...]}``.
    The callable matches the shape the provider expects:
    ``metadata_fetcher(candidate) -> CoreMetadata``.

    A candidate not present in the mapping is treated as "no deps"
    (rather than asserting) — that's the leaf-package case
    (``certifi`` and ``urllib3`` in the happy-path scenario).
    """
    from pipenv.resolver.pure_python_metadata import CoreMetadata

    def fetch(candidate):
        raw = deps_by_candidate.get(
            (candidate.name, candidate.version), []
        )
        return CoreMetadata(
            name=candidate.name,
            version=candidate.version,
            requires_python=candidate.requires_python or "",
            requires_dist=tuple(raw),
            provides_extras=frozenset(),
            summary=None,
        )

    return fetch


def _make_provider(
    *,
    cache: _FakeCache,
    metadata_fetcher: Any,
    target_env: dict | None = None,
):
    from pipenv.resolver.pure_python_provider import PurePythonProvider

    return PurePythonProvider(
        cache=cache,
        fetcher=object(),  # T8 fixtures never need lazy population
        metadata_fetcher=metadata_fetcher,
        target_env=target_env or {"python_version": "3.12"},
        index_urls=[_INDEX],
        allow_prereleases=False,
    )


# ---------------------------------------------------------------------------
# T8 — Happy path: 3-package resolve
# ---------------------------------------------------------------------------


class TestDriveResolverHappyPath:
    """Plan T8 bullet 1: resolve ``requests`` + ``certifi`` + ``urllib3``
    against a synthetic 3-package cache; expected pins land.

    Cache layout (per plan T8):

    * ``requests``: 2.30.0, 2.31.0, 2.32.0; ``2.32.0`` requires
      ``certifi>=2017.4.17`` and ``urllib3>=1.21.1,<3``.
    * ``certifi``: 2024.1.1, 2024.2.2; no deps.
    * ``urllib3``: 1.26.18, 2.0.7, 2.2.0; no deps.

    Top-level requirement: ``requests`` (``"*"``).

    Expected resolved pins:

    * ``requests==2.32.0`` (latest of the three versions),
    * ``certifi==2024.2.2`` (latest, satisfies ``>=2017.4.17``),
    * ``urllib3==2.2.0`` (latest, satisfies ``>=1.21.1,<3``).
    """

    def _build_fixture(self):
        requests_versions = [
            _wheel_candidate("requests", "2.30.0"),
            _wheel_candidate("requests", "2.31.0"),
            _wheel_candidate("requests", "2.32.0"),
        ]
        certifi_versions = [
            _wheel_candidate("certifi", "2024.1.1"),
            _wheel_candidate("certifi", "2024.2.2"),
        ]
        urllib3_versions = [
            _wheel_candidate("urllib3", "1.26.18"),
            _wheel_candidate("urllib3", "2.0.7"),
            _wheel_candidate("urllib3", "2.2.0"),
        ]

        cache = _FakeCache(
            {
                (_INDEX, "requests"): tuple(requests_versions),
                (_INDEX, "certifi"): tuple(certifi_versions),
                (_INDEX, "urllib3"): tuple(urllib3_versions),
            }
        )

        # Only ``requests 2.32.0`` has deps in this fixture.  The
        # provider only fetches metadata for the candidate it actually
        # picks (resolvelib's lazy expansion), so we don't bother
        # seeding entries for the older requests versions.
        deps_by_candidate = {
            ("requests", "2.32.0"): [
                "certifi>=2017.4.17",
                "urllib3>=1.21.1,<3",
            ],
        }
        fetcher = _metadata_fetcher_stub(deps_by_candidate)
        return cache, fetcher

    def test_happy_path_resolves_expected_pins(self):
        from pipenv.resolver.pure_python_provider import _drive_resolver
        from pipenv.resolver.pure_python_requirement import Requirement

        cache, fetcher = self._build_fixture()
        provider = _make_provider(cache=cache, metadata_fetcher=fetcher)

        top_level = [Requirement.from_pipfile_entry("requests", "*")]

        result = _drive_resolver(top_level, provider)

        # ``result.mapping`` is keyed on the provider's identifier
        # tuple — ``(canonical_name, frozenset(extras))``.
        mapping = result.mapping
        pins = {
            name: cand.version
            for (name, _extras), cand in mapping.items()
        }

        # Spot-check each expected pin one at a time so a regression
        # surfaces the exact axis (which version got picked) rather
        # than a single opaque equality failure.
        assert pins.get("requests") == "2.32.0"
        assert pins.get("certifi") == "2024.2.2"
        assert pins.get("urllib3") == "2.2.0"

        # And the closed-world check: no surprise extra packages
        # leaked into the resolution.  Three keys, three packages.
        assert set(pins.keys()) == {"requests", "certifi", "urllib3"}


# ---------------------------------------------------------------------------
# T8 — Conflict scenario
# ---------------------------------------------------------------------------


class TestDriveResolverConflict:
    """Plan T8 bullet 2: conflicting top-level requirements raise
    :class:`ResolutionImpossible` with both causes present.

    Cache layout (per plan T8):

    * ``a 1.0.0``: requires ``b<2``.
    * ``c 1.0.0``: requires ``b>=2``.
    * ``b``: 1.5.0, 2.0.0, 2.1.0; no deps.

    Top-level reqs: ``a`` (``"*"``) and ``c`` (``"*"``).  No version
    of ``b`` satisfies both ``<2`` and ``>=2`` simultaneously, so
    resolvelib raises ``ResolutionImpossible``.
    """

    def _build_fixture(self):
        a_versions = [_wheel_candidate("a", "1.0.0")]
        c_versions = [_wheel_candidate("c", "1.0.0")]
        b_versions = [
            _wheel_candidate("b", "1.5.0"),
            _wheel_candidate("b", "2.0.0"),
            _wheel_candidate("b", "2.1.0"),
        ]
        cache = _FakeCache(
            {
                (_INDEX, "a"): tuple(a_versions),
                (_INDEX, "c"): tuple(c_versions),
                (_INDEX, "b"): tuple(b_versions),
            }
        )
        deps_by_candidate = {
            ("a", "1.0.0"): ["b<2"],
            ("c", "1.0.0"): ["b>=2"],
        }
        fetcher = _metadata_fetcher_stub(deps_by_candidate)
        return cache, fetcher

    def test_conflict_raises_resolution_impossible_with_both_causes(self):
        from pipenv.patched.pip._vendor.resolvelib import ResolutionImpossible

        from pipenv.resolver.pure_python_provider import _drive_resolver
        from pipenv.resolver.pure_python_requirement import Requirement

        cache, fetcher = self._build_fixture()
        provider = _make_provider(cache=cache, metadata_fetcher=fetcher)

        top_level = [
            Requirement.from_pipfile_entry("a", "*"),
            Requirement.from_pipfile_entry("c", "*"),
        ]

        with pytest.raises(ResolutionImpossible) as excinfo:
            _drive_resolver(top_level, provider)

        # ``.causes`` is a list of ``RequirementInformation``
        # namedtuples — ``(requirement, parent)``.  Both transitive
        # requirements (``b<2`` from ``a`` and ``b>=2`` from ``c``)
        # must appear; assert via the rendered specifier strings so
        # the test is robust to ordering changes in ``.causes``.
        causes = list(excinfo.value.causes)
        # All causes should be about ``b`` — that's the package whose
        # constraints conflict.  This is also a useful sanity check
        # that resolvelib reported on the right axis.
        cause_names = {row.requirement.name for row in causes}
        assert cause_names == {"b"}

        # Each cause carries a ``SpecifierSet``; render to a sorted
        # list-of-strings to compare.  ``"<2"`` lives in one cause,
        # ``">=2"`` in the other — both must be present.
        cause_specs = sorted(
            str(row.requirement.specifier) for row in causes
        )
        assert "<2" in cause_specs
        assert ">=2" in cause_specs

        # Bonus: each cause records the parent that produced it
        # (transitive requirements carry ``parent``).  Pin both
        # parent identities so a future refactor of
        # ``get_dependencies`` doesn't silently drop the attribution.
        parents = {
            row.requirement.parent for row in causes if row.requirement.parent
        }
        assert parents == {"a", "c"}
