from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pipenv.vendor.pipdeptree._computed import ComputedValues

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._cli import RenderContext
    from pipenv.vendor.pipdeptree._models import PackageDAG
    from pipenv.vendor.pipdeptree._models.package import RenderMode


def render_json(
    tree: PackageDAG,
    *,
    context: RenderContext | None = None,
    mode: RenderMode = "default",
) -> None:
    """
    Convert the tree into a flat json representation.

    The json repr will be a list of hashes, each hash having 2 fields:
      - package
      - dependencies

    :param tree: dependency tree
    :param context: metadata and computed fields to include
    :param mode: "resolved" emits candidate_version instead of installed/required for resolved trees
    :returns: JSON representation of the tree

    """
    tree = tree.sort()

    def _package_dict(k: Any) -> dict[str, Any]:
        d: dict[str, Any] = k.as_dict(mode=mode)
        if context and context.metadata:
            d["metadata"] = k.get_metadata_dict(list(context.metadata))
        if context and context.computed:
            d["computed"] = ComputedValues(k.key, tree, context.full_tree).as_dict(context.computed)
        return d

    output = json.dumps(
        [{"package": _package_dict(k), "dependencies": [v.as_dict(mode=mode) for v in vs]} for k, vs in tree.items()],
        indent=4,
    )
    print(output)  # noqa: T201


__all__ = [
    "render_json",
]
