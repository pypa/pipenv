from __future__ import annotations

import pathlib
from dataclasses import dataclass
from functools import cached_property
from importlib.metadata import distribution
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pipenv.vendor.pipdeptree._models import PackageDAG


@dataclass
class ComputedValues:
    key: str
    tree: PackageDAG
    full_tree: PackageDAG | None = None

    def as_dict(self, fields: Sequence[str]) -> dict[str, Any]:
        return {
            (attr := field.replace("-", "_")): getattr(self, attr)
            for field in fields
            if hasattr(self, field.replace("-", "_"))
        }

    def format_display(self, fields: Sequence[str], exclude: frozenset[str] = frozenset()) -> list[str]:
        result: list[str] = []
        for field in fields:
            if field in exclude:
                continue
            if field == "size":
                result.append(self.size)
            elif field == "size-raw":
                result.append(str(self.size_raw))
            elif field == "unique-deps-count" and self.unique_deps_count:
                result.append(f"{self.unique_deps_count} unique deps")
            elif field == "unique-deps-names" and self.unique_deps_names:
                result.append(f"unique: {' | '.join(self.unique_deps_names)}")
            elif field == "unique-deps-size" and self.unique_deps_size != "0 B":
                result.append(f"unique size: {self.unique_deps_size}")
        return result

    @cached_property
    def size(self) -> str:
        return self.format_size(self.size_bytes) if self.size_bytes is not None else "0 B"

    @cached_property
    def size_raw(self) -> int:
        return self.size_bytes or 0

    @cached_property
    def size_bytes(self) -> int | None:
        dist = distribution(self.key)
        if not (files := dist.files):
            return None
        return sum(self._file_size(str(dist.locate_file(f))) for f in files)

    @staticmethod
    def _file_size(path: str) -> int:
        try:
            return pathlib.Path(path).stat().st_size
        except OSError:
            return 0

    @staticmethod
    def format_size(size_bytes: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024 or unit == "GB":
                return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
            size_bytes /= 1024  # ty: ignore[invalid-assignment]
        return f"{size_bytes:.1f} GB"  # pragma: no cover

    @cached_property
    def unique_deps_count(self) -> int:
        return len(self.unique_deps)

    @cached_property
    def unique_deps_names(self) -> list[str]:
        return sorted(self.unique_deps)

    @cached_property
    def unique_deps_size(self) -> str:
        total = sum(ComputedValues(dep, self.tree, self.full_tree).size_raw for dep in self.unique_deps)
        return self.format_size(total)

    @cached_property
    def unique_deps(self) -> set[str]:
        tree = self.full_tree or self.tree
        own_deps = self._transitive_deps(self.key, tree)
        removed = {self.key}
        changed = True
        while changed:
            changed = False
            reachable: set[str] = set()
            for pkg in tree:
                if pkg.key not in removed:
                    reachable |= self._transitive_deps(pkg.key, tree, exclude=removed)
            if newly_orphaned := own_deps - reachable - removed:
                removed |= newly_orphaned
                changed = True
        return removed - {self.key}

    @staticmethod
    def _transitive_deps(key: str, tree: PackageDAG, exclude: set[str] | None = None) -> set[str]:
        result: set[str] = set()
        excluded = exclude or set()
        stack = [c.key for c in tree.get_children(key) if c.key not in excluded]
        while stack:
            if (dep := stack.pop()) not in result:
                result.add(dep)
                stack.extend(c.key for c in tree.get_children(dep) if c.key not in excluded)
        return result


__all__ = [
    "ComputedValues",
]
