# -*- coding: utf-8 -*-
import json
import os

import pipfile
import toml

import delegator
from requests.compat import OrderedDict

from .utils import format_toml, mkdir_p
from .utils import convert_deps_from_pip
from .environments import PIPENV_MAX_DEPTH, PIPENV_VENV_IN_PROJECT


class Project(object):
    """docstring for Project"""
    def __init__(self):
        super(Project, self).__init__()
        self._virtualenv_location = None

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

        # Use cached version, if available.
        if self._virtualenv_location:
            return self._virtualenv_location

        # The user wants the virtualenv in the project.
        if not PIPENV_VENV_IN_PROJECT:
            c = delegator.run('pew dir {0}'.format(self.name))
            loc = c.out.strip()
        # Default mode.
        else:
            loc = os.sep.join(self.pipfile_location.split(os.sep)[:-1] + ['.venv'])

        self._virtualenv_location = loc
        return loc

    @property
    def download_location(self):
        d_dir = os.sep.join(self.virtualenv_location.split(os.sep) + ['downloads'])

        # Create the directory, if it doesn't exist.
        mkdir_p(d_dir)

        return d_dir

    @property
    def pipfile_location(self):
        try:
            return pipfile.Pipfile.find(max_depth=PIPENV_MAX_DEPTH)
        except RuntimeError:
            return None

    @property
    def parsed_pipfile(self):
        with open(self.pipfile_location) as f:
            # return toml.load(f)
            return toml.load(f, _dict=OrderedDict)

    @property
    def lockfile_location(self):
        return '{0}.lock'.format(self.pipfile_location)

    @property
    def lockfile_exists(self):
        return os.path.isfile(self.lockfile_location)

    @property
    def lockfile_content(self):
        with open(self.lockfile_location) as lock:
            return json.load(lock)

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
        if self.lockfile_exists:
            meta_ = self.lockfile_content['_meta']
            sources_ = meta_.get('sources')
            if sources_:
                return sources_[0]
        if 'source' in self.parsed_pipfile:
            return self.parsed_pipfile['source'][0]
        else:
            return {u'url': u'https://pypi.python.org/simple', u'verify_ssl': True}

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
