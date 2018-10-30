# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import os

import resolvelib

from ..internals.candidates import find_candidates
from ..internals.dependencies import get_dependencies
from ..internals.utils import (
    filter_sources, get_allow_prereleases, identify_requirment, strip_extras,
)


PROTECTED_PACKAGE_NAMES = {"pip", "setuptools"}


class BasicProvider(resolvelib.AbstractProvider):
    """Provider implementation to interface with `requirementslib.Requirement`.
    """
    def __init__(self, root_requirements, sources,
                 requires_python, allow_prereleases):
        self.sources = sources
        self.requires_python = requires_python
        self.allow_prereleases = bool(allow_prereleases)
        self.invalid_candidates = set()

        # Remember requirements of each pinned candidate. The resolver calls
        # `get_dependencies()` only when it wants to repin, so the last time
        # the dependencies we got when it is last called on a package, are
        # the set used by the resolver. We use this later to trace how a given
        # dependency is specified by a package.
        self.fetched_dependencies = {None: {
            self.identify(r): r for r in root_requirements
        }}

        # Should Pipfile's requires.python_[full_]version be included?
        self.collected_requires_pythons = {None: ""}

    def identify(self, dependency):
        return identify_requirment(dependency)

    def get_preference(self, resolution, candidates, information):
        # TODO: Provide better sorting logic. This simply resolve the ones with
        # less choices first. Not sophisticated, but sounds reasonable?
        return len(candidates)

    def find_matches(self, requirement):
        sources = filter_sources(requirement, self.sources)
        candidates = find_candidates(
            requirement, sources, self.requires_python,
            get_allow_prereleases(requirement, self.allow_prereleases),
        )
        return candidates

    def is_satisfied_by(self, requirement, candidate):
        # A non-named requirement has exactly one candidate, as implemented in
        # `find_matches()`. Since pip does not yet implement URL based lookup
        # (PEP 508) yet, it must match unless there are duplicated entries in
        # Pipfile. If there is, the user takes the blame. (sarugaku/passa#34)
        if not requirement.is_named:
            return True

        # A non-named candidate can only come from a non-named requirement,
        # which, since pip does not implement URL based lookup (PEP 508) yet,
        # can only come from Pipfile. Assume the user knows what they're doing,
        # and use it without checking. (sarugaku/passa#34)
        if not candidate.is_named:
            return True

        # Optimization: Everything matches if there are no specifiers.
        if not requirement.specifiers:
            return True

        # We can't handle old version strings before PEP 440. Drop them all.
        # Practically this shouldn't be a problem if the user is specifying a
        # remotely reasonable dependency not from before 2013.
        candidate_line = candidate.as_line(include_hashes=False)
        if candidate_line in self.invalid_candidates:
            return False
        try:
            version = candidate.get_specifier().version
        except (TypeError, ValueError):
            print('ignoring invalid version from {!r}'.format(candidate_line))
            self.invalid_candidates.add(candidate_line)
            return False

        return requirement.as_ireq().specifier.contains(version)

    def get_dependencies(self, candidate):
        sources = filter_sources(candidate, self.sources)
        try:
            dependencies, requires_python = get_dependencies(
                candidate, sources=sources,
            )
        except Exception as e:
            if os.environ.get("PASSA_NO_SUPPRESS_EXCEPTIONS"):
                raise
            print("failed to get dependencies for {0!r}: {1}".format(
                candidate.as_line(include_hashes=False), e,
            ))
            dependencies = []
            requires_python = ""
        # Exclude protected packages from the list. This prevents those
        # packages from being locked, unless the user is actually working on
        # them, and explicitly lists them as top-level requirements -- those
        # packages are not added via this code path. (sarugaku/passa#15)
        dependencies = [
            dependency for dependency in dependencies
            if dependency.normalized_name not in PROTECTED_PACKAGE_NAMES
        ]
        if candidate.extras:
            # HACK: If this candidate has extras, add the original candidate
            # (same pinned version, no extras) as its dependency. This ensures
            # the same package with different extras (treated as distinct by
            # the resolver) have the same version. (sarugaku/passa#4)
            dependencies.append(strip_extras(candidate))
        candidate_key = self.identify(candidate)
        self.fetched_dependencies[candidate_key] = {
            self.identify(r): r for r in dependencies
        }
        self.collected_requires_pythons[candidate_key] = requires_python
        return dependencies


class PinReuseProvider(BasicProvider):
    """A provider that reuses preferred pins if possible.

    This is used to implement "add", "remove", and "only-if-needed upgrade",
    where already-pinned candidates in Pipfile.lock should be preferred.
    """
    def __init__(self, preferred_pins, *args, **kwargs):
        super(PinReuseProvider, self).__init__(*args, **kwargs)
        self.preferred_pins = preferred_pins

    def find_matches(self, requirement):
        candidates = super(PinReuseProvider, self).find_matches(requirement)
        try:
            # Add the preferred pin. Remember the resolve prefer candidates
            # at the end of the list, so the most preferred should be last.
            candidates.append(self.preferred_pins[self.identify(requirement)])
        except KeyError:
            pass
        return candidates


class EagerUpgradeProvider(PinReuseProvider):
    """A specialized provider to handle an "eager" upgrade strategy.

    An eager upgrade tries to upgrade not only packages specified, but also
    their dependencies (recursively). This contrasts to the "only-if-needed"
    default, which only promises to upgrade the specified package, and
    prevents touching anything else if at all possible.

    The provider is implemented as to keep track of all dependencies of the
    specified packages to upgrade, and free their pins when it has a chance.
    """
    def __init__(self, tracked_names, *args, **kwargs):
        super(EagerUpgradeProvider, self).__init__(*args, **kwargs)
        self.tracked_names = set(tracked_names)
        for name in tracked_names:
            self.preferred_pins.pop(name, None)

        # HACK: Set this special flag to distinguish preferred pins from
        # regular, to tell the resolver to NOT use them for tracked packages.
        for pin in self.preferred_pins.values():
            pin._preferred_by_provider = True

    def is_satisfied_by(self, requirement, candidate):
        # If this is a tracking package, tell the resolver out of using the
        # preferred pin, and into a "normal" candidate selection process.
        if (self.identify(requirement) in self.tracked_names and
                getattr(candidate, "_preferred_by_provider", False)):
            return False
        return super(EagerUpgradeProvider, self).is_satisfied_by(
            requirement, candidate,
        )

    def get_dependencies(self, candidate):
        # If this package is being tracked for upgrade, remove pins of its
        # dependencies, and start tracking these new packages.
        dependencies = super(EagerUpgradeProvider, self).get_dependencies(
            candidate,
        )
        if self.identify(candidate) in self.tracked_names:
            for dependency in dependencies:
                name = self.identify(dependency)
                self.tracked_names.add(name)
                self.preferred_pins.pop(name, None)
        return dependencies

    def get_preference(self, resolution, candidates, information):
        # Resolve tracking packages so we have a chance to unpin them first.
        name = self.identify(candidates[0])
        if name in self.tracked_names:
            return -1
        return len(candidates)
