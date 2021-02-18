import os
import operator
import re
import six
from abc import ABCMeta, abstractmethod


from .environments import PIPENV_INSTALL_TIMEOUT
from .vendor import attr, delegator
from .utils import find_windows_executable


@attr.s
class Version(object):

    major = attr.ib()
    minor = attr.ib()
    patch = attr.ib()

    def __str__(self):
        parts = [self.major, self.minor]
        if self.patch is not None:
            parts.append(self.patch)
        return '.'.join(str(p) for p in parts)

    @classmethod
    def parse(cls, name):
        """Parse an X.Y.Z or X.Y string into a version tuple.
        """
        match = re.match(r'^(\d+)\.(\d+)(?:\.(\d+))?$', name)
        if not match:
            raise ValueError('invalid version name {0!r}'.format(name))
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
        """Check whether this version matches the other in (major, minor).
        """
        return (self.major, self.minor) == (other.major, other.minor)


class InstallerNotFound(RuntimeError):
    pass


class InstallerError(RuntimeError):
    def __init__(self, desc, c):
        super(InstallerError, self).__init__(desc)
        self.out = c.out
        self.err = c.err


@six.add_metaclass(ABCMeta)
class Installer(object):

    def __init__(self):
        self.cmd = self._find_installer()
        super(Installer, self).__init__()

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
        custom environment variable (PYENV_ROOT or ASDF_DIR) which alows them to
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
            find_windows_executable('', name),
            # Check for explicitly set install locations (e.g. PYENV_ROOT, ASDF_DIR).
            os.path.join(os.path.expanduser(os.getenv(env_var, '/dev/null')), 'bin', name),
            # Check the pyenv/asdf-recommended from-source install locations
            os.path.join(os.path.expanduser('~/.{}'.format(name)), 'bin', name),
        ):
            if candidate is not None and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        raise InstallerNotFound()

    def _run(self, *args, **kwargs):
        timeout = kwargs.pop('timeout', delegator.TIMEOUT)
        if kwargs:
            k = list(kwargs.keys())[0]
            raise TypeError('unexpected keyword argument {0!r}'.format(k))
        args = (self.cmd,) + tuple(args)
        c = delegator.run(args, block=False, timeout=timeout)
        c.block()
        if c.return_code != 0:
            raise InstallerError('failed to run {0}'.format(args), c)
        return c

    @abstractmethod
    def iter_installable_versions(self):
        """Iterate through CPython versions available for Pipenv to install.
        """
        pass

    def find_version_to_install(self, name):
        """Find a version in the installer from the version supplied.

        A ValueError is raised if a matching version cannot be found.
        """
        version = Version.parse(name)
        if version.patch is not None:
            return name
        try:
            best_match = max((
                inst_version
                for inst_version in self.iter_installable_versions()
                if inst_version.matches_minor(version)
            ), key=operator.attrgetter('cmpkey'))
        except ValueError:
            raise ValueError(
                'no installable version found for {0!r}'.format(name),
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

    def _find_installer(self):
        return self._find_python_installer_by_name_and_env('pyenv', 'PYENV_ROOT')

    def iter_installable_versions(self):
        """Iterate through CPython versions available for Pipenv to install.
        """
        for name in self._run('install', '--list').out.splitlines():
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
        c = self._run(
            'install', '-s', str(version),
            timeout=PIPENV_INSTALL_TIMEOUT,
        )
        return c


class Asdf(Installer):

    def _find_installer(self):
        return self._find_python_installer_by_name_and_env('asdf', 'ASDF_DIR')

    def iter_installable_versions(self):
        """Iterate through CPython versions available for asdf to install.
        """
        for name in self._run('list-all', 'python').out.splitlines():
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
            'install', 'python', str(version),
            timeout=PIPENV_INSTALL_TIMEOUT,
        )
        return c
