"""pytest plugin that provides the ``platformdirs_isolated`` fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def platformdirs_isolated(tmp_path: Path) -> Iterator[Path]:
    """Redirect every platformdirs directory under ``tmp_path`` with :func:`~platformdirs.testing.isolated_dirs`.

    :returns: the isolation root, ``tmp_path``

    """
    # pytest imports every installed pytest11 plugin at startup, so load the helper only for tests that ask for it.
    from pipenv.patched.pip._vendor.platformdirs.testing import isolated_dirs  # ruff:ignore[import-outside-top-level]

    with isolated_dirs(tmp_path) as root:
        yield root


__all__ = [
    "platformdirs_isolated",
]
