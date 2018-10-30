from pipenv.patched.notpip._vendor.packaging.version import parse as parse_version

from pipenv.patched.notpip._internal.utils.models import KeyBasedCompareMixin


class InstallationCandidate(KeyBasedCompareMixin):
    """Represents a potential "candidate" for installation.
    """

    def __init__(self, project, version, location, requires_python=None):
        self.project = project
        self.version = parse_version(version)
        self.location = location
        self.requires_python = requires_python

        super(InstallationCandidate, self).__init__(
            key=(self.project, self.version, self.location),
            defining_class=InstallationCandidate
        )

    def __repr__(self):
        return "<InstallationCandidate({!r}, {!r}, {!r})>".format(
            self.project, self.version, self.location,
        )
