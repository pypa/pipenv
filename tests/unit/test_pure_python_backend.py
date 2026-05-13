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
    """Q-F top-level wheel-availability pre-check edge cases beyond the
    plain sdist-only top-level path covered by ``TestQFPreCheck``.

    Three rows pinned here:

    1. Cache miss across every index (``manifest is None`` for every
       lookup) — the pre-check must NOT fire.  This is the "different
       failure" path: zero candidates means resolvelib will surface
       its own "no candidates available" error; Q-F should not preempt
       that with a misleading sdist-only-top message.
    2. Mixed sdist + wheel candidates — Q-F must NOT fire because a
       wheel IS available (we only block when the top-level is
       sdist-only).
    3. Multi-top-level with one wheel-bearing + one sdist-only package
       — Q-F fires for the offender and the message references it
       specifically.
    """

    def test_empty_cache_does_not_fire_qf(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # Cache returns None for every (index, name) lookup → manifest
        # is None → the inner ``continue`` branch (line 179) is exercised
        # and Q-F does NOT fire.  resolvelib is still called and we let
        # its synthetic result come through unimpeded.
        cache = _FakeCache({})  # empty
        fetcher = _FakeFetcher()

        # A synthetic empty mapping so the post-resolve translation
        # path returns an empty locked tuple.
        fake_result = _FakeResult(mapping={})
        backend = PurePythonBackend(
            cache=cache,
            fetcher=fetcher,
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = _build_request({"ghostpkg": "*"})

        with mock.patch(
            "pipenv.resolver.backends.pure_python._drive_resolver",
            return_value=fake_result,
        ) as drive:
            response = backend.resolve(request)

        # _drive_resolver WAS called — Q-F did not short-circuit.
        assert drive.called
        # And the result is success (empty mapping → empty locked).
        assert isinstance(response.result, ResolverSuccess)
        assert tuple(response.result.locked) == ()

    def test_mixed_sdist_and_wheel_does_not_fire_qf(self):
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        # Mixed candidates: a sdist AND a wheel for the same package.
        # The Q-F pre-check should see ``saw_wheel=True`` on the wheel
        # and NOT mark the top-level as sdist-only.
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

    def test_qf_message_includes_python_marker_override(self):
        """When ``request.python_marker_override`` is set the Q-F error
        message must use it instead of the running interpreter — line
        354 of the backend.  Pin this so the (rarely-tested) marker
        override path keeps formatting correctly.
        """
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        cache = _FakeCache(
            {
                (_INDEX, "brokenpkg"): (
                    _sdist_candidate("brokenpkg", "1.0.0"),
                ),
            }
        )
        backend = PurePythonBackend(
            cache=cache,
            fetcher=_FakeFetcher(),
            session=mock.MagicMock(),
            metadata_cache=mock.MagicMock(),
        )
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"brokenpkg": "*"}),
            options=ResolverOptions(),
            sources=(Source(name="pypi", url=_INDEX, verify_ssl=True),),
            python_marker_override="3.11",
        )

        response = backend.resolve(request)

        assert isinstance(response.result, ResolutionError)
        # The override string itself is woven into the user-facing
        # message body (rather than the running interpreter version).
        assert "3.11" in response.result.pip_message


class TestGenericExceptionTranslatedToInternalError:
    """A truly unexpected exception out of :func:`_drive_resolver` (not
    :class:`ResolutionImpossible`, not :class:`_SdistEncountered`)
    must be caught and translated into an :class:`InternalError` with
    the original message AND a non-empty traceback.  This is the
    catch-all branch at lines 293-294 — it stops a stray bug deep in
    the provider from crashing the resolver subprocess with an
    untranslated stack trace.
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
        # Index stays Phase-3-default (first URL).
        assert entry.index == _INDEX

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
