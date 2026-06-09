from __future__ import annotations

import itertools as it
from typing import TYPE_CHECKING, Final

from pipenv.vendor.pipdeptree._models import DistPackage, ReqPackage, ReversedPackageDAG

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._cli import RenderContext
    from pipenv.vendor.pipdeptree._models import PackageDAG

_RESERVED_IDS: Final[frozenset[str]] = frozenset(
    [
        "C4Component",
        "C4Container",
        "C4Deployment",
        "C4Dynamic",
        "_blank",
        "_parent",
        "_self",
        "_top",
        "call",
        "class",
        "classDef",
        "click",
        "end",
        "flowchart",
        "flowchart-v2",
        "graph",
        "interpolate",
        "linkStyle",
        "style",
        "subgraph",
    ],
)


def render_mermaid(
    tree: PackageDAG,
    *,
    context: RenderContext | None = None,
) -> None:
    """
    Produce a Mermaid flowchart from the dependency graph.

    :param tree: dependency graph
    :param context: metadata and computed fields to include in node labels

    """
    node_ids_map: dict[str, str] = {}
    nodes: set[str] = set()
    edges: set[str] = set()

    if isinstance(tree, ReversedPackageDAG):
        _build_reversed_mermaid(tree, nodes, edges, node_ids_map, context)
    else:
        _build_forward_mermaid(tree, nodes, edges, node_ids_map, context)

    lines = [
        "flowchart TD",
        "classDef missing stroke-dasharray: 5",
        *sorted(nodes),
        *sorted(edges),
    ]
    print("".join(f"{'    ' if i else ''}{line}\n" for i, line in enumerate(lines)))  # noqa: T201


def _build_reversed_mermaid(
    tree: PackageDAG,
    nodes: set[str],
    edges: set[str],
    node_ids_map: dict[str, str],
    context: RenderContext | None,
) -> None:
    for package, reverse_dependencies in tree.items():
        assert isinstance(package, ReqPackage)
        label_parts = [
            package.project_name,
            "(missing)" if package.is_missing else package.installed_version,
        ]
        if context and (extra := context.build_node_extra_label(package.key, tree, "<br/>")):
            label_parts.append(extra)
        package_key = _mermaid_id(package.key, node_ids_map)
        nodes.add(f'{package_key}["{"<br/>".join(label_parts)}"]')
        for reverse_dependency in reverse_dependencies:
            assert isinstance(reverse_dependency, DistPackage)
            rev_key = _mermaid_id(reverse_dependency.key, node_ids_map)
            edges.add(f'{package_key} -- "{reverse_dependency.edge_label}" --> {rev_key}')


def _build_forward_mermaid(
    tree: PackageDAG,
    nodes: set[str],
    edges: set[str],
    node_ids_map: dict[str, str],
    context: RenderContext | None,
) -> None:
    for package, dependencies in tree.items():
        label_parts = [package.project_name, package.version]
        if context and (extra := context.build_node_extra_label(package.key, tree, "<br/>")):
            label_parts.append(extra)
        package_key = _mermaid_id(package.key, node_ids_map)
        nodes.add(f'{package_key}["{"<br/>".join(label_parts)}"]')
        for dependency in dependencies:
            dependency_key = _mermaid_id(dependency.key, node_ids_map)
            if dependency.is_missing:
                dependency_label = f"{dependency.project_name}<br/>(missing)"
                nodes.add(f'{dependency_key}["{dependency_label}"]:::missing')
                edges.add(f"{package_key} -.-> {dependency_key}")
            else:
                edges.add(f'{package_key} -- "{dependency.edge_label}" --> {dependency_key}')


def _mermaid_id(key: str, node_ids_map: dict[str, str]) -> str:
    """Return a valid Mermaid node ID from a string."""
    if (canonical_id := node_ids_map.get(key)) is not None:
        return canonical_id
    if key not in _RESERVED_IDS:
        node_ids_map[key] = key
        return key
    for number in it.count():
        new_id = f"{key}_{number}"
        if new_id not in node_ids_map:
            node_ids_map[key] = new_id
            return new_id
    raise NotImplementedError


__all__ = [
    "render_mermaid",
]
