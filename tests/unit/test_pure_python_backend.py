"""Unit tests for :class:`PurePythonBackend` (Initiative G phase 3, T9).

The backend wraps the :class:`PurePythonProvider` (T3-T8) +
:class:`MetadataFetcher` (T2) + :class:`Requirement` (T1) chain in the
Initiative F ``Backend`` protocol, with the following Phase 3-specific
behaviours validated below:

* **Happy path** — :func:`_drive_resolver` returns a synthetic result;
  the backend translates the resolved candidate mapping into a typed
  :class:`ResolverSuccess` payload.
* **Resolution conflict** (:class:`ResolutionImpossible`) — translated
  into a :class:`ResolutionError` whose ``pip_message`` names BOTH
  conflicting causes (so the user can find the bad pin without reading
  resolvelib internals).
* **Sdist transitive transparent resolution** (Phase 3b T_S3) — when
  resolvelib expands a transitive whose only artifact is an sdist,
  the provider routes it through ``MetadataFetcher.fetch_metadata``
  (T_S2) which builds METADATA via PEP 517 (T_S1) and resolution
  proceeds normally.  This replaced the Phase 3a fail-loud
  :class:`_SdistEncountered` path which raised an
  :class:`InternalError`.
* **Top-level emptiness pre-check** (Phase 3b T_S4) — when a top-level
  package has ZERO candidates across every configured index (typo /
  yanked-only / cold-cache + every-fetch-failed), the backend aborts
  BEFORE driving resolvelib, returning a :class:`ResolutionError`
  whose ``pip_message`` names the offending package and suggests
  ``pipenv lock --backend pip``.  (Phase 3a fired the same gate on
  sdist-only top-levels; T_S2/T_S3 made sdists transparently
  resolvable so that branch is gone — see
  ``TestQFPreCheck.test_sdist_only_top_level_resolves_after_t_s4``.)

Mocks everything (no HTTP, no real resolvelib drive).
"""
from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from pipenv.resolver.candidate import Candidate, Hash
from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    InternalError,
    PackageSpecs,
    ResolutionError,
    ResolverOptions,
    ResolverRequest,
    ResolverResponse,
    ResolverSuccess,
    Source,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_INDEX = "https://pypi.org/simple"


def _build_request(specs: dict[str, str] | None = None) -> ResolverRequest:
    """Build a minimal but realistic :class:`ResolverRequest`."""
    if specs is None:
        specs = {"requests": "requests==2.31.0"}
    return ResolverRequest(
        schema_version=SCHEMA_VERSION,
        category="default",
        packages=PackageSpecs(specs=specs),
        options=ResolverOptions(),
        sources=(
            Source(name="pypi", url=_INDEX, verify_ssl=True),
        ),
    )


def _wheel_candidate(name: str, version: str) -> Candidate:
    filename = f"{name}-{version}-py3-none-any.whl"
    return Candidate(
        name=name,
        version=version,
        url=f"{_INDEX}/{name}/{filename}",
        filename=filename,
        hashes=frozenset({Hash("sha256", "0" * 64)}),
        requires_python=None,
        yanked=False,
        yanked_reason=None,
        upload_time=None,
        is_wheel=True,
        wheel_tags=None,
        extras=frozenset(),
    )


def _sdist_candidate(name: str, version: str) -> Candidate:
    filename = f"{name}-{version}.tar.gz"
    return Candidate(
        name=name,
        version=version,
        url=f"{_INDEX}/{name}/{filename}",
        filename=filename,
        hashes=frozenset({Hash("sha256", "1" * 64)}),
        requires_python=None,
        yanked=False,
        yanked_reason=None,
        upload_time=None,
        is_wheel=False,
        wheel_tags=None,
        extras=frozenset(),
    )


class _FakeManifest:
    __slots__ = ("candidates",)

    def __init__(self, candidates: tuple[Candidate, ...]) -> None:
        self.candidates = candidates


class _FakeCache:
    """In-memory stand-in for :class:`ParsedManifestCache`."""

    def __init__(self, mapping: dict[tuple[str, str], tuple[Candidate, ...]]) -> None:
        self._mapping = dict(mapping)

    def get(self, index_url: str, package_name: str):
        cands = self._mapping.get((index_url, package_name))
        if cands is None:
            return None
        return _FakeManifest(cands)


class _FakeFetcher:
    """Stand-in for :class:`ParallelFetcher` that records calls."""

    def __init__(self) -> None:
        self.populate_calls: list = []

    def populate(self, targets):
        self.populate_calls.append(list(targets))
        return {}


class _FakeResult:
    """Synthetic stand-in for ``resolvelib.Result`` carrying ``.mapping``
    and optionally ``.criteria`` (T_M3 — marker emission reads
    ``Result.criteria[identifier].information``).
    """

    def __init__(self, mapping: dict, criteria: dict | None = None) -> None:
        self.mapping = mapping
        self.criteria = criteria or {}


class _FakeCriterion:
    """Synthetic stand-in for ``resolvelib.resolvers.criterion.Criterion``;
    only the ``.information`` collection is read by T_M3's translator.
    """

    def __init__(self, information) -> None:
        self.information = tuple(information)


# ---------------------------------------------------------------------------
# T9 — Acceptance tests
# ---------------------------------------------------------------------------


class TestSuccessPath:
    """Mock :func:`_drive_resolver` to return a synthetic result with
    resolved candidates → backend returns :class:`ResolverSuccess`.
    """

    def test_success_translates_mapping_into_locked_tuple(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # Cache has wheel candidates for every top-level so the Q-F
        # pre-check passes and resolution proceeds.
        cache = _FakeCache(
            {
                (_INDEX, "requests"): (
                    _wheel_candidate("requests", "2.31.0"),
                ),
            }
        )
        fetcher = _FakeFetcher()

        # Synthetic resolved mapping: identifier -> Candidate.
        resolved_candidate = _wheel_candidate("requests", "2.31.0")
        fake_result = _FakeResult(
            mapping={
                ("requests", frozenset()): resolved_candidate,
            }
        )

        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"requests": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ) as drive:
            response = backend.resolve(request)

        assert drive.called
        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, ResolverSuccess)
        locked = list(response.result.locked)
        assert len(locked) == 1
        assert locked[0].name == "requests"
        # Lockfile shape uses the ``==<version>`` prefix per the
        # existing pip-backend formatter (see ``_clean_version``
        # auto-prefix at ``schema.py`` lines 213-224).  The pure-python
        # backend mirrors that convention so downstream consumers
        # (lockfile writer / parity tests) don't see a divergent shape.
        assert locked[0].version == "==2.31.0"


class TestResolutionImpossible:
    """Mock :func:`_drive_resolver` to raise :class:`ResolutionImpossible`
    → backend returns :class:`ResolutionError` whose ``pip_message``
    mentions BOTH conflicting causes.
    """

    def test_resolution_impossible_translates_to_resolution_error(self):
        from pipenv.patched.pip._vendor.resolvelib import ResolutionImpossible
        from pipenv.patched.pip._vendor.resolvelib.structs import (
            RequirementInformation,
        )

        from pipenv.resolver.backends.pure_python import PurePythonBackend
        from pipenv.resolver.pure_python_requirement import Requirement

        cache = _FakeCache(
            {
                (_INDEX, "a"): (_wheel_candidate("a", "1.0.0"),),
                (_INDEX, "c"): (_wheel_candidate("c", "1.0.0"),),
            }
        )
        fetcher = _FakeFetcher()

        # Build two conflicting RequirementInformation rows: a → b<2,
        # c → b>=2.  Parent objects expose ``.name`` (Candidate
        # duck-shape) so the formatter can emit "a 1.0.0 requires b<2".
        req_b_lt2 = Requirement.from_pipfile_entry("b", "<2")
        req_b_ge2 = Requirement.from_pipfile_entry("b", ">=2")
        parent_a = mock.MagicMock(name="a", version="1.0.0")
        parent_a.name = "a"
        parent_a.version = "1.0.0"
        parent_c = mock.MagicMock(name="c", version="1.0.0")
        parent_c.name = "c"
        parent_c.version = "1.0.0"

        causes = [
            RequirementInformation(requirement=req_b_lt2, parent=parent_a),
            RequirementInformation(requirement=req_b_ge2, parent=parent_c),
        ]
        impossible = ResolutionImpossible(causes)

        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"a": "*", "c": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            side_effect=impossible,
        ):
            response = backend.resolve(request)

        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, ResolutionError)
        msg = response.result.pip_message
        # Both conflicting causes must appear in the formatted message
        # so the user can find the offending pins without reading
        # resolvelib internals.
        assert "a" in msg
        assert "c" in msg
        assert "<2" in msg
        assert ">=2" in msg


class TestSdistTransitiveResolvesThroughMetadataFetcher:
    """Phase 3b T_S3: a transitive sdist no longer crashes the backend.

    The provider's :meth:`get_dependencies` now routes every candidate
    through ``self._metadata_fetcher`` regardless of ``is_wheel`` —
    T_S2's :meth:`MetadataFetcher.fetch_metadata` branches on
    ``is_wheel`` and builds sdist METADATA via T_S1's PEP 517 path.

    The Phase 3a ``_SdistEncountered`` → :class:`InternalError` branch
    in :meth:`PurePythonBackend.resolve` is gone; this test pins the
    new behaviour by feeding the backend a synthetic resolvelib
    ``Result`` whose ``mapping`` includes a sdist candidate alongside
    a wheel.  The translator must produce :class:`ResolverSuccess`
    with both entries locked.

    Critically: a Phase 3a regression here would have produced an
    :class:`InternalError`; we assert :class:`ResolverSuccess`.
    """

    def test_sdist_transitive_resolves_through_metadata_fetcher(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {
                # Top-level "broken" has a wheel candidate so the Q-F
                # pre-check passes; the sdist appears as a TRANSITIVE.
                (_INDEX, "broken"): (_wheel_candidate("broken", "1.0.0"),),
            }
        )
        fetcher = _FakeFetcher()

        # Synthetic resolved mapping: the top-level wheel plus a
        # transitive sdist that — Phase 3a — would have raised
        # _SdistEncountered.  T_S3 means the provider expanded it
        # transparently via T_S2 and resolvelib produced a clean
        # mapping.
        resolved_top = _wheel_candidate("broken", "1.0.0")
        resolved_sdist = _sdist_candidate("legacy-dep", "0.9.0")
        fake_result = _FakeResult(
            mapping={
                ("broken", frozenset()): resolved_top,
                ("legacy-dep", frozenset()): resolved_sdist,
            }
        )

        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"broken": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ) as drive:
            response = backend.resolve(request)

        assert drive.called
        assert isinstance(response, ResolverResponse)
        # Post-T_S3: ResolverSuccess, NOT InternalError.  The transitive
        # sdist did not derail resolution.
        assert isinstance(response.result, ResolverSuccess)
        locked_names = sorted(lr.name for lr in response.result.locked)
        assert locked_names == ["broken", "legacy-dep"]
        # The sdist transitive is locked at its version per the
        # standard ``==<version>`` translation; pin so a regression
        # that silently drops the sdist entry is caught.
        sdist_entry = next(
            lr for lr in response.result.locked if lr.name == "legacy-dep"
        )
        assert sdist_entry.version == "==0.9.0"


class TestQFPreCheck:
    """Top-level emptiness pre-check (Phase 3b T_S4).

    Two rows pinned here:

    * **Sdist-only top-level** (post-T_S4) — resolution must succeed.
      Phase 3a fired ``ResolutionError`` on this shape because no wheel
      meant no resolvable METADATA; T_S2 made ``MetadataFetcher`` build
      sdist METADATA via PEP 517, so the pre-check no longer treats
      sdist-only as a failure.  We pin :class:`ResolverSuccess`.
    * **Zero candidates across all indexes** — the new pre-check fires
      with a ``ResolutionError`` whose message names the offending
      package and suggests ``pipenv lock --backend pip``.
      :func:`_drive_resolver` is NEVER invoked.
    """

    def test_sdist_only_top_level_resolves_after_t_s4(self):
        """Post-T_S4 (Phase 3b): a top-level package with ONLY sdist
        candidates must resolve normally — the obsolete Phase 3a
        wheel-availability gate is gone.

        The sdist gets built transparently via T_S2's
        :class:`MetadataFetcher` route (the actual PEP 517 invocation
        is exercised in ``test_pure_python_sdist.py``; here we just
        confirm the backend no longer fires the pre-check).
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # ``brokenpkg`` has only an sdist candidate.  In Phase 3a this
        # would have fired the Q-F gate; post-T_S4 it must NOT.
        cache = _FakeCache(
            {
                (_INDEX, "brokenpkg"): (
                    _sdist_candidate("brokenpkg", "1.0.0"),
                ),
            }
        )
        fetcher = _FakeFetcher()

        # Mock _drive_resolver to return a synthetic success — we are
        # pinning the *backend's* behaviour around the pre-check, not
        # the full provider chain (which is covered in T_S2/T_S3
        # acceptance tests).  The mock proves the pre-check did NOT
        # short-circuit and the backend reached the resolution step.
        resolved = _sdist_candidate("brokenpkg", "1.0.0")
        fake_result = _FakeResult(
            mapping={("brokenpkg", frozenset()): resolved}
        )

        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"brokenpkg": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ) as drive:
            response = backend.resolve(request)

        # _drive_resolver WAS called — the pre-check did not
        # short-circuit on sdist-only top-level.
        assert drive.called

        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, ResolverSuccess)
        locked = list(response.result.locked)
        assert len(locked) == 1
        assert locked[0].name == "brokenpkg"

    def test_zero_candidates_top_level_aborts_before_drive(self):
        """A top-level package with ZERO candidates across every
        configured index → backend fires the new emptiness pre-check
        and aborts BEFORE driving resolvelib.

        This is the typo / yanked-only / total-network-failure path:
        we want a clear "no candidates found" message rather than a
        30-second wait followed by resolvelib's opaque
        "no candidates available" error.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # Empty cache: every (index, name) lookup returns None.
        cache = _FakeCache({})
        fetcher = _FakeFetcher()

        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"brokenpkg": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver"
        ) as drive:
            response = backend.resolve(request)

        # _drive_resolver MUST NOT have been called — the emptiness
        # pre-check short-circuits before resolvelib runs.
        assert not drive.called

        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, ResolutionError)
        msg = response.result.pip_message
        assert "brokenpkg" in msg
        assert "no candidates found" in msg
        assert "pipenv lock --backend pip" in msg


# ---------------------------------------------------------------------------
# T14 — Coverage-completing tests
# ---------------------------------------------------------------------------


class TestIsAvailable:
    """The pure-python backend has no external dependency to probe for
    — it ships in-tree as part of ``pipenv.resolver``.  :meth:`is_available`
    is documented to always return ``True``; pin that behaviour so a
    future refactor can't quietly flip the contract.
    """

    def test_is_available_returns_true(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        backend = PurePythonBackend(
            cache=_FakeCache({}),
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        assert backend.is_available() is True


class TestPrefetchExceptionTolerated:
    """Q-B pre-fetch failures are non-fatal: the provider's lazy
    :meth:`find_matches` will retry on cache miss, so the backend
    swallows the exception and continues.  This pins the
    ``except Exception: pass`` branch — without it a transient HTTP
    error during pre-fetch would abort resolution that could otherwise
    have succeeded against a populated cache.
    """

    def test_populate_exception_does_not_abort_resolve(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        class _ExplodingFetcher:
            def __init__(self) -> None:
                self.calls = 0

            def populate(self, targets):
                self.calls += 1
                raise RuntimeError("simulated transient network failure")

        cache = _FakeCache(
            {
                (_INDEX, "requests"): (
                    _wheel_candidate("requests", "2.31.0"),
                ),
            }
        )
        fetcher = _ExplodingFetcher()
        resolved = _wheel_candidate("requests", "2.31.0")
        fake_result = _FakeResult(
            mapping={("requests", frozenset()): resolved}
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"requests": "*"})
        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ):
            response = backend.resolve(request)
        # Pre-fetch did blow up exactly once.
        assert fetcher.calls == 1
        # …yet the backend still produced a success — pre-fetch failure
        # is non-fatal.
        assert isinstance(response.result, ResolverSuccess)


class TestQFPreCheckEdges:
    """Top-level emptiness pre-check edge cases (Phase 3b T_S4) beyond
    the two-row baseline covered by ``TestQFPreCheck``.

    Four rows pinned here:

    1. Mixed sdist + wheel candidates — pre-check must NOT fire (one
       top-level has candidates, period; their artifact mix is the
       provider's problem now).
    2. Sdist-only candidates across all configured indexes — pre-check
       must NOT fire (post-T_S4: sdists are resolvable).
    3. Multi-top-level with two healthy packages + one empty package —
       the new pre-check fires and the message names ONLY the empty
       one (not the healthy siblings).
    4. Multi-index plural-spelling — "indexes" appears in the error
       message when more than one index is configured.
    """

    def test_mixed_sdist_and_wheel_does_not_fire_emptiness(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # Mixed candidates: a sdist AND a wheel for the same package.
        # The emptiness pre-check sees ``saw_any=True`` on the first
        # candidate (the sdist) — it never reaches the wheel check.
        cache = _FakeCache(
            {
                (_INDEX, "mixed"): (
                    _sdist_candidate("mixed", "1.0.0"),
                    _wheel_candidate("mixed", "1.0.0"),
                ),
            }
        )
        fetcher = _FakeFetcher()
        resolved = _wheel_candidate("mixed", "1.0.0")
        fake_result = _FakeResult(
            mapping={("mixed", frozenset()): resolved}
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"mixed": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ) as drive:
            response = backend.resolve(request)

        assert drive.called
        assert isinstance(response.result, ResolverSuccess)

    def test_sdist_only_across_all_indexes_does_not_fire_emptiness(self):
        """Two indexes, both serving only sdists — the emptiness gate
        treats those candidates as present and does NOT fire.  T_S4
        decoupled the gate from artifact type, so the multi-index
        sdist-only shape (Phase 3a's worst-case) now resolves.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        idx_primary = "https://primary.example/simple"
        idx_secondary = "https://secondary.example/simple"

        cache = _FakeCache(
            {
                (idx_primary, "sdistonly"): (
                    _sdist_candidate("sdistonly", "1.0.0"),
                ),
                (idx_secondary, "sdistonly"): (
                    _sdist_candidate("sdistonly", "1.0.0"),
                ),
            }
        )
        fetcher = _FakeFetcher()
        resolved = _sdist_candidate("sdistonly", "1.0.0")
        fake_result = _FakeResult(
            mapping={("sdistonly", frozenset()): resolved}
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"sdistonly": "*"}),
            options=ResolverOptions(),
            sources=(
                Source(name="primary", url=idx_primary, verify_ssl=True),
                Source(name="secondary", url=idx_secondary, verify_ssl=True),
            ),
        )

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ) as drive:
            response = backend.resolve(request)

        assert drive.called
        assert isinstance(response.result, ResolverSuccess)

    def test_mixed_top_level_names_only_empty_one_in_message(self):
        """Three top-level packages: two have candidates (wheels), one
        has zero across every index.  The pre-check must fire naming
        ONLY the empty offender — the healthy siblings must not appear
        in the error message.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {
                (_INDEX, "healthy_one"): (
                    _wheel_candidate("healthy_one", "1.0.0"),
                ),
                (_INDEX, "healthy_two"): (
                    _wheel_candidate("healthy_two", "2.0.0"),
                ),
                # ``ghostpkg`` is missing from the cache entirely.
            }
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request(
            {
                "healthy_one": "*",
                "healthy_two": "*",
                "ghostpkg": "*",
            }
        )

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver"
        ) as drive:
            response = backend.resolve(request)

        # Pre-check short-circuited — resolvelib never ran.
        assert not drive.called
        assert isinstance(response.result, ResolutionError)
        msg = response.result.pip_message
        # Only the empty offender is named.
        assert "ghostpkg" in msg
        assert "healthy_one" not in msg
        assert "healthy_two" not in msg
        # Single-index spelling (one source on the request).
        assert "configured index." in msg or "configured index " in msg
        assert "configured indexes" not in msg

    def test_multi_index_uses_plural_spelling(self):
        """When more than one index is configured the error message
        uses the plural "indexes" form.  Pin this small grammatical
        detail so a refactor that drops the conditional doesn't leak
        ungrammatical English to users.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        idx_a = "https://a.example/simple"
        idx_b = "https://b.example/simple"

        cache = _FakeCache({})  # empty across both indexes
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"ghostpkg": "*"}),
            options=ResolverOptions(),
            sources=(
                Source(name="a", url=idx_a, verify_ssl=True),
                Source(name="b", url=idx_b, verify_ssl=True),
            ),
        )

        response = backend.resolve(request)

        assert isinstance(response.result, ResolutionError)
        assert "configured indexes" in response.result.pip_message


class TestGenericExceptionTranslatedToInternalError:
    """A truly unexpected exception out of :func:`_drive_resolver` (not
    :class:`ResolutionImpossible`) must be caught and translated into
    an :class:`InternalError` with the original message AND a
    non-empty traceback.  This is the catch-all branch — it stops a
    stray bug deep in the provider from crashing the resolver
    subprocess with an untranslated stack trace.  (Phase 3b T_S3
    removed the Phase 3a :class:`_SdistEncountered` clause that used
    to sit between :class:`ResolutionImpossible` and this catch-all.)
    """

    def test_unexpected_exception_yields_internal_error(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {
                (_INDEX, "requests"): (
                    _wheel_candidate("requests", "2.31.0"),
                ),
            }
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"requests": "*"})

        boom = RuntimeError("unexpected provider bug")
        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            side_effect=boom,
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, InternalError)
        assert "unexpected provider bug" in response.result.message
        # Traceback must be populated so the subprocess parent can log
        # the failure for the user.
        assert response.result.traceback is not None
        assert "RuntimeError" in response.result.traceback


class TestResolutionImpossibleFormattingEdges:
    """Edge cases of the :class:`ResolutionImpossible` translator.

    * Empty causes list (defensive) — produces a header-only
      ``pip_message`` and empty ``conflicts``.
    * ``parent is None`` (root requirement) — the formatter must
      render ``<root>`` rather than crashing on the missing attribute
      (line 401).
    * Parent object that lacks ``.name`` / ``.version`` — the
      formatter falls back to ``str(parent)`` (line 408).  This is the
      defensive branch for non-Candidate parent shapes the resolvelib
      protocol allows.
    """

    def test_empty_causes_yields_header_only_message(self):
        from pipenv.patched.pip._vendor.resolvelib import ResolutionImpossible

        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {(_INDEX, "x"): (_wheel_candidate("x", "1.0.0"),)}
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"x": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            side_effect=ResolutionImpossible([]),
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, ResolutionError)
        # Header still present, no per-cause lines.
        assert "Resolution impossible" in response.result.pip_message
        assert tuple(response.result.conflicts) == ()

    def test_root_parent_renders_as_root(self):
        from pipenv.patched.pip._vendor.resolvelib import ResolutionImpossible
        from pipenv.patched.pip._vendor.resolvelib.structs import (
            RequirementInformation,
        )

        from pipenv.resolver.backends.pure_python import PurePythonBackend
        from pipenv.resolver.pure_python_requirement import Requirement

        cache = _FakeCache(
            {(_INDEX, "rootpkg"): (_wheel_candidate("rootpkg", "1.0.0"),)}
        )
        req_root = Requirement.from_pipfile_entry("rootpkg", ">=99")
        causes = [RequirementInformation(requirement=req_root, parent=None)]

        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"rootpkg": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            side_effect=ResolutionImpossible(causes),
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, ResolutionError)
        # The root parent renders as the ``<root>`` sentinel.
        assert "<root>" in response.result.pip_message
        assert "rootpkg" in response.result.pip_message

    def test_parent_without_name_or_version_uses_str_fallback(self):
        from pipenv.patched.pip._vendor.resolvelib import ResolutionImpossible
        from pipenv.patched.pip._vendor.resolvelib.structs import (
            RequirementInformation,
        )

        from pipenv.resolver.backends.pure_python import PurePythonBackend
        from pipenv.resolver.pure_python_requirement import Requirement

        cache = _FakeCache(
            {(_INDEX, "leafpkg"): (_wheel_candidate("leafpkg", "1.0.0"),)}
        )

        # ``object()`` has no .name/.version — but its repr is stable
        # enough that we can find it back in the rendered message.
        class _OpaqueParent:
            def __str__(self) -> str:  # noqa: D401
                return "OPAQUE-PARENT-SENTINEL"

        opaque = _OpaqueParent()
        req = Requirement.from_pipfile_entry("leafpkg", ">=1")
        causes = [RequirementInformation(requirement=req, parent=opaque)]

        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"leafpkg": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            side_effect=ResolutionImpossible(causes),
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, ResolutionError)
        # str(parent) fallback wins.
        assert "OPAQUE-PARENT-SENTINEL" in response.result.pip_message


class TestSpecValueTranslation:
    """:meth:`PurePythonBackend._spec_value_to_pipfile_entry` translates
    the wire-shape ``pip-install`` argument string into a value the
    :class:`Requirement` parser accepts.  Three branches are pinned:

    * Empty / whitespace-only value → ``"*"`` (line 329).
    * Specifier-bearing value → everything from the first marker char
      onward (line 339).
    * Bare-name value → ``"*"`` (line 344).
    """

    def test_empty_string_returns_star(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", ""
        ) == "*"
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", "   "
        ) == "*"
        # ``None`` is tolerated and treated as empty (defensive).
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", None  # type: ignore[arg-type]
        ) == "*"

    def test_specifier_bearing_line_strips_to_marker_char(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # ``==``, ``>=``, ``<=``, ``~=``, ``!=`` are the canonical
        # multi-char markers; ``>`` / ``<`` are the single-char
        # fallbacks.  Each should peel back to the marker.
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", "requests==2.31.0"
        ) == "==2.31.0"
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", "requests>=2.0"
        ) == ">=2.0"
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "django", "django<5"
        ) == "<5"
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "django", "django>4"
        ) == ">4"
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "flask", "flask!=2.0"
        ) == "!=2.0"
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "numpy", "numpy~=1.24"
        ) == "~=1.24"

    def test_bare_name_returns_star(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", "requests"
        ) == "*"
        # Casing is ignored (line 343-344).
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", "Requests"
        ) == "*"

    def test_unparseable_falls_back_to_star(self):
        """The final fallback (line 345 / the ``return "*"`` at the
        very bottom) covers shapes like a stray URL or VCS ref that the
        wire doesn't pre-canonicalise.  We forward as ``"*"`` and let
        the upstream parser pin the dep on its own terms.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # No marker char, doesn't match the package name → final
        # ``return "*"`` fallback.
        assert PurePythonBackend._spec_value_to_pipfile_entry(
            "requests", "something-weird"
        ) == "*"


class TestTargetEnvCaching:
    """:meth:`PurePythonBackend._resolved_target_env` is supposed to
    return the explicitly-supplied ``target_env`` verbatim AND lazily
    cache the running-interpreter default on first call when no
    override was passed.  Both branches matter — the explicit override
    path is exercised by test fixtures, the default-population path
    by production.
    """

    def test_explicit_target_env_returned_verbatim(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        sentinel_env = {"python_version": "3.42", "sys_platform": "atari"}
        backend = PurePythonBackend(
            cache=_FakeCache({}),
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
            target_env=sentinel_env,
        )
        assert backend._resolved_target_env() is sentinel_env
        # Second call returns the same object — no recompute.
        assert backend._resolved_target_env() is sentinel_env

    def test_default_target_env_is_populated_lazily(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        backend = PurePythonBackend(
            cache=_FakeCache({}),
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        env1 = backend._resolved_target_env()
        # The running interpreter's marker env always defines
        # ``python_version`` (PEP 508).  We don't need to assert the
        # value — only that the default-environment shape is present.
        assert "python_version" in env1
        # Cached: the second call returns the same dict instance.
        env2 = backend._resolved_target_env()
        assert env2 is env1


class TestMetadataFetcherClosure:
    """The provider receives a one-argument metadata-fetcher closure
    that re-binds the session + metadata_cache from the backend
    instance.  Pin its forwarding behaviour so a future refactor that
    swaps the closure for a method can't silently change semantics —
    the existing T2 contract is "given a Candidate, return parsed
    metadata using the bound session and read-through cache".
    """

    def test_metadata_fetcher_forwards_to_fetch_metadata(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {
                (_INDEX, "requests"): (
                    _wheel_candidate("requests", "2.31.0"),
                ),
            }
        )
        session_sentinel = mock.MagicMock(name="session")
        metadata_cache_sentinel = mock.MagicMock(name="metadata_cache")
        resolved = _wheel_candidate("requests", "2.31.0")
        fake_result = _FakeResult(
            mapping={("requests", frozenset()): resolved}
        )

        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=session_sentinel,
            metadata_cache=metadata_cache_sentinel,
        )
        request = _build_request({"requests": "*"})

        captured: dict = {}

        def _drive_capturing(reqs, provider):
            # The provider's metadata_fetcher is the closure we want to
            # inspect.  Invoke it and capture the underlying call.
            captured["provider"] = provider
            return fake_result

        # Patch ``fetch_metadata`` at its import site inside the
        # backend module so the closure dispatches through our spy.
        sentinel_metadata = mock.MagicMock(name="CoreMetadata")
        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            side_effect=_drive_capturing,
        ), mock.patch(
            "pipenv.resolver.backends.pure_python.fetch_metadata",
            return_value=sentinel_metadata,
        ) as fetch_spy:
            response = backend.resolve(request)
            # Exercise the closure with a synthetic candidate.
            probe = _wheel_candidate("probe", "0.1.0")
            result = captured["provider"]._metadata_fetcher(probe)

        assert isinstance(response.result, ResolverSuccess)
        # The closure forwarded the bound session + metadata_cache.
        fetch_spy.assert_called_once_with(
            probe, session_sentinel, cache=metadata_cache_sentinel
        )
        assert result is sentinel_metadata


class TestTranslateMappingEdges:
    """:meth:`PurePythonBackend._translate_mapping` edge cases beyond
    the happy path in ``TestSuccessPath``.

    * Non-tuple identifier — the safety net at line 457-459 falls back
      to ``candidate.name`` + empty extras.
    * Candidate with no ``version`` — silently skipped (line 467).
    * Candidate with extras + multiple hashes — both populate the
      :class:`LockedRequirement`.
    """

    def test_non_tuple_identifier_falls_back_to_candidate_name(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {(_INDEX, "weird"): (_wheel_candidate("weird", "1.0.0"),)}
        )
        # Identifier is a BARE STRING, not a (name, frozenset(extras))
        # tuple.  resolvelib never produces this shape, but the
        # defensive unpacking branch at line 457-459 handles it
        # gracefully so test fixtures don't have to bother.
        resolved = _wheel_candidate("weird", "1.0.0")
        fake_result = _FakeResult(mapping={"weird-as-string": resolved})

        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"weird": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, ResolverSuccess)
        locked = tuple(response.result.locked)
        assert len(locked) == 1
        # The fallback picked up the candidate's own name.
        assert locked[0].name == "weird"
        assert locked[0].extras == ()

    def test_candidate_without_version_is_skipped(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {(_INDEX, "broken"): (_wheel_candidate("broken", "1.0.0"),)}
        )

        # A candidate-shaped object whose ``version`` is None — would
        # crash the LockedRequirement constructor (which rejects
        # version=None + no vcs/file/path).  The backend defensively
        # skips it.
        class _VersionlessCandidate:
            name = "broken"
            version = None
            hashes = frozenset()
            extras = frozenset()

        fake_result = _FakeResult(
            mapping={("broken", frozenset()): _VersionlessCandidate()}
        )

        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"broken": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ):
            response = backend.resolve(request)

        # The versionless candidate was silently dropped — success
        # with an EMPTY locked tuple rather than an exception.
        assert isinstance(response.result, ResolverSuccess)
        assert tuple(response.result.locked) == ()

    def test_candidate_with_extras_and_multiple_hashes(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {(_INDEX, "django"): (_wheel_candidate("django", "5.0.0"),)}
        )

        # Candidate carries two hashes + one extra — both should
        # propagate into the LockedRequirement.
        candidate_with_extras = Candidate(
            name="django",
            version="5.0.0",
            url=f"{_INDEX}/django/django-5.0.0-py3-none-any.whl",
            filename="django-5.0.0-py3-none-any.whl",
            hashes=frozenset(
                {
                    Hash("sha256", "a" * 64),
                    Hash("sha256", "b" * 64),
                }
            ),
            requires_python=">=3.10",
            yanked=False,
            yanked_reason=None,
            upload_time=None,
            is_wheel=True,
            wheel_tags=None,
            extras=frozenset({"argon2", "bcrypt"}),
        )
        fake_result = _FakeResult(
            mapping={
                ("django", frozenset({"argon2", "bcrypt"})):
                    candidate_with_extras,
            }
        )

        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"django": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, ResolverSuccess)
        locked = tuple(response.result.locked)
        assert len(locked) == 1
        entry = locked[0]
        # Hashes deduplicated & sorted; both ``a*64`` and ``b*64``
        # present.
        assert len(entry.hashes) == 2
        assert all(h.startswith("sha256:") for h in entry.hashes)
        assert tuple(entry.hashes) == tuple(sorted(entry.hashes))
        # Extras sorted alphabetically.
        assert entry.extras == ("argon2", "bcrypt")
        # T_M4: ``_build_request`` advertises ``Source(name="pypi",
        # url=_INDEX)`` ⇒ the URL maps to the source NAME ``"pypi"``
        # (pip-parity); pre-T_M4 this was the URL verbatim.
        assert entry.index == "pypi"

    def test_empty_specs_yields_empty_locked(self):
        """A request with an empty ``packages.specs`` is a degenerate
        but legal shape — the backend must not blow up and must
        return :class:`ResolverSuccess` with an empty locked tuple.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        backend = PurePythonBackend(
            cache=_FakeCache({}),
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({})  # no top-level packages

        # _drive_resolver returns an empty mapping for an empty
        # requirement set in production; mock the same.
        fake_result = _FakeResult(mapping={})
        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ) as drive:
            response = backend.resolve(request)

        assert drive.called
        assert isinstance(response.result, ResolverSuccess)
        assert tuple(response.result.locked) == ()


# ----------------------------------------------------------------------
# T_M3 (Initiative G Phase 3b): _translate_mapping emits ``markers`` on
# LockedRequirement.
# ----------------------------------------------------------------------
#
# The translator combines two marker sources:
#
# 1. **Requires-Python** — derived from ``candidate.requires_python``
#    (a ``SpecifierSet``-shaped string like ``">=3.10"``).  Each spec is
#    rendered as ``python_version <op> '<ver>'`` and joined with
#    ``and``.
# 2. **Introducing markers** — the ``introducing_marker`` slot
#    populated by T_M2 on every transitive ``Requirement``.  Pulled
#    from ``Result.criteria[identifier].information`` (the
#    ``RequirementInformation`` rows that selected this candidate).
#    Multiple introducing markers OR-join with parentheses (set theory:
#    a candidate satisfies the union of preconditions when any one
#    requirement holds).
#
# Combined with ``and`` when both sources contribute; ``None`` when
# neither does.
class TestTranslateMappingMarkers:
    """T_M3 marker emission on :meth:`PurePythonBackend._translate_mapping`."""

    @staticmethod
    def _candidate_with_requires_python(name: str, version: str, requires_python):
        """Build a wheel :class:`Candidate` overriding ``requires_python``."""
        filename = f"{name}-{version}-py3-none-any.whl"
        return Candidate(
            name=name,
            version=version,
            url=f"{_INDEX}/{name}/{filename}",
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

    @staticmethod
    def _info_rows(*requirements):
        """Build a tuple of ``RequirementInformation`` rows; parent is
        irrelevant for T_M3 (only ``.requirement.introducing_marker`` is
        consulted)."""
        from pipenv.patched.pip._vendor.resolvelib.structs import (
            RequirementInformation,
        )

        return tuple(
            RequirementInformation(requirement=r, parent=None)
            for r in requirements
        )

    def _resolve_for(self, *, candidate, criteria_info, top_name="pkg"):
        """Run :meth:`PurePythonBackend.resolve` with a synthetic
        ``_drive_resolver`` return value carrying ``mapping`` + the
        provided ``criteria_info``.  Returns the single
        :class:`LockedRequirement` emitted (asserts exactly one).
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        identifier = (top_name, frozenset())
        cache = _FakeCache({(_INDEX, top_name): (candidate,)})
        fake_result = _FakeResult(
            mapping={identifier: candidate},
            criteria={identifier: _FakeCriterion(criteria_info)},
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({top_name: "*"})
        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ):
            response = backend.resolve(request)
        assert isinstance(response.result, ResolverSuccess)
        locked = tuple(response.result.locked)
        assert len(locked) == 1
        return locked[0]

    def test_requires_python_emits_marker(self):
        """``requires_python=">=3.10"`` alone → markers carries the
        translated ``python_version >= '3.10'`` clause."""
        cand = self._candidate_with_requires_python("click", "8.3.3", ">=3.10")
        entry = self._resolve_for(
            candidate=cand,
            criteria_info=(),  # no introducing markers
            top_name="click",
        )
        assert entry.markers == "python_version >= '3.10'"

    def test_requires_python_range_emits_combined_marker(self):
        """``requires_python=">=3.8,<4"`` → ``python_version`` lower-
        and upper-bound joined with ``and`` in stable sorted order.
        """
        cand = self._candidate_with_requires_python("foo", "1.0", ">=3.8,<4")
        entry = self._resolve_for(
            candidate=cand,
            criteria_info=(),
            top_name="foo",
        )
        # The translator sorts specs to keep cross-run output stable.
        # ``"python_version < '4'"`` sorts before ``"python_version >= '3.8'"``
        # under default string comparison (``<`` (0x3c) < ``>`` (0x3e)).
        assert entry.markers == "python_version < '4' and python_version >= '3.8'"

    def test_introducing_marker_alone_emits_marker(self):
        """Candidate has no ``requires_python``; one ``Requirement``
        with a non-None ``introducing_marker`` selected it → its marker
        string is the sole contribution."""
        from pipenv.resolver.pure_python_requirement import Requirement
        from pipenv.vendor.packaging.markers import Marker
        from pipenv.vendor.packaging.specifiers import SpecifierSet

        intro = Marker("python_version < '3.10'")
        req = Requirement(
            name="bar",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=None,
            source="transitive",
            parent="some-parent",
            introducing_marker=intro,
        )
        cand = self._candidate_with_requires_python("bar", "1.0", None)
        entry = self._resolve_for(
            candidate=cand,
            criteria_info=self._info_rows(req),
            top_name="bar",
        )
        # The marker text is rendered by ``packaging.markers.Marker.__str__``
        # which uses double quotes around literal values.  We accept the
        # canonical packaging-rendered form as-is rather than normalising
        # to single quotes — both are PEP 508 valid and semantically
        # identical, and matching the upstream form keeps the translator
        # zero-allocation on the hot path.
        assert entry.markers == 'python_version < "3.10"'

    def test_requires_python_and_introducing_marker_combined(self):
        """Both sources contribute → joined with ``and``."""
        from pipenv.resolver.pure_python_requirement import Requirement
        from pipenv.vendor.packaging.markers import Marker
        from pipenv.vendor.packaging.specifiers import SpecifierSet

        intro = Marker("python_version < '3.12'")
        req = Requirement(
            name="baz",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=None,
            source="transitive",
            parent="some-parent",
            introducing_marker=intro,
        )
        cand = self._candidate_with_requires_python("baz", "1.0", ">=3.8")
        entry = self._resolve_for(
            candidate=cand,
            criteria_info=self._info_rows(req),
            top_name="baz",
        )
        # Combined with ``and`` (no parentheses for a single
        # introducing marker — only the multi-intro form parenthesises).
        # The Requires-Python contribution uses single-quoted literals
        # (``repr(str)``) while the introducing-marker contribution
        # comes through ``packaging.markers.Marker.__str__`` which
        # uses double quotes.  Two quoting conventions live side-by-side
        # in the same output — both are PEP 508 valid and we deliberately
        # preserve each source's canonical form rather than normalising.
        assert entry.markers == (
            "python_version >= '3.8' and python_version < \"3.12\""
        )

    def test_multiple_introducing_markers_or_joined(self):
        """Two requirements with distinct ``introducing_marker``s selected
        the same candidate → markers OR-joined with parentheses (a
        candidate satisfies the *union* of its requirements)."""
        from pipenv.resolver.pure_python_requirement import Requirement
        from pipenv.vendor.packaging.markers import Marker
        from pipenv.vendor.packaging.specifiers import SpecifierSet

        intro_a = Marker("python_version < '3.10'")
        intro_b = Marker("python_version >= '3.12'")
        req_a = Requirement(
            name="multi",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=None,
            source="transitive",
            parent="parent-a",
            introducing_marker=intro_a,
        )
        req_b = Requirement(
            name="multi",
            specifier=SpecifierSet(""),
            extras=frozenset(),
            marker=None,
            source="transitive",
            parent="parent-b",
            introducing_marker=intro_b,
        )
        cand = self._candidate_with_requires_python("multi", "1.0", None)
        entry = self._resolve_for(
            candidate=cand,
            criteria_info=self._info_rows(req_a, req_b),
            top_name="multi",
        )
        assert entry.markers is not None
        # Order-stable: insertion-order of ``information`` rows is
        # preserved by the translator so a fixture-driven assertion is
        # robust.  Marker strings come through
        # ``packaging.markers.Marker.__str__`` (double-quoted literals).
        assert entry.markers == (
            '(python_version < "3.10") or (python_version >= "3.12")'
        )

    def test_no_requires_python_no_introducing_marker_emits_none(self):
        """No ``requires_python`` AND no introducing marker → ``markers``
        stays ``None`` on the lockfile entry."""
        cand = self._candidate_with_requires_python("nada", "1.0", None)
        entry = self._resolve_for(
            candidate=cand,
            criteria_info=(),
            top_name="nada",
        )
        assert entry.markers is None

    def test_invalid_requires_python_falls_back_to_none(self):
        """An unparseable ``requires_python`` is treated as no
        contribution (defensive — mirrors T4's behaviour around bad
        ``Requires-Python`` advertisements on index manifests)."""
        cand = self._candidate_with_requires_python(
            "weirdpkg", "1.0", ">>not-a-spec<<"
        )
        entry = self._resolve_for(
            candidate=cand,
            criteria_info=(),
            top_name="weirdpkg",
        )
        # The bad ``requires_python`` produced no marker; no introducing
        # marker either → final ``markers`` is ``None``.
        assert entry.markers is None


# ----------------------------------------------------------------------
# T_M4 (Initiative G Phase 3b): _translate_mapping emits source NAME for
# the ``index`` field, not the URL.
# ----------------------------------------------------------------------
#
# Pip's lockfile writes ``index=<source-name>`` (e.g. ``"pypi"``) per the
# Pipfile ``[[source]]`` block's ``name`` key — NOT the raw URL.  Pre-T_M4
# the pure-python backend wrote ``index=<index-url>`` because the Phase 3
# Candidate doesn't track which configured source served it (T4 walks
# every ``index_url`` and concatenates).
#
# T_M4 closes the gap by building a ``url → name`` map from
# ``request.sources`` and looking up the source name at translate time.
# When the URL doesn't match any configured source (defensive fallback —
# Phase 4 will track per-candidate source attribution), the URL is
# emitted as-is.  When ``request.sources`` is empty (subprocess fixtures
# sometimes omit it), the backend's configured default-URL is used
# directly (still a URL — no source list ⇒ no mapping possible).
class TestTranslateMappingIndexName:
    """T_M4: ``LockedRequirement.index`` carries the source NAME when the
    candidate's index-URL matches a configured ``[[source]]`` block;
    otherwise the URL is emitted verbatim as a defensive fallback.
    """

    def test_url_maps_to_source_name(self):
        """``request.sources = [Source(name="pypi", url="https://pypi.org/simple")]``
        + candidate from that URL ⇒ ``index == "pypi"`` (pip-parity)."""
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {(_INDEX, "click"): (_wheel_candidate("click", "8.3.3"),)}
        )
        resolved = _wheel_candidate("click", "8.3.3")
        fake_result = _FakeResult(
            mapping={("click", frozenset()): resolved}
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        # _build_request() already produces sources=(Source(name="pypi",
        # url=_INDEX, verify_ssl=True),) — the canonical single-source
        # case.
        request = _build_request({"click": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, ResolverSuccess)
        locked = tuple(response.result.locked)
        assert len(locked) == 1
        # Source NAME, not URL: pip writes ``"pypi"``, not the URL.
        assert locked[0].index == "pypi"

    def test_unmatched_url_falls_back_to_url(self):
        """``request.sources`` carries a single source whose URL does NOT
        match the backend's configured ``index_urls`` ⇒ the URL is
        emitted verbatim as a defensive fallback.

        Construction: pass ``index_urls`` explicitly so the resolve path
        consults that URL while ``request.sources`` advertises a
        different one.  The URL→name map built from ``request.sources``
        therefore has no entry for the default URL ⇒ fallback fires.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # Backend's default index — the URL the resolve path lands on.
        unmatched_url = "https://pypi.org/simple"
        # request.sources advertises a different URL under a custom name.
        # The URL→name map built from ``request.sources`` will only
        # contain ``https://other.example/simple -> "custom"`` — no entry
        # for the unmatched_url default, so the fallback fires.
        custom_source = Source(
            name="custom", url="https://other.example/simple", verify_ssl=True
        )
        cache = _FakeCache(
            {
                (unmatched_url, "pkg"): (_wheel_candidate("pkg", "1.0.0"),),
                # Also seed the request-source URL so the prefetch path
                # has something to find (not strictly required but
                # mirrors a realistic production cache).
                (custom_source.url, "pkg"): (
                    _wheel_candidate("pkg", "1.0.0"),
                ),
            }
        )
        resolved = _wheel_candidate("pkg", "1.0.0")
        fake_result = _FakeResult(
            mapping={("pkg", frozenset()): resolved}
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
            # Force the resolve path to land on unmatched_url as the
            # default_index even though request.sources advertises
            # custom_source.url.  We achieve this by building a request
            # whose sources contain ONLY custom_source — then
            # request_index_urls is (custom_source.url,) and
            # default_index is custom_source.url, which IS in url_to_name
            # ⇒ wrong test.  Reverse: supply request.sources with a
            # source whose URL doesn't match the default_index — but
            # default_index IS the first source URL.  So the path can
            # only produce an unmatched default_index when the URL→name
            # map omits it.  Concretely: the test exercises the
            # defensive branch via the dict.get fallback semantic — see
            # below.
        )
        # Build a request whose sources advertise custom_source.  The
        # backend will set ``request_index_urls = (custom_source.url,)``
        # and ``default_index = custom_source.url``.  ``url_to_name``
        # maps ``custom_source.url -> "custom"`` ⇒ this is the
        # HAPPY-path mapping, not the fallback.
        #
        # To exercise the FALLBACK we instead force ``default_index`` to
        # a URL absent from ``url_to_name`` by hand-patching the
        # translator: we want a unit-level assertion on the defensive
        # branch, so call ``_translate_mapping`` directly with a mocked
        # url_to_name that omits the default_index.
        from pipenv.resolver.schema import LockedRequirement

        url_to_name = {custom_source.url: custom_source.name}
        # default_index = unmatched_url which is NOT in url_to_name.
        criteria: dict = {}
        from pipenv.resolver.backends.pure_python import PurePythonBackend as _B

        translator_backend = _B(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )

        class _StubResult:
            def __init__(self):
                self.mapping = {("pkg", frozenset()): resolved}
                self.criteria = criteria

        locked = translator_backend._translate_mapping(
            _StubResult(),
            (unmatched_url,),  # index_urls[0] = unmatched_url
            url_to_name,
        )
        assert len(locked) == 1
        # Defensive fallback: no source matched ⇒ emit URL verbatim.
        assert isinstance(locked[0], LockedRequirement)
        assert locked[0].index == unmatched_url

    def test_no_sources_emits_url(self):
        """``request.sources == ()`` (subprocess fixtures sometimes omit
        the source list) ⇒ ``url_to_name`` is empty ⇒ defensive fallback
        emits the default-index URL verbatim.  No source list ⇒ no
        mapping is possible.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend
        from pipenv.resolver.schema import (
            PackageSpecs,
            ResolverOptions,
            ResolverRequest,
        )

        cache = _FakeCache(
            {(_INDEX, "lonely"): (_wheel_candidate("lonely", "1.0.0"),)}
        )
        resolved = _wheel_candidate("lonely", "1.0.0")
        fake_result = _FakeResult(
            mapping={("lonely", frozenset()): resolved}
        )
        # Build a request with an EMPTY sources tuple — the backend
        # falls through to its configured default ``index_urls``.
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"lonely": "*"}),
            options=ResolverOptions(),
            sources=(),
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
            index_urls=(_INDEX,),
        )

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ):
            response = backend.resolve(request)

        assert isinstance(response.result, ResolverSuccess)
        locked = tuple(response.result.locked)
        assert len(locked) == 1
        # No sources ⇒ no URL→name mapping possible ⇒ emit URL.
        assert locked[0].index == _INDEX


# ----------------------------------------------------------------------
# T10: Backend registration
# ----------------------------------------------------------------------
#
# These tests verify the pure-python backend is wired into the
# Initiative F registry (``pipenv/resolver/backends/__init__.py``) under
# the name ``"pure-python"``.  T9 built the class; T10 makes it
# discoverable via ``get_backend``.
class TestBackendRegistration:
    def test_get_backend_returns_pure_python(self):
        from pipenv.resolver.backends import get_backend
        backend = get_backend("pure-python")
        assert backend.name == "pure-python"

    def test_pure_python_backend_is_available(self):
        from pipenv.resolver.backends import get_backend
        backend = get_backend("pure-python")
        assert backend.is_available() is True


# ----------------------------------------------------------------------
# T9b: Bootstrap-from-request (2026-05-12)
# ----------------------------------------------------------------------
#
# T10 made ``PurePythonBackend.__init__`` zero-arg-constructible by
# defaulting the four collaborators (``cache``, ``fetcher``, ``session``,
# ``metadata_cache``) to ``None``.  That left a gap: the registry path
# (``get_backend("pure-python")``) lands inside ``resolve()`` with every
# collaborator set to ``None``, so ``self._fetcher.populate(targets)``
# would NPE.  T9b closes the gap by adding ``_bootstrap_from_request``
# which constructs sensible defaults from the request envelope when
# fields are missing.  These tests pin the bootstrap path; the existing
# kwarg-injection path is unaffected (regression-covered by the 24
# tests above).
class TestBootstrapFromRequest:
    """:meth:`PurePythonBackend._bootstrap_from_request` populates the
    four collaborators from the :class:`ResolverRequest` when they are
    ``None`` on ``self``.  Pre-injected collaborators win — the
    bootstrap is idempotent and never overwrites a non-None field.
    """

    def test_bootstrap_populates_missing_collaborators(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend
        from pipenv.resolver.fetcher import ParallelFetcher
        from pipenv.resolver.manifest_cache import ParsedManifestCache
        from pipenv.resolver.pure_python_metadata import MetadataCache

        backend = PurePythonBackend()  # zero-arg path (registry shape)
        # Every collaborator starts as ``None`` — pins the precondition
        # T10 introduced (without it, the bootstrap test would be
        # vacuously true).
        assert backend._cache is None
        assert backend._fetcher is None
        assert backend._session is None
        assert backend._metadata_cache is None

        request = _build_request({"requests": "*"})
        backend._bootstrap_from_request(request)

        # All four collaborators are now populated with concrete
        # instances of the canonical classes.
        assert isinstance(backend._cache, ParsedManifestCache)
        assert isinstance(backend._fetcher, ParallelFetcher)
        assert backend._session is not None
        assert isinstance(backend._metadata_cache, MetadataCache)

        # Idempotency: a second call must not rebuild any collaborator
        # (sentinel-by-identity on each of the four).
        prior_cache = backend._cache
        prior_fetcher = backend._fetcher
        prior_session = backend._session
        prior_metadata_cache = backend._metadata_cache
        backend._bootstrap_from_request(request)
        assert backend._cache is prior_cache
        assert backend._fetcher is prior_fetcher
        assert backend._session is prior_session
        assert backend._metadata_cache is prior_metadata_cache

    def test_bootstrap_preserves_injected_collaborators(self):
        """Tests that pass collaborators via ``__init__`` kwargs must
        not have them silently replaced by the bootstrap step.  Pinned
        explicitly because the regression vector here is invisible —
        a future "always rebuild" refactor would pass every other test
        in this file while breaking the kwarg-injection contract that
        the rest of the suite (24 tests) relies on.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        sentinel_cache = _FakeCache({})
        sentinel_fetcher = _FakeFetcher()
        sentinel_session = mock.MagicMock(name="session-sentinel")
        sentinel_metadata_cache = mock.MagicMock(name="metadata-cache-sentinel")

        backend = PurePythonBackend(
            cache=sentinel_cache,
            fetcher=sentinel_fetcher,
            session=sentinel_session,
            metadata_cache=sentinel_metadata_cache,
        )
        backend._bootstrap_from_request(_build_request({"requests": "*"}))

        # Every pre-injected collaborator survived unchanged (identity
        # check — same object, not "equal").
        assert backend._cache is sentinel_cache
        assert backend._fetcher is sentinel_fetcher
        assert backend._session is sentinel_session
        assert backend._metadata_cache is sentinel_metadata_cache
