from typing import Optional

from pipenv.patched.notpip._vendor.pkg_resources import Distribution

from pipenv.patched.notpip._internal.distributions.base import AbstractDistribution
from pipenv.patched.notpip._internal.index.package_finder import PackageFinder


class InstalledDistribution(AbstractDistribution):
    """Represents an installed package.

    This does not need any preparation as the required information has already
    been computed.
    """

    def get_pkg_resources_distribution(self) -> Optional[Distribution]:
        return self.req.satisfied_by

    def prepare_distribution_metadata(
        self, finder: PackageFinder, build_isolation: bool
    ) -> None:
        pass
