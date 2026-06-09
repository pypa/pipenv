"""
A :class:`importlib.metadata.Distribution` look-alike backed by name/version/edges instead of an on-disk package.

Both the ``from-index`` resolver and the ``from-lock`` reader produce package graphs that were never installed, yet
the existing :class:`~pipdeptree._models.PackageDAG` and every renderer expect real ``Distribution`` objects. This
shared adapter bridges that gap: each child is rendered as a PEP 508 ``Requires-Dist`` string so the unchanged
:meth:`pipdeptree._models.package.DistPackage.requires` rebuilds exact edges with no renderer changes.
"""

from __future__ import annotations

from email.message import Message
from importlib.metadata import Distribution
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import os
    from email.message import Message as MessageType


class SyntheticDistribution(Distribution):
    """A Distribution backed by resolved name/version/edges rather than an on-disk package."""

    def __init__(self, name: str, version: str, children: tuple[str, ...]) -> None:
        self._metadata = Message()
        self._metadata["Name"] = name
        self._metadata["Version"] = version
        # children are already requirement strings (e.g. "foo==1.2.3" or bare "foo"), so the existing
        # DistPackage.requires() reconstructs exact edges with no renderer changes.
        for child in children:
            self._metadata["Requires-Dist"] = child

    @property
    def metadata(self) -> MessageType:
        return self._metadata

    @property
    def version(self) -> str:
        return self._metadata["Version"]

    def read_text(self, filename: str) -> str | None:  # noqa: ARG002, PLR6301
        return None

    def locate_file(self, path: str | os.PathLike[str]) -> Path:  # noqa: PLR6301
        return Path(path)


__all__ = [
    "SyntheticDistribution",
]
