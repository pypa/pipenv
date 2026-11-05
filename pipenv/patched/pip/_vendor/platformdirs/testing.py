"""Test helpers that keep platformdirs away from the real user and system directories."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pipenv.patched.pip._vendor import platformdirs
from pipenv.patched.pip._vendor.platformdirs.api import PlatformDirsABC

if TYPE_CHECKING:
    import os
    from collections.abc import Generator

_APP_KINDS: Final[frozenset[str]] = frozenset({
    "user_data",
    "site_data",
    "user_config",
    "site_config",
    "user_cache",
    "site_cache",
    "user_state",
    "site_state",
    "user_log",
    "site_log",
    "user_runtime",
    "site_runtime",
    "user_preference",
})


@contextmanager
def isolated_dirs(root: str | os.PathLike[str]) -> Generator[Path, None, None]:
    """Resolve every directory of :data:`~platformdirs.PlatformDirs` under ``root`` while the context is active.

    Each kind maps to ``<root>/<kind>``, where ``kind`` is the property name without ``_dir``, such as ``user_config``.
    The data, config, cache, state, log, runtime and preference kinds append ``appname`` and ``version``, so
    ``PlatformDirs("app", version="1.0").user_config_path`` becomes ``<root>/user_config/app/1.0``. Every thread of the
    current process sees the change, and subprocesses do not.

    :param root: directory that holds the redirected directories

    :returns: ``root`` as a :class:`~pathlib.Path`

    """
    base = Path(root)
    patches = {
        name: _redirect(
            base / (kind := name.removesuffix("_dir")), app=kind in _APP_KINDS, private=kind.startswith("user_")
        )
        for name in PlatformDirsABC.__abstractmethods__
    }
    # Unix and macOS build the site lists from search paths; the base versions derive them from the redirected dirs.
    patches |= {
        name: value
        for name, value in vars(PlatformDirsABC).items()
        if name.startswith("_site_") and name.endswith("_dirs")
    }
    cls = platformdirs.PlatformDirs
    saved = {name: vars(cls)[name] for name in patches if name in vars(cls)}
    for name, value in patches.items():
        setattr(cls, name, value)
    try:
        yield base
    finally:
        for name in patches:
            if name in saved:
                setattr(cls, name, saved[name])
            else:
                delattr(cls, name)


def _redirect(path: Path, *, app: bool, private: bool) -> property:
    def resolve(self: PlatformDirsABC) -> str:
        return self._append_app_name_and_version(str(path), private=private) if app else str(path)

    return property(resolve)


__all__ = [
    "isolated_dirs",
]
