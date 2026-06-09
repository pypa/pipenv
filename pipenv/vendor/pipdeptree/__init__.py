"""
Programmatic access to pipdeptree.

The :func:`render` function lets you obtain the dependency tree as a string from
within Python -- e.g. a Jupyter or JupyterLite cell -- without going through the
command line or capturing stdout yourself::

    import pipenv.vendor.pipdeptree as pipdeptree

    print(pipdeptree.render())  # text tree, defaults
    pipdeptree.render(output_format="json")  # JSON string
    pipdeptree.render(packages="rich", reverse=True)  # filtered + reversed

In a Jupyter or JupyterLite notebook cell, the default (``text``) render also
displays as a Mermaid dependency diagram (with an HTML/text fallback) via the
rich-display protocol, while its string value stays the plain text tree.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from html import escape
from math import inf
from typing import TYPE_CHECKING

from pipenv.vendor.pipdeptree import _render
from pipenv.vendor.pipdeptree.__main__ import _FilterError, build_tree
from pipenv.vendor.pipdeptree._cli import SUMMARY_RENDER_FORMATS, get_options
from pipenv.vendor.pipdeptree._render.summary import summary_html
from pipenv.vendor.pipdeptree._warning import WarningType, get_warning_printer

from .version import __version__

if TYPE_CHECKING:
    from collections.abc import Container

    from pipenv.vendor.pipdeptree._cli import Options
    from pipenv.vendor.pipdeptree._models import PackageDAG

__all__ = ["__version__", "render"]

_BINARY_GRAPHVIZ_FORMATS = frozenset({"png", "svg", "pdf", "jpeg", "jpg", "gif", "bmp", "ps"})
_FORMAT_FLAGS: dict[str, list[str]] = {
    "text": [],
    "json": ["--json"],
    "json-tree": ["--json-tree"],
    "mermaid": ["--mermaid"],
    "dot": ["--graph-output", "dot"],
}


def render(  # noqa: PLR0913
    *,
    packages: str | None = None,
    exclude: str | None = None,
    output_format: str = "text",
    summary: bool = False,
    reverse: bool = False,
    depth: float = inf,
    extras: bool | str = False,
    local_only: bool = False,
    user_only: bool = False,
    python: str | None = None,
    encoding: str = "utf-8",
    warn: str = "silence",
) -> str:
    """
    Render the dependency tree of an environment and return it as a string.

    :param packages: comma separated allow-list of packages to show (wildcards allowed)
    :param exclude: comma separated deny-list of packages to hide (wildcards allowed)
    :param output_format: one of ``text``, ``json``, ``json-tree``, ``mermaid`` or ``dot`` (Graphviz source); binary
        Graphviz formats (png, svg, ...) cannot be returned as text and raise :class:`ValueError`. With
        ``summary=True`` it instead selects the summary style and must be ``text``, ``rich`` or ``json``
    :param summary: return a one-block health report of the environment rather than the tree; in a notebook the
        ``text`` style additionally displays as an HTML table
    :param reverse: list sub-dependencies with the packages that require them
    :param depth: limit the depth of the tree (text output only)
    :param extras: include optional (extras) dependencies in the tree; ``True`` is shorthand for ``"explicit"``
    :param local_only: only show packages installed in the local virtual environment
    :param user_only: only show packages installed in the user site
    :param python: interpreter whose environment to inspect; defaults to the current one
    :param encoding: encoding used for the text renderer's box-drawing characters
    :param warn: warning control (``silence``, ``suppress`` or ``fail``); defaults to ``silence`` so notebooks are not
        polluted with stderr output
    :raises ValueError: for an unknown ``output_format`` or a binary Graphviz format
    :return: the rendered dependency tree

    The result is always a :class:`str` whose value is the rendering for the requested ``output_format``, so
    ``print``, slicing, ``==`` and other string operations behave exactly as before. For the default ``text`` format
    the result additionally implements Jupyter's rich-display protocol (:meth:`_repr_mimebundle_`), so a notebook cell
    shows a Mermaid dependency diagram with an HTML ``<pre>`` and plain-text fallback. Other formats (``json``,
    ``json-tree``, ``mermaid``, ``dot``) return a plain :class:`str` with no rich display, so their source/JSON shows
    as-is.
    """
    if summary and output_format not in SUMMARY_RENDER_FORMATS:
        allowed = ", ".join(sorted(SUMMARY_RENDER_FORMATS))
        msg = f"summary output_format must be one of {allowed}; got {output_format!r}"
        raise ValueError(msg)

    format_argv = ["--summary", "--output", output_format] if summary else _format_flags(output_format)
    argv = ["--warn", warn, "--encoding", encoding, *format_argv]
    for flag, value in (("--packages", packages), ("--exclude", exclude), ("--python", python)):
        if value is not None:
            argv += [flag, value]
    if depth != inf:
        argv += ["--depth", str(int(depth))]
    if extras:
        # Bare --extras means the "explicit" mode; the boolean keeps the historical call signature working.
        argv += ["--extras", extras if isinstance(extras, str) else "explicit"]
    for flag, enabled in (
        ("--reverse", reverse),
        ("--local-only", local_only),
        ("--user-only", user_only),
    ):
        if enabled:
            argv.append(flag)
    options = get_options(argv)

    # Share the global warning printer so validation warnings honor ``warn`` too and default to silence, keeping
    # notebooks free of stderr noise.
    get_warning_printer().warning_type = WarningType.from_str(options.warn)

    try:
        tree = build_tree(options)
    except _FilterError:
        return ""

    text = _render_to_str(options, tree)
    return _finalize(text, argv=argv, tree=tree, output_format=output_format, summary=summary)


def _finalize(text: str, *, argv: list[str], tree: PackageDAG, output_format: str, summary: bool) -> str:
    if summary:
        # The aggregate report has no tree diagram; the text style instead displays as an HTML table in a notebook.
        return _SummaryResult(text, html=summary_html(tree)) if output_format == "text" else text
    if output_format != "text":
        # Non-text formats (JSON, Mermaid source, Graphviz source) are returned as plain strings so they display
        # verbatim in a notebook instead of being reinterpreted as a diagram.
        return text

    # Reuse the already-discovered tree to also produce a Mermaid diagram for the rich notebook display.
    mermaid_options = get_options([*argv, "--mermaid"])
    mermaid = _render_to_str(mermaid_options, tree)
    return _RenderResult(text, mermaid=mermaid)


def _render_to_str(options: Options, tree: PackageDAG) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _render.render(options, tree)
    return buffer.getvalue()


class _RenderResult(str):  # noqa: FURB189  # Must stay a real ``str`` so isinstance/print/slicing keep working.
    """A ``str`` whose value is the text tree but that also renders as a Mermaid diagram in a notebook cell."""

    __slots__ = ("_mermaid",)

    _mermaid: str

    def __new__(cls, text: str, *, mermaid: str) -> _RenderResult:  # noqa: PYI034  # str subclass, concrete type is fine.
        self = super().__new__(cls, text)
        self._mermaid = mermaid
        return self

    def _repr_mimebundle_(  # noqa: PLW3201  # Jupyter rich-display protocol method, not a Python dunder.
        self,
        include: Container[str] | None = None,
        exclude: Container[str] | None = None,  # noqa: ARG002
    ) -> dict[str, str]:
        bundle = {
            "text/vnd.mermaid": self._mermaid,
            "text/html": f"<pre>{escape(str(self))}</pre>",
            "text/plain": str(self),
        }
        if include is not None:
            bundle = {key: value for key, value in bundle.items() if key in include}
        return bundle


class _SummaryResult(str):  # noqa: FURB189  # Must stay a real ``str`` so isinstance/print/slicing keep working.
    """A ``str`` whose value is the text summary but that also renders as an HTML table in a notebook cell."""

    __slots__ = ("_html",)

    _html: str

    def __new__(cls, text: str, *, html: str) -> _SummaryResult:  # noqa: PYI034  # str subclass, concrete type is fine.
        self = super().__new__(cls, text)
        self._html = html
        return self

    def _repr_mimebundle_(  # noqa: PLW3201  # Jupyter rich-display protocol method, not a Python dunder.
        self,
        include: Container[str] | None = None,
        exclude: Container[str] | None = None,  # noqa: ARG002
    ) -> dict[str, str]:
        bundle = {"text/html": self._html, "text/plain": str(self)}
        if include is not None:
            bundle = {key: value for key, value in bundle.items() if key in include}
        return bundle


def _format_flags(output_format: str) -> list[str]:
    if output_format in _FORMAT_FLAGS:
        return _FORMAT_FLAGS[output_format]
    if output_format in _BINARY_GRAPHVIZ_FORMATS:
        msg = (
            "binary Graphviz formats cannot be returned as a string; use output_format='dot' for the Graphviz source, "
            "or run the pipdeptree CLI for binary output"
        )
        raise ValueError(msg)
    msg = f"unknown output_format {output_format!r}; expected one of {', '.join(_FORMAT_FLAGS)}"
    raise ValueError(msg)
