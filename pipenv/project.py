import os

import toml

from . import _pipfile as pipfile
from .utils import format_toml, multi_split
from .utils import convert_deps_from_pip, convert_deps_to_pip


class Project(object):
    """docstring for Project"""
    def __init__(self):
        super(Project, self).__init__()

    @property
    def name(self):
        return self.pipfile_location.split(os.sep)[-2]

    @property
    def pipfile_exists(self):
        return bool(self.pipfile_location)

    @property
    def virtualenv_exists(self):
        return os.path.isdir(self.virtualenv_location)

    @property
    def virtualenv_location(self):
        return os.sep.join(self.pipfile_location.split(os.sep)[:-1] + ['.venv'])

    @property
    def pipfile_location(self):
        try:
            return pipfile.Pipfile.find()
        except RuntimeError:
            return None

    @property
    def lockfile_location(self):
        return '{0}.lock'.format(self.pipfile_location)

    @property
    def lockfile_exists(self):
        return os.path.isfile(self.lockfile_location)

    def create_pipfile(self):
        data = {u'source': [{u'url': u'https://pypi.org/', u'verify_ssl': True}], u'packages': {}, 'dev-packages': {}}
        with open('Pipfile', 'w') as f:
            f.write(toml.dumps(data))

    @staticmethod
    def remove_package_from_pipfile(package_name, dev=False):
        pipfile_path = pipfile.Pipfile.find()

        # Read and append Pipfile.
        with open(pipfile_path, 'r') as f:
            p = toml.loads(f.read())

            key = 'dev-packages' if dev else 'packages'
            if key in p:
                if package_name in p[key]:
                    del p[key][package_name]

        # Write Pipfile.
        data = format_toml(toml.dumps(p))
        with open(pipfile_path, 'w') as f:
            f.write(data)

    @staticmethod
    def add_package_to_pipfile(package_name, dev=False):
        pipfile_path = pipfile.Pipfile.find()

        # Read and append Pipfile.
        with open(pipfile_path, 'r') as f:
            p = toml.loads(f.read())

            key = 'dev-packages' if dev else 'packages'

            # Set empty group if it doesn't exist yet.
            if key not in p:
                p[key] = {}

            package = convert_deps_from_pip(package_name)
            package_name = [k for k in package.keys()][0]

            # Add the package to the group.
            p[key][package_name] = package[package_name]

        # Write Pipfile.
        data = format_toml(toml.dumps(p))
        with open(pipfile_path, 'w') as f:
            f.write(data)
