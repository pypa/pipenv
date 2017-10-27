#     ___     ( )  ___      ___       __
#   //   ) ) / / //   ) ) //___) ) //   ) ) ||  / /
#  //___/ / / / //___/ / //       //   / /  || / /
# //       / / //       ((____   //   / /   ||/ /
import pkg_resources
from os.path import join, dirname
from setuptools.config import read_configuration


def _extract_version(package_name):
    try:
        return pkg_resources.get_distribution(package_name).version
    except pkg_resources.DistributionNotFound:
        _conf = read_configuration(
            join(dirname(dirname(__file__))), 'setup.cfg'
        )
        return _conf['metadata']['version']


__version__ = _extract_version('pipenv')


if __name__ == "__main__":
    print(__version__)
