# -*- coding=utf-8 -*-
from contextlib import contextmanager

import attr
import six

from pip_shims.shims import Wheel

from .cache import HashCache
from .utils import format_requirement, is_pinned_requirement, version_from_ireq


class ResolutionError(Exception):
    pass


@attr.s
class DependencyResolver(object):
    pinned_deps = attr.ib(default=attr.Factory(dict))
    #: A dictionary of abstract dependencies by name
    dep_dict = attr.ib(default=attr.Factory(dict))
    #: A dictionary of sets of version numbers that are valid for a candidate currently
    candidate_dict = attr.ib(default=attr.Factory(dict))
    #: A historical record of pins
    pin_history = attr.ib(default=attr.Factory(dict))
    #: Whether to allow prerelease dependencies
    allow_prereleases = attr.ib(default=False)
    #: Stores hashes for each dependency
    hashes = attr.ib(default=attr.Factory(dict))
    #: A hash cache
    hash_cache = attr.ib(default=attr.Factory(HashCache))
    #: A finder for searching the index
    finder = attr.ib(default=None)
    #: Whether to include hashes even from incompatible wheels
    include_incompatible_hashes = attr.ib(default=True)
    #: A cache for storing available canddiates when using all wheels
    _available_candidates_cache = attr.ib(default=attr.Factory(dict))

    @classmethod
    def create(cls, finder=None, allow_prereleases=False, get_all_hashes=True):
        if not finder:
            from .dependencies import get_finder
            finder_args = []
            if allow_prereleases:
                finder_args.append('--pre')
            finder = get_finder(*finder_args)
        creation_kwargs = {
            'allow_prereleases': allow_prereleases,
            'include_incompatible_hashes': get_all_hashes,
            'finder': finder,
            'hash_cache': HashCache(),
        }
        resolver = cls(**creation_kwargs)
        return resolver

    @property
    def dependencies(self):
        return list(self.dep_dict.values())

    @property
    def resolution(self):
        return list(self.pinned_deps.values())

    def add_abstract_dep(self, dep):
        """Add an abstract dependency by either creating a new entry or
        merging with an old one.

        :param dep: An abstract dependency to add
        :type dep: :class:`~requirementslib.models.dependency.AbstractDependency`
        :raises ResolutionError: Raised when the given dependency is not compatible with
                                 an existing abstract dependency.
        """

        if dep.name in self.dep_dict:
            compatible_versions = self.dep_dict[dep.name].compatible_versions(dep)
            if compatible_versions:
                self.candidate_dict[dep.name] = compatible_versions
                self.dep_dict[dep.name] = self.dep_dict[
                    dep.name
                ].compatible_abstract_dep(dep)
            else:
                raise ResolutionError
        else:
            self.candidate_dict[dep.name] = dep.version_set
            self.dep_dict[dep.name] = dep

    def pin_deps(self):
        """Pins the current abstract dependencies and adds them to the history dict.

        Adds any new dependencies to the abstract dependencies already present by
        merging them together to form new, compatible abstract dependencies.
        """

        for name in list(self.dep_dict.keys()):
            candidates = self.dep_dict[name].candidates[:]
            abs_dep = self.dep_dict[name]
            while candidates:
                pin = candidates.pop()
                # Move on from existing pins if the new pin isn't compatible
                if name in self.pinned_deps:
                    if self.pinned_deps[name].editable:
                        continue
                    old_version = version_from_ireq(self.pinned_deps[name])
                    if not pin.editable:
                        new_version = version_from_ireq(pin)
                        if (new_version != old_version and
                                new_version not in self.candidate_dict[name]):
                            continue
                pin.parent = abs_dep.parent
                pin_subdeps = self.dep_dict[name].get_deps(pin)
                backup = self.dep_dict.copy(), self.candidate_dict.copy()
                try:
                    for pin_dep in pin_subdeps:
                        self.add_abstract_dep(pin_dep)
                except ResolutionError:
                    self.dep_dict, self.candidate_dict = backup
                    continue
                else:
                    self.pinned_deps[name] = pin
                    break

    def resolve(self, root_nodes, max_rounds=20):
        """Resolves dependencies using a backtracking resolver and multiple endpoints.

        Note: this resolver caches aggressively.
        Runs for *max_rounds* or until any two pinning rounds yield the same outcome.

        :param root_nodes: A list of the root requirements.
        :type root_nodes: list[:class:`~requirementslib.models.requirements.Requirement`]
        :param max_rounds: The max number of resolution rounds, defaults to 20
        :param max_rounds: int, optional
        :raises RuntimeError: Raised when max rounds is exceeded without a resolution.
        """
        if self.dep_dict:
            raise RuntimeError("Do not use the same resolver more than once")

        if not self.hash_cache:
            self.hash_cache = HashCache()

        # Coerce input into AbstractDependency instances.
        # We accept str, Requirement, and AbstractDependency as input.
        from .dependencies import AbstractDependency
        from ..utils import log
        for dep in root_nodes:
            if isinstance(dep, six.string_types):
                dep = AbstractDependency.from_string(dep)
            elif not isinstance(dep, AbstractDependency):
                dep = AbstractDependency.from_requirement(dep)
            self.add_abstract_dep(dep)

        for round_ in range(max_rounds):
            self.pin_deps()
            self.pin_history[round_] = self.pinned_deps.copy()

            if round_ > 0:
                previous_round = set(self.pin_history[round_ - 1].values())
                current_values = set(self.pin_history[round_].values())
                difference = current_values - previous_round
            else:
                difference = set(self.pin_history[round_].values())

            log.debug("\n")
            log.debug("{:=^30}".format(" Round {0} ".format(round_)))
            log.debug("\n")
            if difference:
                log.debug("New Packages: ")
                for d in difference:
                    log.debug("{:>30}".format(format_requirement(d)))
            elif round_ >= 3:
                log.debug("Stable Pins: ")
                for d in current_values:
                    log.debug("{:>30}".format(format_requirement(d)))
                return
            else:
                log.debug("No New Packages.")
        # TODO: Raise a better error.
        raise RuntimeError("cannot resolve after {} rounds".format(max_rounds))

    def get_hashes(self):
        for dep in self.pinned_deps.values():
            if dep.name not in self.hashes:
                self.hashes[dep.name] = self.get_hashes_for_one(dep)
        return self.hashes.copy()

    def get_hashes_for_one(self, ireq):
        if not self.finder:
            from .dependencies import get_finder
            finder_args = []
            if self.allow_prereleases:
                finder_args.append('--pre')
            self.finder = get_finder(*finder_args)

        if ireq.editable:
            return set()

        from pip_shims import VcsSupport
        vcs = VcsSupport()
        if ireq.link and ireq.link.scheme in vcs.all_schemes and 'ssh' in ireq.link.scheme:
            return set()

        if not is_pinned_requirement(ireq):
            raise TypeError(
                "Expected pinned requirement, got {}".format(ireq))

        matching_candidates = set()
        with self.allow_all_wheels():
            from .dependencies import find_all_matches
            matching_candidates = (
                find_all_matches(self.finder, ireq, pre=self.allow_prereleases)
            )

        return {
            self.hash_cache.get_hash(candidate.location)
            for candidate in matching_candidates
        }

    @contextmanager
    def allow_all_wheels(self):
        """
        Monkey patches pip.Wheel to allow wheels from all platforms and Python versions.

        This also saves the candidate cache and set a new one, or else the results from the
        previous non-patched calls will interfere.
        """
        def _wheel_supported(self, tags=None):
            # Ignore current platform. Support everything.
            return True

        def _wheel_support_index_min(self, tags=None):
            # All wheels are equal priority for sorting.
            return 0

        original_wheel_supported = Wheel.supported
        original_support_index_min = Wheel.support_index_min

        Wheel.supported = _wheel_supported
        Wheel.support_index_min = _wheel_support_index_min

        try:
            yield
        finally:
            Wheel.supported = original_wheel_supported
            Wheel.support_index_min = original_support_index_min
