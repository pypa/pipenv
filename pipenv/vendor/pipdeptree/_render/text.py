from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any

from pipenv.vendor.pipdeptree._computed import ComputedValues

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._cli import RenderContext
    from pipenv.vendor.pipdeptree._models import DistPackage, PackageDAG, ReqPackage
    from pipenv.vendor.pipdeptree._models.package import RenderMode


def render_text(  # noqa: PLR0913
    tree: PackageDAG,
    *,
    max_depth: float,
    encoding: str,
    list_all: bool = True,
    context: RenderContext | None = None,
    mode: RenderMode = "default",
) -> None:
    """
    Print tree as text on console.

    :param tree: the package tree
    :param max_depth: the maximum depth of the dependency tree
    :param encoding: encoding to use (use "utf-8", "utf-16", "utf-32" for unicode or anything else for legacy output)
    :param list_all: whether to list all the pkgs at the root level or only those that are the sub-dependencies
    :param context: metadata and computed fields to display
    :param mode: "resolved" renders edges as "[candidate: <version>]" for resolved trees
    :returns: None

    """
    nodes = get_top_level_nodes(tree, list_all=list_all)

    if encoding in {"utf-8", "utf-16", "utf-32"}:
        _render_text_with_unicode(tree, nodes, max_depth, context, mode=mode)
    else:
        _render_text_simple(tree, nodes, max_depth, context=context, mode=mode)


def get_top_level_nodes(tree: PackageDAG, *, list_all: bool) -> list[DistPackage]:
    """
    Get a list of nodes that will appear at the first depth of the dependency tree. This also sorts `tree` in-place.

    :param tree: the package tree
    :param list_all: whether to list all the pkgs at the root level or only those that are the sub-dependencies
    """
    tree = tree.sort(in_place=True)
    nodes = list(tree.keys())
    branch_keys = {r.key for r in chain.from_iterable(tree.values())}

    if not list_all:
        nodes = [p for p in nodes if p.key not in branch_keys]

    return nodes


def _render_text_with_unicode(
    tree: PackageDAG,
    nodes: list[DistPackage],
    max_depth: float,
    context: RenderContext | None,
    *,
    mode: RenderMode = "default",
) -> None:
    def aux(  # noqa: PLR0913, PLR0917
        node: DistPackage | ReqPackage,
        parent: DistPackage | ReqPackage | None = None,
        indent: int = 0,
        cur_chain: list[str] | None = None,
        prefix: str = "",
        depth: int = 0,
        has_grand_parent: bool = False,  # noqa: FBT001, FBT002
        is_last_child: bool = False,  # noqa: FBT001, FBT002
        parent_is_last_child: bool = False,  # noqa: FBT001, FBT002
    ) -> list[Any]:
        cur_chain = cur_chain or []
        node_str = node.render(parent, frozen=False, mode=mode)
        if context and context.active:
            node_str += _build_suffix(node, context, tree)
        next_prefix = ""
        next_indent = indent + 2

        if parent:
            bullet = "├── "
            if is_last_child:
                bullet = "└── "

            if has_grand_parent:
                next_indent -= 1
                if parent_is_last_child:
                    prefix += " " * (indent + 1 - depth)
                else:
                    prefix += "│" + " " * (indent - depth)
                # Without this extra space, bullets will point to the space just before the project name
                prefix += " "
            next_prefix = prefix
            node_str = prefix + bullet + node_str

        result = [node_str]

        children = tree.get_children(node.key)
        children_strings = [
            aux(
                c,
                node,
                indent=next_indent,
                cur_chain=[*cur_chain, c.project_name],
                prefix=next_prefix,
                depth=depth + 1,
                has_grand_parent=parent is not None,
                is_last_child=c is children[-1],
                parent_is_last_child=is_last_child,
            )
            for c in children
            if c.project_name not in cur_chain and depth + 1 <= max_depth
        ]

        result += list(chain.from_iterable(children_strings))
        return result

    lines = chain.from_iterable([aux(p) for p in nodes])
    print("\n".join(lines))  # noqa: T201


def _render_text_simple(  # noqa: PLR0913
    tree: PackageDAG,
    nodes: list[DistPackage],
    max_depth: float,
    *,
    context: RenderContext | None = None,
    frozen: bool = False,
    bullet: str = "- ",
    mode: RenderMode = "default",
) -> None:
    def aux(
        node: DistPackage | ReqPackage,
        parent: DistPackage | ReqPackage | None = None,
        indent: int = 0,
        cur_chain: list[str] | None = None,
        depth: int = 0,
    ) -> list[Any]:
        cur_chain = cur_chain or []
        node_str = node.render(parent, frozen=frozen, mode=mode)
        if context and context.active:
            node_str += _build_suffix(node, context, tree)
        if parent:
            node_str = " " * indent + bullet + node_str
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


def _build_suffix(
    node: DistPackage | ReqPackage,
    context: RenderContext,
    tree: PackageDAG,
    *,
    exclude: frozenset[str] = frozenset(),
) -> str:
    parts: list[str] = []
    if context.metadata:
        parts.extend(node.get_metadata_values(list(context.metadata)))
    if context.computed:
        parts.extend(ComputedValues(node.key, tree, context.full_tree).format_display(context.computed, exclude))
    return f" ({', '.join(parts)})" if parts else ""


__all__ = ["get_top_level_nodes", "render_text"]
