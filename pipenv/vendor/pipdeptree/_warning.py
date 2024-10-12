from __future__ import annotations

import sys
from enum import Enum
from typing import Callable

WarningType = Enum("WarningType", ["SILENCE", "SUPPRESS", "FAIL"])


class WarningPrinter:
    """Non-thread safe class that handles printing warning logic."""

    def __init__(self, warning_type: WarningType = WarningType.SUPPRESS) -> None:
        self._warning_type = warning_type
        self._has_warned = False

    @property
    def warning_type(self) -> WarningType:
        return self._warning_type

    @warning_type.setter
    def warning_type(self, new_warning_type: WarningType) -> None:
        self._warning_type = new_warning_type

    def should_warn(self) -> bool:
        return self._warning_type != WarningType.SILENCE

    def has_warned_with_failure(self) -> bool:
        return self._has_warned and self.warning_type == WarningType.FAIL

    def print_single_line(self, line: str) -> None:
        self._has_warned = True
        print(line, file=sys.stderr)  # noqa: T201

    def print_multi_line(self, summary: str, print_func: Callable[[], None], ignore_fail: bool = False) -> None:  # noqa: FBT001, FBT002
        """
        Print a multi-line warning, delegating most of the printing logic to the caller.

        :param summary: a summary of the warning
        :param print_func: a callback that the caller passes that performs most of the multi-line printing
        :param ignore_fail: if True, this warning won't be a fail when `self.warning_type == WarningType.FAIL`
        """
        print(f"Warning!!! {summary}:", file=sys.stderr)  # noqa: T201
        print_func()
        if ignore_fail:
            print("NOTE: This warning isn't a failure warning.", file=sys.stderr)  # noqa: T201
        else:
            self._has_warned = True
        print("-" * 72, file=sys.stderr)  # noqa: T201


_shared_warning_printer = WarningPrinter()


def get_warning_printer() -> WarningPrinter:
    """Shared warning printer, representing a module-level singleton object."""
    return _shared_warning_printer


__all__ = ["WarningPrinter", "get_warning_printer"]
