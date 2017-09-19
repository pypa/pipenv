# -*- coding: utf-8 -*-
import json
import os
import re
import sys
import base64
import hashlib

import contoml
import delegator
import pipfile
import toml

from .utils import (
    mkdir_p, convert_deps_from_pip, pep423_name, recase_file,
    find_requirements, is_file, is_vcs, python_version
)
from .environments import PIPENV_MAX_DEPTH, PIPENV_VENV_IN_PROJECT
from .environments import PIPENV_USE_SYSTEM


class Project(object):
    """docstring for Project"""

    def __init__(self):
        super(Project, self).__init__()
        self._name = None
        self._virtualenv_location = None
        self._download_location = None
        self._proper_names_location = None
        self._pipfile_location = None
        self._requirements_location = None

        # Hack to skip this during pipenv run.
        if 'run' not in sys.argv:
            try:
                os.chdir(self.project_directory)
            except (TypeError, AttributeError):
                pass

    @property
    def name(self):
        if self._name is None:
            self._name = self.pipfile_location.split(os.sep)[-2]
        return self._name

    @property
    def pipfile_exists(self):
        return bool(self.pipfile_location)

    @property
    def required_python_version(self):
        if self.pipfile_exists:
            required = self.parsed_pipfile.get('requires', {}).get('python_full_version')
            if not required:
                required = self.parsed_pipfile.get('requires', {}).get('python_version')
            if required != "*":
                return required

    @property
    def project_directory(self):
        return os.path.abspath(os.path.join(self.pipfile_location, os.pardir))

    @property
    def requirements_exists(self):
        return bool(self.requirements_location)

    @property
    def virtualenv_exists(self):
        # TODO: Decouple project from existence of Pipfile.
        if self.pipfile_exists:
            return os.path.isdir(self.virtualenv_location)
        return False

    @property
    def virtualenv_name(self):
        # Replace dangerous characters into '_'. The length of the sanitized
        # project name is limited as 42 because of the limit of linux kernel
        #
        # 42 = 127 - len('/home//.local/share/virtualenvs//bin/python2') - 32 - len('-HASHHASH')
        #
        #      127 : BINPRM_BUF_SIZE - 1
        #       32 : Maxmimum length of username
        #
        # References:
        #   https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
        #   http://www.tldp.org/LDP/abs/html/special-chars.html#FIELDREF
        #   https://github.com/torvalds/linux/blob/2bfe01ef/include/uapi/linux/binfmts.h#L18
        sanitized = re.sub(r'[ $`!*@"\\\r\n\t]', '_', self.name)[0:42]

        # Hash the full path of the pipfile
        hash = hashlib.sha256(self.pipfile_location.encode()).digest()[:6]
        encoded_hash = base64.urlsafe_b64encode(hash).decode()

        # If the pipfile was located at '/home/user/MY_PROJECT/Pipfile',
        # the name of its virtualenv will be 'my-project-wyUfYPqE'
        return sanitized + '-' + encoded_hash

    @property
    def virtualenv_location(self):

        # if VIRTUAL_ENV is set, use that.
        if PIPENV_USE_SYSTEM:
            return PIPENV_USE_SYSTEM

        # Use cached version, if available.
        if self._virtualenv_location:
            return self._virtualenv_location

        # The user wants the virtualenv in the project.
        if not PIPENV_VENV_IN_PROJECT:
            c = delegator.run('pew dir "{0}"'.format(self.virtualenv_name))
            loc = c.out.strip()
        # Default mode.
        else:
            loc = os.sep.join(self.pipfile_location.split(os.sep)[:-1] + ['.venv'])

        self._virtualenv_location = loc
        return loc

    @property
    def download_location(self):
        if self._download_location is None:
            loc = os.sep.join([self.virtualenv_location, 'downloads'])
            self._download_location = loc

        # Create the directory, if it doesn't exist.
        mkdir_p(self._download_location)

        return self._download_location

    @property
    def proper_names_location(self):
        if self._proper_names_location is None:
            loc = os.sep.join([self.virtualenv_location, 'pipenev-proper-names.txt'])
            self._proper_names_location = loc

        # Create the database, if it doesn't exist.
        open(self._proper_names_location, 'a').close()

        return self._proper_names_location

    @property
    def proper_names(self):
        with open(self.proper_names_location) as f:
            return f.read().splitlines()

    def register_proper_name(self, name):
        """Registers a proper name to the database."""
        with open(self.proper_names_location, 'a') as f:
            f.write('{0}\n'.format(name))

    @property
    def pipfile_location(self):
        if self._pipfile_location is None:
            try:
                loc = pipfile.Pipfile.find(max_depth=PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = None
            self._pipfile_location = loc

        return self._pipfile_location

    @property
    def requirements_location(self):
        if self._requirements_location is None:
            try:
                loc = find_requirements(max_depth=PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = None
            self._requirements_location = loc

        return self._requirements_location

    @property
    def parsed_pipfile(self):
        # Open the pipfile, read it into memory.
        with open(self.pipfile_location) as f:
            contents = f.read()

        # If any outline tables are present...
        if ('[packages.' in contents) or ('[dev-packages.' in contents):

            data = toml.loads(contents)

            # Convert all outline tables to inline tables.
            for section in ('packages', 'dev-packages'):
                for package in data.get(section):

                    # Convert things to inline tables — fancy :)
                    if hasattr(data[section][package], 'keys'):
                        _data = data[section][package]
                        data[section][package] = toml._get_empty_inline_table(dict)
                        data[section][package].update(_data)

            # We lose comments here, but it's for the best.)
            return contoml.loads(toml.dumps(data, preserve=True))
        else:
            return contoml.loads(contents)

    @property
    def _pipfile(self):
        """Pipfile divided by PyPI and external dependencies."""
        pfile = self.parsed_pipfile
        for section in ('packages', 'dev-packages'):
            p_section = pfile.get(section, {})

            for key in list(p_section.keys()):
                # Normalize key name to PEP 423.
                norm_key = pep423_name(key)
                p_section[norm_key] = p_section.pop(key)

        return pfile

    @property
    def _lockfile(self):
        """Pipfile.lock divided by PyPI and external dependencies."""
        pfile = pipfile.load(self.pipfile_location)
        lockfile = json.loads(pfile.lock())

        for section in ('default', 'develop'):
            lock_section = lockfile.get(section, {})

            for key in list(lock_section.keys()):
                norm_key = pep423_name(key)
                lockfile[section][norm_key] = lock_section.pop(key)

        return lockfile

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

    @property
    def vcs_packages(self):
        """Returns a list of VCS packages, for not pip-tools to consume."""
        ps = {}
        for k, v in self.parsed_pipfile.get('packages', {}).items():
            if is_vcs(v):
                ps.update({k: v})
        return ps

    @property
    def vcs_dev_packages(self):
        """Returns a list of VCS packages, for not pip-tools to consume."""
        ps = {}
        for k, v in self.parsed_pipfile.get('dev-packages', {}).items():
            if is_vcs(v):
                ps.update({k: v})
        return ps

    @property
    def packages(self):
        """Returns a list of packages, for pip-tools to consume."""
        ps = {}
        for k, v in self.parsed_pipfile.get('packages', {}).items():
            # Skip VCS deps.
            if ('extras' in v) or (not hasattr(v, 'keys')):
                ps.update({k: v})
        return ps

    @property
    def dev_packages(self):
        """Returns a list of dev-packages, for pip-tools to consume."""
        ps = {}
        for k, v in self.parsed_pipfile.get('dev-packages', {}).items():
            # Skip VCS deps.
            if ('extras' in v) or (not hasattr(v, 'keys')):
                ps.update({k: v})
        return ps

    def touch_pipfile(self):
        """Simply touches the Pipfile, for later use."""
        with open('Pipfile', 'a'):
            os.utime('Pipfile', None)

    @property
    def pipfile_is_empty(self):
        self.touch_pipfile()

        with open('Pipfile', 'r') as f:
            if not f.read():
                return True

    def create_pipfile(self, python=None):
        """Creates the Pipfile, filled with juicy defaults."""
        data = {
            # Default source.
            u'source': [
                {u'url': u'https://pypi.python.org/simple', u'verify_ssl': True}
            ],

            # Default packages.
            u'packages': {},
            u'dev-packages': {},

        }

        # Default requires.
        if python:
            data[u'requires'] = {'python_version': python_version(python)[:len('2.7')]}

        self.write_toml(data, 'Pipfile')

    def write_toml(self, data, path=None):
        """Writes the given data structure out as TOML."""
        if path is None:
            path = self.pipfile_location

        try:
            formatted_data = contoml.dumps(data)
        except RuntimeError:
            import toml
            for section in ('packages', 'dev-packages'):
                for package in data[section]:

                    # Convert things to inline tables — fancy :)
                    if hasattr(data[section][package], 'keys'):
                        _data = data[section][package]
                        data[section][package] = toml._get_empty_inline_table(dict)
                        data[section][package].update(_data)

            formatted_data = toml.dumps(data)
        else:
            pass
        finally:
            pass

        with open(path, 'w') as f:
            f.write(formatted_data)

    @property
    def sources(self):
        if self.lockfile_exists:
            meta_ = self.lockfile_content['_meta']
            sources_ = meta_.get('sources')
            if sources_:
                return sources_
        if 'source' in self.parsed_pipfile:
            return self.parsed_pipfile['source']
        else:
            return [{u'url': u'https://pypi.python.org/simple', u'verify_ssl': True}]

    def remove_package_from_pipfile(self, package_name, dev=False):

        # Read and append Pipfile.
        p = self._pipfile

        package_name = pep423_name(package_name)

        key = 'dev-packages' if dev else 'packages'

        if key in p and package_name in p[key]:
            del p[key][package_name]

        # Write Pipfile.
        self.write_toml(recase_file(p))

    def add_package_to_pipfile(self, package_name, dev=False):

        # Read and append Pipfile.
        p = self._pipfile

        # Don't re-capitalize file URLs.
        if not is_file(package_name):
            package_name = pep423_name(package_name)

        key = 'dev-packages' if dev else 'packages'

        # Set empty group if it doesn't exist yet.
        if key not in p:
            p[key] = {}

        package = convert_deps_from_pip(package_name)
        package_name = [k for k in package.keys()][0]

        # Add the package to the group.
        p[key][package_name] = package[package_name]

        # Write Pipfile.
        self.write_toml(p)

    def recase_pipfile(self):
        self.write_toml(recase_file(self._pipfile))
