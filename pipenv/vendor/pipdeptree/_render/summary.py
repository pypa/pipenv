"""
Render a single-block health summary of a dependency tree.

The report has two tiers. Graph-structural metrics (counts, depth, cycles) derive purely from the DAG edges and are
available for every command. The installed-environment tier (missing/conflicting deps, licenses, requires-python,
size) reads real distribution metadata and on-disk files, which the ``from-index``/``from-lock`` synthetic trees do
not carry; in that ``resolved`` mode those metrics are reported as unavailable rather than a misleading zero.

The same computed metrics drive three presentation styles -- aligned ``text``, a ``rich`` table, and ``json`` -- plus
an HTML table for notebook display, all built from the one shared row list.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from html import escape
from itertools import chain
from typing import TYPE_CHECKING

from pipenv.vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
from pipenv.vendor.packaging.version import InvalidVersion, Version

from pipenv.vendor.pipdeptree._computed import ComputedValues
from pipenv.vendor.pipdeptree._models.package import Package
from pipenv.vendor.pipdeptree._validate import conflicting_deps, cyclic_deps

if TYPE_CHECKING:
    from pipenv.vendor.pipdeptree._models import PackageDAG
    from pipenv.vendor.pipdeptree._models.package import RenderMode

# Weak and strong copyleft families worth flagging for compliance review; matched case-insensitively as substrings.
_COPYLEFT_MARKERS = ("AGPL", "LGPL", "GPL", "MPL", "EUPL", "CDDL")
_RESOLVED_NOTE = "n/a (resolved from index/lock - package metadata unavailable)"


@dataclass
class _Summary:
    total_packages: int
    direct_dependencies: int
    transitive_dependencies: int
    max_depth: int
    cyclic_dependencies: int
    resolved: bool
    missing_dependencies: int | None = None
    conflicting_packages: int | None = None
    conflicting_edges: int | None = None
    licenses: dict[str, int] | None = None
    unknown_licenses: int | None = None
    copyleft_licenses: bool | None = None
    min_requires_python: str | None = None
    total_size: str | None = None
    total_size_raw: int | None = None


def render_summary(tree: PackageDAG, *, mode: RenderMode = "default", style: str = "text") -> None:
    """
    Print a one-block summary of the dependency tree.

    :param tree: the package tree
    :param mode: ``"resolved"`` (from-index/from-lock) drops the installed-environment metrics that synthetic
        distributions cannot supply
    :param style: presentation style -- ``"text"`` (aligned), ``"rich"`` (table) or ``"json"``
    """
    summary = _collect(tree, resolved=mode == "resolved")
    if style == "json":
        print(_as_json(summary))  # noqa: T201
    elif style == "rich":
        _as_rich(summary)
    else:
        print(_as_text(summary))  # noqa: T201


def summary_html(tree: PackageDAG, *, mode: RenderMode = "default") -> str:
    """Return the summary as an HTML ``<table>`` for notebook rich display."""
    return _as_html(_collect(tree, resolved=mode == "resolved"))


def _collect(tree: PackageDAG, *, resolved: bool) -> _Summary:
    child_keys = {str(r.key) for r in chain.from_iterable(tree.values())}
    total = len(tree)
    direct = sum(1 for p in tree if p.key not in child_keys)
    summary = _Summary(
        total_packages=total,
        direct_dependencies=direct,
        transitive_dependencies=total - direct,
        max_depth=_max_depth(tree, child_keys),
        cyclic_dependencies=len(cyclic_deps(tree)),
        resolved=resolved,
    )
    if resolved:
        return summary

    conflicts = conflicting_deps(tree)
    licenses = _license_breakdown(tree)
    total_bytes = sum(ComputedValues(p.key, tree).size_raw for p in tree)
    summary.missing_dependencies = len({r.key for reqs in tree.values() for r in reqs if r.is_missing})
    summary.conflicting_packages = len(conflicts)
    summary.conflicting_edges = sum(len(reqs) for reqs in conflicts.values())
    summary.licenses = licenses
    summary.unknown_licenses = licenses.get(Package.UNKNOWN_LICENSE_STR, 0)
    summary.copyleft_licenses = _has_copyleft(licenses)
    summary.min_requires_python = _min_requires_python(tree)
    summary.total_size = ComputedValues.format_size(total_bytes)
    summary.total_size_raw = total_bytes
    return summary


def _max_depth(tree: PackageDAG, child_keys: set[str]) -> int:
    # Longest dependency chain measured in packages. Start from roots (the longest simple path in a DAG always begins
    # at one); if every node is inside a cycle there are no roots, so fall back to all nodes. The on-path guard keeps
    # cyclic graphs from recursing forever and yields the longest *simple* path.
    roots = [p.key for p in tree if p.key not in child_keys] or [p.key for p in tree]

    def longest(key: str, on_path: frozenset[str]) -> int:
        children = tree.get_children(key)
        deeper = on_path | {key}
        return 1 + max((longest(c.key, deeper) for c in children if c.key not in deeper), default=0)

    return max((longest(root, frozenset()) for root in roots), default=0)


def _license_breakdown(tree: PackageDAG) -> dict[str, int]:
    return dict(sorted(Counter(pkg.licenses() for pkg in tree).items()))


def _has_copyleft(licenses: dict[str, int]) -> bool:
    return any(marker in label.upper() for label in licenses for marker in _COPYLEFT_MARKERS)


def _min_requires_python(tree: PackageDAG) -> str:
    floors: list[Version] = []
    for pkg in tree:
        raw = pkg.get_metadata("Requires-Python")
        if not isinstance(raw, str) or raw == Package.NA:
            continue
        try:
            specifier = SpecifierSet(raw)
        except InvalidSpecifier:
            continue
        for spec in specifier:
            if spec.operator in {">=", ">", "=="}:
                try:
                    floors.append(Version(spec.version))
                except InvalidVersion:
                    continue
    return str(max(floors)) if floors else "n/a"


def _rows(summary: _Summary) -> list[tuple[str, str]]:
    rows = [
        ("total packages", str(summary.total_packages)),
        ("direct dependencies", str(summary.direct_dependencies)),
        ("transitive dependencies", str(summary.transitive_dependencies)),
        ("max depth", str(summary.max_depth)),
        ("cyclic dependencies", str(summary.cyclic_dependencies)),
    ]
    if summary.resolved:
        labels = ("missing dependencies", "conflicting dependencies", "licenses")
        rows.extend((label, _RESOLVED_NOTE) for label in labels)
        return rows
    rows.extend([
        ("missing dependencies", str(summary.missing_dependencies)),
        ("conflicting dependencies", f"{summary.conflicting_packages} ({summary.conflicting_edges} edges)"),
        ("licenses", _format_licenses(summary.licenses)),
        ("unknown licenses", str(summary.unknown_licenses)),
        ("copyleft licenses", "yes" if summary.copyleft_licenses else "no"),
        ("min requires-python", str(summary.min_requires_python)),
        ("total size", str(summary.total_size)),
    ])
    return rows


def _format_licenses(licenses: dict[str, int] | None) -> str:
    return ", ".join(f"{label}: {count}" for label, count in licenses.items()) if licenses else "none"


def _as_text(summary: _Summary) -> str:
    rows = _rows(summary)
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label + ':':<{width + 1}} {value}" for label, value in rows)


def _as_rich(summary: _Summary) -> None:
    try:
        from rich.console import Console  # noqa: PLC0415
        from rich.table import Table  # noqa: PLC0415
    except ImportError as exc:
        print(  # noqa: T201
            "rich is not available, but necessary for the output option. Please install it.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    table = Table(title="environment summary", show_header=False, title_style="bold")
    table.add_column("metric", style="bold cyan", no_wrap=True)
    table.add_column("value")
    for label, value in _rows(summary):
        table.add_row(label, value, style="dim" if value == _RESOLVED_NOTE else None)
    Console().print(table)


def _as_html(summary: _Summary) -> str:
    body = "".join(f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>" for label, value in _rows(summary))
    return f"<table>\n<tr><th>metric</th><th>value</th></tr>\n{body}\n</table>"


def _as_json(summary: _Summary) -> str:
    data: dict[str, object] = {
        "total_packages": summary.total_packages,
        "direct_dependencies": summary.direct_dependencies,
        "transitive_dependencies": summary.transitive_dependencies,
        "max_depth": summary.max_depth,
        "cyclic_dependencies": summary.cyclic_dependencies,
    }
    if not summary.resolved:
        data.update(
            missing_dependencies=summary.missing_dependencies,
            conflicting_dependencies={"packages": summary.conflicting_packages, "edges": summary.conflicting_edges},
            licenses={
                "breakdown": summary.licenses,
                "unknown": summary.unknown_licenses,
                "copyleft": summary.copyleft_licenses,
            },
            min_requires_python=summary.min_requires_python,
            total_size=summary.total_size,
            total_size_raw=summary.total_size_raw,
        )
    return json.dumps(data, indent=2)


__all__ = [
    "render_summary",
    "summary_html",
]
