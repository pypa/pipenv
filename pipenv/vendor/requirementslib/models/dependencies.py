import atexit
import contextlib
import copy
import functools
import os
from json import JSONDecodeError

import pipenv.vendor.attr as attr
import pipenv.patched.pip._vendor.requests as requests
from pipenv.patched.pip._internal.cache import WheelCache
from pipenv.patched.pip._internal.operations.build.build_tracker import get_build_tracker
from pipenv.patched.pip._internal.req.constructors import install_req_from_line
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.req.req_set import RequirementSet
from pipenv.patched.pip._internal.utils.temp_dir import TempDirectory, global_tempdir_manager
from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse

from ..environment import MYPY_RUNNING
from ..fileutils import create_tracked_tempdir
from ..utils import (
    get_package_finder,
    get_pip_command,
    prepare_pip_source_args,
    temp_environ,
)
from .cache import CACHE_DIR, DependencyCache
from .setup_info import SetupInfo
from .utils import (
    clean_requires_python,
    format_requirement,
    full_groupby,
    is_pinned_requirement,
    key_from_ireq,
    make_install_requirement,
    name_from_req,
    version_from_ireq,
)

if MYPY_RUNNING:
    from typing import Any, Dict, List, Optional, Set, Text, TypeVar, Union

    from pipenv.patched.pip._internal.commands import Command
    from pipenv.patched.pip._internal.index.package_finder import PackageFinder
    from pipenv.patched.pip._internal.models.candidate import InstallationCandidate
    from pipenv.patched.pip._vendor.packaging.requirements import Requirement as PackagingRequirement

    TRequirement = TypeVar("TRequirement")
    RequirementType = TypeVar(
        "RequirementType", covariant=True, bound=PackagingRequirement
    )
    MarkerType = TypeVar("MarkerType", covariant=True, bound=Marker)
    STRING_TYPE = Union[str, bytes, Text]
    S = TypeVar("S", bytes, str, Text)


PKGS_DOWNLOAD_DIR = os.path.join(CACHE_DIR, "pkgs")
WHEEL_DOWNLOAD_DIR = os.path.join(CACHE_DIR, "wheels")

DEPENDENCY_CACHE = DependencyCache()


@contextlib.contextmanager
def _get_wheel_cache():
    with global_tempdir_manager():
        yield WheelCache(CACHE_DIR)


def _get_filtered_versions(ireq, versions, prereleases):
    return set(ireq.specifier.filter(versions, prereleases=prereleases))


def find_all_matches(finder, ireq, pre=False):
    # type: (PackageFinder, InstallRequirement, bool) -> List[InstallationCandidate]
    """Find all matching dependencies using the supplied finder and the given
    ireq.

    :param finder: A package finder for discovering matching candidates.
    :type finder: :class:`~pipenv.patched.pip._internal.index.PackageFinder`
    :param ireq: An install requirement.
    :type ireq: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :return: A list of matching candidates.
    :rtype: list[:class:`~pipenv.patched.pip._internal.index.InstallationCandidate`]
    """

    candidates = clean_requires_python(finder.find_all_candidates(ireq.name))
    versions = {candidate.version for candidate in candidates}
    allowed_versions = _get_filtered_versions(ireq, versions, pre)
    if not pre and not allowed_versions:
        allowed_versions = _get_filtered_versions(ireq, versions, True)
    candidates = {c for c in candidates if c.version in allowed_versions}
    return candidates


@attr.s
class AbstractDependency(object):
    name = attr.ib()  # type: STRING_TYPE
    specifiers = attr.ib()
    markers = attr.ib()
    candidates = attr.ib()
    requirement = attr.ib()
    parent = attr.ib()
    finder = attr.ib()
    dep_dict = attr.ib(default=attr.Factory(dict))

    @property
    def version_set(self):
        """Return the set of versions for the candidates in this abstract
        dependency.

        :return: A set of matching versions
        :rtype: set(str)
        """

        if len(self.candidates) == 1:
            return set()
        return set(parse(version_from_ireq(c)) for c in self.candidates)

    def compatible_versions(self, other):
        """Find compatible version numbers between this abstract dependency and
        another one.

        :param other: An abstract dependency to compare with.
        :type other: :class:`~requirementslib.models.dependency.AbstractDependency`
        :return: A set of compatible version strings
        :rtype: set(str)
        """

        if len(self.candidates) == 1 and next(iter(self.candidates)).editable:
            return self
        elif len(other.candidates) == 1 and next(iter(other.candidates)).editable:
            return other
        return self.version_set & other.version_set

    def compatible_abstract_dep(self, other):
        """Merge this abstract dependency with another one.

        Return the result of the merge as a new abstract dependency.

        :param other: An abstract dependency to merge with
        :type other: :class:`~requirementslib.models.dependency.AbstractDependency`
        :return: A new, combined abstract dependency
        :rtype: :class:`~requirementslib.models.dependency.AbstractDependency`
        """

        from .requirements import Requirement

        if len(self.candidates) == 1 and next(iter(self.candidates)).editable:
            return self
        elif len(other.candidates) == 1 and next(iter(other.candidates)).editable:
            return other
        new_specifiers = self.specifiers & other.specifiers
        markers = set(self.markers) if self.markers else set()
        if other.markers:
            markers.add(other.markers)
        new_markers = None
        if markers:
            new_markers = Marker(" or ".join(str(m) for m in sorted(markers)))
        new_ireq = copy.deepcopy(self.requirement.ireq)
        new_ireq.req.specifier = new_specifiers
        new_ireq.req.marker = new_markers
        new_requirement = Requirement.from_line(format_requirement(new_ireq))
        compatible_versions = self.compatible_versions(other)
        if isinstance(compatible_versions, AbstractDependency):
            return compatible_versions
        candidates = [
            c
            for c in self.candidates
            if parse(version_from_ireq(c)) in compatible_versions
        ]
        dep_dict = {}
        candidate_strings = [format_requirement(c) for c in candidates]
        for c in candidate_strings:
            if c in self.dep_dict:
                dep_dict[c] = self.dep_dict.get(c)
        return AbstractDependency(
            name=self.name,
            specifiers=new_specifiers,
            markers=new_markers,
            candidates=candidates,
            requirement=new_requirement,
            parent=self.parent,
            dep_dict=dep_dict,
            finder=self.finder,
        )

    def get_deps(self, candidate):
        """Get the dependencies of the supplied candidate.

        :param candidate: An installrequirement
        :type candidate: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
        :return: A list of abstract dependencies
        :rtype: list[:class:`~requirementslib.models.dependency.AbstractDependency`]
        """

        key = format_requirement(candidate)
        if key not in self.dep_dict:
            from .requirements import Requirement

            req = Requirement.from_line(key)
            req = req.merge_markers(self.markers)
            self.dep_dict[key] = req.abstract_dependencies()
        return self.dep_dict[key]

    @classmethod
    def from_requirement(cls, requirement, parent=None):
        """Creates a new
        :class:`~requirementslib.models.dependency.AbstractDependency` from a
        :class:`~requirementslib.models.requirements.Requirement` object.

        This class is used to find all candidates matching a given set of specifiers
        and a given requirement.

        :param requirement: A requirement for resolution
        :type requirement: :class:`~requirementslib.models.requirements.Requirement` object.
        """
        name = requirement.normalized_name
        specifiers = requirement.ireq.specifier if not requirement.editable else ""
        markers = requirement.ireq.markers
        extras = requirement.ireq.extras
        is_pinned = is_pinned_requirement(requirement.ireq)
        is_constraint = bool(parent)
        _, finder = get_finder(sources=None)
        candidates = []
        if not is_pinned and not requirement.editable:
            for r in requirement.find_all_matches(finder=finder):
                req = make_install_requirement(
                    name,
                    r.version,
                    extras=extras,
                    markers=markers,
                    constraint=is_constraint,
                )
                req.req.link = getattr(r, "location", getattr(r, "link", None))
                req.parent = parent
                candidates.append(req)
                candidates = sorted(
                    set(candidates),
                    key=lambda k: parse(version_from_ireq(k)),
                )
        else:
            candidates = [requirement.ireq]
        return cls(
            name=name,
            specifiers=specifiers,
            markers=markers,
            candidates=candidates,
            requirement=requirement,
            parent=parent,
            finder=finder,
        )

    @classmethod
    def from_string(cls, line, parent=None):
        from .requirements import Requirement

        req = Requirement.from_line(line)
        abstract_dep = cls.from_requirement(req, parent=parent)
        return abstract_dep


def get_abstract_dependencies(reqs, parent=None):
    """Get all abstract dependencies for a given list of requirements.

    Given a set of requirements, convert each requirement to an Abstract Dependency.

    :param reqs: A list of Requirements
    :type reqs: list[:class:`~requirementslib.models.requirements.Requirement`]
    :param parent: The parent of this list of dependencies, defaults to None
    :param parent: :class:`~requirementslib.models.requirements.Requirement`, optional
    :return: A list of Abstract Dependencies
    :rtype: list[:class:`~requirementslib.models.dependency.AbstractDependency`]
    """
    deps = []
    from .requirements import Requirement

    for req in reqs:
        if isinstance(req, InstallRequirement):
            requirement = Requirement.from_line("{0}{1}".format(req.name, req.specifier))
            if req.link:
                requirement.req.link = req.link
                requirement.markers = req.markers
                requirement.req.markers = req.markers
                requirement.extras = req.extras
                requirement.req.extras = req.extras
        elif isinstance(req, Requirement):
            requirement = copy.deepcopy(req)
        else:
            requirement = Requirement.from_line(req)
        dep = AbstractDependency.from_requirement(requirement, parent=parent)
        deps.append(dep)
    return deps


def get_dependencies(ireq, sources=None, parent=None):
    # type: (Union[InstallRequirement, InstallationCandidate], Optional[List[Dict[S, Union[S, bool]]]], Optional[AbstractDependency]) -> Set[S, ...]
    """Get all dependencies for a given install requirement.

    :param ireq: A single InstallRequirement
    :type ireq: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :param sources: Pipfile-formatted sources, defaults to None
    :type sources: list[dict], optional
    :param parent: The parent of this list of dependencies, defaults to None
    :type parent: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str)
    """
    if not isinstance(ireq, InstallRequirement):
        name = getattr(ireq, "project_name", getattr(ireq, "project", ireq.name))
        version = getattr(ireq, "version", None)
        if not version:
            ireq = install_req_from_line("{0}".format(name))
        else:
            ireq = install_req_from_line("{0}=={1}".format(name, version))
    getters = [
        get_dependencies_from_cache,
        get_dependencies_from_wheel_cache,
        get_dependencies_from_json,
        functools.partial(get_dependencies_from_index, sources=sources),
    ]
    for getter in getters:
        deps = getter(ireq)
        if deps is not None:
            return deps
    raise RuntimeError("failed to get dependencies for {}".format(ireq))


def get_dependencies_from_wheel_cache(ireq):
    # type: (InstallRequirement) -> Optional[Set[InstallRequirement]]
    """Retrieves dependencies for the given install requirement from the wheel
    cache.

    :param ireq: A single InstallRequirement
    :type ireq: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str) or None
    """

    if ireq.editable or not is_pinned_requirement(ireq):
        return
    with _get_wheel_cache() as wheel_cache:
        matches = wheel_cache.get(ireq.link, name_from_req(ireq.req), ireq.markers)
        if matches:
            matches = set(matches)
            if not DEPENDENCY_CACHE.get(ireq):
                DEPENDENCY_CACHE[ireq] = [format_requirement(m) for m in matches]
            return matches
        return None


def _marker_contains_extra(ireq):
    # TODO: Implement better parsing logic avoid false-positives.
    return "extra" in repr(ireq.markers)


def get_dependencies_from_json(ireq):
    """Retrieves dependencies for the given install requirement from the json
    api.

    :param ireq: A single InstallRequirement
    :type ireq: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str) or None
    """

    if ireq.editable or not is_pinned_requirement(ireq):
        return

    # It is technically possible to parse extras out of the JSON API's
    # requirement format, but it is such a chore let's just use the simple API.
    if ireq.extras:
        return

    session = requests.session()
    atexit.register(session.close)
    version = str(ireq.req.specifier).lstrip("=")

    def gen(ireq):
        info = None
        try:
            info = session.get(
                "https://pypi.org/pypi/{0}/{1}/json".format(ireq.req.name, version)
            ).json()["info"]
        finally:
            session.close()
        requires_dist = info.get("requires_dist", info.get("requires"))
        if not requires_dist:  # The API can return None for this.
            return
        for requires in requires_dist:
            i = install_req_from_line(requires)
            # See above, we don't handle requirements with extras.
            if not _marker_contains_extra(i):
                yield format_requirement(i)

    if ireq not in DEPENDENCY_CACHE:
        try:
            reqs = DEPENDENCY_CACHE[ireq] = list(gen(ireq))
        except JSONDecodeError:
            return
        req_iter = iter(reqs)
    else:
        req_iter = gen(ireq)
    return set(req_iter)


def get_dependencies_from_cache(ireq):
    """Retrieves dependencies for the given install requirement from the
    dependency cache.

    :param ireq: A single InstallRequirement
    :type ireq: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str) or None
    """
    if ireq.editable or not is_pinned_requirement(ireq):
        return
    if ireq not in DEPENDENCY_CACHE:
        return
    cached = set(DEPENDENCY_CACHE[ireq])

    # Preserving sanity: Run through the cache and make sure every entry if
    # valid. If this fails, something is wrong with the cache. Drop it.
    try:
        broken = False
        for line in cached:
            dep_ireq = install_req_from_line(line)
            name = canonicalize_name(dep_ireq.name)
            if _marker_contains_extra(dep_ireq):
                broken = True  # The "extra =" marker breaks everything.
            elif name == canonicalize_name(ireq.name):
                broken = True  # A package cannot depend on itself.
            if broken:
                break
    except Exception:
        broken = True

    if broken:
        del DEPENDENCY_CACHE[ireq]
        return

    return cached


def is_python(section):
    return section.startswith("[") and ":" in section


def get_resolver(
    finder, build_tracker, pip_options, session, directory, install_command=None
):
    wheel_cache = WheelCache(pip_options.cache_dir)
    if install_command is None:
        install_command = get_pip_command()
    preparer = install_command.make_requirement_preparer(
        temp_build_dir=directory,
        options=pip_options,
        build_tracker=build_tracker,
        session=session,
        finder=finder,
        use_user_site=False,
    )
    resolver = install_command.make_resolver(
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
    return resolver


def resolve(ireq, sources, install_command, pip_options):
    with global_tempdir_manager(), get_build_tracker() as build_tracker, TempDirectory() as directory:
        session, finder = get_finder(
            sources=sources, pip_command=install_command, pip_options=pip_options
        )
        resolver = get_resolver(
            finder=finder,
            build_tracker=build_tracker,
            pip_options=pip_options,
            session=session,
            directory=directory,
            install_command=install_command,
        )
        reqset = RequirementSet(install_command)
        reqset.add_named_requirement(ireq)
        resolver_args = []
        resolver_args.append([ireq])
        resolver_args.append(True)  # check_supported_wheels
        if getattr(reqset, "prepare_files", None):
            reqset.prepare_files(finder)
            result = reqset.requirements
            reqset.cleanup_files()
            return result
        result_reqset = resolver.resolve(*resolver_args)
        if result_reqset is None:
            result_reqset = reqset
        results = result_reqset.requirements
        cleanup_fn = getattr(reqset, "cleanup_files", None)
        if cleanup_fn is not None:
            cleanup_fn()
        return results


def get_dependencies_from_index(dep, sources=None, pip_options=None, wheel_cache=None):
    """Retrieves dependencies for the given install requirement from the pip
    resolver.

    :param dep: A single InstallRequirement
    :type dep: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :param sources: Pipfile-formatted sources, defaults to None
    :type sources: list[dict], optional
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str) or None
    """
    install_command = get_pip_command()
    if pip_options is None:
        pip_options = get_pip_options(sources=sources, pip_command=install_command)
    dep.is_direct = True
    setup_requires = {}
    with temp_environ():
        os.environ["PIP_EXISTS_ACTION"] = "i"
        if dep.editable and not dep.prepared and not dep.req:
            setup_info = SetupInfo.from_ireq(dep)
            results = setup_info.get_info()
            setup_requires.update(results["setup_requires"])
            requirements = set(results["requires"].values())
        else:
            results = resolve(
                dep,
                sources=sources,
                install_command=install_command,
                pip_options=pip_options,
            )
            requirements = [v for v in results.values() if v.name != dep.name]
        requirements = set([format_requirement(r) for r in requirements])
    if not dep.editable and is_pinned_requirement(dep) and requirements is not None:
        DEPENDENCY_CACHE[dep] = list(requirements)
    return requirements


def get_pip_options(args=None, sources=None, pip_command=None):
    """Build a pip command from a list of sources.

    :param args: positional arguments passed through to the pip parser
    :param sources: A list of pipfile-formatted sources, defaults to None
    :param sources: list[dict], optional
    :param pip_command: A pre-built pip command instance
    :type pip_command: :class:`~pipenv.patched.pip._internal.cli.base_command.Command`
    :return: An instance of pip_options using the supplied arguments plus sane defaults
    :rtype: :class:`~pipenv.patched.pip._internal.cli.cmdoptions`
    """

    if not pip_command:
        pip_command = get_pip_command()
    if not sources:
        sources = [{"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}]
    os.makedirs(CACHE_DIR, mode=0o777, exist_ok=True)
    pip_args = args or []
    pip_args = prepare_pip_source_args(sources, pip_args)
    pip_options, _ = pip_command.parser.parse_args(pip_args)
    pip_options.cache_dir = CACHE_DIR
    return pip_options


def get_finder(sources=None, pip_command=None, pip_options=None):
    # type: (List[Dict[S, Union[S, bool]]], Optional[Command], Any) -> PackageFinder
    """Get a package finder for looking up candidates to install.

    :param sources: A list of pipfile-formatted sources, defaults to None
    :param sources: list[dict], optional
    :param pip_command: A pip command instance, defaults to None
    :type pip_command: :class:`~pipenv.patched.pip._internal.cli.base_command.Command`
    :param pip_options: A pip options, defaults to None
    :type pip_options: :class:`~pipenv.patched.pip._internal.cli.cmdoptions`
    :return: A package finder
    :rtype: :class:`~pipenv.patched.pip._internal.index.PackageFinder`
    """

    if not pip_command:
        pip_command = get_pip_command()
    if not sources:
        sources = [{"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}]
    if not pip_options:
        pip_options = get_pip_options(sources=sources, pip_command=pip_command)
    session = pip_command._build_session(pip_options)
    atexit.register(session.close)
    finder = get_package_finder(get_pip_command(), options=pip_options, session=session)
    return session, finder


@contextlib.contextmanager
def start_resolver(finder=None, session=None, wheel_cache=None):
    """Context manager to produce a resolver.

    :param finder: A package finder to use for searching the index
    :type finder: :class:`~pipenv.patched.pip._internal.index.PackageFinder`
    :param :class:`~requests.Session` session: A session instance
    :param :class:`~pipenv.patched.pip._internal.cache.WheelCache` wheel_cache: A pip WheelCache instance
    :return: A 3-tuple of finder, preparer, resolver
    :rtype: (:class:`~pipenv.patched.pip._internal.operations.prepare.RequirementPreparer`,
             :class:`~pipenv.patched.pip._internal.resolve.Resolver`)
    """

    pip_command = get_pip_command()
    pip_options = get_pip_options(pip_command=pip_command)
    session = None
    if not finder:
        session, finder = get_finder(pip_command=pip_command, pip_options=pip_options)
    if not session:
        session = pip_command._build_session(pip_options)

    download_dir = PKGS_DOWNLOAD_DIR
    os.makedir(download_dir, mode=0o777)

    _build_dir = create_tracked_tempdir("build")
    _source_dir = create_tracked_tempdir("source")
    pip_options.src_dir = _source_dir
    try:
        with global_tempdir_manager(), get_build_tracker() as build_tracker:
            if not wheel_cache:
                wheel_cache = _get_wheel_cache()
            os.makdirs(os.path.join(wheel_cache.cache_dir, "wheels"))
            preparer = pip_command.make_requirement_preparer(
                temp_build_dir=_build_dir,
                options=pip_options,
                build_tracker=build_tracker,
                session=session,
                finder=finder,
                use_user_site=False,
            )
            resolver = pip_command.make_resolver(
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
    finally:
        session.close()


def get_grouped_dependencies(constraints):
    # We need to track what contributed a specifierset
    # as well as which specifiers were required by the root node
    # in order to resolve any conflicts when we are deciding which thing to backtrack on
    # then we take the loose match (which _is_ flexible) and start moving backwards in
    # versions by popping them off of a stack and checking for the conflicting package
    for _, ireqs in full_groupby(constraints, key=key_from_ireq):
        ireqs = sorted(ireqs, key=lambda ireq: ireq.editable)
        editable_ireq = next(iter(ireq for ireq in ireqs if ireq.editable), None)
        if editable_ireq:
            yield editable_ireq  # only the editable match mattters, ignore all others
            continue
        ireqs = iter(ireqs)
        # deepcopy the accumulator so as to not modify the self.our_constraints invariant
        combined_ireq = copy.deepcopy(next(ireqs))
        for ireq in ireqs:
            # NOTE we may be losing some info on dropped reqs here
            try:
                combined_ireq.req.specifier &= ireq.req.specifier
            except TypeError:
                if ireq.req.specifier._specs and not combined_ireq.req.specifier._specs:
                    combined_ireq.req.specifier._specs = ireq.req.specifier._specs
            combined_ireq.constraint &= ireq.constraint
            if not combined_ireq.markers:
                combined_ireq.markers = ireq.markers
            else:
                _markers = combined_ireq.markers._markers
                if not isinstance(_markers[0], (tuple, list)):
                    combined_ireq.markers._markers = [
                        _markers,
                        "and",
                        ireq.markers._markers,
                    ]
            # Return a sorted, de-duped tuple of extras
            combined_ireq.extras = tuple(
                sorted(set(tuple(combined_ireq.extras) + tuple(ireq.extras)))
            )
        yield combined_ireq
