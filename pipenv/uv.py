"""Integration with uv for fast dependency resolution and installation.

When enabled via PIPENV_UV=1, this module monkey-patches pipenv's resolver
and installer to use uv instead of pip, providing significantly faster
lock and install operations.

Environment variables:
    PIPENV_UV              -- Enable uv integration (default: disabled)
    PIPENV_UV_NO_RESOLVE   -- Disable uv-based resolution only
    PIPENV_UV_NO_INSTALL   -- Disable uv-based installation only
    PIPENV_UV_VERBOSE      -- Enable debug logging for uv commands
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

# Saved references to original functions, set by patch()
_original_resolve = None
_original_pip_install_deps = None
_install_message_shown = False


def _is_local_path_or_file_uri(pip_line):
    """Check if a pip install line refers to a local path or file:// URI.

    uv has issues with local path packages (paths with spaces, ``file://`` URIs,
    ``+`` in filenames, ``.`` references, etc.), so we detect these and fall
    back to pip.

    :param pip_line: A single pip install line (str)
    :return: True if the line refers to a local path or file:// URI
    """
    stripped = pip_line.strip()
    if not stripped or stripped.startswith("#"):
        return False

    # Remove leading -e for editable
    if stripped.startswith("-e "):
        stripped = stripped[3:].strip()

    # file:// URIs
    if stripped.startswith("file://") or stripped.startswith("file:///"):
        return True

    # Explicit local path patterns
    if stripped.startswith("./") or stripped.startswith("../"):
        return True
    if stripped == "." or stripped.startswith(".["):
        return True
    if stripped.startswith("/"):
        # Absolute path — but not a flag like --some-option
        return True

    # Check for path= or file= in pip line (shouldn't be in raw line, but be safe)
    # Also detect lines that are bare relative paths (no == version specifier)
    # e.g. "some/local/dir" or "some/local/dir[extras]"
    # But NOT "package==1.0" or "package @ https://..."
    if os.sep in stripped and "==" not in stripped and " @ " not in stripped:
        return True

    return False


def _has_local_path_requirement(args):
    """Check if any requirements file in the args contains local path packages.

    :param args: Command argument list (may contain ``-r <file>`` pairs)
    :return: True if any requirements file contains local path lines
    """
    req_files = []
    it = iter(args)
    for arg in it:
        if arg == "-r":
            try:
                req_files.append(next(it))
            except StopIteration:
                break
        elif arg.startswith("-r"):
            req_files.append(arg[2:])

    for req_file in req_files:
        try:
            with open(req_file) as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if _is_local_path_or_file_uri(stripped):
                        return True
        except OSError:
            continue
    return False


def find_uv_bin():
    """Locate the uv binary.

    Tries the uv Python package first, falls back to PATH lookup.

    :return: Path to the uv binary
    :raises FileNotFoundError: If uv cannot be found
    """
    # Try the uv Python package first
    try:
        from uv._find_uv import find_uv_bin as _find

        return _find()
    except (ImportError, FileNotFoundError):
        pass

    # Fall back to PATH lookup
    import shutil

    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path

    raise FileNotFoundError(
        "uv binary not found. Install it via 'pip install uv' or ensure it is available on PATH."
    )


def parse_requirements_lines(lines):
    """Parse ``uv pip compile`` output into a dict of package entries.

    Each entry is a dict suitable for writing into a Pipfile.lock section.

    When ``--emit-index-annotation`` is used with ``uv pip compile``, the
    output includes ``# from <url>`` comments after each package.  These are
    captured in the returned ``index_annotations`` dict.

    :param lines: Iterable of requirement lines (str)
    :return: Tuple of (packages dict, index url str, index_annotations dict)
        where ``index_annotations`` maps canonical package names to source URLs.
    """
    import re

    ret = {}
    _index = ""
    hashes = []
    # Track the most recently parsed package name so we can associate
    # ``# from <url>`` annotations that follow it.
    last_name = None
    index_annotations = {}  # {canonical_name: source_url}

    for _line in lines:
        line = _line.strip("\n \\")
        if not line:
            continue
        if line.startswith("# from "):
            # ``--emit-index-annotation`` output: ``# from https://pypi.org/simple``
            source_url = line[len("# from ") :].strip()
            if last_name is not None:
                from pipenv.patched.pip._vendor.packaging.utils import (
                    canonicalize_name,
                )

                index_annotations[canonicalize_name(last_name)] = source_url
            continue
        if line.startswith("#"):
            continue
        if line.startswith("-i "):
            _index = line.split("-i ")[-1]
            continue
        if line.startswith("--hash="):
            hashes.append(line.split("--hash=")[-1])
            continue

        hashes.sort()

        package, _, markers = line.partition(";")
        package = package.strip()
        markers = markers.strip()

        extras = ""
        name = "NOTHING"

        if package.startswith("-e "):
            project_dir = os.path.abspath(package.split("-e ")[-1])
            pyproject_path = os.path.join(project_dir, "pyproject.toml")
            name = os.path.basename(project_dir)
            if os.path.exists(pyproject_path):
                pattern = re.compile(r'name\s*=\s*["\']([^"\']+)["\']')
                with open(pyproject_path) as pf:
                    for mline in pf:
                        match = pattern.search(mline)
                        if match:
                            name = match.group(1)
                            break
            pkg = {
                "editable": True,
                "file": line.split("-e ")[-1],
            }
        elif "git+" in package:
            # Two formats:
            #   "name @ git+https://host/repo@ref"  (uv pip compile output)
            #   "name@git+https://host/repo@ref"     (no spaces around @)
            if " @ " in package:
                name, _, git_url_with_ref = package.partition(" @ ")
                name = name.strip()
            else:
                name, _, git_url_with_ref = package.partition("@")
            if "[" in name:
                name, extras = name.strip("]").split("[", maxsplit=1)
            # git_url_with_ref = "git+https://host/repo@ref"
            # Split on last @ to separate URL from ref
            at_idx = git_url_with_ref.rfind("@")
            if at_idx > 0:
                url = git_url_with_ref[:at_idx].strip()
                ref = git_url_with_ref[at_idx + 1 :].strip()
            else:
                url = git_url_with_ref.strip()
                ref = ""
            # Handle #subdirectory= fragment in the ref
            subdirectory = ""
            if "#subdirectory=" in ref:
                ref, _, subdirectory = ref.partition("#subdirectory=")
            elif "#subdirectory=" in url:
                url, _, subdirectory = url.partition("#subdirectory=")
            _vcs, _, git = url.partition("+")
            pkg = {
                "git": git,
                "ref": ref,
            }
            if subdirectory:
                pkg["subdirectory"] = subdirectory
        elif " @ " in package and "git+" not in package:
            # Direct URL packages: "name @ https://example.com/pkg-1.0.tar.gz"
            name, _, url = package.partition(" @ ")
            name = name.strip()
            url = url.strip()
            if "[" in name:
                name, extras = name.strip("]").split("[", maxsplit=1)
            pkg = {
                "file": url,
                "hashes": hashes,
            }
        else:
            name, _, version = package.partition("==")
            extras = ""
            if "[" in name:
                name, extras = name.strip("]").split("[", maxsplit=1)
            if name not in ret:
                hashes = []
            pkg = {
                "hashes": hashes,
                "version": f"=={version}",
            }

        if markers:
            pkg["markers"] = markers
        if extras:
            pkg["extras"] = extras.split(",")
        if name in ret:
            ret[name].pop("markers", None)
        else:
            ret[name] = pkg
        last_name = name

    return ret, _index, index_annotations


def _has_local_path_constraint(constraints):
    """Check if any constraint value is a local path or file:// URI.

    :param constraints: Dict of {name: pip_line} from the constraints file
    :return: True if any constraint refers to a local path
    """
    for pip_line in constraints.values():
        if _is_local_path_or_file_uri(pip_line):
            return True
    return False


def _has_env_var_in_constraints(constraints):
    """Check if any constraint contains unexpanded environment variables.

    uv doesn't expand ``${VAR}`` or ``$VAR`` in URLs.

    :param constraints: Dict of {name: pip_line} from the constraints file
    :return: True if any constraint contains env var references
    """
    for pip_line in constraints.values():
        if "${" in pip_line or re.search(r"\$[A-Za-z_]", pip_line):
            return True
    return False


def _get_pipfile_markers(project, category):
    """Extract user-specified markers from the Pipfile for a given category.

    :param project: The pipenv Project instance
    :param category: Category name (e.g. "default", "develop")
    :return: Dict of {canonical_name: marker_string}
    """
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    markers = {}
    if category == "default":
        deps = project.packages
    elif category == "develop":
        deps = project.dev_packages
    else:
        deps = project.parsed_pipfile.get(category, {})

    for name, entry in deps.items():
        if isinstance(entry, dict):
            # Check for marker-related keys in Pipfile entries
            # Pipfile uses keys like os_name, sys_platform, python_version, etc.
            marker_keys = {
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
            marker_parts = []
            for key in marker_keys:
                if key in entry:
                    val = entry[key]
                    marker_parts.append(f"{key} {val}")
            if entry.get("markers"):
                marker_parts.append(entry["markers"])
            if marker_parts:
                markers[canonicalize_name(name)] = " and ".join(marker_parts)
    return markers


def _get_pipfile_index_for_deps(project, category):
    """Extract index assignments from the Pipfile for a given category.

    :param project: The pipenv Project instance
    :param category: Category name (e.g. "default", "develop")
    :return: Dict of {canonical_name: index_name}
    """
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    index_map = {}
    if category == "default":
        deps = project.packages
    elif category == "develop":
        deps = project.dev_packages
    else:
        deps = project.parsed_pipfile.get(category, {})

    for name, entry in deps.items():
        if isinstance(entry, dict) and entry.get("index"):
            index_map[canonicalize_name(name)] = entry["index"]
    return index_map


def uv_resolve(cmd, st, project):
    """Replacement for ``pipenv.utils.resolver.resolve`` that uses uv.

    Runs ``uv pip compile`` to resolve dependencies, parses the output,
    and writes the result as JSON.  Falls back to the original resolver
    on failure.

    :param cmd: Command list (the resolver subprocess command)
    :param st: Rich Status spinner object
    :param project: The pipenv Project instance
    :return: ``subprocess.CompletedProcess``
    """
    if _original_resolve is None:
        raise RuntimeError("Original resolve function is not available")

    from pipenv.resolver import get_parser

    parsed, _remaining = get_parser().parse_known_args(cmd[2:])
    constraints_file = parsed.constraints_file
    write = parsed.write or "/dev/stdout"

    if not constraints_file:
        logger.warning("No constraints file provided, falling back to pip resolver")
        return _original_resolve(cmd, st, project)

    constraints = {}
    with open(constraints_file) as f:
        for line in f:
            left, right = line.split(", ", maxsplit=1)
            # Strip index URL annotation if present
            constraints[left] = right.strip().split(" -i ", maxsplit=1)[0].strip()

    if not constraints:
        logger.warning("No constraints found, falling back to pip resolver")
        return _original_resolve(cmd, st, project)

    # Fall back to pip if constraints contain local paths, file:// URIs,
    # unexpanded environment variables, or editable VCS packages — all of
    # which uv handles differently or not at all.
    if _has_local_path_constraint(constraints):
        logger.info(
            "Local path/file:// constraint detected, falling back to pip resolver"
        )
        return _original_resolve(cmd, st, project)
    if _has_env_var_in_constraints(constraints):
        logger.info(
            "Environment variable in constraint detected, falling back to pip resolver"
        )
        return _original_resolve(cmd, st, project)
    for pip_line in constraints.values():
        stripped = pip_line.strip()
        if stripped.startswith("-e ") and "git+" in stripped:
            logger.info("Editable VCS constraint detected, falling back to pip resolver")
            return _original_resolve(cmd, st, project)

    if os.environ.get("PIPENV_UV_VERBOSE"):
        import json

        data = {"constraints": constraints, "cmd": cmd}
        logger.info(
            "\nRunning uv pip compile with data: %s",
            json.dumps(data, default=str, indent=2),
        )

    sources = project.pipfile_sources()
    if not sources:
        raise ValueError("No sources found in Pipfile")
    default_source, *_other_sources = sources

    # Build default constraints for non-default categories (e.g. dev-packages)
    # This mirrors pip resolver's cross-category constraint behavior
    import tempfile

    default_constraint_args = []
    default_constraint_tmpfile = None
    category = parsed.category or "default"
    if category != "default" and project.settings.get("use_default_constraints", True):
        from pipenv.utils.dependencies import get_constraints_from_deps

        default_constraints = get_constraints_from_deps(project.packages)
        if default_constraints:
            default_constraint_tmpfile = tempfile.NamedTemporaryFile(
                mode="w",
                prefix="pipenv-uv-",
                suffix="-default-constraints.txt",
                delete=False,
            )
            default_constraint_tmpfile.write("\n".join(sorted(default_constraints)))
            default_constraint_tmpfile.close()
            default_constraint_args = [f"--constraint={default_constraint_tmpfile.name}"]

    uv_bin = find_uv_bin()

    # Build --allow-insecure-host args for sources with verify_ssl: false
    insecure_host_args = []
    for source in [default_source, *sources]:
        if not source.get("verify_ssl", True):
            from urllib.parse import urlparse

            parsed_url = urlparse(source["url"])
            host = parsed_url.hostname or ""
            if host:
                port = parsed_url.port
                host_with_port = f"{host}:{port}" if port else host
                insecure_host_args.append(f"--allow-insecure-host={host_with_port}")

    uv_cmd = [
        uv_bin,
        "pip",
        "compile",
        f"--python={project.python(parsed.system)}",
        "--format=requirements.txt",
        "--generate-hashes",
        "--no-strip-extras",
        "--no-strip-markers",
        "--no-annotate",
        "--no-header",
        "--emit-index-annotation",
        "--quiet",
        f"--default-index={default_source['url']}",
        *(f"--index={source['url']}" for source in sources),
        *(("--prerelease=allow",) if parsed.pre else ()),
        "--index-strategy=unsafe-best-match",
        "--universal",
        *insecure_host_args,
        *default_constraint_args,
        "-",
    ]

    if os.environ.get("PIPENV_UV_VERBOSE"):
        logger.info("\nRunning command: %s", " ".join(uv_cmd))

    st.console.print("[bold green]Using uv for dependency resolution[/bold green]")
    result = subprocess.run(
        uv_cmd,
        input="\n".join(constraints.values()),
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        logger.error("uv pip compile failed (rc=%d)", result.returncode)
        logger.error("stdout: %s", result.stdout)
        logger.error("stderr: %s", result.stderr)
        logger.error("Falling back to pip resolver")
        # Clean up temporary constraint file
        if default_constraint_tmpfile is not None:
            try:
                os.unlink(default_constraint_tmpfile.name)
            except OSError:
                pass
        return _original_resolve(cmd, st, project)

    packages, _index, index_annotations = parse_requirements_lines(
        result.stdout.splitlines()
    )

    # Post-process: detect extras-only dependencies and add appropriate markers.
    # uv doesn't emit ``extra == '<name>'`` markers like pip does.  We detect
    # extras in the constraints, re-resolve without them, and diff to find
    # which packages are extras-only.
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    extras_constraints = {}  # {constraint_name: [extras]}
    non_extras_lines = []
    for _name, pip_line in constraints.items():
        stripped = pip_line.strip()
        # Check for extras like "requests[socks]" or "requests[socks,security]"
        bracket_match = re.match(r"^([^\[]+)\[([^\]]+)\](.*)", stripped)
        if bracket_match:
            base_pkg = bracket_match.group(1).strip()
            extras_list = [e.strip() for e in bracket_match.group(2).split(",")]
            rest_of_line = bracket_match.group(3).strip()
            extras_constraints[canonicalize_name(base_pkg)] = extras_list
            # Add the base package (without extras) for comparison resolution
            non_extras_lines.append(f"{base_pkg}{rest_of_line}")
        else:
            non_extras_lines.append(stripped)

    extras_only_packages = set()
    if extras_constraints and non_extras_lines:
        # Resolve without extras to find base dependencies
        no_extras_result = subprocess.run(
            uv_cmd,
            input="\n".join(non_extras_lines),
            text=True,
            capture_output=True,
            check=False,
        )
        if os.environ.get("PIPENV_UV_VERBOSE"):
            logger.info(
                "Extras detection: extras_constraints=%s, non_extras_lines=%s, no_extras_rc=%d, no_extras_stderr=%s",
                extras_constraints,
                non_extras_lines,
                no_extras_result.returncode,
                no_extras_result.stderr[:500] if no_extras_result.stderr else "",
            )
        if no_extras_result.returncode == 0:
            base_packages, _, _ = parse_requirements_lines(
                no_extras_result.stdout.splitlines()
            )
            base_canonical = {canonicalize_name(n) for n in base_packages}
            all_canonical = {canonicalize_name(n) for n in packages}
            extras_only_packages = all_canonical - base_canonical
            if os.environ.get("PIPENV_UV_VERBOSE"):
                logger.info(
                    "Extras detection: base_pkgs=%s, all_pkgs=%s, extras_only=%s",
                    base_canonical,
                    all_canonical,
                    extras_only_packages,
                )

    # Clean up temporary constraint file (after the second resolve above)
    if default_constraint_tmpfile is not None:
        try:
            os.unlink(default_constraint_tmpfile.name)
        except OSError:
            pass

    if extras_only_packages:
        # Build a mapping of extras-only package → which extra(s) pulled them in.
        all_extras = []
        for _pkg, elist in extras_constraints.items():
            all_extras.extend(elist)

        if os.environ.get("PIPENV_UV_VERBOSE"):
            logger.info(
                "Applying extras markers: extras_only=%s, all_extras=%s, packages_keys=%s",
                extras_only_packages,
                all_extras,
                list(packages.keys()),
            )

        for pkg_name, pkg_entry in packages.items():
            canonical = canonicalize_name(pkg_name)
            if canonical in extras_only_packages:
                # Find which extra(s) this package is associated with
                # For single-extra cases, just use that extra directly
                if len(all_extras) == 1:
                    marker = f"extra == '{all_extras[0]}'"
                else:
                    # Multiple extras — try to determine which one
                    # by checking each extra individually.  If too complex,
                    # just combine them with "or".
                    marker = " or ".join(
                        f"extra == '{e}'" for e in sorted(set(all_extras))
                    )
                existing = pkg_entry.get("markers", "")
                if existing:
                    pkg_entry["markers"] = f"{existing} and {marker}"
                else:
                    pkg_entry["markers"] = marker

    # Post-process: re-apply Pipfile-specified markers to uv output.
    # uv's universal resolver doesn't preserve user-specified markers from
    # the Pipfile (e.g. os_name = "== 'splashwear'").  We merge them in.
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    pipfile_markers = _get_pipfile_markers(project, category)
    if pipfile_markers:
        for pkg_name, pkg_entry in packages.items():
            canonical = canonicalize_name(pkg_name)
            if canonical in pipfile_markers:
                user_marker = pipfile_markers[canonical]
                existing = pkg_entry.get("markers", "")
                if existing:
                    # Combine: existing AND user marker
                    pkg_entry["markers"] = f"{existing} and {user_marker}"
                else:
                    pkg_entry["markers"] = user_marker

    # Post-process: add index field for top-level packages that have an
    # explicit index in the Pipfile.  uv doesn't output index info, but
    # pip's resolver tracks it via index_lookup.  We only add it for
    # top-level deps because sub-deps index tracking is handled downstream
    # by get_locked_dep() -> clean_resolved_dep() which merges the Pipfile.
    pipfile_indexes = _get_pipfile_index_for_deps(project, category)
    if pipfile_indexes:
        for pkg_name, pkg_entry in packages.items():
            canonical = canonicalize_name(pkg_name)
            if canonical in pipfile_indexes:
                pkg_entry["index"] = pipfile_indexes[canonical]

    # Build a URL-to-source-name mapping from project sources.  When
    # ``--emit-index-annotation`` is used, uv tells us which index URL each
    # package was resolved from (``index_annotations``).  We normalise the
    # URLs to allow matching with or without trailing slashes.
    all_sources = project.pipfile_sources()
    url_to_source_name = {}
    for src in all_sources:
        src_url = src["url"].rstrip("/")
        url_to_source_name[src_url] = src["name"]

    default_index_name = project.get_default_index()["name"]

    for pkg_name, pkg_entry in packages.items():
        if "index" in pkg_entry or "file" in pkg_entry or "git" in pkg_entry:
            continue
        canonical = canonicalize_name(pkg_name)
        annotation_url = index_annotations.get(canonical, "").rstrip("/")
        if annotation_url and annotation_url in url_to_source_name:
            pkg_entry["index"] = url_to_source_name[annotation_url]
        else:
            # Fallback: assign the default index name.  This mirrors what
            # the pip resolver does via index_lookup in Resolver.create().
            pkg_entry["index"] = default_index_name

    import json

    output_data = [{"name": k, **v} for k, v in packages.items()]
    if os.environ.get("PIPENV_UV_VERBOSE"):
        logger.info(
            "Writing resolved packages to %s: %s",
            write,
            json.dumps(output_data, indent=2),
        )

    with open(write, "w") as f:
        f.write(json.dumps(output_data))

    return result


def _should_fall_back_to_pip(args):
    """Check if any requirements file in the args contains packages uv can't handle.

    This includes:
    - Editable VCS packages (``-e git+...``) — uv requires editable to be local dir
    - Local path packages (``.``, ``./path``, ``/path``, ``file://``) — uv has
      issues with paths containing spaces, special chars, and file:// URIs

    :param args: Command argument list (may contain ``-r <file>`` pairs)
    :return: True if any requirements file contains unsupported lines
    """
    req_files = []
    it = iter(args)
    for arg in it:
        if arg == "-r":
            try:
                req_files.append(next(it))
            except StopIteration:
                break
        elif arg.startswith("-r"):
            req_files.append(arg[2:])

    for req_file in req_files:
        try:
            with open(req_file) as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    # Editable VCS: -e git+...
                    if stripped.startswith("-e ") and "git+" in stripped:
                        return True
                    # Local paths / file:// URIs
                    if _is_local_path_or_file_uri(stripped):
                        return True
        except OSError:
            continue
    return False


def _make_uv_subprocess_run(project):
    """Create a ``subprocess_run`` replacement bound to a specific project.

    The returned function rewrites ``pip install`` commands to ``uv pip install``
    and ensures all project source indexes are included so uv can find
    packages across all configured indexes.

    :param project: The pipenv Project instance (used for source URLs)
    :return: A replacement for ``subprocess_run``
    """

    def _uv_subprocess_run(
        args,
        *,
        block=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        env=None,
        **other_kwargs,
    ):
        if block:
            raise ValueError("uv subprocess patch only supports non-blocking calls")

        # Check if the requirements contain packages that uv can't handle.
        # Fall back to the original subprocess_run (pip) for those.
        if _should_fall_back_to_pip(args):
            logger.info(
                "Unsupported package type detected, falling back to pip for this batch"
            )
            from pipenv.utils.processes import subprocess_run as original_subprocess_run

            return original_subprocess_run(
                args,
                block=block,
                text=text,
                capture_output=capture_output,
                encoding=encoding,
                env=env,
                **other_kwargs,
            )

        _env = os.environ.copy()
        _env["PYTHONIOENCODING"] = encoding
        if env:
            string_env = {k: str(v) for k, v in env.items() if v is not None}
            _env.update(string_env)
        other_kwargs["env"] = _env

        if capture_output:
            other_kwargs["stdout"] = subprocess.PIPE
            other_kwargs["stderr"] = subprocess.PIPE

        # Original args: [python, <runnable_pip>, install, ...pip_flags]
        python, _pip_file, _install_verb, *rest = args

        uv_bin = find_uv_bin()

        # Remove --no-input which uv doesn't understand
        if "--no-input" in rest:
            rest.remove("--no-input")

        # Rewrite pip index flags to uv equivalents and ensure all project
        # sources are included.  The original pip command may use:
        #   -i <url>               → primary index
        #   --extra-index-url <url> → additional indexes
        #   --trusted-host <host>   → trusted (non-SSL) hosts
        # uv equivalents:
        #   --default-index=<url>   (or -i, deprecated but works)
        #   --index=<url>           (or --extra-index-url, deprecated)
        #   --trusted-host <host>   (supported)
        #
        # We strip the original index flags and rebuild from project sources
        # to ensure ALL configured indexes are available during install.
        cleaned_rest = []
        skip_next = False
        for i, arg in enumerate(rest):
            if skip_next:
                skip_next = False
                continue
            if arg in ("-i", "--extra-index-url", "--trusted-host"):
                skip_next = True
                continue
            if arg.startswith(("-i=", "--extra-index-url=", "--trusted-host=")):
                continue
            cleaned_rest.append(arg)

        # Build index args from all project sources
        sources = project.pipfile_sources()
        index_args = []
        if sources:
            index_args.append(f"--default-index={sources[0]['url']}")
            if not sources[0].get("verify_ssl", True):
                from pipenv.patched.pip._vendor.urllib3.util import parse_url

                url_parts = parse_url(sources[0]["url"])
                url_port = f":{url_parts.port}" if url_parts.port else ""
                index_args.extend(["--trusted-host", f"{url_parts.host}{url_port}"])
            for source in sources[1:]:
                url = source.get("url")
                if not url:
                    continue
                index_args.append(f"--index={url}")
                if not source.get("verify_ssl", True):
                    from pipenv.patched.pip._vendor.urllib3.util import parse_url

                    url_parts = parse_url(url)
                    url_port = f":{url_parts.port}" if url_parts.port else ""
                    index_args.extend(["--trusted-host", f"{url_parts.host}{url_port}"])

        uv_args = [
            uv_bin,
            "pip",
            "install",
            f"--python={python}",
            f"--prefix={os.path.dirname(os.path.dirname(python))}",
            "--index-strategy=unsafe-best-match",
            *index_args,
            *cleaned_rest,
        ]

        if os.environ.get("PIPENV_UV_VERBOSE"):
            logger.info("\nRunning command: %s", " ".join(uv_args))

        return subprocess.Popen(
            uv_args,
            universal_newlines=text,
            encoding=encoding,
            **other_kwargs,
        )

    return _uv_subprocess_run


def uv_pip_install_deps(
    project,
    deps,
    sources,
    allow_global=False,
    ignore_hashes=False,
    no_deps=False,
    requirements_dir=None,
    use_pep517=True,
    extra_pip_args=None,
):
    """Replacement for ``pipenv.utils.pip.pip_install_deps`` that uses uv.

    Wraps the original function, temporarily patching ``subprocess_run``
    in ``pipenv.utils.pip`` to redirect pip install commands to uv.
    """
    if _original_pip_install_deps is None:
        raise RuntimeError("Original pip_install_deps function is not available")

    global _install_message_shown
    if not _install_message_shown:
        import sys

        print("Using uv for package installation", file=sys.stderr)
        _install_message_shown = True

    from unittest.mock import patch

    import pipenv.utils.pip

    _uv_subprocess_run = _make_uv_subprocess_run(project)

    with patch.object(pipenv.utils.pip, "subprocess_run", _uv_subprocess_run):
        return _original_pip_install_deps(
            project=project,
            deps=deps,
            sources=sources,
            allow_global=allow_global,
            ignore_hashes=ignore_hashes,
            no_deps=no_deps,
            requirements_dir=requirements_dir,
            use_pep517=use_pep517,
            extra_pip_args=extra_pip_args,
        )


def patch():
    """Apply uv monkey-patches to pipenv's resolver and installer.

    This is a no-op if:
    - Already patched
    - ``PIPENV_UV`` is not set / falsy
    - The uv binary cannot be found

    Individual patches can be disabled via:
    - ``PIPENV_UV_NO_RESOLVE`` -- skip resolution patch
    - ``PIPENV_UV_NO_INSTALL`` -- skip installation patch
    """
    global _original_resolve, _original_pip_install_deps

    # Idempotent
    if _original_resolve is not None or _original_pip_install_deps is not None:
        return

    # Check master switch
    from pipenv.utils.shell import env_to_bool

    uv_enabled = os.environ.get("PIPENV_UV", "")
    if not uv_enabled:
        return
    try:
        if not env_to_bool(uv_enabled):
            return
    except ValueError:
        # Non-boolean string value — treat as truthy
        pass

    # Verify uv is available before patching
    try:
        uv_path = find_uv_bin()
        logger.debug("Found uv at: %s", uv_path)
    except FileNotFoundError:
        logger.warning(
            "PIPENV_UV is set but uv binary was not found. Install uv via 'pip install uv' or ensure it is on PATH."
        )
        return

    # Patch resolver
    if not os.environ.get("PIPENV_UV_NO_RESOLVE"):
        from pipenv.utils import resolver

        _original_resolve = resolver.resolve
        resolver.resolve = uv_resolve
        logger.debug("Patched pipenv.utils.resolver.resolve with uv_resolve")

    # Patch installer
    if not os.environ.get("PIPENV_UV_NO_INSTALL"):
        from pipenv.utils import pip

        _original_pip_install_deps = pip.pip_install_deps
        pip.pip_install_deps = uv_pip_install_deps
        logger.debug("Patched pipenv.utils.pip.pip_install_deps with uv_pip_install_deps")
