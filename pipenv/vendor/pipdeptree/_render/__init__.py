from __future__ import annotations

from typing import TYPE_CHECKING

from .freeze import render_freeze
from .graphviz import render_graphviz
from .json import render_json
from .json_tree import render_json_tree
from .mermaid import render_mermaid
from .rich_text import render_rich_text
from .summary import render_summary
from .text import render_text

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._cli import Options
    from pipenv.vendor.pipdeptree._models import PackageDAG
    from pipenv.vendor.pipdeptree._models.package import RenderMode


def render(options: Options, tree: PackageDAG) -> None:
    output_format = options.output_format
    # from-index/from-lock build a tree from resolved data: one version per package and no per-edge
    # range, so edges show "[candidate: <version>]" instead of "[required:, installed:]".
    mode: RenderMode = "resolved" if options.command in {"from-index", "from-lock"} else "default"
    # --summary reduces the tree to an aggregate report; output_format then only selects its presentation style.
    if options.summary:
        render_summary(tree, mode=mode, style=output_format)
    elif output_format == "json":
        render_json(tree, context=options.context, mode=mode)
    elif output_format == "json-tree":
        render_json_tree(tree, context=options.context, mode=mode)
    elif output_format == "mermaid":
        render_mermaid(tree, context=options.context)
    elif output_format == "freeze":
        render_freeze(tree, max_depth=options.depth, list_all=options.all)
    elif output_format == "rich":
        render_rich_text(tree, max_depth=options.depth, list_all=options.all, context=options.context, mode=mode)
    elif output_format.startswith("graphviz-"):
        render_graphviz(
            tree,
            output_format=output_format[len("graphviz-") :],
            reverse=options.reverse,
            max_depth=options.depth,
            context=options.context,
        )
    else:
        render_text(
            tree,
            max_depth=options.depth,
            encoding=options.encoding,
            list_all=options.all,
            context=options.context,
            mode=mode,
        )


__all__ = [
    "render",
]
