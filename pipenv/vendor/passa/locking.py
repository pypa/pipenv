# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import itertools

from plette import Lockfile
from requirementslib import Requirement
from resolvelib import Resolver

from .caches import HashCache
from .hashes import get_hashes
from .metadata import set_metadata
from .providers import RequirementsLibProvider
from .reporters import StdOutReporter
from .traces import trace_graph
from .utils import identify_requirment


def resolve_requirements(requirements, sources, pins, allow_pre):
    """Lock specified (abstract) requirements into (concrete) candidates.

    The locking procedure consists of four stages:

    * Resolve versions and dependency graph (powered by ResolveLib).
    * Walk the graph to determine "why" each candidate came to be, i.e. what
      top-level requirements result in a given candidate.
    * Populate hashes for resolved candidates.
    * Populate markers based on dependency specifications of each candidate,
      and the dependency graph.
    """
    provider = RequirementsLibProvider(requirements, sources, pins, allow_pre)
    reporter = StdOutReporter(requirements)
    resolver = Resolver(provider, reporter)

    state = resolver.resolve(requirements)
    traces = trace_graph(state.graph)

    hash_cache = HashCache()
    for r in state.mapping.values():
        if not r.hashes:
            r.hashes = get_hashes(hash_cache, r)

    set_metadata(
        state.mapping, traces,
        provider.fetched_dependencies, provider.requires_pythons,
    )
    return state, traces


def _get_requirements(pipfile, section_name):
    """Produce a mapping of identifier: requirement from the section.
    """
    return {identify_requirment(r): r for r in (
        Requirement.from_pipfile(name, package._data)
        for name, package in pipfile.get(section_name, {}).items()
    )}


def _get_derived_entries(state, traces, names):
    """Produce a mapping containing all candidates derived from `names`.

    `name` should provide a collection of requirement identifications from
    a section (i.e. `packages` or `dev-packages`). This function uses `trace`
    to filter out candidates in the state that are present because of an entry
    in that collection.
    """
    if not names:
        return {}
    return_map = {}
    for req_name_from_state, req in state.mapping.items():
        req_traces = [trace[1] for trace in traces[req_name_from_state] if len(trace) > 1]
        if req_name_from_state in names or len(set(names) & set(req_traces)):
            return_map[req.normalized_name] = next(iter(req.as_pipfile().values()))
    return return_map


def build_lockfile(pipfile, lockfile):
    default_reqs = _get_requirements(pipfile, "packages")
    develop_reqs = _get_requirements(pipfile, "dev-packages")

    pins = {}
    if lockfile:
        pins = _get_requirements(lockfile, "develop")
        pins.update(_get_requirements(lockfile, "default"))

    # This comprehension dance ensures we merge packages from both
    # sections, and definitions in the default section win.
    requirements = {k: r for k, r in itertools.chain(
        develop_reqs.items(), default_reqs.items(),
    )}.values()

    sources = [s._data.copy() for s in pipfile.sources]
    try:
        allow_prereleases = bool(pipfile["pipenv"]["allow_prereleases"])
    except (KeyError, TypeError):
        allow_prereleases = False
    state, traces = resolve_requirements(
        requirements, sources, pins, allow_prereleases,
    )

    new_lock = Lockfile.with_meta_from(pipfile)
    new_lock["default"] = _get_derived_entries(state, traces, default_reqs)
    new_lock["develop"] = _get_derived_entries(state, traces, develop_reqs)
    return new_lock
