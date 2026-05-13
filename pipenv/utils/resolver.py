import contextlib
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from pipenv import environments
from pipenv.exceptions import ResolutionFailure
from pipenv.patched.pip._internal.cache import WheelCache
from pipenv.patched.pip._internal.cli.cmdoptions import check_release_control_exclusive

# ``InstallCommand`` is only constructed in :meth:`Resolver._get_pip_command`
# (one call site) — defer the import so loading ``pipenv.utils.resolver``
# doesn't drag in pip's command/network/CLI machinery (~79 ms cum) until
# the resolver actually instantiates the command.  The resolver subprocess
# pays this cost on every ``pipenv lock`` invocation; the in-process
# debug path pays it once per session.
from pipenv.patched.pip._internal.exceptions import InstallationError
from pipenv.patched.pip._internal.models.target_python import TargetPython
from pipenv.patched.pip._internal.operations.build.build_tracker import (
    get_build_tracker,
)
from pipenv.patched.pip._internal.req.constructors import (
    install_req_from_parsed_requirement,
)
from pipenv.patched.pip._internal.req.req_file import parse_requirements
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.utils.temp_dir import global_tempdir_manager
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    InternalError,
    LockedRequirement,
    PackageSpecs,
    RequestMetadata,
    ResolutionError,
    ResolvedDeps,
    ResolverOptions,
    ResolverRequest,
    ResolverResponse,
    ResolverSuccess,
)
from pipenv.resolver.schema import Source as ResolverSource
from pipenv.utils import console, err
from pipenv.utils.dependencies import determine_vcs_revision_hash, normalize_vcs_url
from pipenv.utils.fileutils import create_tracked_tempdir

from .dependencies import (
    HackedPythonVersion,
    convert_deps_to_pip,
    expansive_install_req_from_line,
    get_constraints_from_deps,
    get_lockfile_section_using_pipfile_category,
    is_pinned_requirement,
    pep423_name,
    prepare_constraint_file,
)
from .indexes import parse_indexes, prepare_pip_source_args
from .internet import is_pypi_url, write_credentials_netrc
from .locking import prepare_lockfile
from .shell import make_posix, subprocess_run, temp_environ


def _is_python_version_specifier(value):
    """Return True if *value* looks like a PEP 440 specifier (e.g. ``>=3.9``)
    rather than a literal version string.  Literal versions contain only digits
    and dots; anything else indicates a specifier expression.
    """
    return any(not (ch.isdigit() or ch == ".") for ch in value)


def _get_pipfile_python_override(project):
    """Determine python_version and python_full_version overrides from the Pipfile.

    When the Pipfile specifies ``python_version = "3.11"`` (major.minor only),
    the resolver should evaluate markers as if ``python_full_version`` were
    ``"3.11.0"`` — the lowest patch release for that minor series.  This ensures
    that dependencies guarded by markers like
    ``python_full_version <= "3.11.2"`` are *included* in the lock file so that
    the lock file is portable across all patch releases of that minor version.

    If the Pipfile instead specifies a PEP 440 specifier (e.g. ``">=3.9"``),
    no concrete single version is implied; we return None so that the running
    interpreter's actual version is used for marker evaluation.  See #6645.

    Returns a dict with ``python_version`` and ``python_full_version`` keys
    suitable for passing as an environment override, or *None* if no override
    is needed.
    """
    if not project.pipfile.exists:
        return None

    requires = project.pipfile.parsed.get("requires", {})
    python_full = requires.get("python_full_version")
    python_ver = requires.get("python_version")

    if python_full and python_full != "*":
        if _is_python_version_specifier(python_full):
            # Range/specifier — no single concrete version implied.
            return None
        # Explicit full version — use it directly.
        parts = python_full.split(".")
        return {
            "python_full_version": python_full,
            "python_version": ".".join(parts[:2]),
        }

    if python_ver and python_ver != "*":
        if _is_python_version_specifier(python_ver):
            # Range/specifier — no single concrete version implied.
            return None
        parts = python_ver.split(".")
        if len(parts) < 2:
            # Major-only version (e.g. "3") is too imprecise for marker
            # evaluation — don't override, let the running interpreter's
            # actual version be used.
            return None
        # Only major.minor specified — use the running interpreter's actual
        # patch version so that markers like ``python_full_version >= "3.11.4"``
        # evaluate correctly.  Previously we assumed ".0" which caused
        # ResolutionTooDeep failures by wrongly excluding packages.
        import platform

        actual_full = platform.python_version()  # e.g. "3.11.15"
        actual_major_minor = ".".join(actual_full.split(".")[:2])
        if actual_major_minor == python_ver:
            # Running interpreter matches the Pipfile — use its real patch.
            full_version = actual_full
        else:
            # Different minor version — fall back to .0 (best guess).
            full_version = f"{python_ver}.0"
        return {
            "python_full_version": full_version,
            "python_version": python_ver,
        }

    return None


@contextlib.contextmanager
def _patched_marker_environment(override):
    """Context manager that monkey-patches ``default_environment`` in pip's
    vendored ``packaging.markers`` so that marker evaluation during dependency
    resolution uses the Pipfile-specified Python version rather than the
    running interpreter's version.

    Only ``python_version`` and ``python_full_version`` are overridden; all
    other environment markers (``os_name``, ``sys_platform``, etc.) remain
    unchanged.
    """
    if not override:
        yield
        return

    import pipenv.patched.pip._vendor.packaging.markers as pip_markers

    _orig = pip_markers.default_environment

    def _patched_default_environment():
        env = _orig()
        env["python_version"] = override["python_version"]
        env["python_full_version"] = override["python_full_version"]
        return env

    pip_markers.default_environment = _patched_default_environment
    try:
        yield
    finally:
        pip_markers.default_environment = _orig


def get_package_finder(
    install_cmd=None,
    options=None,
    session=None,
    platform=None,
    python_versions=None,
    abi=None,
    implementation=None,
    ignore_requires_python=None,
    py_version_info=None,
):
    """Reduced Shim for compatibility to generate package finders."""
    if py_version_info is None and python_versions:
        py_version_info_python = max(python_versions)
        py_version_info = tuple([int(part) for part in py_version_info_python])
    target_python = TargetPython(
        platforms=[platform] if platform else None,
        py_version_info=py_version_info,
        abis=[abi] if abi else None,
        implementation=implementation,
    )
    return install_cmd._build_package_finder(
        options=options,
        session=session,
        target_python=target_python,
        ignore_requires_python=ignore_requires_python,
    )


class HashCacheMixin:
    """Caches hashes of PyPI artifacts so we do not need to re-download them.

    Hashes are only cached when the URL appears to contain a hash in it and the
    cache key includes the hash value returned from the server). This ought to
    avoid issues where the location on the server changes.
    """

    def __init__(self, project, session):
        self.project = project
        self.session = session

    def get_hash(self, link):
        hash_value = self.project.get_file_hash(self.session, link).encode()
        return hash_value.decode("utf8")


def _format_resolution_error(install_error):
    """Extract and format conflict details from an InstallationError exception chain.

    When pip raises an InstallationError due to a ResolutionImpossible, the original
    ResolutionImpossible exception (with its ``causes`` list) is attached as
    ``install_error.__cause__``. This helper traverses that chain and builds a
    human-readable summary of the conflicting requirements so users can diagnose
    the problem without needing to re-run with ``--verbose``.

    Also handles MetadataGenerationFailed with actionable hints (#5155).
    """
    # Detect MetadataGenerationFailed specifically and emit an actionable hint.
    try:
        from pipenv.patched.pip._internal.exceptions import MetadataGenerationFailed

        if isinstance(install_error, MetadataGenerationFailed):
            pkg_name = getattr(install_error, "package_name", None) or "a package"
            return (
                f"Metadata generation failed for {pkg_name}.\n\n"
                "This usually means the package uses a legacy build system "
                "(setup.py egg_info) that is incompatible with modern pip.\n\n"
                "Possible causes and fixes:\n"
                "  1. The package version is too old — try upgrading to a newer release.\n"
                "  2. A file named 'util.py', 'setup.py', or similar in your project\n"
                "     directory is shadowing a system module. Rename or move it.\n"
                "  3. Missing build dependencies (e.g. setuptools, wheel) — run:\n"
                "       pipenv run pip install --upgrade setuptools wheel\n"
                "  4. Re-run with --verbose for the full pip build log."
            )
    except ImportError:
        pass

    base_msg = str(install_error)

    # Walk the exception chain to find a ResolutionImpossible cause
    cause = getattr(install_error, "__cause__", None)
    resolution_impossible = None
    while cause is not None:
        # Import lazily to avoid circular imports at module level
        try:
            from pipenv.patched.pip._vendor.resolvelib import ResolutionImpossible

            if isinstance(cause, ResolutionImpossible):
                resolution_impossible = cause
                break
        except ImportError:
            break
        cause = getattr(cause, "__cause__", None)

    if resolution_impossible is None or not getattr(
        resolution_impossible, "causes", None
    ):
        return base_msg

    lines = [base_msg, "\nThe conflict is caused by:"]
    for req_info in resolution_impossible.causes:
        requirement = getattr(req_info, "requirement", None)
        parent = getattr(req_info, "parent", None)
        if requirement is None:
            continue
        req_str = (
            requirement.format_for_error()
            if hasattr(requirement, "format_for_error")
            else str(requirement)
        )
        if parent is not None:
            parent_name = getattr(parent, "name", str(parent))
            parent_version = getattr(parent, "version", "")
            prefix = f"    {parent_name} {parent_version} depends on "
        else:
            prefix = "    The user requested "
        lines.append(prefix + req_str)

    return "\n".join(lines)


class Resolver:
    def __init__(
        self,
        constraints,
        req_dir,
        project,
        sources,
        index_lookup=None,
        markers_lookup=None,
        skipped=None,
        clear=False,
        pre=False,
        lockfile_category=None,
        original_deps=None,
        install_reqs=None,
        pipfile_entries=None,
        resolved_default_deps=None,
        extra_pip_args=None,
    ):
        self.initial_constraints = constraints
        self.req_dir = req_dir
        self.project = project
        self.sources = sources
        self.resolved_tree = set()
        self.hashes = {}
        self.clear = clear
        self.pre = pre
        self.category = lockfile_category
        self.results = None
        self.markers_lookup = markers_lookup if markers_lookup is not None else {}
        self.index_lookup = index_lookup if index_lookup is not None else {}
        self.skipped = skipped if skipped is not None else {}
        self.markers = {}
        self.requires_python_markers = {}
        # Resolved lockfile entries from the default category (including transitive
        # deps).  When set, these are used as constraints for non-default categories
        # instead of the raw Pipfile [packages] specs.  See gh-4665.
        self.resolved_default_deps = resolved_default_deps
        self.original_deps = original_deps if original_deps is not None else {}
        self.install_reqs = install_reqs if install_reqs is not None else {}
        self.pipfile_entries = pipfile_entries
        # T_F.3 B2: ``extra_pip_args`` used to flow in through a
        # parent-set environment-variable hop.  After the typed-schema
        # rewrite the parent passes it through the typed
        # ``ResolverRequest`` (subprocess path) or directly into
        # ``Resolver.create`` (in-process path).  See
        # ``prepare_pip_args`` below.
        self.extra_pip_args = list(extra_pip_args or [])
        self._retry_attempts = 0
        self._hash_cache = None
        self._constraint_file = None
        self._default_constraint_file = None
        self._parsed_constraints = None
        self._parsed_default_constraints = None
        self._hash_finder = None
        self._prepared_index_lookup = None

    def __repr__(self):
        return (
            f"<Resolver (constraints={self.initial_constraints}, req_dir={self.req_dir}, "
            f"sources={self.sources})>"
        )

    @staticmethod
    def _get_pip_command():
        from pipenv.patched.pip._internal.commands.install import InstallCommand

        return InstallCommand(name="InstallCommand", summary="pip Install command.")

    @property
    def hash_cache(self):
        if not self._hash_cache:
            self._hash_cache = HashCacheMixin(self.project, self.session)
        return self._hash_cache

    def check_if_package_req_skipped(
        self,
        req: InstallRequirement,
    ) -> bool:
        if req.markers and not req.markers.evaluate():
            err.print(
                f"Could not find a matching version of {req}; {req.markers} for your environment, "
                "its dependencies will be skipped.",
            )
            return True
        return False

    @classmethod
    def create(
        cls,
        deps: Dict[str, str],
        project,
        index_lookup: Dict[str, str] = None,
        markers_lookup: Dict[str, str] = None,
        sources: List[str] = None,
        req_dir: str = None,
        clear: bool = False,
        pre: bool = False,
        pipfile_category: str = None,
        resolved_default_deps: Dict[str, Any] = None,
        extra_pip_args: List[str] = None,
    ) -> "Resolver":
        if not req_dir:
            req_dir = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")
        if index_lookup is None:
            index_lookup = {}
        if markers_lookup is None:
            markers_lookup = {}
        original_deps = {}
        install_reqs = {}
        pipfile_entries = project.pipfile.get_section(pipfile_category)
        skipped = {}
        if sources is None:
            # Always read sources from the Pipfile, not from the (potentially
            # stale) lockfile _meta.sources.  This ensures settings like
            # ``verify_ssl = false`` are respected even when an old lockfile
            # still carries ``verify_ssl = true``.  See gh-5665.
            sources = project.sources.pipfile_sources()
        packages = project.pipfile.get_section(pipfile_category)
        constraints = set()
        for package_name, dep in deps.items():  # Build up the index and markers lookups
            if not dep:
                continue
            canonical_package_name = canonicalize_name(package_name)
            is_constraint = True
            install_req, _ = expansive_install_req_from_line(dep, expand_env=True)
            original_deps[package_name] = dep
            install_reqs[package_name] = install_req
            index, extra_index, trust_host, remainder = parse_indexes(dep)
            if package_name in packages:
                pipfile_entry = pipfile_entries.get(package_name)
                if isinstance(pipfile_entry, dict):
                    if packages[package_name].get("index"):
                        index_lookup[canonical_package_name] = packages[package_name].get(
                            "index"
                        )
                    if packages[package_name].get("skip_resolver"):
                        is_constraint = False
                        skipped[package_name] = dep
                elif index:
                    index_lookup[canonical_package_name] = index
                else:
                    index_lookup[canonical_package_name] = project.sources.get_default_index()[
                        "name"
                    ]
            if install_req.markers:
                markers_lookup[package_name] = install_req.markers
            if is_constraint:
                constraints.add(dep)

        # For non-default categories (e.g. dev-packages, custom groups), also
        # populate index_lookup with index information from *all other* Pipfile
        # sections.  This is necessary so that transitive dependencies of the
        # current category that happen to be explicitly listed in another
        # section (most commonly [packages]) can still be found on the correct
        # private index when the resolver uses index_restricted=True.
        #
        # Example: if [packages] has ``private_lib = {index = "private"}`` and
        # [dev-packages] has ``dev_tool`` which depends on ``private_lib``,
        # locking [dev-packages] would fail because ``private_lib`` was not in
        # index_lookup and pip therefore tried the default (PyPI) index only.
        if pipfile_category and pipfile_category != "packages":
            for other_category in project.pipfile.get_package_categories():
                if other_category == pipfile_category:
                    continue
                other_packages = project.pipfile.get_section(other_category)
                for pkg_name, pkg_entry in other_packages.items():
                    canonical_pkg_name = canonicalize_name(pkg_name)
                    # Don't override entries already set for the current category
                    if canonical_pkg_name not in index_lookup:
                        if isinstance(pkg_entry, dict) and pkg_entry.get("index"):
                            index_lookup[canonical_pkg_name] = pkg_entry["index"]

        lockfile_category = get_lockfile_section_using_pipfile_category(pipfile_category)
        resolver = Resolver(
            set(),
            req_dir,
            project,
            sources,
            index_lookup=index_lookup,
            markers_lookup=markers_lookup,
            skipped=skipped,
            clear=clear,
            pre=pre,
            lockfile_category=lockfile_category,
            original_deps=original_deps,
            install_reqs=install_reqs,
            pipfile_entries=pipfile_entries,
            resolved_default_deps=resolved_default_deps,
            extra_pip_args=extra_pip_args,
        )
        for package_name, dep in original_deps.items():
            install_req = install_reqs[package_name]
            if resolver.check_if_package_req_skipped(install_req):
                resolver.skipped[package_name] = dep
        resolver.initial_constraints = constraints
        resolver.index_lookup = index_lookup
        resolver.markers_lookup = markers_lookup
        return resolver

    @property
    def pip_command(self):
        return self._get_pip_command()

    def prepare_pip_args(self, use_pep517=None, build_isolation=True):
        pip_args = []
        if self.sources:
            pip_args = prepare_pip_source_args(self.sources, pip_args)
        if use_pep517 is False:
            pip_args.append("--no-use-pep517")
        if build_isolation is False:
            pip_args.append("--no-build-isolation")
        if self.pre:
            pip_args.append("--pre")
        pip_args.extend(["--cache-dir", self.project.s.PIPENV_CACHE_DIR])
        # T_F.3 B2: ``extra_pip_args`` flows through the
        # ``Resolver`` instance (set in ``__init__`` from the typed
        # ``ResolverRequest`` on the subprocess path, or from the parent's
        # ``actually_resolve_deps`` call on the in-process path) rather
        # than the legacy env-var hop.
        if self.extra_pip_args:
            pip_args.extend(self.extra_pip_args)
        return pip_args

    @property  # cached_property breaks authenticated private indexes
    def pip_args(self):
        use_pep517 = environments.get_from_env("USE_PEP517", prefix="PIP")
        build_isolation = environments.get_from_env("BUILD_ISOLATION", prefix="PIP")
        return self.prepare_pip_args(
            use_pep517=use_pep517, build_isolation=build_isolation
        )

    def prepare_constraint_file(self):
        if self._constraint_file is not None:
            return self._constraint_file
        constraint_filename = prepare_constraint_file(
            self.initial_constraints,
            directory=self.req_dir,
            sources=self.sources,
            pip_args=self.pip_args,
        )
        self._constraint_file = constraint_filename
        return constraint_filename

    @property
    def default_constraint_file(self):
        if self._default_constraint_file is not None:
            return self._default_constraint_file

        # When resolved default deps are available (passed from do_lock after
        # resolving the default category), use them.  They include transitive
        # dependencies and exact version pins, which is critical for ensuring
        # non-default categories resolve compatible versions.  See gh-4665.
        if self.resolved_default_deps:
            from .dependencies import get_constraints_from_resolved_deps

            default_constraints = get_constraints_from_resolved_deps(
                self.resolved_default_deps
            )
        else:
            default_constraints = get_constraints_from_deps(self.project.pipfile.packages)
        default_constraint_filename = prepare_constraint_file(
            default_constraints,
            directory=self.req_dir,
            sources=None,
            pip_args=None,
        )
        self._default_constraint_file = default_constraint_filename
        return default_constraint_filename

    @property
    def target_py_version_info(self):
        """Extract the target Python version tuple from the Pipfile override."""
        override = _get_pipfile_python_override(self.project)
        if override:
            parts = override["python_full_version"].split(".")
            return tuple(int(part) for part in parts)
        return None

    @property  # cached_property breaks authenticated private indexes
    def pip_options(self):
        pip_options, _ = self.pip_command.parser.parse_args(self.pip_args)
        pip_options.cache_dir = self.project.s.PIPENV_CACHE_DIR
        pip_options.no_python_version_warning = True
        pip_options.no_input = self.project.settings.get("disable_pip_input", True)
        pip_options.progress_bar = "off"
        pip_options.ignore_requires_python = False
        pip_options.pre = self.pre or self.project.settings.get(
            "allow_prereleases", False
        )
        # Allow the user to override the keyring provider so that credential
        # managers (e.g. Windows Credential Manager) work even when pip input
        # is disabled.  See https://github.com/pypa/pipenv/issues/5715
        keyring_provider = self.project.s.PIPENV_KEYRING_PROVIDER
        if keyring_provider:
            pip_options.keyring_provider = keyring_provider
        # In pip 26+, setting options.pre=True is no longer sufficient to
        # enable pre-release resolution. pip's PackageFinder uses
        # release_control.all_releases to determine whether pre-releases are
        # allowed, and check_release_control_exclusive() is what transforms
        # options.pre=True into release_control.all_releases={":all:"}.
        # pip's own commands (install, download, lock) call this in run(),
        # but pipenv bypasses those entry points, so we must call it here.
        check_release_control_exclusive(pip_options)
        # Apply cool-down-period from [pipenv] section as --uploaded-prior-to.
        # Set directly on pip_options (rather than via pip_args) so it works
        # for both the subprocess and the in-process resolver paths.
        cool_down = _get_cool_down_timedelta(self.project)
        if cool_down is not None:
            import datetime as _dt
            pip_options.uploaded_prior_to = _dt.datetime.now(_dt.timezone.utc) - cool_down
        return pip_options

    @property  # Remove cached_property to prevent stale sessions and authentication issues
    def session(self):
        return self.pip_command._build_session(self.pip_options)

    def prepare_index_lookup(self):
        # sources and index_lookup are stable after Resolver.create() returns;
        # cache the prepared mapping so each finder() call doesn't rebuild it.
        if self._prepared_index_lookup is not None:
            return self._prepared_index_lookup
        index_mapping = {}
        for source in self.sources:
            if source.get("name"):
                index_mapping[source["name"]] = source["url"]
        alt_index_lookup = {}
        for req_name, index in self.index_lookup.items():
            if index_mapping.get(index):
                alt_index_lookup[req_name] = [index_mapping[index]]
        self._prepared_index_lookup = alt_index_lookup
        return alt_index_lookup

    @property
    def package_finder(self):
        py_version_info = self.target_py_version_info
        finder = get_package_finder(
            install_cmd=self.pip_command,
            options=self.pip_options,
            session=self.session,
            py_version_info=py_version_info,
        )
        return finder

    def finder(self, ignore_compatibility=False):
        finder = self.package_finder
        index_lookup = self.prepare_index_lookup()
        finder._link_collector.index_lookup = index_lookup
        # SearchScope is a frozen dataclass, so we need to use replace() to create
        # a new instance with the updated fields
        finder._link_collector.search_scope = dataclasses.replace(
            finder._link_collector.search_scope,
            index_restricted=True,
            index_lookup=index_lookup,
        )
        finder._ignore_compatibility = ignore_compatibility
        return finder

    @property
    def parsed_default_constraints(self):
        if self._parsed_default_constraints is not None:
            return self._parsed_default_constraints

        pip_options = self.pip_options
        pip_options.extra_index_urls = []
        # Convert Path object to string to avoid PosixPath decode errors.
        constraint_file = self.default_constraint_file
        if isinstance(constraint_file, Path):
            constraint_file = str(constraint_file)
        parsed_default_constraints = parse_requirements(
            constraint_file,
            constraint=True,
            finder=self.finder(),
            session=self.session,
            options=pip_options,
        )
        self._parsed_default_constraints = list(parsed_default_constraints)
        return self._parsed_default_constraints

    @property
    def parsed_constraints(self):
        """Get parsed constraints including those from default packages if needed."""
        if self._parsed_constraints is not None:
            return self._parsed_constraints

        pip_options = self.pip_options
        pip_options.extra_index_urls = []
        # Convert Path object to string to avoid PosixPath decode errors.
        constraint_file = self.prepare_constraint_file()
        if isinstance(constraint_file, Path):
            constraint_file = str(constraint_file)
        constraints = list(
            parse_requirements(
                constraint_file,
                finder=self.finder(),
                session=self.session,
                options=pip_options,
            )
        )

        # Only add default constraints for dev packages if setting allows
        if self.category != "default" and self.project.settings.get(
            "use_default_constraints", True
        ):
            constraints.extend(self.parsed_default_constraints)

        self._parsed_constraints = constraints
        return self._parsed_constraints

    @property
    def default_constraints(self):
        """Get constraints from default section when installing dev packages."""
        if not self.project.settings.get("use_default_constraints", True):
            return set()

        possible_default_constraints = [
            install_req_from_parsed_requirement(
                c,
                isolated=self.pip_options.build_isolation,
                user_supplied=False,
            )
            for c in self.parsed_default_constraints
        ]
        return set(possible_default_constraints)

    @property
    def possible_constraints(self):
        possible_constraints_list = [
            install_req_from_parsed_requirement(
                c,
                isolated=self.pip_options.build_isolation,
                user_supplied=True,
            )
            for c in self.parsed_constraints
        ]
        return possible_constraints_list

    @property
    def constraints(self):
        """Get all applicable constraints."""
        possible_constraints_list = self.possible_constraints
        constraints_list = set()
        for c in possible_constraints_list:
            constraints_list.add(c)

        # Always use default_constraints when installing dev-packages
        if self.category != "default" and self.project.settings.get(
            "use_default_constraints", True
        ):
            constraints_list |= self.default_constraints

        return constraints_list

    @contextlib.contextmanager
    def get_resolver(self, clear=False):
        from pipenv.patched.pip._internal.utils.temp_dir import TempDirectory

        with global_tempdir_manager():
            with get_build_tracker() as build_tracker:
                with TempDirectory(globally_managed=True) as directory:
                    pip_options = self.pip_options
                    finder = self.finder()
                    wheel_cache = WheelCache(pip_options.cache_dir)
                    preparer = self.pip_command.make_requirement_preparer(
                        temp_build_dir=directory,
                        options=pip_options,
                        build_tracker=build_tracker,
                        session=self.session,
                        finder=finder,
                        use_user_site=False,
                    )
                    resolver = self.pip_command.make_resolver(
                        preparer=preparer,
                        finder=finder,
                        options=pip_options,
                        wheel_cache=wheel_cache,
                        use_user_site=False,
                        ignore_installed=True,
                        ignore_requires_python=pip_options.ignore_requires_python,
                        force_reinstall=pip_options.force_reinstall,
                        upgrade_strategy="to-satisfy-only",
                        py_version_info=self.target_py_version_info,
                    )
                    yield resolver

    def resolve(self):
        with temp_environ(), self.get_resolver() as resolver:
            try:
                results = resolver.resolve(self.constraints, check_supported_wheels=False)
            except InstallationError as e:
                raise ResolutionFailure(message=_format_resolution_error(e)) from e
            else:
                self.results = set(results.all_requirements)
                self.resolved_tree.update(self.results)
        return self.resolved_tree

    def _get_pipfile_markers(self, pipfile_entry):
        sys_platform = pipfile_entry.get("sys_platform")
        platform_machine = pipfile_entry.get("platform_machine")
        markers = pipfile_entry.get("markers")

        if sys_platform:
            sys_platform = f"sys_platform {sys_platform}"
        if platform_machine:
            platform_machine = f"platform_machine {platform_machine}"

        combined_markers = [
            f"({marker})"
            for marker in (sys_platform, markers, platform_machine)
            if marker
        ]

        return " and ".join(combined_markers).strip()

    def _fold_markers(self, dependency_tree, install_req, checked_dependencies=None):
        if checked_dependencies is None:
            checked_dependencies = set()

        if install_req.name is None:
            return None  # Or handle this edge case differently

        comes_from = dependency_tree.get(install_req.name)
        if comes_from is None:
            return None  # Or handle this edge case differently

        # Check for recursion loop
        if install_req.name in checked_dependencies:
            return None  # Or raise an error or handle cyclic dependencies differently

        checked_dependencies.add(install_req.name)

        if comes_from == "Pipfile":
            pipfile_entry = self.pipfile_entries.get(install_req.name)
            if pipfile_entry and isinstance(pipfile_entry, dict):
                return self._get_pipfile_markers(pipfile_entry)
        else:
            markers = self._fold_markers(
                dependency_tree, comes_from, checked_dependencies
            )
            if markers:
                self.markers_lookup[install_req.name] = markers
            return markers

    def resolve_constraints(self):
        """Fold per-package ``requires-python`` markers into the resolved tree.

        For each resolved item, read ``link.requires_python`` directly and
        convert it to a marker via :func:`pipenv.utils.markers.marker_from_specifier`.
        The marker then flows onto the lockfile entry's ``markers`` field.

        Behaviour change vs the pre-2026-05 implementation (commit
        ``cf53eb17`` — `Resolver.resolve_constraints``):

        - **Before**: this method called
          ``self.finder().find_best_candidate(name, specifier)`` once per
          resolved item and read ``candidate.link.requires_python``.  The
          default ``self.finder()`` is the *strict* finder
          (``_ignore_compatibility = False``).  For a resolved item whose
          link came from a *lenient* path (e.g., the
          ``pip_finder_ignore_compatability`` patched-pip flag, cross-
          platform locking workflows, or any caller monkey-patching
          ``finder._ignore_compatibility = True`` before resolve),
          ``find_best_candidate`` on the strict finder returned ``None`` →
          no marker added → that lockfile entry silently lacked its
          advertised ``requires_python`` constraint.

        - **After**: we read the marker directly from the resolved item's
          ``link`` regardless of which finder produced it.  Cross-compat
          packages whose links advertise ``requires-python`` now get
          their markers in the lockfile.  This is arguably a correctness
          fix (markers were missing for one specific category of
          packages) but it IS a behaviour change for any consumer that
          relied on those markers being absent — most likely scripts
          running ``pipenv lock --ignore-compatibility``-equivalent
          workflows via the patched-pip flag.

        See ``tests/unit/test_resolver_regressions.py``
        ``test_resolve_constraints_marker_for_ignore_compatibility_link``
        for the test that pins the new behaviour.
        """
        from .markers import marker_from_specifier

        # Build mapping of package origins and Python requirements
        comes_from = {}
        python_requirements = {}

        results_list = list(self.resolved_tree)
        for result in results_list:
            # Track package origin
            if isinstance(result.comes_from, InstallRequirement):
                comes_from[result.name] = result.comes_from
            else:
                comes_from[result.name] = "Pipfile"

        # Profiling (May 2026, in-process resolver, 100-pkg bench)
        # caught this method spending ~8.9 s of a 31.4 s wall walking
        # pip's ``PackageFinder.find_best_candidate`` once per resolved
        # package — solely to pull ``requires_python`` off the winning
        # candidate's link.  But the resolved tree already carries that
        # link: pip's resolvelib stores the chosen candidate on every
        # ``InstallRequirement`` it returns from ``resolve()``.  Re-asking
        # pip via ``find_best_candidate`` repeated the per-package
        # simple-API walk (cached HTTP, but still parses every link
        # through ``Link.from_json`` + ``_ensure_quoted_url``).  Read
        # the marker directly off ``result.link`` — same answer, no
        # network, no ``ThreadPoolExecutor``.
        for result in results_list:
            link = getattr(result, "link", None)
            requires_python = (
                getattr(link, "requires_python", None) if link is not None else None
            )
            if not requires_python:
                continue
            try:
                marker = marker_from_specifier(requires_python)
            except TypeError:
                # Malformed ``requires-python`` value from the index —
                # fall through silently to match the prior contract.
                continue
            if marker is not None:
                python_requirements[result.name] = marker

        # Build the results tree with markers
        new_tree = set()
        for result in self.resolved_tree:
            # Start with any Python requirement markers
            if result.name in python_requirements:
                marker = python_requirements[result.name]
                self.markers[result.name] = marker
                result.markers = marker
                if result.req:
                    result.req.marker = marker
            elif result.markers:
                self.markers[result.name] = result.markers
                if result.req:
                    result.req.marker = result.markers

            new_tree.add(result)

        # Use existing fold_markers to properly combine all constraints
        for result in new_tree:
            folded_markers = self._fold_markers(comes_from, result)
            if folded_markers:
                self.markers[result.name] = folded_markers
                result.markers = folded_markers
                if result.req:
                    result.req.marker = folded_markers

        self.resolved_tree = new_tree

    @property
    def hash_finder(self):
        if getattr(self, "_hash_finder", None) is None:
            self._hash_finder = self.finder(ignore_compatibility=True)
        return self._hash_finder

    def collect_hashes(self, ireq):
        link = ireq.link  # Handle VCS and file links first
        if link and (link.is_vcs or (link.is_file and link.is_existing_dir())):
            return set()
        if not is_pinned_requirement(ireq):
            return set()

        sources = self.sources  # Enforce index restrictions
        canonical_ireq_name = canonicalize_name(ireq.name)
        if canonical_ireq_name in self.index_lookup:
            sources = list(
                filter(
                    lambda s: s.get("name") == self.index_lookup[canonical_ireq_name],
                    sources,
                )
            )
        source = sources[0] if sources else None
        if source:
            if is_pypi_url(source["url"]):
                hashes = self.project.sources.get_hashes_from_pypi(ireq, source)
                if hashes:
                    return hashes
            else:
                hashes = self.project.sources.get_hashes_from_remote_index_urls(ireq, source)
                if hashes:
                    return hashes

        # Updated section to use applicable_candidates directly
        best_candidate_result = self.hash_finder.find_best_candidate(
            ireq.name, ireq.specifier
        )
        if best_candidate_result.applicable_candidates:
            return sorted(
                {
                    self.project.sources.get_hash_from_link(self.hash_cache, candidate.link)
                    for candidate in best_candidate_result.applicable_candidates
                }
            )
        if link:
            return {self.project.sources.get_hash_from_link(self.hash_cache, link)}

        if self.project.s.is_verbose():
            err.print(
                f"[bold][red]Warning[/red][/bold]: Error generating hash for {ireq.name}."
            )
        return set()

    @property
    def resolve_hashes(self):
        if self.results is None:
            return self.hashes
        ireqs = list(self.results)
        if not ireqs:
            return self.hashes
        # Hash collection is mostly network-bound (PyPI JSON or simple-index
        # HTML), so we dispatch the per-ireq calls on a small thread pool.
        # collect_hashes reads resolver state that is stable post-resolve
        # (sources, hash_finder, hash_cache); eagerly initialize any lazily
        # created shared state here on the main thread to avoid races between
        # workers creating duplicate finders/caches/sessions.
        _ = self.hash_finder
        with contextlib.suppress(AttributeError):
            _ = self.hash_cache
        max_workers = min(len(ireqs), 16)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for ireq, hashes in zip(ireqs, pool.map(self.collect_hashes, ireqs)):
                self.hashes[ireq] = hashes
        return self.hashes

    def clean_skipped_result(
        self,
        req_name: str,
        ireq: InstallRequirement,
        pipfile_entry: Union[str, Dict[str, Any]],
    ) -> Tuple[str, Dict[str, Any]]:
        """Clean up skipped requirements with better VCS handling."""
        # Start with pipfile entry if it's a dict, otherwise create new dict
        entry = pipfile_entry.copy() if isinstance(pipfile_entry, dict) else {}
        entry["name"] = req_name

        # Handle VCS references
        if ireq.link and ireq.link.is_vcs:
            vcs = ireq.link.scheme.split("+", 1)[0]

            # Try to get reference from multiple sources
            ref = determine_vcs_revision_hash(ireq, vcs, ireq.link)

            if ref:
                entry["ref"] = ref
            elif ireq.link.hash:
                entry["ref"] = ireq.link.hash

            # Ensure VCS URL is present
            if vcs not in entry:
                vcs_url, _ = normalize_vcs_url(ireq.link.url)
                entry[vcs] = vcs_url

        # Remove version if editable
        if entry.get("editable", False) and entry.get("version"):
            del entry["version"]

        # Add hashes
        collected_hashes = self.collect_hashes(ireq)
        if collected_hashes:
            entry["hashes"] = sorted(set(collected_hashes))

        return req_name, entry

    def clean_results(self) -> List[Dict[str, Any]]:
        """Clean all results including both resolved and skipped packages.

        T_F.3 B2: ``format_requirement_for_lockfile`` was deleted in B3,
        but ``resolve_packages`` (B1) and ``prepare_lockfile`` (B3) both
        still consume the *flat lockfile dict* shape — the same shape
        the legacy formatter produced.  We therefore route resolved
        entries through the canonical
        :meth:`LockedRequirement.from_install_requirement` constructor
        and then immediately flatten back to dict via
        :meth:`LockedRequirement.to_lockfile_dict`, preserving the exact
        wire shape callers expect.  This is the unifying step the
        deleted ``format_requirement_for_lockfile`` performed before
        T_F.3.
        """
        results: Dict[str, Dict[str, Any]] = {}

        # Handle resolved packages
        for ireq in self.resolved_tree:
            if pep423_name(ireq.name) in self.skipped:
                continue

            collected_hashes = self.hashes.get(ireq, set())
            if collected_hashes:
                collected_hashes = sorted(collected_hashes)

            name = pep423_name(ireq.name)
            pipfile_entry = (
                self.pipfile_entries.get(ireq.name)
                or self.pipfile_entries.get(name)
                or {}
            )
            try:
                locked = LockedRequirement.from_install_requirement(
                    ireq,
                    sources_lookup=self.index_lookup,
                    markers_lookup=self.markers_lookup,
                    pipfile_entry=pipfile_entry if isinstance(pipfile_entry, dict) else None,
                    hashes=collected_hashes or None,
                )
                entry = locked.to_lockfile_dict()
            except ValueError:
                # The LockedRequirement invariants reject entries that
                # carry no version / vcs / file / path.  Such entries
                # used to slip through the legacy formatter as
                # ``{"name": ...}``-only dicts; preserve that
                # transitional path for now (B3's prepare_lockfile
                # tolerates it).
                entry = {"name": name}

            if entry["name"] in results:
                results[entry["name"]].update(entry)
            else:
                results[entry["name"]] = entry

        # Handle skipped packages
        for req_name in self.skipped:
            install_req = self.install_reqs[req_name]
            pipfile_entry = self.pipfile_entries.get(req_name, {})

            name, entry = self.clean_skipped_result(req_name, install_req, pipfile_entry)

            if name in results:
                results[name].update(entry)
            else:
                results[name] = entry

        return list(results.values())


# Global cache for resolution results to avoid repeated expensive subprocess calls
_resolution_cache = {}
_resolution_cache_timestamp = {}


def _generate_resolution_cache_key(
    deps,
    project,
    pipfile_category,
    pre,
    clear,
    allow_global,
    pypi_mirror,
    extra_pip_args,
    resolver_backend=None,
):
    """Generate a cache key for resolution results.

    T_PLUMBING (Initiative G phase 3): ``resolver_backend`` participates
    in the key so a pip-resolved cache entry can't satisfy a
    pure-python lookup.  ``None`` collapses to the empty string so the
    default-backend cache key is byte-identical to pre-T_PLUMBING (the
    pre-existing on-disk caches are still valid for the default path).
    """
    # Get lockfile and pipfile modification times
    lockfile_mtime = "no-lock"
    if project.lockfile.location:
        lockfile_path = Path(project.lockfile.location)
        if lockfile_path.exists():
            lockfile_mtime = str(lockfile_path.stat().st_mtime)

    pipfile_mtime = "no-pipfile"
    if project.pipfile.location:
        pipfile_path = Path(project.pipfile.location)
        if pipfile_path.exists():
            pipfile_mtime = str(pipfile_path.stat().st_mtime)

    # Include environment variables that affect resolution
    env_factors = [
        os.environ.get("PIPENV_CACHE_VERSION", "1"),
        os.environ.get("PIPENV_PYPI_MIRROR", ""),
        os.environ.get("PIP_INDEX_URL", ""),
        str(pypi_mirror) if pypi_mirror else "",
        json.dumps(extra_pip_args, sort_keys=True) if extra_pip_args else "",
    ]

    # Create a deterministic representation of dependencies
    deps_str = json.dumps(deps, sort_keys=True) if isinstance(deps, dict) else str(deps)

    key_components = [
        str(project.pipfile.project_directory),
        lockfile_mtime,
        pipfile_mtime,
        deps_str,
        str(pipfile_category),
        str(pre),
        str(clear),
        str(allow_global),
        "|".join(env_factors),
    ]
    # T_PLUMBING (Initiative G phase 3): backend selection
    # participates in the cache key — but ONLY when a non-default
    # backend is selected.  Appending unconditionally would change
    # the cache key for every default-path call (the empty string
    # would still hash differently than the no-component shape),
    # which would invalidate pre-T_PLUMBING on-disk caches and break
    # the "default path byte-identical" acceptance criterion.
    if resolver_backend:
        key_components.append(f"backend={resolver_backend}")

    key_string = "|".join(key_components)
    return hashlib.sha256(key_string.encode()).hexdigest()


def _should_use_resolution_cache(cache_key, clear):
    """Check if we should use cached resolution results."""
    if clear:
        return False

    if cache_key not in _resolution_cache:
        return False

    if cache_key not in _resolution_cache_timestamp:
        return False

    # Cache is valid for 10 minutes
    current_time = time.time()
    cache_age = current_time - _resolution_cache_timestamp[cache_key]
    return cache_age < 600  # 10 minutes


def _show_warning(message, category, filename, lineno, line):
    warnings.showwarning(
        message=message,
        category=category,
        filename=filename,
        lineno=lineno,
        file=sys.stderr,
        line=line,
    )
    sys.stderr.flush()


def actually_resolve_deps(
    deps,
    index_lookup,
    markers_lookup,
    project,
    sources,
    clear,
    pre,
    pipfile_category,
    req_dir,
    resolved_default_deps=None,
    extra_pip_args=None,
):
    with warnings.catch_warnings(record=True) as warning_list:
        resolver = Resolver.create(
            deps,
            project,
            index_lookup,
            markers_lookup,
            sources,
            req_dir,
            clear,
            pre,
            pipfile_category,
            resolved_default_deps=resolved_default_deps,
            extra_pip_args=extra_pip_args,
        )
        resolver.resolve()
        hashes = resolver.resolve_hashes
        resolver.resolve_constraints()
        results = resolver.clean_results()
    for warning in warning_list:
        _show_warning(
            warning.message,
            warning.category,
            warning.filename,
            warning.lineno,
            warning.line,
        )
    return (results, hashes, resolver)


def _is_download_status_line(line: str) -> bool:
    """Return True if the pip stderr line reports a file download.

    pip emits lines like::

        Downloading torch-2.0.0-cp311-cp311-linux_x86_64.whl (726.8 MB)

    to stderr during the resolution/hash-gathering phase.  We surface these
    even in non-verbose mode so that users can see *why* pipenv appears to be
    doing nothing for a long time instead of assuming it is frozen.
    """
    stripped = line.strip()
    # Match "Downloading <name>.whl (X MB)" style messages.
    return stripped.startswith("Downloading ") and (
        " MB)" in stripped
        or " kB)" in stripped
        or " KB)" in stripped
        or " GB)" in stripped
    )


def resolve(cmd, st, project, *, deadline_seconds=None):
    """Invoke the resolver subprocess and stream its stdout/stderr.

    The optional ``deadline_seconds`` keyword carries the wall-clock
    timeout enforced via ``subprocess.wait(timeout=...)`` (T_F.6).  When
    ``None`` we fall back to the env-var-backed
    ``Setting.PIPENV_RESOLVER_TIMEOUT_S`` value for back-compat with
    callers that haven't been updated to thread the deadline through.
    """
    # cmd is a pre-tokenized list (not a TOML sequence); pass it directly.
    c = subprocess_run([str(x) for x in cmd], block=False, env=os.environ.copy())
    is_verbose = project.s.is_verbose()

    # Use threading to read from both stdout and stderr concurrently.
    # This prevents deadlocks when the subprocess writes a lot of data to stdout,
    # which would fill the pipe buffer and block if we only read stderr first.
    # Threading works reliably on all platforms (Windows, Linux, macOS).
    stdout_chunks = []
    stderr_lines = []

    def read_stdout():
        """Read all stdout data in chunks."""
        while True:
            chunk = c.stdout.read(4096)
            if not chunk:
                break
            stdout_chunks.append(chunk)

    def read_stderr():
        """Read stderr line by line, printing verbose output or download notices."""
        for line in iter(c.stderr.readline, ""):
            if line.rstrip():
                stderr_lines.append(line)
                if is_verbose:
                    st.console.print(line.rstrip())
                elif _is_download_status_line(line):
                    # Always show download progress so users know pipenv is not
                    # frozen when pip is fetching a large package (issue #5718).
                    err.print(f"  [dim]{line.rstrip()}[/dim]")

    # Start reader threads
    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    # Configurable cap on how long we wait for the resolver subprocess. Unbounded
    # waits previously turned hung mirrors / stuck pip downloads into "pipenv
    # hangs forever" reports.  Precedence (T_F.6):
    #
    #   1. ``deadline_seconds`` keyword (request-carried, set by
    #      ``_build_resolver_request`` from the Pipfile / env / default
    #      precedence chain).
    #   2. ``project.s.PIPENV_RESOLVER_TIMEOUT_S`` (env-var-backed
    #      setting) — fallback for callers that pre-date T_F.6.
    resolver_timeout_s = (
        deadline_seconds
        if deadline_seconds is not None
        else project.s.PIPENV_RESOLVER_TIMEOUT_S
    )

    try:
        c.wait(timeout=resolver_timeout_s)
    except subprocess.TimeoutExpired:
        # Kill the subprocess and drain reader threads so we don't leak threads
        # or pipe buffers.
        try:
            c.kill()
        except Exception:
            pass
        try:
            c.wait(timeout=5)
        except Exception:
            pass
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        st.console.print(environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!"))
        msg = (
            f"Resolver subprocess timed out after {resolver_timeout_s} seconds. "
            f"Set PIPENV_RESOLVER_TIMEOUT_S=<bigger> in your environment (or "
            f"[pipenv] resolver_timeout_seconds in your Pipfile) to extend, or "
            f"check that your index/mirror is reachable."
        )
        err.print(f"[red]{msg}[/red]")
        raise ResolutionFailure(msg)

    # Make sure reader threads have finished draining the now-closed pipes
    # before we read the buffers below. They are daemons so a missed join
    # wouldn't deadlock the interpreter, but joining keeps stdout/stderr
    # collection deterministic.
    stdout_thread.join()
    stderr_thread.join()

    returncode = c.poll()

    out = "".join(stdout_chunks)
    errors = "".join(stderr_lines)

    # NOTE: pre-2026-05-12 this function raised ``ResolutionFailure`` on
    # any non-zero return code, which threw away the structured
    # ``ResolverResponse`` the subprocess writes to ``--response-file``
    # via the ``InternalError`` exit path (see
    # ``pipenv/resolver/main.py:_main``).  The caller
    # (``_run_resolver_subprocess``) already has dispatch logic that
    # reads the response file and surfaces structured error detail
    # ("Q10: response file is the source of truth whenever it exists,
    # regardless of exit code").  We now return the completed process
    # unconditionally so that dispatch path is reachable on non-zero
    # exit too — the caller decides between ``ResolutionFailure`` from
    # a typed ``ResolutionError``, ``RuntimeError`` from a typed
    # ``InternalError``, and the legacy stderr-fallback path for genuine
    # crashes that didn't write a response.  Without this change the
    # phase-3 multi-category-lock failures (default succeeds, dev fails
    # silently — see GH Actions run 25751144209) raised
    # ``ResolutionFailure("Failed to lock Pipfile.lock!")`` with the
    # real error message stranded inside the response file.
    if is_verbose:
        err.print(out.strip())
    return subprocess.CompletedProcess(c.args, returncode, out, errors)


def _set_resolver_netrc(project, req_dir):
    """Write a temporary netrc with credentials extracted from Pipfile sources
    and expose it via ``NETRC`` so the resolver subprocess can authenticate
    to private indexes without those credentials appearing in pip argv.
    """
    netrc_path = write_credentials_netrc(project.sources.pipfile_sources(), req_dir)
    if netrc_path:
        os.environ["NETRC"] = netrc_path


# ---------------------------------------------------------------------------
# T_F.3 B2: typed-request / typed-response parent-side dispatch
# ---------------------------------------------------------------------------


# --- T_F.6 BEGIN: resolver wall-clock deadline resolution -------------------
#
# Owned by T_F.6 (timeout enforcement).  Do not co-mingle with T_F.7's
# Diagnostics.resolver_log work.
def _resolve_deadline_seconds(project) -> float:
    """Resolve the wall-clock deadline (in seconds) for one resolver invocation.

    Precedence (highest first):

    1. Pipfile ``[pipenv] resolver_timeout_seconds`` — per-project override
       (positive int/float).  Garbage values silently fall through.
    2. Env-var-backed ``Setting.PIPENV_RESOLVER_TIMEOUT_S`` — the existing
       phase-2 hotfix knob, defaults to 1800.
    3. The hardcoded ``1800`` default inside ``Setting`` itself (reached
       only if both above are missing or invalid).

    Returns
    -------
    float
        A positive deadline in seconds, suitable for
        ``subprocess.wait(timeout=...)`` and serialization into
        ``RequestMetadata.deadline_seconds``.
    """
    # 1) Pipfile setting — must be a positive number to win.  Strings,
    # negatives, zero, and ``None`` fall through to the env-backed default.
    raw = None
    settings = getattr(project, "settings", None)
    if settings is not None:
        try:
            raw = settings.get("resolver_timeout_seconds")
        except AttributeError:
            raw = None
    if raw is not None:
        try:
            candidate = float(raw)
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and candidate > 0:
            return candidate

    # 2) Env-var-backed setting (already validated/defaulted by ``Setting``).
    return float(project.s.PIPENV_RESOLVER_TIMEOUT_S)
# --- T_F.6 END --------------------------------------------------------------


def _selected_backend_for_request(project, resolver_backend=None):
    """Return the resolver backend the parent should stamp onto the request.

    The parent computes the full precedence chain (CLI/caller > env >
    current project's Pipfile > default) before serializing the request so
    the resolver subprocess does not need to rediscover a Pipfile from its
    cwd just to make the same decision again.
    """
    backend = str(resolver_backend or "").strip()
    if backend:
        return backend

    backend = str(os.environ.get("PIPENV_RESOLVER") or "").strip()
    if backend:
        return backend

    pipfile_backend = None
    settings = getattr(project, "settings", None)
    if settings is not None:
        pipfile_backend = getattr(settings, "resolver", None)
        if pipfile_backend is None and hasattr(settings, "get"):
            pipfile_backend = settings.get("resolver")

    backend = str(pipfile_backend or "").strip()
    return backend or "pip"


def _build_resolver_request(
    *,
    deps,
    sources,
    category,
    pre,
    clear,
    allow_global,
    verbose,
    python_marker_override,
    extra_pip_args,
    resolved_default_deps,
    project,
    resolver_backend=None,
):
    """Build a :class:`ResolverRequest` from the parent-side inputs.

    Replaces the argv + env-var + constraints-tempfile +
    resolved-default-deps-tempfile cocktail (F.1 §3.1–3.2) with one
    typed envelope.  ``deps`` is the post-``convert_deps_to_pip`` mapping
    of ``name -> pip-install-argument-string``.  The parent also stamps
    the selected resolver backend onto the request so the subprocess can
    dispatch without re-reading Pipfile state from disk.
    """
    typed_sources = tuple(
        ResolverSource(
            name=src.get("name", ""),
            url=src.get("url", ""),
            verify_ssl=bool(src.get("verify_ssl", True)),
        )
        for src in (sources or [])
    )
    typed_resolved: ResolvedDeps | None = None
    if resolved_default_deps:
        entries = []
        for name, raw in resolved_default_deps.items():
            entry = dict(raw) if isinstance(raw, dict) else {"name": raw}
            entry.setdefault("name", name)
            # Coerce loose lockfile-dict shapes into LockedRequirement via
            # ``from_json_dict`` so the wire shape stays canonical.  Skip
            # malformed entries (no version / vcs / file / path) — those
            # would fail the LockedRequirement invariant and resolver
            # would treat them as constraint noise anyway.
            try:
                entries.append(LockedRequirement.from_json_dict(entry))
            except (KeyError, ValueError):
                continue
        typed_resolved = ResolvedDeps(entries=tuple(entries))

    return ResolverRequest(
        schema_version=SCHEMA_VERSION,
        category=category or "default",
        packages=PackageSpecs(specs=dict(deps)),
        options=ResolverOptions(
            pre=bool(pre),
            clear=bool(clear),
            system=bool(allow_global),
            verbose=bool(verbose),
            # T_F.5: stamp the effective backend chosen by the parent onto
            # the wire request so the subprocess can dispatch without
            # rediscovering env / Pipfile state.
            backend=_selected_backend_for_request(project, resolver_backend),
        ),
        sources=typed_sources,
        python_marker_override=python_marker_override,
        extra_pip_args=tuple(extra_pip_args or ()),
        resolved_default_deps=typed_resolved,
        metadata=RequestMetadata(
            pipenv_version=getattr(environments, "PIPENV_VERSION", "") or "",
            parent_pid=os.getpid(),
            # T_F.6: stamp the wall-clock deadline onto the request so the
            # parent (via subprocess.wait) AND the subprocess (for its
            # internal logging) see the same value.
            deadline_seconds=_resolve_deadline_seconds(project),
        ),
    )


def _run_resolver_subprocess(*, request, python_executable, project, st):
    """Serialize ``request`` to a tempfile, invoke ``pipenv-resolver`` with
    only ``--request-file`` / ``--response-file`` argv, then parse the
    typed response.

    Returns
    -------
    Sequence[LockedRequirement]
        On a successful resolve.

    Raises
    ------
    ResolutionFailure
        On structured ``ResolutionError`` from the subprocess
        (user-actionable dependency conflict).  The
        :attr:`ResolutionError.pip_message` is the user-facing text and
        :attr:`ResolutionError.conflicts` is attached as the
        ``conflicts`` attribute on the raised exception for downstream
        formatting code.
    RuntimeError
        On structured ``InternalError`` from the subprocess (true
        crash where the child managed to write a response) or on
        non-zero exit with no readable / parseable response file
        (genuine subprocess crash — fall back to the legacy stderr
        text channel).
    """
    request_file = tempfile.NamedTemporaryFile(
        prefix="pipenv-request-", suffix=".json", delete=False
    )
    request_file.close()
    response_file = tempfile.NamedTemporaryFile(
        prefix="pipenv-response-", suffix=".json", delete=False
    )
    response_file.close()

    request_path = request_file.name
    response_path = response_file.name

    try:
        with open(request_path, "w", encoding="utf-8") as fh:
            json.dump(request.to_json_dict(), fh, sort_keys=True)

        # ``pipenv.resolver`` is a package whose ``__init__`` re-exports
        # ``main`` as a function, so attribute access via
        # ``pipenv.resolver.main`` resolves to that function rather
        # than the module.  Pull the module explicitly via
        # :func:`importlib.import_module` to get its file path.
        from importlib import import_module

        resolver_main_module = import_module("pipenv.resolver.main")
        cmd = [
            python_executable,
            Path(resolver_main_module.__file__.rstrip("co")).as_posix(),
            "--request-file",
            make_posix(request_path),
            "--response-file",
            make_posix(response_path),
        ]
        # T_F.6: thread the request-carried deadline through to ``resolve``
        # so ``subprocess.wait(timeout=...)`` enforces the Pipfile/env/default
        # precedence chain rather than re-reading the project setting.
        c = resolve(
            cmd,
            st,
            project=project,
            deadline_seconds=request.metadata.deadline_seconds,
        )

        # ------------------------------------------------------------
        # Parse + dispatch on the structured response (Q10: response
        # file is the source of truth whenever it exists, regardless
        # of exit code).
        # ------------------------------------------------------------
        response: ResolverResponse | None = None
        if os.path.exists(response_path):
            try:
                with open(response_path, encoding="utf-8") as fh:
                    raw = fh.read()
                if raw.strip():
                    response = ResolverResponse.from_json_dict(json.loads(raw))
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                if c.returncode == 0:
                    # Clean exit but unparseable response — that's a
                    # real bug in the child; surface it.
                    raise RuntimeError(
                        f"Malformed resolver response file at {response_path}: {exc}"
                    ) from exc
                # Otherwise fall through to the legacy stderr-fallback
                # below (the child crashed before writing a clean
                # response).
                response = None

        if response is not None:
            # T_F.7: surface the structured resolver log to the user
            # BEFORE dispatching (the dispatcher may raise, and we want
            # verbose users to see the log even on failure paths).
            _surface_resolver_log(response, project)
            locked = _dispatch_resolver_response(response, st)
            # Forward the subprocess's captured stderr to the parent's
            # stderr stream on the success path so user-actionable
            # warnings emitted by the in-subprocess ``Resolver`` (e.g.
            # ``check_if_package_req_skipped``'s "Could not find a
            # matching version of <pkg>; <markers>" notice) remain
            # visible.  The T_F.4 refactor accidentally dropped this:
            # ``read_stderr`` captures every line into ``stderr_lines``
            # but only echoes verbose / download-progress lines onward,
            # so without an explicit forward the warning lands on
            # ``CompletedProcess.stderr`` in memory and never reaches
            # the user's terminal — breaking the contract
            # ``test_resolve_skip_unmatched_requirements`` asserts.
            # In verbose mode each line was already echoed live by
            # ``read_stderr``, so skip the bulk re-print to avoid
            # double-output.
            if not project.s.is_verbose() and c.stderr and c.stderr.strip():
                err.print(
                    f"Warning: {c.stderr.strip()}",
                    overflow="ignore",
                    crop=False,
                )
            return locked

        # No structured response — fall back to the legacy stderr text
        # channel.  This is reached only when the child crashed before
        # it could write a response, OR when the response file was
        # produced but unreadable AND exit was non-zero.
        if c.returncode == 0:
            # Clean exit but no response file — shouldn't happen with
            # the new wire format; treat as a bug rather than silently
            # returning empty results.
            raise RuntimeError(
                "Resolver subprocess exited cleanly but produced no response file."
            )

        st.console.print(
            environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!")
        )
        err.print(f"Output: {c.stdout.strip()}")
        err.print(f"Error: {c.stderr.strip()}")
        # Provide helpful hints for common build errors
        # See: https://github.com/pypa/pipenv/issues/6058
        combined_output = (c.stdout + c.stderr).lower()
        if "getting requirements to build wheel" in combined_output:
            err.print(
                "\n[cyan]Hint:[/cyan] The error 'Getting requirements to build wheel' often indicates:\n"
                "  • Invalid pyproject.toml syntax or configuration\n"
                "  • Encoding issues in files referenced by pyproject.toml (e.g., README.md with special characters)\n"
                "  • Missing or incompatible build dependencies\n"
                "Try running [yellow]$ pip install . -v[/yellow] in your project directory for more detailed error output."
            )
        raise RuntimeError(
            "Resolver subprocess crashed without producing a structured response."
        )
    finally:
        # Leave the tempfiles on disk for post-mortem inspection only on
        # the failure paths above — on the success path we clean both up.
        # Actually, per Q10 the request stays readable post-mortem.  We
        # therefore *always* leave both files; OS-level cleanup of the
        # ``pipenv-`` prefix happens via the tracked-tempdir machinery
        # the parent already uses for sibling artifacts.
        #
        # If a future maintainer wants more aggressive cleanup, route it
        # through ``create_tracked_tempdir`` rather than ad-hoc unlink.
        pass


def _surface_resolver_log(response, project) -> None:
    """T_F.7: print the structured ``Diagnostics.resolver_log`` records
    when the user opted into verbose mode.

    The records are a *complement* to the existing stderr stream (per
    Q9 in ``docs/dev/initiative-f-typed-design.md`` §8) — stderr stays
    the user-facing channel for everything from pip-progress chatter to
    fatal error tracebacks.  This helper exists so that verbose users
    can ALSO see the structured trace that resolve emitted (source
    substitution, timing markers, pip's internal candidate-selection
    log).

    Non-verbose runs see no behaviour change; this is purely additive.
    """
    if response is None:
        return
    log = getattr(response.diagnostics, "resolver_log", ()) or ()
    if not log:
        return
    if not project.s.is_verbose():
        return
    err.print("[dim]--- resolver log ---[/dim]")
    for record in log:
        err.print(f"[dim]{record}[/dim]")
    err.print("[dim]--- end resolver log ---[/dim]")


def _dispatch_resolver_response(response, st):
    """Dispatch on ``response.result.kind``.  See
    :func:`_run_resolver_subprocess` for the contract.
    """
    result = response.result
    if isinstance(result, ResolverSuccess):
        st.console.print(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
        return result.locked
    if isinstance(result, ResolutionError):
        st.console.print(
            environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!")
        )
        pip_message = result.pip_message or "Failed to lock Pipfile.lock!"
        if pip_message:
            err.print(pip_message)
        exc = ResolutionFailure(pip_message or "Failed to lock Pipfile.lock!")
        # Attach structured detail so callers / future UI can iterate
        # ``conflicts`` without re-parsing pip's English.
        exc.conflicts = result.conflicts
        raise exc
    if isinstance(result, InternalError):
        st.console.print(
            environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!")
        )
        if result.message:
            err.print(result.message)
        if result.traceback:
            err.print(result.traceback)
        raise RuntimeError(result.message or "Resolver subprocess internal error.")
    raise RuntimeError(
        f"Unknown ResolverResponse variant: {type(result).__name__}"
    )


def _normalize_resolver_results(results):
    """Coerce a mixed sequence of ``LockedRequirement`` / dict / None
    entries into ``Sequence[LockedRequirement]``.

    During Wave B the subprocess path produces ``LockedRequirement``
    instances directly, but the in-process path still flows through
    legacy code (B1 takes responsibility for migrating the in-process
    branch's return type once it lands).  This helper bridges both
    shapes so downstream consumers (the lockfile writer) see one type.
    """
    out = []
    for entry in results or ():
        if entry is None:
            continue
        if isinstance(entry, LockedRequirement):
            out.append(entry)
            continue
        if isinstance(entry, dict):
            try:
                out.append(LockedRequirement.from_json_dict(entry))
            except (KeyError, ValueError):
                # Legacy / partial dicts pass through unchanged; B3's
                # ``prepare_lockfile`` rewrite will decide how to handle
                # them.  Wrap as a dict-shaped sentinel for back-compat.
                out.append(entry)  # type: ignore[arg-type]
            continue
        out.append(entry)
    return out


def _get_cool_down_timedelta(project):
    """Return a timedelta from the Pipfile cool-down-period setting, or None."""
    raw = project.settings.get("cool-down-period")
    if not raw:
        return None
    import datetime as _dt
    import re as _re
    m = _re.match(r"^(\d+)d$", raw)
    if not m:
        return None
    return _dt.timedelta(days=int(m.group(1)))


def _resolve_in_process(request, st, project=None):
    """In-process adapter around :func:`pipenv.resolver.core.resolve_for_pipenv`.

    T_F.4 fold: the ``PIPENV_RESOLVER_PARENT_PYTHON=1`` debug bypass now
    calls the exact same unified driver that the subprocess entry calls,
    then dispatches on ``response.result.kind`` to either return the
    locked entries or raise.  The marker-environment override is handled
    inside the unified driver, so this adapter does NOT wrap a separate
    ``_patched_marker_environment`` context manager.

    Parameter ``project`` (T_F.7) is optional purely for backward
    compatibility with the existing test suite — when supplied, the
    structured ``Diagnostics.resolver_log`` is surfaced to stderr in
    verbose mode via :func:`_surface_resolver_log`.

    Returns
    -------
    Sequence[LockedRequirement]
        On a successful resolve.

    Raises
    ------
    ResolutionFailure
        Structured dependency conflict (``ResolutionError`` variant of
        the typed response).
    RuntimeError
        Genuine internal failure (``InternalError`` variant).
    """
    from pipenv.resolver.core import resolve_for_pipenv

    response = resolve_for_pipenv(request)
    # T_F.7: surface the resolver log before any dispatch (the dispatch
    # below may raise, and verbose users want the log on failure too).
    if project is not None:
        _surface_resolver_log(response, project)
    kind = response.result.kind
    if kind == "success":
        results = _normalize_resolver_results(response.result.locked)
        if results:
            st.console.print(
                environments.PIPENV_SPINNER_OK_TEXT.format("Success!")
            )
        return results
    st.console.print(environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!"))
    if kind == "resolution_error":
        message = response.result.pip_message or "Failed to lock Pipfile.lock!"
        err.print(message)
        exc = ResolutionFailure(message)
        exc.conflicts = response.result.conflicts
        raise exc
    # internal_error or unknown — surface the captured traceback.
    if response.result.message:
        err.print(response.result.message)
    if response.result.traceback:
        err.print(response.result.traceback)
    raise RuntimeError(
        response.result.message or "Resolver internal error in PARENT_PYTHON branch."
    )


def venv_resolve_deps(
    deps,
    which,
    project,
    pipfile_category,
    pre=False,
    clear=False,
    allow_global=False,
    pypi_mirror=None,
    pipfile=None,
    lockfile=None,
    old_lock_data=None,
    extra_pip_args=None,
    resolved_default_deps=None,
    resolver_backend=None,
):
    """
    Resolve dependencies for a pipenv project, acts as a portal to the target environment.

    Regardless of whether a virtual environment is present or not, this will spawn
    a subprocess which is isolated to the target environment and which will perform
    dependency resolution.  This function reads the output of that call and mutates
    the provided lockfile accordingly, returning nothing.

    :param List[:class:`~pip.InstallRequirement`] deps: A list of dependencies to resolve.
    :param Callable which: [description]
    :param project: The pipenv Project instance to use during resolution
    :param Optional[bool] pre: Whether to resolve pre-release candidates, defaults to False
    :param Optional[bool] clear: Whether to clear the cache during resolution, defaults to False
    :param Optional[bool] allow_global: Whether to use *sys.executable* as the python binary, defaults to False
    :param Optional[str] pypi_mirror: A URL to substitute any time *pypi.org* is encountered, defaults to None
    :param Optional[bool] dev: Whether to target *dev-packages* or not, defaults to False
    :param pipfile: A Pipfile section to operate on, defaults to None
    :type pipfile: Optional[Dict[str, Union[str, Dict[str, bool, List[str]]]]]
    :param Dict[str, Any] lockfile: A project lockfile to mutate, defaults to None
    :raises RuntimeError: Raised on resolution failure
    :return: The lock data
    :rtype: dict
    """
    lockfile_category = get_lockfile_section_using_pipfile_category(pipfile_category)

    deps = deps or (project.pipfile.parsed.get(pipfile_category, {}) if project.pipfile.exists else {})
    if not deps:
        return {}

    pipfile = pipfile or getattr(project, pipfile_category, {})
    if lockfile is None:
        lockfile = project.lockfile.as_dict(categories=[pipfile_category])
    if old_lock_data is None:
        old_lock_data = lockfile.get(lockfile_category, {})

    extra_pip_args = list(extra_pip_args or [])

    # Check cache before expensive resolution
    # T_PLUMBING (Initiative G phase 3): include resolver_backend in the
    # cache key so a pip-resolved cache entry can't satisfy a
    # pure-python lookup (and vice versa).  ``None`` collapses to the
    # empty string so the default path's cache key is byte-identical
    # to pre-T_PLUMBING.
    cache_key = _generate_resolution_cache_key(
        deps,
        project,
        pipfile_category,
        pre,
        clear,
        allow_global,
        pypi_mirror,
        extra_pip_args,
        resolver_backend=resolver_backend,
    )

    if _should_use_resolution_cache(cache_key, clear):
        if project.s.is_verbose():
            err.print("[dim]Using cached resolution results...[/dim]")
        cached_results = _resolution_cache[cache_key]
        return prepare_lockfile(
            project,
            cached_results,
            pipfile,
            lockfile.get(lockfile_category, {}),
            old_lock_data,
        )

    req_dir = create_tracked_tempdir(prefix="pipenv", suffix="requirements")
    results = []
    with temp_environ():
        os.environ.update({k: str(val) for k, val in os.environ.items()})
        if pypi_mirror:
            os.environ["PIPENV_PYPI_MIRROR"] = str(pypi_mirror)
        os.environ["PIP_NO_INPUT"] = "1"
        # Pass through keyring provider so that credential managers
        # (e.g. Windows Credential Manager) work during resolution.
        # See https://github.com/pypa/pipenv/issues/5715
        keyring_provider = project.s.PIPENV_KEYRING_PROVIDER
        if keyring_provider:
            os.environ["PIP_KEYRING_PROVIDER"] = keyring_provider
        # Pipenv strips credentials from URLs that flow into pip argv to
        # avoid leaking secrets via process listings (GHSA-8xgg-v3jj-95m2).
        # Re-inject them out-of-band through a temporary netrc file so that
        # the resolver subprocess (and the in-process pip session it
        # creates) can still authenticate to private indexes.
        _set_resolver_netrc(project, req_dir)
        # T_F.3 B2: ``extra_pip_args`` and the Pipfile-derived
        # ``python_full_version`` used to flow into the subprocess as
        # dedicated environment variables.  Both now ride inside the
        # typed ``ResolverRequest`` (built below); the env-var hops are
        # deleted.  The other inherited env-vars (``PIP_*``, ``NETRC``,
        # ``PYTHONIOENCODING``, ``PYTHONUNBUFFERED``,
        # ``PIPENV_PYPI_MIRROR``) continue to flow via
        # ``os.environ.copy()`` because pip-internal code reads them
        # directly.
        python_override = _get_pipfile_python_override(project)
        python_marker_override = (
            python_override["python_full_version"] if python_override else None
        )
        with console.status(
            f"Locking {pipfile_category}...", spinner=project.s.PIPENV_SPINNER
        ) as st:
            # This conversion is somewhat slow on local and file-type requirements since
            # we now download those requirements / make temporary folders to perform
            # dependency resolution on them, so we are including this step inside the
            # spinner context manager for the UX improvement
            st.console.print("Building requirements...")
            deps = convert_deps_to_pip(
                deps, project.sources.pipfile_sources(), include_index=True
            )

            # Build the typed request envelope ONCE — both the
            # in-process debug bypass and the subprocess path consume
            # the same typed ``ResolverRequest`` after T_F.3 B1+B2.
            request = _build_resolver_request(
                deps=deps,
                sources=project.sources.pipfile_sources(),
                category=pipfile_category,
                pre=pre,
                clear=clear,
                allow_global=allow_global,
                verbose=project.s.is_verbose(),
                python_marker_override=python_marker_override,
                extra_pip_args=extra_pip_args,
                resolved_default_deps=resolved_default_deps,
                project=project,
                # T_PLUMBING (Initiative G phase 3): stamp the
                # parent-resolved backend name onto the typed request
                # so both the subprocess and in-process branches see
                # the same selection.  ``None`` becomes the empty
                # string in ``_build_resolver_request`` — the
                # dispatcher then falls through to the env/Pipfile
                # chain on the child side.
                resolver_backend=resolver_backend,
            )

            # Useful for debugging and hitting breakpoints in the resolver
            if project.s.PIPENV_RESOLVER_PARENT_PYTHON:
                # ---- In-process branch (debug bypass) ----
                # T_F.4: this branch is now a THIN adapter around the
                # same :func:`pipenv.resolver.core.resolve_for_pipenv`
                # the subprocess entry calls.  The only difference is
                # that we dispatch on ``response.result.kind`` here
                # rather than reading a JSON file.
                results = _resolve_in_process(request, st, project=project)
            else:  # Default/Production behavior is to use project python's resolver
                st.console.print("Resolving dependencies...")
                results = _run_resolver_subprocess(
                    request=request,
                    python_executable=which("python", allow_global=allow_global),
                    project=project,
                    st=st,
                )
                results = _normalize_resolver_results(results)

    # Cache the results for future use
    if results:
        _resolution_cache[cache_key] = results
        _resolution_cache_timestamp[cache_key] = time.time()

        # Clean old cache entries (keep only last 5 projects)
        if len(_resolution_cache) > 5:
            oldest_key = min(
                _resolution_cache_timestamp.keys(),
                key=lambda k: _resolution_cache_timestamp[k],
            )
            _resolution_cache.pop(oldest_key, None)
            _resolution_cache_timestamp.pop(oldest_key, None)

    if lockfile_category not in lockfile:
        lockfile[lockfile_category] = {}
    return prepare_lockfile(
        project, results, pipfile, lockfile[lockfile_category], old_lock_data
    )


def resolve_deps(
    deps,
    which,
    project,
    sources=None,
    python=False,
    clear=False,
    pre=False,
    pipfile_category=None,
    allow_global=False,
    req_dir=None,
    resolved_default_deps=None,
    extra_pip_args=None,
):
    """Given a list of dependencies, return a resolved list of dependencies,
    and their hashes, using the warehouse API / pip.
    """
    index_lookup = {}
    markers_lookup = {}
    if not os.environ.get("PIP_SRC"):
        os.environ["PIP_SRC"] = str(project.venv_locator.src_location)
    results = []
    resolver = None
    if not deps:
        return results, resolver
    # First (proper) attempt:
    if not req_dir:
        req_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-requirements")
    python_override = _get_pipfile_python_override(project)
    with HackedPythonVersion(python_path=project.venv_locator.python(system=allow_global)):
        with _patched_marker_environment(python_override):
            try:
                results, hashes, internal_resolver = actually_resolve_deps(
                    deps,
                    index_lookup,
                    markers_lookup,
                    project,
                    sources,
                    clear,
                    pre,
                    pipfile_category,
                    req_dir=req_dir,
                    resolved_default_deps=resolved_default_deps,
                    extra_pip_args=extra_pip_args,
                )
            except RuntimeError:
                # Don't exit here, like usual.
                results = None
    # Second (last-resort) attempt:
    if results is None:
        with HackedPythonVersion(
            python_path=project.venv_locator.python(system=allow_global),
        ):
            with _patched_marker_environment(python_override):
                try:
                    # Attempt to resolve again, with different Python version
                    # information, particularly for particularly particular
                    # packages.
                    (
                        results,
                        hashes,
                        internal_resolver,
                    ) = actually_resolve_deps(
                        deps,
                        index_lookup,
                        markers_lookup,
                        project,
                        sources,
                        clear,
                        pre,
                        pipfile_category,
                        req_dir=req_dir,
                        resolved_default_deps=resolved_default_deps,
                        extra_pip_args=extra_pip_args,
                    )
                except RuntimeError:
                    sys.exit(1)
    return results, internal_resolver
