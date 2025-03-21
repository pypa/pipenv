from __future__ import annotations

import argparse
import sys

from . import __version__
from .pythonfinder import Finder


def colorize(text: str, color: str | None = None, bold: bool = False) -> str:
    """
    Simple function to colorize text for terminal output.
    """
    colors = {
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
    }

    reset = "\033[0m"
    bold_code = "\033[1m" if bold else ""
    color_code = colors.get(color, "")

    if not color_code and not bold:
        return text

    return f"{bold_code}{color_code}{text}{reset}"


def create_parser() -> argparse.ArgumentParser:
    """
    Create the argument parser for the CLI.
    """
    parser = argparse.ArgumentParser(description="Find and manage Python installations.")

    parser.add_argument("--find", help="Find a specific python version.")

    parser.add_argument("--which", help="Run the which command.")

    parser.add_argument(
        "--findall", action="store_true", help="Find all python versions."
    )

    parser.add_argument(
        "--ignore-unsupported",
        "--no-unsupported",
        action="store_true",
        default=True,
        help="Ignore unsupported python versions.",
    )

    parser.add_argument(
        "--version", action="store_true", help="Show the version and exit."
    )

    return parser


def cli(args: list[str] | None = None) -> int:
    """
    Main CLI function.

    Args:
        args: Command line arguments. If None, sys.argv[1:] is used.

    Returns:
        Exit code.
    """
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    # Show version and exit
    if parsed_args.version:
        print(
            f"{colorize('PythonFinder', bold=True)} {colorize(__version__, color='yellow')}"
        )
        return 0

    # Create finder
    finder = Finder(ignore_unsupported=parsed_args.ignore_unsupported)

    # Find all Python versions
    if parsed_args.findall:
        versions = [v for v in finder.find_all_python_versions()]
        if versions:
            print(colorize("Found python at the following locations:", color="green"))
            for v in versions:
                py = v
                comes_from = getattr(py, "comes_from", None)
                if comes_from is not None:
                    comes_from_path = getattr(comes_from, "path", v.path)
                else:
                    comes_from_path = v.path
                print(
                    colorize(
                        f"{py.name or 'python'}: {py.version_str} ({py.architecture or 'unknown'}) @ {comes_from_path}",
                        color="yellow",
                    )
                )
            return 0
        else:
            print(
                colorize(
                    "ERROR: No valid python versions found! Check your path and try again.",
                    color="red",
                )
            )
            return 1

    # Find a specific Python version
    if parsed_args.find:
        print(
            colorize(f"Searching for python: {parsed_args.find.strip()}", color="yellow")
        )
        found = finder.find_python_version(parsed_args.find.strip())
        if found:
            py = found
            comes_from = getattr(py, "comes_from", None)
            if comes_from is not None:
                comes_from_path = getattr(comes_from, "path", found.path)
            else:
                comes_from_path = found.path

            print(colorize("Found python at the following locations:", color="green"))
            print(
                colorize(
                    f"{py.name or 'python'}: {py.version_str} ({py.architecture or 'unknown'}) @ {comes_from_path}",
                    color="yellow",
                )
            )
            return 0
        else:
            print(colorize("Failed to find matching executable...", color="yellow"))
            return 1

    # Which command
    elif parsed_args.which:
        found = finder.which(parsed_args.which.strip())
        if found:
            print(colorize(f"Found Executable: {found}", color="white"))
            return 0
        else:
            print(colorize("Failed to find matching executable...", color="yellow"))
            return 1

    # No command provided
    else:
        print(colorize("Please provide a command", color="red"))
        return 1


if __name__ == "__main__":
    sys.exit(cli())
