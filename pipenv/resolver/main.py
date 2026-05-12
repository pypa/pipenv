"""``pipenv-resolver`` subprocess entry point (T_F.3 + T_F.4).

Wave B1 of Initiative F (T_F.3) replaced the legacy argv/env-var/tempfile
cocktail (see ``docs/dev/initiative-f-protocol.md`` §3 for the full list
of deleted flags + env-var hops) with a single typed envelope:

    pipenv-resolver --request-file <path> --response-file <path>

Both files carry a ``ResolverRequest`` / ``ResolverResponse`` JSON payload
defined in :mod:`pipenv.resolver.schema`.

T_F.4 then folded the in-process and subprocess branches onto a single
:func:`pipenv.resolver.core.resolve_for_pipenv` driver.  This module is
now a *thin adapter* around that function — its only jobs are:

1. Bootstrap ``pipenv`` on ``sys.path`` (the subprocess is invoked by
   the target venv's interpreter, which may not have pipenv installed
   into its own ``site-packages``).
2. Read the request JSON from ``--request-file``.
3. Validate ``schema_version`` BEFORE dispatching on the payload
   (design §3.6 / plan Risk #6).
4. Call :func:`resolve_for_pipenv` (which never raises).
5. Write the response JSON to ``--response-file``.
6. Choose an exit code based on ``response.result.kind``.

See ``docs/dev/initiative-f-typed-design.md`` for the full design and
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
    resolved_default_deps)`` signature.
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
    interpreter is always ``sys.executable``.
    """
    return sys.executable


# ---------------------------------------------------------------------------
# Subprocess entry: --request-file in, --response-file out.
# Thin adapter around :func:`pipenv.resolver.core.resolve_for_pipenv`
# (T_F.4 fold).
# ---------------------------------------------------------------------------


def _main(request_file: str, response_file: str) -> int:
    """Subprocess adapter: read request → call :func:`resolve_for_pipenv`
    → write response.  Returns the intended exit code, never raises.

    Split from :func:`main` so callers (and tests) can drive the logic
    without going through ``sys.argv``.  Always writes a structured
    response to ``response_file`` — schema-version mismatch and uncaught
    exceptions still produce a typed ``InternalError`` payload.
    """
    # ``_ensure_modules`` must run BEFORE the first ``pipenv.*`` import:
    # the subprocess may be invoked via the project venv's python against
    # the absolute path of this file, so ``pipenv`` is not on
    # ``sys.path`` at startup.  Bootstrap it first, then resolve the
    # schema import the normal way.
    _ensure_modules()

    from pipenv.resolver.core import _apply_request_env, resolve_for_pipenv
    from pipenv.resolver.schema import (
        SCHEMA_VERSION,
        InternalError,
        ResolverRequest,
        ResolverResponse,
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

    # ---- Stage 3: full typed parse + delegate to the unified driver. -
    try:
        request = ResolverRequest.from_json_dict(raw)
        _apply_request_env(request)
        response = resolve_for_pipenv(request)
        _write_response(response)
    except Exception as exc:  # noqa: BLE001 — request parsing / response writing only
        # ``resolve_for_pipenv`` itself never raises; the only ways into
        # this branch are a malformed-but-schema-version-OK request
        # (``from_json_dict`` raises ``KeyError``/``ValueError``) or an
        # I/O error while writing the response file.  Either way, try
        # to record an InternalError so the parent has structured
        # detail before bailing.
        tb = traceback.format_exc()
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
            print(tb, file=sys.stderr)
        return 1

    # ---- Stage 4: pick exit code from the structured response. -------
    kind = response.result.kind
    if kind == "internal_error":
        return 1
    # success and resolution_error are both exit 0 (structured payload
    # carries the failure detail — non-zero exit is reserved for
    # genuine crashes per the plan §B1 contract).
    return 0


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
