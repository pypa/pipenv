from __future__ import annotations

import os
import sys
import sysconfig
from collections.abc import Iterable
from types import TracebackType
from typing import TYPE_CHECKING

from pipenv.patched.pip._internal.build_env.base import (
    BuildEnvironment,
    BuildEnvironmentInstaller,
    Prefix,
)
from pipenv.patched.pip._internal.exceptions import VenvCreationError, VenvImportError
from pipenv.patched.pip._internal.utils.temp_dir import TempDirectory, tempdir_kinds

if TYPE_CHECKING:
    from pipenv.patched.pip._internal.req.req_install import InstallRequirement


def _get_venv_path_from_sysconfig(name: str, env_dir: str) -> str:
    vars = {
        "base": env_dir,
        "platbase": env_dir,
    }
    return sysconfig.get_path(name, scheme="venv", vars=vars)


class VenvBuildEnvironment(BuildEnvironment):
    """A venv-based build environment."""

    def __init__(self, installer: BuildEnvironmentInstaller) -> None:
        # We defer this import because certain distributions of Python do not include
        # a functional venv out of the box.
        try:
            import venv
        except ImportError:
            raise VenvImportError

        self._env_path = TempDirectory(
            kind=tempdir_kinds.BUILD_ENV, globally_managed=True
        ).path
        # Use symlinks to support relocatable Python installations on POSIX, including
        # python-build-standalone. This matches upstream venv CLI's behaviour.
        env = venv.EnvBuilder(symlinks=(os.name != "nt"))
        try:
            context = env.ensure_directories(self._env_path)
            env.create(self._env_path)
        except OSError as e:
            raise VenvCreationError(str(e))

        if sys.version_info >= (3, 12):
            # The context object was only documented in Python 3.12
            self.lib_dirs = [context.lib_path]
            self._bin_path = context.bin_path
        elif sys.version_info[:2] == (3, 11):
            # On Python 3.11, we can use sysconfig.
            self.lib_dirs = [_get_venv_path_from_sysconfig("purelib", self._env_path)]
            self._bin_path = _get_venv_path_from_sysconfig("scripts", self._env_path)
        else:
            # Otherwise, we need to manually construct all the paths... sigh.
            if sys.platform == "win32":
                libpath = os.path.join(self._env_path, "Lib", "site-packages")
            else:
                python = "pypy" if sys.implementation.name == "pypy" else "python"
                libpath = os.path.join(
                    self._env_path,
                    "lib",
                    f"{python}{sys.version_info.major}.{sys.version_info.minor}",
                    "site-packages",
                )
            self.lib_dirs = [libpath]
            # Same reasoning for try-except as for python_executable below.
            try:
                self._bin_path = context.bin_path
            except AttributeError:
                scripts_dir = "Scripts" if os.name == "nt" else "bin"
                self._bin_path = os.path.join(self._env_path, scripts_dir)

        # There are enough ways trying to construct the Python executable path can go
        # wrong that we're better off assuming that the context object has the right
        # attributes, and only when they don't exist do we try to guess.
        #
        # These attributes seem to exist in every CPython version after 3.10.1 and
        # are documented to exist on 3.12 and higher.
        try:
            self.python_executable = context.env_exec_cmd
        except AttributeError:
            try:
                self.python_executable = context.env_exe
            except AttributeError:
                executable_name = "python.exe" if os.name == "nt" else "python"
                self.python_executable = os.path.join(self._bin_path, executable_name)

        self._save_env: dict[str, str | None] = {}
        self._installer = installer

        if not os.path.exists(self.python_executable):
            # This error is only likely on Windows due to interference from AV software.
            raise VenvCreationError(
                f"Python executable failed to copy to {self.python_executable}"
            )

    def __enter__(self) -> None:
        # We want backend calls to be able to use binaries installed as if this
        # virtual environment was "activated".
        self._save_env = {
            name: os.environ.get(name, None) for name in ("PATH", "PYTHONPATH")
        }

        new_path = [self._bin_path]
        if old_path := self._save_env["PATH"]:
            new_path.extend(old_path.split(os.pathsep))
        # However, we don't want a pre-existing PYTHONPATH to influence the
        # backend calls.
        os.environ.update({"PATH": os.pathsep.join(new_path), "PYTHONPATH": ""})

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
        if not requirements:
            return

        # TODO: when better support for installing to arbitrary Python environments
        # is added, replace this prefix hack with that.
        prefix = Prefix(self._env_path, venv_executable=self.python_executable)
        self._installer.install(requirements, prefix, kind=kind, for_req=for_req)
