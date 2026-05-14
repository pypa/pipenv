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

        # Fake project shape that exposes a ``pipfile.parsed`` mapping.
        class _FakePipfile:
            def __init__(self, table):
                self.parsed = {"pipenv": table}

        class _FakeProject:
            def __init__(self, table):
                self.pipfile = _FakePipfile(table)

        settings_with = Settings(_FakeProject({"resolver": "pip"}))
        assert settings_with.resolver == "pip"

        # And the absent case returns None (the default).
        settings_without = Settings(_FakeProject({}))
        assert settings_without.resolver is None


# ---------------------------------------------------------------------------
# T_PLUMBING (Initiative G phase 3): CLI flag + Pipfile-setting dispatcher
# ---------------------------------------------------------------------------
#
# T_F.5 wired the dispatcher inside :mod:`pipenv.resolver.core` and added
# the ``--resolver`` free-form CLI flag.  T_PLUMBING adds the
# user-facing ``--backend`` flag (constrained ``choices=``), the
# ``[pipenv] resolver_backend`` Pipfile-setting accessor, and the
# parent-side precedence chain inside ``do_lock`` that stamps the
# resolved name onto the typed ``ResolverRequest.options.backend``
# field via ``venv_resolve_deps(resolver_backend=...)``.
#
# These tests pin the four user-visible behaviours of T_PLUMBING:
#
#  1. ``--backend pure-python`` routes through ``state.resolver`` ->
#     ``RoutineContext.execution_options.resolver``.
#  2. ``[pipenv] resolver_backend = "pure-python"`` is read by Settings
#     and is preferred over the T_F.5 ``[pipenv] resolver`` back-compat
#     alias.
#  3. CLI flag wins over Pipfile setting.
#  4. Default (neither set) yields ``None`` so the wire shape stays
#     empty and the dispatcher's no-op default-path is byte-identical
#     to today.


class TestPipfileResolverBackendSetting:
    """``[pipenv] resolver_backend = "..."`` is the documented user-facing
    Pipfile setting (T_PLUMBING).  ``[pipenv] resolver`` is the T_F.5
    back-compat alias; both go through :class:`Settings` accessors.
    """

    def _fake_project(self, table):
        class _FakePipfile:
            def __init__(self, t):
                self.parsed = {"pipenv": t}

        class _FakeProject:
            def __init__(self, t):
                self.pipfile = _FakePipfile(t)

        return _FakeProject(table)

    def test_resolver_backend_reads_pipenv_section(self):
        from pipenv.utils.settings import Settings

        settings = Settings(self._fake_project({"resolver_backend": "pure-python"}))
        assert settings.resolver_backend == "pure-python"

    def test_resolver_backend_absent_returns_none(self):
        from pipenv.utils.settings import Settings

        settings = Settings(self._fake_project({}))
        assert settings.resolver_backend is None

    def test_resolver_backend_whitespace_only_normalises_to_none(self):
        from pipenv.utils.settings import Settings

        settings = Settings(self._fake_project({"resolver_backend": "   "}))
        assert settings.resolver_backend is None

    def test_resolver_backend_strips_surrounding_whitespace(self):
        from pipenv.utils.settings import Settings

        settings = Settings(self._fake_project({"resolver_backend": "  pip  "}))
        assert settings.resolver_backend == "pip"


class TestBackendCLIFlag:
    """``--backend`` is a constrained alias the user-facing surface; it
    flows through ``state.resolver`` for back-compat with the T_F.5
    ``--resolver`` free-form flag.  The argparse ``choices=`` constraint
    validates the value at parse time, so a typo fails with a clean
    "invalid choice" error instead of falling through to the
    dispatcher's ``InternalError`` translation.
    """

    def _parse_lock_args(self, argv):
        from pipenv.cli.options import apply_env_vars, build_parser, build_state

        parser = build_parser()
        ns = parser.parse_args(["lock", *argv])
        apply_env_vars(ns)
        return ns

    def test_backend_flag_recognised_for_lock(self):
        """``pipenv lock --backend pure-python`` parses cleanly."""
        ns = self._parse_lock_args(["--backend", "pure-python"])
        assert ns.backend == "pure-python"

    def test_backend_flag_rejects_unknown_choice(self, capsys):
        """An unknown ``--backend`` value fails parsing with an
        actionable "invalid choice" error.  This is the T_PLUMBING
        promise that typos don't silently fall through to the
        dispatcher's KeyError path.
        """
        import pytest

        with pytest.raises(SystemExit):
            self._parse_lock_args(["--backend", "uv"])  # not in choices
        err_text = capsys.readouterr().err
        assert "invalid choice" in err_text or "argument" in err_text

    def test_backend_flag_default_is_none(self):
        """No flag → ``ns.backend is None``.  The downstream state /
        routine chain then falls through to the Pipfile / env-var /
        default chain — byte-identical to pre-T_PLUMBING behaviour.
        """
        ns = self._parse_lock_args([])
        assert ns.backend is None

    def test_backend_flag_populates_state_resolver(self):
        """``--backend NAME`` overrides ``--resolver NAME`` in
        ``build_state`` (T_PLUMBING precedence: the constrained flag
        wins over the free-form back-compat one).
        """
        from pipenv.cli.options import apply_env_vars, build_parser, build_state

        parser = build_parser()
        ns = parser.parse_args(["lock", "--backend", "pure-python"])
        apply_env_vars(ns)
        state = build_state(ns)
        assert state.resolver == "pure-python"

    def test_resolver_flag_alone_still_populates_state_resolver(self):
        """Back-compat: ``--resolver NAME`` (T_F.5) still works.
        ``--backend`` is the new spelling; ``--resolver`` is preserved.
        """
        from pipenv.cli.options import apply_env_vars, build_parser, build_state

        parser = build_parser()
        ns = parser.parse_args(["lock", "--resolver", "pip"])
        apply_env_vars(ns)
        state = build_state(ns)
        assert state.resolver == "pip"

    def test_backend_wins_over_resolver_when_both_set(self):
        """When both flags are supplied, ``--backend`` (constrained)
        wins over ``--resolver`` (free-form).  Documented user surface
        takes precedence over the back-compat alias.
        """
        from pipenv.cli.options import apply_env_vars, build_parser, build_state

        parser = build_parser()
        ns = parser.parse_args(
            ["lock", "--resolver", "pip", "--backend", "pure-python"]
        )
        apply_env_vars(ns)
        state = build_state(ns)
        assert state.resolver == "pure-python"

    def test_default_is_none(self):
        """Neither flag → ``state.resolver is None`` → wire shape stays
        empty → dispatcher falls through to default ``pip`` path.
        """
        from pipenv.cli.options import apply_env_vars, build_parser, build_state

        parser = build_parser()
        ns = parser.parse_args(["lock"])
        apply_env_vars(ns)
        state = build_state(ns)
        assert state.resolver is None


class TestVenvResolveDepsBackendPropagation:
    """The ``resolver_backend`` kwarg on ``venv_resolve_deps`` reaches the
    typed ``ResolverRequest.options.backend`` wire field via
    ``_build_resolver_request``.  This is the bridge from the routine
    layer down to the subprocess argv / typed-request envelope.
    """

    def _fake_project(self):
        """Build a stub ``project`` accepted by ``_build_resolver_request``.

        ``_build_resolver_request`` only touches ``project`` via the
        deadline helper :func:`_resolve_deadline_seconds`, which reads
        ``project.s.PIPENV_RESOLVER_TIMEOUT_S`` and
        ``project.settings.get("resolver_timeout")``.  A bare object
        with those attributes is enough for our use.
        """
        class _FakeSettings:
            def get(self, _key, default=None):
                return default

        class _S:
            PIPENV_RESOLVER_TIMEOUT_S = 0

        class _FakeProject:
            s = _S()
            settings = _FakeSettings()

        return _FakeProject()

    def test_build_resolver_request_stamps_backend(self):
        from pipenv.utils.resolver import _build_resolver_request

        request = _build_resolver_request(
            deps={"requests": "requests==2.31.0"},
            sources=[{"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}],
            category="default",
            pre=False,
            clear=False,
            allow_global=False,
            verbose=False,
            python_marker_override=None,
            extra_pip_args=[],
            resolved_default_deps=None,
            project=self._fake_project(),
            resolver_backend="pure-python",
        )
        assert request.options.backend == "pure-python"

    def test_build_resolver_request_defaults_backend_to_pip(self):
        """No ``resolver_backend`` kwarg + no env / Pipfile override →
        ``"pip"``.  Per commit ``0bf0c192``
        (``fix(resolver): stamp selected backend onto resolver requests``),
        the parent now resolves the full
        precedence chain (CLI/caller > env > Pipfile > default) and
        stamps the result onto the request before sending — so the
        subprocess no longer has to rediscover the project's Pipfile to
        make the same decision.  The default-fallback value is ``"pip"``.
        """
        from pipenv.utils.resolver import _build_resolver_request

        request = _build_resolver_request(
            deps={"requests": "requests==2.31.0"},
            sources=[{"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}],
            category="default",
            pre=False,
            clear=False,
            allow_global=False,
            verbose=False,
            python_marker_override=None,
            extra_pip_args=[],
            resolved_default_deps=None,
            project=self._fake_project(),
        )
        assert request.options.backend == "pip"
        # The wire dict carries the resolved backend.
        wire = request.to_json_dict()
        assert wire["options"].get("backend") == "pip"


class TestResolverSubprocessDispatch:
    """End-to-end: ``resolve_for_pipenv`` reads ``request.options.backend``
    and dispatches through ``get_backend(name).resolve(request)``.  This
    test confirms the dispatcher honours the parent-stamped selection
    without consulting env / Pipfile fallbacks.
    """

    def test_subprocess_dispatches_to_named_backend(self):
        from pipenv.resolver import core
        from pipenv.resolver.backends import base as backends_base

        captured = {"called": False, "request": None}

        class _SentinelBackend:
            name = "sentinel"

            def is_available(self) -> bool:
                return True

            def resolve(self, request):
                captured["called"] = True
                captured["request"] = request
                return ResolverResponse(
                    schema_version=SCHEMA_VERSION,
                    result=ResolverSuccess(kind="success", locked=()),
                )

        request = _build_request(options=ResolverOptions(backend="sentinel"))

        with mock.patch.dict(
            backends_base.REGISTRY, {"sentinel": _SentinelBackend()}
        ):
            response = core.resolve_for_pipenv(request)

        assert captured["called"] is True
        assert captured["request"] is request
        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, ResolverSuccess)

    def test_pure_python_backend_is_registered_and_dispatchable(self):
        """The actual ``pure-python`` registry entry is reachable via
        the dispatcher.  We don't run a real resolve (that's T15's
        integration job); we just confirm ``get_backend("pure-python")``
        returns an instance that ``resolve_for_pipenv`` would invoke.
        """
        from pipenv.resolver.backends import REGISTRY, get_backend
        from pipenv.resolver.backends.pure_python import PurePythonBackend

        assert "pure-python" in REGISTRY
        backend = get_backend("pure-python")
        assert isinstance(backend, PurePythonBackend)
        # And it self-reports its name as the dispatcher would expect.
        assert backend.name == "pure-python"
