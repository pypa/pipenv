# -*- coding=utf-8 -*-

import atexit
import contextlib
import copy
import functools
import os
from contextlib import ExitStack
from json import JSONDecodeError

import pipenv.vendor.attr as attr
import packaging.markers
import packaging.version
import pip_shims.shims
import pipenv.vendor.requests as requests
from pipenv.vendor.packaging.utils import canonicalize_name
from pipenv.vendor.vistir.compat import fs_str
from pipenv.vendor.vistir.contextmanagers import cd, temp_environ
from pipenv.vendor.vistir.path import create_tracked_tempdir

from ..environment import MYPY_RUNNING
from ..utils import _ensure_dir, prepare_pip_source_args
from .cache import CACHE_DIR, DependencyCache
from .setup_info import SetupInfo
from .utils import (
    clean_requires_python,
    fix_requires_python_marker,
    format_requirement,
    full_groupby,
    is_pinned_requirement,
    key_from_ireq,
    make_install_requirement,
    name_from_req,
    version_from_ireq,
)

if MYPY_RUNNING:
    from typing import (
        Any,
        Dict,
        Generator,
        List,
        Optional,
        Set,
        Text,
        Tuple,
        TypeVar,
        Union,
    )

    from pipenv.vendor.packaging.markers import Marker
    from pipenv.vendor.packaging.requirements import Requirement as PackagingRequirement
    from pipenv.vendor.pip_shims.shims import (
        Command,
        InstallationCandidate,
        InstallRequirement,
        PackageFinder,
    )

    TRequirement = TypeVar("TRequirement")
    RequirementType = TypeVar(
        "RequirementType", covariant=True, bound=PackagingRequirement
    )
    MarkerType = TypeVar("MarkerType", covariant=True, bound=Marker)
    STRING_TYPE = Union[str, bytes, Text]
    S = TypeVar("S", bytes, str, Text)


PKGS_DOWNLOAD_DIR = fs_str(os.path.join(CACHE_DIR, "pkgs"))
WHEEL_DOWNLOAD_DIR = fs_str(os.path.join(CACHE_DIR, "wheels"))

DEPENDENCY_CACHE = DependencyCache()


@contextlib.contextmanager
def _get_wheel_cache():
    with pip_shims.shims.global_tempdir_manager():
        yield pip_shims.shims.WheelCache(
            CACHE_DIR, pip_shims.shims.FormatControl(set(), set())
        )


def _get_filtered_versions(ireq, versions, prereleases):
    return set(ireq.specifier.filter(versions, prereleases=prereleases))


def find_all_matches(finder, ireq, pre=False):
    # type: (PackageFinder, InstallRequirement, bool) -> List[InstallationCandidate]
    """Find all matching dependencies using the supplied finder and the given
    ireq.

    :param finder: A package finder for discovering matching candidates.
    :type finder: :class:`~pipenv.patched.notpip._internal.index.PackageFinder`
    :param ireq: An install requirement.
    :type ireq: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
    :return: A list of matching candidates.
    :rtype: list[:class:`~pipenv.patched.notpip._internal.index.InstallationCandidate`]
    """

    candidates = clean_requires_python(finder.find_all_candidates(ireq.name))
    versions = {candidate.version for candidate in candidates}
    allowed_versions = _get_filtered_versions(ireq, versions, pre)
    if not pre and not allowed_versions:
        allowed_versions = _get_filtered_versions(ireq, versions, True)
    candidates = {c for c in candidates if c.version in allowed_versions}
    return candidates


def get_pip_command():
    # type: () -> Command
    # Use pip's parser for pip.conf management and defaults.
    # General options (find_links, index_url, extra_index_url, trusted_host,
    # and pre) are defered to pip.
    pip_command = pip_shims.shims.InstallCommand()
    return pip_command


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
        return set(packaging.version.parse(version_from_ireq(c)) for c in self.candidates)

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
            new_markers = packaging.markers.Marker(
                " or ".join(str(m) for m in sorted(markers))
            )
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
            if packaging.version.parse(version_from_ireq(c)) in compatible_versions
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
        :type candidate: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
        :return: A list of abstract dependencies
        :rtype: list[:class:`~requirementslib.models.dependency.AbstractDependency`]
        """

        key = format_requirement(candidate)
        if key not in self.dep_dict:
            from .requirements import Requirement

            req = Requirement.from_line(key)
            req = req.merge_markers(self.markers)
            self.dep_dict[key] = req.get_abstract_dependencies()
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
                    key=lambda k: packaging.version.parse(version_from_ireq(k)),
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


def get_abstract_dependencies(reqs, sources=None, parent=None):
    """Get all abstract dependencies for a given list of requirements.

    Given a set of requirements, convert each requirement to an Abstract Dependency.

    :param reqs: A list of Requirements
    :type reqs: list[:class:`~requirementslib.models.requirements.Requirement`]
    :param sources: Pipfile-formatted sources, defaults to None
    :param sources: list[dict], optional
    :param parent: The parent of this list of dependencies, defaults to None
    :param parent: :class:`~requirementslib.models.requirements.Requirement`, optional
    :return: A list of Abstract Dependencies
    :rtype: list[:class:`~requirementslib.models.dependency.AbstractDependency`]
    """

    deps = []
    from .requirements import Requirement

    for req in reqs:
        if isinstance(req, pip_shims.shims.InstallRequirement):
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
    :type ireq: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
    :param sources: Pipfile-formatted sources, defaults to None
    :type sources: list[dict], optional
    :param parent: The parent of this list of dependencies, defaults to None
    :type parent: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str)
    """
    if not isinstance(ireq, pip_shims.shims.InstallRequirement):
        name = getattr(ireq, "project_name", getattr(ireq, "project", ireq.name))
        version = getattr(ireq, "version", None)
        if not version:
            ireq = pip_shims.shims.InstallRequirement.from_line("{0}".format(name))
        else:
            ireq = pip_shims.shims.InstallRequirement.from_line(
                "{0}=={1}".format(name, version)
            )
    pip_options = get_pip_options(sources=sources)
    getters = [
        get_dependencies_from_cache,
        get_dependencies_from_wheel_cache,
        get_dependencies_from_json,
        functools.partial(get_dependencies_from_index, pip_options=pip_options),
    ]
    for getter in getters:
        deps = getter(ireq)
        if deps is not None:
            return deps
    raise RuntimeError("failed to get dependencies for {}".format(ireq))


def get_dependencies_from_wheel_cache(ireq):
    # type: (pip_shims.shims.InstallRequirement) -> Optional[Set[pip_shims.shims.InstallRequirement]]
    """Retrieves dependencies for the given install requirement from the wheel
    cache.

    :param ireq: A single InstallRequirement
    :type ireq: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str) or None
    """

    if ireq.editable or not is_pinned_requirement(ireq):
        return
    with _get_wheel_cache() as wheel_cache:
        matches = wheel_cache.get(ireq.link, name_from_req(ireq.req))
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
    :type ireq: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
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
            i = pip_shims.shims.InstallRequirement.from_line(requires)
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
    :type ireq: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
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
            dep_ireq = pip_shims.shims.InstallRequirement.from_line(line)
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


def get_dependencies_from_index(dep, sources=None, pip_options=None, wheel_cache=None):
    """Retrieves dependencies for the given install requirement from the pip
    resolver.

    :param dep: A single InstallRequirement
    :type dep: :class:`~pipenv.patched.notpip._internal.req.req_install.InstallRequirement`
    :param sources: Pipfile-formatted sources, defaults to None
    :type sources: list[dict], optional
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str) or None
    """

    session, finder = get_finder(sources=sources, pip_options=pip_options)
    dep.is_direct = True
    requirements = None
    setup_requires = {}
    with temp_environ(), ExitStack() as stack:
        if not wheel_cache:
            wheel_cache = stack.enter_context(_get_wheel_cache())
        os.environ["PIP_EXISTS_ACTION"] = "i"
        if dep.editable and not dep.prepared and not dep.req:
            setup_info = SetupInfo.from_ireq(dep)
            results = setup_info.get_info()
            setup_requires.update(results["setup_requires"])
            requirements = set(results["requires"].values())
        else:
            results = pip_shims.shims.resolve(dep)
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
    :type pip_command: :class:`~pipenv.patched.notpip._internal.cli.base_command.Command`
    :return: An instance of pip_options using the supplied arguments plus sane defaults
    :rtype: :class:`~pipenv.patched.notpip._internal.cli.cmdoptions`
    """

    if not pip_command:
        pip_command = get_pip_command()
    if not sources:
        sources = [{"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}]
    _ensure_dir(CACHE_DIR)
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
    :type pip_command: :class:`~pipenv.patched.notpip._internal.cli.base_command.Command`
    :param pip_options: A pip options, defaults to None
    :type pip_options: :class:`~pipenv.patched.notpip._internal.cli.cmdoptions`
    :return: A package finder
    :rtype: :class:`~pipenv.patched.notpip._internal.index.PackageFinder`
    """

    if not pip_command:
        pip_command = pip_shims.shims.InstallCommand()
    if not sources:
        sources = [{"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}]
    if not pip_options:
        pip_options = get_pip_options(sources=sources, pip_command=pip_command)
    session = pip_command._build_session(pip_options)
    atexit.register(session.close)
    finder = pip_shims.shims.get_package_finder(
        pip_shims.shims.InstallCommand(), options=pip_options, session=session
    )
    return session, finder


@contextlib.contextmanager
def start_resolver(finder=None, session=None, wheel_cache=None):
    """Context manager to produce a resolver.

    :param finder: A package finder to use for searching the index
    :type finder: :class:`~pipenv.patched.notpip._internal.index.PackageFinder`
    :param :class:`~requests.Session` session: A session instance
    :param :class:`~pipenv.patched.notpip._internal.cache.WheelCache` wheel_cache: A pip WheelCache instance
    :return: A 3-tuple of finder, preparer, resolver
    :rtype: (:class:`~pipenv.patched.notpip._internal.operations.prepare.RequirementPreparer`,
             :class:`~pipenv.patched.notpip._internal.resolve.Resolver`)
    """

    pip_command = get_pip_command()
    pip_options = get_pip_options(pip_command=pip_command)
    session = None
    if not finder:
        session, finder = get_finder(pip_command=pip_command, pip_options=pip_options)
    if not session:
        session = pip_command._build_session(pip_options)

    download_dir = PKGS_DOWNLOAD_DIR
    _ensure_dir(download_dir)

    _build_dir = create_tracked_tempdir(fs_str("build"))
    _source_dir = create_tracked_tempdir(fs_str("source"))
    try:
        with ExitStack() as ctx:
            ctx.enter_context(pip_shims.shims.global_tempdir_manager())
            if not wheel_cache:
                wheel_cache = ctx.enter_context(_get_wheel_cache())
            _ensure_dir(fs_str(os.path.join(wheel_cache.cache_dir, "wheels")))
            preparer = ctx.enter_context(
                pip_shims.shims.make_preparer(
                    options=pip_options,
                    finder=finder,
                    session=session,
                    build_dir=_build_dir,
                    src_dir=_source_dir,
                    download_dir=download_dir,
                    wheel_download_dir=WHEEL_DOWNLOAD_DIR,
                    progress_bar="off",
                    build_isolation=False,
                    install_cmd=pip_command,
                )
            )
            resolver = pip_shims.shims.get_resolver(
                finder=finder,
                ignore_dependencies=False,
                ignore_requires_python=True,
                preparer=preparer,
                session=session,
                options=pip_options,
                install_cmd=pip_command,
                wheel_cache=wheel_cache,
                force_reinstall=True,
                ignore_installed=True,
                upgrade_strategy="to-satisfy-only",
                isolated=False,
                use_user_site=False,
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
