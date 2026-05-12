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

Follow-up tasks wired into this module:

* ``request.metadata.deadline_seconds`` — T_F.6 enforces a wall-clock
  timeout on the in-process branch via a ``signal.SIGALRM`` guard
  installed by :func:`_wall_clock_deadline`.  Unix only; on Windows
  the guard is a no-op (subprocess branch handles enforcement).
* ``Diagnostics.resolver_log`` — T_F.7 populates this via the
  ``_capture_resolver_log`` context manager defined below; resolver-
  side loggers are scraped during the resolve call and the formatted
  records land on ``response.diagnostics.resolver_log``.
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

# ---------------------------------------------------------------------------
# T_F.7: structured resolver-log capture (per design Q9 / §8).
# ---------------------------------------------------------------------------
#
# We attach a single :class:`logging.Handler` to the loggers the resolver
# actually emits on, collect formatted records into a bounded list, and
# attach the result to :class:`Diagnostics.resolver_log` on the way out.
#
# Design decisions (documented inline so the next maintainer doesn't have
# to dig the plan doc back up):
#
# 1. **Which loggers**: ``pipenv`` (pipenv's own resolution-tracing
#    logger, including ``pipenv.utils.resolver`` and the source-
#    substitution log) and ``pip._internal.resolution`` (pip's resolver-
#    internal logger that emits the candidate selection trace).  Pip's
#    download/progress chatter lives on ``pip._internal.network`` and
#    ``pip._internal.operations.prepare`` and is intentionally NOT
#    captured — stderr is the appropriate channel for that.
# 2. **Format**: ``"[LEVELNAME] message"`` — one string per record, no
#    timestamps (the resolve is a single ~seconds-scale span; a relative
#    delta would be redundant with the existing ``elapsed_seconds`` field
#    on Diagnostics).
# 3. **Bound**: 500 records.  A runaway logger can produce thousands of
#    candidate-evaluation lines per resolve; cap protects both the JSON
#    envelope size and the parent's memory.  Truncation appends a single
#    ``"... (N records elided)"`` sentinel so consumers know they're
#    looking at a clipped view.
# 4. **In-process vs subprocess parity**: this capture happens inside
#    ``resolve_for_pipenv`` so both adapters get identical logs.
# 5. **Stderr is NOT replaced**: this is structured *complement* data
#    surfaced only in verbose mode — see ``pipenv/utils/resolver.py``
#    where the parent prints the records after the resolve completes.
#
# Target-Python constraint (design §3.6): stdlib only, ≥3.10 idioms.
# The handler is a plain ``logging.Handler`` subclass; no MemoryHandler
# (its flushing semantics are wrong for this use case — we want
# every-record capture, not buffered flush-on-overflow).

_RESOLVER_LOG_CAP = 500

# The loggers we want resolution traces from.  Order doesn't matter; we
# install one handler per logger and remove them all on the way out.
_RESOLVER_LOG_LOGGER_NAMES: tuple[str, ...] = (
    "pipenv",
    "pip._internal.resolution",
)


class _BoundedListHandler(logging.Handler):
    """A logging handler that appends formatted records to an in-memory
    list, capped at :data:`_RESOLVER_LOG_CAP` records.

    Once the cap is hit, subsequent records are counted but not stored
    so a runaway logger can't OOM the parent.  The trailing sentinel is
    appended by the surrounding context manager, not by the handler
    itself, so the handler doesn't have to know when capture is "done".
    """

    def __init__(self, sink: list[str], cap: int) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink
        self._cap = cap
        self._dropped = 0
        # Single canonical record format — keep this in lock-step with
        # the test expectations in ``test_resolver_diagnostics.py``.
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    @property
    def dropped(self) -> int:
        return self._dropped

    def emit(self, record: logging.LogRecord) -> None:
        if len(self._sink) >= self._cap:
            self._dropped += 1
            return
        try:
            self._sink.append(self.format(record))
        except Exception:  # noqa: BLE001 — never let a log format crash a resolve
            self._dropped += 1


@contextmanager
def _capture_resolver_log() -> Iterator[list[str]]:
    """Install :class:`_BoundedListHandler` on each target logger,
    yield the shared sink list, and restore each logger's handler set
    (and original level) on exit, even if the resolve raises.

    The yielded list is mutated in place; callers snapshot it after the
    ``with`` block.  The truncation sentinel is appended on exit if the
    handler reports dropped records.

    Logger level handling: pipenv's ``pipenv`` logger and pip's
    ``pip._internal.resolution`` logger both default to ``WARNING`` (or
    inherit a non-DEBUG level from root in pytest / pipenv-launched
    contexts), which would drop INFO resolver-trace records before our
    handler ever sees them.  We lower each captured logger's level to
    ``INFO`` for the duration of capture — **NOT DEBUG**.  Pre-fix this
    function used ``DEBUG`` and cascaded the lowered level to every
    ``pipenv.*`` child (including ``pipenv.patched.pip._internal.*``),
    which made pip's verbose config-loader DEBUG records pass their
    effective-level filter.  Those records then bubbled to pip's
    already-installed root handler (with its ``VERBOSE:logger:message``
    formatter) and flooded stderr — on a multi-category ``pipenv lock``
    (default then dev) the second resolver subprocess drowned in that
    noise and exited non-zero, breaking phase-3 CI consistently
    (see ``tests/unit/test_resolver_diagnostics.py``'s regression
    suite below).  ``INFO`` is the floor pipenv's actual resolver-side
    log emissions use; DEBUG records (pip-internal chatter) stay
    filtered.

    **Propagation discipline** — additionally we set
    ``lg.propagate = False`` while the handler is attached and restore
    the original ``propagate`` flag on exit.  Defence in depth: even if
    an INFO record reaches our handler, ``propagate=False`` prevents
    it from continuing up to root, so pip's already-installed root
    handler can't print a "VERBOSE:" version of the same line as a side
    effect of being captured.

    Pipenv's primary user-facing log channel is the pip-vendored Rich
    consoles in ``pipenv.utils.__init__`` (``console``, ``err``), not
    Python ``logging`` — so this capture is best-effort.  The field
    stays reserved-but-mostly-empty in non-verbose runs, consistent
    with T_F.7 Q9.
    """
    sink: list[str] = []
    handler = _BoundedListHandler(sink, _RESOLVER_LOG_CAP)
    # ``(logger, original_level, original_propagate)`` tuples so we can
    # restore each logger individually.  Levels are integers;
    # ``logger.level`` of ``0`` means NOTSET (inherits from parent).
    touched: list[tuple[logging.Logger, int, bool]] = []
    try:
        for name in _RESOLVER_LOG_LOGGER_NAMES:
            lg = logging.getLogger(name)
            touched.append((lg, lg.level, lg.propagate))
            lg.addHandler(handler)
            # INFO, not DEBUG — see docstring for the phase-3 regression
            # that DEBUG caused.  INFO captures resolver-trace records
            # pipenv actually emits; DEBUG opens the floodgates on
            # ``pipenv.patched.pip._internal.*`` config-loader chatter.
            lg.setLevel(logging.INFO)
            # Defence in depth: prevent records that DO pass the INFO
            # filter from bubbling to pip's root handler as a side effect.
            lg.propagate = False
        yield sink
    finally:
        for lg, original_level, original_propagate in touched:
            try:
                lg.removeHandler(handler)
            except ValueError:
                # Handler already removed — shouldn't happen but be
                # defensive; a leaked handler is the failure mode we're
                # protecting against.
                pass
            lg.setLevel(original_level)
            lg.propagate = original_propagate
        if handler.dropped:
            sink.append(f"... ({handler.dropped} records elided)")


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
# T_F.6: wall-clock deadline guard for the in-process resolve branch.
# ---------------------------------------------------------------------------
#
# The subprocess branch enforces the deadline via
# ``subprocess.wait(timeout=...)`` from the parent (see
# ``pipenv/utils/resolver.py::resolve``).  The in-process branch
# (``PIPENV_RESOLVER_PARENT_PYTHON=1``) runs the resolve inline in the
# same interpreter that pipenv itself is using, so it needs a soft
# in-process guard.  We use ``signal.SIGALRM`` (Unix only) — Windows
# can't install a signal handler that interrupts a synchronous C call
# cleanly, so the in-process guard is a no-op there.  The subprocess
# branch is the production path; this guard is best-effort for the
# debug branch.


@contextmanager
def _wall_clock_deadline(deadline_seconds: float | None) -> Iterator[None]:
    """Install a ``signal.SIGALRM`` handler that raises :class:`TimeoutError`
    after ``deadline_seconds`` and restore the previous handler on exit.

    Behaviour:

    * ``deadline_seconds is None`` or ``<= 0`` — no guard installed.
    * Non-main thread or unsupported platform (Windows) — no guard
      installed; the caller (subprocess branch) is responsible.
    * Otherwise — a SIGALRM handler is installed for the duration of
      the ``with`` block.  When the alarm fires the handler raises
      ``TimeoutError("resolver wall-clock deadline elapsed (Ns)")``,
      which the surrounding ``resolve_for_pipenv`` catches and converts
      into an :class:`InternalError` response variant.
    """
    if deadline_seconds is None or deadline_seconds <= 0:
        yield
        return

    # ``signal.SIGALRM`` is Unix-only.  Guard the import too so the
    # module stays importable on Windows builds.
    try:
        import signal as _signal
    except ImportError:  # pragma: no cover — signal is in stdlib
        yield
        return
    if not hasattr(_signal, "SIGALRM"):
        # Windows path: skip the guard.  The subprocess branch is the
        # production path; the in-process debug branch on Windows will
        # simply not enforce the deadline.
        yield
        return

    # ``signal.setitimer`` only works in the main thread of the main
    # interpreter; fall back gracefully if we're not there.
    import threading as _threading

    if _threading.current_thread() is not _threading.main_thread():
        yield
        return

    seconds = float(deadline_seconds)

    def _handler(_signum, _frame):
        raise TimeoutError(
            f"resolver wall-clock deadline elapsed ({seconds:g}s)"
        )

    previous_handler = _signal.signal(_signal.SIGALRM, _handler)
    # ``setitimer`` accepts a float; ``alarm`` truncates to int and
    # silently turns sub-second timeouts into 0 (== disabled).  Prefer
    # ``setitimer`` so 1.5s deadlines work for tests.
    try:
        _signal.setitimer(_signal.ITIMER_REAL, seconds)
    except (AttributeError, ValueError):  # pragma: no cover — extremely rare
        _signal.alarm(max(1, int(seconds)))
    try:
        yield
    finally:
        try:
            _signal.setitimer(_signal.ITIMER_REAL, 0)
        except (AttributeError, ValueError):  # pragma: no cover
            _signal.alarm(0)
        _signal.signal(_signal.SIGALRM, previous_handler)


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


def _pip_resolve(request: ResolverRequest) -> ResolverResponse:
    """Run the (pip) resolver against a typed :class:`ResolverRequest` and
    return a typed :class:`ResolverResponse`.

    This is the core resolve flow that lived inline in
    :func:`resolve_for_pipenv` prior to T_F.5.  T_F.5 turned
    ``resolve_for_pipenv`` into a thin backend dispatcher; this function
    is the body of the default (pip) backend, called via
    :class:`pipenv.resolver.backends.pip.PipBackend`.

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
    # T_F.7: wrap the entire resolve in a structured log-capture
    # context so both adapters (in-process + subprocess) see the same
    # ``Diagnostics.resolver_log`` payload.  The capture always
    # restores handler state on exit; the live list is captured by
    # reference so we can also attach a partial log to the failure
    # branches below.  The :func:`_capture_resolver_log` context
    # manager appends the truncation sentinel on exit, so the snapshot
    # we take after the ``with`` block sees the final list.
    log_sink: list[str] = []
    try:
        with _capture_resolver_log() as _live_sink:
            # Alias so the outer ``except`` paths can still see whatever
            # records made it in before the exception fired.
            log_sink = _live_sink
            # --- T_F.6 BEGIN: wall-clock deadline guard (in-process) ---
            # The subprocess branch enforces the deadline via
            # ``subprocess.wait(timeout=...)`` in the parent; this guard
            # protects the ``PIPENV_RESOLVER_PARENT_PYTHON=1`` debug branch
            # where pipenv runs the resolve inline.
            with _wall_clock_deadline(request.metadata.deadline_seconds):
                with _patched_marker_environment(request.python_marker_override):
                    locked, _internal_resolver = _dispatch_resolve_packages(request)
            # --- T_F.6 END --------------------------------------------
        captured_log = tuple(log_sink)

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
            diagnostics=Diagnostics(resolver_log=captured_log),
        )

    except Exception as exc:  # noqa: BLE001 — top-level catch-all per design
        tb = traceback.format_exc()
        # The ``with _capture_resolver_log()`` block has unwound by the
        # time we get here (Python guarantees ``__exit__`` runs on
        # exception), so the truncation sentinel — if any — is already
        # appended.  Snapshot the live list now.
        partial_log = tuple(log_sink)

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
                diagnostics=Diagnostics(resolver_log=partial_log),
            )

        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=InternalError(
                kind="internal_error",
                message=str(exc),
                traceback=tb,
            ),
            diagnostics=Diagnostics(resolver_log=partial_log),
        )


# ---------------------------------------------------------------------------
# T_F.5: pluggable resolver-backend dispatch.
# ---------------------------------------------------------------------------
#
# ``resolve_for_pipenv`` was originally the canonical resolve function
# (T_F.4); T_F.5 turns it into a thin dispatcher that routes through the
# ``pipenv.resolver.backends`` registry.  The default behaviour is
# unchanged: with no selection at any level, the pip backend is chosen
# and ``PipBackend.resolve`` runs the same flow that previously lived
# here (now in :func:`_pip_resolve`).
#
# Backend selection precedence (sign-off 2026-05-12 answers 1, 2):
#
#     1. ``ResolverOptions.backend`` on the request (the CLI flag
#        ``--resolver NAME`` stamps it here);
#     2. ``PIPENV_RESOLVER`` env var;
#     3. ``[pipenv] resolver`` Pipfile setting (read via
#        :class:`pipenv.utils.settings.Settings`);
#     4. ``"pip"`` (the default).
#
# An unknown backend name yields a structured ``InternalError``
# response — NOT a crash (sign-off answer 4 "fail loud", but loudly
# *via the typed response*, so adapters can render a clean error).


def _resolver_name_from_env() -> str | None:
    """Return the value of ``PIPENV_RESOLVER`` if set, else ``None``.

    Separated as a helper so tests can monkey-patch the env-var read
    without manipulating ``os.environ`` (which is process-wide and
    leaks across tests).
    """
    value = os.environ.get("PIPENV_RESOLVER")
    if value is None:
        return None
    value = value.strip()
    return value or None


def _resolver_name_from_pipfile() -> str | None:
    """Return the ``[pipenv] resolver`` value from the current project
    Pipfile, or ``None`` if absent / unreadable.

    Best-effort: this is called from the resolver-call layer in the
    parent.  The subprocess child does NOT call this (it consults
    ``request.options.backend`` only — the parent has already made the
    selection by the time the wire request goes out).  If the project
    isn't accessible (e.g. running unit tests with no Pipfile on disk),
    return ``None`` silently and let the caller fall through to the
    default.
    """
    try:
        from pipenv.project import Project
    except Exception:  # noqa: BLE001 — defensive against import issues
        return None
    try:
        project = Project()
        resolver = project.settings.get("resolver")
    except Exception:  # noqa: BLE001 — any read failure → default
        return None
    if not resolver:
        return None
    return str(resolver).strip() or None


def _selected_backend_name(request: ResolverRequest) -> str:
    """Apply the precedence chain CLI > env > Pipfile > default and
    return the backend name to dispatch to.

    Reads only from ``request.options.backend`` (the CLI / explicit
    selection), :func:`_resolver_name_from_env`, and
    :func:`_resolver_name_from_pipfile`.  All four levels of the chain
    are individually monkey-patchable by tests.
    """
    # 1. CLI / explicit request override: ``ResolverOptions.backend`` is
    # the wire-level home for ``--resolver NAME``.  Empty / unset / the
    # "pip" default all fall through to the lower precedence levels so
    # that ``pipenv install`` without ``--resolver`` honours the Pipfile
    # or env-var selection.  The CLI plumbing only stamps this field
    # when the user explicitly passed ``--resolver``.
    cli_choice = getattr(request.options, "backend", None)
    if cli_choice:
        return str(cli_choice)

    # 2. Env var.
    env_choice = _resolver_name_from_env()
    if env_choice:
        return env_choice

    # 3. Pipfile.
    pipfile_choice = _resolver_name_from_pipfile()
    if pipfile_choice:
        return pipfile_choice

    # 4. Default.
    return "pip"


def resolve_for_pipenv(request: ResolverRequest) -> ResolverResponse:
    """Dispatch ``request`` to the configured resolver backend.

    Default behaviour (no ``--resolver`` flag, no ``PIPENV_RESOLVER``
    env var, no ``[pipenv] resolver`` Pipfile key) is unchanged from
    pre-T_F.5 pipenv: the pip backend is selected and the resolve flow
    that previously lived inline here (now :func:`_pip_resolve`) runs.

    Unknown or unavailable backends produce a typed ``InternalError``
    response with a clear message — the function still never raises.
    """
    backend_name = _selected_backend_name(request)

    # Look up the backend.  Resolve KeyError into a typed InternalError
    # so the dispatcher contract ("never raises") is preserved.
    try:
        # Lazy import to avoid a cycle: ``backends.pip`` imports from
        # this module to reach :func:`_pip_resolve`.
        from pipenv.resolver.backends import get_backend

        backend = get_backend(backend_name)
    except KeyError as exc:
        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=InternalError(
                kind="internal_error",
                message=(
                    f"Resolver backend {backend_name!r} is not registered. "
                    f"{exc!s}.  Remove the [pipenv] resolver setting from "
                    f"your Pipfile, unset PIPENV_RESOLVER, or pass "
                    f"--resolver pip."
                ),
                traceback=None,
            ),
        )

    if not backend.is_available():
        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=InternalError(
                kind="internal_error",
                message=(
                    f"Resolver backend {backend_name!r} is not available "
                    f"on this machine.  Install it and re-run, or remove "
                    f"the [pipenv] resolver setting from your Pipfile / "
                    f"unset PIPENV_RESOLVER / pass --resolver pip."
                ),
                traceback=None,
            ),
        )

    return backend.resolve(request)


__all__ = [
    "resolve_for_pipenv",
    "resolve_packages",
    "_apply_request_env",
    "_patched_marker_environment",
    "_pip_resolve",
    "_selected_backend_name",
    "_resolver_name_from_env",
    "_resolver_name_from_pipfile",
]
