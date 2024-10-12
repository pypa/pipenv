from __future__ import annotations

import enum
import sys
from argparse import Action, ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from typing import Any, Sequence, cast

from pipenv.vendor.pipdeptree._warning import WarningType

from .version import __version__


class Options(Namespace):
    freeze: bool
    python: str
    all: bool
    local_only: bool
    user_only: bool
    warn: WarningType
    reverse: bool
    packages: str
    exclude: str
    json: bool
    json_tree: bool
    mermaid: bool
    output_format: str | None
    depth: float
    encoding: str
    license: bool


class _Formatter(ArgumentDefaultsHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=22, width=240)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Dependency tree of the installed python packages", formatter_class=_Formatter)
    parser.add_argument("-v", "--version", action="version", version=f"{__version__}")
    parser.add_argument(
        "-w",
        "--warn",
        dest="warn",
        type=WarningType,
        nargs="?",
        default="suppress",
        action=EnumAction,
        help=(
            "warning control: suppress will show warnings but return 0 whether or not they are present; silence will "
            "not show warnings at all and  always return 0; fail will show warnings and  return 1 if any are present"
        ),
    )

    select = parser.add_argument_group(title="select", description="choose what to render")
    select.add_argument(
        "--python",
        default=sys.executable,
        help=(
            'Python interpreter to inspect. With "auto", it attempts to detect your virtual environment and fails if'
            " it can't."
        ),
    )
    select.add_argument(
        "-p",
        "--packages",
        help="comma separated list of packages to show - wildcards are supported, like 'somepackage.*'",
        metavar="P",
    )
    select.add_argument(
        "-e",
        "--exclude",
        help="comma separated list of packages to not show - wildcards are supported, like 'somepackage.*'. "
        "(cannot combine with -p or -a)",
        metavar="P",
    )
    select.add_argument("-a", "--all", action="store_true", help="list all deps at top level")

    scope = select.add_mutually_exclusive_group()
    scope.add_argument(
        "-l",
        "--local-only",
        action="store_true",
        help="if in a virtualenv that has global access do not show globally installed packages",
    )
    scope.add_argument("-u", "--user-only", action="store_true", help="only show installations in the user site dir")

    render = parser.add_argument_group(
        title="render",
        description="choose how to render the dependency tree (by default will use text mode)",
    )
    render.add_argument("-f", "--freeze", action="store_true", help="print names so as to write freeze files")
    render.add_argument(
        "--encoding",
        dest="encoding_type",
        default=sys.stdout.encoding,
        help="the encoding to use when writing to the output",
        metavar="E",
    )
    render.add_argument(
        "-d",
        "--depth",
        type=lambda x: int(x) if x.isdigit() and (int(x) >= 0) else parser.error("Depth must be a number that is >= 0"),
        default=float("inf"),
        help="limit the depth of the tree (text render only)",
        metavar="D",
    )
    render.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        default=False,
        help=(
            "render the dependency tree in the reverse fashion ie. the sub-dependencies are listed with the list of "
            "packages that need them under them"
        ),
    )
    render.add_argument(
        "--license",
        action="store_true",
        help="list the license(s) of a package (text render only)",
    )

    render_type = render.add_mutually_exclusive_group()
    render_type.add_argument(
        "-j",
        "--json",
        action="store_true",
        default=False,
        help="raw JSON - this will yield output that may be used by external tools",
    )
    render_type.add_argument(
        "--json-tree",
        action="store_true",
        default=False,
        help="nested JSON - mimics the text format layout",
    )
    render_type.add_argument(
        "--mermaid",
        action="store_true",
        default=False,
        help="https://mermaid.js.org flow diagram",
    )
    render_type.add_argument(
        "--graph-output",
        metavar="FMT",
        dest="output_format",
        help="Graphviz rendering with the value being the graphviz output e.g.: dot, jpeg, pdf, png, svg",
    )
    return parser


def get_options(args: Sequence[str] | None) -> Options:
    parser = build_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.exclude and (parsed_args.all or parsed_args.packages):
        return parser.error("cannot use --exclude with --packages or --all")
    if parsed_args.license and parsed_args.freeze:
        return parser.error("cannot use --license with --freeze")

    return cast(Options, parsed_args)


class EnumAction(Action):
    """
    Generic action that exists to convert a string into a Enum value that is then added into a `Namespace` object.

    This custom action exists because argparse doesn't have support for enums.

    References
    ----------
    - https://github.com/python/cpython/issues/69247#issuecomment-1308082792
    - https://docs.python.org/3/library/argparse.html#action-classes

    """

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        option_strings: list[str],
        dest: str,
        nargs: str | None = None,
        const: Any | None = None,
        default: Any | None = None,
        type: Any | None = None,  # noqa: A002
        choices: Any | None = None,
        required: bool = False,  # noqa: FBT001, FBT002
        help: str | None = None,  # noqa: A002
        metavar: str | None = None,
    ) -> None:
        if not type or not issubclass(type, enum.Enum):
            msg = "type must be a subclass of Enum"
            raise TypeError(msg)
        if not isinstance(default, str):
            msg = "default must be defined with a string value"
            raise TypeError(msg)

        choices = tuple(e.name.lower() for e in type)
        if default not in choices:
            msg = "default value should be among the enum choices"
            raise ValueError(msg)

        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=nargs,
            const=const,
            default=default,
            type=None,  # We return None here so that we default to str.
            choices=choices,
            required=required,
            help=help,
            metavar=metavar,
        )

        self._enum = type

    def __call__(
        self,
        parser: ArgumentParser,  # noqa: ARG002
        namespace: Namespace,
        value: Any,
        option_string: str | None = None,  # noqa: ARG002
    ) -> None:
        value = value or self.default
        value = next(e for e in self._enum if e.name.lower() == value)
        setattr(namespace, self.dest, value)


__all__ = [
    "Options",
    "get_options",
]
