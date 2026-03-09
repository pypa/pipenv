"""uv lock-based resolver integration for pipenv.

Uses ``uv lock`` (native project-based resolution) instead of ``uv pip compile``
for dependency resolution, providing richer structured data including per-package
source registry, structural extras info, and environment markers.

Activated via ``PIPENV_RESOLVER=uv-lock``.  The dispatcher functions in
``pipenv.utils.resolver`` and ``pipenv.utils.pip`` call into this module
based on the ``PIPENV_RESOLVER`` environment variable.  The installer side
is handled by ``pipenv.uv.uv_pip_install_deps``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, TypedDict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TypedDicts for uv.lock parsing
# ---------------------------------------------------------------------------


class UvLockSource(TypedDict, total=False):
    registry: str
    virtual: str
    git: str
    editable: str
    url: str
    subdirectory: str


UvLockSdist = TypedDict(
    "UvLockSdist",
    {
        "url": str,
        "hash": str,
        "size": int,
        "upload-time": str,
    },
    total=False,
)

UvLockWheel = TypedDict(
    "UvLockWheel",
    {
        "url": str,
        "hash": str,
        "size": int,
        "upload-time": str,
    },
    total=False,
)


class UvLockDependency(TypedDict, total=False):
    name: str
    version: str
    marker: str
    extra: list[str]
    source: UvLockSource


UvLockPackage = TypedDict(
    "UvLockPackage",
    {
        "name": str,
        "version": str,
        "source": UvLockSource,
        "dependencies": list[UvLockDependency],
        "optional-dependencies": dict[str, list[UvLockDependency]],
        "sdist": UvLockSdist,
        "wheels": list[UvLockWheel],
        "resolution-markers": list[str],
    },
    total=False,
)

UvLock = TypedDict(
    "UvLock",
    {
        "version": int,
        "revision": int,
        "requires-python": str,
        "package": list[UvLockPackage],
        "resolution-markers": list[str],
    },
    total=False,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _url_matches(url1: str, url2: str) -> bool:
    """Compare two URLs ignoring trailing slashes and scheme differences.

    :param url1: First URL
    :param url2: Second URL
    :return: True if the URLs point to the same location
    """
    if not url1 or not url2:
        return False
    # Normalize: strip trailing slashes, lowercase
    u1 = url1.rstrip("/").lower()
    u2 = url2.rstrip("/").lower()
    if u1 == u2:
        return True
    # Try comparing just host+path (ignore scheme http vs https)
    p1 = urlparse(u1)
    p2 = urlparse(u2)
    return p1.netloc == p2.netloc and p1.path.rstrip("/") == p2.path.rstrip("/")


def _source_url_to_index_name(
    registry_url: str, project_sources: list[dict[str, Any]]
) -> str | None:
    """Map a uv.lock registry URL to a Pipfile source name.

    :param registry_url: The ``source.registry`` URL from a uv.lock package
    :param project_sources: Result of ``project.pipfile_sources()``
    :return: The source name, or None if no match found
    """
    for source in project_sources:
        if _url_matches(source.get("url", ""), registry_url):
            return source.get("name")
    return None


def _normalize_marker(marker_str: str) -> str:
    """Normalize ``python_full_version`` to ``python_version`` for simple comparisons.

    UV uses ``python_full_version`` where pip uses ``python_version``.  For
    simple comparisons like ``>= '3.6'`` (no micro part, no wildcard), the two
    are semantically equivalent, so we normalize for compatibility.

    :param marker_str: A PEP 508 marker string
    :return: The normalized marker string
    """
    return re.sub(
        r"python_full_version\s*(>=|<=|>|<|!=)\s*([\"'])(\d+\.\d+)\2",
        lambda m: f"python_version {m.group(1)} {m.group(2)}{m.group(3)}{m.group(2)}",
        marker_str,
    )


# ---------------------------------------------------------------------------
# Pipfile -> pyproject.toml translation
# ---------------------------------------------------------------------------


def _pipfile_entry_to_pep508(name: str, entry: str | dict[str, Any]) -> str:
    """Convert a single Pipfile entry to a PEP 508 dependency string.

    Uses :class:`packaging.requirements.Requirement` for normalization,
    ensuring valid PEP 508 output with consistent extras ordering and
    marker quoting.

    :param name: Package name
    :param entry: Pipfile value — either ``"*"`` / ``">=1.0"`` or a dict
    :return: Normalized PEP 508 string suitable for ``[project.dependencies]``
    """
    from pipenv.patched.pip._vendor.packaging.requirements import Requirement

    if isinstance(entry, str):
        if entry == "*":
            return str(Requirement(name))
        return str(Requirement(f"{name}{entry}"))

    # Dict entry
    version = entry.get("version", "*")
    extras = entry.get("extras", [])
    markers_str = entry.get("markers", "")

    # Build extras portion
    extras_str = f"[{','.join(extras)}]" if extras else ""

    # Build version portion
    version_str = version if version and version != "*" else ""

    # Build markers from individual marker keys (PEP 508 environment markers)
    _marker_keys = {
        "os_name",
        "sys_platform",
        "platform_machine",
        "platform_python_implementation",
        "platform_release",
        "platform_system",
        "platform_version",
        "python_version",
        "python_full_version",
        "implementation_name",
        "implementation_version",
    }
    marker_parts: list[str] = []
    for key in sorted(_marker_keys):
        if key in entry:
            marker_parts.append(f"{key} {entry[key]}")
    if markers_str:
        marker_parts.append(markers_str)

    marker_combined = " and ".join(marker_parts) if marker_parts else ""

    # Assemble and normalize through packaging.Requirement
    req_str = f"{name}{extras_str}{version_str}"
    if marker_combined:
        req_str += f"; {marker_combined}"

    return str(Requirement(req_str))


def _pipfile_entry_to_uv_source(
    name: str, entry: str | dict[str, Any]
) -> dict[str, Any] | None:
    """Convert a Pipfile entry to a ``[tool.uv.sources]`` entry if needed.

    :param name: Package name
    :param entry: Pipfile value
    :return: A dict for ``[tool.uv.sources.<name>]``, or None if not needed
    """
    if isinstance(entry, str):
        return None

    # Index-restricted package
    if entry.get("index"):
        return {"index": entry["index"]}

    # Git dependency
    if entry.get("git"):
        source: dict[str, Any] = {"git": entry["git"]}
        if entry.get("ref"):
            source["rev"] = entry["ref"]
        if entry.get("subdirectory"):
            source["subdirectory"] = entry["subdirectory"]
        return source

    # Path / editable dependency
    if entry.get("path"):
        source = {"path": entry["path"]}
        if entry.get("editable"):
            source["editable"] = True
        return source

    # File / URL dependency
    if entry.get("file"):
        url = entry["file"]
        if url.startswith(("http://", "https://")):
            return {"url": url}
        # Local file path
        return {"path": url}

    return None


def _build_pyproject_toml(
    project: Any,
    category: str,
    pre: bool = False,
) -> str:
    """Build a temporary ``pyproject.toml`` for ``uv lock`` resolution.

    Uses :mod:`tomlkit` for proper TOML generation with escaping, inline
    tables for ``[tool.uv.sources]`` entries, and array-of-tables for
    ``[[tool.uv.index]]``.

    :param project: The pipenv Project instance
    :param category: The Pipfile category being resolved (e.g. "default", "develop")
    :param pre: Whether to allow pre-release versions
    :return: The pyproject.toml content as a string
    """
    from pipenv.vendor import tomlkit

    # Get dependencies for the target category
    if category == "default":
        deps = project.packages
    elif category == "develop":
        deps = project.dev_packages
    else:
        deps = project.parsed_pipfile.get(category, {})

    # Build PEP 508 dependency strings and uv sources
    pep508_deps: list[str] = []
    uv_sources_dict: dict[str, dict[str, Any]] = {}

    for name, entry in deps.items():
        pep508_deps.append(_pipfile_entry_to_pep508(name, entry))
        uv_source = _pipfile_entry_to_uv_source(name, entry)
        if uv_source:
            uv_sources_dict[name] = uv_source

    # Get requires-python from Pipfile
    requires_python = project.required_python_version or ""
    if requires_python and not any(
        op in requires_python for op in (">=", "<=", "==", "!=", ">", "<", "~=")
    ):
        # Bare version like "3.10" — convert to ">= 3.10"
        requires_python = f">= {requires_python}"

    # Get cross-category constraints for non-default categories
    constraint_deps: list[str] = []
    if category != "default" and project.settings.get("use_default_constraints", True):
        from pipenv.utils.dependencies import get_constraints_from_deps

        constraints = get_constraints_from_deps(project.packages)
        constraint_deps = sorted(constraints)

    # Get sources
    sources = project.pipfile_sources()

    # -- Build TOML document with tomlkit --
    doc = tomlkit.document()

    # [project]
    proj_table = tomlkit.table()
    proj_table.add("name", "pipenv-resolver")
    proj_table.add("version", "0.0.0")
    if requires_python:
        proj_table.add("requires-python", requires_python)
    dep_array = tomlkit.array()
    dep_array.multiline(True)
    for d in pep508_deps:
        dep_array.append(d)
    proj_table.add("dependencies", dep_array)
    doc.add("project", proj_table)

    # [tool.uv] — may contain constraint-dependencies, prerelease, sources, indexes
    tool = tomlkit.table(is_super_table=True)
    uv_table = tomlkit.table()
    has_uv = False

    if constraint_deps:
        c_array = tomlkit.array()
        c_array.multiline(True)
        for c in constraint_deps:
            c_array.append(c)
        uv_table.add("constraint-dependencies", c_array)
        has_uv = True

    if pre:
        uv_table.add("prerelease", "allow")
        has_uv = True

    # [tool.uv.sources] — values must be inline tables
    if uv_sources_dict:
        sources_table = tomlkit.table()
        for pkg_name, src in uv_sources_dict.items():
            it = tomlkit.inline_table()
            for k, v in src.items():
                it.append(k, v)
            sources_table.append(pkg_name, it)
        uv_table.add("sources", sources_table)
        has_uv = True

    # [[tool.uv.index]]
    if sources:
        indexes = tomlkit.aot()
        for i, source in enumerate(sources):
            idx = tomlkit.table()
            idx.add("name", source.get("name", f"source-{i}"))
            idx.add("url", source["url"])
            if i == 0:
                idx.add("default", True)
            indexes.append(idx)
        uv_table.add("index", indexes)
        has_uv = True

    if has_uv:
        tool.add("uv", uv_table)
        doc.add("tool", tool)

    return tomlkit.dumps(doc)


def _build_uv_lock_cmd(
    project: Any,
    pyproject_dir: str,
    pre: bool = False,
) -> list[str]:
    """Build the ``uv lock`` command line.

    :param project: The pipenv Project instance
    :param pyproject_dir: Path to the temp directory containing pyproject.toml
    :param pre: Whether to allow pre-release versions
    :return: Command list suitable for subprocess
    """
    from pipenv.uv import find_uv_bin

    uv_bin = find_uv_bin()

    cmd = [
        uv_bin,
        "lock",
        f"--project={pyproject_dir}",
        "--index-strategy=unsafe-best-match",
    ]

    if pre:
        cmd.append("--prerelease=allow")

    # Add --allow-insecure-host for sources with verify_ssl: false
    sources = project.pipfile_sources()
    for source in sources:
        if not source.get("verify_ssl", True):
            parsed_url = urlparse(source["url"])
            host = parsed_url.hostname or ""
            port = parsed_url.port
            if port:
                cmd.append(f"--allow-insecure-host={host}:{port}")
            else:
                cmd.append(f"--allow-insecure-host={host}")

    return cmd


# ---------------------------------------------------------------------------
# uv.lock parsing
# ---------------------------------------------------------------------------


def _collect_hashes(pkg: UvLockPackage) -> list[str]:
    """Extract and sort hashes from a uv.lock package entry.

    :param pkg: A package entry from uv.lock
    :return: Sorted list of hash strings like ``"sha256:abcdef..."``
    """
    hashes: set[str] = set()

    sdist = pkg.get("sdist")
    if sdist and sdist.get("hash"):
        hashes.add(sdist["hash"])

    for wheel in pkg.get("wheels", []):
        if wheel.get("hash"):
            hashes.add(wheel["hash"])

    return sorted(hashes)


def _find_extras_deps(
    packages: list[UvLockPackage],
) -> dict[str, dict[str, list[str]]]:
    """Build a map of extras-only dependencies from uv.lock packages.

    Examines ``[package.optional-dependencies]`` sections to find packages
    that are transitive dependencies of extras.

    :param packages: The list of ``[[package]]`` entries from uv.lock
    :return: Dict of ``{parent_canonical_name: {extra_name: [dep_canonical_names]}}``
    """
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    result: dict[str, dict[str, list[str]]] = {}
    for pkg in packages:
        opt_deps = pkg.get("optional-dependencies")
        if not opt_deps:
            continue
        parent = canonicalize_name(pkg["name"])
        result[parent] = {}
        for extra_name, dep_list in opt_deps.items():
            result[parent][extra_name] = [canonicalize_name(d["name"]) for d in dep_list]
    return result


def _get_root_dep_markers(
    packages: list[UvLockPackage],
) -> dict[str, str]:
    """Extract markers from the root (virtual) package's dependency references.

    These are the combined markers (user markers + metadata markers) that UV
    produces for top-level dependencies.

    :param packages: The list of ``[[package]]`` entries from uv.lock
    :return: Dict of ``{canonical_dep_name: marker_string}``
    """
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    for pkg in packages:
        source = pkg.get("source", {})
        if source.get("virtual") == ".":
            markers: dict[str, str] = {}
            for dep in pkg.get("dependencies", []):
                marker = dep.get("marker", "")
                if marker:
                    cn = canonicalize_name(dep["name"])
                    markers[cn] = marker
            return markers
    return {}


def _get_root_dep_extras(
    packages: list[UvLockPackage],
) -> dict[str, list[str]]:
    """Extract extras from the root (virtual) package's dependency references.

    :param packages: The list of ``[[package]]`` entries from uv.lock
    :return: Dict of ``{canonical_dep_name: [extra_names]}``
    """
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    for pkg in packages:
        source = pkg.get("source", {})
        if source.get("virtual") == ".":
            extras_map: dict[str, list[str]] = {}
            for dep in pkg.get("dependencies", []):
                extras = dep.get("extra")
                if extras:
                    cn = canonicalize_name(dep["name"])
                    extras_map[cn] = extras
            return extras_map
    return {}


def _parse_uv_lock(
    lock_path: str,
    project: Any,
    category: str,
) -> list[dict[str, Any]]:
    """Parse a ``uv.lock`` file into the JSON format expected by ``prepare_lockfile``.

    :param lock_path: Path to the ``uv.lock`` file
    :param project: The pipenv Project instance
    :param category: The Pipfile category being resolved
    :return: A list of dicts, each representing a resolved package
    """
    if sys.version_info < (3, 11):
        import tomli as tomllib
    else:
        import tomllib

    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
    from pipenv.uv import _get_pipfile_index_for_deps, _get_pipfile_markers

    with open(lock_path, "rb") as f:
        lock_data: UvLock = tomllib.load(f)  # type: ignore[assignment]

    packages: list[UvLockPackage] = lock_data.get("package", [])
    sources = project.pipfile_sources()

    # Build extras dependency map
    extras_deps = _find_extras_deps(packages)
    # Get root dependency markers and extras
    root_dep_markers = _get_root_dep_markers(packages)
    root_dep_extras = _get_root_dep_extras(packages)
    # Get user-specified markers from Pipfile
    pipfile_markers = _get_pipfile_markers(project, category)
    # Get index assignments from Pipfile
    pipfile_indexes = _get_pipfile_index_for_deps(project, category)

    # Determine which packages are *only* needed via extras
    # These are packages that appear in optional-dependencies but NOT in
    # regular dependencies of any package requested with that extra
    extras_only_pkgs: dict[str, str] = {}  # {canonical_name: extra_name}
    for parent_name, extra_map in extras_deps.items():
        # Check if the root requested this parent with extras
        root_extras = root_dep_extras.get(parent_name, [])
        for extra_name, dep_names in extra_map.items():
            if extra_name in root_extras:
                for dep_name in dep_names:
                    extras_only_pkgs[dep_name] = extra_name

    # Collect all regular (non-extras) transitive dependencies
    # to exclude them from extras_only_pkgs
    regular_deps: set[str] = set()
    for pkg in packages:
        source = pkg.get("source", {})
        if source.get("virtual") == ".":
            # Root package — its regular deps are in dependencies (not optional)
            for dep in pkg.get("dependencies", []):
                regular_deps.add(canonicalize_name(dep["name"]))
        else:
            # Non-root — all its dependencies are regular
            for dep in pkg.get("dependencies", []):
                regular_deps.add(canonicalize_name(dep["name"]))

    results: list[dict[str, Any]] = []

    for pkg in packages:
        source = pkg.get("source", {})

        # Skip root virtual package
        if source.get("virtual") == ".":
            continue

        cn = canonicalize_name(pkg["name"])
        entry: dict[str, Any] = {"name": pkg["name"]}

        # Version
        version = pkg.get("version", "")
        if version:
            entry["version"] = f"=={version}"

        # Hashes
        hashes = _collect_hashes(pkg)
        if hashes:
            entry["hashes"] = hashes

        # Source -> index name
        registry_url = source.get("registry")
        if registry_url:
            index_name = _source_url_to_index_name(registry_url, sources)
            if index_name:
                entry["index"] = index_name
        elif source.get("git"):
            entry["git"] = source["git"]
            # Parse ref from the git URL or separate field
            # uv.lock format: source = { git = "https://...", rev = "abc123" }
            # or the ref may be embedded differently
            if "rev" in source:
                entry["ref"] = source["rev"]
            if source.get("subdirectory"):
                entry["subdirectory"] = source["subdirectory"]
        elif source.get("editable"):
            entry["editable"] = True
            entry["path"] = source["editable"]
        elif source.get("url"):
            entry["file"] = source["url"]

        # Override index from Pipfile if explicitly specified
        if cn in pipfile_indexes:
            entry["index"] = pipfile_indexes[cn]

        # Markers: prefer root dependency markers (combined metadata + user markers)
        marker = root_dep_markers.get(cn, "")
        if marker:
            # Normalize python_full_version -> python_version
            marker = _normalize_marker(marker)
        elif cn in pipfile_markers:
            marker = pipfile_markers[cn]

        # Extras-only markers
        if cn in extras_only_pkgs and cn not in regular_deps:
            extra_name = extras_only_pkgs[cn]
            extra_marker = f'extra == "{extra_name}"'
            if marker:
                marker = f"{marker} and {extra_marker}"
            else:
                marker = extra_marker

        if marker:
            entry["markers"] = marker

        # Extras from root dependency
        if cn in root_dep_extras:
            entry["extras"] = sorted(root_dep_extras[cn])

        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Main resolver function
# ---------------------------------------------------------------------------


def uv_lock_resolve(
    cmd: list[str],
    st: Any,
    project: Any,
) -> subprocess.CompletedProcess:
    """Resolver backend that uses ``uv lock``.

    Creates a temporary project directory with a ``pyproject.toml`` translated
    from the Pipfile, runs ``uv lock``, parses the resulting ``uv.lock``, and
    writes the result as JSON.  Falls back to the default pip resolver on failure.

    :param cmd: Command list (the resolver subprocess command)
    :param st: Rich Status spinner object
    :param project: The pipenv Project instance
    :return: ``subprocess.CompletedProcess``
    """
    from pipenv.resolver import get_parser
    from pipenv.utils.resolver import _pip_resolve
    from pipenv.uv import (
        _has_env_var_in_constraints,
        _has_local_path_constraint,
    )

    parsed, _remaining = get_parser().parse_known_args(cmd[2:])
    constraints_file = parsed.constraints_file
    write = parsed.write or "/dev/stdout"
    category = parsed.category or "default"
    pre = parsed.pre

    if not constraints_file:
        logger.warning("No constraints file provided, falling back to pip resolver")
        return _pip_resolve(cmd, st, project)

    # Read constraints to check for fallback conditions
    constraints: dict[str, str] = {}
    with open(constraints_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            left, right = line.split(", ", maxsplit=1)
            constraints[left] = right.strip().split(" -i ", maxsplit=1)[0].strip()

    if not constraints:
        logger.warning("No constraints found, falling back to pip resolver")
        return _pip_resolve(cmd, st, project)

    # Fall back for local paths, env vars, editable VCS
    if _has_local_path_constraint(constraints):
        logger.info(
            "Local path/file:// constraint detected, falling back to pip resolver"
        )
        return _pip_resolve(cmd, st, project)
    if _has_env_var_in_constraints(constraints):
        logger.info(
            "Environment variable in constraint detected, falling back to pip resolver"
        )
        return _pip_resolve(cmd, st, project)
    for pip_line in constraints.values():
        stripped = pip_line.strip()
        if stripped.startswith("-e ") and "git+" in stripped:
            logger.info("Editable VCS constraint detected, falling back to pip resolver")
            return _pip_resolve(cmd, st, project)

    logger.debug(
        "Running uv lock resolve with data: %s",
        json.dumps(
            {"constraints": constraints, "cmd": cmd, "category": category},
            default=str,
            indent=2,
        ),
    )

    # Build pyproject.toml in a temporary directory
    pyproject_content = _build_pyproject_toml(project, category, pre=pre)

    tmpdir = tempfile.mkdtemp(prefix="pipenv-uv-lock-")
    pyproject_path = os.path.join(tmpdir, "pyproject.toml")
    with open(pyproject_path, "w") as f:
        f.write(pyproject_content)

    logger.debug("pyproject.toml content:\n%s", pyproject_content)

    # Run uv lock
    uv_cmd = _build_uv_lock_cmd(project, tmpdir, pre=pre)

    logger.debug("Running command: %s", " ".join(uv_cmd))

    try:
        result = subprocess.run(
            uv_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("uv lock failed with %s, falling back to pip resolver", exc)
        return _pip_resolve(cmd, st, project)

    if result.returncode != 0:
        logger.warning(
            "uv lock returned non-zero exit code %d:\nstdout: %s\nstderr: %s",
            result.returncode,
            result.stdout,
            result.stderr,
        )
        # Fall back to original resolver
        return _pip_resolve(cmd, st, project)

    # Parse uv.lock
    lock_path = os.path.join(tmpdir, "uv.lock")
    if not os.path.exists(lock_path):
        logger.warning("uv.lock not found at %s, falling back to pip resolver", lock_path)
        return _pip_resolve(cmd, st, project)

    try:
        resolved = _parse_uv_lock(lock_path, project, category)
    except Exception as exc:
        logger.warning("Failed to parse uv.lock: %s, falling back to pip resolver", exc)
        return _pip_resolve(cmd, st, project)

    logger.debug(
        "Resolved %d packages:\n%s",
        len(resolved),
        json.dumps(resolved, indent=2),
    )

    # Write results to the target file
    with open(write, "w") as f:
        json.dump(resolved, f)

    # Clean up temp directory
    import shutil

    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    return subprocess.CompletedProcess(
        args=uv_cmd,
        returncode=0,
        stdout=result.stdout,
        stderr=result.stderr,
    )
