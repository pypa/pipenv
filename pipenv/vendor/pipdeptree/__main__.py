"""The main entry point used for CLI."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

pardir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# for finding pipdeptree itself
sys.path.append(pardir)
# for finding stuff in vendor and patched
sys.path.append(os.path.dirname(os.path.dirname(pardir)))

from pipenv.vendor.pipdeptree._cli import Options, get_options
from pipenv.vendor.pipdeptree._detect_env import detect_active_interpreter
from pipenv.vendor.pipdeptree._discovery import InterpreterQueryError, get_installed_distributions
from pipenv.vendor.pipdeptree._models import PackageDAG
from pipenv.vendor.pipdeptree._models.dag import IncludeExcludeOverlapError, IncludePatternNotFoundError
from pipenv.vendor.pipdeptree._render import render
from pipenv.vendor.pipdeptree._validate import validate
from pipenv.vendor.pipdeptree._warning import WarningPrinter, WarningType, get_warning_printer

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(args: Sequence[str] | None = None) -> int | None:
    """CLI - The main function called as entry point."""
    options = get_options(args)

    # Warnings are only enabled when using text output.
    if not _is_text_output(options):
        options.warn = "silence"
    warning_printer = get_warning_printer()
    warning_printer.warning_type = WarningType.from_str(options.warn)

    if options.python == "auto":
        resolved_path = detect_active_interpreter()
        options.python = resolved_path
        print(f"(resolved python: {resolved_path})", file=sys.stderr)  # noqa: T201

    try:
        pkgs = get_installed_distributions(
            interpreter=options.python,
            supplied_paths=options.path or None,
            local_only=options.local_only,
            user_only=options.user_only,
        )
    except InterpreterQueryError as e:
        print(f"Failed to query custom interpreter: {e}", file=sys.stderr)  # noqa: T201
        return 1

    tree = PackageDAG.from_pkgs(pkgs)

    validate(tree)

    # Reverse the tree (if applicable) before filtering, thus ensuring, that the filter will be applied on ReverseTree
    if options.reverse:
        tree = tree.reverse()

    include = options.packages.split(",") if options.packages else None
    exclude = set(options.exclude.split(",")) if options.exclude else None

    if include is not None or exclude is not None:
        try:
            tree = tree.filter_nodes(include, exclude, exclude_deps=options.exclude_dependencies)
        except IncludeExcludeOverlapError:
            print("Cannot have --packages and --exclude contain the same entries", file=sys.stderr)  # noqa: T201
            return 1
        except IncludePatternNotFoundError as e:
            if warning_printer.should_warn():
                warning_printer.print_single_line(str(e))
            return _determine_return_code(warning_printer)

    render(options, tree)

    return _determine_return_code(warning_printer)


def _is_text_output(options: Options) -> bool:
    if any([options.json, options.json_tree, options.graphviz_format, options.mermaid]):
        return False
    return options.output_format in {"freeze", "text"}


def _determine_return_code(warning_printer: WarningPrinter) -> int:
    return 1 if warning_printer.has_warned_with_failure() else 0


if __name__ == "__main__":
    sys.exit(main())
