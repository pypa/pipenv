from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipenv.patched.pip._vendor.pkg_resources import DistInfoDistribution


def get_installed_distributions(
    local_only: bool = False,  # noqa: FBT001, FBT002
    user_only: bool = False,  # noqa: FBT001, FBT002
) -> list[DistInfoDistribution]:
    try:
        from pipenv.patched.pip._internal.metadata import pkg_resources
    except ImportError:
        # For backward compatibility with python ver. 2.7 and pip
        # version 20.3.4 (the latest pip version that works with python
        # version 2.7)
        from pipenv.patched.pip._internal.utils import misc

        return misc.get_installed_distributions(  # type: ignore[no-any-return,attr-defined]
            local_only=local_only,
            user_only=user_only,
        )

    else:
        dists = pkg_resources.Environment.from_paths(None).iter_installed_distributions(
            local_only=local_only,
            skip=(),
            user_only=user_only,
        )
        return [d._dist for d in dists]  # type: ignore[attr-defined] # noqa: SLF001


__all__ = [
    "get_installed_distributions",
]
