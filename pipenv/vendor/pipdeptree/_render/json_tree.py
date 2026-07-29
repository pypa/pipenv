from __future__ import annotations

import json
from itertools import chain
from typing import TYPE_CHECKING, Any

from pipenv.vendor.pipdeptree._computed import ComputedValues
from pipenv.vendor.pipdeptree._models import ReqPackage

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._cli import RenderContext
    from pipenv.vendor.pipdeptree._models import DistPackage, PackageDAG
    from pipenv.vendor.pipdeptree._models.package import RenderMode


def render_json_tree(
    tree: PackageDAG,
    *,
    context: RenderContext | None = None,
    mode: RenderMode = "default",
) -> None:
    """
    Convert the tree into a nested json representation.

    The json repr will be a list of hashes, each hash having the following fields:

      - package_name
      - key
      - required_version
      - installed_version
      - dependencies: list of dependencies

    :param tree: dependency tree
    :param context: metadata and computed fields to include
    :param mode: "resolved" emits candidate_version instead of installed/required for resolved trees
    :returns: json representation of the tree

    """
    tree = tree.sort()
    branch_keys = {r.key for r in chain.from_iterable(tree.values())}
    nodes = [p for p in tree if p.key not in branch_keys]

    def aux(
        node: DistPackage | ReqPackage,
        parent: DistPackage | ReqPackage | None = None,
        cur_chain: list[str] | None = None,
    ) -> dict[str, Any]:
        if cur_chain is None:
            cur_chain = [node.project_name]

        d: dict[str, str | list[Any] | None] = node.as_dict(mode=mode)  # ty: ignore[invalid-assignment]
        if mode == "default":
            if parent:
                d["required_version"] = (
                    node.version_spec if isinstance(node, ReqPackage) and node.version_spec else "Any"
                )
            else:
                d["required_version"] = d["installed_version"]

        if context and context.metadata:
            d["metadata"] = node.get_metadata_dict(list(context.metadata))  # ty: ignore[invalid-assignment]
        if context and context.computed:
            d["computed"] = ComputedValues(node.key, tree, context.full_tree).as_dict(context.computed)  # ty: ignore[invalid-assignment]

        d["dependencies"] = [
            aux(c, parent=node, cur_chain=[*cur_chain, c.project_name])
            for c in tree.get_children(node.key)
            if c.project_name not in cur_chain
        ]

        return d

    print(json.dumps([aux(p) for p in nodes], indent=4))  # noqa: T201


__all__ = [
    "render_json_tree",
]
