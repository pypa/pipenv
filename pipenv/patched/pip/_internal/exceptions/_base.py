"""Base pip exception classes."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pipenv.patched.pip._vendor.rich.text import Text

if TYPE_CHECKING:
    from pipenv.patched.pip._vendor.rich.console import Console, ConsoleOptions, RenderResult


def _is_kebab_case(s: str) -> bool:
    return re.match(r"^[a-z]+(-[a-z]+)*$", s) is not None


def _prefix_with_indent(
    s: Text | str,
    console: Console,
    *,
    prefix: str,
    indent: str,
) -> Text:
    if isinstance(s, Text):
        text = s
    else:
        text = console.render_str(s)

    return console.render_str(prefix, overflow="ignore") + console.render_str(
        f"\n{indent}", overflow="ignore"
    ).join(text.split(allow_blank=True))


class PipError(Exception):
    """The base pip error."""


class InstallationError(PipError):
    """General exception during installation"""


class BlockedImportError(InstallationError):
    """An import blocked after wheel installation started.

    ImportError would be swallowed by codec lookup and cache the codec as missing.
    """


class DiagnosticPipError(PipError):
    """An error, that presents diagnostic information to the user.

    This contains a bunch of logic, to enable pretty presentation of our error
    messages. Each error gets a unique reference. Each error can also include
    additional context, a hint and/or a note -- which are presented with the
    main error message in a consistent style.

    This is adapted from the error output styling in `sphinx-theme-builder`.
    """

    reference: str

    def __init__(
        self,
        *,
        kind: Literal["error", "warning"] = "error",
        reference: str | None = None,
        message: str | Text,
        context: str | Text | None,
        hint_stmt: str | Text | None,
        note_stmt: str | Text | None = None,
        link: str | None = None,
    ) -> None:
        # Ensure a proper reference is provided.
        if reference is None:
            assert hasattr(self, "reference"), "error reference not provided!"
            reference = self.reference
        assert _is_kebab_case(reference), "error reference must be kebab-case!"

        self.kind = kind
        self.reference = reference

        self.message = message
        self.context = context

        self.note_stmt = note_stmt
        self.hint_stmt = hint_stmt

        self.link = link

        super().__init__(f"<{self.__class__.__name__}: {self.reference}>")

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}("
            f"reference={self.reference!r}, "
            f"message={self.message!r}, "
            f"context={self.context!r}, "
            f"note_stmt={self.note_stmt!r}, "
            f"hint_stmt={self.hint_stmt!r}"
            ")>"
        )

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        colour = "red" if self.kind == "error" else "yellow"

        yield f"[{colour} bold]{self.kind}[/]: [bold]{self.reference}[/]"
        yield ""

        if not options.ascii_only:
            # Present the main message, with relevant context indented.
            if self.context is not None:
                yield _prefix_with_indent(
                    self.message,
                    console,
                    prefix=f"[{colour}]×[/] ",
                    indent=f"[{colour}]│[/] ",
                )
                yield _prefix_with_indent(
                    self.context,
                    console,
                    prefix=f"[{colour}]╰─>[/] ",
                    indent=f"[{colour}]   [/] ",
                )
            else:
                yield _prefix_with_indent(
                    self.message,
                    console,
                    prefix="[red]×[/] ",
                    indent="  ",
                )
        else:
            yield self.message
            if self.context is not None:
                yield ""
                yield self.context

        if self.note_stmt is not None or self.hint_stmt is not None:
            yield ""

        if self.note_stmt is not None:
            yield _prefix_with_indent(
                self.note_stmt,
                console,
                prefix="[magenta bold]note[/]: ",
                indent="      ",
            )
        if self.hint_stmt is not None:
            yield _prefix_with_indent(
                self.hint_stmt,
                console,
                prefix="[cyan bold]hint[/]: ",
                indent="      ",
            )

        if self.link is not None:
            yield ""
            yield f"Link: {self.link}"
