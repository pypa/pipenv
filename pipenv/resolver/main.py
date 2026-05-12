"""``pipenv-resolver`` subprocess entry point (T_F.3).

Wave B1 of Initiative F replaced the legacy argv/env-var/tempfile cocktail
(see ``docs/dev/initiative-f-protocol.md`` §3 for the full list of
deleted flags + env-var hops) with a single typed envelope:

    pipenv-resolver --request-file <path> --response-file <path>

Both files carry a ``ResolverRequest`` / ``ResolverResponse`` JSON payload
defined in :mod:`pipenv.resolver.schema`.  See
``docs/dev/initiative-f-typed-design.md`` for the full design and
``docs/dev/initiative-f-execution-plan.md`` §B1 for the rewrite
checklist.

Exit-code contract (plan §B1 / design §3.2):

* **Exit 0** on resolution success AND on resolution failure (a
  structured ``ResolutionError`` response is written; non-zero exit is
  reserved for genuine crashes).
* **Non-zero** only when an uncaught exception escaped before the
  response could be assembled, OR when the request fails the
  ``schema_version`` check (per Q2 — structured ``InternalError`` written
  AND non-zero exit so the parent can distinguish "protocol skew" from
  "regular resolution failure").

Stderr free-text continues to flow.  The parent-side
``_is_download_status_line`` filter in ``pipenv/utils/resolver.py``
consumes it; we do not silence it here.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import traceback
from typing import Any


def _ensure_modules() -> None:
    """Bootstrap typing_extensions + pipenv on ``sys.modules``.

    Preserved verbatim from the legacy entry point — patched pip uses
    absolute imports like ``pipenv.patched.pip._internal.X``, so pipenv
    must be importable as a top-level package before any pip-internal
    import fires.
    """
    if "typing_extensions" not in sys.modules:
        typing_ext_path = os.path.join(
            os.path.dirname(__file__),
            "patched",
            "pip",
            "_vendor",
            "typing_extensions.py",
        )
        if os.path.exists(typing_ext_path):
            spec = importlib.util.spec_from_file_location(
                "typing_extensions",
                location=typing_ext_path,
            )
            typing_extensions = importlib.util.module_from_spec(spec)
            sys.modules["typing_extensions"] = typing_extensions
            spec.loader.exec_module(typing_extensions)
        else:
            try:
                import typing_extensions  # noqa: F401
            except ImportError:
                pass

    if "pipenv" not in sys.modules:
        pipenv_parent = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if pipenv_parent not in sys.path:
            sys.path.insert(0, pipenv_parent)
        import pipenv  # noqa: F401


# ---------------------------------------------------------------------------
# argv contract: --request-file <p> --response-file <q>  (and nothing else).
# ---------------------------------------------------------------------------


def get_parser():
    from argparse import ArgumentParser

    parser = ArgumentParser(
        "pipenv-resolver",
        description=(
            "Internal pipenv subprocess entry: reads a typed ResolverRequest "
            "JSON envelope and writes a typed ResolverResponse JSON envelope. "
            "Not intended to be invoked directly."
        ),
    )
    parser.add_argument(
        "--request-file",
        metavar="path",
        required=True,
        help="Path to the ResolverRequest JSON payload (see pipenv/resolver/schema.py).",
    )
    parser.add_argument(
        "--response-file",
        metavar="path",
        required=True,
        help="Path to write the ResolverResponse JSON payload to.",
    )
    return parser


# ---------------------------------------------------------------------------
# Marker-environment override — travelled via a legacy env-var pre-T_F.3,
# now a typed field on the request.  See design doc §3.6.
# ---------------------------------------------------------------------------


def _apply_python_marker_override(python_marker_override: str | None) -> None:
    """Monkey-patch ``default_environment`` in pip's vendored packaging so
    marker evaluation uses the project's target Python rather than the
    interpreter currently executing ``pipenv-resolver``.

    Pre-T_F.3 the override travelled via an environment variable; now it
    rides on the typed request as ``ResolverRequest.python_marker_override``.
    See https://github.com/pypa/pipenv/issues/5908.
    """
    if not python_marker_override:
        return

    parts = python_marker_override.split(".")
    python_version = ".".join(parts[:2])
    python_full_version = python_marker_override

    import pipenv.patched.pip._vendor.packaging.markers as pip_markers

    _orig = pip_markers.default_environment

    def _patched():
        env = _orig()
        env["python_version"] = python_version
        env["python_full_version"] = python_full_version
        return env

    pip_markers.default_environment = _patched


# ---------------------------------------------------------------------------
# Result-dict → typed LockedRequirement adapter.
# ---------------------------------------------------------------------------


def _result_dict_to_locked_requirement(entry: dict[str, Any]):
    """Convert a ``clean_results``-shaped dict into a ``LockedRequirement``.

    ``Resolver.clean_results`` (in ``pipenv/utils/resolver.py``) currently
    returns dicts produced by ``format_requirement_for_lockfile`` — the
    *flat* lockfile shape with top-level VCS keys (``git`` / ``hg`` /
    ``svn`` / ``bzr``) rather than the schema's nested ``vcs`` dict.

    Wave B3 will fold ``format_requirement_for_lockfile`` into
    ``LockedRequirement.from_install_requirement`` directly; until then,
    B1 needs this adapter so the subprocess can emit a typed response
    while ``clean_results``'s output shape is still flat.
    """
    from pipenv.resolver.schema import LockedRequirement, VCSPin
    from pipenv.utils.constants import VCS_LIST

    vcs_pin: VCSPin | None = None
    for backend in VCS_LIST:
        if backend in entry:
            vcs_pin = VCSPin(
                backend=backend,
                url=entry[backend],
                ref=entry.get("ref"),
                subdirectory=entry.get("subdirectory"),
            )
            break

    extras = entry.get("extras") or ()
    hashes = entry.get("hashes") or ()

    return LockedRequirement(
        name=entry["name"],
        version=entry.get("version") if vcs_pin is None else None,
        extras=tuple(extras),
        markers=entry.get("markers"),
        hashes=tuple(hashes),
        index=entry.get("index"),
        vcs=vcs_pin,
        file=entry.get("file"),
        path=entry.get("path"),
        editable=bool(entry.get("editable", False)),
        no_binary=bool(entry.get("no_binary", False)),
        subdirectory=entry.get("subdirectory") if vcs_pin is None else None,
    )


# ---------------------------------------------------------------------------
# Core resolve driver — kept under the historical name ``resolve_packages``
# so the in-process branch in ``pipenv/utils/resolver.py`` (B2's territory)
# can keep calling it.  The signature changes from the legacy positional
# zoo to a single typed ``ResolverRequest``.
# ---------------------------------------------------------------------------


def resolve_packages(request):
    """Run the resolver against a typed :class:`ResolverRequest`.

    Returns a tuple ``(locked, resolver)`` where ``locked`` is a list of
    :class:`pipenv.resolver.schema.LockedRequirement` instances and
    ``resolver`` is the internal pipenv ``Resolver`` instance (preserved
    for the in-process branch's smoke assertions, which still poke at
    it).

    Replaces the legacy ``resolve_packages(pre, clear, verbose, system,
    write, requirements_dir, packages, pipfile_category, constraints,
    resolved_default_deps)`` signature.  The in-process branch at
    ``pipenv/utils/resolver.py:1431`` must adapt to the new shape; that
    migration is B2's job.
    """
    from pipenv.project import Project
    from pipenv.utils.resolver import resolve_deps

    project = Project()

    # Translate the typed sources back into pipenv-flavoured source dicts.
    sources = [
        {
            "name": s.name,
            "url": s.url,
            "verify_ssl": s.verify_ssl,
        }
        for s in request.sources
    ]

    # Resolved-default-deps for non-default categories (gh-4665).
    if request.resolved_default_deps is not None:
        resolved_default_deps = [
            lr.to_lockfile_dict() for lr in request.resolved_default_deps.entries
        ]
    else:
        resolved_default_deps = None

    packages = dict(request.packages.specs)

    # Drive the existing resolver — clean_results still produces flat
    # lockfile-shaped dicts via ``format_requirement_for_lockfile`` (B3's
    # territory).  We adapt the dicts to typed LockedRequirement here.
    results, resolver = resolve_deps(
        packages,
        which,
        project=project,
        pre=request.options.pre,
        pipfile_category=request.category,
        sources=sources,
        clear=request.options.clear,
        allow_global=request.options.system,
        req_dir=None,
        resolved_default_deps=resolved_default_deps,
        extra_pip_args=list(request.extra_pip_args) if request.extra_pip_args else None,
    )

    # ``clean_results`` may return either ``LockedRequirement`` instances
    # (post-B2 typed flow) or raw dicts (transitional skipped-entry
    # path).  Adapt both shapes uniformly.
    from pipenv.resolver.schema import LockedRequirement

    locked: list[LockedRequirement] = []
    for r in results or []:
        if isinstance(r, LockedRequirement):
            locked.append(r)
        else:
            locked.append(_result_dict_to_locked_requirement(r))
    return locked, resolver


def which(*args, **kwargs):
    """Stub for the ``which`` callable that pipenv's resolver expects.

    The subprocess runs *inside* the target venv, so the resolving
    interpreter is always ``sys.executable``.  Preserved (and ONLY
    preserved as an in-module function — the legacy module-level
    ``which`` stub at ``resolver.py:90-91`` is gone) because pipenv's
    Resolver internals call it as a callback.
    """
    return sys.executable


# ---------------------------------------------------------------------------
# Subprocess entry: --request-file in, --response-file out.
# ---------------------------------------------------------------------------


def _main(request_file: str, response_file: str) -> int:
    """Inner entry: returns the intended exit code, never raises.

    Split from :func:`main` so callers (and tests) can drive the logic
    without going through ``sys.argv``.  Always writes a structured
    response to ``response_file`` — schema-version mismatch and uncaught
    exceptions still produce a typed ``InternalError`` payload.
    """
    from pipenv.resolver.schema import (
        SCHEMA_VERSION,
        InternalError,
        ResolutionError,
        ResolverRequest,
        ResolverResponse,
        ResolverSuccess,
    )

    def _write_response(response: ResolverResponse) -> None:
        with open(response_file, "w") as fh:
            json.dump(response.to_json_dict(), fh, indent=2, sort_keys=True)

    # ---- Stage 1: read the raw JSON.  Crash-only on this read; if we
    # can't even open the request file, we can't produce a structured
    # response either (no place to write it might still be open, but
    # we try). --------------------------------------------------------
    try:
        with open(request_file) as fh:
            raw = json.load(fh)
    except Exception as exc:  # noqa: BLE001 — we genuinely catch all
        try:
            _write_response(
                ResolverResponse(
                    schema_version=SCHEMA_VERSION,
                    result=InternalError(
                        kind="internal_error",
                        message=f"could not read request file {request_file!r}: {exc!s}",
                        traceback=traceback.format_exc(),
                    ),
                )
            )
        except Exception:  # noqa: BLE001
            pass
        return 1

    # ---- Stage 2: schema-version check BEFORE attempting to dispatch
    # on the rest of the payload (design §3.6 / plan Risk #6). ---------
    payload_schema_version = raw.get("schema_version")
    if payload_schema_version != SCHEMA_VERSION:
        _write_response(
            ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=InternalError(
                    kind="internal_error",
                    message=(
                        f"schema version mismatch: parent sent "
                        f"{payload_schema_version!r}, child expects {SCHEMA_VERSION!r}"
                    ),
                ),
            )
        )
        return 2

    # ---- Stage 3: full typed parse + resolve. ------------------------
    try:
        request = ResolverRequest.from_json_dict(raw)
        _ensure_modules()
        os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        os.environ["PYTHONIOENCODING"] = "utf-8"
        os.environ["PYTHONUNBUFFERED"] = "1"
        if request.options.verbose:
            os.environ["PIPENV_VERBOSITY"] = "1"
            os.environ["PIP_RESOLVER_DEBUG"] = "1"
        else:
            logging.getLogger("pipenv").setLevel(logging.WARN)

        _apply_python_marker_override(request.python_marker_override)

        # Dispatch ``resolve_packages`` via attribute lookup on the
        # package-qualified module rather than the module-local name.
        # When the entry is invoked as a script path, the script runs
        # under the ``__main__`` module identity (distinct from
        # ``pipenv.resolver.main`` in ``sys.modules``); calling via
        # ``sys.modules["pipenv.resolver.main"].resolve_packages``
        # means tests + future re-exports can monkey-patch one well-
        # known location and have it stick regardless of which entry
        # path Python took.
        _resolver_main_mod = sys.modules.get("pipenv.resolver.main")
        if _resolver_main_mod is not None and hasattr(
            _resolver_main_mod, "resolve_packages"
        ):
            _resolve_packages_callable = _resolver_main_mod.resolve_packages
        else:
            _resolve_packages_callable = resolve_packages
        locked, _resolver = _resolve_packages_callable(request)

        _write_response(
            ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=ResolverSuccess(kind="success", locked=tuple(locked)),
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — top-level catch-all per plan §B1 step 8
        tb = traceback.format_exc()
        # Try to detect resolution-impossible failures so we can emit
        # ResolutionError rather than InternalError.  The detection is
        # by class name to avoid a hard import dep on
        # ``pipenv/utils/resolver.py`` (the parent-side rewrite owns
        # that module).
        exc_class_name = type(exc).__name__
        if exc_class_name in {"ResolutionFailure", "DependencyConflict", "DistributionNotFound"}:
            _write_response(
                ResolverResponse(
                    schema_version=SCHEMA_VERSION,
                    result=ResolutionError(
                        kind="resolution_error",
                        conflicts=(),
                        pip_message=str(exc),
                    ),
                )
            )
            return 0
        # Genuine crash → InternalError + non-zero exit.
        try:
            _write_response(
                ResolverResponse(
                    schema_version=SCHEMA_VERSION,
                    result=InternalError(
                        kind="internal_error",
                        message=str(exc),
                        traceback=tb,
                    ),
                )
            )
        except Exception:  # noqa: BLE001
            # If we can't even write the response, surface the crash
            # via stderr and the non-zero exit.
            print(tb, file=sys.stderr)
        return 1


def main(argv=None) -> int:
    """Console-script entry point.  Returns the exit code (does not
    ``sys.exit`` so tests can drive it directly).
    """
    parser = get_parser()
    parsed = parser.parse_args(argv)
    rc = _main(parsed.request_file, parsed.response_file)
    return rc


if __name__ == "__main__":
    sys.exit(main() or 0)
