"""Unit tests for the typed parent-side dispatch in
``pipenv/utils/resolver.py`` introduced by T_F.3 Wave B2.

These tests cover the *file-format contract* and the *response dispatch*
machinery in isolation — they do NOT spawn a real subprocess.  Real
end-to-end coverage of ``pipenv lock`` lives in the integration suite
(Wave C2 protocol golden test).

The parent-side machine under test is:

1. Build a :class:`pipenv.resolver.schema.ResolverRequest` from the parent
   inputs (deps dict, sources list, options, etc.).
2. Write it to a ``--request-file`` tempfile.
3. Invoke ``pipenv-resolver`` with ONLY ``--request-file`` and
   ``--response-file`` argv (no ``--pre``, ``--clear``, etc.).
4. Read the ``--response-file`` after the child exits; dispatch on
   ``response.result.kind``:

       * ``success`` → return ``Sequence[LockedRequirement]``
       * ``resolution_error`` → raise :class:`pipenv.exceptions.ResolutionFailure`
         with the structured detail attached
       * ``internal_error`` → raise ``RuntimeError`` (same path as today's
         non-zero-exit handling)

5. Non-zero exit without a response file → fall back to stderr text
   (this is a true subprocess crash; the structured response was never
   written).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from pipenv.exceptions import ResolutionFailure
from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    LockedRequirement,
    PackageSpecs,
    ResolverOptions,
    ResolverRequest,
    Source,
)
from pipenv.utils import resolver as resolver_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_project(tmp_path: Path):
    """Minimal project double that exposes the attributes the parent-side
    dispatch helper touches."""
    project = mock.MagicMock()
    project.pipfile.project_directory = str(tmp_path)
    project.s.is_verbose.return_value = False
    project.s.PIPENV_RESOLVER_TIMEOUT_S = 60
    project.s.PIPENV_SPINNER = "dots"
    project.s.PIPENV_RESOLVER_PARENT_PYTHON = False
    project.s.PIPENV_KEYRING_PROVIDER = None
    project.pipfile.exists = True
    project.pipfile.parsed = {"requires": {}}
    project.sources.pipfile_sources.return_value = [
        {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
    ]
    project.settings = {}
    return project


def _success_response_dict():
    """Return a JSON-shaped success ``ResolverResponse`` dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "result": {
            "kind": "success",
            "locked": [
                {"name": "requests", "version": "==2.31.0"},
            ],
        },
    }


def _resolution_error_response_dict():
    return {
        "schema_version": SCHEMA_VERSION,
        "result": {
            "kind": "resolution_error",
            "conflicts": [
                {"package": "foo", "version": "1.0", "requires": "bar>=2"},
                {"package": "baz", "version": "0.1", "requires": "bar<1"},
            ],
            "pip_message": "ResolutionImpossible: foo+baz",
        },
    }


def _internal_error_response_dict():
    return {
        "schema_version": SCHEMA_VERSION,
        "result": {
            "kind": "internal_error",
            "message": "AttributeError: pip exploded",
            "traceback": "Traceback (most recent call last):\n  ...\n",
        },
    }


# ---------------------------------------------------------------------------
# Request building (parent → wire)
# ---------------------------------------------------------------------------


class TestBuildResolverRequest:
    """The parent serializes its inputs as a typed ``ResolverRequest``."""

    def test_minimal_request_envelope_fields(self, tmp_path):
        """The minimum-viable request has schema_version, category,
        packages, options, and at least one source — and the JSON
        round-trips through :func:`ResolverRequest.from_json_dict`.
        """
        request = resolver_mod._build_resolver_request(
            deps={"requests": "requests==2.31.0"},
            sources=[
                {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
            ],
            category="default",
            pre=False,
            clear=False,
            allow_global=False,
            verbose=False,
            python_marker_override=None,
            extra_pip_args=[],
            resolved_default_deps=None,
            project=_stub_project(tmp_path),
        )
        assert request.schema_version == SCHEMA_VERSION
        assert request.category == "default"
        assert request.packages.specs == {"requests": "requests==2.31.0"}
        assert request.options.pre is False
        assert request.options.clear is False
        assert request.options.system is False
        assert request.options.verbose is False
        assert len(request.sources) == 1
        assert request.sources[0].name == "pypi"
        # Round-trip through JSON.
        round_tripped = ResolverRequest.from_json_dict(
            request.to_json_dict()
        )
        assert round_tripped.packages.specs == request.packages.specs

    def test_request_carries_python_marker_override(self, tmp_path):
        """The Pipfile-derived ``python_full_version`` flows into the
        typed field, NOT into ``os.environ["PIPENV_RESOLVER_PYTHON_VERSION"]``.
        """
        request = resolver_mod._build_resolver_request(
            deps={"requests": "requests==2.31.0"},
            sources=[
                {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
            ],
            category="default",
            pre=False,
            clear=False,
            allow_global=False,
            verbose=False,
            python_marker_override="3.11.0",
            extra_pip_args=["--no-binary", ":all:"],
            resolved_default_deps=None,
            project=_stub_project(tmp_path),
        )
        assert request.python_marker_override == "3.11.0"
        assert list(request.extra_pip_args) == ["--no-binary", ":all:"]

    def test_request_carries_resolved_default_deps(self, tmp_path):
        """When the caller passes ``resolved_default_deps`` (gh-4665),
        they ride along inside the typed envelope, NOT in a separate
        tempfile via ``--resolved-default-deps-file``.
        """
        resolved = {
            "requests": {"name": "requests", "version": "==2.31.0"},
        }
        request = resolver_mod._build_resolver_request(
            deps={"black": "black"},
            sources=[
                {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
            ],
            category="dev",
            pre=False,
            clear=False,
            allow_global=False,
            verbose=False,
            python_marker_override=None,
            extra_pip_args=[],
            resolved_default_deps=resolved,
            project=_stub_project(tmp_path),
        )
        assert request.resolved_default_deps is not None
        names = {e.name for e in request.resolved_default_deps.entries}
        assert "requests" in names


# ---------------------------------------------------------------------------
# Subprocess invocation argv shape
# ---------------------------------------------------------------------------


class TestSubprocessInvocationArgv:
    """The subprocess is invoked with ONLY ``--request-file`` and
    ``--response-file`` — no ``--pre``, ``--clear``, ``--category``,
    ``--constraints-file``, etc.
    """

    def test_only_request_and_response_file_argv(self, tmp_path, monkeypatch):
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"requests": "requests==2.31.0"}),
            options=ResolverOptions(),
            sources=(
                Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
            ),
        )

        captured = {}

        def fake_resolve(cmd, st, project, **_kwargs):
            captured["cmd"] = list(cmd)
            # The response file path is the *last* argv element by our
            # convention.  Write a success response so the dispatcher
            # treats this as a clean run.
            response_path = cmd[-1]
            Path(response_path).write_text(json.dumps(_success_response_dict()))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(resolver_mod, "resolve", fake_resolve)

        project = _stub_project(tmp_path)
        st = SimpleNamespace(console=mock.MagicMock())

        locked = resolver_mod._run_resolver_subprocess(
            request=request,
            python_executable="/usr/bin/python3",
            project=project,
            st=st,
        )
        assert isinstance(locked, tuple) or isinstance(locked, list)
        assert len(locked) == 1
        assert locked[0].name == "requests"

        cmd = captured["cmd"]
        # Forbidden legacy argv flags.
        for forbidden in (
            "--pre",
            "--clear",
            "--system",
            "--verbose",
            "--category",
            "--constraints-file",
            "--resolved-default-deps-file",
            "--parse-only",
            "--pipenv-site",
            "--write",
        ):
            assert forbidden not in cmd, f"argv must not carry legacy flag {forbidden!r}"
        # Required new argv flags.
        assert "--request-file" in cmd
        assert "--response-file" in cmd


# ---------------------------------------------------------------------------
# Response dispatch (wire → parent)
# ---------------------------------------------------------------------------


class TestResponseDispatch:
    """The parent dispatches on ``response.result.kind`` and translates
    each variant to the appropriate parent-side outcome.
    """

    def test_success_returns_locked_requirements(self, tmp_path, monkeypatch):
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"requests": "requests==2.31.0"}),
            options=ResolverOptions(),
            sources=(
                Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
            ),
        )

        def fake_resolve(cmd, st, project, **_kwargs):
            response_path = cmd[-1]
            Path(response_path).write_text(json.dumps(_success_response_dict()))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(resolver_mod, "resolve", fake_resolve)

        project = _stub_project(tmp_path)
        st = SimpleNamespace(console=mock.MagicMock())
        locked = resolver_mod._run_resolver_subprocess(
            request=request,
            python_executable="/usr/bin/python3",
            project=project,
            st=st,
        )
        assert all(isinstance(lr, LockedRequirement) for lr in locked)
        assert [lr.name for lr in locked] == ["requests"]

    def test_resolution_error_raises_resolution_failure(self, tmp_path, monkeypatch):
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"foo": "foo"}),
            options=ResolverOptions(),
            sources=(
                Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
            ),
        )

        def fake_resolve(cmd, st, project, **_kwargs):
            response_path = cmd[-1]
            Path(response_path).write_text(
                json.dumps(_resolution_error_response_dict())
            )
            # Resolution failures still exit 0 — the structured payload
            # carries the failure detail, non-zero exit is reserved for
            # genuine subprocess crashes.
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(resolver_mod, "resolve", fake_resolve)

        project = _stub_project(tmp_path)
        st = SimpleNamespace(console=mock.MagicMock())
        with pytest.raises(ResolutionFailure) as exc_info:
            resolver_mod._run_resolver_subprocess(
                request=request,
                python_executable="/usr/bin/python3",
                project=project,
                st=st,
            )
        # The pip_message must show up in the user-facing text.
        assert "ResolutionImpossible" in str(exc_info.value)
        # Structured detail attached for downstream code to surface.
        conflicts = getattr(exc_info.value, "conflicts", None)
        assert conflicts is not None
        assert len(conflicts) == 2

    def test_internal_error_raises_runtime_error(self, tmp_path, monkeypatch):
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"foo": "foo"}),
            options=ResolverOptions(),
            sources=(
                Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
            ),
        )

        def fake_resolve(cmd, st, project, **_kwargs):
            response_path = cmd[-1]
            Path(response_path).write_text(
                json.dumps(_internal_error_response_dict())
            )
            # Internal-error variant also typically corresponds to a
            # non-zero exit, but the structured payload was successfully
            # written before exit so the parent dispatches on its kind.
            return subprocess.CompletedProcess(cmd, 1, "", "AttributeError\n")

        monkeypatch.setattr(resolver_mod, "resolve", fake_resolve)

        project = _stub_project(tmp_path)
        st = SimpleNamespace(console=mock.MagicMock())
        with pytest.raises(RuntimeError) as exc_info:
            resolver_mod._run_resolver_subprocess(
                request=request,
                python_executable="/usr/bin/python3",
                project=project,
                st=st,
            )
        assert "pip exploded" in str(exc_info.value)

    def test_nonzero_exit_without_response_file_falls_back(
        self, tmp_path, monkeypatch
    ):
        """True subprocess crash: the child died before it could write
        a structured response.  Fallback path raises ``RuntimeError`` from
        the existing free-text stderr handler — NOT a structured dispatch.
        """
        request = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"foo": "foo"}),
            options=ResolverOptions(),
            sources=(
                Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
            ),
        )

        def fake_resolve(cmd, st, project, **_kwargs):
            # Note: do NOT write the response file.  The dispatcher must
            # detect this missing-file case.
            return subprocess.CompletedProcess(
                cmd, 1, "stdout text", "SegmentationFault\n"
            )

        monkeypatch.setattr(resolver_mod, "resolve", fake_resolve)

        project = _stub_project(tmp_path)
        st = SimpleNamespace(console=mock.MagicMock())
        with pytest.raises(RuntimeError):
            resolver_mod._run_resolver_subprocess(
                request=request,
                python_executable="/usr/bin/python3",
                project=project,
                st=st,
            )
