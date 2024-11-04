"""The main entry point used for CLI."""

from __future__ import annotations

import os
import sys
from typing import Sequence

pardir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# for finding pipdeptree itself, vendor, and patched
sys.path = [pardir, os.path.dirname(os.path.dirname(pardir))] + sys.path

from pipenv.vendor.pipdeptree._cli import get_options
from pipenv.vendor.pipdeptree._detect_env import detect_active_interpreter
from pipenv.vendor.pipdeptree._discovery import get_installed_distributions
from pipenv.vendor.pipdeptree._models import PackageDAG
from pipenv.vendor.pipdeptree._render import render
from pipenv.vendor.pipdeptree._validate import validate
from pipenv.vendor.pipdeptree._warning import (
    WarningPrinter,
    WarningType,
    get_warning_printer,
)


def main(args: Sequence[str] | None = None) -> None | int:
    """CLI - The main function called as entry point."""
    options = get_options(args)

    # Warnings are only enabled when using text output.
    is_text_output = not any([options.json, options.json_tree, options.output_format])
    if not is_text_output:
        options.warn = WarningType.SILENCE
    warning_printer = get_warning_printer()
    warning_printer.warning_type = options.warn

    if options.python == "auto":
        resolved_path = detect_active_interpreter()
        options.python = resolved_path
        print(f"(resolved python: {resolved_path})", file=sys.stderr)  # noqa: T201

    pkgs = get_installed_distributions(
        interpreter=options.python,
        local_only=options.local_only,
        user_only=options.user_only,
    )
    tree = PackageDAG.from_pkgs(pkgs)

    validate(tree)

    # Reverse the tree (if applicable) before filtering, thus ensuring, that the filter will be applied on ReverseTree
    if options.reverse:
        tree = tree.reverse()

    show_only = options.packages.split(",") if options.packages else None
    exclude = set(options.exclude.split(",")) if options.exclude else None

    if show_only is not None or exclude is not None:
        try:
            tree = tree.filter_nodes(show_only, exclude)
        except ValueError as e:
            if warning_printer.should_warn():
                warning_printer.print_single_line(str(e))
            return _determine_return_code(warning_printer)

    render(options, tree)

    return _determine_return_code(warning_printer)


def _determine_return_code(warning_printer: WarningPrinter) -> int:
    return 1 if warning_printer.has_warned_with_failure() else 0


if __name__ == "__main__":
    sys.exit(main())
