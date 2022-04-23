import contextlib
import hashlib
import os
import subprocess
import sys
import warnings
from functools import lru_cache

import crayons
from click import echo as click_echo

from pipenv import environments
from pipenv.exceptions import RequirementError, ResolutionFailure
from pipenv.vendor.requirementslib import Pipfile, Requirement
from pipenv.vendor.requirementslib.models.utils import DIRECT_URL_RE
from pipenv.vendor.vistir import TemporaryDirectory, open_file
from pipenv.vendor.vistir.path import create_tracked_tempdir

from .dependencies import (
    HackedPythonVersion,
    clean_pkg_version,
    convert_deps_to_pip,
    get_vcs_deps,
    is_pinned_requirement,
    pep423_name,
    translate_markers,
)
from .indexes import parse_indexes, prepare_pip_source_args
from .internet import _get_requests_session, is_pypi_url
from .locking import format_requirement_for_lockfile, prepare_lockfile
from .shell import make_posix, subprocess_run, temp_environ
from .spinner import create_spinner

if environments.MYPY_RUNNING:
    from typing import Any, Dict, List, Optional, Set, Tuple, Union  # noqa

    from pipenv.project import Project  # noqa
    from pipenv.vendor.requirementslib import Pipfile, Requirement  # noqa
    from pipenv.vendor.requirementslib.models.requirements import Line  # noqa


class HashCacheMixin:

    """Caches hashes of PyPI artifacts so we do not need to re-download them.

    Hashes are only cached when the URL appears to contain a hash in it and the
    cache key includes the hash value returned from the server). This ought to
    avoid issues where the location on the server changes.
    """

    def __init__(self, directory, session):
        self.session = session
        if not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        super().__init__(directory=directory)

    def get_hash(self, link):
        # If there is no link hash (i.e., md5, sha256, etc.), we don't want
        # to store it.
        hash_value = self.get(link.url)
        if not hash_value:
            hash_value = self._get_file_hash(link).encode()
            self.set(link.url, hash_value)
        return hash_value.decode("utf8")

    def _get_file_hash(self, link):
        from pipenv.vendor.pip_shims import shims

        h = hashlib.new(shims.FAVORITE_HASH)
        with open_file(link.url, self.session) as fp:
            for chunk in iter(lambda: fp.read(8096), b""):
                h.update(chunk)
        return ":".join([h.name, h.hexdigest()])


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
    ):
        self.initial_constraints = constraints
        self.req_dir = req_dir
        self.project = project
        self.sources = sources
        self.resolved_tree = set()
        self.hashes = {}
        self.clear = clear
        self.pre = pre
        self.results = None
        self.markers_lookup = markers_lookup if markers_lookup is not None else {}
        self.index_lookup = index_lookup if index_lookup is not None else {}
        self.skipped = skipped if skipped is not None else {}
        self.markers = {}
        self.requires_python_markers = {}
        self._pip_args = None
        self._constraints = None
        self._parsed_constraints = None
        self._resolver = None
        self._finder = None
        self._ignore_compatibility_finder = None
        self._session = None
        self._constraint_file = None
        self._pip_options = None
        self._pip_command = None
        self._retry_attempts = 0
        self._hash_cache = None

    def __repr__(self):
        return (
            "<Resolver (constraints={self.initial_constraints}, req_dir={self.req_dir}, "
            "sources={self.sources})>".format(self=self)
        )

    @staticmethod
    @lru_cache()
    def _get_pip_command():
        from pipenv.vendor.pip_shims import shims

        return shims.InstallCommand()

    @property
    def hash_cache(self):
        from pipenv.vendor.pip_shims import shims

        if not self._hash_cache:
            self._hash_cache = type(
                "HashCache", (HashCacheMixin, shims.SafeFileCache), {}
            )(os.path.join(self.project.s.PIPENV_CACHE_DIR, "hashes"), self.session)
        return self._hash_cache

    @classmethod
    def get_metadata(
        cls,
        deps,  # type: List[str]
        index_lookup,  # type: Dict[str, str]
        markers_lookup,  # type: Dict[str, str]
        project,  # type: Project
        sources,  # type: Dict[str, str]
        req_dir=None,  # type: Optional[str]
        pre=False,  # type: bool
        clear=False,  # type: bool
    ):
        # type: (...) -> Tuple[Set[str], Dict[str, Dict[str, Union[str, bool, List[str]]]], Dict[str, str], Dict[str, str]]
        constraints = set()  # type: Set[str]
        skipped = {}  # type: Dict[str, Dict[str, Union[str, bool, List[str]]]]
        if index_lookup is None:
            index_lookup = {}
        if markers_lookup is None:
            markers_lookup = {}
        if not req_dir:
            req_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-reqdir")
        transient_resolver = cls(
            [],
            req_dir,
            project,
            sources,
            index_lookup=index_lookup,
            markers_lookup=markers_lookup,
            clear=clear,
            pre=pre,
        )
        for dep in deps:
            if not dep:
                continue
            req, req_idx, markers_idx = cls.parse_line(
                dep,
                index_lookup=index_lookup,
                markers_lookup=markers_lookup,
                project=project,
            )
            index_lookup.update(req_idx)
            markers_lookup.update(markers_idx)
            # Add dependencies of any file (e.g. wheels/tarballs), source, or local
            # directories into the initial constraint pool to be resolved with the
            # rest of the dependencies, while adding the files/vcs deps/paths themselves
            # to the lockfile directly
            use_sources = None
            if req.name in index_lookup:
                use_sources = list(
                    filter(lambda s: s.get("name") == index_lookup[req.name], sources)
                )
            if not use_sources:
                use_sources = sources
            transient_resolver = cls(
                [],
                req_dir,
                project,
                use_sources,
                index_lookup=index_lookup,
                markers_lookup=markers_lookup,
                clear=clear,
                pre=pre,
            )
            constraint_update, lockfile_update = cls.get_deps_from_req(
                req, resolver=transient_resolver, resolve_vcs=project.s.PIPENV_RESOLVE_VCS
            )
            constraints |= constraint_update
            skipped.update(lockfile_update)
        return constraints, skipped, index_lookup, markers_lookup

    @classmethod
    def parse_line(
        cls,
        line,  # type: str
        index_lookup=None,  # type: Dict[str, str]
        markers_lookup=None,  # type: Dict[str, str]
        project=None,  # type: Optional[Project]
    ):
        # type: (...) -> Tuple[Requirement, Dict[str, str], Dict[str, str]]

        if index_lookup is None:
            index_lookup = {}
        if markers_lookup is None:
            markers_lookup = {}
        if project is None:
            from pipenv.project import Project

            project = Project()
        index, extra_index, trust_host, remainder = parse_indexes(line)
        line = " ".join(remainder)
        req = None  # type: Requirement
        try:
            req = Requirement.from_line(line)
        except ValueError:
            direct_url = DIRECT_URL_RE.match(line)
            if direct_url:
                line = "{}#egg={}".format(line, direct_url.groupdict()["name"])
                try:
                    req = Requirement.from_line(line)
                except ValueError:
                    raise ResolutionFailure(
                        f"Failed to resolve requirement from line: {line!s}"
                    )
            else:
                raise ResolutionFailure(
                    f"Failed to resolve requirement from line: {line!s}"
                )
        if index:
            try:
                index_lookup[req.normalized_name] = project.get_source(
                    url=index, refresh=True
                ).get("name")
            except TypeError:
                pass
        try:
            req.normalized_name
        except TypeError:
            raise RequirementError(req=req)
        # strip the marker and re-add it later after resolution
        # but we will need a fallback in case resolution fails
        # eg pypiwin32
        if req.markers:
            markers_lookup[req.normalized_name] = req.markers.replace('"', "'")
        return req, index_lookup, markers_lookup

    @classmethod
    def get_deps_from_req(cls, req, resolver=None, resolve_vcs=True):
        # type: (Requirement, Optional["Resolver"], bool) -> Tuple[Set[str], Dict[str, Dict[str, Union[str, bool, List[str]]]]]
        from pipenv.vendor.requirementslib.models.requirements import Requirement
        from pipenv.vendor.requirementslib.models.utils import (
            _requirement_to_str_lowercase_name,
        )
        from pipenv.vendor.requirementslib.utils import is_installable_dir

        # TODO: this is way too complex, refactor this
        constraints = set()  # type: Set[str]
        locked_deps = {}  # type: Dict[str, Dict[str, Union[str, bool, List[str]]]]
        if (req.is_file_or_url or req.is_vcs) and not req.is_wheel:
            # for local packages with setup.py files and potential direct url deps:
            if req.is_vcs:
                req_list, lockfile = get_vcs_deps(reqs=[req])
                req = next(iter(req for req in req_list if req is not None), req_list)
                entry = lockfile[pep423_name(req.normalized_name)]
            else:
                _, entry = req.pipfile_entry
            parsed_line = req.req.parsed_line  # type: Line
            try:
                name = req.normalized_name
            except TypeError:
                raise RequirementError(req=req)
            setup_info = req.req.setup_info
            setup_info.get_info()
            locked_deps[pep423_name(name)] = entry
            requirements = []
            # Allow users to toggle resolution off for non-editable VCS packages
            # but leave it on for local, installable folders on the filesystem
            if resolve_vcs or (
                req.editable
                or parsed_line.is_wheel
                or (
                    req.is_file_or_url
                    and parsed_line.is_local
                    and is_installable_dir(parsed_line.path)
                )
            ):
                requirements = [v for v in getattr(setup_info, "requires", {}).values()]
            for r in requirements:
                if getattr(r, "url", None) and not getattr(r, "editable", False):
                    if r is not None:
                        if not r.url:
                            continue
                        line = _requirement_to_str_lowercase_name(r)
                        new_req, _, _ = cls.parse_line(line)
                        if r.marker and not r.marker.evaluate():
                            new_constraints = {}
                            _, new_entry = req.pipfile_entry
                            new_lock = {pep423_name(new_req.normalized_name): new_entry}
                        else:
                            new_constraints, new_lock = cls.get_deps_from_req(
                                new_req, resolver
                            )
                        locked_deps.update(new_lock)
                        constraints |= new_constraints
                # if there is no marker or there is a valid marker, add the constraint line
                elif r and (not r.marker or (r.marker and r.marker.evaluate())):
                    line = _requirement_to_str_lowercase_name(r)
                    constraints.add(line)
            # ensure the top level entry remains as provided
            # note that we shouldn't pin versions for editable vcs deps
            if not req.is_vcs:
                if req.specifiers:
                    locked_deps[name]["version"] = req.specifiers
                elif parsed_line.setup_info and parsed_line.setup_info.version:
                    locked_deps[name]["version"] = "=={}".format(
                        parsed_line.setup_info.version
                    )
            # if not req.is_vcs:
            locked_deps.update({name: entry})
        else:
            # if the dependency isn't installable, don't add it to constraints
            # and instead add it directly to the lock
            if (
                req
                and req.requirement
                and (req.requirement.marker and not req.requirement.marker.evaluate())
            ):
                pypi = resolver.finder if resolver else None
                ireq = req.ireq
                best_match = (
                    pypi.find_best_candidate(ireq.name, ireq.specifier).best_candidate
                    if pypi
                    else None
                )
                if best_match:
                    ireq.req.specifier = ireq.specifier.__class__(
                        f"=={best_match.version}"
                    )
                    hashes = resolver.collect_hashes(ireq) if resolver else []
                    new_req = Requirement.from_ireq(ireq)
                    new_req = new_req.add_hashes(hashes)
                    name, entry = new_req.pipfile_entry
                    locked_deps[pep423_name(name)] = translate_markers(entry)
                    click_echo(
                        "{} doesn't match your environment, "
                        "its dependencies won't be resolved.".format(req.as_line()),
                        err=True,
                    )
                else:
                    click_echo(
                        "Could not find a version of {} that matches your environment, "
                        "it will be skipped.".format(req.as_line()),
                        err=True,
                    )
                return constraints, locked_deps
            constraints.add(req.constraint_line)
            return constraints, locked_deps
        return constraints, locked_deps

    @classmethod
    def create(
        cls,
        deps,  # type: List[str]
        project,  # type: Project
        index_lookup=None,  # type: Dict[str, str]
        markers_lookup=None,  # type: Dict[str, str]
        sources=None,  # type: List[str]
        req_dir=None,  # type: str
        clear=False,  # type: bool
        pre=False,  # type: bool
    ):
        # type: (...) -> "Resolver"

        if not req_dir:
            req_dir = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")
        if index_lookup is None:
            index_lookup = {}
        if markers_lookup is None:
            markers_lookup = {}
        if sources is None:
            sources = project.sources
        constraints, skipped, index_lookup, markers_lookup = cls.get_metadata(
            deps,
            index_lookup,
            markers_lookup,
            project,
            sources,
            req_dir=req_dir,
            pre=pre,
            clear=clear,
        )
        return Resolver(
            constraints,
            req_dir,
            project,
            sources,
            index_lookup=index_lookup,
            markers_lookup=markers_lookup,
            skipped=skipped,
            clear=clear,
            pre=pre,
        )

    @classmethod
    def from_pipfile(cls, project, pipfile=None, dev=False, pre=False, clear=False):
        # type: (Optional[Project], Optional[Pipfile], bool, bool, bool) -> "Resolver"

        if not pipfile:
            pipfile = project._pipfile
        req_dir = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")
        index_lookup, markers_lookup = {}, {}
        deps = set()
        if dev:
            deps.update({req.as_line() for req in pipfile.dev_packages})
        deps.update({req.as_line() for req in pipfile.packages})
        constraints, skipped, index_lookup, markers_lookup = cls.get_metadata(
            list(deps),
            index_lookup,
            markers_lookup,
            project,
            project.sources,
            req_dir=req_dir,
            pre=pre,
            clear=clear,
        )
        return Resolver(
            constraints,
            req_dir,
            project,
            project.sources,
            index_lookup=index_lookup,
            markers_lookup=markers_lookup,
            skipped=skipped,
            clear=clear,
            pre=pre,
        )

    @property
    def pip_command(self):
        if self._pip_command is None:
            self._pip_command = self._get_pip_command()
        return self._pip_command

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

    @property
    def pip_args(self):
        use_pep517 = environments.get_from_env("USE_PEP517", prefix="PIP")
        build_isolation = environments.get_from_env("BUILD_ISOLATION", prefix="PIP")
        if self._pip_args is None:
            self._pip_args = self.prepare_pip_args(
                use_pep517=use_pep517, build_isolation=build_isolation
            )
        return self._pip_args

    def prepare_constraint_file(self):
        from pipenv.vendor.vistir.path import create_tracked_tempfile

        constraints_file = create_tracked_tempfile(
            mode="w",
            prefix="pipenv-",
            suffix="-constraints.txt",
            dir=self.req_dir,
            delete=False,
        )
        skip_args = ("build-isolation", "use-pep517", "cache-dir")
        args_to_add = [
            arg
            for arg in self.pip_args
            if not any(bad_arg in arg for bad_arg in skip_args)
        ]
        if self.sources:
            requirementstxt_sources = " ".join(args_to_add) if args_to_add else ""
            requirementstxt_sources = requirementstxt_sources.replace(" --", "\n--")
            constraints_file.write(f"{requirementstxt_sources}\n")
        constraints = self.initial_constraints
        constraints_file.write("\n".join([c for c in constraints]))
        constraints_file.close()
        return constraints_file.name

    @property
    def constraint_file(self):
        if self._constraint_file is None:
            self._constraint_file = self.prepare_constraint_file()
        return self._constraint_file

    @property
    def pip_options(self):
        if self._pip_options is None:
            pip_options, _ = self.pip_command.parser.parse_args(self.pip_args)
            pip_options.cache_dir = self.project.s.PIPENV_CACHE_DIR
            pip_options.no_python_version_warning = True
            pip_options.no_input = self.project.settings.get("disable_pip_input", True)
            pip_options.progress_bar = "off"
            pip_options.ignore_requires_python = True
            pip_options.pre = self.pre or self.project.settings.get(
                "allow_prereleases", False
            )
            self._pip_options = pip_options
        return self._pip_options

    @property
    def session(self):
        if self._session is None:
            self._session = self.pip_command._build_session(self.pip_options)
        return self._session

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

    @property
    def finder(self):
        from pipenv.vendor.pip_shims import shims

        if self._finder is None:
            self._finder = shims.get_package_finder(
                install_cmd=self.pip_command,
                options=self.pip_options,
                session=self.session,
            )
        index_lookup = self.prepare_index_lookup()
        self._finder._link_collector.index_lookup = index_lookup
        self._finder._link_collector.search_scope.index_lookup = index_lookup
        return self._finder

    @property
    def ignore_compatibility_finder(self):
        from pipenv.vendor.pip_shims import shims

        if self._ignore_compatibility_finder is None:
            ignore_compatibility_finder = shims.get_package_finder(
                install_cmd=self.pip_command,
                options=self.pip_options,
                session=self.session,
            )
            # It would be nice if `shims.get_package_finder` took an
            # `ignore_compatibility` parameter, but that's some vendorered code
            # we'd rather avoid touching.
            index_lookup = self.prepare_index_lookup()
            ignore_compatibility_finder._ignore_compatibility = True
            self._ignore_compatibility_finder = ignore_compatibility_finder
            self._ignore_compatibility_finder._link_collector.index_lookup = index_lookup
            self._ignore_compatibility_finder._link_collector.search_scope.index_lookup = (
                index_lookup
            )
        return self._ignore_compatibility_finder

    @property
    def parsed_constraints(self):
        from pipenv.vendor.pip_shims import shims

        pip_options = self.pip_options
        pip_options.extra_index_urls = []
        if self._parsed_constraints is None:
            self._parsed_constraints = shims.parse_requirements(
                self.constraint_file,
                finder=self.finder,
                session=self.session,
                options=pip_options,
            )
        return self._parsed_constraints

    @property
    def constraints(self):
        from pipenv.patched.notpip._internal.req.constructors import (
            install_req_from_parsed_requirement,
        )

        if self._constraints is None:
            self._constraints = [
                install_req_from_parsed_requirement(
                    c,
                    isolated=self.pip_options.build_isolation,
                    use_pep517=self.pip_options.use_pep517,
                    user_supplied=True,
                )
                for c in self.parsed_constraints
            ]
        return self._constraints

    @contextlib.contextmanager
    def get_resolver(self, clear=False):
        from pipenv.vendor.pip_shims.shims import (
            WheelCache,
            get_requirement_tracker,
            global_tempdir_manager,
        )

        with global_tempdir_manager(), get_requirement_tracker() as req_tracker, TemporaryDirectory(
            suffix="-build", prefix="pipenv-"
        ) as directory:
            pip_options = self.pip_options
            finder = self.finder
            wheel_cache = WheelCache(pip_options.cache_dir, pip_options.format_control)
            directory.path = directory.name
            preparer = self.pip_command.make_requirement_preparer(
                temp_build_dir=directory,
                options=pip_options,
                req_tracker=req_tracker,
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
        from pipenv.exceptions import ResolutionFailure
        from pipenv.vendor.pip_shims.shims import InstallationError

        self.constraints  # For some reason it is important to evaluate constraints before resolver context
        with temp_environ(), self.get_resolver() as resolver:
            try:
                results = resolver.resolve(self.constraints, check_supported_wheels=False)
            except InstallationError as e:
                raise ResolutionFailure(message=str(e))
            else:
                self.results = set(results.all_requirements)
                self.resolved_tree.update(self.results)
        return self.resolved_tree

    def resolve_constraints(self):
        from pipenv.vendor.requirementslib.models.markers import marker_from_specifier

        new_tree = set()
        for result in self.resolved_tree:
            if result.markers:
                self.markers[result.name] = result.markers
            else:
                candidate = self.finder.find_best_candidate(
                    result.name, result.specifier
                ).best_candidate
                if candidate:
                    requires_python = candidate.link.requires_python
                    if requires_python:
                        marker = marker_from_specifier(requires_python)
                        self.markers[result.name] = marker
                        result.markers = marker
                        if result.req:
                            result.req.marker = marker
            new_tree.add(result)
        self.resolved_tree = new_tree

    @classmethod
    def prepend_hash_types(cls, checksums, hash_type):
        cleaned_checksums = set()
        for checksum in checksums:
            if not checksum:
                continue
            if not checksum.startswith(f"{hash_type}:"):
                checksum = f"{hash_type}:{checksum}"
            cleaned_checksums.add(checksum)
        return cleaned_checksums

    def _get_hashes_from_pypi(self, ireq):
        from pipenv.vendor.pip_shims import shims

        pkg_url = f"https://pypi.org/pypi/{ireq.name}/json"
        session = _get_requests_session(self.project.s.PIPENV_MAX_RETRIES)
        try:
            collected_hashes = set()
            # Grab the hashes from the new warehouse API.
            r = session.get(pkg_url, timeout=10)
            api_releases = r.json()["releases"]
            cleaned_releases = {}
            for api_version, api_info in api_releases.items():
                api_version = clean_pkg_version(api_version)
                cleaned_releases[api_version] = api_info
            version = ""
            if ireq.specifier:
                spec = next(iter(s for s in ireq.specifier), None)
                if spec:
                    version = spec.version
            for release in cleaned_releases[version]:
                collected_hashes.add(release["digests"][shims.FAVORITE_HASH])
            return self.prepend_hash_types(collected_hashes, shims.FAVORITE_HASH)
        except (ValueError, KeyError, ConnectionError):
            if self.project.s.is_verbose():
                click_echo(
                    "{}: Error generating hash for {}".format(
                        crayons.red("Warning", bold=True), ireq.name
                    ),
                    err=True,
                )
            return None

    def collect_hashes(self, ireq):
        link = ireq.link  # Handle VCS and file links first
        if link and (link.is_vcs or (link.is_file and link.is_existing_dir())):
            return set()
        if link and ireq.original_link:
            return {self._get_hash_from_link(ireq.original_link)}

        if not is_pinned_requirement(ireq):
            return set()

        sources = self.sources  # Enforce index restrictions
        if ireq.name in self.index_lookup:
            sources = list(
                filter(lambda s: s.get("name") == self.index_lookup[ireq.name], sources)
            )
        if any(is_pypi_url(source["url"]) for source in sources):
            hashes = self._get_hashes_from_pypi(ireq)
            if hashes:
                return hashes

        applicable_candidates = self.ignore_compatibility_finder.find_best_candidate(
            ireq.name, ireq.specifier
        ).iter_applicable()
        applicable_candidates = list(applicable_candidates)
        if applicable_candidates:
            return {
                self._get_hash_from_link(candidate.link)
                for candidate in applicable_candidates
            }
        if link:
            return {self._get_hash_from_link(link)}
        return set()

    def resolve_hashes(self):
        if self.results is not None:
            for ireq in self.results:
                self.hashes[ireq] = self.collect_hashes(ireq)
        return self.hashes

    def _get_hash_from_link(self, link):
        from pipenv.vendor.pip_shims import shims

        if link.hash and link.hash_name == shims.FAVORITE_HASH:
            return f"{link.hash_name}:{link.hash}"

        return self.hash_cache.get_hash(link)

    def _clean_skipped_result(self, req, value):
        ref = None
        if req.is_vcs:
            ref = req.commit_hash
        ireq = req.as_ireq()
        entry = value.copy()
        entry["name"] = req.name
        if entry.get("editable", False) and entry.get("version"):
            del entry["version"]
        ref = ref if ref is not None else entry.get("ref")
        if ref:
            entry["ref"] = ref
        collected_hashes = self.collect_hashes(ireq)
        if collected_hashes:
            entry["hashes"] = sorted(set(collected_hashes))
        return req.name, entry

    def clean_results(self):
        from pipenv.vendor.requirementslib.models.requirements import Requirement

        reqs = [(Requirement.from_ireq(ireq), ireq) for ireq in self.resolved_tree]
        results = {}
        for req, ireq in reqs:
            if req.vcs and req.editable and not req.is_direct_url:
                continue
            elif req.normalized_name in self.skipped.keys():
                continue
            collected_hashes = self.hashes.get(ireq, set())
            req = req.add_hashes(collected_hashes)
            if collected_hashes:
                collected_hashes = sorted(collected_hashes)
            name, entry = format_requirement_for_lockfile(
                req, self.markers_lookup, self.index_lookup, collected_hashes
            )
            entry = translate_markers(entry)
            if name in results:
                results[name].update(entry)
            else:
                results[name] = entry
        for k in list(self.skipped.keys()):
            req = Requirement.from_pipfile(k, self.skipped[k])
            name, entry = self._clean_skipped_result(req, self.skipped[k])
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
    req_dir=None,
):
    if not req_dir:
        req_dir = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")
    warning_list = []

    with warnings.catch_warnings(record=True) as warning_list:
        resolver = Resolver.create(
            deps, project, index_lookup, markers_lookup, sources, req_dir, clear, pre
        )
        resolver.resolve()
        hashes = resolver.resolve_hashes()
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
    return (results, hashes, resolver.markers_lookup, resolver, resolver.skipped)


def resolve(cmd, sp, project):
    from pipenv._compat import decode_output
    from pipenv.cmdparse import Script
    from pipenv.vendor.vistir.misc import echo

    c = subprocess_run(Script.parse(cmd).cmd_args, block=False, env=os.environ.copy())
    is_verbose = project.s.is_verbose()
    err = ""
    for line in iter(c.stderr.readline, ""):
        line = decode_output(line)
        if not line.rstrip():
            continue
        err += line
        if is_verbose:
            sp.hide_and_write(line.rstrip())

    c.wait()
    returncode = c.poll()
    out = c.stdout.read()
    if returncode != 0:
        sp.red.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!"))
        echo(out.strip(), err=True)
        if not is_verbose:
            echo(err, err=True)
        sys.exit(returncode)
    if is_verbose:
        echo(out.strip(), err=True)
    return subprocess.CompletedProcess(c.args, returncode, out, err)


def venv_resolve_deps(
    deps,
    which,
    project,
    pre=False,
    clear=False,
    allow_global=False,
    pypi_mirror=None,
    dev=False,
    pipfile=None,
    lockfile=None,
    keep_outdated=False,
):
    """
    Resolve dependencies for a pipenv project, acts as a portal to the target environment.

    Regardless of whether a virtual environment is present or not, this will spawn
    a subprocess which is isolated to the target environment and which will perform
    dependency resolution.  This function reads the output of that call and mutates
    the provided lockfile accordingly, returning nothing.

    :param List[:class:`~requirementslib.Requirement`] deps: A list of dependencies to resolve.
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
    :param bool keep_outdated: Whether to retain outdated dependencies and resolve with them in mind, defaults to False
    :raises RuntimeError: Raised on resolution failure
    :return: Nothing
    :rtype: None
    """

    import json
    import tempfile

    from pipenv import resolver
    from pipenv._compat import decode_for_output
    from pipenv.vendor.vistir.compat import Path

    results = []
    pipfile_section = "dev-packages" if dev else "packages"
    lockfile_section = "develop" if dev else "default"
    if not deps:
        if not project.pipfile_exists:
            return None
        deps = project.parsed_pipfile.get(pipfile_section, {})
    if not deps:
        return None

    if not pipfile:
        pipfile = getattr(project, pipfile_section, {})
    if not lockfile:
        lockfile = project._lockfile
    req_dir = create_tracked_tempdir(prefix="pipenv", suffix="requirements")
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
    if dev:
        cmd.append("--dev")
    target_file = tempfile.NamedTemporaryFile(
        prefix="resolver", suffix=".json", delete=False
    )
    target_file.close()
    cmd.extend(["--write", make_posix(target_file.name)])
    with temp_environ():
        os.environ.update({k: str(val) for k, val in os.environ.items()})
        if pypi_mirror:
            os.environ["PIPENV_PYPI_MIRROR"] = str(pypi_mirror)
        os.environ["PIPENV_VERBOSITY"] = str(project.s.PIPENV_VERBOSITY)
        os.environ["PIPENV_REQ_DIR"] = req_dir
        os.environ["PIP_NO_INPUT"] = "1"
        pipenv_site_dir = get_pipenv_sitedir()
        if pipenv_site_dir is not None:
            os.environ["PIPENV_SITE_DIR"] = pipenv_site_dir
        else:
            os.environ.pop("PIPENV_SITE_DIR", None)
        if keep_outdated:
            os.environ["PIPENV_KEEP_OUTDATED"] = "1"
        with create_spinner(
            text=decode_for_output("Locking..."), setting=project.s
        ) as sp:
            # This conversion is somewhat slow on local and file-type requirements since
            # we now download those requirements / make temporary folders to perform
            # dependency resolution on them, so we are including this step inside the
            # spinner context manager for the UX improvement
            sp.write(decode_for_output("Building requirements..."))
            deps = convert_deps_to_pip(deps, project, r=False, include_index=True)
            constraints = set(deps)
            os.environ["PIPENV_PACKAGES"] = str("\n".join(constraints))
            sp.write(decode_for_output("Resolving dependencies..."))
            c = resolve(cmd, sp, project=project)
            results = c.stdout.strip()
            if c.returncode == 0:
                sp.green.ok(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
                if not project.s.is_verbose() and c.stderr.strip():
                    click_echo(crayons.yellow(f"Warning: {c.stderr.strip()}"), err=True)
            else:
                sp.red.fail(
                    environments.PIPENV_SPINNER_FAIL_TEXT.format("Locking Failed!")
                )
                click_echo(f"Output: {c.stdout.strip()}", err=True)
                click_echo(f"Error: {c.stderr.strip()}", err=True)
    try:
        with open(target_file.name) as fh:
            results = json.load(fh)
    except (IndexError, json.JSONDecodeError):
        click_echo(c.stdout.strip(), err=True)
        click_echo(c.stderr.strip(), err=True)
        if os.path.exists(target_file.name):
            os.unlink(target_file.name)
        raise RuntimeError("There was a problem with locking.")
    if os.path.exists(target_file.name):
        os.unlink(target_file.name)
    if lockfile_section not in lockfile:
        lockfile[lockfile_section] = {}
    prepare_lockfile(results, pipfile, lockfile[lockfile_section])


def resolve_deps(
    deps,
    which,
    project,
    sources=None,
    python=False,
    clear=False,
    pre=False,
    allow_global=False,
    req_dir=None,
):
    """Given a list of dependencies, return a resolved list of dependencies,
    and their hashes, using the warehouse API / pip.
    """
    index_lookup = {}
    markers_lookup = {}
    python_path = which("python", allow_global=allow_global)
    if not os.environ.get("PIP_SRC"):
        os.environ["PIP_SRC"] = project.virtualenv_src_location
    backup_python_path = sys.executable
    results = []
    resolver = None
    if not deps:
        return results, resolver
    # First (proper) attempt:
    req_dir = req_dir if req_dir else os.environ.get("req_dir", None)
    if not req_dir:
        req_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-requirements")
    with HackedPythonVersion(python_version=python, python_path=python_path):
        try:
            results, hashes, markers_lookup, resolver, skipped = actually_resolve_deps(
                deps,
                index_lookup,
                markers_lookup,
                project,
                sources,
                clear,
                pre,
                req_dir=req_dir,
            )
        except RuntimeError:
            # Don't exit here, like usual.
            results = None
    # Second (last-resort) attempt:
    if results is None:
        with HackedPythonVersion(
            python_version=".".join([str(s) for s in sys.version_info[:3]]),
            python_path=backup_python_path,
        ):
            try:
                # Attempt to resolve again, with different Python version information,
                # particularly for particularly particular packages.
                (
                    results,
                    hashes,
                    markers_lookup,
                    resolver,
                    skipped,
                ) = actually_resolve_deps(
                    deps,
                    index_lookup,
                    markers_lookup,
                    project,
                    sources,
                    clear,
                    pre,
                    req_dir=req_dir,
                )
            except RuntimeError:
                sys.exit(1)
    return results, resolver


@lru_cache()
def get_pipenv_sitedir():
    # type: () -> Optional[str]
    import pkg_resources

    site_dir = next(
        iter(d for d in pkg_resources.working_set if d.key.lower() == "pipenv"), None
    )
    if site_dir is not None:
        return site_dir.location
    return None
