from pipenv.patched.notpip._vendor.packaging.version import parse as parse_version

from pipenv.patched.notpip._internal.utils.models import KeyBasedCompareMixin
from pipenv.patched.notpip._internal.utils.typing import MYPY_CHECK_RUNNING

if MYPY_CHECK_RUNNING:
    from pipenv.patched.notpip._vendor.packaging.version import _BaseVersion  # noqa: F401
    from pipenv.patched.notpip._internal.models.link import Link  # noqa: F401
    from typing import Any, Union  # noqa: F401


class InstallationCandidate(KeyBasedCompareMixin):
    """Represents a potential "candidate" for installation.
    """

    def __init__(self, project, version, location, requires_python=None):
        # type: (Any, str, Link, Any) -> None
        self.project = project
        self.version = parse_version(version)  # type: _BaseVersion
        self.location = location
        self.requires_python = requires_python

        super(InstallationCandidate, self).__init__(
            key=(self.project, self.version, self.location),
            defining_class=InstallationCandidate
        )

    def __repr__(self):
        # type: () -> str
        return "<InstallationCandidate({!r}, {!r}, {!r})>".format(
            self.project, self.version, self.location,
        )
