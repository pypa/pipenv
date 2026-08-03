from __future__ import annotations

import abc
from collections.abc import Iterable
from contextlib import AbstractContextManager as ContextManager
from typing import TYPE_CHECKING, Literal, Protocol

from pipenv.patched.pip._vendor.packaging.version import Version

from pipenv.patched.pip._internal.locations import get_scheme
from pipenv.patched.pip._internal.metadata import get_default_environment, get_environment
from pipenv.patched.pip._internal.utils.packaging import get_requirement

if TYPE_CHECKING:
    from pipenv.patched.pip._internal.req.req_install import InstallRequirement


BuildIsolationMode = Literal["off", "virtual", "venv"]


def _dedup(a: str, b: str) -> tuple[str] | tuple[str, str]:
    return (a, b) if a != b else (a,)


class Prefix:
    # TODO: simplify this data model when the legacy subprocess installer is removed
    def __init__(self, path: str, *, venv_executable: str | None = None) -> None:
        self.path = path
        self.setup = False
        scheme = get_scheme("", prefix=path)
        self.bin_dir = scheme.scripts
        self.lib_dirs = _dedup(scheme.purelib, scheme.platlib)
        self.venv_executable = venv_executable


class BuildEnvironmentInstaller(Protocol):
    """
    Interface for installing build dependencies into an isolated build
    environment.
    """

    def install(
        self,
        requirements: Iterable[str],
        prefix: Prefix,
        *,
        kind: str,
        for_req: InstallRequirement | None,
    ) -> None: ...


class BuildEnvironment(ContextManager[None], metaclass=abc.ABCMeta):
    """Creates and manages an isolated environment to install build deps"""

    lib_dirs: list[str]
    python_executable: str

    @abc.abstractmethod
    def __init__(self, installer: BuildEnvironmentInstaller): ...

    def check_requirements(
        self, reqs: Iterable[str]
    ) -> tuple[set[tuple[str, str]], set[str]]:
        """Return 2 sets:
        - conflicting requirements: set of (installed, wanted) reqs tuples
        - missing requirements: set of reqs
        """
        missing = set()
        conflicting = set()
        if reqs:
            env = (
                get_environment(self.lib_dirs)
                if hasattr(self, "lib_dirs")
                else get_default_environment()
            )
            for req_str in reqs:
                req = get_requirement(req_str)
                # We're explicitly evaluating with an empty extra value, since build
                # environments are not provided any mechanism to select specific extras.
                if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                    continue
                dist = env.get_distribution(req.name)
                if not dist:
                    missing.add(req_str)
                    continue
                if isinstance(dist.version, Version):
                    installed_req_str = f"{req.name}=={dist.version}"
                else:
                    installed_req_str = f"{req.name}==={dist.version}"
                if not req.specifier.contains(dist.version, prereleases=True):
                    conflicting.add((installed_req_str, req_str))
                # FIXME: Consider direct URL?
        return conflicting, missing

    @abc.abstractmethod
    def install_requirements(
        self,
        requirements: Iterable[str],
        prefix_as_string: str,
        *,
        kind: str,
        for_req: InstallRequirement | None = None,
    ) -> None: ...
