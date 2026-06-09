from __future__ import annotations

import sys
import warnings
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, ArgumentTypeError, Namespace
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast, get_args

from pipenv.vendor.pipdeptree._computed import ComputedValues
from pipenv.vendor.pipdeptree._models.dag import ExtrasMode

from .version import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pipenv.vendor.pipdeptree._models import PackageDAG


class Options(Namespace):
    freeze: bool
    python: str | None
    path: list[str]
    command: str | None
    requirement: list[str]
    requirements: list[str] | None
    pyproject: list[str] | None
    index_url: str | None
    extra_index_url: list[str] | None
    lock: str | None
    all: bool
    local_only: bool
    user_only: bool
    warn: str
    reverse: bool
    packages: str
    exclude: str
    exclude_dependencies: bool
    json: bool
    json_tree: bool
    mermaid: bool
    graphviz_format: str | None
    output_format: str
    summary: bool
    extras: ExtrasMode
    depth: float
    encoding: str
    license: bool
    metadata: list[str]
    computed: list[str]
    context: RenderContext


@dataclass
class RenderContext:
    """Bundles metadata and computed fields that augment package display."""

    metadata: list[str] = field(default_factory=list)
    computed: list[str] = field(default_factory=list)
    full_tree: PackageDAG | None = field(default=None, repr=False, compare=False)

    @property
    def active(self) -> bool:
        return bool(self.metadata or self.computed)

    def build_node_extra_label(self, key: str, tree: PackageDAG, separator: str) -> str:
        if not self.active:
            return ""
        parts: list[str] = []
        if self.metadata:
            parts.extend(self._get_metadata_label_parts(key, self.metadata, tree))
        if self.computed:
            computed = ComputedValues(key, tree, self.full_tree)
            for field_key, field_value in computed.as_dict(self.computed).items():
                parts.append(f"{field_key}: {field_value}")
        return separator.join(parts)

    def with_metadata(self, metadata: list[str]) -> RenderContext:
        """Return a copy with a different metadata field list."""
        return RenderContext(metadata=metadata, computed=self.computed, full_tree=self.full_tree)

    @staticmethod
    def _get_metadata_label_parts(key: str, fields: list[str], tree: PackageDAG) -> list[str]:
        for pkg in tree:
            if pkg.key == key:
                return pkg.get_metadata_values(fields)
        return []


# NOTE: graphviz-* has been intentionally left out. Users of this var should handle it separately.
ALLOWED_RENDER_FORMATS = ["freeze", "json", "json-tree", "mermaid", "rich", "text"]
# Tree-specific renderers (mermaid, graphviz, freeze, json-tree) have no meaning for the aggregate summary, so
# --summary is restricted to the styles that can present a flat report.
SUMMARY_RENDER_FORMATS = frozenset({"text", "rich", "json"})
ALLOWED_COMPUTED_FIELDS = frozenset({"size", "size-raw", "unique-deps-count", "unique-deps-names", "unique-deps-size"})


class _Formatter(ArgumentDefaultsHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=22, width=240)


def build_parser() -> ArgumentParser:
    # The render/select flags shared by the default command and the from-index subcommand are defined once on a
    # parent parser; both the top-level parser and the from-index subparser inherit them via parents=[...], so the
    # flags stay single-sourced and the top-level CLI keeps its existing behavior.
    render_parent = _build_render_parent()

    parser = ArgumentParser(
        prog="pipdeptree",
        description="Dependency tree of the installed python packages",
        formatter_class=_Formatter,
        parents=[render_parent],
    )
    parser.add_argument("-v", "--version", action="version", version=f"{__version__}")

    select = parser.add_argument_group(title="select", description="choose what to render")
    select.add_argument(
        "--python",
        default=None,
        help=(
            "Python interpreter to inspect. By default it auto-detects your active virtual environment (venv, "
            "virtualenv, conda, or poetry), falling back to the interpreter running pipdeptree when none is found. "
            'With "auto" it detects the active virtual environment and fails if it can\'t.'
        ),
    )
    select.add_argument(
        "--path",
        help="passes a path used to restrict where packages should be looked for (can be used multiple times)",
        action="append",
    )

    scope = select.add_mutually_exclusive_group()
    scope.add_argument(
        "-l",
        "--local-only",
        action="store_true",
        help="if in a virtualenv that has global access do not show globally installed packages",
    )
    scope.add_argument("-u", "--user-only", action="store_true", help="only show installations in the user site dir")

    _add_installed_metadata_arguments(parser)

    sub = parser.add_subparsers(dest="command")
    from_index = sub.add_parser(
        "from-index",
        aliases=["i"],
        parents=[render_parent],
        formatter_class=_Formatter,
        help="resolve requirements by querying a package index and render their tree (needs the index extra)",
        description=(
            "Resolve the given requirements by querying the package index (PyPI) and render the dependency tree "
            "without installing or inspecting the environment. Positional arguments are inline PEP 508 requirements; "
            "files are supplied explicitly via --requirements and --pyproject. A lone --pyproject is resolved "
            "natively (honoring [tool.nab]); otherwise every source merges into one resolve. Needs the optional "
            "index resolver (pip install pipdeptree[index])."
        ),
    )
    from_index.add_argument(
        "requirement",
        nargs="*",
        metavar="REQUIREMENT",
        help="inline PEP 508 requirement to resolve, like a pip install argument; repeatable",
    )
    # argparse records the alias actually typed in ``command``; pin it to the canonical name so __main__ and
    # get_options can branch on a single value regardless of whether the user typed "from-index" or "i".
    from_index.set_defaults(command="from-index")
    from_index.add_argument(
        "--requirements",
        action="append",
        metavar="FILE",
        help="a requirements.txt or .in style file (nested -r, -c constraints, markers and comments supported); "
        "repeatable",
    )
    from_index.add_argument(
        "--pyproject",
        action="append",
        metavar="FILE",
        help="a pyproject.toml handed natively to the resolver when it is the only source; repeatable",
    )
    from_index.add_argument(
        "--index-url",
        metavar="URL",
        default=None,
        help="primary package index to resolve against, replacing PyPI; falls back to PIP_INDEX_URL then "
        "UV_INDEX_URL when unset, and defaults to PyPI",
    )
    from_index.add_argument(
        "--extra-index-url",
        action="append",
        metavar="URL",
        default=None,
        help="additional package index to resolve against, repeatable; falls back to PIP_EXTRA_INDEX_URL then "
        "UV_EXTRA_INDEX_URL (whitespace separated) when unset",
    )

    from_lock = sub.add_parser(
        "from-lock",
        aliases=["l"],
        parents=[render_parent],
        formatter_class=_Formatter,
        help="render the dependency tree from a PEP 751 pylock.toml (offline; no index/network needed)",
        description=(
            "Read a PEP 751 lock file (pylock.toml) and render its dependency tree. The lock is already resolved, so "
            "this is fully offline -- no package index, network, or extra is required."
        ),
    )
    from_lock.add_argument("lock", metavar="PYLOCK", help="path to a PEP 751 pylock.toml lock file")
    from_lock.set_defaults(command="from-lock")

    # Bare ``pipdeptree`` does not visit the subparser, so seed defaults for its attributes to keep Options total. The
    # installed-only display options (license/metadata/computed) are not exposed on the subparsers, so seed them too:
    # this keeps Options total whichever path argparse takes, so get_options can post-process it always.
    parser.set_defaults(
        command=None,
        requirement=[],
        requirements=None,
        pyproject=None,
        index_url=None,
        extra_index_url=None,
        lock=None,
        license=False,
        metadata="",
        computed="",
    )
    return parser


def _build_render_parent() -> ArgumentParser:
    parent = ArgumentParser(add_help=False)
    parent.add_argument(
        "-w",
        "--warn",
        dest="warn",
        type=str,
        choices=["silence", "suppress", "fail"],
        default="suppress",
        help=(
            "warning control: suppress will show warnings but return 0 whether or not they are present; silence will "
            "not show warnings at all and  always return 0; fail will show warnings and  return 1 if any are present"
        ),
    )
    _add_render_arguments(parent)
    return parent


def _add_render_arguments(parser: ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--packages",
        help=(
            "comma separated list of packages to show - wildcards are supported, like 'somepackage.*'. append an "
            "extras spec to also show a package's extra dependencies, like ``somepackage[extra1,extra2]``"
        ),
        metavar="P",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        help="comma separated list of packages to not show - wildcards are supported, like 'somepackage.*'. "
        "(cannot combine with -p or -a)",
        metavar="P",
    )
    parser.add_argument(
        "--exclude-dependencies",
        help="used along with --exclude to also exclude dependencies of packages",
        action="store_true",
    )
    parser.add_argument(
        "-x",
        "--extras",
        nargs="?",
        const="explicit",
        choices=get_args(ExtrasMode),
        default="explicit",
        help=(
            "which optional (extras) dependencies to include: 'explicit' (default) shows extras requested via "
            "name[extra], including transitively; 'active' also shows extras whose dependencies are all "
            "installed; 'none' shows none. Bare --extras means 'explicit'"
        ),
    )
    parser.add_argument(
        "-f", "--freeze", action="store_true", help="(Deprecated, use -o) print names so as to write freeze files"
    )
    parser.add_argument(
        "--encoding",
        dest="encoding",
        default=sys.stdout.encoding,
        help="the encoding to use when writing to the output",
        metavar="E",
    )
    parser.add_argument(
        "-a", "--all", action="store_true", help="list all deps at top level (text, rich, and freeze render only)"
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=_positive_int,
        default=float("inf"),
        help="limit the depth of the tree (text, rich, freeze, and graphviz render only)",
        metavar="D",
    )
    parser.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        default=False,
        help=(
            "render the dependency tree in the reverse fashion ie. the sub-dependencies are listed with the list of "
            "packages that need them under them"
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        default=False,
        help="render a one-block health report of the tree instead of the tree itself; combine with -o text "
        "(default), rich, or json. Composes with from-index/from-lock",
    )
    render_type = parser.add_mutually_exclusive_group()
    render_type.add_argument(
        "-j",
        "--json",
        action="store_true",
        default=False,
        help="(Deprecated, use -o) raw JSON - this will yield output that may be used by external tools",
    )
    render_type.add_argument(
        "--json-tree",
        action="store_true",
        default=False,
        help="(Deprecated, use -o) nested JSON - mimics the text format layout",
    )
    render_type.add_argument(
        "--mermaid",
        action="store_true",
        default=False,
        help="(Deprecated, use -o) https://mermaid.js.org flow diagram",
    )
    render_type.add_argument(
        "--graph-output",
        metavar="FMT",
        dest="graphviz_format",
        help="(Deprecated, use -o) Graphviz rendering with the value being the graphviz output e.g.:\
              dot, jpeg, pdf, png, svg",
    )
    render_type.add_argument(
        "-o",
        "--output",
        metavar="FMT",
        dest="output_format",
        type=_validate_output_format,
        default="text",
        help=f"specify how to render the tree; supported formats: {', '.join(ALLOWED_RENDER_FORMATS)}, or graphviz-*\
            (e.g. graphviz-png, graphviz-dot)",
    )


def _add_installed_metadata_arguments(parser: ArgumentParser) -> None:
    # These read state of already-installed packages (METADATA file contents, on-disk file sizes), so they only make
    # sense for the default command that inspects an environment. The from-index subcommand renders resolver output for
    # packages that are never installed, so it intentionally omits them.
    parser.add_argument(
        "--license",
        action="store_true",
        help="(Deprecated, use --metadata license) list the license(s) of a package",
    )
    parser.add_argument(
        "-m",
        "--metadata",
        default="",
        help="comma separated list of metadata fields to display from the package METADATA file"
        " (e.g. license,summary,author,home-page,requires-python)",
        metavar="M",
    )
    parser.add_argument(
        "-c",
        "--computed",
        default="",
        help=f"comma separated list of computed fields to display: {', '.join(sorted(ALLOWED_COMPUTED_FIELDS))}",
        metavar="C",
    )


def _positive_int(value: str) -> int:
    if value.isdigit() and int(value) >= 0:
        return int(value)
    msg = "Depth must be a number that is >= 0"
    raise ArgumentTypeError(msg)


def get_options(args: Sequence[str] | None) -> Options:
    parser = build_parser()
    parsed_args = parser.parse_args(args)
    options = cast("Options", parsed_args)

    options.output_format = _handle_legacy_render_options(options)
    raw_metadata: str = cast("str", options.metadata)
    raw_computed: str = cast("str", options.computed)
    options.metadata = (
        list(dict.fromkeys(f.strip() for f in raw_metadata.split(",") if f.strip())) if raw_metadata else []
    )
    options.computed = [f.strip() for f in raw_computed.split(",") if f.strip()] if raw_computed else []

    # ``parser.error`` is ``NoReturn`` (it raises ``SystemExit``), so these are terminal guards, not returns.
    if options.license:
        if "license" in options.metadata:
            parser.error("cannot use --license with --metadata license")
        warnings.warn("--license is deprecated, use --metadata license instead", DeprecationWarning, stacklevel=1)
        options.metadata = ["license", *options.metadata]

    if invalid := set(options.computed) - ALLOWED_COMPUTED_FIELDS:
        allowed = ", ".join(sorted(ALLOWED_COMPUTED_FIELDS))
        parser.error(f"invalid --computed values: {', '.join(sorted(invalid))}. Allowed: {allowed}")

    options.context = RenderContext(metadata=options.metadata, computed=options.computed)

    if options.summary and options.output_format not in SUMMARY_RENDER_FORMATS:
        allowed = ", ".join(sorted(SUMMARY_RENDER_FORMATS))
        parser.error(f"--summary supports only -o {allowed} (got {options.output_format})")

    if options.command == "from-index" and not (options.requirement or options.requirements or options.pyproject):
        parser.error("from-index needs at least one REQUIREMENT, --requirements FILE, or --pyproject FILE")
    if options.exclude_dependencies and not options.exclude:
        parser.error("must use --exclude-dependencies with --exclude")
    if options.path and (options.local_only or options.user_only):
        parser.error("cannot use --path with --user-only or --local-only")

    return options


def _handle_legacy_render_options(options: Options) -> str:
    if options.freeze:
        return "freeze"
    if options.json:
        return "json"
    if options.json_tree:
        return "json-tree"
    if options.mermaid:
        return "mermaid"
    if options.graphviz_format:
        return f"graphviz-{options.graphviz_format}"

    return options.output_format


def _validate_output_format(value: str) -> str:
    if value in ALLOWED_RENDER_FORMATS:
        return value
    if value.startswith("graphviz-"):
        return value
    msg = f'"{value}" is not a known output format. Must be one of {", ".join(ALLOWED_RENDER_FORMATS)}, or graphviz-*'
    raise ArgumentTypeError(msg)


def parse_packages(value: str | None) -> tuple[list[str], dict[str, set[str]]]:
    """
    Split a ``--packages`` value into bare name patterns and the extras requested per entry.

    An entry like ``foo[bar,baz]`` yields the name pattern ``foo`` and the extras ``{bar, baz}``; plain entries
    carry no extras. The extras are matched against installed package names later, so wildcard patterns such as
    ``foo*[bar]`` apply to every package matching ``foo*``.
    """
    if not value:
        return [], {}
    names: list[str] = []
    requested_extras: dict[str, set[str]] = {}
    for raw in _split_entries(value):
        if not (entry := raw.strip()):
            continue
        name, extras = _split_extras(entry)
        names.append(name)
        if extras:
            requested_extras.setdefault(name, set()).update(extras)
    return names, requested_extras


def _split_entries(value: str) -> list[str]:
    # Split on commas, but not commas inside an ``[...]`` extras spec, so ``foo[a,b],bar`` yields two entries.
    entries: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            entries.append(value[start:index])
            start = index + 1
    entries.append(value[start:])
    return entries


def _split_extras(entry: str) -> tuple[str, set[str]]:
    if not entry.endswith("]") or "[" not in entry:
        return entry, set()
    name, _, extras_part = entry[:-1].partition("[")
    return name, {extra.strip() for extra in extras_part.split(",") if extra.strip()}


__all__ = [
    "Options",
    "get_options",
    "parse_packages",
]
