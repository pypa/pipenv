from __future__ import annotations

from typing import TYPE_CHECKING

from .freeze import render_freeze
from .graphviz import render_graphviz
from .json import render_json
from .json_tree import render_json_tree
from .mermaid import render_mermaid
from .text import render_text

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._cli import Options
    from pipenv.vendor.pipdeptree._models import PackageDAG


def render(options: Options, tree: PackageDAG) -> None:
    output_format = options.output_format
    if output_format == "json":
        render_json(tree)
    elif output_format == "json-tree":
        render_json_tree(tree)
    elif output_format == "mermaid":
        render_mermaid(tree)
    elif output_format == "freeze":
        render_freeze(tree, max_depth=options.depth, list_all=options.all)
    elif output_format.startswith("graphviz-"):
        render_graphviz(tree, output_format=output_format[len("graphviz-") :], reverse=options.reverse)
    else:
        render_text(
            tree,
            max_depth=options.depth,
            encoding=options.encoding,
            list_all=options.all,
            include_license=options.license,
        )


__all__ = [
    "render",
]
