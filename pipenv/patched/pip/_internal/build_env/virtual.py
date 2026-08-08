from __future__ import annotations

import os
import site
import sys
import textwrap
from collections import OrderedDict
from collections.abc import Iterable
from types import TracebackType
from typing import TYPE_CHECKING

from pipenv.patched.pip._internal.build_env.base import (
    BuildEnvironment,
    BuildEnvironmentInstaller,
    Prefix,
)
from pipenv.patched.pip._internal.utils.temp_dir import TempDirectory, tempdir_kinds

if TYPE_CHECKING:
    from pipenv.patched.pip._internal.req.req_install import InstallRequirement


def get_system_sitepackages() -> set[str]:
    """Get system site packages, as a normalized set of strings."""
    system_sites = site.getsitepackages()
    return {os.path.normcase(path) for path in system_sites}


class VirtualBuildEnvironment(BuildEnvironment):
    """Legacy build environment implementation.

    Patches sys.path and uses sitecustomize.py to isolate Python processes. It has
    known bugs and weird edge cases, but it exists as a fallback for platforms where
    the venv module is unavailable or dysfunctional.
    """

    def __init__(self, installer: BuildEnvironmentInstaller) -> None:
        self.python_executable = sys.executable
        self.installer = installer
        temp_dir = TempDirectory(kind=tempdir_kinds.BUILD_ENV, globally_managed=True)

        self._prefixes = OrderedDict(
            (name, Prefix(os.path.join(temp_dir.path, name)))
            for name in ("normal", "overlay")
        )

        self._bin_dirs: list[str] = []
        self.lib_dirs: list[str] = []
        for prefix in reversed(list(self._prefixes.values())):
            self._bin_dirs.append(prefix.bin_dir)
            self.lib_dirs.extend(prefix.lib_dirs)

        # Customize site to:
        # - ensure .pth files are honored
        # - prevent access to system site packages
        system_sites = get_system_sitepackages()

        self._site_dir = os.path.join(temp_dir.path, "site")
        if not os.path.exists(self._site_dir):
            os.mkdir(self._site_dir)
        with open(
            os.path.join(self._site_dir, "sitecustomize.py"), "w", encoding="utf-8"
        ) as fp:
            fp.write(textwrap.dedent("""
                import os, site, sys

                # First, discover all system-sites related paths.
                original_sys_path = sys.path[:]
                # Clear sys.path so addsitedir() will add system site paths and paths
                # added by contained .pth files to sys.path reliably. This is necessary
                # since Python 3.15, which notably no longer re-executes .pth files for
                # known paths.
                sys.path = []
                known_paths = set()
                for path in {system_sites!r}:
                    site.addsitedir(path, known_paths=known_paths)
                system_paths = set(os.path.normcase(path) for path in sys.path)

                # Drop discovered system-sites related paths.
                original_sys_path = [
                    path for path in original_sys_path
                    if os.path.normcase(path) not in system_paths
                ]
                sys.path = original_sys_path

                # Second, add lib directories.
                # ensuring .pth file are processed.
                for path in {lib_dirs!r}:
                    assert not path in sys.path
                    site.addsitedir(path)
                """).format(system_sites=system_sites, lib_dirs=self.lib_dirs))

    def __enter__(self) -> None:
        self._save_env = {
            name: os.environ.get(name, None)
            for name in ("PATH", "PYTHONNOUSERSITE", "PYTHONPATH")
        }

        path = self._bin_dirs[:]
        old_path = self._save_env["PATH"]
        if old_path:
            path.extend(old_path.split(os.pathsep))

        pythonpath = [self._site_dir]

        os.environ.update(
            {
                "PATH": os.pathsep.join(path),
                "PYTHONNOUSERSITE": "1",
                "PYTHONPATH": os.pathsep.join(pythonpath),
            }
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        for varname, old_value in self._save_env.items():
            if old_value is None:
                os.environ.pop(varname, None)
            else:
                os.environ[varname] = old_value

    def install_requirements(
        self,
        requirements: Iterable[str],
        prefix_as_string: str,
        *,
        kind: str,
        for_req: InstallRequirement | None = None,
    ) -> None:
        prefix = self._prefixes[prefix_as_string]
        assert not prefix.setup
        prefix.setup = True
        if not requirements:
            return
        self.installer.install(requirements, prefix, kind=kind, for_req=for_req)
