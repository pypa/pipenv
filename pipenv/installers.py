import operator
import os
import re
import sys
from abc import ABCMeta, abstractmethod

from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import find_windows_executable
from pipenv.vendor import attr


@attr.s
class Version:

    major = attr.ib()
    minor = attr.ib()
    patch = attr.ib()

    def __str__(self):
        parts = [self.major, self.minor]
        if self.patch is not None:
            parts.append(self.patch)
        return ".".join(str(p) for p in parts)

    @classmethod
    def parse(cls, name):
        """Parse an X.Y.Z or X.Y string into a version tuple."""
        match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", name)
        if not match:
            raise ValueError(f"invalid version name {name!r}")
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = match.group(3)
        if patch is not None:
            patch = int(patch)
        return cls(major, minor, patch)

    @property
    def cmpkey(self):
        """Make the version a comparable tuple.

        Some old Python versions does not have a patch part, e.g. 2.7.0 is
        named "2.7" in pyenv. Fix that, otherwise `None` will fail to compare
        with int.
        """
        return (self.major, self.minor, self.patch or 0)

    def matches_minor(self, other):
        """Check whether this version matches the other in (major, minor)."""
        return (self.major, self.minor) == (other.major, other.minor)


class InstallerNotFound(RuntimeError):
    pass


class InstallerError(RuntimeError):
    def __init__(self, desc, c):
        super().__init__(desc)
        self.out = c.stdout
        self.err = c.stderr


class Installer(metaclass=ABCMeta):
    def __init__(self, project):
        self.cmd = self._find_installer()
        self.project = project

    def __str__(self):
        return self.__class__.__name__

    @abstractmethod
    def _find_installer(self):
        pass

    @staticmethod
    def _find_python_installer_by_name_and_env(name, env_var):
        """
        Given a python installer (pyenv or asdf), try to locate the binary for that
        installer.

        pyenv/asdf are not always present on PATH. Both installers also support a
        custom environment variable (PYENV_ROOT or ASDF_DIR) which allows them to
        be installed into a non-default location (the default/suggested source
        install location is in ~/.pyenv or ~/.asdf).

        For systems without the installers on PATH, and with a custom location
        (e.g. /opt/pyenv), Pipenv can use those installers without modifications to
        PATH, if an installer's respective environment variable is present in an
        environment's .env file.

        This function searches for installer binaries in the following locations,
        by precedence:
            1. On PATH, equivalent to which(1).
            2. In the "bin" subdirectory of PYENV_ROOT or ASDF_DIR, depending on the
               installer.
            3. In ~/.pyenv/bin or ~/.asdf/bin, depending on the installer.
        """
        for candidate in (
            # Look for the Python installer using the equivalent of 'which'. On
            # Homebrew-installed systems, the env var may not be set, but this
            # strategy will work.
            find_windows_executable("", name),
            # Check for explicitly set install locations (e.g. PYENV_ROOT, ASDF_DIR).
            os.path.join(
                os.path.expanduser(os.getenv(env_var, "/dev/null")), "bin", name
            ),
            # Check the pyenv/asdf-recommended from-source install locations
            os.path.join(os.path.expanduser(f"~/.{name}"), "bin", name),
        ):
            if (
                candidate is not None
                and os.path.isfile(candidate)
                and os.access(candidate, os.X_OK)
            ):
                return candidate
        raise InstallerNotFound()

    def _run(self, *args, **kwargs):
        timeout = kwargs.pop("timeout", 30)
        shell = kwargs.pop("shell", False)
        if kwargs:
            k = list(kwargs.keys())[0]
            raise TypeError(f"unexpected keyword argument {k!r}")
        args = (self.cmd,) + tuple(args)
        c = subprocess_run(args, timeout=timeout, shell=shell)
        if c.returncode != 0:
            raise InstallerError(f"failed to run {args}", c)
        return c

    @abstractmethod
    def iter_installable_versions(self):
        """Iterate through CPython versions available for Pipenv to install."""
        pass

    def find_version_to_install(self, name):
        """Find a version in the installer from the version supplied.

        A ValueError is raised if a matching version cannot be found.
        """
        version = Version.parse(name)
        if version.patch is not None:
            return name
        try:
            best_match = max(
                (
                    inst_version
                    for inst_version in self.iter_installable_versions()
                    if inst_version.matches_minor(version)
                ),
                key=operator.attrgetter("cmpkey"),
            )
        except ValueError:
            raise ValueError(
                f"no installable version found for {name!r}",
            )
        return best_match

    @abstractmethod
    def install(self, version):
        """Install the given version with runner implementation.

        The version must be a ``Version`` instance representing a version
        found in the Installer.

        A ValueError is raised if the given version does not have a match in
        the runner. A InstallerError is raised if the runner command fails.
        """
        pass


class Pyenv(Installer):
    WIN = sys.platform.startswith("win") or (sys.platform == "cli" and os.name == "nt")

    def _find_installer(self):
        return self._find_python_installer_by_name_and_env("pyenv", "PYENV_ROOT")

    def _run(self, *args, **kwargs):
        if Pyenv.WIN:
            kwargs["shell"] = True
        return super(Pyenv, self)._run(*args, **kwargs)

    def iter_installable_versions(self):
        """Iterate through CPython versions available for Pipenv to install."""
        for name in self._run("install", "--list").stdout.splitlines():
            try:
                version = Version.parse(name.strip())
            except ValueError:
                continue
            yield version

    def install(self, version):
        """Install the given version with pyenv.
        The version must be a ``Version`` instance representing a version
        found in pyenv.
        A ValueError is raised if the given version does not have a match in
        pyenv. A InstallerError is raised if the pyenv command fails.
        """
        args = ["install", "-s", str(version)]
        if Pyenv.WIN:
            # pyenv-win skips installed versions by default and does not support -s
            del args[1]
        return self._run(*args, timeout=self.project.s.PIPENV_INSTALL_TIMEOUT)


class Asdf(Installer):
    def _find_installer(self):
        return self._find_python_installer_by_name_and_env("asdf", "ASDF_DIR")

    def iter_installable_versions(self):
        """Iterate through CPython versions available for asdf to install."""
        for name in self._run("list-all", "python").stdout.splitlines():
            try:
                version = Version.parse(name.strip())
            except ValueError:
                continue
            yield version

    def install(self, version):
        """Install the given version with asdf.
        The version must be a ``Version`` instance representing a version
        found in asdf.
        A ValueError is raised if the given version does not have a match in
        asdf. A InstallerError is raised if the asdf command fails.
        """
        c = self._run(
            "install",
            "python",
            str(version),
            timeout=self.project.s.PIPENV_INSTALL_TIMEOUT,
        )
        return c
