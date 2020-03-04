import unittest
import packaging.requirements
import packaging.version

from . import fixtures
from .. import version


class IntegrationTests(fixtures.DistInfoPkg, unittest.TestCase):

    def test_package_spec_installed(self):
        """
        Illustrate the recommended procedure to determine if
        a specified version of a package is installed.
        """
        def is_installed(package_spec):
            req = packaging.requirements.Requirement(package_spec)
            return version(req.name) in req.specifier

        assert is_installed('distinfo-pkg==1.0')
        assert is_installed('distinfo-pkg>=1.0,<2.0')
        assert not is_installed('distinfo-pkg<1.0')
