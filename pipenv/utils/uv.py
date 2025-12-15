"""
UV backend utilities for pipenv.

This module provides an optional UV backend for pipenv operations,
enforcing index-restricted package resolution similar to pipenv's
patched pip behavior.

UV is used as a subprocess with configuration translation to achieve
equivalent security guarantees without maintaining a UV fork.

Index Restriction Enforcement Strategy:
======================================
Pipenv's `index_restricted` mode works as follows:
- If a package has an explicit `index` in Pipfile, use ONLY that index
- Otherwise, use ONLY the primary (first) index - ignore all extra indexes

UV's built-in `--index-strategy first-index` doesn't match this exactly:
- UV still searches all indexes in order until it finds the package

To achieve true index restriction with UV, we:
1. Group packages by their assigned index
2. Resolve/install each group separately with ONLY its designated index
3. Packages without explicit index use ONLY the primary index

This prevents dependency confusion attacks where a malicious package
on a public index could shadow a private package name.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipenv.patched.pip._vendor.urllib3.util import parse_url
from pipenv.utils import err
from pipenv.utils.fileutils import create_tracked_tempdir
from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import project_python


def is_uv_available() -> bool:
    """Check if uv is available in PATH."""
    return shutil.which("uv") is not None


def get_uv_command() -> Optional[str]:
    """Get the path to the uv executable."""
    return shutil.which("uv")


def prepare_uv_source_args(
    sources: List[Dict],
    index_lookup: Optional[Dict[str, str]] = None,
    package_name: Optional[str] = None,
) -> List[str]:
    """
    Prepare UV index arguments with index restriction enforcement.

    Unlike pip with --extra-index-url, this enforces that:
    1. If a package has an explicit index in index_lookup, ONLY that index is used
    2. Otherwise, ONLY the default (first) index is used

    This prevents dependency confusion attacks where a malicious package
    on a public index could shadow a private package.

    Args:
        sources: List of source dicts with 'url', 'name', 'verify_ssl' keys
        index_lookup: Dict mapping package names to index URLs
        package_name: If provided, get args for this specific package

    Returns:
        List of UV CLI arguments for index configuration
    """
    uv_args = []

    if not sources:
        return uv_args

    # Determine which index URL to use
    if package_name and index_lookup and package_name in index_lookup:
        # Package has explicit index - use ONLY that index
        index_url = index_lookup[package_name]
        uv_args.extend(["--default-index", index_url])
    else:
        # No explicit index - use ONLY the primary (first) index
        # This is the index restriction: we don't add extra indexes
        primary_source = sources[0]
        index_url = primary_source.get("url")
        if index_url:
            uv_args.extend(["--default-index", index_url])

            # Handle SSL verification
            if not primary_source.get("verify_ssl", True):
                url_parts = parse_url(index_url)
                url_port = f":{url_parts.port}" if url_parts.port else ""
                uv_args.extend(["--allow-insecure-host", f"{url_parts.host}{url_port}"])

    # Use first-index strategy to stop at first index that has the package
    uv_args.extend(["--index-strategy", "first-index"])

    return uv_args


def prepare_uv_install_args(
    pre: bool = False,
    verbose: bool = False,
    upgrade: bool = False,
    require_hashes: bool = False,
    no_deps: bool = False,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Prepare UV pip install arguments."""
    args = []

    if pre:
        args.append("--prerelease=allow")
    if verbose:
        args.append("--verbose")
    if upgrade:
        args.append("--upgrade")
    if require_hashes:
        args.append("--require-hashes")
    if no_deps:
        args.append("--no-deps")

    if extra_args:
        args.extend(extra_args)

    return args


def build_index_lookup_from_lockfile(lockfile: Dict) -> Dict[str, str]:
    """
    Build a mapping of package names to their index URLs from lockfile.

    The lockfile stores index names, so we need to resolve them to URLs
    using the _meta.sources section.

    Args:
        lockfile: The parsed Pipfile.lock dict

    Returns:
        Dict mapping normalized package names to index URLs
    """
    index_lookup = {}

    # Build source name to URL mapping
    sources = lockfile.get("_meta", {}).get("sources", [])
    source_map = {s.get("name"): s.get("url") for s in sources if s.get("name")}

    # Scan all sections for packages with index specifications
    for section in ["default", "develop"]:
        packages = lockfile.get(section, {})
        for pkg_name, pkg_info in packages.items():
            if isinstance(pkg_info, dict) and "index" in pkg_info:
                index_name = pkg_info["index"]
                if index_name in source_map:
                    index_lookup[pkg_name.lower()] = source_map[index_name]

    return index_lookup


def get_sources_from_lockfile(lockfile: Dict) -> List[Dict]:
    """Extract sources from lockfile metadata."""
    return lockfile.get("_meta", {}).get("sources", [])


def _dep_to_requirement(pkg_name: str, pkg_spec) -> str:
    """Convert a Pipfile dependency spec to a pip requirement string.

    Args:
        pkg_name: The package name
        pkg_spec: The package specification (string like "==1.0.0" or "*",
                  or dict like {"version": ">=2.0", "index": "pypi"})

    Returns:
        A pip requirement string like "package==1.0.0" or "package>=2.0"
    """
    if isinstance(pkg_spec, str):
        if pkg_spec == "*":
            return pkg_name
        # Version specifier like "==1.0.0" or ">=2.0"
        return f"{pkg_name}{pkg_spec}"
    elif isinstance(pkg_spec, dict):
        version = pkg_spec.get("version", "")
        if version and version != "*":
            return f"{pkg_name}{version}"
        return pkg_name
    return pkg_name


def generate_uv_pyproject_toml(
    sources: List[Dict],
    index_lookup: Dict[str, str],
    python_version: Optional[str] = None,
) -> str:
    """
    Generate a pyproject.toml content for UV with index restriction enforcement.

    This implements pipenv's index_restricted behavior using UV's native features:
    - All non-primary indexes are marked as `explicit = true`
    - Only packages with explicit index assignments get `tool.uv.sources` entries
    - Packages without explicit mappings can ONLY come from the primary index

    Args:
        sources: List of source dicts from Pipfile/lockfile
        index_lookup: Dict mapping package names to their designated index names
        python_version: Optional Python version constraint

    Returns:
        pyproject.toml content as a string
    """
    lines = ["[project]", 'name = "pipenv-uv-resolver"', 'version = "0.0.0"']

    if python_version:
        lines.append(f'requires-python = ">={python_version}"')

    lines.append("")

    # Build index name to URL mapping
    source_name_to_url = {s.get("name"): s.get("url") for s in sources if s.get("name")}

    # Add UV indexes - primary index first, others marked as explicit
    for i, source in enumerate(sources):
        name = source.get("name")
        url = source.get("url")

        if not name or not url:
            continue

        lines.append("[[tool.uv.index]]")
        lines.append(f'name = "{name}"')
        lines.append(f'url = "{url}"')

        # Non-primary indexes are marked explicit - they require explicit source mapping
        # This is the key to enforcing index restriction!
        if i > 0:
            lines.append("explicit = true")

        lines.append("")

    # Add source mappings for packages with explicit index assignments
    if index_lookup:
        lines.append("[tool.uv.sources]")
        for pkg_name, index_name in sorted(index_lookup.items()):
            # Verify the index exists
            if index_name in source_name_to_url:
                lines.append(f'{pkg_name} = {{ index = "{index_name}" }}')
        lines.append("")

    return "\n".join(lines)


def uv_resolve_with_index_restriction(
    project,
    requirements: List[str],
    sources: List[Dict],
    index_lookup: Dict[str, str],
    dev: bool = False,
    pre: bool = False,
    python_version: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """
    Resolve dependencies using UV with index restriction enforcement.

    Uses UV's pyproject.toml-based resolution with explicit indexes to enforce
    that packages without explicit index assignments only come from the primary index.

    This uses `uv lock` (not `uv pip compile`) because only `uv lock` respects
    the full pyproject.toml configuration including tool.uv.sources and
    tool.uv.index with explicit=true.

    Args:
        project: The pipenv Project instance
        requirements: List of requirement strings to resolve
        sources: List of source dicts from Pipfile
        index_lookup: Dict mapping package names to their index names
        dev: Whether to include dev dependencies
        pre: Whether to allow prereleases
        python_version: Python version constraint

    Returns:
        Tuple of (success, lockfile_content, stderr)
        Where lockfile_content is the uv.lock file content on success
    """
    uv_cmd = get_uv_command()
    if not uv_cmd:
        raise RuntimeError("UV is not available")

    # Create temp directory for UV resolution
    temp_dir = create_tracked_tempdir(prefix="pipenv-uv-resolve")
    temp_path = Path(temp_dir)

    # Generate pyproject.toml with index restrictions and dependencies
    lines = ["[project]", 'name = "pipenv-uv-resolver"', 'version = "0.0.0"']

    if python_version:
        lines.append(f'requires-python = ">={python_version}"')

    # Add dependencies to pyproject.toml
    deps_list = ", ".join(f'"{req}"' for req in requirements)
    lines.append(f"dependencies = [{deps_list}]")
    lines.append("")

    # Build index name to URL mapping for source lookups
    source_name_to_url = {s.get("name"): s.get("url") for s in sources if s.get("name")}

    # Add UV indexes - primary index first, others marked as explicit
    for i, source in enumerate(sources):
        name = source.get("name")
        url = source.get("url")

        if not name or not url:
            continue

        lines.append("[[tool.uv.index]]")
        lines.append(f'name = "{name}"')
        lines.append(f'url = "{url}"')

        # Non-primary indexes are marked explicit - they require explicit source mapping
        # This is the key to enforcing index restriction!
        if i > 0:
            lines.append("explicit = true")

        lines.append("")

    # Add source mappings for packages with explicit index assignments
    if index_lookup:
        lines.append("[tool.uv.sources]")
        for pkg_name, index_name in sorted(index_lookup.items()):
            # Verify the index exists
            if index_name in source_name_to_url:
                lines.append(f'{pkg_name} = {{ index = "{index_name}" }}')
        lines.append("")

    pyproject_content = "\n".join(lines)
    pyproject_path = temp_path / "pyproject.toml"
    pyproject_path.write_text(pyproject_content)

    if project.s.is_verbose():
        err.print("Generated pyproject.toml for UV resolution:", style="bold cyan")
        err.print(pyproject_content, style="dim")

    # Run UV lock to resolve dependencies
    uv_command = [
        uv_cmd,
        "lock",
    ]

    if pre:
        uv_command.append("--prerelease=allow")

    if project.s.is_verbose():
        from pipenv.utils.shell import cmd_list_to_shell

        err.print(f"$ {cmd_list_to_shell(uv_command)}", style="cyan")

    result = subprocess.run(
        uv_command,
        capture_output=True,
        text=True,
        cwd=str(temp_path),
        check=False,
    )

    lockfile_content = ""
    if result.returncode == 0:
        lockfile_path = temp_path / "uv.lock"
        if lockfile_path.exists():
            lockfile_content = lockfile_path.read_text()

    return result.returncode == 0, lockfile_content, result.stderr


def uv_resolve_deps(
    project,
    deps: Dict[str, Any],
    sources: List[Dict],
    index_lookup: Optional[Dict[str, str]] = None,
    pre: bool = False,
    output_format: str = "requirements.txt",
) -> Tuple[bool, str]:
    """
    Resolve dependencies using UV with index restriction enforcement.

    This resolves packages grouped by their assigned index to enforce
    true index restriction - each package can only be resolved from
    its designated index (or primary index if not specified).

    Args:
        project: The pipenv Project instance
        deps: Dict of package names to their Pipfile specifications
        sources: List of source dicts from Pipfile
        index_lookup: Dict mapping package names to index names
        pre: Allow pre-release versions
        output_format: Output format ("requirements.txt" or "pylock.toml")

    Returns:
        Tuple of (success: bool, output: str)
    """
    uv_cmd = get_uv_command()
    if not uv_cmd:
        raise RuntimeError(
            "UV is not available. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )

    if index_lookup is None:
        index_lookup = {}

    # Build source name to URL mapping
    source_map = {s.get("name"): s.get("url") for s in sources if s.get("name")}
    primary_index = sources[0].get("url") if sources else "https://pypi.org/simple"

    # Group deps by their designated index
    deps_by_index: Dict[str, List[str]] = {}
    for pkg_name, pkg_spec in deps.items():
        # Determine which index this package should use
        if pkg_name.lower() in index_lookup:
            index_name = index_lookup[pkg_name.lower()]
            index_url = source_map.get(index_name, primary_index)
        elif isinstance(pkg_spec, dict) and "index" in pkg_spec:
            index_name = pkg_spec["index"]
            index_url = source_map.get(index_name, primary_index)
        else:
            # No explicit index - use ONLY primary (index restriction!)
            index_url = primary_index

        if index_url not in deps_by_index:
            deps_by_index[index_url] = []

        # Convert Pipfile spec to requirement string
        req_str = _pipfile_spec_to_requirement(pkg_name, pkg_spec)
        deps_by_index[index_url].append(req_str)

    # Resolve each group with its designated index ONLY
    all_resolved = []
    for index_url, group_deps in deps_by_index.items():
        # Write requirements to temp file
        with tempfile.NamedTemporaryFile(
            prefix="pipenv-uv-", suffix="-requirements.in", delete=False, mode="w"
        ) as req_file:
            for dep in group_deps:
                req_file.write(dep + "\n")
            req_file_path = req_file.name

        try:
            # Build UV compile command with ONLY this index
            uv_command = [
                uv_cmd,
                "pip",
                "compile",
                req_file_path,
                "--default-index",
                index_url,
                "--index-strategy",
                "first-index",
                "--no-header",
                "--no-annotate",
            ]

            if pre:
                uv_command.append("--prerelease=allow")

            if output_format == "pylock.toml":
                uv_command.extend(["--format", "pylock.toml"])

            # Find source for SSL verification
            source = next((s for s in sources if s.get("url") == index_url), None)
            if source and not source.get("verify_ssl", True):
                url_parts = parse_url(index_url)
                url_port = f":{url_parts.port}" if url_parts.port else ""
                uv_command.extend(
                    ["--allow-insecure-host", f"{url_parts.host}{url_port}"]
                )

            if project.s.is_verbose():
                err.print(
                    f"UV Resolve: {len(group_deps)} packages from {index_url}",
                    style="bold cyan",
                )
                from pipenv.utils.shell import cmd_list_to_shell

                err.print(f"$ {cmd_list_to_shell(uv_command)}", style="cyan")

            result = subprocess.run(
                uv_command,
                capture_output=True,
                text=True,
                env={**os.environ, "UV_NO_PROGRESS": "1"},
                check=False,
            )

            if result.returncode != 0:
                err.print(f"UV resolution failed for index {index_url}", style="bold red")
                err.print(result.stderr, style="red")
                return False, result.stderr

            all_resolved.append(result.stdout)

        finally:
            os.unlink(req_file_path)

    # Combine all resolved requirements
    combined_output = "\n".join(all_resolved)
    return True, combined_output


def _pipfile_spec_to_requirement(pkg_name: str, pkg_spec: Any) -> str:
    """Convert a Pipfile package specification to a requirement string."""
    if isinstance(pkg_spec, str):
        if pkg_spec == "*":
            return pkg_name
        elif pkg_spec.startswith(("==", ">=", "<=", ">", "<", "~=", "!=")):
            return f"{pkg_name}{pkg_spec}"
        else:
            return f"{pkg_name}=={pkg_spec}"

    if isinstance(pkg_spec, dict):
        # Handle VCS requirements
        for vcs in ["git", "hg", "svn", "bzr"]:
            if vcs in pkg_spec:
                url = pkg_spec[vcs]
                ref = pkg_spec.get("ref", "")
                ref_str = f"@{ref}" if ref else ""
                return f"{pkg_name} @ {vcs}+{url}{ref_str}"

        # Handle version specifier
        version = pkg_spec.get("version", "*")
        extras = pkg_spec.get("extras", [])
        extras_str = f"[{','.join(extras)}]" if extras else ""

        if version == "*":
            return f"{pkg_name}{extras_str}"
        elif version.startswith(("==", ">=", "<=", ">", "<", "~=", "!=")):
            return f"{pkg_name}{extras_str}{version}"
        else:
            return f"{pkg_name}{extras_str}=={version}"

    return pkg_name


def uv_pip_install_deps(
    project,
    deps: List[str],
    sources: List[Dict],
    index_lookup: Optional[Dict[str, str]] = None,
    allow_global: bool = False,
    ignore_hashes: bool = False,
    no_deps: bool = False,
    requirements_dir: Optional[str] = None,
    extra_pip_args: Optional[List[str]] = None,
) -> List:
    """
    Install dependencies using UV with index restriction enforcement.

    This is the UV equivalent of pip_install_deps() from pipenv/utils/pip.py.
    Key difference: enforces that packages without explicit index assignments
    are only fetched from the primary index, preventing dependency confusion.

    Args:
        project: The pipenv Project instance
        deps: List of pip requirement lines to install
        sources: List of source dicts from Pipfile/lockfile
        index_lookup: Dict mapping package names to their designated index URLs
        allow_global: If True, install to system Python
        ignore_hashes: If True, don't require hash verification
        no_deps: If True, don't install package dependencies
        requirements_dir: Directory for temporary requirements files
        extra_pip_args: Additional arguments to pass to UV

    Returns:
        List of subprocess results
    """
    uv_cmd = get_uv_command()
    if not uv_cmd:
        raise RuntimeError(
            "UV is not available. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )

    if index_lookup is None:
        index_lookup = {}

    if not requirements_dir:
        requirements_dir = create_tracked_tempdir(
            prefix="pipenv-uv", suffix="requirements"
        )

    # Group deps by their index to batch installations efficiently
    deps_by_index: Dict[str, List[str]] = {}

    for dep_line in deps:
        # Extract package name from requirement line
        pkg_name = _extract_package_name(dep_line)
        if pkg_name:
            pkg_name_lower = pkg_name.lower()
            # Determine which index this package should use
            if pkg_name_lower in index_lookup:
                index_url = index_lookup[pkg_name_lower]
            else:
                # Default to primary index only (index restriction!)
                index_url = (
                    sources[0].get("url") if sources else "https://pypi.org/simple"
                )

            if index_url not in deps_by_index:
                deps_by_index[index_url] = []
            deps_by_index[index_url].append(dep_line)
        else:
            # Fallback for lines we can't parse
            default_url = sources[0].get("url") if sources else "https://pypi.org/simple"
            if default_url not in deps_by_index:
                deps_by_index[default_url] = []
            deps_by_index[default_url].append(dep_line)

    cmds = []
    python_path = project_python(project, system=allow_global)

    # Install each group with its specific index
    for index_url, group_deps in deps_by_index.items():
        # Write requirements to temp file
        req_file = tempfile.NamedTemporaryFile(
            prefix="pipenv-uv-",
            suffix="-reqs.txt",
            dir=requirements_dir,
            delete=False,
            mode="w",
        )
        for dep_line in group_deps:
            # Strip hashes if ignoring them
            if ignore_hashes:
                dep_line = _strip_hashes(dep_line)
            req_file.write(dep_line + "\n")
        req_file.close()

        # Build UV command
        uv_command = [
            uv_cmd,
            "pip",
            "install",
            "--python",
            python_path,
        ]

        # Add index arguments - ONLY the specific index for this group
        uv_command.extend(["--default-index", index_url])
        uv_command.extend(["--index-strategy", "first-index"])

        # Find source for SSL verification
        source = next((s for s in sources if s.get("url") == index_url), None)
        if source and not source.get("verify_ssl", True):
            url_parts = parse_url(index_url)
            url_port = f":{url_parts.port}" if url_parts.port else ""
            uv_command.extend(["--allow-insecure-host", f"{url_parts.host}{url_port}"])

        # Add standard install args
        uv_command.extend(
            prepare_uv_install_args(
                pre=project.settings.get("allow_prereleases", False),
                upgrade=True,
                no_deps=no_deps,
                extra_args=extra_pip_args,
            )
        )

        # Add requirements file
        uv_command.extend(["-r", req_file.name])

        if project.s.is_verbose():
            err.print(
                f"UV Install: {len(group_deps)} packages from {index_url}", style="bold"
            )
            from pipenv.utils.shell import cmd_list_to_shell

            err.print(f"$ {cmd_list_to_shell(uv_command)}", style="cyan")

        # Set up environment
        cache_dir = Path(project.s.PIPENV_CACHE_DIR)
        env = {
            "UV_CACHE_DIR": cache_dir.joinpath("uv").as_posix(),
            "PATH": os.environ.get("PATH", ""),
        }

        c = subprocess_run(uv_command, block=False, capture_output=True, env=env)
        c.env = env
        cmds.append(c)

        if project.s.is_verbose():
            while True:
                line = c.stdout.readline()
                if not line:
                    break
                err.print(line.rstrip(), style="yellow")

    return cmds


def _extract_package_name(dep_line: str) -> Optional[str]:
    """
    Extract package name from a pip requirement line.

    Handles various formats:
    - package==1.0.0
    - package[extra]==1.0.0
    - package>=1.0.0 --hash=sha256:...
    - -e git+https://...#egg=package
    - package @ https://...
    """
    import re

    dep_line = dep_line.strip()

    # Skip empty lines and comments
    if not dep_line or dep_line.startswith("#"):
        return None

    # Handle editable installs: -e git+...#egg=name
    if dep_line.startswith("-e"):
        match = re.search(r"#egg=([a-zA-Z0-9_-]+)", dep_line)
        if match:
            return match.group(1)
        return None

    # Handle URL installs: name @ https://...
    if " @ " in dep_line:
        return dep_line.split(" @ ")[0].split("[")[0].strip()

    # Handle standard requirements: name[extras]>=version
    match = re.match(r"^([a-zA-Z0-9_.-]+)", dep_line)
    if match:
        return match.group(1)

    return None


def _strip_hashes(dep_line: str) -> str:
    """Remove --hash arguments from a requirement line."""
    import re

    return re.sub(r"\s+--hash=[^\s]+", "", dep_line).strip()


def uv_lock_to_pylock(
    project,
    deps: Dict[str, Any],
    sources: List[Dict],
    index_lookup: Dict[str, str],
    lockfile_categories: List[str],
    category_packages: Optional[Dict[str, set]] = None,
    pre: bool = False,
) -> Dict[str, Any]:
    """
    Resolve dependencies using UV and convert to pylock.toml format.

    Uses UV's native `uv lock` command with pyproject.toml configuration
    that enforces pipenv's index restriction behavior.

    Args:
        project: The pipenv Project instance
        deps: Dict of package names to their Pipfile specifications
        sources: List of source dicts from Pipfile
        index_lookup: Dict mapping package names to index names
        lockfile_categories: List of lockfile categories being resolved
        category_packages: Dict mapping category names to sets of package names
        pre: Allow pre-release versions

    Returns:
        Dict in pylock.toml format (PEP 751)
    """
    from pipenv.vendor import tomlkit

    # Convert deps dict to requirement strings with version specifiers
    requirements = []
    for pkg_name, pkg_spec in deps.items():
        requirements.append(_dep_to_requirement(pkg_name, pkg_spec))

    # Run UV lock with index restriction
    success, uv_lockfile, stderr = uv_resolve_with_index_restriction(
        project=project,
        requirements=requirements,
        sources=sources,
        index_lookup=index_lookup,
        pre=pre,
    )

    if not success:
        raise RuntimeError(f"UV lock failed: {stderr}")

    # Parse the UV lockfile (TOML format)
    try:
        uv_lock_data = tomlkit.parse(uv_lockfile)
    except Exception as e:
        raise RuntimeError(f"Failed to parse UV lockfile: {e}")

    # Convert UV lock format to pylock.toml format (PEP 751)
    pylock_data = _convert_uv_lock_to_pylock(
        uv_lock_data=uv_lock_data,
        deps=deps,
        sources=sources,
        index_lookup=index_lookup,
        lockfile_categories=lockfile_categories,
        category_packages=category_packages,
        project=project,
    )

    return pylock_data


def _convert_uv_lock_to_pylock(
    uv_lock_data: Dict[str, Any],
    deps: Dict[str, Any],
    sources: List[Dict],
    index_lookup: Dict[str, str],
    lockfile_categories: List[str],
    category_packages: Optional[Dict[str, set]],
    project,
) -> Dict[str, Any]:
    """
    Convert UV's uv.lock format to PEP 751 pylock.toml format.

    UV lock format (simplified):
    ```toml
    version = 1
    requires-python = ">=3.11"

    [[package]]
    name = "requests"
    version = "2.31.0"
    source = { registry = "https://pypi.org/simple" }
    dependencies = [
        { name = "certifi" },
        { name = "charset-normalizer", ... },
    ]
    sdist = { url = "...", hash = "sha256:..." }
    wheels = [
        { url = "...", hash = "sha256:..." },
    ]
    ```

    Pylock.toml format (PEP 751):
    ```toml
    lock-version = "1.0"
    requires-python = ">=3.11"
    created-by = "pipenv"

    [[packages]]
    name = "requests"
    version = "2.31.0"

    [[packages.files]]
    name = "requests-2.31.0-py3-none-any.whl"
    url = "..."
    hashes = ["sha256:..."]
    ```
    """
    import datetime

    # Build source URL to name mapping for index tracking
    source_url_to_name = {s.get("url"): s.get("name") for s in sources if s.get("url")}

    # Use category_packages if provided, otherwise fall back to deps-based detection
    if category_packages:
        dev_packages = category_packages.get("develop", set())
        default_packages = category_packages.get("default", set())
    else:
        dev_packages = set()
        default_packages = set()
        for pkg_name in deps.keys():
            pkg_lower = pkg_name.lower().replace("_", "-")
            if "develop" in lockfile_categories:
                dev_packages.add(pkg_lower)
            if "default" in lockfile_categories:
                default_packages.add(pkg_lower)

    # Create the pylock.toml structure
    pylock_data: Dict[str, Any] = {
        "lock-version": "1.0",
        "created-by": "pipenv (uv backend)",
        "packages": [],
    }

    # Add requires-python if present
    requires_python = uv_lock_data.get("requires-python")
    if requires_python:
        pylock_data["requires-python"] = requires_python

    # Add dependency groups
    pylock_data["dependency-groups"] = ["dev"] if "develop" in lockfile_categories else []
    pylock_data["default-groups"] = (
        ["default"] if "default" in lockfile_categories else []
    )

    # Add metadata
    pylock_data["tool"] = {
        "pipenv": {
            "resolver": "uv",
            "generation_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    }

    # Convert each UV package to pylock format
    uv_packages = uv_lock_data.get("package", [])
    for uv_pkg in uv_packages:
        pkg_name = uv_pkg.get("name", "")
        pkg_version = uv_pkg.get("version", "")

        if not pkg_name:
            continue

        # Skip the temporary UV resolver project
        if pkg_name == "pipenv-uv-resolver":
            continue

        pylock_pkg: Dict[str, Any] = {
            "name": pkg_name,
            "version": pkg_version,
        }

        # Add source/index info
        source_info = uv_pkg.get("source", {})
        registry_url = source_info.get("registry")
        if registry_url:
            # Normalize URL for lookup
            normalized_url = registry_url.rstrip("/")
            for src_url, src_name in source_url_to_name.items():
                if normalized_url in src_url or src_url in normalized_url:
                    pylock_pkg["index"] = src_name
                    break

        # Add files (wheels and sdist)
        files = []

        # Add wheels
        wheels = uv_pkg.get("wheels", [])
        for wheel in wheels:
            file_entry: Dict[str, Any] = {}
            if "url" in wheel:
                file_entry["url"] = wheel["url"]
                # Extract filename from URL
                file_entry["name"] = wheel["url"].rsplit("/", 1)[-1]
            if "hash" in wheel:
                file_entry["hashes"] = [wheel["hash"]]
            if file_entry:
                files.append(file_entry)

        # Add sdist
        sdist = uv_pkg.get("sdist")
        if sdist:
            file_entry = {}
            if "url" in sdist:
                file_entry["url"] = sdist["url"]
                file_entry["name"] = sdist["url"].rsplit("/", 1)[-1]
            if "hash" in sdist:
                file_entry["hashes"] = [sdist["hash"]]
            if file_entry:
                files.append(file_entry)

        if files:
            pylock_pkg["files"] = files

        # Add dependency group markers
        pkg_lower = pkg_name.lower().replace("_", "-")
        if pkg_lower in dev_packages and pkg_lower not in default_packages:
            pylock_pkg["groups"] = ["dev"]

        pylock_data["packages"].append(pylock_pkg)

    return pylock_data
