"""``uv`` resolver backend (gh-6109).

Implements the Initiative F ``Backend`` protocol by shelling out to
``uv pip compile``.  uv is **not** vendored: the backend discovers the
``uv`` binary on ``$PATH`` and the dispatcher fails loud (with an
install hint) when it is missing — see the maintainer sign-off in
``docs/dev/initiative-f-backends-design.md`` (answers 4 and 8).

Why ``uv pip compile`` rather than ``uv lock``
----------------------------------------------
The pip backend resolves for a *single* target environment (the
project's interpreter, optionally with the Pipfile's
``python_full_version`` patched into the marker environment).
``uv lock`` performs a *universal* resolution that may fork a package
into several versions under different markers, which ``Pipfile.lock``
(one version per package) cannot represent.  ``uv pip compile`` with
``--python <interpreter>`` resolves for the same single environment the
pip backend targets, and ``--generate-hashes`` records hashes for every
distribution of the pinned version — the same coverage the pip
backend's hash collection produces, so the lockfile installs on other
platforms.

Flow inside :meth:`UvBackend.resolve`:

1. Translate ``request.packages.specs`` (pip-install argument lines)
   into PEP 508 dependencies, ``[tool.uv.sources]`` pins and path
   sources, and write them to a throwaway ``pyproject.toml``.
2. Make the first source uv's default index and every other source an
   ``explicit = true`` ``[[tool.uv.index]]`` entry, consulted only for
   packages pinned to it.  This is pipenv's index-restriction security
   property: an unpinned package resolves *only* from the primary
   index.  ``uv pip compile`` ignores ``default = true`` on indexes
   declared in the input file, so the primary index is passed as
   ``UV_DEFAULT_INDEX`` — in the environment rather than on the command
   line, so credentials embedded in the URL stay out of process
   listings.
3. Write ``request.resolved_default_deps`` as a constraints file.
4. Run ``uv pip compile`` and parse its requirements-format output
   (``--hash`` lines and ``# via`` annotations).
5. Translate each entry into a :class:`LockedRequirement`.  Markers of
   marker-guarded top-level packages are folded onto the transitive
   dependencies only they introduce.

Known difference from the pip backend: the pip backend AND-merges each
package's ``Requires-Python`` into its ``markers``; uv does not report
``Requires-Python``, so those markers are absent.  They are always true
for the environment the lockfile was resolved for.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlsplit, urlunsplit

from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    Diagnostics,
    InternalError,
    LockedRequirement,
    ResolutionError,
    ResolverRequest,
    ResolverResponse,
    ResolverSuccess,
    Source,
    VCSPin,
)

# Name of the throwaway project uv compiles.  uv reports it in
# ``# via`` annotations for top-level requirements.
_ROOT_PROJECT = "your-pipfile"

_DEFAULT_SOURCE = Source(name="pypi", url="https://pypi.org/simple")

_VCS_SCHEMES = ("git", "hg", "svn", "bzr")

# Environment variables that would let the caller's uv configuration
# redirect where packages come from or silently add requirements.  The
# Pipfile's ``[[source]]`` blocks and package specs are authoritative,
# so these are removed from the uv subprocess environment.
_SCRUBBED_UV_ENV = (
    "UV_CONSTRAINT",
    "UV_DEFAULT_INDEX",
    "UV_EXTRA_INDEX_URL",
    "UV_FIND_LINKS",
    "UV_INDEX",
    "UV_INDEX_STRATEGY",
    "UV_INDEX_URL",
    "UV_NO_INDEX",
    "UV_OVERRIDE",
    "UV_PRERELEASE",
)

INSTALL_HINT = (
    "uv was not found on $PATH.  Install it with one of:\n"
    "    pip install uv\n"
    "    pipx install uv\n"
    "    curl -LsSf https://astral.sh/uv/install.sh | sh\n"
    "See https://docs.astral.sh/uv/getting-started/installation/"
)


def find_uv() -> str | None:
    """Return the path to the ``uv`` executable, or ``None``."""
    return shutil.which("uv")


@dataclass
class _Dependency:
    """One top-level package from the request, prepared for uv."""

    name: str
    pep508: str
    extras: tuple[str, ...] = ()
    markers: str | None = None
    index: str | None = None
    index_url: str | None = None
    lock_index: str | None = None
    path: str | None = None
    abs_path: str | None = None
    file: str | None = None
    vcs: VCSPin | None = None
    editable: bool = False
    skip: bool = False
    specifier: str = ""


@dataclass
class _CompiledEntry:
    """One requirement block parsed from ``uv pip compile`` output."""

    line: str
    hashes: list[str] = field(default_factory=list)
    via: list[str] = field(default_factory=list)


class UvBackend:
    """Resolver backend that drives ``uv pip compile``."""

    name: str = "uv"
    install_hint: str = INSTALL_HINT

    def is_available(self) -> bool:
        return find_uv() is not None

    def resolve(self, request: ResolverRequest) -> ResolverResponse:
        """Resolve ``request`` with uv.  Never raises; failures are
        returned as structured ``ResolutionError`` / ``InternalError``.
        """
        started = time.monotonic()
        uv = find_uv()
        if uv is None:
            return _internal_error(INSTALL_HINT)
        try:
            with tempfile.TemporaryDirectory(prefix="pipenv-uv-") as workdir:
                return self._resolve_in(request, uv, Path(workdir), started)
        except subprocess.TimeoutExpired as exc:
            return _internal_error(
                f"uv did not finish resolving within {exc.timeout:.0f} seconds."
            )
        except Exception as exc:  # noqa: BLE001 — backend contract: never raise
            return _internal_error(str(exc), traceback.format_exc())

    def _resolve_in(
        self, request: ResolverRequest, uv: str, workdir: Path, started: float
    ) -> ResolverResponse:
        sources = list(request.sources) or [_DEFAULT_SOURCE]
        url_to_name = {_normalize_url(s.url): s.name for s in sources}
        pipfile_entries, foreign_pins = _pipfile_context(request.category)

        deps: list[_Dependency] = []
        for name, spec in request.packages.specs.items():
            dep = _parse_spec(name, spec, pipfile_entries.get(name), url_to_name)
            if dep.index_url and dep.index not in url_to_name.values():
                # ``-i URL`` naming an index that isn't a Pipfile source.
                sources.append(Source(name=dep.index or "", url=dep.index_url))
                url_to_name[_normalize_url(dep.index_url)] = dep.index or ""
            deps.append(dep)

        warnings: list[str] = []
        if request.extra_pip_args:
            warnings.append(
                "The uv resolver backend ignores extra pip arguments: "
                + " ".join(request.extra_pip_args)
            )

        index_pins = {
            _canonical(name): index
            for name, index in foreign_pins.items()
        }
        for dep in deps:
            if dep.index:
                index_pins[_canonical(dep.name)] = dep.index
        # Like the pip backend, a pin naming an index that isn't a source
        # restricts nothing: the package resolves from the primary index.
        # Direct references (VCS, file, path) don't come from an index.
        known = set(url_to_name.values())
        direct = {
            _canonical(dep.name) for dep in deps if dep.vcs or dep.file or dep.path
        }
        index_pins = {
            k: v for k, v in index_pins.items() if v in known and k not in direct
        }
        pyproject = workdir / "pyproject.toml"
        pyproject.write_text(
            _render_pyproject(deps, sources, index_pins), encoding="utf-8"
        )

        cmd = [
            uv,
            "pip",
            "compile",
            str(pyproject),
            "--no-config",
            "--python",
            sys.executable,
            "--generate-hashes",
            "--no-header",
            "--color",
            "never",
            "--no-progress",
            "--prerelease",
            "allow" if request.options.pre else "explicit",
        ]
        if request.python_marker_override:
            cmd += ["--python-version", request.python_marker_override]
        if request.options.clear:
            cmd.append("--refresh")
        if request.options.verbose:
            cmd.append("--verbose")
        for source in sources:
            if not source.verify_ssl:
                host = urlsplit(source.url).netloc.rpartition("@")[2]
                if host:
                    cmd += ["--allow-insecure-host", host]
        constraints = _render_constraints(request)
        if constraints:
            constraints_file = workdir / "constraints.txt"
            constraints_file.write_text(constraints, encoding="utf-8")
            cmd += ["--constraint", str(constraints_file)]

        proc = subprocess.run(
            cmd,
            check=False,
            cwd=workdir,
            env=_uv_environment(sources[0].url),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=request.metadata.deadline_seconds,
        )
        log = [" ".join(cmd)]
        if request.options.verbose:
            log.extend(proc.stderr.splitlines())
        diagnostics = Diagnostics(
            warnings=tuple(warnings),
            elapsed_seconds=time.monotonic() - started,
            resolver_log=tuple(log),
        )
        for warning in warnings:
            print(warning, file=sys.stderr)

        if proc.returncode == 1:
            # uv exits 1 for unsatisfiable requirements and for packages
            # that can't be found — both user-actionable.
            return ResolverResponse(
                schema_version=SCHEMA_VERSION,
                result=ResolutionError(
                    kind="resolution_error",
                    conflicts=(),
                    pip_message=proc.stderr.strip(),
                ),
                diagnostics=diagnostics,
            )
        if proc.returncode != 0:
            return _internal_error(
                f"uv pip compile exited with status {proc.returncode}:\n"
                f"{proc.stderr.strip()}",
                diagnostics=diagnostics,
            )

        locked = _translate(
            _parse_compile_output(proc.stdout),
            deps,
            index_pins,
        )
        return ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=ResolverSuccess(kind="success", locked=locked),
            diagnostics=diagnostics,
        )


# ---------------------------------------------------------------------------
# Request → uv input
# ---------------------------------------------------------------------------


def _parse_spec(
    name: str,
    spec: str,
    pipfile_entry: Any,
    url_to_name: Mapping[str, str],
) -> _Dependency:
    """Translate one wire-shape spec (a pip-install argument line, as
    produced by ``convert_deps_to_pip``) into a :class:`_Dependency`.
    """
    from pipenv.utils.indexes import parse_indexes
    from pipenv.vendor.packaging.requirements import Requirement

    entry = pipfile_entry if isinstance(pipfile_entry, dict) else {}
    index_url, _extra, _trusted, remainder = parse_indexes(spec)
    editable = bool(entry.get("editable"))
    if remainder and remainder[0] in ("-e", "--editable"):
        editable = True
        remainder = remainder[1:]
    text = " ".join(remainder).strip()

    index = entry.get("index")
    if index_url and not index:
        index = url_to_name.get(_normalize_url(index_url))
        if index is None:
            index = f"pipenv-index-{len(url_to_name)}"
    # The lockfile ``index`` field follows the pip backend's rule: a
    # dict-style Pipfile entry records only an explicit ``index``; a
    # plain string entry records the index it resolves from.
    if isinstance(pipfile_entry, dict):
        lock_index = entry.get("index")
    else:
        lock_index = index or (next(iter(url_to_name.values()), None))
    dep = _Dependency(
        name=name,
        pep508="",
        editable=editable,
        index=index,
        index_url=index_url,
        lock_index=lock_index,
        skip=bool(entry.get("skip_resolver")),
    )

    if _looks_like_path(text):
        location = entry.get("path") or entry.get("file") or text
        dep.abs_path = os.path.abspath(os.path.expanduser(text))
        if entry.get("file"):
            dep.file = location
        else:
            dep.path = location
        dep.pep508 = name
        dep.index = dep.lock_index = None
        return dep

    req = Requirement(text)
    dep.extras = tuple(sorted(req.extras))
    if req.marker is not None:
        dep.markers = str(req.marker).replace('"', "'")
    dep.specifier = str(req.specifier)
    if req.url:
        dep.index = dep.lock_index = None
        scheme = req.url.split("+", 1)[0] if "+" in req.url.split(":", 1)[0] else ""
        if scheme in _VCS_SCHEMES:
            dep.vcs = _vcs_pin(req.url)
        elif req.url.startswith("file:"):
            dep.abs_path = _file_url_to_path(req.url)
            dep.file = entry.get("file") or entry.get("path") or req.url
        else:
            dep.file = req.url
    dep.pep508 = str(req)
    return dep


def _render_pyproject(
    deps: Sequence[_Dependency],
    sources: Sequence[Source],
    index_pins: Mapping[str, str],
) -> str:
    """Render the throwaway ``pyproject.toml`` uv compiles.

    JSON string literals are valid TOML basic strings, so ``json.dumps``
    does the quoting.
    """
    q = json.dumps
    lines = [
        "[project]",
        f"name = {q(_ROOT_PROJECT)}",
        'version = "0"',
        "dependencies = [",
    ]
    for dep in deps:
        if dep.skip:
            continue
        if dep.abs_path and dep.vcs is None and (dep.path or dep.editable):
            requirement = dep.name + (f"[{','.join(dep.extras)}]" if dep.extras else "")
            if dep.markers:
                requirement += f" ; {dep.markers}"
        else:
            requirement = dep.pep508
        lines.append(f"    {q(requirement)},")
    lines.append("]")
    lines.append("")
    lines.append("[tool.uv.sources]")
    for dep in deps:
        if dep.skip or not dep.abs_path or dep.vcs is not None:
            continue
        if dep.path or dep.editable:
            editable = "true" if dep.editable else "false"
            lines.append(
                f"{q(_canonical(dep.name))} = "
                f"{{ path = {q(dep.abs_path)}, editable = {editable} }}"
            )
    primary = sources[0].name
    for name, index in sorted(index_pins.items()):
        if index != primary:
            lines.append(f"{q(name)} = {{ index = {q(_uv_index_name(index))} }}")
    # The primary index is uv's default index (see ``_uv_environment``).
    for source in sources[1:]:
        lines.append("")
        lines.append("[[tool.uv.index]]")
        lines.append(f"name = {q(_uv_index_name(source.name))}")
        lines.append(f"url = {q(source.url)}")
        lines.append("explicit = true")
    return "\n".join(lines) + "\n"


def _render_constraints(request: ResolverRequest) -> str:
    """Pin the already-resolved default-category packages so that
    non-default categories resolve consistently with them."""
    resolved = request.resolved_default_deps
    if resolved is None:
        return ""
    lines = []
    for entry in resolved.entries:
        if entry.vcs is not None:
            ref = f"@{entry.vcs.ref}" if entry.vcs.ref else ""
            lines.append(f"{entry.name} @ {entry.vcs.backend}+{entry.vcs.url}{ref}")
        elif entry.version and entry.version.startswith("=="):
            lines.append(f"{entry.name}{entry.version}")
    return "\n".join(lines) + ("\n" if lines else "")


def _uv_environment(default_index: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_UV_ENV}
    env["UV_DEFAULT_INDEX"] = default_index
    # Pipenv forwards its keyring setting to pip as PIP_KEYRING_PROVIDER
    # (gh-5715); uv reads its own variable and only knows ``disabled``
    # and ``subprocess``, so pip's ``auto`` / ``import`` map to the
    # latter.
    keyring = env.get("PIP_KEYRING_PROVIDER")
    if keyring and "UV_KEYRING_PROVIDER" not in env:
        env["UV_KEYRING_PROVIDER"] = "disabled" if keyring == "disabled" else "subprocess"
    env.setdefault("UV_NO_PROGRESS", "1")
    return env


def _pipfile_context(category: str) -> tuple[dict, dict]:
    """Best-effort read of the project's Pipfile, mirroring what the pip
    backend's ``Resolver.create`` reads inside the resolver subprocess.

    Returns ``(entries, foreign_pins)``: the Pipfile entries of
    ``category`` (for ``editable`` / ``file`` / ``path`` /
    ``skip_resolver`` details the wire spec doesn't carry), and, for
    non-default categories, the ``index`` pins declared in *other*
    categories so their transitive use resolves from the right index.
    """
    try:
        from pipenv.project import Project

        project = Project(chdir=False)
        if not project.pipfile.exists:
            return {}, {}
        pipfile = project.pipfile
        entries = dict(pipfile.get_section(category) or {})
        foreign: dict[str, str] = {}
        if category and category != "packages":
            for other in pipfile.get_package_categories():
                if other == category:
                    continue
                for name, entry in (pipfile.get_section(other) or {}).items():
                    if isinstance(entry, dict) and entry.get("index"):
                        foreign.setdefault(name, entry["index"])
        return entries, foreign
    except Exception:  # noqa: BLE001 — no project on disk → spec-only
        return {}, {}


# ---------------------------------------------------------------------------
# uv output → LockedRequirement
# ---------------------------------------------------------------------------


def _parse_compile_output(text: str) -> list[_CompiledEntry]:
    """Parse ``uv pip compile`` requirements-format output.

    Each requirement starts on an unindented line; ``--hash`` lines and
    ``# via`` annotations follow, indented.  ``# via`` is
    either inline (single parent) or followed by ``#   parent`` lines.
    """
    entries: list[_CompiledEntry] = []
    current: _CompiledEntry | None = None
    in_via = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if not raw[0].isspace() and not stripped.startswith("#"):
            tokens = stripped.rstrip("\\").split(" --hash=")
            current = _CompiledEntry(line=tokens[0].strip())
            current.hashes.extend(t.strip() for t in tokens[1:])
            entries.append(current)
            in_via = False
            continue
        if current is None:
            continue
        if stripped.startswith("--hash="):
            current.hashes.append(stripped[len("--hash=") :].rstrip("\\").strip())
            in_via = False
        elif stripped.startswith("# via"):
            rest = stripped[len("# via") :].strip()
            in_via = not rest
            if rest:
                current.via.append(rest)
        elif in_via and stripped.startswith("#"):
            current.via.append(stripped.lstrip("#").strip())
    return entries


def _translate(
    entries: Sequence[_CompiledEntry],
    deps: Sequence[_Dependency],
    index_pins: Mapping[str, str],
) -> tuple[LockedRequirement, ...]:
    from pipenv.utils.dependencies import pep423_name
    from pipenv.vendor.packaging.requirements import Requirement

    top_level = {_canonical(dep.name): dep for dep in deps}
    by_path = {
        os.path.normcase(dep.abs_path): dep for dep in deps if dep.abs_path
    }

    resolved: dict[str, tuple[_CompiledEntry, _Dependency | None, Any]] = {}
    for entry in entries:
        dep: _Dependency | None = None
        req = None
        if entry.line.startswith(("-e ", "--editable ")):
            location = entry.line.split(None, 1)[1].strip()
            if location.startswith("file:"):
                location = _file_url_to_path(location)
            dep = by_path.get(os.path.normcase(os.path.abspath(location)))
            if dep is None:
                continue
            key = _canonical(dep.name)
        else:
            req = Requirement(entry.line)
            key = _canonical(req.name)
            dep = top_level.get(key)
        resolved[key] = (entry, dep, req)

    parents: dict[str, set[str]] = {}
    for key, (entry, _dep, _req) in resolved.items():
        parents[key] = set()
        for via in entry.via:
            if via.startswith(_ROOT_PROJECT):
                parents[key].add("")
            elif not via.startswith("-"):
                parents[key].add(_canonical(via.split()[0]))
    markers = _fold_markers(parents, top_level)

    locked: list[LockedRequirement] = []
    for key, (entry, dep, req) in resolved.items():
        name = pep423_name(dep.name if dep else req.name)
        index = dep.lock_index if dep is not None else index_pins.get(key)
        fields: dict[str, Any] = {
            "name": name,
            "extras": dep.extras if dep else (),
            "markers": markers.get(key),
            "hashes": tuple(sorted(set(entry.hashes))),
            "index": index,
            "editable": bool(dep and dep.editable),
        }
        if dep is not None and (dep.path or dep.file) and dep.vcs is None:
            fields["path"] = dep.path
            fields["file"] = dep.file
        elif dep is not None and dep.vcs is not None:
            pinned_vcs = _vcs_pin(req.url) if req is not None and req.url else dep.vcs
            fields["vcs"] = VCSPin(
                backend=pinned_vcs.backend,
                url=pinned_vcs.url,
                ref=pinned_vcs.ref or dep.vcs.ref,
                subdirectory=pinned_vcs.subdirectory or dep.vcs.subdirectory,
            )
        elif req is not None and req.url:
            fields["file"] = req.url
        else:
            fields["version"] = "==" + next(iter(req.specifier)).version
        locked.append(LockedRequirement(**fields))

    # Top-level packages uv left out because their markers don't apply
    # to this environment.  The pip backend records them anyway (from
    # the Pipfile entry, without hashes) so the lockfile still installs
    # them on the platforms they target; do the same.
    for key, dep in top_level.items():
        if key in resolved or not (dep.markers or dep.skip):
            continue
        locked.append(
            LockedRequirement(
                name=pep423_name(dep.name),
                version=None if (dep.vcs or dep.path or dep.file) else (dep.specifier or "*"),
                extras=dep.extras,
                markers=dep.markers,
                index=dep.lock_index,
                vcs=dep.vcs,
                path=dep.path,
                file=dep.file,
                editable=dep.editable,
            )
        )
    return tuple(locked)


def _fold_markers(
    parents: Mapping[str, set[str]], top_level: Mapping[str, _Dependency]
) -> dict[str, str | None]:
    """Compute each package's marker from the markers of the top-level
    packages that pull it in.

    A package needed by any unconditional path gets no marker; one
    reached only through marker-guarded top-level packages gets the OR
    of their markers.  ``""`` in ``parents`` means "required directly
    by the project".
    """
    memo: dict[str, tuple[str, ...] | None] = {}

    def conditions(key: str, visiting: frozenset[str]) -> tuple[str, ...] | None:
        # ``None`` means unconditional; a tuple lists alternative markers
        # (empty when every path back to the project runs through a
        # cycle edge, i.e. no contribution from this branch).
        if key in memo:
            return memo[key]
        found: list[str] = []
        partial = False
        for parent in sorted(parents.get(key, ())):
            if parent == "":
                dep = top_level.get(key)
                if dep is None or not dep.markers:
                    memo[key] = None
                    return None
                found.append(dep.markers)
            elif parent in visiting:
                partial = True
            else:
                upstream = conditions(parent, visiting | {key})
                if upstream is None:
                    memo[key] = None
                    return None
                found.extend(upstream)
        unique = tuple(dict.fromkeys(found))
        # A result computed while skipping a cycle edge depends on the
        # path taken to get here, so only memoize complete results.
        if not partial:
            memo[key] = unique
        return unique

    folded: dict[str, str | None] = {}
    for key in parents:
        found = conditions(key, frozenset())
        if not found:
            # Unconditional, or only reachable through an unknown parent
            # (e.g. a constraints file).
            folded[key] = None
        elif len(found) == 1:
            folded[key] = found[0]
        else:
            folded[key] = " or ".join(f"({m})" for m in found)
    return folded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _internal_error(
    message: str, tb: str | None = None, diagnostics: Diagnostics | None = None
) -> ResolverResponse:
    return ResolverResponse(
        schema_version=SCHEMA_VERSION,
        result=InternalError(kind="internal_error", message=message, traceback=tb),
        diagnostics=diagnostics or Diagnostics(),
    )


def _canonical(name: str) -> str:
    from pipenv.vendor.packaging.utils import canonicalize_name

    return canonicalize_name(name)


def _uv_index_name(name: str) -> str:
    """uv index names allow only ASCII alphanumerics, ``-``, ``_``, ``.``."""
    return "".join(c if c.isascii() and (c.isalnum() or c in "-_.") else "-" for c in name)


def _normalize_url(url: str) -> str:
    """Strip credentials and trailing slashes so an ``-i URL`` in a spec
    matches the Pipfile source it names."""
    parts = urlsplit(url.strip())
    netloc = parts.netloc.rpartition("@")[2].lower()
    return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), "", ""))


def _looks_like_path(text: str) -> bool:
    if not text or " @ " in text:
        return False
    return (
        text.startswith((".", "/", "~", "\\"))
        or (len(text) > 1 and text[1] == ":")  # Windows drive
        or os.path.exists(text)
    )


def _file_url_to_path(url: str) -> str:
    parts = urlsplit(url)
    path = unquote(parts.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return os.path.abspath(path)


def _vcs_pin(url: str) -> VCSPin:
    """Split ``git+https://host/repo.git@ref#subdirectory=x`` into a
    :class:`VCSPin`."""
    backend, _, rest = url.partition("+")
    parts = urlsplit(rest)
    path, sep, ref = parts.path.rpartition("@")
    if not sep:
        path, ref = parts.path, ""
    subdirectory = None
    for item in parts.fragment.split("&"):
        key, _, value = item.partition("=")
        if key == "subdirectory" and value:
            subdirectory = value
    return VCSPin(
        backend=backend,
        url=urlunsplit((parts.scheme, parts.netloc, path, parts.query, "")),
        ref=ref or None,
        subdirectory=subdirectory,
    )


__all__ = ["UvBackend", "find_uv", "INSTALL_HINT"]
