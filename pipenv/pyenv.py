import operator
import re

from .vendor import attr, delegator

from .environments import PIPENV_INSTALL_TIMEOUT


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


class PyenvError(RuntimeError):
    def __init__(self, desc, c):
        super(PyenvError, self).__init__(desc)
        self.out = c.out
        self.err = c.err


class Runner(object):

    def __init__(self, pyenv):
        self._cmd = pyenv

    def _pyenv(self, *args, **kwargs):
        timeout = kwargs.pop('timeout', delegator.TIMEOUT)
        if kwargs:
            k = list(kwargs.keys())[0]
            raise TypeError('unexpected keyword argument {0!r}'.format(k))
        args = (self._cmd,) + tuple(args)
        c = delegator.run(args, block=False, timeout=timeout)
        c.block()
        if c.return_code != 0:
            raise PyenvError('faild to run {0}'.format(args), c)
        return c

    def iter_installable_versions(self):
        """Iterate through CPython versions available for Pipenv to install.
        """
        for name in self._pyenv('install', '--list').out.splitlines():
            try:
                version = Version.parse(name.strip())
            except ValueError:
                continue
            yield version

    def find_version_to_install(self, name):
        """Find a version in pyenv from the version supplied.

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

    def install(self, version):
        """Install the given version with pyenv.

        The version must be a ``Version`` instance representing a version
        found in pyenv.

        A ValueError is raised if the given version does not have a match in
        pyenv. A PyenvError is raised if the pyenv command fails.
        """
        c = self._pyenv(
            'install', '-s', str(version),
            timeout=PIPENV_INSTALL_TIMEOUT,
        )
        return c
