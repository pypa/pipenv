from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._models import PackageDAG


def render_json(tree: PackageDAG) -> str:
    """
    Convert the tree into a flat json representation.

    The json repr will be a list of hashes, each hash having 2 fields:
      - package
      - dependencies: list of dependencies

    :param tree: dependency tree
    :returns: JSON representation of the tree

    """
    tree = tree.sort()
    return json.dumps(
        [{"package": k.as_dict(), "dependencies": [v.as_dict() for v in vs]} for k, vs in tree.items()],
        indent=4,
    )


__all__ = [
    "render_json",
]
