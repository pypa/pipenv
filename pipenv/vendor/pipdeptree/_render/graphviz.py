from __future__ import annotations

import math
import os
import sys
from collections import deque
from typing import TYPE_CHECKING

from pipenv.vendor.pipdeptree._models import DistPackage, ReqPackage

if TYPE_CHECKING:
    from graphviz import Digraph

    from pipenv.vendor.pipdeptree._models import PackageDAG


def _get_all_dep_keys(tree: PackageDAG) -> set[str]:
    """Return the set of keys that appear as dependencies of some package."""
    dep_keys: set[str] = set()
    for deps in tree.values():
        dep_keys.update(dep.key for dep in deps)
    return dep_keys


def _build_reverse_graph(tree: PackageDAG, graph: Digraph, max_depth: float) -> None:  # noqa: C901, PLR0912
    """Build graphviz nodes and edges for a reversed dependency tree."""
    if max_depth < math.inf:
        parent_keys = _get_all_dep_keys(tree)
        root_keys = {dep_rev.key for dep_rev in tree if dep_rev.key not in parent_keys}
        visited: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((k, 0) for k in root_keys)
        while queue:
            key, depth = queue.popleft()
            if key in visited:
                continue
            visited[key] = depth
            if depth < max_depth:
                for parent in tree.get_children(key):
                    if parent.key not in visited:
                        queue.append((parent.key, depth + 1))
        for dep_rev, parents in tree.items():
            if dep_rev.key not in visited:
                continue
            assert isinstance(dep_rev, ReqPackage)
            dep_label = f"{dep_rev.project_name}\\n{dep_rev.installed_version}"
            graph.node(dep_rev.key, label=dep_label)
            if visited[dep_rev.key] < max_depth:
                for parent in parents:
                    assert isinstance(parent, DistPackage)
                    if parent.key in visited:
                        edge_label = (parent.req.version_spec if parent.req is not None else None) or "any"
                        graph.edge(dep_rev.key, parent.key, label=edge_label)
    else:
        for dep_rev, parents in tree.items():
            assert isinstance(dep_rev, ReqPackage)
            dep_label = f"{dep_rev.project_name}\\n{dep_rev.installed_version}"
            graph.node(dep_rev.key, label=dep_label)
            for parent in parents:
                assert isinstance(parent, DistPackage)
                edge_label = (parent.req.version_spec if parent.req is not None else None) or "any"
                graph.edge(dep_rev.key, parent.key, label=edge_label)


def _build_forward_graph(tree: PackageDAG, graph: Digraph, max_depth: float) -> None:  # noqa: C901, PLR0912
    """Build graphviz nodes and edges for a forward dependency tree."""
    if max_depth < math.inf:  # noqa: PLR1702
        dep_keys = _get_all_dep_keys(tree)
        root_keys = {pkg.key for pkg in tree if pkg.key not in dep_keys}
        visited: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((k, 0) for k in root_keys)
        while queue:
            key, depth = queue.popleft()
            if key in visited:
                continue
            visited[key] = depth
            if depth < max_depth:
                children = tree.get_children(key)
                for dep in children:
                    if dep.key not in visited:
                        queue.append((dep.key, depth + 1))
        for pkg, deps in tree.items():
            if pkg.key not in visited:
                continue
            pkg_label = f"{pkg.project_name}\\n{pkg.version}"
            graph.node(pkg.key, label=pkg_label)
            if visited[pkg.key] < max_depth:
                for dep in deps:
                    if dep.key in visited:
                        edge_label = dep.version_spec or "any"
                        if dep.is_missing:
                            dep_label = f"{dep.project_name}\\n(missing)"
                            graph.node(dep.key, label=dep_label, style="dashed")
                            graph.edge(pkg.key, dep.key, style="dashed")
                        else:
                            graph.edge(pkg.key, dep.key, label=edge_label)
    else:
        for pkg, deps in tree.items():
            pkg_label = f"{pkg.project_name}\\n{pkg.version}"
            graph.node(pkg.key, label=pkg_label)
            for dep in deps:
                edge_label = dep.version_spec or "any"
                if dep.is_missing:
                    dep_label = f"{dep.project_name}\\n(missing)"
                    graph.node(dep.key, label=dep_label, style="dashed")
                    graph.edge(pkg.key, dep.key, style="dashed")
                else:
                    graph.edge(pkg.key, dep.key, label=edge_label)


def dump_graphviz(
    tree: PackageDAG,
    output_format: str = "dot",
    is_reverse: bool = False,  # noqa: FBT001, FBT002
    max_depth: float = math.inf,
) -> str | bytes:
    """
    Output dependency graph as one of the supported GraphViz output formats.

    :param dict tree: dependency graph
    :param string output_format: output format
    :param bool is_reverse: reverse or not
    :param float max_depth: maximum depth of the dependency tree to include
    :returns: representation of tree in the specified output format
    :rtype: str or binary representation depending on the output format
    """
    try:
        from graphviz import Digraph  # noqa: PLC0415
    except ImportError as exc:
        print(  # noqa: T201
            "graphviz is not available, but necessary for the output option. Please install it.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    from graphviz import parameters  # noqa: PLC0415

    valid_formats = parameters.FORMATS

    if output_format not in valid_formats:
        print(f"{output_format} is not a supported output format.", file=sys.stderr)  # noqa: T201
        print(f"Supported formats are: {', '.join(sorted(valid_formats))}", file=sys.stderr)  # noqa: T201
        raise SystemExit(1)

    graph = Digraph(format=output_format)

    if is_reverse:
        _build_reverse_graph(tree, graph, max_depth)
    else:
        _build_forward_graph(tree, graph, max_depth)

    # Allow output of dot format, even if GraphViz isn't installed.
    if output_format == "dot":
        # Emulates graphviz.dot.Dot.__iter__() to force the sorting of graph.body.
        # Fixes https://github.com/tox-dev/pipdeptree/issues/188
        # That way we can guarantee the output of the dot format is deterministic
        # and stable.
        return "".join([next(iter(graph)), *sorted(graph.body), graph._tail])  # noqa: SLF001

    # As it's unknown if the selected output format is binary or not, try to
    # decode it as UTF8 and only print it out in binary if that's not possible.
    try:
        return graph.pipe().decode("utf-8")  # type: ignore[no-any-return]
    except UnicodeDecodeError:
        return graph.pipe()  # type: ignore[no-any-return]


def print_graphviz(dump_output: str | bytes) -> None:
    """
    Dump the data generated by GraphViz to stdout.

    :param dump_output: The output from dump_graphviz

    """
    if hasattr(dump_output, "encode"):
        print(dump_output)  # noqa: T201
    else:
        with os.fdopen(sys.stdout.fileno(), "wb") as bytestream:
            bytestream.write(dump_output)


def render_graphviz(tree: PackageDAG, *, output_format: str, reverse: bool, max_depth: float = math.inf) -> None:
    output = dump_graphviz(tree, output_format=output_format, is_reverse=reverse, max_depth=max_depth)
    print_graphviz(output)


__all__ = [
    "render_graphviz",
]
