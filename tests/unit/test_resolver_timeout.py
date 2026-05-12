"""Tests for T_F.6: wall-clock timeout enforcement on the resolver.

The timeout flows like this:

    Pipfile [pipenv] resolver_timeout_seconds  (highest precedence)
        |
    env var PIPENV_RESOLVER_TIMEOUT_S
        |
    default 1800 seconds                       (lowest precedence)
        |
    -> request.metadata.deadline_seconds       (carried on the wire)
        |
    -> subprocess.Popen.wait(timeout=...)      (parent kills child)

These tests pin the three observable contracts:

1. ``subprocess.TimeoutExpired`` from the child wait converts to a
   structured ``ResolutionFailure`` whose message names the override.
2. ``_build_resolver_request`` reads the deadline with the documented
   precedence and writes it into ``RequestMetadata.deadline_seconds``.
3. ``resolve()`` honours the deadline carried on the request even when
   the project setting disagrees.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal doubles re-used across the cases below
# ---------------------------------------------------------------------------


class _ClosedStream:
    """A stream that signals EOF immediately so the reader threads inside
    :func:`pipenv.utils.resolver.resolve` exit without blocking the test.
    """

    def read(self, _n):
        return ""

    def readline(self):
        return ""


class _HangingPopen:
    """A subprocess.Popen stand-in whose first ``wait`` always times out."""

    def __init__(self):
        self.args = ["python", "-m", "pipenv.resolver"]
        self.killed = False
        self.stdout = _ClosedStream()
        self.stderr = _ClosedStream()
        self.wait_timeout = None

    def wait(self, timeout=None):
        # Record the timeout the parent passed so the test can assert on it.
        if self.wait_timeout is None:
            self.wait_timeout = timeout
        if not self.killed:
            raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout)
        return -9

    def kill(self):
        self.killed = True

    def poll(self):
        return None if not self.killed else -9


def _make_project(*, timeout_setting=600, pipfile_timeout=None):
    """Build a Project double exposing only the attributes our code touches."""
    project = mock.MagicMock()
    project.s.is_verbose.return_value = False
    project.s.PIPENV_RESOLVER_TIMEOUT_S = timeout_setting
    # ``project.settings`` is a dict-like in real pipenv (the parsed
    # ``[pipenv]`` Pipfile section).  Honour ``.get``.
    settings = {}
    if pipfile_timeout is not None:
        settings["resolver_timeout_seconds"] = pipfile_timeout
    project.settings = settings
    return project


# ---------------------------------------------------------------------------
# 1. subprocess.TimeoutExpired -> ResolutionFailure
# ---------------------------------------------------------------------------


@pytest.mark.utils
def test_subprocess_timeout_raises_resolution_failure(monkeypatch):
    """A hung resolver subprocess must be killed and a clear timeout
    error raised that tells the user how to extend the limit.
    """
    from pipenv.exceptions import ResolutionFailure
    from pipenv.utils import resolver as resolver_mod

    popen = _HangingPopen()
    monkeypatch.setattr(resolver_mod, "subprocess_run", lambda *a, **kw: popen)

    st = SimpleNamespace(console=mock.MagicMock())
    project = _make_project(timeout_setting=1)

    with pytest.raises(ResolutionFailure) as exc_info:
        resolver_mod.resolve(
            ["python", "-m", "pipenv.resolver"],
            st,
            project,
            deadline_seconds=1,
        )

    assert popen.killed, "Resolver should kill the hung subprocess on timeout"
    msg = str(exc_info.value)
    # User-facing message must name the override so a user with a
    # legitimate long resolve knows how to extend it.
    assert "timed out" in msg.lower()
    assert "PIPENV_RESOLVER_TIMEOUT_S" in msg


# ---------------------------------------------------------------------------
# 2. Default deadline is used when no override is set
# ---------------------------------------------------------------------------


@pytest.mark.utils
def test_default_deadline_from_setting(monkeypatch):
    """When no Pipfile setting is given, ``_resolve_deadline_seconds`` falls
    back to the env-var-backed ``Setting.PIPENV_RESOLVER_TIMEOUT_S`` value.
    """
    from pipenv.utils.resolver import _resolve_deadline_seconds

    project = _make_project(timeout_setting=1800, pipfile_timeout=None)
    assert _resolve_deadline_seconds(project) == 1800


# ---------------------------------------------------------------------------
# 3. Pipfile setting wins over the env-var-backed default
# ---------------------------------------------------------------------------


@pytest.mark.utils
def test_pipfile_setting_overrides_env(monkeypatch):
    """``[pipenv] resolver_timeout_seconds`` in the Pipfile beats the
    env-var-backed default — precedence is Pipfile > env > default.
    """
    from pipenv.utils.resolver import _resolve_deadline_seconds

    project = _make_project(timeout_setting=600, pipfile_timeout=42)
    assert _resolve_deadline_seconds(project) == 42


@pytest.mark.utils
def test_pipfile_setting_invalid_falls_back(monkeypatch):
    """A garbage ``resolver_timeout_seconds`` value in the Pipfile must
    not crash — fall back to the env-var-backed setting.
    """
    from pipenv.utils.resolver import _resolve_deadline_seconds

    project = _make_project(timeout_setting=600, pipfile_timeout="not-an-int")
    assert _resolve_deadline_seconds(project) == 600

    project = _make_project(timeout_setting=600, pipfile_timeout=0)
    assert _resolve_deadline_seconds(project) == 600


# ---------------------------------------------------------------------------
# 4. The deadline flows into RequestMetadata.deadline_seconds
# ---------------------------------------------------------------------------


@pytest.mark.utils
def test_build_resolver_request_records_deadline(monkeypatch):
    """``_build_resolver_request`` must stamp the resolved deadline onto
    ``RequestMetadata.deadline_seconds`` so the schema records the
    configured timeout for diagnostics and subprocess-side awareness.
    """
    from pipenv.utils.resolver import _build_resolver_request

    project = _make_project(timeout_setting=900, pipfile_timeout=None)
    project.sources.pipfile_sources.return_value = []

    request = _build_resolver_request(
        deps={},
        sources=[],
        category="default",
        pre=False,
        clear=False,
        allow_global=False,
        verbose=False,
        python_marker_override=None,
        extra_pip_args=[],
        resolved_default_deps=None,
        project=project,
    )

    assert request.metadata.deadline_seconds == 900.0


# ---------------------------------------------------------------------------
# 5. resolve() honours the request-carried deadline
# ---------------------------------------------------------------------------


@pytest.mark.utils
@pytest.mark.skipif(
    not hasattr(__import__("signal"), "SIGALRM"),
    reason="In-process wall-clock guard uses SIGALRM (Unix only).",
)
def test_in_process_deadline_returns_internal_error(monkeypatch):
    """In-process resolve (``PIPENV_RESOLVER_PARENT_PYTHON=1`` debug
    branch) honours ``request.metadata.deadline_seconds`` via SIGALRM.
    A resolve that overruns the deadline returns an ``InternalError``
    variant whose message names the wall-clock deadline.
    """
    import time

    from pipenv.resolver import core
    from pipenv.resolver.schema import (
        SCHEMA_VERSION,
        InternalError,
        PackageSpecs,
        RequestMetadata,
        ResolverOptions,
        ResolverRequest,
    )

    def _hung_resolve_packages(_request):
        # Sleep long enough to overrun the 0.2s deadline.
        time.sleep(5)
        return [], None

    monkeypatch.setattr(core, "resolve_packages", _hung_resolve_packages)

    request = ResolverRequest(
        schema_version=SCHEMA_VERSION,
        category="default",
        packages=PackageSpecs(specs={}),
        options=ResolverOptions(),
        sources=(),
        metadata=RequestMetadata(deadline_seconds=0.2),
    )

    response = core.resolve_for_pipenv(request)
    assert isinstance(response.result, InternalError)
    assert "wall-clock deadline elapsed" in response.result.message


@pytest.mark.utils
def test_resolve_uses_request_deadline_when_provided(monkeypatch):
    """When ``resolve()`` is given an explicit ``deadline_seconds``, it
    passes that to ``subprocess.wait`` rather than reading the project
    setting — so the request's metadata is the source of truth.
    """
    from pipenv.exceptions import ResolutionFailure
    from pipenv.utils import resolver as resolver_mod

    popen = _HangingPopen()
    monkeypatch.setattr(resolver_mod, "subprocess_run", lambda *a, **kw: popen)

    st = SimpleNamespace(console=mock.MagicMock())
    # Project setting says 9999, but resolve() should use 7 (from request).
    project = _make_project(timeout_setting=9999)

    with pytest.raises(ResolutionFailure):
        resolver_mod.resolve(
            ["python", "-m", "pipenv.resolver"],
            st,
            project,
            deadline_seconds=7,
        )

    assert popen.wait_timeout == 7, (
        f"resolve() should honour the request-carried deadline (7s); "
        f"saw wait(timeout={popen.wait_timeout!r})"
    )
