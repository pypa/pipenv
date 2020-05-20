# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import os
from functools import partial
from itertools import chain, count

from pip_shims.shims import install_req_from_line
from pipenv.vendor.requirementslib.models.markers import normalize_marker_str
from packaging.markers import Marker

from . import click
from .logging import log
from .utils import (
    UNSAFE_PACKAGES,
    format_requirement,
    format_specifier,
    full_groupby,
    is_pinned_requirement,
    is_url_requirement,
    key_from_ireq,
)

green = partial(click.style, fg="green")
magenta = partial(click.style, fg="magenta")


class RequirementSummary(object):
    """
    Summary of a requirement's properties for comparison purposes.
    """

    def __init__(self, ireq):
        self.req = ireq.req
        self.key = key_from_ireq(ireq)
        self.extras = str(sorted(ireq.extras))
        self.markers = ireq.markers
        self.specifier = str(ireq.specifier)

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __str__(self):
        return repr([self.key, self.specifier, self.extras])


def combine_install_requirements(ireqs):
    """
    Return a single install requirement that reflects a combination of
    all the inputs.
    """
    # We will store the source ireqs in a _source_ireqs attribute;
    # if any of the inputs have this, then use those sources directly.
    source_ireqs = []
    for ireq in ireqs:
        source_ireqs.extend(getattr(ireq, "_source_ireqs", [ireq]))

    # deepcopy the accumulator so as to not modify the inputs
    combined_ireq = copy.deepcopy(source_ireqs[0])
    for ireq in source_ireqs[1:]:
        # NOTE we may be losing some info on dropped reqs here
        if combined_ireq.req is not None and ireq.req is not None:
            combined_ireq.req.specifier &= ireq.req.specifier
        combined_ireq.constraint &= ireq.constraint
        if ireq.markers and not combined_ireq.markers:
            combined_ireq.markers = copy.deepcopy(ireq.markers)
        elif ireq.markers and combined_ireq.markers:
            _markers = []  # type: List[Marker]
            for marker in [ireq.markers, combined_ireq.markers]:
                if isinstance(marker, str):
                    _markers.append(Marker(marker))
                else:
                    _markers.append(marker)
            marker_str = " and ".join([normalize_marker_str(m) for m in _markers if m])
            combined_ireq.markers = Marker(marker_str)
        # Return a sorted, de-duped tuple of extras
        combined_ireq.extras = tuple(
            sorted(set(tuple(combined_ireq.extras) + tuple(ireq.extras)))
        )

    # InstallRequirements objects are assumed to come from only one source, and
    # so they support only a single comes_from entry. This function breaks this
    # model. As a workaround, we deterministically choose a single source for
    # the comes_from entry, and add an extra _source_ireqs attribute to keep
    # track of multiple sources for use within pip-tools.
    if len(source_ireqs) > 1:
        if any(ireq.comes_from is None for ireq in source_ireqs):
            # None indicates package was directly specified.
            combined_ireq.comes_from = None
        else:
            # Populate the comes_from field from one of the sources.
            # Requirement input order is not stable, so we need to sort:
            # We choose the shortest entry in order to keep the printed
            # representation as concise as possible.
            combined_ireq.comes_from = min(
                (ireq.comes_from for ireq in source_ireqs),
                key=lambda x: (len(str(x)), str(x)),
            )
        combined_ireq._source_ireqs = source_ireqs
    return combined_ireq


class Resolver(object):
    def __init__(
        self,
        constraints,
        repository,
        cache,
        prereleases=False,
        clear_caches=False,
        allow_unsafe=False,
    ):
        """
        This class resolves a given set of constraints (a collection of
        InstallRequirement objects) by consulting the given Repository and the
        DependencyCache.
        """
        self.our_constraints = set(constraints)
        self.their_constraints = set()
        self.repository = repository
        self.dependency_cache = cache
        self.prereleases = prereleases
        self.clear_caches = clear_caches
        self.allow_unsafe = allow_unsafe
        self.unsafe_constraints = set()

    @property
    def constraints(self):
        return set(
            self._group_constraints(
                chain(
                    sorted(self.our_constraints, key=str),
                    sorted(self.their_constraints, key=str),
                )
            )
        )

    def resolve_hashes(self, ireqs):
        """
        Finds acceptable hashes for all of the given InstallRequirements.
        """
        log.debug("")
        log.debug("Generating hashes:")
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

        # Ignore existing packages
        os.environ[str("PIP_EXISTS_ACTION")] = str(
            "i"
        )  # NOTE: str() wrapping necessary for Python 2/3 compat
        for current_round in count(start=1):  # pragma: no branch
            if current_round > max_rounds:
                raise RuntimeError(
                    "No stable configuration of concrete packages "
                    "could be found for the given constraints after "
                    "{max_rounds} rounds of resolving.\n"
                    "This is likely a bug.".format(max_rounds=max_rounds)
                )

            log.debug("")
            log.debug(magenta("{:^60}".format("ROUND {}".format(current_round))))
            has_changed, best_matches = self._resolve_one_round()
            log.debug("-" * 60)
            log.debug(
                "Result of round {}: {}".format(
                    current_round, "not stable" if has_changed else "stable, done"
                )
            )
            if not has_changed:
                break

            # If a package version (foo==2.0) was built in a previous round,
            # and in this round a different version of foo needs to be built
            # (i.e. foo==1.0), the directory will exist already, which will
            # cause a pip build failure.  The trick is to start with a new
            # build cache dir for every round, so this can never happen.
            self.repository.freshen_build_caches()

        del os.environ["PIP_EXISTS_ACTION"]

        # Only include hard requirements and not pip constraints
        results = {req for req in best_matches if not req.constraint}

        # Filter out unsafe requirements.
        self.unsafe_constraints = set()
        if not self.allow_unsafe:
            # reverse_dependencies is used to filter out packages that are only
            # required by unsafe packages. This logic is incomplete, as it would
            # fail to filter sub-sub-dependencies of unsafe packages. None of the
            # UNSAFE_PACKAGES currently have any dependencies at all (which makes
            # sense for installation tools) so this seems sufficient.
            reverse_dependencies = self.reverse_dependencies(results)
            for req in results.copy():
                required_by = reverse_dependencies.get(req.name.lower(), [])
                if req.name in UNSAFE_PACKAGES or (
                    required_by and all(name in UNSAFE_PACKAGES for name in required_by)
                ):
                    self.unsafe_constraints.add(req)
                    results.remove(req)

        return results

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
            yield combine_install_requirements(ireqs)

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

        log.debug("Current constraints:")
        for constraint in constraints:
            log.debug("  {}".format(constraint))

        log.debug("")
        log.debug("Finding the best candidates:")
        best_matches = {self.get_best_match(ireq) for ireq in constraints}

        # Find the new set of secondary dependencies
        log.debug("")
        log.debug("Finding secondary dependencies:")

        their_constraints = []
        for best_match in best_matches:
            their_constraints.extend(self._iter_dependencies(best_match))
        # Grouping constraints to make clean diff between rounds
        theirs = set(self._group_constraints(sorted(their_constraints, key=str)))

        # NOTE: We need to compare RequirementSummary objects, since
        # InstallRequirement does not define equality
        diff = {RequirementSummary(t) for t in theirs} - {
            RequirementSummary(t) for t in self.their_constraints
        }
        removed = {RequirementSummary(t) for t in self.their_constraints} - {
            RequirementSummary(t) for t in theirs
        }

        has_changed = len(diff) > 0 or len(removed) > 0
        if has_changed:
            log.debug("")
            log.debug("New dependencies found in this round:")
            for new_dependency in sorted(diff, key=key_from_ireq):
                log.debug("  adding {}".format(new_dependency))
            log.debug("Removed dependencies in this round:")
            for removed_dependency in sorted(removed, key=key_from_ireq):
                log.debug("  removing {}".format(removed_dependency))

        # Store the last round's results in the their_constraints
        self.their_constraints = theirs
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
        if ireq.editable or is_url_requirement(ireq):
            # NOTE: it's much quicker to immediately return instead of
            # hitting the index server
            best_match = ireq
        elif is_pinned_requirement(ireq):
            # NOTE: it's much quicker to immediately return instead of
            # hitting the index server
            best_match = ireq
        else:
            best_match = self.repository.find_best_match(
                ireq, prereleases=self.prereleases
            )

        # Format the best match
        log.debug(
            "  found candidate {} (constraint was {})".format(
                format_requirement(best_match), format_specifier(ireq)
            )
        )
        best_match.comes_from = ireq.comes_from
        if hasattr(ireq, "_source_ireqs"):
            best_match._source_ireqs = ireq._source_ireqs
        return best_match

    def _iter_dependencies(self, ireq):
        """
        Given a pinned, url, or editable InstallRequirement, collects all the
        secondary dependencies for them, either by looking them up in a local
        cache, or by reaching out to the repository.

        Editable requirements will never be looked up, as they may have
        changed at any time.
        """
        # Pip does not resolve dependencies of constraints. We skip handling
        # constraints here as well to prevent the cache from being polluted.
        # Constraints that are later determined to be dependencies will be
        # marked as non-constraints in later rounds by
        # `combine_install_requirements`, and will be properly resolved.
        # See https://github.com/pypa/pip/
        # blob/6896dfcd831330c13e076a74624d95fa55ff53f4/src/pip/_internal/
        # legacy_resolve.py#L325
        if ireq.constraint:
            return

        if ireq.editable or (is_url_requirement(ireq) and not ireq.link.is_wheel):
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
            raise TypeError(
                "Expected pinned or editable requirement, got {}".format(ireq)
            )

        # Now, either get the dependencies from the dependency cache (for
        # speed), or reach out to the external repository to
        # download and inspect the package version and get dependencies
        # from there
        if ireq not in self.dependency_cache:
            log.debug(
                "  {} not in cache, need to check index".format(
                    format_requirement(ireq)
                ),
                fg="yellow",
            )
            dependencies = self.repository.get_dependencies(ireq)
            self.dependency_cache[ireq] = sorted(set(format_requirement(ireq) for ireq in dependencies))

        # Example: ['Werkzeug>=0.9', 'Jinja2>=2.4']
        dependency_strings = self.dependency_cache[ireq]
        log.debug(
            "  {:25} requires {}".format(
                format_requirement(ireq),
                ", ".join(sorted(dependency_strings, key=lambda s: s.lower())) or "-",
            )
        )
        for dependency_string in dependency_strings:
            yield install_req_from_line(
                dependency_string, constraint=ireq.constraint, comes_from=ireq
            )

    def reverse_dependencies(self, ireqs):
        is_non_wheel_url = lambda r: is_url_requirement(r) and not r.link.is_wheel
        non_editable = [
            ireq for ireq in ireqs if not (ireq.editable or is_non_wheel_url(ireq))
        ]
        return self.dependency_cache.reverse_dependencies(non_editable)
