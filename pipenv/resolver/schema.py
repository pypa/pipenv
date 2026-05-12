"""Typed wire-schema for the pipenv-resolver subprocess protocol (T_F.3).

This module is the single source of truth for the ``ResolverRequest`` /
``ResolverResponse`` JSON envelope exchanged between the parent ``pipenv``
process and the ``pipenv-resolver`` subprocess.  See:

* ``docs/dev/initiative-f-typed-design.md`` §3 — the full design.
* ``docs/dev/initiative-f-protocol.md`` — the historical (pre-T_F.3) ad-hoc
  protocol that this module replaces.
* ``docs/dev/initiative-f-execution-plan.md`` — the T_F.3 task plan.

Execution-environment constraint (design §3.6):
    ``pipenv-resolver`` runs under the *target venv*'s Python interpreter,
    which may be older than the Python pipenv itself was installed under.
    pipenv currently supports CPython 3.10+ (``pyproject.toml`` ::
    ``requires-python = ">=3.10"``).  This module therefore restricts
    itself to stdlib idioms that import cleanly on 3.10:

    * ``@dataclass(frozen=True)`` from ``dataclasses``
    * ``from __future__ import annotations`` for forward refs
    * ``Optional`` / ``Sequence`` / ``Mapping`` / ``Union`` / ``Any`` from
      ``typing``

    Disallowed at module top level: ``typing.Self`` (3.11+), ``tomllib``
    (3.11+), 3.11+-only ``match`` patterns, any vendored dependency, any
    ``from pipenv.patched.pip._internal`` import.  Pip-internal types
    (notably ``InstallRequirement``) appear only inside the body of
    :meth:`LockedRequirement.from_install_requirement`, where the
    subprocess is the only caller and the patched-pip path is available.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Mapping, Sequence, Union

# Bump on any breaking field rename or semantics change.  Additive fields
# with safe defaults do NOT bump (per plan Q8 / design §5 item 2).
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Source-side types (request)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageSpecs:
    """Typed replacement for the legacy constraints-tempfile format.

    Today: ``<name>, <pip-line>`` lines split with ``str.split(",", 1)``
    (``pipenv/resolver/main.py``::handle_parsed_args + F.1 §8 row 9 —
    flagged as fragile because PEP 508 markers can contain commas).

    Replacement: a typed ``dict`` mapping package name to the full
    pip-install-argument string.  Commas in markers no longer matter.
    """

    specs: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Source:
    """One Pipfile ``[[source]]`` block, post-mirror-substitution.

    Replaces the in-child Pipfile re-read at the legacy resolver
    (F.1 §8 row 5, §9 decision 10).  The parent substitutes
    ``PIPENV_PYPI_MIRROR`` before serializing; the child consumes the
    final list verbatim.
    """

    name: str
    url: str
    verify_ssl: bool = True


@dataclass(frozen=True)
class ResolverOptions:
    """Boolean / verbosity options that today are argv flags.

    Today: ``--pre`` / ``--clear`` / ``--system`` / ``--verbose``
    (F.1 §3.1).  Verbosity translates on the child side to the
    ``PIPENV_VERBOSITY`` / ``PIP_RESOLVER_DEBUG`` pip env-vars after
    receipt — those env-vars are pip's own, not part of *this* protocol.
    """

    pre: bool = False
    clear: bool = False
    system: bool = False
    verbose: bool = False


@dataclass(frozen=True)
class ResolvedDeps:
    """Already-resolved default-category deps used to constrain non-default
    categories.  Replaces the ``--resolved-default-deps-file`` tempfile.

    Tracks gh-4665 / gh-4473 (F.1 §3.1, §8 row 8).
    """

    entries: Sequence[LockedRequirement] = ()


@dataclass(frozen=True)
class RequestMetadata:
    """Caller-side context for the resolver request.

    ``deadline_seconds`` carries the caller-provided timeout budget for
    the subprocess request and is stamped onto requests as metadata for
    timeout enforcement in the resolver flow.
    """

    pipenv_version: str = ""
    parent_pid: int = 0
    deadline_seconds: float | None = None


# ---------------------------------------------------------------------------
# Result-side discriminated union (response)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VCSPin:
    """VCS pin: backend + URL + ref + optional subdirectory."""

    backend: str  # One of {"git", "hg", "svn", "bzr"}.  F.1 §5.2.
    url: str
    ref: str | None = None
    subdirectory: str | None = None


@dataclass(frozen=True)
class LockedRequirement:
    """The canonical lockfile-entry shape (design §3.3).

    Each field corresponds 1:1 to a key in today's
    ``Entry.get_cleaned_dict`` output (F.1 §5.2 table).  VCS-vs-non-VCS
    semantics are encoded as ``Optional[VCSPin]``; the "either VCS or
    version, never both" invariant from F.1 §5.2 is enforced by
    ``__post_init__``.

    Replaces both legacy formatters:

    * ``Entry.get_cleaned_dict`` (legacy ``pipenv/resolver.py:288-320``,
      now ``pipenv/resolver/main.py``) — subprocess-side dict-cleaner
    * ``format_requirement_for_lockfile``
      (``pipenv/utils/locking.py:46-160``) — parent-side richer formatter

    The single canonical constructor :meth:`from_install_requirement`
    absorbs both.
    """

    name: str
    version: str | None = None
    extras: Sequence[str] = ()
    markers: str | None = None
    hashes: Sequence[str] = ()
    index: str | None = None
    vcs: VCSPin | None = None
    file: str | None = None
    path: str | None = None
    editable: bool = False
    no_binary: bool = False
    subdirectory: str | None = None

    def __post_init__(self) -> None:
        # Wire-shape invariant: every entry has at least one of {version,
        # vcs, file, path}.  Bare-name entries are rejected at the
        # boundary.  Mirrors F.1 §5.2.
        if (
            self.vcs is None
            and self.version is None
            and self.file is None
            and self.path is None
        ):
            raise ValueError(
                f"LockedRequirement {self.name!r} carries no version, vcs, file, or path"
            )
        # Mutual exclusion: version + vcs combo is meaningless on the
        # wire (a VCS pin is its own version).  Enforced explicitly per
        # design §3.3.
        if self.vcs is not None and self.version is not None:
            raise ValueError(
                f"LockedRequirement {self.name!r}: vcs and version are mutually exclusive (F.1 §5.2)"
            )

    # -----------------------------------------------------------------
    # Canonical constructor (design §3.3 + §6; plan A1 deliverable)
    # -----------------------------------------------------------------

    @classmethod
    def from_install_requirement(
        cls,
        req: Any,  # pip's InstallRequirement; typed Any to avoid module-level import
        *,
        sources_lookup: Mapping[str, str] | None = None,
        markers_lookup: Mapping[str, str] | None = None,
        pipfile_entry: Mapping[str, Any] | None = None,
        hashes: Sequence[str] | None = None,
    ) -> LockedRequirement:
        """Build a ``LockedRequirement`` from a pip ``InstallRequirement``.

        This constructor is the **single fold target** for the two legacy
        formatters that today produce overlapping lockfile-entry dicts.
        Behaviour is preserved from both source paths:

        * ``Entry.get_cleaned_dict`` (legacy ``pipenv/resolver.py:288-320``;
          now ``pipenv/resolver/main.py``) — supplies the
          ``_clean_version`` normalization at lines 213-224 (the
          ``any``/``<any>``/``*`` collapse, the ``==`` auto-prefix) and
          the ``_clean_markers`` collapse at lines 226-245 (``sys_platform``
          / ``python_version`` / ``os_name`` / ``platform_machine`` /
          ``markers`` keys joined with ``" and "``).
        * ``format_requirement_for_lockfile``
          (``pipenv/utils/locking.py:46-160``) — supplies the richer
          parent-side behaviours:

            - File / path Pipfile-override at locking.py:142-155
              (Pipfile-declared ``file`` or ``path`` wins; strips
              ``version`` and ``index`` from the entry)
            - Cached-wheel guard at locking.py:91-102 (``file://`` link
              is recorded only when the Pipfile entry actually declares
              the dep as ``file``/``path``)
            - PEP-508 direct-URL ``pkg @ file://...`` at locking.py:103-110
              (``req.req.url`` is set ⇒ record the file)
            - HTTP/HTTPS direct URL at locking.py:111-117 (same idea for
              ``http(s)`` schemes)
            - VCS handling at locking.py:60-83 (``link.is_vcs`` ⇒ build
              ``VCSPin``; subdirectory from Pipfile or link fragment;
              ref via ``determine_vcs_revision_hash``)
            - ``merge_markers`` at locking.py:121-131 (req-markers +
              ``markers_lookup`` + Pipfile ``markers`` + Pipfile
              ``os_name``, all AND-merged)
            - Index lookup at locking.py:118-120
            - ``no_binary`` propagation at locking.py:156-158
            - Hashes pass-through at locking.py:138-140 (sorted)

        The constructor lives at the wire boundary so a future "second
        backend" (uv, etc.; see design §6a) can ship as a sibling
        constructor without touching the schema fields themselves.

        Arguments
        ---------
        req:
            A pip ``InstallRequirement``.  Typed ``Any`` here to keep
            the schema module importable on target Pythons that don't
            have pipenv's patched-pip on ``sys.path`` (design §3.6
            constraint #3).  In practice the caller is always the
            subprocess, which DOES have ``pipenv.patched.pip`` available.
        sources_lookup:
            Maps ``name -> index_name`` for the ``entry["index"]`` field
            (replaces the parent-side ``index_lookup`` argument of
            ``format_requirement_for_lockfile``).
        markers_lookup:
            Maps ``name -> extra_marker_string`` for AND-merging into
            the resulting markers (parent-side cross-package context).
        pipfile_entry:
            The dep's entry in the Pipfile, if any.  Drives the
            file/path/no_binary/editable overrides.
        hashes:
            Optional pre-computed hashes to attach; sorted before
            storage to keep the wire output deterministic.
        """
        # Local imports — pip-internals are NOT importable at schema
        # module top level (design §3.6 constraint #3).  Inside this
        # method the subprocess context guarantees the patched-pip
        # surface is on sys.path.
        from pipenv.utils.constants import VCS_LIST
        from pipenv.utils.dependencies import (
            determine_vcs_revision_hash,
            normalize_vcs_url,
            pep423_name,
            translate_markers,
        )

        name = pep423_name(req.name)
        sources_lookup = sources_lookup or {}
        markers_lookup = markers_lookup or {}
        pipfile_entry = pipfile_entry or {}

        # Mutable scratch dict — we mirror the locking.py flow exactly,
        # then transform the result into our typed shape at the bottom.
        entry: dict = {"name": name}

        # ---- VCS branch (locking.py:60-83) ----
        is_vcs_dep = next(
            iter([v for v in VCS_LIST if v in pipfile_entry]), None
        )
        if getattr(req, "link", None) is not None and getattr(req.link, "is_vcs", False):
            is_vcs_dep = True

        vcs_pin: VCSPin | None = None
        if is_vcs_dep:
            if req.link is not None and getattr(req.link, "is_vcs", False):
                link = req.link
            else:
                link = req.cached_wheel_source_link
            vcs_backend = link.scheme.split("+", 1)[0]
            vcs_url, _ = normalize_vcs_url(link.url)
            vcs_sub: str | None = None
            if pipfile_entry.get("subdirectory"):
                vcs_sub = pipfile_entry["subdirectory"]
            elif getattr(link, "subdirectory_fragment", None):
                vcs_sub = link.subdirectory_fragment
            vcs_ref = determine_vcs_revision_hash(
                req, vcs_backend, pipfile_entry.get("ref")
            )
            vcs_pin = VCSPin(
                backend=vcs_backend,
                url=vcs_url,
                ref=vcs_ref or None,
                subdirectory=vcs_sub,
            )
            entry[vcs_backend] = vcs_url
            if vcs_sub:
                entry["subdirectory"] = vcs_sub
            if vcs_ref:
                entry["ref"] = vcs_ref
        else:
            # ---- Non-VCS branch (locking.py:84-117) ----
            if getattr(req, "req", None) and getattr(req.req, "specifier", None):
                entry["version"] = str(req.req.specifier)
            elif getattr(req, "specifier", None):
                entry["version"] = str(req.specifier)
            if getattr(req, "link", None) is not None:
                link = req.link
                if getattr(link, "is_file", False):
                    # Cached-wheel guard (locking.py:91-102): record the
                    # file ONLY when the Pipfile explicitly declares
                    # this as a file/path dep — otherwise pip's local
                    # wheel cache path would bleed into the lockfile.
                    if isinstance(pipfile_entry, Mapping) and (
                        pipfile_entry.get("file") or pipfile_entry.get("path")
                    ):
                        entry["file"] = link.url
                    elif (
                        getattr(req, "req", None)
                        and getattr(req.req, "url", None)
                        and str(req.req.url).startswith("file:")
                    ):
                        # PEP-508 transitive file:// dep
                        # (locking.py:103-110)
                        entry["file"] = link.url
                        entry.pop("version", None)
                        entry.pop("index", None)
                elif link.scheme in ("http", "https") and getattr(req, "req", None) and getattr(req.req, "url", None):
                    # HTTP/HTTPS direct URL (locking.py:111-117)
                    entry["file"] = link.url
                    entry.pop("version", None)
                    entry.pop("index", None)

        # ---- Index lookup (locking.py:118-120) ----
        if name in sources_lookup:
            entry["index"] = sources_lookup[name]

        # ---- Markers (locking.py:122-132) ----
        req_markers = getattr(req, "markers", None)
        if req_markers:
            entry["markers"] = str(req_markers)
        if name in markers_lookup:
            _merge_markers(entry, markers_lookup[name])
        if isinstance(pipfile_entry, Mapping):
            if "markers" in pipfile_entry:
                _merge_markers(entry, pipfile_entry["markers"])
            if "os_name" in pipfile_entry:
                _merge_markers(entry, f"os_name {pipfile_entry['os_name']}")

        # ---- Extras (locking.py:134-136) ----
        req_extras = getattr(req, "extras", None)
        extras_tuple: Sequence[str] = ()
        if req_extras:
            extras_tuple = tuple(sorted(req_extras))
            entry["extras"] = list(extras_tuple)

        # ---- Hashes (locking.py:138-140) ----
        hashes_tuple: Sequence[str] = ()
        if hashes:
            hashes_tuple = tuple(sorted(set(hashes)))
            entry["hashes"] = list(hashes_tuple)

        # ---- File / path Pipfile-override (locking.py:142-155) ----
        file_override: str | None = None
        path_override: str | None = None
        editable = False
        if isinstance(pipfile_entry, Mapping):
            if pipfile_entry.get("file"):
                file_override = pipfile_entry["file"]
                entry["file"] = file_override
                if pipfile_entry.get("editable"):
                    editable = bool(pipfile_entry["editable"])
                    entry["editable"] = editable
                entry.pop("version", None)
                entry.pop("index", None)
            elif pipfile_entry.get("path"):
                path_override = pipfile_entry["path"]
                entry["path"] = path_override
                if pipfile_entry.get("editable"):
                    editable = bool(pipfile_entry["editable"])
                    entry["editable"] = editable
                entry.pop("version", None)
                entry.pop("index", None)
            # ---- no_binary propagation (locking.py:156-158) ----
            no_binary = bool(pipfile_entry.get("no_binary"))
        else:
            no_binary = False

        entry = translate_markers(entry)

        # Now project the scratch dict back into typed fields.
        return cls(
            name=name,
            version=entry.get("version") if vcs_pin is None else None,
            extras=tuple(entry.get("extras", ())),
            markers=entry.get("markers"),
            hashes=tuple(entry.get("hashes", ())),
            index=entry.get("index"),
            vcs=vcs_pin,
            file=entry.get("file"),
            path=entry.get("path"),
            editable=bool(entry.get("editable", False)),
            no_binary=no_binary,
            subdirectory=(
                entry.get("subdirectory") if vcs_pin is None else None
            ),
        )

    # -----------------------------------------------------------------
    # JSON serialization
    # -----------------------------------------------------------------

    def to_json_dict(self) -> dict:
        """Return a deterministic JSON-ready dict.

        Drops fields that are None, empty-sequence, or default-False so
        the wire format matches today's pruned-dict shape (no key carries
        a meaningless null).
        """
        out: dict = {"name": self.name}
        if self.version is not None:
            out["version"] = self.version
        if self.extras:
            out["extras"] = sorted(self.extras)
        if self.markers is not None:
            out["markers"] = self.markers
        if self.hashes:
            out["hashes"] = sorted(self.hashes)
        if self.index is not None:
            out["index"] = self.index
        if self.vcs is not None:
            out["vcs"] = _vcs_pin_to_dict(self.vcs)
        if self.file is not None:
            out["file"] = self.file
        if self.path is not None:
            out["path"] = self.path
        if self.editable:
            out["editable"] = True
        if self.no_binary:
            out["no_binary"] = True
        if self.subdirectory is not None:
            out["subdirectory"] = self.subdirectory
        return out

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> LockedRequirement:
        vcs = data.get("vcs")
        vcs_pin = _vcs_pin_from_dict(vcs) if vcs is not None else None
        return cls(
            name=data["name"],
            version=data.get("version"),
            extras=tuple(data.get("extras", ())),
            markers=data.get("markers"),
            hashes=tuple(data.get("hashes", ())),
            index=data.get("index"),
            vcs=vcs_pin,
            file=data.get("file"),
            path=data.get("path"),
            editable=bool(data.get("editable", False)),
            no_binary=bool(data.get("no_binary", False)),
            subdirectory=data.get("subdirectory"),
        )

    @classmethod
    def from_lockfile_dict(cls, data: Mapping[str, Any]) -> LockedRequirement:
        """Inverse of :meth:`to_lockfile_dict`.

        Reconstructs a ``LockedRequirement`` from the flat top-level
        lockfile-entry dict shape (VCS backend as top-level key rather
        than the nested ``vcs`` object used by :meth:`to_json_dict`).
        Used by the C1 parity tests to round-trip the A1 golden
        snapshots through the typed schema.

        VCS backends are detected by membership in the canonical list
        ``{"git", "hg", "svn", "bzr"}``.  ``ref`` / ``subdirectory``
        attach to the resulting ``VCSPin`` when a VCS backend is present.
        """
        vcs_backends = ("git", "hg", "svn", "bzr")
        vcs_pin: VCSPin | None = None
        for backend in vcs_backends:
            if backend in data:
                vcs_pin = VCSPin(
                    backend=backend,
                    url=data[backend],
                    ref=data.get("ref"),
                    subdirectory=data.get("subdirectory"),
                )
                break
        return cls(
            name=data["name"],
            version=data.get("version") if vcs_pin is None else None,
            extras=tuple(data.get("extras", ())),
            markers=data.get("markers"),
            hashes=tuple(data.get("hashes", ())),
            index=data.get("index"),
            vcs=vcs_pin,
            file=data.get("file"),
            path=data.get("path"),
            editable=bool(data.get("editable", False)),
            no_binary=bool(data.get("no_binary", False)),
            subdirectory=(
                data.get("subdirectory") if vcs_pin is None else None
            ),
        )

    def to_lockfile_dict(self) -> dict:
        """Return the TOML-ready dict that ``prepare_lockfile`` consumes.

        Per design Q3, the schema module does NOT import Plette; the
        downstream lockfile writer consumes plain dicts.  T_F.3 Wave B3
        will replace ``format_requirement_for_lockfile``'s output dict
        with this method's output.
        """
        out = self.to_json_dict()
        # Lockfile-side flattening: VCSPin's three fields are flattened
        # to top-level keys (matches today's
        # ``Entry.get_cleaned_dict`` output where ``git`` / ``hg`` /
        # ``svn`` / ``bzr`` is a top-level key, not nested).
        if "vcs" in out:
            vcs = out.pop("vcs")
            out[vcs["backend"]] = vcs["url"]
            if vcs.get("ref"):
                out["ref"] = vcs["ref"]
            if vcs.get("subdirectory"):
                out["subdirectory"] = vcs["subdirectory"]
        return out


# ---------------------------------------------------------------------------
# Discriminated result variants (response.result.kind)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolverSuccess:
    """Resolution completed; lockfile entries follow."""

    kind: str  # Always "success".  Discriminator for JSON readers.
    locked: Sequence[LockedRequirement] = ()


@dataclass(frozen=True)
class ResolutionError:
    """The dependency set has no satisfying solution.

    Distinguishes user-actionable resolution failure from
    subprocess-internal failure.  Today these are conflated under
    "non-zero exit + stderr text" (F.1 §4.3, §5.4).
    """

    kind: str  # Always "resolution_error".
    conflicts: Sequence[ConflictRecord] = ()
    pip_message: str = ""


@dataclass(frozen=True)
class InternalError:
    """Subprocess hit an unexpected internal error (not a resolution
    failure).  The parent typically also sees a non-zero exit and
    stderr traceback in this case; the structured payload is
    best-effort.
    """

    kind: str  # Always "internal_error".
    message: str = ""
    traceback: str | None = None


ResolverResult = Union[ResolverSuccess, ResolutionError, InternalError]


@dataclass(frozen=True)
class ConflictRecord:
    """One row of pip's 'The conflict is caused by' table.

    Today: free text only (F.1 §5.4).  Structured here so the parent
    can format it without re-parsing pip's English.
    """

    package: str
    version: str
    requires: str


@dataclass(frozen=True)
class Diagnostics:
    """Side-channel info: warnings, timing, source-substitution log.

    ``resolver_log`` is reserved-but-empty in T_F.3 per design Q9 —
    stderr remains the user-facing channel.
    """

    warnings: Sequence[str] = ()
    elapsed_seconds: float = 0.0
    pip_version: str = ""
    resolver_log: Sequence[str] = ()


# ---------------------------------------------------------------------------
# Top-level envelopes (design §3.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolverRequest:
    """The single input to a pipenv-resolver subprocess invocation.

    Replaces the current argv + env-var + constraints-tempfile +
    resolved-default-deps-tempfile cocktail (F.1 §3.1–3.2).
    """

    schema_version: int
    category: str
    packages: PackageSpecs
    options: ResolverOptions
    sources: Sequence[Source]
    python_marker_override: str | None = None
    extra_pip_args: Sequence[str] = ()
    resolved_default_deps: ResolvedDeps | None = None
    metadata: RequestMetadata = field(default_factory=RequestMetadata)

    def to_json_dict(self) -> dict:
        """Return a deterministic JSON-ready dict (no None values)."""
        out: dict = {
            "schema_version": self.schema_version,
            "category": self.category,
            "packages": {"specs": dict(sorted(self.packages.specs.items()))},
            "options": _dataclass_to_dict(self.options),
            "sources": [_dataclass_to_dict(s) for s in self.sources],
        }
        if self.python_marker_override is not None:
            out["python_marker_override"] = self.python_marker_override
        if self.extra_pip_args:
            out["extra_pip_args"] = list(self.extra_pip_args)
        if self.resolved_default_deps is not None:
            out["resolved_default_deps"] = {
                "entries": [e.to_json_dict() for e in self.resolved_default_deps.entries],
            }
        # Metadata is always serialized (it's tiny + all-defaults) so the
        # wire shape is stable across "did the caller bother to set
        # metadata" branches.  Suppress only if it's exactly default.
        meta_dict = _dataclass_to_dict(self.metadata)
        # Drop None-valued keys inside metadata for determinism.
        meta_dict = {k: v for k, v in meta_dict.items() if v is not None}
        if meta_dict != _dataclass_to_dict(RequestMetadata()):
            # Filter Nones from default too so the comparison is fair
            default_meta = {
                k: v
                for k, v in _dataclass_to_dict(RequestMetadata()).items()
                if v is not None
            }
            if meta_dict != default_meta:
                out["metadata"] = meta_dict
        return out

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> ResolverRequest:
        """Two-stage parse: validate ``schema_version`` BEFORE dispatching
        on the rest of the payload (design §3.6 / plan Risk #6).
        """
        sv = data.get("schema_version")
        if sv != SCHEMA_VERSION:
            raise ValueError(
                f"schema version mismatch: payload schema_version={sv!r} "
                f"but this pipenv-resolver expects {SCHEMA_VERSION!r}"
            )
        packages_data = data["packages"]
        packages = PackageSpecs(specs=dict(packages_data.get("specs", {})))
        options = ResolverOptions(**data["options"])
        sources = tuple(Source(**s) for s in data.get("sources", ()))
        resolved = data.get("resolved_default_deps")
        if resolved is not None:
            resolved_default_deps: ResolvedDeps | None = ResolvedDeps(
                entries=tuple(
                    LockedRequirement.from_json_dict(e) for e in resolved.get("entries", ())
                )
            )
        else:
            resolved_default_deps = None
        metadata_data = data.get("metadata")
        if metadata_data is not None:
            metadata = RequestMetadata(**metadata_data)
        else:
            metadata = RequestMetadata()
        return cls(
            schema_version=sv,
            category=data["category"],
            packages=packages,
            options=options,
            sources=sources,
            python_marker_override=data.get("python_marker_override"),
            extra_pip_args=tuple(data.get("extra_pip_args", ())),
            resolved_default_deps=resolved_default_deps,
            metadata=metadata,
        )


@dataclass(frozen=True)
class ResolverResponse:
    """The single output written by pipenv-resolver to ``--response-file``.

    Replaces the current top-level ``list[dict]`` payload (F.1 §5.1).
    """

    schema_version: int
    result: ResolverResult
    diagnostics: Diagnostics = field(default_factory=Diagnostics)

    def to_json_dict(self) -> dict:
        out: dict = {
            "schema_version": self.schema_version,
            "result": _result_to_dict(self.result),
        }
        diag_dict = _dataclass_to_dict(self.diagnostics)
        # Always include diagnostics (the empty-default case still has
        # ``elapsed_seconds`` and ``pip_version`` as part of the wire).
        # Filter None values for determinism (no field is currently
        # Optional in Diagnostics but future-proof).
        diag_dict = {k: v for k, v in diag_dict.items() if v is not None}
        default_diag = {
            k: v
            for k, v in _dataclass_to_dict(Diagnostics()).items()
            if v is not None
        }
        if diag_dict != default_diag:
            out["diagnostics"] = diag_dict
        return out

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> ResolverResponse:
        """Two-stage parse: validate ``schema_version`` BEFORE attempting
        to dispatch on ``result.kind`` (design §3.6 / plan Risk #6).
        """
        sv = data.get("schema_version")
        if sv != SCHEMA_VERSION:
            raise ValueError(
                f"schema version mismatch: payload schema_version={sv!r} "
                f"but this pipenv expects {SCHEMA_VERSION!r}"
            )
        result = _result_from_dict(data["result"])
        diag_data = data.get("diagnostics")
        if diag_data is not None:
            diagnostics = Diagnostics(
                warnings=tuple(diag_data.get("warnings", ())),
                elapsed_seconds=float(diag_data.get("elapsed_seconds", 0.0)),
                pip_version=diag_data.get("pip_version", ""),
                resolver_log=tuple(diag_data.get("resolver_log", ())),
            )
        else:
            diagnostics = Diagnostics()
        return cls(
            schema_version=sv,
            result=result,
            diagnostics=diagnostics,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _dataclass_to_dict(obj: Any) -> dict:
    """Shallow dataclass-to-dict (NO recursion through dataclass-fields).

    We avoid ``dataclasses.asdict`` because it recurses through nested
    dataclasses, which breaks the discriminated-union pattern (the
    ``result.kind`` discriminator gets eaten).  Each parent does its own
    nested serialization explicitly.
    """
    return {f.name: getattr(obj, f.name) for f in fields(obj)}


def _vcs_pin_to_dict(pin: VCSPin) -> dict:
    out: dict = {"backend": pin.backend, "url": pin.url}
    if pin.ref is not None:
        out["ref"] = pin.ref
    if pin.subdirectory is not None:
        out["subdirectory"] = pin.subdirectory
    return out


def _vcs_pin_from_dict(data: Mapping[str, Any]) -> VCSPin:
    return VCSPin(
        backend=data["backend"],
        url=data["url"],
        ref=data.get("ref"),
        subdirectory=data.get("subdirectory"),
    )


def _result_to_dict(result: ResolverResult) -> dict:
    if isinstance(result, ResolverSuccess):
        return {
            "kind": "success",
            "locked": [lr.to_json_dict() for lr in result.locked],
        }
    if isinstance(result, ResolutionError):
        return {
            "kind": "resolution_error",
            "conflicts": [_dataclass_to_dict(c) for c in result.conflicts],
            "pip_message": result.pip_message,
        }
    if isinstance(result, InternalError):
        out: dict = {"kind": "internal_error", "message": result.message}
        if result.traceback is not None:
            out["traceback"] = result.traceback
        return out
    raise TypeError(f"unknown ResolverResult variant: {type(result).__name__}")


def _result_from_dict(data: Mapping[str, Any]) -> ResolverResult:
    if not isinstance(data, Mapping):
        raise ValueError(
            f"result must be a mapping, got {type(data).__name__}"
        )
    kind = data.get("kind")
    if kind == "success":
        return ResolverSuccess(
            kind="success",
            locked=tuple(
                LockedRequirement.from_json_dict(d) for d in data.get("locked", ())
            ),
        )
    if kind == "resolution_error":
        return ResolutionError(
            kind="resolution_error",
            conflicts=tuple(
                ConflictRecord(**c) for c in data.get("conflicts", ())
            ),
            pip_message=data.get("pip_message", ""),
        )
    if kind == "internal_error":
        return InternalError(
            kind="internal_error",
            message=data.get("message", ""),
            traceback=data.get("traceback"),
        )
    raise ValueError(f"unknown result kind: {kind!r}")


def _merge_markers(entry: dict, markers: Any) -> None:
    """Mirror of :func:`pipenv.utils.locking.merge_markers`.

    Duplicated here (rather than imported) because the schema module
    must not depend on ``pipenv/utils/locking.py`` — that file is Wave
    B3's territory and gets gutted during B3.  Once B3 lands,
    ``locking.merge_markers`` can call this function instead.
    """
    if not isinstance(markers, list):
        markers = [markers]
    for marker in markers:
        if not isinstance(marker, str):
            marker = str(marker)
        if "markers" not in entry:
            entry["markers"] = marker
        elif marker not in entry["markers"]:
            entry["markers"] = f"({entry['markers']}) and ({marker})"


__all__ = [
    "SCHEMA_VERSION",
    "ConflictRecord",
    "Diagnostics",
    "InternalError",
    "LockedRequirement",
    "PackageSpecs",
    "RequestMetadata",
    "ResolutionError",
    "ResolvedDeps",
    "ResolverOptions",
    "ResolverRequest",
    "ResolverResponse",
    "ResolverResult",
    "ResolverSuccess",
    "Source",
    "VCSPin",
]
