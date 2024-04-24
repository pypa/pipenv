from __future__ import annotations

import sys
from collections import defaultdict, deque
from fnmatch import fnmatch
from itertools import chain
from typing import TYPE_CHECKING, Iterator, List, Mapping

from pipenv.vendor.packaging.utils import canonicalize_name

if TYPE_CHECKING:
    from importlib.metadata import Distribution


from .package import DistPackage, InvalidRequirementError, ReqPackage


def render_invalid_reqs_text_if_necessary(dist_name_to_invalid_reqs_dict: dict[str, list[str]]) -> None:
    if not dist_name_to_invalid_reqs_dict:
        return

    print("Warning!!! Invalid requirement strings found for the following distributions:", file=sys.stderr)  # noqa: T201
    for dist_name, invalid_reqs in dist_name_to_invalid_reqs_dict.items():
        print(dist_name, file=sys.stderr)  # noqa: T201

        for invalid_req in invalid_reqs:
            print(f'  Skipping "{invalid_req}"', file=sys.stderr)  # noqa: T201
    print("-" * 72, file=sys.stderr)  # noqa: T201


class PackageDAG(Mapping[DistPackage, List[ReqPackage]]):
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
    def from_pkgs(cls, pkgs: list[Distribution]) -> PackageDAG:
        dist_pkgs = [DistPackage(p) for p in pkgs]
        idx = {p.key: p for p in dist_pkgs}
        m: dict[DistPackage, list[ReqPackage]] = {}
        dist_name_to_invalid_reqs_dict: dict[str, list[str]] = {}
        for p in dist_pkgs:
            reqs = []
            requires_iterator = p.requires()
            while True:
                try:
                    req = next(requires_iterator)
                except InvalidRequirementError as err:
                    # We can't work with invalid requirement strings. Let's warn the user about them.
                    dist_name_to_invalid_reqs_dict.setdefault(p.project_name, []).append(str(err))
                    continue
                except StopIteration:
                    break
                d = idx.get(canonicalize_name(req.name))
                # Distribution.requires only returns the name of requirements in the metadata file, which may not be the
                # same as the name in PyPI. We should try to retain the original package names for requirements.
                # See https://github.com/tox-dev/pipdeptree/issues/242
                req.name = d.project_name if d is not None else req.name
                pkg = ReqPackage(req, d)
                reqs.append(pkg)
            m[p] = reqs

        render_invalid_reqs_text_if_necessary(dist_name_to_invalid_reqs_dict)

        return cls(m)

    def __init__(self, m: dict[DistPackage, list[ReqPackage]]) -> None:
        """
        Initialize the PackageDAG object.

        :param dict m: dict of node objects (refer class docstring)
        :returns: None
        :rtype: NoneType

        """
        self._obj: dict[DistPackage, list[ReqPackage]] = m
        self._index: dict[str, DistPackage] = {p.key: p for p in list(self._obj)}

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

    def filter_nodes(self, include: list[str] | None, exclude: set[str] | None) -> PackageDAG:  # noqa: C901, PLR0912
        """
        Filter nodes in a graph by given parameters.

        If a node is included, then all it's children are also included.

        :param include: list of node keys to include (or None)
        :param exclude: set of node keys to exclude (or None)
        :raises ValueError: If include has node keys that do not exist in the graph
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

        # Check for mutual exclusion of show_only and exclude sets
        # after normalizing the values to lowercase
        if include and exclude:
            assert not (set(include) & exclude)

        # Traverse the graph in a depth first manner and filter the
        # nodes according to `show_only` and `exclude` sets
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
            raise ValueError("No packages matched using the following patterns: " + ", ".join(non_existent_includes))

        return self.__class__(m)

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
        m: defaultdict[ReqPackage, list[DistPackage]] = defaultdict(list)
        child_keys = {r.key for r in chain.from_iterable(self._obj.values())}
        for k, vs in self._obj.items():
            for v in vs:
                # if v is already added to the dict, then ensure that
                # we are using the same object. This check is required
                # as we're using array mutation
                node: ReqPackage = next((p for p in m if p.key == v.key), v)
                m[node].append(k.as_parent_of(v))
            if k.key not in child_keys:
                m[k.as_requirement()] = []
        return ReversedPackageDAG(dict(m))  # type: ignore[arg-type]

    def sort(self) -> PackageDAG:
        """
        Return sorted tree in which the underlying _obj dict is an dict, sorted alphabetically by the keys.

        :returns: Instance of same class with dict

        """
        return self.__class__({k: sorted(v) for k, v in sorted(self._obj.items())})

    # Methods required by the abstract base class Mapping
    def __getitem__(self, arg: DistPackage) -> list[ReqPackage] | None:  # type: ignore[override]
        return self._obj.get(arg)

    def __iter__(self) -> Iterator[DistPackage]:
        return self._obj.__iter__()

    def __len__(self) -> int:
        return len(self._obj)


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
        m: defaultdict[DistPackage, list[ReqPackage]] = defaultdict(list)
        child_keys = {r.key for r in chain.from_iterable(self._obj.values())}
        for k, vs in self._obj.items():
            for v in vs:
                assert isinstance(v, DistPackage)
                node = next((p for p in m if p.key == v.key), v.as_parent_of(None))
                m[node].append(k)
            if k.key not in child_keys:
                assert isinstance(k, ReqPackage)
                assert k.dist is not None
                m[k.dist] = []
        return PackageDAG(dict(m))


__all__ = [
    "PackageDAG",
    "ReversedPackageDAG",
]
