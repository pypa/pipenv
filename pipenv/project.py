import os

import pipfile
import toml

from requests.compat import OrderedDict

from .utils import format_toml, multi_split
from .utils import convert_deps_from_pip, convert_deps_to_pip


def mkdir_p(newdir):
    """works the way a good mkdir should :)
        - already exists, silently complete
        - regular file in the way, raise an exception
        - parent directory(ies) does not exist, make them as well
        From: http://code.activestate.com/recipes/82465-a-friendly-mkdir/
    """
    if os.path.isdir(newdir):
        pass
    elif os.path.isfile(newdir):
        raise OSError("a file with the same name as the desired dir, '%s', already exists." % newdir)
    else:
        head, tail = os.path.split(newdir)
        if head and not os.path.isdir(head):
            _mkdir(head)
        if tail:
            os.mkdir(newdir)


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
    def download_location(self):
        d_dir = os.sep.join(self.pipfile_location.split(os.sep)[:-1] + ['.venv', 'downloads'])

        # Create the directory, if it doesn't exist.
        mkdir_p(d_dir)

        return d_dir

    @property
    def pipfile_location(self):
        try:
            return pipfile.Pipfile.find()
        except RuntimeError:
            return None

    @property
    def parsed_pipfile(self):
        with open(self.pipfile_location, 'r') as f:
            # return toml.load(f)
            return toml.load(f, _dict=OrderedDict)

    @property
    def lockfile_location(self):
        return '{0}.lock'.format(self.pipfile_location)

    @property
    def lockfile_exists(self):
        return os.path.isfile(self.lockfile_location)

    def create_pipfile(self):
        data = {u'source': [{u'url': u'https://pypi.python.org/simple', u'verify_ssl': True}], u'packages': {}, 'dev-packages': {}}
        with open('Pipfile', 'w') as f:
            f.write(toml.dumps(data))

    def write(self, data):
        # format TOML data.
        with open(self.pipfile_location, 'w') as f:
            f.write(format_toml(toml.dumps(data)))

    @property
    def source(self):
        # TODO: Should load from Pipfile.lock too.
        if 'source' in self.parsed_pipfile:
            return self.parsed_pipfile['source'][0]
        else:
            return [{u'url': u'https://pypi.python.org/simple', u'verify_ssl': True}][0]

    def remove_package_from_pipfile(self, package_name, dev=False):
        pipfile_path = pipfile.Pipfile.find()

        # Read and append Pipfile.
        p = self.parsed_pipfile

        key = 'dev-packages' if dev else 'packages'

        if key in p:
            if package_name in p[key]:
                del p[key][package_name]

        # Write Pipfile.
        data = format_toml(toml.dumps(p))
        with open(pipfile_path, 'w') as f:
            f.write(data)

    def add_package_to_pipfile(self, package_name, dev=False):

        # Find the Pipfile.
        pipfile_path = pipfile.Pipfile.find()

        # Read and append Pipfile.
        p = self.parsed_pipfile

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
