from __future__ import annotations

import sys
from collections.abc import Iterable
from types import TracebackType
from typing import TYPE_CHECKING

from pipenv.patched.pip._internal.build_env.base import BuildEnvironment

if TYPE_CHECKING:
    from pipenv.patched.pip._internal.req.req_install import InstallRequirement


class NoOpBuildEnvironment(BuildEnvironment):
    """A no-op drop-in replacement for BuildEnvironment"""

    def __init__(self) -> None:
        self.python_executable = sys.executable

    def __enter__(self) -> None:
        pass

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    def cleanup(self) -> None:
        pass

    def install_requirements(
        self,
        requirements: Iterable[str],
        prefix_as_string: str,
        *,
        kind: str,
        for_req: InstallRequirement | None = None,
    ) -> None:
        raise NotImplementedError()
