# -*- coding: utf-8 -*-
import json
import os
import re
import sys
import shlex
import base64
import hashlib

import contoml
import delegator
import pipfile
import toml

from .patched.pip.baseparser import ConfigOptionParser
from .utils import (
    mkdir_p, convert_deps_from_pip, pep423_name, recase_file,
    find_requirements, is_file, is_vcs, python_version, cleanup_toml,
    is_installable_file, is_valid_url, normalize_drive
)
from .environments import (
    PIPENV_MAX_DEPTH,
    PIPENV_PIPFILE,
    PIPENV_VENV_IN_PROJECT,
    PIPENV_VIRTUALENV,
    PIPENV_NO_INHERIT,
    PIPENV_TEST_INDEX
)

if PIPENV_PIPFILE:
    if not os.path.isfile(PIPENV_PIPFILE):
        raise RuntimeError('Given PIPENV_PIPFILE is not found!')
    else:
        PIPENV_PIPFILE = normalize_drive(os.path.abspath(PIPENV_PIPFILE))


class Project(object):
    """docstring for Project"""

    def __init__(self, which=None, chdir=True):
        super(Project, self).__init__()
        self._name = None
        self._virtualenv_location = None
        self._download_location = None
        self._proper_names_location = None
        self._pipfile_location = None
        self._requirements_location = None
        self._original_dir = os.path.abspath(os.curdir)
        self.which = which

        # Hack to skip this during pipenv run, or -r.
        if ('run' not in sys.argv) and chdir:
            try:
                os.chdir(self.project_directory)
            except (TypeError, AttributeError):
                pass

    def path_to(self, p):
        """Returns the absolute path to a given relative path."""
        if os.path.isabs(p):
            return p

        return os.sep.join([self._original_dir, p])

    def _build_package_list(self, package_section):
        """Returns a list of packages for pip-tools to consume."""
        ps = {}
        # TODO: Separate the logic for showing packages from the filters for supplying pip-tools
        for k, v in self.parsed_pipfile.get(package_section, {}).items():
            # Skip editable VCS deps.
            if hasattr(v, 'keys'):
                # When a vcs url is gven without editable it only appears as a key
                # Eliminate any vcs, path, or url entries which are not editable
                # Since pip-tools can't do deep resolution on them, even setuptools-installable ones
                if (is_vcs(v) or is_vcs(k) or (is_installable_file(k) or is_installable_file(v)) or
                        any((prefix in v and
                             (os.path.isfile(v[prefix]) or is_valid_url(v[prefix])))
                            for prefix in ['path', 'file'])):
                    # If they are editable, do resolve them
                    if 'editable' not in v:
                        continue
                    else:
                        ps.update({k: v})
                else:
                    ps.update({k: v})
            else:
                # Since these entries have no attributes we know they are not editable
                # So we can safely exclude things that need to be editable in order to be resolved
                # First exclude anything that is a vcs entry either in the key or value
                if not (any(is_vcs(i) for i in [k, v]) or
                        # Then exclude any installable files that are not directories
                        # Because pip-tools can resolve setup.py for example
                        any(is_installable_file(i) for i in [k, v]) or
                        # Then exclude any URLs because they need to be editable also
                        # Things that are excluded can only be 'shallow resolved'
                        any(is_valid_url(i) for i in [k, v])):
                    ps.update({k: v})
        return ps

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
        if self.pipfile_location is not None:
            return os.path.abspath(os.path.join(self.pipfile_location, os.pardir))
        else:
            return None

    @property
    def requirements_exists(self):
        return bool(self.requirements_location)

    @property
    def virtualenv_exists(self):
        # TODO: Decouple project from existence of Pipfile.
        if self.pipfile_exists and os.path.exists(self.virtualenv_location):
            if os.name == 'nt':
                extra = ['Scripts', 'activate.bat']
            else:
                extra = ['bin', 'activate']
            return os.path.isfile(os.sep.join([self.virtualenv_location] + extra))

        return False

    @property
    def virtualenv_name(self):
        # Replace dangerous characters into '_'. The length of the sanitized
        # project name is limited as 42 because of the limit of linux kernel
        #
        # 42 = 127 - len('/home//.local/share/virtualenvs//bin/python2') - 32 - len('-HASHHASH')
        #
        #      127 : BINPRM_BUF_SIZE - 1
        #       32 : Maximum length of username
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
        if PIPENV_VIRTUALENV:
            return PIPENV_VIRTUALENV

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
    def virtualenv_src_location(self):
        loc = os.sep.join([self.virtualenv_location, 'src'])
        mkdir_p(loc)
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
            loc = os.sep.join([self.virtualenv_location, 'pipenv-proper-names.txt'])
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
        if PIPENV_PIPFILE:
            return PIPENV_PIPFILE

        if self._pipfile_location is None:
            try:
                loc = pipfile.Pipfile.find(max_depth=PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = None
            self._pipfile_location = normalize_drive(loc)

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
                for package in data.get(section, {}):

                    # Convert things to inline tables — fancy :)
                    if hasattr(data[section][package], 'keys'):
                        _data = data[section][package]
                        data[section][package] = toml._get_empty_inline_table(dict)
                        data[section][package].update(_data)

            # We lose comments here, but it's for the best.)
            try:
                return contoml.loads(toml.dumps(data, preserve=True))
            except RuntimeError:
                return toml.loads(toml.dumps(data, preserve=True))

        else:
            # Fallback to toml parser, for large files.
            try:
                return contoml.loads(contents)
            except Exception:
                return toml.loads(contents)

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
    def settings(self):
        """A dictionary of the settings added to the Pipfile."""
        return self.parsed_pipfile.get('pipenv', {})

    @property
    def scripts(self):
        scripts = self.parsed_pipfile.get('scripts', {})
        for (k, v) in scripts.items():
            scripts[k] = shlex.split(v, posix=True)

        return scripts


    def update_settings(self, d):
        settings = self.settings

        changed = False
        for new in d:
            if new not in settings:
                settings[new] = d[new]
                changed = True

        if changed:
            p = self.parsed_pipfile
            p['pipenv'] = settings

            # Write the changes to disk.
            self.write_toml(p)

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
            if is_vcs(v) or is_vcs(k):
                ps.update({k: v})
        return ps

    @property
    def vcs_dev_packages(self):
        """Returns a list of VCS packages, for not pip-tools to consume."""
        ps = {}
        for k, v in self.parsed_pipfile.get('dev-packages', {}).items():
            if is_vcs(v) or is_vcs(k):
                ps.update({k: v})
        return ps

    @property
    def all_packages(self):
        """Returns a list of all packages."""
        p = dict(self.parsed_pipfile.get('dev-packages', {}))
        p.update(self.parsed_pipfile.get('packages', {}))
        return p

    @property
    def packages(self):
        """Returns a list of packages, for pip-tools to consume."""
        return self._build_package_list('packages')

    @property
    def dev_packages(self):
        """Returns a list of dev-packages, for pip-tools to consume."""
        return self._build_package_list('dev-packages')

    def touch_pipfile(self):
        """Simply touches the Pipfile, for later use."""
        with open('Pipfile', 'a'):
            os.utime('Pipfile', None)

    @property
    def pipfile_is_empty(self):
        if not self.pipfile_exists:
            return True

        with open(self.pipfile_location, 'r') as f:
            if not f.read():
                return True

        return False

    def create_pipfile(self, python=None):
        """Creates the Pipfile, filled with juicy defaults."""
        config_parser = ConfigOptionParser(name=self.name)
        install = dict(config_parser.get_config_section('install'))
        indexes = install.get('extra-index-url', '').lstrip('\n').split('\n')

        if PIPENV_TEST_INDEX:
            sources = [{u'url': PIPENV_TEST_INDEX, u'verify_ssl': True, u'name': u'custom'}]
        else:
            # Default source.
            pypi_source = {u'url': u'https://pypi.python.org/simple', u'verify_ssl': True, u'name': 'pypi'}
            sources = [pypi_source]

            for i, index in enumerate(indexes):
                if not index:
                    continue
                source_name = 'pip_index_{}'.format(i)
                verify_ssl = index.startswith('https')

                sources.append({u'url': index, u'verify_ssl': verify_ssl, u'name': source_name})

        data = {
            u'source': sources,

            # Default packages.
            u'packages': {},
            u'dev-packages': {},

        }

        # Default requires.
        data[u'requires'] = {'python_version': python_version(self.which('python'))[:len('2.7')]}

        self.write_toml(data, 'Pipfile')

    def write_toml(self, data, path=None):
        """Writes the given data structure out as TOML."""
        if path is None:
            path = self.pipfile_location

        try:
            formatted_data = contoml.dumps(data).rstrip()
        except Exception:
            for section in ('packages', 'dev-packages'):
                for package in data[section]:

                    # Convert things to inline tables — fancy :)
                    if hasattr(data[section][package], 'keys'):
                        _data = data[section][package]
                        data[section][package] = toml._get_empty_inline_table(dict)
                        data[section][package].update(_data)

            formatted_data = toml.dumps(data).rstrip()

        formatted_data = cleanup_toml(formatted_data)
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
            return [{u'url': u'https://pypi.python.org/simple', u'verify_ssl': True, 'name': 'pypi'}]

    def get_source(self, name=None, url=None):
        for source in self.sources:
            if name:
                if source.get('name') == name:
                    return source
            elif url:
                if source.get('url') in url:
                    return source

    def destroy_lockfile(self):
        """Deletes the lockfile."""
        try:
            return os.remove(self.lockfile_location)
        except OSError:
            pass

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

        # Don't re-capitalize file URLs or VCSs.
        converted = convert_deps_from_pip(package_name)
        converted = converted[[k for k in converted.keys()][0]]

        if not (is_file(package_name) or is_vcs(converted) or 'path' in converted):
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

    def add_index_to_pipfile(self, index):
        """Adds a given index to the Pipfile."""

        # Read and append Pipfile.
        p = self._pipfile

        source = {'url': index, 'verify_ssl': True}

        # Add the package to the group.
        if 'source' not in p:
            p['source'] = [source]

        else:
            p['source'].append(source)

        # Write Pipfile.
        self.write_toml(p)

    def recase_pipfile(self):
        self.write_toml(recase_file(self._pipfile))
