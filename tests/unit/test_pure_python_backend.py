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
* **Sdist fail-loud** (:class:`_SdistEncountered`, Q-A) — translated
  into :class:`InternalError`; the pip backend is NOT invoked as a
  fallback (deliberate fail-loud per design Q-A 2026-05-12).
* **Q-F top-level wheel-availability pre-check** — when a top-level
  package has candidates but ZERO are wheels (sdist-only top-level),
  the backend aborts BEFORE driving resolvelib, returning a
  :class:`ResolutionError` whose ``pip_message`` names the offending
  package and suggests ``pipenv lock --backend pip``.

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
    """Synthetic stand-in for ``resolvelib.Result`` carrying ``.mapping``."""

    def __init__(self, mapping: dict) -> None:
        self.mapping = mapping


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


class TestSdistEncounteredFailLoud:
    """Mock :func:`_drive_resolver` to raise :class:`_SdistEncountered`
    → backend returns :class:`InternalError` whose ``message`` contains
    the package name, version, "sdist-only", and "pipenv lock".

    Critically: the pip backend is NEVER invoked as a fallback
    (Initiative G phase 3 Q-A: fail-loud, no silent fallback).  We
    assert this by checking the result is exactly :class:`InternalError`
    — a pip-fallback would have returned :class:`ResolverSuccess`.
    """

    def test_sdist_encountered_translates_to_internal_error(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend
        from pipenv.resolver.pure_python_provider import _SdistEncountered

        cache = _FakeCache(
            {
                # Top-level "broken" has a wheel candidate so the Q-F
                # pre-check passes; the sdist failure is TRANSITIVE.
                (_INDEX, "broken"): (_wheel_candidate("broken", "1.0.0"),),
            }
        )
        fetcher = _FakeFetcher()

        # Build the offending sdist candidate the provider would have
        # tried to expand.
        offending = _sdist_candidate("legacy-dep", "0.9.0")
        sdist_exc = _SdistEncountered(offending)

        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"broken": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            side_effect=sdist_exc,
        ) as drive:
            response = backend.resolve(request)

        # _drive_resolver IS called in the transitive-sdist case (the
        # Q-F pre-check only fires for sdist-only TOP-LEVEL packages).
        assert drive.called

        assert isinstance(response, ResolverResponse)
        # Fail-loud: InternalError, NOT ResolverSuccess.  A silent
        # pip-backend fallback would have produced ResolverSuccess.
        assert isinstance(response.result, InternalError)
        msg = response.result.message
        assert "legacy-dep" in msg
        assert "0.9.0" in msg
        assert "sdist-only" in msg
        # Per the Q-A 2026-05-12 sign-off, the message must direct the
        # user to switch backends — recovery path.
        assert "resolver_backend" in msg
        assert "pip" in msg


class TestQFPreCheck:
    """Mock cache with a top-level package whose only candidates are
    sdists → backend returns :class:`ResolutionError` naming the package
    and suggesting ``pipenv lock --backend pip``.  :func:`_drive_resolver`
    is NEVER invoked (Q-F pre-check fires before resolution).
    """

    def test_sdist_only_top_level_aborts_before_drive(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # ``brokenpkg`` has only an sdist candidate.  The Q-F pre-check
        # must fire and abort BEFORE resolvelib runs.
        cache = _FakeCache(
            {
                (_INDEX, "brokenpkg"): (
                    _sdist_candidate("brokenpkg", "1.0.0"),
                ),
            }
        )
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

        # _drive_resolver MUST NOT have been called — the pre-check
        # short-circuits before resolvelib runs.
        assert not drive.called

        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, ResolutionError)
        msg = response.result.pip_message
        assert "brokenpkg" in msg
        assert "pipenv lock --backend pip" in msg
