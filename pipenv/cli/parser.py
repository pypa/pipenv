"""Custom ArgumentParser for pipenv with Rich-formatted help and 'did you mean' suggestions."""

import argparse
import difflib
import sys

from pipenv.utils import console, err


class PipenvArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser with Rich help formatting and typo suggestions."""

    def __init__(self, *args, **kwargs):
        self._pipenv_subparsers_action = None
        super().__init__(*args, **kwargs)

    def format_help(self):
        """Override to produce Rich-formatted help output."""
        return super().format_help()

    def print_help(self, file=None):
        """Print Rich-formatted help to console."""
        from pipenv.utils.display import format_help

        help_text = self.format_help()
        console.print(format_help(help_text))

    def error(self, message):
        """Override error to add 'did you mean' suggestions and Rich formatting."""
        # Try to detect misspelled subcommands
        if self._pipenv_subparsers_action is not None:
            choices = list(self._pipenv_subparsers_action.choices.keys())
            # Check for "invalid choice" pattern
            for arg in sys.argv[1:]:
                if arg.startswith("-"):
                    continue
                matches = difflib.get_close_matches(arg, choices, n=3, cutoff=0.5)
                if matches and arg not in choices:
                    suggestions = ", ".join(matches)
                    message += f"\n\nDid you mean one of these?\n    {suggestions}"
                    break

        err.print("Usage: pipenv [OPTIONS] COMMAND [ARGS]...")
        err.print(f"\nError: {message}", style="red")
        err.print("\nTry 'pipenv -h' for help.")
        sys.exit(2)

    def add_subparsers(self, **kwargs):
        """Track the subparsers action for 'did you mean' suggestions."""
        action = super().add_subparsers(**kwargs)
        self._pipenv_subparsers_action = action
        return action

    def exit(self, status=0, message=None):
        if message:
            err.print(message)
        sys.exit(status)


class PipenvSubcommandParser(argparse.ArgumentParser):
    """Subcommand parser with Rich help output."""

    def print_help(self, file=None):
        help_text = self.format_help()
        console.print(help_text)

    def error(self, message):
        err.print(f"Usage: {self.format_usage().strip()}")
        err.print(f"\nError: {message}", style="red")
        err.print(f"\nTry '{self.prog} -h' for help.")
        sys.exit(2)

    def exit(self, status=0, message=None):
        if message:
            err.print(message)
        sys.exit(status)


def confirm(prompt, default=True):
    """Simple confirm prompt replacement for click.confirm."""
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        response = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not response:
        return default
    return response in ("y", "yes")
