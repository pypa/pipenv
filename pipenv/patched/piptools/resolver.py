# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import copy
from functools import partial
from itertools import chain, count
import os

from ._compat import install_req_from_line

from . import click
from .cache import DependencyCache
from .exceptions import UnsupportedConstraint
from .logging import log
from .utils import (format_requirement, format_specifier, full_groupby, dedup, simplify_markers,
                    is_pinned_requirement, key_from_ireq, key_from_req, UNSAFE_PACKAGES)

green = partial(click.style, fg='green')
magenta = partial(click.style, fg='magenta')


class RequirementSummary(object):
    """
    Summary of a requirement's properties for comparison purposes.
    """
    def __init__(self, ireq):
        self.req = ireq.req
        self.key = key_from_req(ireq.req)
        self.markers = ireq.markers
        self.extras = str(sorted(ireq.extras))
        self.specifier = str(ireq.specifier)

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __str__(self):
        return repr([self.key, self.specifier, self.extras])


class Resolver(object):
    def __init__(self, constraints, repository, cache=None, prereleases=False, clear_caches=False, allow_unsafe=False):
        """
        This class resolves a given set of constraints (a collection of
        InstallRequirement objects) by consulting the given Repository and the
        DependencyCache.
        """
        self.our_constraints = set(constraints)
        self.their_constraints = set()
        self.repository = repository
        if cache is None:
            cache = DependencyCache()  # pragma: no cover
        self.dependency_cache = cache
        self.prereleases = prereleases
        self.clear_caches = clear_caches
        self.allow_unsafe = allow_unsafe
        self.unsafe_constraints = set()

    @property
    def constraints(self):
        return set(self._group_constraints(chain(self.our_constraints,
                                                 self.their_constraints)))

    def resolve_hashes(self, ireqs):
        """
        Finds acceptable hashes for all of the given InstallRequirements.
        """
        with self.repository.allow_all_wheels():
            return {ireq: self.repository.get_hashes(ireq) for ireq in ireqs}

    def resolve(self, max_rounds=10):
        """
        Finds concrete package versions for all the given InstallRequirements
        and their recursive dependencies.  The end result is a flat list of
        (name, version) tuples.  (Or an editable package.)

        Resolves constraints one round at a time, until they don't change
        anymore.  Protects against infinite loops by breaking out after a max
        number rounds.
        """
        if self.clear_caches:
            self.dependency_cache.clear()
            self.repository.clear_caches()

        self.check_constraints(chain(self.our_constraints,
                                     self.their_constraints))

        # Ignore existing packages
        os.environ[str('PIP_EXISTS_ACTION')] = str('i')  # NOTE: str() wrapping necessary for Python 2/3 compat
        for current_round in count(start=1):
            if current_round > max_rounds:
                raise RuntimeError('No stable configuration of concrete packages '
                                   'could be found for the given constraints after '
                                   '%d rounds of resolving.\n'
                                   'This is likely a bug.' % max_rounds)

            log.debug('')
            log.debug(magenta('{:^60}'.format('ROUND {}'.format(current_round))))
            has_changed, best_matches = self._resolve_one_round()
            log.debug('-' * 60)
            log.debug('Result of round {}: {}'.format(current_round,
                                                      'not stable' if has_changed else 'stable, done'))
            if not has_changed:
                break

            # If a package version (foo==2.0) was built in a previous round,
            # and in this round a different version of foo needs to be built
            # (i.e. foo==1.0), the directory will exist already, which will
            # cause a pip build failure.  The trick is to start with a new
            # build cache dir for every round, so this can never happen.
            self.repository.freshen_build_caches()

        del os.environ['PIP_EXISTS_ACTION']
        # Only include hard requirements and not pip constraints
        return {req for req in best_matches if not req.constraint}

    @staticmethod
    def check_constraints(constraints):
        for constraint in constraints:
            if constraint.link is not None and not constraint.editable and not constraint.is_wheel:
                msg = ('pip-compile does not support URLs as packages, unless they are editable. '
                       'Perhaps add -e option?')
                raise UnsupportedConstraint(msg, constraint)

    def _group_constraints(self, constraints):
        """
        Groups constraints (remember, InstallRequirements!) by their key name,
        and combining their SpecifierSets into a single InstallRequirement per
        package.  For example, given the following constraints:

            Django<1.9,>=1.4.2
            django~=1.5
            Flask~=0.7

        This will be combined into a single entry per package:

            django~=1.5,<1.9,>=1.4.2
            flask~=0.7

        """
        for _, ireqs in full_groupby(constraints, key=key_from_ireq):
            ireqs = list(ireqs)
            editable_ireq = next((ireq for ireq in ireqs if ireq.editable), None)
            if editable_ireq:
                yield editable_ireq  # ignore all the other specs: the editable one is the one that counts
                continue

            ireqs = iter(ireqs)
            # deepcopy the accumulator so as to not modify the self.our_constraints invariant
            combined_ireq = copy.deepcopy(next(ireqs))
            combined_ireq.comes_from = None
            for ireq in ireqs:
                # NOTE we may be losing some info on dropped reqs here
                combined_ireq.req.specifier &= ireq.req.specifier
                combined_ireq.constraint &= ireq.constraint
                if not combined_ireq.markers:
                    combined_ireq.markers = ireq.markers
                else:
                    _markers = combined_ireq.markers._markers
                    if not isinstance(_markers[0], (tuple, list)):
                        combined_ireq.markers._markers = [_markers, 'and', ireq.markers._markers]

                # Return a sorted, de-duped tuple of extras
                combined_ireq.extras = tuple(sorted(set(tuple(combined_ireq.extras) + tuple(ireq.extras))))
            yield combined_ireq

    def _resolve_one_round(self):
        """
        Resolves one level of the current constraints, by finding the best
        match for each package in the repository and adding all requirements
        for those best package versions.  Some of these constraints may be new
        or updated.

        Returns whether new constraints appeared in this round.  If no
        constraints were added or changed, this indicates a stable
        configuration.
        """
        # Sort this list for readability of terminal output
        constraints = sorted(self.constraints, key=key_from_ireq)
        unsafe_constraints = []
        original_constraints = copy.copy(constraints)
        if not self.allow_unsafe:
            for constraint in original_constraints:
                if constraint.name in UNSAFE_PACKAGES:
                    constraints.remove(constraint)
                    constraint.req.specifier = None
                    unsafe_constraints.append(constraint)

        log.debug('Current constraints:')
        for constraint in constraints:
            log.debug('  {}'.format(constraint))

        log.debug('')
        log.debug('Finding the best candidates:')
        best_matches = {self.get_best_match(ireq) for ireq in constraints}

        # Find the new set of secondary dependencies
        log.debug('')
        log.debug('Finding secondary dependencies:')

        safe_constraints = []
        for best_match in best_matches:
            for dep in self._iter_dependencies(best_match):
                if self.allow_unsafe or dep.name not in UNSAFE_PACKAGES:
                    safe_constraints.append(dep)
        # Grouping constraints to make clean diff between rounds
        theirs = set(self._group_constraints(safe_constraints))

        # NOTE: We need to compare RequirementSummary objects, since
        # InstallRequirement does not define equality
        diff = {RequirementSummary(t) for t in theirs} - {RequirementSummary(t) for t in self.their_constraints}
        removed = ({RequirementSummary(t) for t in self.their_constraints} -
                   {RequirementSummary(t) for t in theirs})
        unsafe = ({RequirementSummary(t) for t in unsafe_constraints} -
                  {RequirementSummary(t) for t in self.unsafe_constraints})

        has_changed = len(diff) > 0 or len(removed) > 0 or len(unsafe) > 0
        if has_changed:
            log.debug('')
            log.debug('New dependencies found in this round:')
            for new_dependency in sorted(diff, key=lambda req: key_from_req(req.req)):
                log.debug('  adding {}'.format(new_dependency))
            log.debug('Removed dependencies in this round:')
            for removed_dependency in sorted(removed, key=lambda req: key_from_req(req.req)):
                log.debug('  removing {}'.format(removed_dependency))
            log.debug('Unsafe dependencies in this round:')
            for unsafe_dependency in sorted(unsafe, key=lambda req: key_from_req(req.req)):
                log.debug('  remembering unsafe {}'.format(unsafe_dependency))

        # Store the last round's results in the their_constraints
        self.their_constraints = theirs
        # Store the last round's unsafe constraints
        self.unsafe_constraints = unsafe_constraints
        return has_changed, best_matches

    def get_best_match(self, ireq):
        """
        Returns a (pinned or editable) InstallRequirement, indicating the best
        match to use for the given InstallRequirement (in the form of an
        InstallRequirement).

        Example:
        Given the constraint Flask>=0.10, may return Flask==0.10.1 at
        a certain moment in time.

        Pinned requirements will always return themselves, i.e.

            Flask==0.10.1 => Flask==0.10.1

        """
        if ireq.editable:
            # NOTE: it's much quicker to immediately return instead of
            # hitting the index server
            best_match = ireq
        elif is_pinned_requirement(ireq):
            # NOTE: it's much quicker to immediately return instead of
            # hitting the index server
            best_match = ireq
        else:
            best_match = self.repository.find_best_match(ireq, prereleases=self.prereleases)

        # Format the best match
        log.debug('  found candidate {} (constraint was {})'.format(format_requirement(best_match),
                                                                    format_specifier(ireq)))
        return best_match

    def _iter_dependencies(self, ireq):
        """
        Given a pinned or editable InstallRequirement, collects all the
        secondary dependencies for them, either by looking them up in a local
        cache, or by reaching out to the repository.

        Editable requirements will never be looked up, as they may have
        changed at any time.
        """
        if ireq.editable:
            for dependency in self.repository.get_dependencies(ireq):
                yield dependency
            return

        # fix our malformed extras
        if ireq.extras:
            if getattr(ireq, "extra", None):
                if ireq.extras:
                    ireq.extras.extend(ireq.extra)
                else:
                    ireq.extras = ireq.extra

        elif not is_pinned_requirement(ireq):
            raise TypeError('Expected pinned or editable requirement, got {}'.format(ireq))

        # Now, either get the dependencies from the dependency cache (for
        # speed), or reach out to the external repository to
        # download and inspect the package version and get dependencies
        # from there
        if ireq not in self.dependency_cache:
            log.debug('  {} not in cache, need to check index'.format(format_requirement(ireq)), fg='yellow')
            dependencies = self.repository.get_dependencies(ireq)
            self.dependency_cache[ireq] = sorted(set(format_requirement(ireq) for ireq in dependencies))

        # Example: ['Werkzeug>=0.9', 'Jinja2>=2.4']
        dependency_strings = self.dependency_cache[ireq]
        log.debug('  {:25} requires {}'.format(format_requirement(ireq),
                                               ', '.join(sorted(dependency_strings, key=lambda s: s.lower())) or '-'))
        for dependency_string in dependency_strings:
            yield install_req_from_line(dependency_string, constraint=ireq.constraint)

    def reverse_dependencies(self, ireqs):
        non_editable = [ireq for ireq in ireqs if not ireq.editable]
        return self.dependency_cache.reverse_dependencies(non_editable)
