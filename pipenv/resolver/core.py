"""Unified resolver entry point (T_F.4).

T_F.3 left the resolver with TWO call sites for the underlying
``resolve_packages`` driver:

1. ``pipenv/resolver/main.py:_main`` — the subprocess entry, reads the
   request JSON and writes the response JSON.
2. ``pipenv/utils/resolver.py`` ``venv_resolve_deps`` debug bypass
   (``PIPENV_RESOLVER_PARENT_PYTHON=1``) — runs the driver in the parent
   interpreter and skips the JSON round-trip.

T_F.4 folds the resolve plumbing onto ONE function,
:func:`resolve_for_pipenv`, that takes a typed
:class:`pipenv.resolver.schema.ResolverRequest` and ALWAYS returns a
typed :class:`pipenv.resolver.schema.ResolverResponse` — never raises.
Both adapters then become thin wrappers:

* **Subprocess adapter** (``pipenv/resolver/main.py``) reads the request
  file, calls :func:`resolve_for_pipenv`, writes the response file, and
  picks an exit code based on ``response.result.kind``.
* **In-process adapter** (``pipenv/utils/resolver.py``) builds the
  request from parent-local state, calls :func:`resolve_for_pipenv`,
  and dispatches on ``response.result.kind`` to either return the
  locked entries or raise.

The acceptance criterion from the PRD — "one resolver implementation,
two thin adapters" — is satisfied here.

Design references:

* ``docs/dev/initiative-f-typed-design.md`` §4 step 6 (deferral of this
  fold to T_F.4).
* ``docs/dev/initiative-f-typed-design.md`` §6a (target-Python
  constraints; this module imports patched-pip lazily for the same
  reason :mod:`pipenv.resolver.schema` does).
* ``docs/dev/initiative-f-protocol.md`` §7 (the in-process branch).

Future-task hooks (intentionally reserved-but-unused):

* ``request.metadata.deadline_seconds`` — T_F.6 will wire this to a
  wall-clock-timeout guard around the resolve call.  The slot is
  already on the schema; this function reads ``request.metadata`` but
  does not enforce the timeout yet.
* ``Diagnostics.resolver_log`` — T_F.7 will populate this with a
  structured log of resolution events.  This function currently builds
  an empty :class:`Diagnostics` and attaches it to the response;
  callers see the field today but it's always the default empty
  sequence.
"""
from __future__ import annotations

import logging
import os
import traceback
from contextlib import contextmanager
from typing import Iterator

from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    Diagnostics,
    InternalError,
    LockedRequirement,
    ResolutionError,
    ResolverRequest,
    ResolverResponse,
    ResolverSuccess,
)

# Re-exported so existing callers / tests that monkey-patch
# ``pipenv.resolver.main.resolve_packages`` continue to work.  The
# function still lives in ``pipenv.resolver.main``; we import it lazily
# inside :func:`resolve_for_pipenv` to avoid a top-level circular
# import (``main`` imports schema; this module is imported by ``main``
# in turn for the typed adapter wrapper).
#
# The module-level name ``resolve_packages`` is bound on first call so
# that ``mock.patch.object(core, "resolve_packages", ...)`` is a viable
# test pattern (see ``tests/unit/test_resolver_core.py``).
resolve_packages = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Marker-environment override (formerly duplicated between the
# subprocess entry's ``_apply_python_marker_override`` and the
# parent-side ``_patched_marker_environment``).  We use a context
# manager so the parent interpreter's ``default_environment`` is
# restored on the way out — important for the in-process adapter,
# which runs in the same Python that pipenv itself is using.
# ---------------------------------------------------------------------------


@contextmanager
def _patched_marker_environment(python_marker_override: str | None) -> Iterator[None]:
    """Monkey-patch ``default_environment`` in pip's vendored packaging
    so marker evaluation uses the project's target Python rather than
    the running interpreter.

    Pre-T_F.3 the override travelled via an environment variable; T_F.3
    moved it to a typed field on the request; T_F.4 turns it into a
    context manager so both adapters use the same restore-on-exit
    semantics (critical for the in-process branch — see
    https://github.com/pypa/pipenv/issues/5908).
    """
    if not python_marker_override:
        yield
        return

    parts = python_marker_override.split(".")
    python_version = ".".join(parts[:2])
    python_full_version = python_marker_override

    # Lazy import: this module must stay importable on target Pythons
    # that don't have pipenv's patched-pip on ``sys.path`` (see
    # ``docs/dev/initiative-f-typed-design.md`` §3.6 / §6a).  In the
    # subprocess entry path the bootstrapper guarantees the import is
    # available before we get here; in the in-process branch the
    # parent always has it.
    import pipenv.patched.pip._vendor.packaging.markers as pip_markers

    _orig = pip_markers.default_environment

    def _patched() -> dict:
        env = _orig()
        env["python_version"] = python_version
        env["python_full_version"] = python_full_version
        return env

    pip_markers.default_environment = _patched
    try:
        yield
    finally:
        pip_markers.default_environment = _orig


# ---------------------------------------------------------------------------
# The fold target itself.
# ---------------------------------------------------------------------------


def _apply_request_env(request: ResolverRequest) -> None:
    """Apply the env-var side effects that historically the subprocess
    entry would apply to its own process.

    These were originally inside ``_main`` in :mod:`pipenv.resolver.main`:

    * ``PIP_DISABLE_PIP_VERSION_CHECK`` / ``PYTHONIOENCODING`` /
      ``PYTHONUNBUFFERED`` are pipenv-resolver-process defaults.
    * ``PIPENV_VERBOSITY`` / ``PIP_RESOLVER_DEBUG`` mirror the
      ``--verbose`` option.

    The in-process branch DOES NOT want these — they leak into the
    parent pipenv process and persist across invocations.  Both
    adapters now gate the env-var work explicitly:

    * Subprocess: calls this helper directly before invoking
      :func:`resolve_for_pipenv` (its env IS the subprocess's env).
    * In-process: skips this helper; the parent's env was already
      configured by the user's shell.
    """
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUNBUFFERED"] = "1"
    if request.options.verbose:
        os.environ["PIPENV_VERBOSITY"] = "1"
        os.environ["PIP_RESOLVER_DEBUG"] = "1"
    else:
        logging.getLogger("pipenv").setLevel(logging.WARN)


def _dispatch_resolve_packages(request: ResolverRequest):
    """Look up ``resolve_packages`` via ``sys.modules`` rather than a
    direct reference.

    The function actually lives in :mod:`pipenv.resolver.main`, but
    test/stub injection happens at several different name-binding
    sites and we need each of them to "win" if it's been patched:

    * ``mock.patch.object(core, "resolve_packages", ...)`` rebinds
      the attribute on THIS module (the pattern used by
      ``tests/unit/test_resolver_core.py``).
    * ``mock.patch("pipenv.resolver.resolve_packages", ...)`` rebinds
      the re-export in :mod:`pipenv.resolver` (the pattern used by
      ``tests/unit/test_locking_no_mutation.py``).
    * ``pipenv.resolver.main.resolve_packages = stub`` rebinds on
      the canonical module (the pattern used by
      ``tests/unit/test_resolver_protocol_smoke.py``'s
      sitecustomize stub).
    * When the subprocess is launched by script path (``[python,
      /path/to/main.py, ...]``), Python loads ``main.py`` under
      ``__main__`` rather than under ``pipenv.resolver.main`` in
      ``sys.modules``; the ``pipenv.resolver`` re-export is then
      the only canonical reference.

    Preference order: local module → ``pipenv.resolver`` (re-export)
    → ``pipenv.resolver.main`` → direct import.  The first callable
    found wins.
    """
    import sys

    for module_name in (__name__, "pipenv.resolver", "pipenv.resolver.main"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        fn = getattr(module, "resolve_packages", None)
        # Skip the module-local sentinel ``None`` and our own
        # re-exported function (avoid infinite re-dispatch through
        # the re-exported alias in ``pipenv.resolver.core``).
        if callable(fn) and fn is not _dispatch_resolve_packages:
            return fn(request)

    # Last-ditch: import and call directly.  This path is reached only
    # if none of the modules above have a callable bound — unlikely in
    # practice but defensible.
    from pipenv.resolver.main import resolve_packages as _fn

    return _fn(request)


def resolve_for_pipenv(request: ResolverRequest) -> ResolverResponse:
    """Run the resolver against a typed :class:`ResolverRequest` and
    return a typed :class:`ResolverResponse`.

    This function NEVER raises.  Every outcome — success, dependency
    conflict, or genuine crash — is captured in the returned response's
    discriminated ``result`` field.  Callers dispatch on ``result.kind``
    to translate to their own outcome shape (return value, raised
    exception, exit code, etc.).

    Variants returned via ``response.result``:

    * :class:`ResolverSuccess` — resolution completed; ``locked`` carries
      a tuple of :class:`LockedRequirement`.
    * :class:`ResolutionError` — pip reported a dependency conflict (a
      :class:`pipenv.exceptions.ResolutionFailure` or
      ``ResolutionImpossible`` / ``DistributionNotFound`` /
      ``DependencyConflict``); ``pip_message`` carries the user-facing
      text.
    * :class:`InternalError` — any other exception; ``message`` and
      ``traceback`` capture the crash.

    The marker environment for ``request.python_marker_override`` is
    patched around the underlying resolve call via the
    :func:`_patched_marker_environment` context manager — so the parent
    interpreter's state is restored on return, which the in-process
    adapter relies on.
    """
    try:
        with _patched_marker_environment(request.python_marker_override):
            locked, _internal_resolver = _dispatch_resolve_packages(request)

        # ``resolve_packages`` may return ``LockedRequirement`` directly
        # (the typed post-T_F.3 shape) or, transitionally, dicts; we
        # accept either and emit only the typed shape on the wire.
        normalized: list[LockedRequirement] = []
        for entry in locked or ():
            if entry is None:
                continue
            if isinstance(entry, LockedRequirement):
                normalized.append(entry)
            elif isinstance(entry, dict):
                try:
                    normalized.append(LockedRequirement.from_json_dict(entry))
                except (KeyError, ValueError):
                    # Skip malformed transitional dicts rather than
                    # crashing the whole resolve.  The legacy path
                    # tolerated these silently; preserve that.
                    continue
            else:
                # Unknown shape — let it through; downstream lockfile
                # writer is the last line of defense.  Future T_F.x can
                # tighten this.
                normalized.append(entry)  # type: ignore[arg-type]

        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=ResolverSuccess(kind="success", locked=tuple(normalized)),
            diagnostics=Diagnostics(),  # T_F.7 will populate resolver_log here.
        )

    except Exception as exc:  # noqa: BLE001 — top-level catch-all per design
        tb = traceback.format_exc()

        # Detect resolution-impossible failures (user-actionable
        # dependency conflicts) by class name to avoid a hard import
        # dependency on ``pipenv.exceptions`` (which would pull in the
        # whole pipenv runtime — unwanted in the schema-only path).
        exc_class_name = type(exc).__name__
        if exc_class_name in {
            "ResolutionFailure",
            "DependencyConflict",
            "DistributionNotFound",
        }:
            return ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=ResolutionError(
                    kind="resolution_error",
                    conflicts=(),
                    pip_message=str(exc),
                ),
                diagnostics=Diagnostics(),
            )

        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=InternalError(
                kind="internal_error",
                message=str(exc),
                traceback=tb,
            ),
            diagnostics=Diagnostics(),
        )


__all__ = [
    "resolve_for_pipenv",
    "resolve_packages",
    "_apply_request_env",
    "_patched_marker_environment",
]
