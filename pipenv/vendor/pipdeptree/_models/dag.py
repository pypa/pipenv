from __future__ import annotations

import sys
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping
from fnmatch import fnmatch
from itertools import chain
from typing import TYPE_CHECKING

from pipenv.vendor.packaging.utils import canonicalize_name

if TYPE_CHECKING:
    from importlib.metadata import Distribution


from pipenv.vendor.pipdeptree._warning import get_warning_printer

from .package import DistPackage, InvalidRequirementError, ReqPackage


class IncludeExcludeOverlapError(Exception):
    """Include and exclude sets passed as input violate mutual exclusivity requirement."""


class IncludePatternNotFoundError(Exception):
    """Include patterns weren't found when filtering a `PackageDAG`."""


class PackageDAG(Mapping[DistPackage, list[ReqPackage]]):
    """
    Representation of Package dependencies as directed acyclic graph using a dict as the underlying datastructure.

    The nodes and their relationships (edges) are internally stored using a map as follows,

    {a: [b, c],
     b: [d],
     c: [d, e],
     d: [e],
     e: [],
     f: [b],
     g: [e, f]}

    Here, node `a` has 2 children nodes `b` and `c`. Consider edge direction from `a` -> `b` and `a` -> `c`
    respectively.

    A node is expected to be an instance of a subclass of `Package`. The keys are must be of class `DistPackage` and
    each item in values must be of class `ReqPackage`. (See also ReversedPackageDAG where the key and value types are
    interchanged).

    """

    @classmethod
    def from_pkgs(
        cls,
        pkgs: list[Distribution],
        *,
        include_extras: bool = False,
    ) -> PackageDAG:
        warning_printer = get_warning_printer()
        dist_pkgs = [DistPackage(p) for p in pkgs]
        idx = {p.key: p for p in dist_pkgs}
        pkg_deps: dict[DistPackage, list[ReqPackage]] = {}
        dist_name_to_invalid_reqs_dict: dict[str, list[str]] = {}
        for pkg in dist_pkgs:
            reqs: list[ReqPackage] = []
            requires_iterator = pkg.requires()
            while True:
                try:
                    req = next(requires_iterator)
                except InvalidRequirementError as err:
                    if warning_printer.should_warn():
                        dist_name_to_invalid_reqs_dict.setdefault(pkg.project_name, []).append(str(err))
                    continue
                except StopIteration:
                    break
                dist = idx.get(canonicalize_name(req.name))
                # Distribution.requires only returns the name of requirements in the metadata file, which may not be the
                # same as the name in PyPI. We should try to retain the original package names for requirements.
                # See https://github.com/tox-dev/pipdeptree/issues/242
                req.name = dist.project_name if dist is not None else req.name
                reqs.append(ReqPackage(req, dist))
            pkg_deps[pkg] = reqs

        should_print_warning = warning_printer.should_warn() and dist_name_to_invalid_reqs_dict
        if should_print_warning:
            warning_printer.print_multi_line(
                "Invalid requirement strings found for the following distributions",
                lambda: render_invalid_reqs_text(dist_name_to_invalid_reqs_dict),
            )

        if include_extras:
            _resolve_extras(pkg_deps, idx)

        return cls(pkg_deps)

    def __init__(self, m: dict[DistPackage, list[ReqPackage]]) -> None:
        """
        Initialize the PackageDAG object.

        :param dict m: dict of node objects (refer class docstring)
        :returns: None
        :rtype: NoneType

        """
        self._obj: dict[DistPackage, list[ReqPackage]] = m
        self._index: dict[str, DistPackage] = {p.key: p for p in self._obj}

    def get_node_as_parent(self, node_key: str) -> DistPackage | None:
        """
        Get the node from the keys of the dict representing the DAG.

        This method is useful if the dict representing the DAG contains different kind of objects in keys and values.
        Use this method to look up a node obj as a parent (from the keys of the dict) given a node key.

        :param node_key: identifier corresponding to key attr of node obj
        :returns: node obj (as present in the keys of the dict)

        """
        try:
            return self._index[node_key]
        except KeyError:
            return None

    def get_children(self, node_key: str) -> list[ReqPackage]:
        """
        Get child nodes for a node by its key.

        :param node_key: key of the node to get children of
        :returns: child nodes

        """
        node = self.get_node_as_parent(node_key)
        return self._obj[node] if node else []

    def filter_nodes(  # noqa: C901, PLR0912
        self,
        include: list[str] | None,
        exclude: set[str] | None,
        exclude_deps: bool = False,  # noqa: FBT001, FBT002
    ) -> PackageDAG:
        """
        Filter nodes in a graph by given parameters.

        If a node is included, then all it's children are also included.

        :param include: list of node keys to include (or None)
        :param exclude: set of node keys to exclude (or None)
        :raises IncludeExcludeOverlapError: if include and exclude contains the same elements
        :raises IncludePatternNotFoundError: if include has patterns that do not match anything in the graph
        :returns: filtered version of the graph

        """
        # If neither of the filters are specified, short circuit
        if include is None and exclude is None:
            return self

        include_with_casing_preserved: list[str] = []
        if include:
            include_with_casing_preserved = include
            include = [canonicalize_name(i) for i in include]
        exclude = {canonicalize_name(s) for s in exclude} if exclude else set()

        # Check for mutual exclusion of include and exclude sets
        # after normalizing the values to lowercase
        if include and exclude and (set(include) & exclude):
            raise IncludeExcludeOverlapError

        if exclude_deps:
            exclude = self._build_exclusion_set_with_dependencies(exclude)

        # Filter nodes that are explicitly included/excluded
        stack: deque[DistPackage] = deque()
        m: dict[DistPackage, list[ReqPackage]] = {}
        seen = set()
        matched_includes: set[str] = set()
        for node in self._obj:
            if any(fnmatch(node.key, e) for e in exclude):
                continue
            if include is None:
                stack.append(node)
            else:
                should_append = False
                for i in include:
                    if fnmatch(node.key, i):
                        # Add all patterns that match with the node key. Otherwise if we break, patterns like py* or
                        # pytest* (which both should match "pytest") may cause one pattern to be missed and will
                        # raise an error
                        matched_includes.add(i)
                        should_append = True
                if should_append:
                    stack.append(node)

            # Perform DFS on the explicitly included nodes so that we can also include their dependencies, if applicable
            while stack:
                n = stack.pop()
                cldn = [c for c in self._obj[n] if not any(fnmatch(c.key, e) for e in exclude)]
                m[n] = cldn
                seen.add(n.key)
                for c in cldn:
                    if c.key not in seen:
                        cld_node = self.get_node_as_parent(c.key)
                        if cld_node:
                            stack.append(cld_node)
                        else:
                            # It means there's no root node corresponding to the child node i.e.
                            # a dependency is missing
                            continue

        non_existent_includes = [
            i for i in include_with_casing_preserved if canonicalize_name(i) not in matched_includes
        ]
        if non_existent_includes:
            raise IncludePatternNotFoundError(
                "No packages matched using the following patterns: " + ", ".join(non_existent_includes)
            )

        return self.__class__(m)

    def _build_exclusion_set_with_dependencies(self, old_exclude: set[str]) -> set[str]:
        """
        Build a new exclusion set using the fnmatch patterns in `old_exclude` to also grab dependencies.

        Note that it will actually resolve the patterns in old_exclude to actual nodes and use that result instead of
        keeping the patterns.
        """
        # First, resolve old_exclude to actual nodes in the graph as old_exclude may instead contain patterns that are
        # used by fnmatch (or the exclusion may not even exist in the graph)
        resolved_exclude: set[str] = set()

        resolved_exclude.update(node.key for node in self._obj if any(fnmatch(node.key, e) for e in old_exclude))

        # Find all possible candidate nodes for exclusion using DFS
        candidates: set[str] = set()
        stack = list(resolved_exclude)
        while stack:
            candidate = stack.pop()
            if candidate not in candidates:
                candidates.add(candidate)
                stack.extend(dep.key for dep in self.get_children(candidate))

        # Build a reverse graph to know the dependents of a candidate node
        reverse_graph = self.reverse()

        # Precompute number of dependents for each candidate
        dependents_count: defaultdict[str, int] = defaultdict(int)
        for node in candidates:
            dependents_count[node] += len(reverse_graph.get_children(node))

        new_exclude = set()

        # Determine what nodes should actually be excluded
        # Use the resolved exclude set as a starting point as these nodes are explicitly excluded
        queue = deque(resolved_exclude)
        while queue:
            node = queue.popleft()
            new_exclude.add(node)
            for child in self.get_children(node):
                child_key = child.key
                dependents_count[child_key] -= 1

                # If all dependents of child are excluded, it itself is now eligible for exclusion
                # If this branch is never reached, this means there is a dependant that is outside the exclusion set
                # that needs child
                #
                # We also don't want to add child nodes that are in the resolved exclude set, as they are explicitly
                # excluded and have either already been processed or are in the queue awaiting processing
                if (
                    dependents_count[child_key] == 0
                    and child_key not in new_exclude
                    and child_key not in resolved_exclude
                ):
                    queue.append(child_key)

        return new_exclude

    def reverse(self) -> ReversedPackageDAG:
        """
        Reverse the DAG, or turn it upside-down.

        In other words, the directions of edges of the nodes in the DAG will be reversed.

        Note that this function purely works on the nodes in the graph. This implies that to perform a combination of
        filtering and reversing, the order in which `filter` and `reverse` methods should be applied is important. For
        e.g., if reverse is called on a filtered graph, then only the filtered nodes and it's children will be
        considered when reversing. On the other hand, if filter is called on reversed DAG, then the definition of
        "child" nodes is as per the reversed DAG.

        :returns: DAG in the reversed form

        """
        reversed_dag: dict[ReqPackage, list[DistPackage]] = {}
        key_index: dict[str, ReqPackage] = {}
        child_keys = {r.key for r in chain.from_iterable(self._obj.values())}
        for parent, deps in self._obj.items():
            for dep in deps:
                node = key_index.setdefault(dep.key, dep)
                reversed_dag.setdefault(node, []).append(parent.as_parent_of(dep))
            if parent.key not in child_keys:
                reversed_dag[parent.as_requirement()] = []
        return ReversedPackageDAG(dict(reversed_dag))  # type: ignore[arg-type]

    def sort(self) -> PackageDAG:
        """
        Return sorted tree in which the underlying _obj dict is an dict, sorted alphabetically by the keys.

        :returns: Instance of same class with dict

        """
        return self.__class__({k: sorted(v) for k, v in sorted(self._obj.items())})

    # Methods required by the abstract base class Mapping
    def __getitem__(self, arg: DistPackage) -> list[ReqPackage]:
        return self._obj[arg]

    def __iter__(self) -> Iterator[DistPackage]:
        return self._obj.__iter__()

    def __len__(self) -> int:
        return len(self._obj)


def render_invalid_reqs_text(dist_name_to_invalid_reqs_dict: dict[str, list[str]]) -> None:
    for dist_name, invalid_reqs in dist_name_to_invalid_reqs_dict.items():
        print(dist_name, file=sys.stderr)  # noqa: T201

        for invalid_req in invalid_reqs:
            print(f'  Skipping "{invalid_req}"', file=sys.stderr)  # noqa: T201


class ReversedPackageDAG(PackageDAG):
    """
    Representation of Package dependencies in the reverse order.

    Similar to it's super class `PackageDAG`, the underlying datastructure is a dict, but here the keys are expected to
    be of type `ReqPackage` and each item in the values of type `DistPackage`.

    Typically, this object will be obtained by calling `PackageDAG.reverse`.

    """

    def reverse(self) -> PackageDAG:  # type: ignore[override]
        """
        Reverse the already reversed DAG to get the PackageDAG again.

        :returns: reverse of the reversed DAG

        """
        forward_dag: dict[DistPackage, list[ReqPackage]] = {}
        key_index: dict[str, DistPackage] = {}
        child_keys = {r.key for r in chain.from_iterable(self._obj.values())}
        for req_node, parents in self._obj.items():
            for parent in parents:
                assert isinstance(parent, DistPackage)
                node = key_index.setdefault(parent.key, parent.as_parent_of(None))
                forward_dag.setdefault(node, []).append(req_node)  # type: ignore[invalid-argument-type]  # runtime: ReqPackage
            if req_node.key not in child_keys:
                assert isinstance(req_node, ReqPackage)
                assert req_node.dist is not None
                forward_dag.setdefault(key_index.setdefault(req_node.dist.key, req_node.dist), [])
        return PackageDAG(dict(forward_dag))


def _resolve_extras(pkg_deps: dict[DistPackage, list[ReqPackage]], idx: dict[str, DistPackage]) -> None:
    """Add extra/optional dependencies to the DAG in-place."""
    extras_needed = _collect_explicit_extras(pkg_deps)
    for pkg_key, extras in _collect_satisfied_extras(pkg_deps, idx).items():
        extras_needed.setdefault(pkg_key, set()).update(extras)
    processed: dict[str, set[str]] = {}
    while extras_needed:
        next_round: dict[str, set[str]] = {}
        for pkg_key, extras in extras_needed.items():
            new_extras = extras - processed.get(pkg_key, set())
            if not new_extras:
                continue
            processed.setdefault(pkg_key, set()).update(new_extras)
            dist_pkg = idx.get(pkg_key)
            if dist_pkg is None or dist_pkg not in pkg_deps:
                continue
            for req, extra_name in dist_pkg.requires_for_extras(frozenset(new_extras)):
                dist = idx.get(canonicalize_name(req.name))
                if dist is None:
                    continue
                req.name = dist.project_name
                pkg_deps[dist_pkg].append(ReqPackage(req, dist, extra=extra_name))
                if req.extras:
                    next_round.setdefault(dist.key, set()).update(req.extras)
        extras_needed = next_round


def _collect_explicit_extras(pkg_deps: dict[DistPackage, list[ReqPackage]]) -> dict[str, set[str]]:
    """Collect extras explicitly requested via requirement specifiers (e.g. ``oauthlib[signedtoken]``)."""
    extras_needed: dict[str, set[str]] = {}
    for deps in pkg_deps.values():
        for dep in deps:
            if dep._obj.extras:  # noqa: SLF001
                extras_needed.setdefault(dep.key, set()).update(dep._obj.extras)  # noqa: SLF001
    return extras_needed


def _collect_satisfied_extras(
    pkg_deps: dict[DistPackage, list[ReqPackage]], idx: dict[str, DistPackage]
) -> dict[str, set[str]]:
    """Collect extras whose dependencies are all installed in the environment."""
    extras_needed: dict[str, set[str]] = {}
    for dist_pkg in pkg_deps:
        for extra_name in dist_pkg.provides_extras:
            if _extra_is_satisfied(dist_pkg.key, extra_name, pkg_deps, idx, set()):
                extras_needed.setdefault(dist_pkg.key, set()).add(extra_name)
    return extras_needed


def _extra_is_satisfied(
    pkg_key: str,
    extra_name: str,
    pkg_deps: dict[DistPackage, list[ReqPackage]],
    idx: dict[str, DistPackage],
    visited: set[tuple[str, str]],
) -> bool:
    if (pkg_key, extra_name) in visited:
        return True
    visited.add((pkg_key, extra_name))
    if (dist_pkg := idx.get(pkg_key)) is None or dist_pkg not in pkg_deps:
        return False
    if not (reqs := list(dist_pkg.requires_for_extras(frozenset({extra_name})))):
        return False
    for req, _ in reqs:
        if (dep_key := canonicalize_name(req.name)) not in idx:
            return False
        if not all(_extra_is_satisfied(dep_key, sub_extra, pkg_deps, idx, visited) for sub_extra in req.extras):
            return False
    return True


__all__ = [
    "PackageDAG",
    "ReversedPackageDAG",
]
