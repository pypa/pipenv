from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any

from .text import get_top_level_nodes

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._models.dag import PackageDAG
    from pipenv.vendor.pipdeptree._models.package import DistPackage, ReqPackage


def render_freeze(tree: PackageDAG, *, max_depth: float, list_all: bool = True) -> None:
    nodes = get_top_level_nodes(tree, list_all=list_all)

    def aux(
        node: DistPackage | ReqPackage,
        parent: DistPackage | ReqPackage | None = None,
        indent: int = 0,
        cur_chain: list[str] | None = None,
        depth: int = 0,
    ) -> list[Any]:
        cur_chain = cur_chain or []
        node_str = node.render(parent, frozen=True)
        if parent:
            prefix = " " * indent
            node_str = prefix + node_str
        result = [node_str]
        children = [
            aux(c, node, indent=indent + 2, cur_chain=[*cur_chain, c.project_name], depth=depth + 1)
            for c in tree.get_children(node.key)
            if c.project_name not in cur_chain and depth + 1 <= max_depth
        ]
        result += list(chain.from_iterable(children))
        return result

    lines = chain.from_iterable([aux(p) for p in nodes])
    print("\n".join(lines))  # noqa: T201


__all__ = [
    "render_freeze",
]
