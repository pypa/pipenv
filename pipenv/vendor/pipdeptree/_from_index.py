"""
Resolve a set of requirements into a dependency tree by querying a package index.

This is the engine behind the ``from-index`` CLI subcommand. It defers to the optional :pypi:`nab-python`
resolver, which resolves a ``[project].dependencies`` table against the package index (PyPI) -- returning pinned
versions plus a forward edge graph -- without touching the active environment. The resolved pins and edges are
adapted into lightweight ``importlib.metadata.Distribution`` look-alikes so the existing
:class:`~pipdeptree._models.PackageDAG` and every renderer work unchanged.

Inputs are explicit, never guessed from a path's shape:

- inline PEP 508 requirement strings (the positional arguments);
- ``--requirements`` files -- standard ``requirements.txt``/``.in``-style files parsed with
  :pypi:`pip-requirements-parser`, so nested ``-r``, ``-c`` constraints, environment markers and comments all work;
- ``--pyproject`` files -- handed natively to nab, which reads ``[project].dependencies`` and honors ``[tool.nab]``.

A lone pyproject (the only source) is resolved natively for full fidelity; otherwise every source is reduced to a
merged list of requirement strings resolved through a temporary ``pyproject.toml``.

Editable installs (``-e ./pkg``), local-path requirements (``./pkg``, ``file://``) and pinned git VCS requirements
(``pkg @ git+https://.../r.git@<sha>``) are not handed to the index. Instead they are translated into nab's
source-override config: a ``[[tool.nab.local-sources]]`` / ``[[tool.nab.vcs-sources]]`` entry plus the package name
added to ``[project].dependencies``. nab reads the target's PEP 621 ``[project]`` metadata statically (no build);
it only invokes a build backend when that metadata is dynamic. Bare wheel/sdist URLs and non-git VCS schemes have no
nab mapping and are still rejected.
"""

from __future__ import annotations

import dataclasses
import os
import string
import tempfile
from dataclasses import dataclass, field
from itertools import starmap
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pipenv.vendor.pipdeptree._synthetic_dist import SyntheticDistribution

if TYPE_CHECKING:
    from collections.abc import Mapping
    from importlib.metadata import Distribution

# nab's recognized git VCS schemes (see nab_python._vcs_admission._VCS_SCHEMES); only these map to a vcs-source.
_GIT_SCHEMES: Final[tuple[str, ...]] = ("git+https", "git+ssh", "git+http", "git+file", "git+git")
# A pinned git ref is a full 40-char hex commit sha; nab's require-pin (default true) refuses anything looser.
_SHA_LENGTH: Final[int] = 40


class FromIndexUnavailableError(Exception):
    """Raised when ``from-index`` is requested but the optional index resolver is not installed."""


class FromIndexInputError(ValueError):
    """Raised when a from-index source cannot be read (missing file, unsupported requirements directive)."""


_INSTALL_HINT: Final[str] = (
    "The from-index subcommand requires the optional index resolver. Install it with: pip install pipdeptree[index]"
)


@dataclass
class _LocalSource:
    """A directory translated into a ``[[tool.nab.local-sources]]`` override."""

    name: str
    path: str
    editable: bool


@dataclass
class _VcsSource:
    """A pinned git URL translated into a ``[[tool.nab.vcs-sources]]`` override."""

    name: str
    url: str


@dataclass
class _ParsedInputs:
    """Accumulated roots plus the source-overrides translated out of editable/local/VCS requirements."""

    requirements: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    local_sources: list[_LocalSource] = field(default_factory=list)
    vcs_sources: list[_VcsSource] = field(default_factory=list)
    indexes: list[tuple[str, str]] | None = None


def resolve_from_index(
    *,
    requirements: list[str],
    requirement_files: list[str],
    pyproject_files: list[str],
    index_url: str | None = None,
    extra_index_url: list[str] | None = None,
) -> list[Distribution]:
    """
    Resolve the explicit inputs into Distribution-like objects by querying the package index.

    :param requirements: inline PEP 508 requirement strings (the positional arguments).
    :param requirement_files: ``requirements.txt``/``.in``-style file paths, parsed into PEP 508 strings.
    :param pyproject_files: ``pyproject.toml`` file paths handed natively to nab.
    :param index_url: primary index URL, replacing PyPI; ``None`` falls back to env then PyPI.
    :param extra_index_url: additional index URLs; ``None`` falls back to env.
    :returns: a list of :class:`importlib.metadata.Distribution` look-alikes ready for
        :meth:`pipdeptree._models.PackageDAG.from_pkgs`.
    :raises FromIndexUnavailableError: if the index resolver is not installed.
    :raises FromIndexInputError: if a source file is missing or a requirements file uses an unsupported directive.
    """
    indexes = _resolve_indexes(index_url, extra_index_url)
    if not requirements and not requirement_files and len(pyproject_files) == 1:
        # A lone pyproject.toml is resolved natively so nab can honor [tool.nab] and the full [project] table; any
        # local/VCS deps there are the user's own [tool.nab] concern, so this path is left untranslated.
        result = _resolve_pyproject_path(_require_existing(Path(pyproject_files[0])), indexes)
    else:
        # Mixed/multiple sources lose native fidelity: fold every pyproject's [project].dependencies into the
        # merged requirement list and resolve them all through one temporary pyproject.
        inputs = _ParsedInputs(
            requirements=[
                dep for path in pyproject_files for dep in _read_pyproject_dependencies(_require_existing(Path(path)))
            ],
            indexes=indexes,
        )
        # A merged --pyproject keeps its [project].dependencies but NOT its own [tool.nab].constraints; only
        # constraints declared via --requirements (-c) files flow into the resolve. Acceptable known gap.
        for path in requirement_files:
            _parse_requirements_file(_require_existing(Path(path)), inputs)
        # Inline positional requirements are scanned for the same editable/local/VCS forms a file would carry.
        _parse_inline_requirements(requirements, inputs)
        result = _resolve_requirements(inputs)
    return _adapt(result)


def _resolve_indexes(index_url: str | None, extra_index_url: list[str] | None) -> list[tuple[str, str]] | None:
    """
    Resolve the effective ordered indexes from flags then env, or ``None`` to use nab's PyPI default.

    Precedence per slot: explicit flag, then PIP_*, then UV_*. The primary replaces PyPI (matching pip's
    ``--index-url``); with only extras given, PyPI stays primary. nab tries indexes in order and the first
    carrying the package wins, unlike pip's merge-and-pick-highest.
    """
    primary = index_url or os.environ.get("PIP_INDEX_URL") or os.environ.get("UV_INDEX_URL") or None
    if extra_index_url is not None:
        extras = extra_index_url
    else:
        extras = (os.environ.get("PIP_EXTRA_INDEX_URL") or os.environ.get("UV_EXTRA_INDEX_URL") or "").split()
    if primary is None and not extras:
        return None

    from nab_python.fetch import (  # noqa: PLC0415
        DEFAULT_INDEX_NAME,
        DEFAULT_INDEX_URL,
    )

    # Only extras given: keep PyPI as the primary so the extras are genuinely additional, not a replacement.
    if primary is None:
        resolved = [(DEFAULT_INDEX_NAME, DEFAULT_INDEX_URL)]
    else:
        name = DEFAULT_INDEX_NAME if primary == DEFAULT_INDEX_URL else "primary"
        resolved = [(name, primary)]
    # nab requires unique index names; generate stable extra-N names that cannot collide with the primary slot.
    resolved.extend((f"extra-{position}", url) for position, url in enumerate(extras, start=1))
    return resolved


def _require_existing(path: Path) -> Path:
    if not path.is_file():
        msg = f"source file does not exist: {path}"
        raise FromIndexInputError(msg)
    return path


def _parse_requirements_file(path: Path, inputs: _ParsedInputs) -> None:
    """
    Parse a requirements file into ``inputs``, following nested ``-r``/``-c`` files.

    The parser routes comment and bare-option lines (``--hash``, ``--index-url``) to its ``options``/``comments``,
    so they drop out silently. Editable/local/git-VCS entries become nab source-overrides; inputs with no nab
    mapping (bare archive URLs, non-git VCS) and constraints bearing extras are rejected.
    """
    # pip-requirements-parser ships in the optional 'index' extra, so it is guarded like nab below.
    from pip_requirements_parser import RequirementsFile  # noqa: PLC0415

    parsed = RequirementsFile.from_file(str(path), include_nested=True)
    for entry in parsed.requirements:
        location = f"{entry.line} ({path}:{entry.line_number})"
        if entry.is_editable or entry.link is not None:
            # Editable lines carry ``req is None``; a relative path is resolved against the requirements file's dir.
            _translate_source(entry, base_dir=path.parent, location=location, inputs=inputs)
            continue
        # The parser routes comment/option-only lines to its ``options``/``comments``; everything left here that is
        # not editable/link-backed carries a parsed PEP 508 ``req``.
        assert entry.req is not None
        if entry.is_constraint:
            if entry.req.extras:
                msg = f"the index resolver cannot constrain extras: {location}"
                raise FromIndexInputError(msg)
            inputs.constraints.append(str(entry.req))
        else:
            # pip-requirements-parser moves the marker off ``req`` onto ``entry.marker``; reattach it so the
            # resolver still sees marker-gated requirements.
            text = str(entry.req)
            inputs.requirements.append(f"{text}; {entry.marker}" if entry.marker is not None else text)


def _parse_inline_requirements(requirements: list[str], inputs: _ParsedInputs) -> None:
    """
    Translate editable/local/VCS forms from positional requirements like file entries.

    Plain PEP 508 strings pass through verbatim; only path/URL-shaped inputs go through the parser, since they
    need a link object to classify and locate.
    """
    translatable = [req for req in requirements if _looks_like_source(req)]
    inputs.requirements.extend(req for req in requirements if not _looks_like_source(req))
    if not translatable:
        return
    from pip_requirements_parser import RequirementsFile  # noqa: PLC0415

    # The parser has no working per-line API (its from_string is broken), so route the lines through a temp file;
    # relative paths in a positional argument resolve against the current working directory.
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "inline.txt"
        listing.write_text("\n".join(translatable) + "\n", encoding="utf-8")
        parsed = RequirementsFile.from_file(str(listing), include_nested=True)
    for entry in parsed.requirements:
        _translate_source(entry, base_dir=Path.cwd(), location=str(entry.line), inputs=inputs)


def _looks_like_source(requirement: str) -> bool:
    # A positional source is a ``name @ <url>`` form or a bare local path; everything else is a plain PEP 508 req.
    stripped = requirement.strip()
    return (
        "://" in stripped
        or stripped.startswith(("./", "../", "/", "file:"))
        or (Path(stripped).exists() and (Path(stripped) / "pyproject.toml").exists())
    )


def _translate_source(entry: Any, *, base_dir: Path, location: str, inputs: _ParsedInputs) -> None:
    """Translate one editable/local/git-VCS entry into a nab source-override, or reject an unmappable URL."""
    link = entry.link
    scheme = "" if link is None else link.scheme
    if entry.is_vcs_url or scheme.startswith("git+"):
        if not scheme.startswith("git+"):
            # Non-git VCS (hg+/bzr+/svn+) has no nab mapping.
            msg = f"only git VCS requirements are supported by the index resolver: {location}"
            raise FromIndexInputError(msg)
        inputs.vcs_sources.append(_to_vcs_source(entry, location))
    elif entry.is_editable or scheme in {"", "file"}:
        # Empty scheme is a bare/editable local path; ``file`` is a file:// URL -- both name a local directory.
        inputs.local_sources.append(_to_local_source(entry, base_dir, location))
    else:
        # Bare wheel/sdist archive URLs (https/http) have no nab source-override.
        msg = f"URL requirements are not supported by the index resolver: {location}"
        raise FromIndexInputError(msg)


def _to_vcs_source(entry: Any, location: str) -> _VcsSource:
    # pip's ``name @ git+...`` and ``git+...#egg=name`` both populate ``req.name``; without a name nab cannot map it.
    if entry.req is None or entry.req.name is None:
        msg = f"VCS requirement needs an explicit name (use 'name @ git+...'): {location}"
        raise FromIndexInputError(msg)
    url = entry.link.url
    # Preempt nab's require-pin so the error names the line; a pinned ref is a 40-char hex sha after the last '@'.
    ref = url.split("#", 1)[0].split("://", 1)[-1].rsplit("@", 1)
    if len(ref) != 2 or len(ref[1]) != _SHA_LENGTH or not all(c in string.hexdigits for c in ref[1]):
        msg = f"VCS requirement must be pinned to a full commit sha: {location}"
        raise FromIndexInputError(msg)
    return _VcsSource(name=entry.req.name, url=url)


def _to_local_source(entry: Any, base_dir: Path, location: str) -> _LocalSource:
    link = entry.link
    # A file:// URL exposes file_path; a bare/editable path is a (possibly relative) filesystem path in link.url.
    raw_path = link.file_path if link.scheme == "file" else link.url
    directory = Path(raw_path)
    if not directory.is_absolute():
        directory = (base_dir / directory).resolve()
    if not (directory / "pyproject.toml").is_file():
        msg = f"editable/local source must be a directory with a pyproject.toml: {location}"
        raise FromIndexInputError(msg)
    if (name := _read_pyproject_name(directory)) is None:
        msg = f"cannot determine package name for editable/local source {directory}: its pyproject.toml has no [project].name"  # noqa: E501
        raise FromIndexInputError(msg)
    return _LocalSource(name=name, path=str(directory), editable=bool(entry.is_editable))


def _read_pyproject_name(directory: Path) -> str | None:
    # read_pyproject_name lives in nab_python, guarded like the resolver imports below.
    try:
        from nab_python.requirements_file import read_pyproject_name  # noqa: PLC0415
    except ImportError as exc:
        raise FromIndexUnavailableError(_INSTALL_HINT) from exc
    return read_pyproject_name(directory / "pyproject.toml")


def _adapt(result: Any) -> list[Distribution]:
    pins: Mapping[str, object] = result.pins
    dependencies: Mapping[str, tuple[str, ...]] = result.lock_input.dependencies
    return [
        SyntheticDistribution(
            name,
            str(version),
            tuple(f"{child}=={pins[child]}" for child in dependencies.get(name, ())),
        )
        for name, version in pins.items()
    ]


def _read_pyproject_dependencies(path: Path) -> list[str]:
    # Pipenv already ships tomli through patched pip on Python versions before stdlib tomllib exists.
    import sys  # noqa: PLC0415

    if sys.version_info >= (3, 11):  # pragma: >=3.11 cover
        import tomllib  # noqa: PLC0415
    else:  # pragma: <3.11 cover
        from pipenv.patched.pip._vendor import tomli as tomllib  # noqa: PLC0415

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    dependencies = data.get("project", {}).get("dependencies", [])
    return [str(dep) for dep in dependencies]


def _resolve_requirements(inputs: _ParsedInputs) -> Any:
    with tempfile.TemporaryDirectory() as tmp:
        pyproject = Path(tmp) / "pyproject.toml"
        # The temp pyproject already carries the [[tool.nab.indexes]] tables, so the resolve path reads them from the
        # file rather than overriding the config; pass None to leave the read config untouched.
        pyproject.write_text(_render_pyproject(inputs), encoding="utf-8")
        return _resolve_pyproject_path(pyproject, None)


def _resolve_pyproject_path(pyproject: Path, indexes: list[tuple[str, str]] | None) -> Any:
    # Imports are deferred and guarded so the optional nab dependency stays out of the core import path; this
    # mirrors how the graphviz renderer guards its import (see _render/graphviz.py).
    try:
        # nab is an optional dependency, absent from a minimal (non-index) install.
        from nab_index.multi_index import IndexConfig  # noqa: PLC0415
        from nab_index.urllib3_async_transport import (  # noqa: PLC0415
            Urllib3AsyncTransport,
        )
        from nab_python.config import read_pyproject_config  # noqa: PLC0415
        from nab_python.resolve import resolve_pyproject  # noqa: PLC0415
    except ImportError as exc:
        raise FromIndexUnavailableError(_INSTALL_HINT) from exc

    config = read_pyproject_config(pyproject)
    if indexes is not None:
        # An explicit --index-url/--extra-index-url (or its env fallback) overrides a --pyproject's own
        # [tool.nab].indexes; with no override (indexes is None) the pyproject's own indexes apply.
        config = dataclasses.replace(config, indexes=tuple(starmap(IndexConfig, indexes)))
    return resolve_pyproject(pyproject, Urllib3AsyncTransport(), config=config)


def _render_pyproject(inputs: _ParsedInputs) -> str:
    # A source-override only changes HOW a package is sourced; the package must also be a root requirement to enter
    # the tree, so every translated source name is added to [project].dependencies.
    roots = [*inputs.requirements, *(s.name for s in inputs.local_sources), *(s.name for s in inputs.vcs_sources)]
    deps = "".join(f"  {_toml_quote(req)},\n" for req in roots)
    rendered = f'[project]\nname = "pipdeptree-from-index"\nversion = "0"\ndependencies = [\n{deps}]\n'

    has_sources = bool(inputs.local_sources or inputs.vcs_sources)
    if inputs.constraints or has_sources:
        rendered += "[tool.nab]\n"
    if inputs.constraints:
        # nab reads constraints only from [tool.nab].constraints; resolve_pyproject has no per-call argument for
        # them, so requirements-file -c entries must be threaded through this temporary pyproject.
        rendered_constraints = "".join(f"  {_toml_quote(con)},\n" for con in inputs.constraints)
        rendered += f"constraints = [\n{rendered_constraints}]\n"
    if has_sources:
        # WHY build-remote with local/VCS sources: nab extracts static PEP 621 metadata first, so a static
        # [project] target resolves with NO build; a build only fires when the target's metadata is dynamic. Using
        # build-remote (vs build-local) keeps that escape hatch open for cloned VCS targets too. Plain resolves
        # (no sources) leave nab's default policy untouched.
        rendered += 'build-policy = "build-remote"\n'
    if inputs.vcs_sources:
        # nab refuses VCS by default (policy=block, empty allowlist); opt in to every recognized git scheme and
        # leave allowed-repos unset (any repo) and require-pin at its default true (reproducible: full sha needed).
        schemes = ", ".join(_toml_quote(scheme) for scheme in _GIT_SCHEMES)
        rendered += f'[tool.nab.vcs]\npolicy = "allow"\nallowed-schemes = [{schemes}]\n'
    for source in inputs.local_sources:
        rendered += (
            "[[tool.nab.local-sources]]\n"
            f"name = {_toml_quote(source.name)}\n"
            f"path = {_toml_quote(source.path)}\n"
            f"editable = {'true' if source.editable else 'false'}\n"
        )
    for source in inputs.vcs_sources:
        rendered += f"[[tool.nab.vcs-sources]]\nname = {_toml_quote(source.name)}\nurl = {_toml_quote(source.url)}\n"
    # An override replaces nab's default PyPI index; with no override the default applies, so nothing is emitted.
    for name, url in inputs.indexes or ():
        rendered += f"[[tool.nab.indexes]]\nname = {_toml_quote(name)}\nurl = {_toml_quote(url)}\n"
    return rendered


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


__all__ = [
    "FromIndexInputError",
    "FromIndexUnavailableError",
    "resolve_from_index",
]
