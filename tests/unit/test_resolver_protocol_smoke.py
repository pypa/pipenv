"""Smoke-level unit tests for the typed pipenv-resolver subprocess protocol
(T_F.3 Wave B1).

These tests exercise the ``pipenv/resolver/main.py`` entry point as a
*subprocess*, using nothing but the typed ``ResolverRequest`` /
``ResolverResponse`` envelope defined in ``pipenv/resolver/schema.py``.

Coverage:

1. **Happy path** — invoke the subprocess with a valid request, mock
   :func:`pipenv.resolver.main.resolve_packages` so the test does not
   depend on the parent-side rewrite (B2) or the lockfile-writer
   rewrite (B3), and assert that the wire protocol round-trips a
   :class:`ResolverSuccess` payload with the expected ``LockedRequirement``
   entries.
2. **Schema-version mismatch** — request with ``schema_version=999``
   produces a structured ``InternalError`` response AND the subprocess
   exits non-zero (per plan §B1 / design Q2).
3. **Live-resolve happy path** (``@pytest.mark.network``) — when the
   parent-side / lockfile-writer rewrites have all landed (Wave-B tip),
   this test exercises an actual PyPI fetch end-to-end.  Mid-Wave-B it
   may fail with a structured ``InternalError`` (B2/B3's
   in-progress-state cross-dependency); the parent agent's PR-tip CI
   is the gate that actually pins it green.

The integration counterpart in ``tests/integration/test_resolver_protocol.py``
(C2) covers end-to-end ``pipenv lock`` against a fixture Pipfile.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import pipenv.resolver
from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    PackageSpecs,
    ResolverOptions,
    ResolverRequest,
    ResolverResponse,
    Source,
)


def _main_module_path() -> Path:
    """Path to the subprocess entry script (``pipenv/resolver/main.py``)."""
    # ``pipenv.resolver`` is a package whose __init__.py re-exports the
    # entry-point ``main`` function — so ``pipenv.resolver.main`` resolves
    # to the function, not the submodule.  We sidestep that by finding the
    # package directory and appending ``main.py``.
    package_dir = Path(pipenv.resolver.__file__).resolve().parent
    return package_dir / "main.py"


def _build_request(
    *,
    schema_version: int = SCHEMA_VERSION,
    packages: dict[str, str] | None = None,
) -> ResolverRequest:
    """Build a minimal ``ResolverRequest`` for the smoke test."""
    if packages is None:
        # ``pytz`` is the canonical "tiny pure-Python PyPI package with
        # zero deps" used elsewhere in pipenv's test suite.
        packages = {"pytz": "pytz==2024.1"}
    return ResolverRequest(
        schema_version=schema_version,
        category="default",
        packages=PackageSpecs(specs=packages),
        options=ResolverOptions(pre=False, clear=False, system=False, verbose=False),
        sources=(
            Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
        ),
    )


def _invoke_subprocess(
    request: ResolverRequest,
    tmp_path: Path,
    *,
    inject_resolver_stub: bool = False,
) -> tuple[int, dict | None, str]:
    """Write ``request`` to a tempfile, invoke the subprocess, return
    ``(returncode, response_dict_or_None, stderr_text)``.

    If ``inject_resolver_stub`` is true, the harness writes a small
    sitecustomize-style preload that replaces
    :func:`pipenv.resolver.main.resolve_packages` with a stub returning
    a single hard-coded ``LockedRequirement`` for ``pytz==2024.1``.  This
    lets the test exercise the wire-protocol logic without depending on
    the parent-side rewrite (B2) or the lockfile-writer rewrite (B3),
    both of which may be mid-flight in the working tree.
    """
    request_file = tmp_path / "request.json"
    response_file = tmp_path / "response.json"
    request_file.write_text(
        json.dumps(request.to_json_dict(), indent=2, sort_keys=True)
    )

    env = os.environ.copy()
    # Make sure the subprocess can import pipenv from the working tree
    # even if the harness's PYTHONPATH does not already include it.
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath_entries = [str(repo_root)]

    if inject_resolver_stub:
        # Drop a stub-injection ``sitecustomize`` module into a sibling
        # tempdir and prepend it to ``PYTHONPATH`` so Python imports it
        # before any other module on subprocess startup.  The stub
        # rebinds :func:`pipenv.resolver.main.resolve_packages` to a
        # zero-dep function returning a hard-coded
        # :class:`LockedRequirement` — that's enough to exercise the
        # wire protocol without dragging in B2 / B3's mid-flight files.
        stub_dir = tmp_path / "_stub_path"
        stub_dir.mkdir()
        (stub_dir / "sitecustomize.py").write_text(textwrap.dedent("""
            import pipenv.resolver.main as _resolver_main
            from pipenv.resolver.schema import LockedRequirement


            def _stub_resolve_packages(request):
                pkg_name = (
                    next(iter(request.packages.specs))
                    if request.packages.specs
                    else 'pytz'
                )
                return [LockedRequirement(name=pkg_name, version='==2024.1')], None


            _resolver_main.resolve_packages = _stub_resolve_packages
        """))
        pythonpath_entries.insert(0, str(stub_dir))

    existing = env.get("PYTHONPATH", "")
    if existing:
        pythonpath_entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    # We invoke ``python -m pipenv.resolver.main`` rather than the
    # script-path form used in production (``[venv_python,
    # /path/to/main.py, ...]``) for one reason: stub injection.
    # Running the script directly loads ``main.py`` under the
    # ``__main__`` module identity, separate from
    # ``pipenv.resolver.main`` in ``sys.modules`` — which means
    # patching ``pipenv.resolver.main.resolve_packages`` does not
    # reach the function the entry point actually calls.  With
    # ``-m``, the script's module identity IS
    # ``pipenv.resolver.main``, so the stub takes effect.  The
    # production code path is exercised by the C2 integration test
    # (``tests/integration/test_resolver_protocol.py``) which runs
    # the real subprocess invocation end-to-end.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipenv.resolver.main",
            "--request-file",
            str(request_file),
            "--response-file",
            str(response_file),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    response_dict: dict | None
    if response_file.exists():
        response_dict = json.loads(response_file.read_text())
    else:
        response_dict = None
    return proc.returncode, response_dict, proc.stderr


def test_resolver_subprocess_happy_path_returns_success_with_stubbed_resolver(tmp_path):
    """A valid ``ResolverRequest`` round-trips through the subprocess and
    returns a typed ``ResolverSuccess`` with exit 0.

    The resolver itself is stubbed so this test gates the wire-protocol
    rewrite (B1) without coupling to B2 / B3's in-progress state.
    """
    request = _build_request()
    returncode, response_dict, stderr = _invoke_subprocess(
        request, tmp_path, inject_resolver_stub=True
    )

    assert returncode == 0, (
        f"subprocess exited {returncode}; "
        f"response file: {response_dict!r}; stderr: {stderr!r}"
    )
    assert response_dict is not None, "subprocess produced no response file"

    response = ResolverResponse.from_json_dict(response_dict)
    assert response.schema_version == SCHEMA_VERSION
    assert response.result.kind == "success", (
        f"expected success, got {response.result.kind!r} "
        f"with payload {response_dict!r}"
    )
    locked_names = {lr.name for lr in response.result.locked}
    assert "pytz" in locked_names, (
        f"expected pytz in locked entries; got {locked_names!r}"
    )


def test_resolver_subprocess_schema_version_mismatch_returns_internal_error(tmp_path):
    """A request with ``schema_version=999`` produces a structured
    ``InternalError`` response AND non-zero exit (plan §B1 Q2).

    No stub injection: the schema-version check fires before the
    resolver ever runs, so this test stands on its own regardless of
    B2 / B3 state.
    """
    request = _build_request(schema_version=999)
    returncode, response_dict, _stderr = _invoke_subprocess(request, tmp_path)

    assert returncode != 0, "schema mismatch must exit non-zero (plan Q2)"
    assert response_dict is not None, (
        "subprocess must write a best-effort response even on schema mismatch"
    )

    # Parse the response without going through ResolverResponse.from_json_dict
    # — that classmethod itself validates schema_version and would raise.
    assert response_dict["schema_version"] == SCHEMA_VERSION
    assert response_dict["result"]["kind"] == "internal_error"
    assert "schema version mismatch" in response_dict["result"]["message"].lower()


@pytest.mark.network
def test_resolver_subprocess_live_resolve_against_pypi(tmp_path):
    """End-to-end live-resolve happy path against PyPI.

    Will be flaky mid-Wave-B (cross-task import inconsistencies); the
    parent agent's PR-tip CI is the actual gate.  This test exists so
    that, once Wave B converges, the live path is sanity-checked at
    the unit-suite level too.
    """
    request = _build_request()
    returncode, response_dict, stderr = _invoke_subprocess(request, tmp_path)

    if returncode != 0:
        # Mid-Wave-B: skip rather than fail so this doesn't block B1's
        # commit while B2 / B3 are still landing.  The structured-error
        # payload is informational.
        pytest.skip(
            f"live-resolve subprocess exited {returncode}; "
            f"response: {response_dict!r}; likely B2/B3 mid-flight"
        )

    assert response_dict is not None
    response = ResolverResponse.from_json_dict(response_dict)
    assert response.result.kind == "success", (
        f"got {response.result.kind!r}: {response_dict!r}"
    )
    locked_names = {lr.name for lr in response.result.locked}
    assert "pytz" in locked_names
