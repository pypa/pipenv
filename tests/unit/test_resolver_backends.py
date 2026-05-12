"""Unit tests for the pluggable resolver-backend registry scaffolding (T_F.5).

T_F.5 introduces a ``pipenv/resolver/backends/`` subpackage with a
``Backend`` protocol, a name -> backend registry, and a ``PipBackend``
that wraps the existing :func:`pipenv.resolver.core.resolve_for_pipenv`
flow so its behaviour is identical to the pre-T_F.5 default.  The uv
backend is **not** part of T_F.5 — see the maintainer sign-off addendum
in ``docs/dev/initiative-f-backends-design.md`` (2026-05-12), answer 8.

The tests below verify the scaffolding only:

* the registry dispatches to ``PipBackend`` by default,
* unknown backend names fail loud with a clear message,
* the pip backend's ``resolve(request)`` produces the same response as
  the canonical resolve driver,
* an unavailable backend yields a structured ``InternalError`` (NOT a
  crash) per sign-off answer 4 (fail-loud),
* the precedence chain CLI > env > Pipfile > default is respected,
* the ``[pipenv] resolver`` Pipfile key is read by ``Settings``.
"""
from __future__ import annotations

from unittest import mock

import pytest

from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    InternalError,
    LockedRequirement,
    PackageSpecs,
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


class TestRegistryDispatch:
    def test_registry_dispatches_pip_backend(self):
        """``get_backend("pip")`` returns a PipBackend instance."""
        from pipenv.resolver.backends import REGISTRY, get_backend
        from pipenv.resolver.backends.pip import PipBackend

        assert "pip" in REGISTRY
        assert REGISTRY["pip"] is PipBackend
        backend = get_backend("pip")
        assert isinstance(backend, PipBackend)
        assert backend.name == "pip"

    def test_unknown_backend_fails_loud(self):
        """Asking for a backend that isn't registered raises with a clear
        message that names the bad backend AND lists the available ones.
        """
        from pipenv.resolver.backends import get_backend

        with pytest.raises(KeyError) as exc_info:
            get_backend("nonexistent")
        msg = str(exc_info.value)
        assert "nonexistent" in msg
        # Available backends must be listed for the user to recover from
        # the typo.
        assert "pip" in msg

    def test_pip_backend_is_available(self):
        """The pip backend is always available — it's the built-in
        default, no external binary to discover.
        """
        from pipenv.resolver.backends import get_backend

        assert get_backend("pip").is_available() is True


class TestPipBackendAdapterShape:
    """``PipBackend().resolve(request)`` is a thin shim around the existing
    resolve flow that previously lived inline in ``resolve_for_pipenv``.
    Given the same request, both call paths produce the same response.
    """

    def test_pip_backend_resolve_matches_resolve_for_pipenv(self):
        from pipenv.resolver import core
        from pipenv.resolver.backends import get_backend

        locked = [LockedRequirement(name="requests", version="==2.31.0")]
        request = _build_request()

        # ``resolve_for_pipenv`` now dispatches through the registry to
        # ``PipBackend.resolve``; both call paths invoke the same inner
        # ``resolve_packages`` so they must produce equivalent responses.
        with mock.patch.object(core, "resolve_packages", return_value=(locked, None)):
            response_via_dispatcher = core.resolve_for_pipenv(request)

        with mock.patch.object(core, "resolve_packages", return_value=(locked, None)):
            response_via_backend = get_backend("pip").resolve(request)

        assert isinstance(response_via_dispatcher, ResolverResponse)
        assert isinstance(response_via_backend, ResolverResponse)
        assert isinstance(response_via_dispatcher.result, ResolverSuccess)
        assert isinstance(response_via_backend.result, ResolverSuccess)
        # The locked entries must round-trip identically.
        assert list(response_via_backend.result.locked) == locked
        assert (
            list(response_via_dispatcher.result.locked)
            == list(response_via_backend.result.locked)
        )

    def test_missing_backend_returns_internal_error(self):
        """If a configured backend's ``is_available()`` returns False,
        ``resolve_for_pipenv`` returns a structured ``InternalError``
        response — NOT a crash.  The message names the missing backend
        per sign-off answer 4.
        """
        from pipenv.resolver import core
        from pipenv.resolver.backends import base as backends_base

        class _UnavailableBackend:
            name = "phantom"

            def is_available(self) -> bool:
                return False

            def resolve(self, request):  # pragma: no cover — never called
                raise AssertionError("unavailable backend.resolve must not run")

        request = _build_request()

        # Pre-bind the backend selector to "phantom" and register a fake
        # backend that reports unavailable, then run the dispatcher.
        with mock.patch.object(
            core, "_selected_backend_name", return_value="phantom"
        ), mock.patch.dict(
            backends_base.REGISTRY, {"phantom": _UnavailableBackend()}
        ):
            response = core.resolve_for_pipenv(request)

        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, InternalError)
        assert "phantom" in response.result.message


class TestPrecedence:
    """CLI > env var > Pipfile > default."""

    def test_resolver_precedence_cli_over_pipfile(self):
        """The CLI selection wins over the Pipfile selection."""
        from pipenv.resolver import core

        request = _build_request(
            options=ResolverOptions(backend="uv"),  # CLI / explicit-on-request
        )

        # The Pipfile-derived hint says "pip" (would be the fall-through);
        # the explicit request says "uv".  CLI wins.
        with mock.patch.object(
            core, "_resolver_name_from_pipfile", return_value="pip"
        ), mock.patch.object(core, "_resolver_name_from_env", return_value=None):
            chosen = core._selected_backend_name(request)
        assert chosen == "uv"

    def test_resolver_precedence_env_over_pipfile(self):
        """The PIPENV_RESOLVER env var wins over the Pipfile value when
        the CLI did not specify a backend.
        """
        from pipenv.resolver import core

        request = _build_request(options=ResolverOptions())  # no CLI override
        with mock.patch.object(
            core, "_resolver_name_from_pipfile", return_value="pip"
        ), mock.patch.object(
            core, "_resolver_name_from_env", return_value="uv"
        ):
            chosen = core._selected_backend_name(request)
        assert chosen == "uv"

    def test_resolver_default_is_pip(self):
        """With nothing configured at any level the default is pip."""
        from pipenv.resolver import core

        request = _build_request(options=ResolverOptions())
        with mock.patch.object(
            core, "_resolver_name_from_pipfile", return_value=None
        ), mock.patch.object(
            core, "_resolver_name_from_env", return_value=None
        ):
            chosen = core._selected_backend_name(request)
        assert chosen == "pip"


class TestPipfileResolverSetting:
    """``[pipenv] resolver = "..."`` in the Pipfile is read via Settings."""

    def test_pipfile_resolver_reads_pipenv_section(self):
        """Settings exposes a ``resolver`` accessor that returns the
        ``[pipenv] resolver`` key (None when absent).
        """
        from pipenv.utils.settings import Settings

        # Fake project shape that exposes the parsed pipfile mapping.
        class _FakeProject:
            def __init__(self, table):
                self.parsed_pipfile = {"pipenv": table}

        settings_with = Settings(_FakeProject({"resolver": "pip"}))
        assert settings_with.resolver == "pip"

        # And the absent case returns None (the default).
        settings_without = Settings(_FakeProject({}))
        assert settings_without.resolver is None
