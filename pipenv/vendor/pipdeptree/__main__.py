"""The main entry point used for CLI."""
from __future__ import annotations

import os
import sys
from typing import Sequence

pardir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# for finding pipdeptree itself
sys.path.append(pardir)
# for finding stuff in vendor and patched
sys.path.append(os.path.dirname(os.path.dirname(pardir)))

from pipenv.vendor.pipdeptree._cli import get_options
from pipenv.vendor.pipdeptree._discovery import get_installed_distributions
from pipenv.vendor.pipdeptree._models import PackageDAG
from pipenv.vendor.pipdeptree._non_host import handle_non_host_target
from pipenv.vendor.pipdeptree._render import render
from pipenv.vendor.pipdeptree._validate import validate


def main(args: Sequence[str] | None = None) -> None | int:
    """CLI - The main function called as entry point."""
    options = get_options(args)
    result = handle_non_host_target(options)
    if result is not None:
        return result

    pkgs = get_installed_distributions(local_only=options.local_only, user_only=options.user_only)
    tree = PackageDAG.from_pkgs(pkgs)
    is_text_output = not any([options.json, options.json_tree, options.output_format])

    return_code = validate(options, is_text_output, tree)

    # Reverse the tree (if applicable) before filtering, thus ensuring, that the filter will be applied on ReverseTree
    if options.reverse:
        tree = tree.reverse()

    show_only = options.packages.split(",") if options.packages else None
    exclude = set(options.exclude.split(",")) if options.exclude else None

    if show_only is not None or exclude is not None:
        try:
            tree = tree.filter_nodes(show_only, exclude)
        except ValueError as e:
            if options.warn in ("suppress", "fail"):
                print(e, file=sys.stderr)  # noqa: T201
                return_code |= 1 if options.warn == "fail" else 0
            return return_code

    render(options, tree)

    return return_code


if __name__ == "__main__":
    sys.exit(main())
