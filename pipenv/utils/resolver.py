import contextlib
import json
import os
import subprocess
import sys
import tempfile
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from pipenv import environments, resolver
from pipenv.exceptions import ResolutionFailure
from pipenv.patched.pip._internal.cache import WheelCache
from pipenv.patched.pip._internal.commands.install import InstallCommand
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
from pipenv.patched.pip._vendor import pkg_resources, rich
from pipenv.project import Project
from pipenv.utils.fileutils import create_tracked_tempdir
from pipenv.utils.requirements import normalize_name
from pipenv.vendor import click

try:
    # this is only in Python3.8 and later
    from functools import cached_property
except ImportError:
    # eventually distlib will remove cached property when they drop Python3.7
    from pipenv.patched.pip._vendor.distlib.util import cached_property

from .dependencies import (
    HackedPythonVersion,
    convert_deps_to_pip,
    expansive_install_req_from_line,
    get_constraints_from_deps,
    get_lockfile_section_using_pipfile_category,
    is_pinned_requirement,
    prepare_constraint_file,
    translate_markers,
)
from .indexes import parse_indexes, prepare_pip_source_args
from .internet import is_pypi_url
from .locking import format_requirement_for_lockfile, prepare_lockfile
from .shell import make_posix, subprocess_run, temp_environ

console = rich.console.Console()
err = rich.console.Console(stderr=True)


def get_package_finder(
    install_cmd=None,
    options=None,
    session=None,
    platform=None,
    python_versions=None,
    abi=None,
    implementation=None,
    ignore_requires_python=None,
):
    """Reduced Shim for compatibility to generate package finders."""
    py_version_info = None
    if python_versions:
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
        category=None,
        original_deps=None,
        install_reqs=None,
        pipfile_entries=None,
    ):
        self.initial_constraints = constraints
        self.req_dir = req_dir
        self.project = project
        self.sources = sources
        self.resolved_tree = set()
        self.hashes = {}
        self.clear = clear
        self.pre = pre
        self.category = category
        self.results = None
        self.markers_lookup = markers_lookup if markers_lookup is not None else {}
        self.index_lookup = index_lookup if index_lookup is not None else {}
        self.skipped = skipped if skipped is not None else {}
        self.markers = {}
        self.requires_python_markers = {}
        self.original_deps = original_deps if original_deps is not None else {}
        self.install_reqs = install_reqs if install_reqs is not None else {}
        self.pipfile_entries = pipfile_entries if pipfile_entries is not None else {}
        self._retry_attempts = 0
        self._hash_cache = None

    def __repr__(self):
        return (
            f"<Resolver (constraints={self.initial_constraints}, req_dir={self.req_dir}, "
            f"sources={self.sources})>"
        )

    @staticmethod
    @lru_cache
    def _get_pip_command():
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
        project: Project,
        index_lookup: Dict[str, str] = None,
        markers_lookup: Dict[str, str] = None,
        sources: List[str] = None,
        req_dir: str = None,
        clear: bool = False,
        pre: bool = False,
        category: str = None,
    ) -> "Resolver":
        if not req_dir:
            req_dir = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")
        if index_lookup is None:
            index_lookup = {}
        if markers_lookup is None:
            markers_lookup = {}
        original_deps = {}
        install_reqs = {}
        pipfile_entries = {}
        skipped = {}
        if sources is None:
            sources = project.sources
        packages = project.get_pipfile_section(category)
        constraints = set()
        for package_name, dep in deps.items():  # Build up the index and markers lookups
            if not dep:
                continue
            is_constraint = True
            install_req, _ = expansive_install_req_from_line(dep, expand_env=True)
            original_deps[package_name] = dep
            install_reqs[package_name] = install_req
            index, extra_index, trust_host, remainder = parse_indexes(dep)
            if package_name in packages:
                pipfile_entry = packages[package_name]
                pipfile_entries[package_name] = pipfile_entry
                if isinstance(pipfile_entry, dict):
                    if packages[package_name].get("index"):
                        index_lookup[package_name] = packages[package_name].get("index")
                    if packages[package_name].get("skip_resolver"):
                        is_constraint = False
                        skipped[package_name] = dep
                elif index:
                    index_lookup[package_name] = index
                else:
                    index_lookup[package_name] = project.get_default_index()["name"]
            if install_req.markers:
                markers_lookup[package_name] = install_req.markers
            if is_constraint:
                constraints.add(dep)
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
            category=category,
            original_deps=original_deps,
            install_reqs=install_reqs,
            pipfile_entries=pipfile_entries,
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
        return pip_args

    @property  # cached_property breaks authenticated private indexes
    def pip_args(self):
        use_pep517 = environments.get_from_env("USE_PEP517", prefix="PIP")
        build_isolation = environments.get_from_env("BUILD_ISOLATION", prefix="PIP")
        return self.prepare_pip_args(
            use_pep517=use_pep517, build_isolation=build_isolation
        )

    def prepare_constraint_file(self):
        constraint_filename = prepare_constraint_file(
            self.initial_constraints,
            directory=self.req_dir,
            sources=self.sources,
            pip_args=self.pip_args,
        )
        return constraint_filename

    @property
    def constraint_file(self):
        return self.prepare_constraint_file()

    @cached_property
    def default_constraint_file(self):
        default_constraints = get_constraints_from_deps(self.project.packages)
        default_constraint_filename = prepare_constraint_file(
            default_constraints,
            directory=self.req_dir,
            sources=None,
            pip_args=None,
        )
        return default_constraint_filename

    @property  # cached_property breaks authenticated private indexes
    def pip_options(self):
        pip_options, _ = self.pip_command.parser.parse_args(self.pip_args)
        pip_options.cache_dir = self.project.s.PIPENV_CACHE_DIR
        pip_options.no_python_version_warning = True
        pip_options.no_input = self.project.settings.get("disable_pip_input", True)
        pip_options.progress_bar = "off"
        pip_options.ignore_requires_python = True
        pip_options.pre = self.pre or self.project.settings.get(
            "allow_prereleases", False
        )
        return pip_options

    @property
    def session(self):
        return self.pip_command._build_session(self.pip_options)

    def prepare_index_lookup(self):
        index_mapping = {}
        for source in self.sources:
            if source.get("name"):
                index_mapping[source["name"]] = source["url"]
        alt_index_lookup = {}
        for req_name, index in self.index_lookup.items():
            if index_mapping.get(index):
                alt_index_lookup[req_name] = index_mapping[index]
        return alt_index_lookup

    @cached_property
    def package_finder(self):
        finder = get_package_finder(
            install_cmd=self.pip_command,
            options=self.pip_options,
            session=self.session,
        )
        return finder

    def finder(self, ignore_compatibility=False):
        finder = self.package_finder
        index_lookup = self.prepare_index_lookup()
        finder._link_collector.index_lookup = index_lookup
        finder._link_collector.search_scope.index_restricted = True
        finder._link_collector.search_scope.index_lookup = index_lookup
        finder._ignore_compatibility = ignore_compatibility
        return finder

    @cached_property
    def parsed_constraints(self):
        pip_options = self.pip_options
        pip_options.extra_index_urls = []
        return parse_requirements(
            self.constraint_file,
            finder=self.finder(),
            session=self.session,
            options=pip_options,
        )

    @cached_property
    def parsed_default_constraints(self):
        pip_options = self.pip_options
        pip_options.extra_index_urls = []
        parsed_default_constraints = parse_requirements(
            self.default_constraint_file,
            constraint=True,
            finder=self.finder(),
            session=self.session,
            options=pip_options,
        )
        return set(parsed_default_constraints)

    @cached_property
    def default_constraints(self):
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
                use_pep517=self.pip_options.use_pep517,
                user_supplied=True,
            )
            for c in self.parsed_constraints
        ]
        return possible_constraints_list

    @property
    def constraints(self):
        possible_constraints_list = self.possible_constraints
        constraints_list = set()
        for c in possible_constraints_list:
            constraints_list.add(c)
        # Only use default_constraints when installing dev-packages
        if self.category != "packages":
            constraints_list |= self.default_constraints
        return set(constraints_list)

    @contextlib.contextmanager
    def get_resolver(self, clear=False):
        from pipenv.patched.pip._internal.utils.temp_dir import TempDirectory

        with global_tempdir_manager(), get_build_tracker() as build_tracker, TempDirectory(
            globally_managed=True
        ) as directory:
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
                use_pep517=pip_options.use_pep517,
            )
            yield resolver

    def resolve(self):
        constraints = self.constraints
        with temp_environ(), self.get_resolver() as resolver:
            try:
                results = resolver.resolve(constraints, check_supported_wheels=False)
            except InstallationError as e:
                raise ResolutionFailure(message=str(e))
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
        from .markers import marker_from_specifier

        # Build mapping of where package originates from
        comes_from = {}
        for result in self.resolved_tree:
            if isinstance(result.comes_from, InstallRequirement):
                comes_from[result.name] = result.comes_from
            else:
                comes_from[result.name] = "Pipfile"

        # Build up the results tree with markers
        new_tree = set()
        for result in self.resolved_tree:
            if result.markers:
                self.markers[result.name] = result.markers
            else:
                candidate = (
                    self.finder()
                    .find_best_candidate(result.name, result.specifier)
                    .best_candidate
                )
                if candidate:
                    requires_python = candidate.link.requires_python
                    if requires_python:
                        try:
                            marker = marker_from_specifier(requires_python)
                            self.markers[result.name] = marker
                            result.markers = marker
                            if result.req:
                                result.req.marker = marker
                        except TypeError as e:
                            click.echo(
                                f"Error generating python marker for {candidate}.  "
                                f"Is the specifier {requires_python} incorrectly quoted or otherwise wrong?"
                                f"Full error: {e}",
                                err=True,
                            )
            new_tree.add(result)

        # Fold markers
        for result in new_tree:
            self._fold_markers(comes_from, result)

        self.resolved_tree = new_tree

    def collect_hashes(self, ireq):
        link = ireq.link  # Handle VCS and file links first
        if link and (link.is_vcs or (link.is_file and link.is_existing_dir())):
            return set()
        if not is_pinned_requirement(ireq):
            return set()

        sources = self.sources  # Enforce index restrictions
        if ireq.name in self.index_lookup:
            sources = list(
                filter(lambda s: s.get("name") == self.index_lookup[ireq.name], sources)
            )
        source = sources[0] if len(sources) else None
        if source:
            if is_pypi_url(source["url"]):
                hashes = self.project.get_hashes_from_pypi(ireq, source)
                if hashes:
                    return hashes
            else:
                hashes = self.project.get_hashes_from_remote_index_urls(ireq, source)
                if hashes:
                    return hashes

        applicable_candidates = (
            self.finder(ignore_compatibility=True)
            .find_best_candidate(ireq.name, ireq.specifier)
            .iter_applicable()
        )
        applicable_candidates = list(applicable_candidates)
        if applicable_candidates:
            return sorted(
                {
                    self.project.get_hash_from_link(self.hash_cache, candidate.link)
                    for candidate in applicable_candidates
                }
            )
        if link:
            return {self.project.get_hash_from_link(self.hash_cache, link)}
        return set()

    @cached_property
    def resolve_hashes(self):
        if self.results is not None:
            for ireq in self.results:
                self.hashes[ireq] = self.collect_hashes(ireq)
        return self.hashes

    def clean_skipped_result(
        self, req_name: str, ireq: InstallRequirement, pipfile_entry
    ):
        ref = None
        if ireq.link and ireq.link.is_vcs:
            ref = ireq.link.egg_fragment

        if isinstance(pipfile_entry, dict):
            entry = pipfile_entry.copy()
        else:
            entry = {}
        entry["name"] = req_name
        if entry.get("editable", False) and entry.get("version"):
            del entry["version"]
        ref = ref if ref is not None else entry.get("ref")
        if ref:
            entry["ref"] = ref
        collected_hashes = self.collect_hashes(ireq)
        if collected_hashes:
            entry["hashes"] = sorted(set(collected_hashes))
        return req_name, entry

    def clean_results(self):
        reqs = [(ireq,) for ireq in self.resolved_tree]
        results = {}
        for (ireq,) in reqs:
            if normalize_name(ireq.name) in self.skipped:
                continue
            collected_hashes = self.hashes.get(ireq, set())
            if collected_hashes:
                collected_hashes = sorted(collected_hashes)
            name, entry = format_requirement_for_lockfile(
                ireq,
                self.markers_lookup,
                self.index_lookup,
                self.original_deps,
                self.pipfile_entries,
                collected_hashes,
            )
            entry = translate_markers(entry)
            if name in results:
                results[name].update(entry)
            else:
                results[name] = entry
        for req_name in self.skipped:
            install_req = self.install_reqs[req_name]
            name, entry = self.clean_skipped_result(
                req_name, install_req, self.pipfile_entries[req_name]
            )
            entry = translate_markers(entry)
            if name in results:
                results[name].update(entry)
            else:
                results[name] = entry
        results = list(results.values())
        return results


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
    category,
    req_dir,
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
            category,
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


def resolve(cmd, st, project):
    from pipenv.cmdparse import Script
    from pipenv.vendor.click import echo

    c = subprocess_run(Script.parse(cmd).cmd_args, block=False, env=os.environ.copy())
    is_verbose = project.s.is_verbose()
    err = ""
    for line in iter(c.stderr.readline, ""):
        if not line.rstrip():
            continue
        err += line
        if is_verbose:
            st.console.print(line.rstrip())

    c.wait()
    returncode = c.poll()
    out = c.stdout.read()
    if returncode != 0:
        st.console.print(environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!"))
        echo(out.strip(), err=True)
        if not is_verbose:
            echo(err, err=True)
        raise RuntimeError("Failed to lock Pipfile.lock!")
    if is_verbose:
        echo(out.strip(), err=True)
    return subprocess.CompletedProcess(c.args, returncode, out, err)


def venv_resolve_deps(
    deps,
    which,
    project,
    category,
    pre=False,
    clear=False,
    allow_global=False,
    pypi_mirror=None,
    pipfile=None,
    lockfile=None,
    old_lock_data=None,
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
    lockfile_section = get_lockfile_section_using_pipfile_category(category)

    if not deps:
        if not project.pipfile_exists:
            return None
        deps = project.parsed_pipfile.get(category, {})
    if not deps:
        return None

    if not pipfile:
        pipfile = getattr(project, category, {})
    if lockfile is None:
        lockfile = project.lockfile(categories=[category])
    if old_lock_data is None:
        old_lock_data = lockfile.get(lockfile_section, {})
    req_dir = create_tracked_tempdir(prefix="pipenv", suffix="requirements")
    results = []
    with temp_environ():
        os.environ.update({k: str(val) for k, val in os.environ.items()})
        if pypi_mirror:
            os.environ["PIPENV_PYPI_MIRROR"] = str(pypi_mirror)
        os.environ["PIP_NO_INPUT"] = "1"
        pipenv_site_dir = get_pipenv_sitedir()
        if pipenv_site_dir is not None:
            os.environ["PIPENV_SITE_DIR"] = pipenv_site_dir
        else:
            os.environ.pop("PIPENV_SITE_DIR", None)
        with console.status("Locking...", spinner=project.s.PIPENV_SPINNER) as st:
            # This conversion is somewhat slow on local and file-type requirements since
            # we now download those requirements / make temporary folders to perform
            # dependency resolution on them, so we are including this step inside the
            # spinner context manager for the UX improvement
            st.console.print("Building requirements...")
            deps = convert_deps_to_pip(
                deps, project.pipfile_sources(), include_index=True
            )
            # Useful for debugging and hitting breakpoints in the resolver
            if project.s.PIPENV_RESOLVER_PARENT_PYTHON:
                try:
                    results = resolver.resolve_packages(
                        pre,
                        clear,
                        project.s.is_verbose(),
                        system=allow_global,
                        write=False,
                        requirements_dir=req_dir,
                        packages=deps,
                        category=category,
                        constraints=deps,
                    )
                    if results:
                        st.console.print(
                            environments.PIPENV_SPINNER_OK_TEXT.format("Success!")
                        )
                except Exception:
                    st.console.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!")
                    )
                    raise  # maybe sys.exit(1) here?
            else:  # Default/Production behavior is to use project python's resolver
                cmd = [
                    which("python", allow_global=allow_global),
                    Path(resolver.__file__.rstrip("co")).as_posix(),
                ]
                if pre:
                    cmd.append("--pre")
                if clear:
                    cmd.append("--clear")
                if allow_global:
                    cmd.append("--system")
                if category:
                    cmd.append("--category")
                    cmd.append(category)
                if project.s.is_verbose():
                    cmd.append("--verbose")
                target_file = tempfile.NamedTemporaryFile(
                    prefix="resolver", suffix=".json", delete=False
                )
                target_file.close()
                cmd.extend(["--write", make_posix(target_file.name)])

                with tempfile.NamedTemporaryFile(
                    mode="w+", prefix="pipenv", suffix="constraints.txt", delete=False
                ) as constraints_file:
                    for dep_name, pip_line in deps.items():
                        constraints_file.write(f"{dep_name}, {pip_line}\n")
                cmd.append("--constraints-file")
                cmd.append(constraints_file.name)
                st.console.print("Resolving dependencies...")
                c = resolve(cmd, st, project=project)
                if c.returncode == 0:
                    try:
                        with open(target_file.name) as fh:
                            results = json.load(fh)
                    except (IndexError, json.JSONDecodeError):
                        click.echo(c.stdout.strip(), err=True)
                        click.echo(c.stderr.strip(), err=True)
                        if os.path.exists(target_file.name):
                            os.unlink(target_file.name)
                        raise RuntimeError("There was a problem with locking.")
                    if os.path.exists(target_file.name):
                        os.unlink(target_file.name)
                    st.console.print(
                        environments.PIPENV_SPINNER_OK_TEXT.format("Success!")
                    )
                    if not project.s.is_verbose() and c.stderr.strip():
                        click.echo(click.style(f"Warning: {c.stderr.strip()}"), err=True)
                else:
                    st.console.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!")
                    )
                    click.echo(f"Output: {c.stdout.strip()}", err=True)
                    click.echo(f"Error: {c.stderr.strip()}", err=True)
    if lockfile_section not in lockfile:
        lockfile[lockfile_section] = {}
    return prepare_lockfile(
        project, results, pipfile, lockfile[lockfile_section], old_lock_data
    )


def resolve_deps(
    deps,
    which,
    project,
    sources=None,
    python=False,
    clear=False,
    pre=False,
    category=None,
    allow_global=False,
    req_dir=None,
):
    """Given a list of dependencies, return a resolved list of dependencies,
    and their hashes, using the warehouse API / pip.
    """
    index_lookup = {}
    markers_lookup = {}
    if not os.environ.get("PIP_SRC"):
        os.environ["PIP_SRC"] = project.virtualenv_src_location
    results = []
    resolver = None
    if not deps:
        return results, resolver
    # First (proper) attempt:
    if not req_dir:
        req_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-requirements")
    with HackedPythonVersion(python_path=project.python(system=allow_global)):
        try:
            results, hashes, internal_resolver = actually_resolve_deps(
                deps,
                index_lookup,
                markers_lookup,
                project,
                sources,
                clear,
                pre,
                category,
                req_dir=req_dir,
            )
        except RuntimeError:
            # Don't exit here, like usual.
            results = None
    # Second (last-resort) attempt:
    if results is None:
        with HackedPythonVersion(
            python_path=project.python(system=allow_global),
        ):
            try:
                # Attempt to resolve again, with different Python version information,
                # particularly for particularly particular packages.
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
                    category,
                    req_dir=req_dir,
                )
            except RuntimeError:
                sys.exit(1)
    return results, internal_resolver


@lru_cache
def get_pipenv_sitedir() -> Optional[str]:
    site_dir = next(
        iter(d for d in pkg_resources.working_set if d.key.lower() == "pipenv"), None
    )
    if site_dir is not None:
        return site_dir.location
    return None
