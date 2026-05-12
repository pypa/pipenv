"""Unit tests for the unified resolver entry point introduced by T_F.4.

T_F.3 left the resolver with TWO call sites for the underlying
``resolve_packages`` driver:

1. ``pipenv/resolver/main.py:_main`` — the subprocess entry, which
   reads/writes a JSON envelope.
2. ``pipenv/utils/resolver.py`` ``venv_resolve_deps`` debug bypass
   (``PIPENV_RESOLVER_PARENT_PYTHON=1``) — runs the same driver in the
   parent interpreter and skips the JSON round-trip.

T_F.4 folds both call sites onto one canonical entry,
:func:`pipenv.resolver.core.resolve_for_pipenv`, that takes a typed
``ResolverRequest`` and returns a typed ``ResolverResponse`` with the
discriminated ``result.kind``.  Both adapters become thin wrappers
around that single function.

These tests mock the inner ``resolve_packages`` call to keep the unit
boundary tight; the full subprocess round-trip is exercised by
``tests/unit/test_resolver_protocol_smoke.py`` and the integration
golden test under ``tests/integration/test_resolver_protocol.py``.
"""
from __future__ import annotations

from unittest import mock

import pytest

from pipenv.exceptions import ResolutionFailure
from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    InternalError,
    LockedRequirement,
    PackageSpecs,
    ResolutionError,
    ResolverOptions,
    ResolverRequest,
    ResolverResponse,
    ResolverSuccess,
    Source,
)


def _build_request(**overrides) -> ResolverRequest:
    kwargs = dict(
        schema_version=SCHEMA_VERSION,
        category="default",
        packages=PackageSpecs(specs={"requests": "requests==2.31.0"}),
        options=ResolverOptions(),
        sources=(
            Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
        ),
    )
    kwargs.update(overrides)
    return ResolverRequest(**kwargs)


class TestResolveForPipenvSuccess:
    """Happy path: ``resolve_packages`` returns a list of LockedRequirements;
    ``resolve_for_pipenv`` wraps them in a ``ResolverSuccess`` response.
    """

    def test_returns_resolver_response_with_success_variant(self):
        from pipenv.resolver import core

        locked = [LockedRequirement(name="requests", version="==2.31.0")]

        with mock.patch.object(
            core, "resolve_packages", return_value=(locked, None)
        ):
            response = core.resolve_for_pipenv(_build_request())

        assert isinstance(response, ResolverResponse)
        assert response.schema_version == SCHEMA_VERSION
        assert isinstance(response.result, ResolverSuccess)
        assert response.result.kind == "success"
        assert list(response.result.locked) == locked

    def test_empty_locked_list_still_yields_success(self):
        from pipenv.resolver import core

        with mock.patch.object(
            core, "resolve_packages", return_value=([], None)
        ):
            response = core.resolve_for_pipenv(_build_request())

        assert isinstance(response.result, ResolverSuccess)
        assert list(response.result.locked) == []


class TestResolveForPipenvResolutionError:
    """When ``resolve_packages`` raises a dependency-conflict-style
    exception (the kind users can fix by changing their Pipfile),
    ``resolve_for_pipenv`` converts it to a ``ResolutionError`` response
    rather than letting it propagate.
    """

    def test_resolution_failure_becomes_resolution_error_response(self):
        from pipenv.resolver import core

        def _raise(_request):
            raise ResolutionFailure("ResolutionImpossible: foo+bar")

        with mock.patch.object(core, "resolve_packages", side_effect=_raise):
            response = core.resolve_for_pipenv(_build_request())

        assert isinstance(response.result, ResolutionError)
        assert response.result.kind == "resolution_error"
        assert "ResolutionImpossible" in response.result.pip_message


class TestResolveForPipenvInternalError:
    """Any other unexpected exception inside ``resolve_packages`` is
    captured as a structured ``InternalError`` response.  The function
    NEVER lets the exception propagate — both adapters need a typed
    response to dispatch on.
    """

    def test_unexpected_exception_becomes_internal_error_response(self):
        from pipenv.resolver import core

        def _explode(_request):
            raise AttributeError("pip exploded")

        with mock.patch.object(core, "resolve_packages", side_effect=_explode):
            response = core.resolve_for_pipenv(_build_request())

        assert isinstance(response.result, InternalError)
        assert response.result.kind == "internal_error"
        assert "pip exploded" in response.result.message
        # Traceback present so post-mortem debugging stays possible.
        assert response.result.traceback is not None
        assert "AttributeError" in response.result.traceback


class TestResolveForPipenvPythonMarkerOverride:
    """The python_marker_override on the request triggers the marker patch
    inside ``resolve_for_pipenv`` so both adapters benefit from the same
    behaviour — no parent-side ``_patched_marker_environment`` wrapper
    needed.
    """

    def test_marker_override_is_applied_before_resolve(self):
        from pipenv.resolver import core

        captured_env = {}

        def _capture_default_environment_state(_request):
            import pipenv.patched.pip._vendor.packaging.markers as pip_markers

            env = pip_markers.default_environment()
            captured_env.update(env)
            return [], None

        with mock.patch.object(
            core, "resolve_packages", side_effect=_capture_default_environment_state
        ):
            response = core.resolve_for_pipenv(
                _build_request(python_marker_override="3.11.0")
            )

        assert isinstance(response.result, ResolverSuccess)
        assert captured_env.get("python_version") == "3.11"
        assert captured_env.get("python_full_version") == "3.11.0"

    def test_marker_override_is_restored_after_resolve(self):
        """The override must NOT leak out of ``resolve_for_pipenv``
        — both adapters call this synchronously, and the parent
        interpreter's marker environment must be restored on return.
        """
        import pipenv.patched.pip._vendor.packaging.markers as pip_markers

        from pipenv.resolver import core

        orig = pip_markers.default_environment

        with mock.patch.object(core, "resolve_packages", return_value=([], None)):
            core.resolve_for_pipenv(
                _build_request(python_marker_override="3.11.0")
            )

        assert pip_markers.default_environment is orig
