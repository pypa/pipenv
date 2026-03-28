from __future__ import annotations

from typing import TYPE_CHECKING

from .text import _render_text_simple, get_top_level_nodes

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._models.dag import PackageDAG


def render_freeze(tree: PackageDAG, *, max_depth: float, list_all: bool = True) -> None:
    nodes = get_top_level_nodes(tree, list_all=list_all)
    _render_text_simple(tree, nodes, max_depth, include_license=False, frozen=True, bullet="")


__all__ = [
    "render_freeze",
]
