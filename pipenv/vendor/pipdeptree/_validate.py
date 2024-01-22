from __future__ import annotations

import sys
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._models.package import Package

    from ._cli import Options
    from ._models import DistPackage, PackageDAG, ReqPackage


def validate(args: Options, is_text_output: bool, tree: PackageDAG) -> int:  # noqa: FBT001
    # Before any reversing or filtering, show warnings to console, about possibly conflicting or cyclic deps if found
    # and warnings are enabled (i.e. only if output is to be printed to console)
    if is_text_output and args.warn != "silence":
        conflicts = conflicting_deps(tree)
        if conflicts:
            render_conflicts_text(conflicts)
            print("-" * 72, file=sys.stderr)  # noqa: T201

        cycles = cyclic_deps(tree)
        if cycles:
            render_cycles_text(cycles)
            print("-" * 72, file=sys.stderr)  # noqa: T201

        if args.warn == "fail" and (conflicts or cycles):
            return 1
    return 0


def conflicting_deps(tree: PackageDAG) -> dict[DistPackage, list[ReqPackage]]:
    """Return dependencies which are not present or conflict with the requirements of other packages.

    e.g. will warn if pkg1 requires pkg2==2.0 and pkg2==1.0 is installed

    :param tree: the requirements tree (dict)
    :returns: dict of DistPackage -> list of unsatisfied/unknown ReqPackage
    :rtype: dict

    """
    conflicting = defaultdict(list)
    for package, requires in tree.items():
        for req in requires:
            if req.is_conflicting():
                conflicting[package].append(req)
    return conflicting


def render_conflicts_text(conflicts: dict[DistPackage, list[ReqPackage]]) -> None:
    if conflicts:
        print("Warning!!! Possibly conflicting dependencies found:", file=sys.stderr)  # noqa: T201
        # Enforce alphabetical order when listing conflicts
        pkgs = sorted(conflicts.keys())
        for p in pkgs:
            pkg = p.render_as_root(frozen=False)
            print(f"* {pkg}", file=sys.stderr)  # noqa: T201
            for req in conflicts[p]:
                req_str = req.render_as_branch(frozen=False)
                print(f" - {req_str}", file=sys.stderr)  # noqa: T201


def cyclic_deps(tree: PackageDAG) -> list[list[Package]]:
    """Return cyclic dependencies as list of lists.

    :param  tree: package tree/dag
    :returns: list of lists, where each list represents a cycle

    """

    def dfs(root: DistPackage, current: Package, visited: set[str], cdeps: list[Package]) -> bool:
        if current.key not in visited:
            visited.add(current.key)
            current_dist = tree.get_node_as_parent(current.key)
            if not current_dist:
                return False

            reqs = tree.get(current_dist)
            if not reqs:
                return False

            for req in reqs:
                if dfs(root, req, visited, cdeps):
                    cdeps.append(current)
                    return True
        elif current.key == root.key:
            cdeps.append(current)
            return True
        return False

    cycles: list[list[Package]] = []

    for p in tree:
        cdeps: list[Package] = []
        visited: set[str] = set()
        if dfs(p, p, visited, cdeps):
            cdeps.reverse()
            cycles.append(cdeps)

    return cycles


def render_cycles_text(cycles: list[list[Package]]) -> None:
    if cycles:
        print("Warning!! Cyclic dependencies found:", file=sys.stderr)  # noqa: T201
        # List in alphabetical order the dependency that caused the cycle (i.e. the second-to-last Package element)
        cycles = sorted(cycles, key=lambda c: c[len(c) - 2].key)
        for cycle in cycles:
            print("*", end=" ", file=sys.stderr)  # noqa: T201

            size = len(cycle) - 1
            for idx, pkg in enumerate(cycle):
                if idx == size:
                    print(f"{pkg.project_name}", end="", file=sys.stderr)  # noqa: T201
                else:
                    print(f"{pkg.project_name} =>", end=" ", file=sys.stderr)  # noqa: T201
            print(file=sys.stderr)  # noqa: T201


__all__ = [
    "validate",
]
