# -*- coding: utf-8 -*-
import io
import json
import os
import re
import sys
import base64
import hashlib
import contoml
from first import first
import pipfile
import pipfile.api
import six
import toml
import json as simplejson

try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path

from .cmdparse import Script
from .utils import (
    atomic_open_for_write,
    mkdir_p,
    pep423_name,
    proper_case,
    find_requirements,
    is_editable,
    is_file,
    is_vcs,
    cleanup_toml,
    is_installable_file,
    is_valid_url,
    normalize_drive,
    python_version,
    safe_expandvars,
)
from .environments import (
    PIPENV_MAX_DEPTH,
    PIPENV_PIPFILE,
    PIPENV_VENV_IN_PROJECT,
    PIPENV_VIRTUALENV,
    PIPENV_TEST_INDEX,
    PIPENV_PYTHON,
    PIPENV_DEFAULT_PYTHON_VERSION,
)


def _normalized(p):
    if p is None:
        return None
    return normalize_drive(str(Path(p).resolve()))


DEFAULT_NEWLINES = u'\n'


def preferred_newlines(f):
    if isinstance(f.newlines, six.text_type):
        return f.newlines

    return DEFAULT_NEWLINES


if PIPENV_PIPFILE:
    if not os.path.isfile(PIPENV_PIPFILE):
        raise RuntimeError('Given PIPENV_PIPFILE is not found!')

    else:
        PIPENV_PIPFILE = _normalized(PIPENV_PIPFILE)
# (path, file contents) => TOMLFile
# keeps track of pipfiles that we've seen so we do not need to re-parse 'em
_pipfile_cache = {}


if PIPENV_TEST_INDEX:
    DEFAULT_SOURCE = {
        u'url': PIPENV_TEST_INDEX,
        u'verify_ssl': True,
        u'name': u'custom',
    }
else:
    DEFAULT_SOURCE = {
        u'url': u'https://pypi.org/simple',
        u'verify_ssl': True,
        u'name': u'pypi',
    }

pipfile.api.DEFAULT_SOURCE = DEFAULT_SOURCE


class SourceNotFound(KeyError):
    pass


class Project(object):
    """docstring for Project"""

    def __init__(self, which=None, python_version=None, chdir=True):
        super(Project, self).__init__()
        self._name = None
        self._virtualenv_location = None
        self._download_location = None
        self._proper_names_location = None
        self._pipfile_location = None
        self._pipfile_newlines = DEFAULT_NEWLINES
        self._lockfile_newlines = DEFAULT_NEWLINES
        self._requirements_location = None
        self._original_dir = os.path.abspath(os.curdir)
        self.which = which
        self.python_version = python_version
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
                if (
                    is_vcs(v) or
                    is_vcs(k) or
                    (is_installable_file(k) or is_installable_file(v)) or
                    any(
                        (
                            prefix in v and
                            (
                                os.path.isfile(v[prefix]) or
                                is_valid_url(v[prefix])
                            )
                        )
                        for prefix in ['path', 'file']
                    )
                ):
                    # If they are editable, do resolve them
                    if 'editable' not in v:
                        # allow wheels to be passed through
                        if not (hasattr(v, 'keys') and v.get('path', v.get('file', '')).endswith('.whl')):
                            continue
                        ps.update({k: v})

                    else:
                        ps.update({k: v})
                else:
                    ps.update({k: v})
            else:
                # Since these entries have no attributes we know they are not editable
                # So we can safely exclude things that need to be editable in order to be resolved
                # First exclude anything that is a vcs entry either in the key or value
                if not (
                    any(is_vcs(i) for i in [k, v]) or
                    # Then exclude any installable files that are not directories
                    # Because pip-tools can resolve setup.py for example
                    any(is_installable_file(i) for i in [k, v]) or
                    # Then exclude any URLs because they need to be editable also
                    # Things that are excluded can only be 'shallow resolved'
                    any(is_valid_url(i) for i in [k, v])
                ):
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
            required = self.parsed_pipfile.get('requires', {}).get(
                'python_full_version'
            )
            if not required:
                required = self.parsed_pipfile.get('requires', {}).get(
                    'python_version'
                )
            if required != "*":
                return required

    @property
    def project_directory(self):
        if self.pipfile_location is not None:
            return os.path.abspath(
                os.path.join(self.pipfile_location, os.pardir)
            )

        else:
            return None

    @property
    def requirements_exists(self):
        return bool(self.requirements_location)

    def is_venv_in_project(self):
        return (
            PIPENV_VENV_IN_PROJECT or
            os.path.exists(os.path.join(self.project_directory, '.venv'))
        )

    @property
    def virtualenv_exists(self):
        # TODO: Decouple project from existence of Pipfile.
        if self.pipfile_exists and os.path.exists(self.virtualenv_location):
            if os.name == 'nt':
                extra = ['Scripts', 'activate.bat']
            else:
                extra = ['bin', 'activate']
            return os.path.isfile(
                os.sep.join([self.virtualenv_location] + extra)
            )

        return False

    @classmethod
    def _get_virtualenv_location(cls, name):
        from .patched.pew.pew import get_workon_home
        venv = get_workon_home() / name
        if not venv.exists():
            return ''
        return '{0}'.format(venv)

    @classmethod
    def _sanitize(cls, name):
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
        return re.sub(r'[ $`!*@"\\\r\n\t]', '_', name)[0:42]

    def _get_virtualenv_hash(self, name):
        """Get the name of the virtualenv adjusted for windows if needed

        Returns (name, encoded_hash)
        """
        def get_name(name, location):
            name = self._sanitize(name)
            hash = hashlib.sha256(location.encode()).digest()[:6]
            encoded_hash = base64.urlsafe_b64encode(hash).decode()
            return name, encoded_hash[:8]

        clean_name, encoded_hash = get_name(name, self.pipfile_location)
        venv_name = '{0}-{1}'.format(clean_name, encoded_hash)

        # This should work most of the time, for non-WIndows, in-project venv,
        # or "proper" path casing (on Windows).
        if (os.name != 'nt' or
                self.is_venv_in_project() or
                self._get_virtualenv_location(venv_name)):
            return clean_name, encoded_hash

        # Check for different capitalization of the same project.
        from .patched.pew.pew import lsenvs
        for env in lsenvs():
            try:
                env_name, hash_ = env.rsplit('-', 1)
            except ValueError:
                continue
            if len(hash_) != 8 or env_name.lower() != name.lower():
                continue
            return get_name(env_name, self.pipfile_location.replace(name, env_name))

        # Use the default if no matching env exists.
        return clean_name, encoded_hash

    @property
    def virtualenv_name(self):
        sanitized, encoded_hash = self._get_virtualenv_hash(self.name)
        suffix = '-{0}'.format(PIPENV_PYTHON) if PIPENV_PYTHON else ''
        # If the pipfile was located at '/home/user/MY_PROJECT/Pipfile',
        # the name of its virtualenv will be 'my-project-wyUfYPqE'
        return sanitized + '-' + encoded_hash + suffix

    @property
    def virtualenv_location(self):
        # if VIRTUAL_ENV is set, use that.
        if PIPENV_VIRTUALENV:
            return PIPENV_VIRTUALENV

        # Use cached version, if available.
        if self._virtualenv_location:
            return self._virtualenv_location

        # Default mode.
        if not self.is_venv_in_project():
            loc = self._get_virtualenv_location(self.virtualenv_name)
        # The user wants the virtualenv in the project.
        else:
            loc = os.sep.join(
                self.pipfile_location.split(os.sep)[:-1] + ['.venv']
            )
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
            loc = os.sep.join(
                [self.virtualenv_location, 'pipenv-proper-names.txt']
            )
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
            self._pipfile_location = _normalized(loc)
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
        """Parse Pipfile into a TOMLFile and cache it

        (call clear_pipfile_cache() afterwards if mutating)"""
        contents = self.read_pipfile()
        # use full contents to get around str/bytes 2/3 issues
        cache_key = (self.pipfile_location, contents)
        if cache_key not in _pipfile_cache:
            parsed = self._parse_pipfile(contents)
            _pipfile_cache[cache_key] = parsed
        return _pipfile_cache[cache_key]

    def read_pipfile(self):
        # Open the pipfile, read it into memory.
        with io.open(self.pipfile_location) as f:
            contents = f.read()
            self._pipfile_newlines = preferred_newlines(f)

        return contents

    @property
    def pased_pure_pipfile(self):
        contents = self.read_pipfile()

        return self._parse_pipfile(contents)

    def clear_pipfile_cache(self):
        """Clear pipfile cache (e.g., so we can mutate parsed pipfile)"""
        _pipfile_cache.clear()

    def _parse_pipfile(self, contents):
        # If any outline tables are present...
        if ('[packages.' in contents) or ('[dev-packages.' in contents):
            data = toml.loads(contents)
            # Convert all outline tables to inline tables.
            for section in ('packages', 'dev-packages'):
                for package in data.get(section, {}):
                    # Convert things to inline tables — fancy :)
                    if hasattr(data[section][package], 'keys'):
                        _data = data[section][package]
                        data[section][package] = toml._get_empty_inline_table(
                            dict
                        )
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
    def settings(self):
        """A dictionary of the settings added to the Pipfile."""
        return self.parsed_pipfile.get('pipenv', {})

    def has_script(self, name):
        try:
            return name in self.parsed_pipfile['scripts']
        except KeyError:
            return False

    def build_script(self, name, extra_args=None):
        try:
            script = Script.parse(self.parsed_pipfile['scripts'][name])
        except KeyError:
            script = Script(name)
        if extra_args:
            script.extend(extra_args)
        return script

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
        pfile = pipfile.load(self.pipfile_location, inject_env=False)
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
        return self.load_lockfile()

    @property
    def editable_packages(self):
        packages = {
            k: v
            for k, v in self.parsed_pipfile.get('packages', {}).items()
            if is_editable(v)
        }
        return packages

    @property
    def editable_dev_packages(self):
        packages = {
            k: v
            for k, v in self.parsed_pipfile.get('dev-packages', {}).items()
            if is_editable(v)
        }
        return packages

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

        if not len(self.read_pipfile()):
            return True

        return False

    def create_pipfile(self, python=None):
        """Creates the Pipfile, filled with juicy defaults."""
        from .vendor.pip9 import ConfigOptionParser
        config_parser = ConfigOptionParser(name=self.name)
        install = dict(config_parser.get_config_section('install'))
        indexes = install.get('extra-index-url', '').lstrip('\n').split('\n')
        sources = [DEFAULT_SOURCE]
        for i, index in enumerate(indexes):
            if not index:
                continue

            source_name = 'pip_index_{}'.format(i)
            verify_ssl = index.startswith('https')
            sources.append(
                {
                    u'url': index,
                    u'verify_ssl': verify_ssl,
                    u'name': source_name,
                }
            )

        data = {
            u'source': sources,
            # Default packages.
            u'packages': {},
            u'dev-packages': {},
        }
        # Default requires.
        required_python = python
        if not python:
            if self.virtualenv_location:
                required_python = self.which('python', self.virtualenv_location)
            else:
                required_python = self.which('python')
        version = python_version(required_python) or PIPENV_DEFAULT_PYTHON_VERSION
        if version and len(version) >= 3:
            data[u'requires'] = {
                'python_version': version[: len('2.7')]
            }
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
                        data[section][package] = toml._get_empty_inline_table(
                            dict
                        )
                        data[section][package].update(_data)
            formatted_data = toml.dumps(data).rstrip()

        if Path(path).absolute() == Path(self.pipfile_location).absolute():
            newlines = self._pipfile_newlines
        else:
            newlines = DEFAULT_NEWLINES
        formatted_data = cleanup_toml(formatted_data)
        with io.open(path, 'w', newline=newlines) as f:
            f.write(formatted_data)
        # pipfile is mutated!
        self.clear_pipfile_cache()

    def write_lockfile(self, content):
        """Write out the lockfile.
        """
        newlines = self._lockfile_newlines
        s = simplejson.dumps(   # Send Unicode in to guarentee Unicode out.
            content, indent=4, separators=(u',', u': '), sort_keys=True,
        )
        with atomic_open_for_write(self.lockfile_location, newline=newlines) as f:
            f.write(s)
            if not s.endswith(u'\n'):
                f.write(u'\n')  # Write newline at end of document. GH #319.

    @property
    def pipfile_sources(self):
        if 'source' not in self.parsed_pipfile:
            return [DEFAULT_SOURCE]
        # We need to make copies of the source info so we don't
        # accidentally modify the cache. See #2100 where values are
        # written after the os.path.expandvars() call.
        return [
            {k: safe_expandvars(v) for k, v in source.items()}
            for source in self.parsed_pipfile['source']
        ]

    @property
    def sources(self):
        if self.lockfile_exists and hasattr(self.lockfile_content, 'keys'):
            meta_ = self.lockfile_content['_meta']
            sources_ = meta_.get('sources')
            if sources_:
                return sources_

        else:
            return self.pipfile_sources

    def find_source(self, source):
        """given a source, find it.

        source can be a url or an index name.
        """
        if not is_valid_url(source):
            try:
                source = self.get_source(name=source)
            except SourceNotFound:
                source = self.get_source(url=source)
        else:
            source = self.get_source(url=source)
        return source

    def get_source(self, name=None, url=None):
        def find_source(sources, name=None, url=None):
            source = None
            if name:
                source = [s for s in sources if s.get('name') == name]
            elif url:
                source = [s for s in sources if url.startswith(s.get('url'))]
            if source:
                return first(source)

        found_source = find_source(self.sources, name=name, url=url)
        if found_source:
            return found_source
        found_source = find_source(self.pipfile_sources, name=name, url=url)
        if found_source:
            return found_source
        raise SourceNotFound(name or url)

    def get_package_name_in_pipfile(self, package_name, dev=False):
        """Get the equivalent package name in pipfile"""
        key = 'dev-packages' if dev else 'packages'
        section = self.parsed_pipfile.get(key, {})
        package_name = pep423_name(package_name)
        for name in section.keys():
            if pep423_name(name) == package_name:
                return name
        return None

    def remove_package_from_pipfile(self, package_name, dev=False):
        # Read and append Pipfile.
        name = self.get_package_name_in_pipfile(package_name, dev)
        key = 'dev-packages' if dev else 'packages'
        p = self.parsed_pipfile
        if name:
            del p[key][name]
            self.write_toml(p)

    def add_package_to_pipfile(self, package_name, dev=False):
        from .utils import convert_deps_from_pip
        # Read and append Pipfile.
        p = self.parsed_pipfile
        # Don't re-capitalize file URLs or VCSs.
        converted = convert_deps_from_pip(package_name)
        converted = converted[first(k for k in converted.keys())]
        if not (
            is_file(package_name) or is_vcs(converted) or 'path' in converted
        ):
            package_name = pep423_name(package_name)
        key = 'dev-packages' if dev else 'packages'
        # Set empty group if it doesn't exist yet.
        if key not in p:
            p[key] = {}
        package = convert_deps_from_pip(package_name)
        package_name = first(k for k in package.keys())
        name = self.get_package_name_in_pipfile(package_name, dev)
        if name and converted == '*':
            # Skip for wildcard version
            return
        # Add the package to the group.
        p[key][name or package_name] = package[package_name]
        # Write Pipfile.
        self.write_toml(p)

    def add_index_to_pipfile(self, index):
        """Adds a given index to the Pipfile."""
        # Read and append Pipfile.
        p = self.parsed_pipfile
        source = {'url': index, 'verify_ssl': True}
        # Add the package to the group.
        if 'source' not in p:
            p['source'] = [source]
        else:
            p['source'].append(source)
        # Write Pipfile.
        self.write_toml(p)

    def recase_pipfile(self):
        if self.ensure_proper_casing():
            self.write_toml(self.parsed_pipfile)

    def load_lockfile(self, expand_env_vars=True):
        with io.open(self.lockfile_location) as lock:
            j = json.load(lock)
            self._lockfile_newlines = preferred_newlines(lock)
        # lockfile is just a string
        if not j or not hasattr(j, 'keys'):
            return j

        if expand_env_vars:
            # Expand environment variables in Pipfile.lock at runtime.
            for i, source in enumerate(j['_meta']['sources'][:]):
                j['_meta']['sources'][i]['url'] = os.path.expandvars(j['_meta']['sources'][i]['url'])

        return j

    def get_lockfile_hash(self):
        if not os.path.exists(self.lockfile_location):
            return

        lockfile = self.load_lockfile(expand_env_vars=False)
        if '_meta' in lockfile and hasattr(lockfile, 'keys'):
            return lockfile['_meta'].get('hash', {}).get('sha256')
        # Lockfile exists but has no hash at all
        return ''

    def calculate_pipfile_hash(self):
        # Update the lockfile if it is out-of-date.
        p = pipfile.load(self.pipfile_location, inject_env=False)
        return p.hash

    def ensure_proper_casing(self):
        """Ensures proper casing of Pipfile packages"""
        pfile = self.parsed_pipfile
        casing_changed = self.proper_case_section(pfile.get('packages', {}))
        casing_changed |= self.proper_case_section(pfile.get('dev-packages', {}))
        return casing_changed

    def proper_case_section(self, section):
        """Verify proper casing is retrieved, when available, for each
        dependency in the section.
        """
        # Casing for section.
        changed_values = False
        unknown_names = [
            k for k in section.keys() if k not in set(self.proper_names)
        ]
        # Replace each package with proper casing.
        for dep in unknown_names:
            try:
                # Get new casing for package name.
                new_casing = proper_case(dep)
            except IOError:
                # Unable to normalize package name.
                continue

            if new_casing != dep:
                changed_values = True
                self.register_proper_name(new_casing)
                # Replace old value with new value.
                old_value = section[dep]
                section[new_casing] = old_value
                del section[dep]
        # Return whether or not values have been changed.
        return changed_values
