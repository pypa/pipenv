# -*- coding: utf-8 -*-
import io
import json
import os
import re
import sys
import base64
import fnmatch
import hashlib
import contoml
from first import first
from cached_property import cached_property
import pipfile
import pipfile.api
import six
import vistir
import toml

from .cmdparse import Script
from .utils import (
    pep423_name,
    proper_case,
    find_requirements,
    is_editable,
    cleanup_toml,
    is_installable_file,
    is_valid_url,
    normalize_drive,
    python_version,
    safe_expandvars,
    is_star,
    get_workon_home,
    is_virtual_environment,
    looks_like_dir,
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
from requirementslib.utils import is_vcs


def _normalized(p):
    if p is None:
        return None
    loc = vistir.compat.Path(p)
    if loc.is_absolute():
        return normalize_drive(str(loc))
    else:
        try:
            loc = loc.resolve()
        except OSError:
            loc = loc.absolute()
        return normalize_drive(str(loc))


DEFAULT_NEWLINES = u"\n"


class _LockFileEncoder(json.JSONEncoder):
    """A specilized JSON encoder to convert loaded TOML data into a lock file.

    This adds a few characteristics to the encoder:

    * The JSON is always prettified with indents and spaces.
    * PrettyTOML's container elements are seamlessly encodable.
    * The output is always UTF-8-encoded text, never binary, even on Python 2.
    """

    def __init__(self):
        super(_LockFileEncoder, self).__init__(
            indent=4, separators=(",", ": "), sort_keys=True
        )

    def default(self, obj):
        from prettytoml.elements.common import ContainerElement, TokenElement

        if isinstance(obj, (ContainerElement, TokenElement)):
            return obj.primitive_value
        return super(_LockFileEncoder, self).default(obj)

    def encode(self, obj):
        content = super(_LockFileEncoder, self).encode(obj)
        if not isinstance(content, six.text_type):
            content = content.decode("utf-8")
        return content


def preferred_newlines(f):
    if isinstance(f.newlines, six.text_type):
        return f.newlines
    return DEFAULT_NEWLINES


if PIPENV_PIPFILE:
    if not os.path.isfile(PIPENV_PIPFILE):
        raise RuntimeError("Given PIPENV_PIPFILE is not found!")

    else:
        PIPENV_PIPFILE = _normalized(PIPENV_PIPFILE)
# (path, file contents) => TOMLFile
# keeps track of pipfiles that we've seen so we do not need to re-parse 'em
_pipfile_cache = {}


if PIPENV_TEST_INDEX:
    DEFAULT_SOURCE = {
        u"url": PIPENV_TEST_INDEX,
        u"verify_ssl": True,
        u"name": u"custom",
    }
else:
    DEFAULT_SOURCE = {
        u"url": u"https://pypi.org/simple",
        u"verify_ssl": True,
        u"name": u"pypi",
    }

pipfile.api.DEFAULT_SOURCE = DEFAULT_SOURCE


class SourceNotFound(KeyError):
    pass


class Project(object):
    """docstring for Project"""

    _lockfile_encoder = _LockFileEncoder()

    def __init__(self, which=None, python_version=None, chdir=True):
        super(Project, self).__init__()
        self._name = None
        self._virtualenv_location = None
        self._download_location = None
        self._proper_names_db_path = None
        self._pipfile_location = None
        self._pipfile_newlines = DEFAULT_NEWLINES
        self._lockfile_newlines = DEFAULT_NEWLINES
        self._requirements_location = None
        self._original_dir = os.path.abspath(os.curdir)
        self.which = which
        self.python_version = python_version
        # Hack to skip this during pipenv run, or -r.
        if ("run" not in sys.argv) and chdir:
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
            if hasattr(v, "keys"):
                # When a vcs url is gven without editable it only appears as a key
                # Eliminate any vcs, path, or url entries which are not editable
                # Since pip-tools can't do deep resolution on them, even setuptools-installable ones
                if (
                    is_vcs(v)
                    or is_vcs(k)
                    or (is_installable_file(k) or is_installable_file(v))
                    or any(
                        (
                            prefix in v
                            and (os.path.isfile(v[prefix]) or is_valid_url(v[prefix]))
                        )
                        for prefix in ["path", "file"]
                    )
                ):
                    # If they are editable, do resolve them
                    if "editable" not in v:
                        # allow wheels to be passed through
                        if not (
                            hasattr(v, "keys")
                            and v.get("path", v.get("file", "")).endswith(".whl")
                        ):
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
                    any(is_vcs(i) for i in [k, v])
                    or
                    # Then exclude any installable files that are not directories
                    # Because pip-tools can resolve setup.py for example
                    any(is_installable_file(i) for i in [k, v])
                    or
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
            required = self.parsed_pipfile.get("requires", {}).get(
                "python_full_version"
            )
            if not required:
                required = self.parsed_pipfile.get("requires", {}).get("python_version")
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

    def is_venv_in_project(self):
        return PIPENV_VENV_IN_PROJECT or (
            self.project_directory
            and os.path.isdir(os.path.join(self.project_directory, ".venv"))
        )

    @property
    def virtualenv_exists(self):
        # TODO: Decouple project from existence of Pipfile.
        if self.pipfile_exists and os.path.exists(self.virtualenv_location):
            if os.name == "nt":
                extra = ["Scripts", "activate.bat"]
            else:
                extra = ["bin", "activate"]
            return os.path.isfile(os.sep.join([self.virtualenv_location] + extra))

        return False

    def get_location_for_virtualenv(self):
        if self.is_venv_in_project():
            return os.path.join(self.project_directory, ".venv")

        name = self.virtualenv_name
        if self.project_directory:
            venv_path = os.path.join(self.project_directory, ".venv")
            if os.path.exists(venv_path) and not os.path.isdir(".venv"):
                with io.open(venv_path, "r") as f:
                    name = f.read().strip()
                # Assume file's contents is a path if it contains slashes.
                if looks_like_dir(name):
                    return vistir.compat.Path(name).absolute().as_posix()
        return str(get_workon_home().joinpath(name))

    @property
    def working_set(self):
        from .utils import load_path
        sys_path = load_path(self.which("python"))
        import pkg_resources
        return pkg_resources.WorkingSet(sys_path)

    def find_egg(self, egg_dist):
        import site
        from distutils import sysconfig as distutils_sysconfig
        site_packages = distutils_sysconfig.get_python_lib()
        search_filename = "{0}.egg-link".format(egg_dist.project_name)
        try:
            user_site = site.getusersitepackages()
        except AttributeError:
            user_site = site.USER_SITE
        search_locations = [site_packages, user_site]
        for site_directory in search_locations:
                egg = os.path.join(site_directory, search_filename)
                if os.path.isfile(egg):
                    return egg

    def locate_dist(self, dist):
        location = self.find_egg(dist)
        if not location:
            return dist.location

    def dist_is_in_project(self, dist):
        prefix = _normalized(self.env_paths["prefix"])
        location = self.locate_dist(dist)
        if not location:
            return False
        return _normalized(location).startswith(prefix)

    def get_installed_packages(self):
        workingset = self.working_set
        if self.virtualenv_exists:
            packages = [pkg for pkg in workingset if self.dist_is_in_project(pkg)]
        else:
            packages = [pkg for pkg in packages]
        return packages

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
        return re.sub(r'[ $`!*@"\\\r\n\t]', "_", name)[0:42]

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
        venv_name = "{0}-{1}".format(clean_name, encoded_hash)

        # This should work most of the time for
        #   Case-sensitive filesystems,
        #   In-project venv
        #   "Proper" path casing (on non-case-sensitive filesystems).
        if (
            fnmatch.fnmatch("A", "a")
            or self.is_venv_in_project()
            or get_workon_home().joinpath(venv_name).exists()
        ):
            return clean_name, encoded_hash

        # Check for different capitalization of the same project.
        for path in get_workon_home().iterdir():
            if not is_virtual_environment(path):
                continue
            try:
                env_name, hash_ = path.name.rsplit("-", 1)
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
        suffix = "-{0}".format(PIPENV_PYTHON) if PIPENV_PYTHON else ""
        # If the pipfile was located at '/home/user/MY_PROJECT/Pipfile',
        # the name of its virtualenv will be 'my-project-wyUfYPqE'
        return sanitized + "-" + encoded_hash + suffix

    @property
    def virtualenv_location(self):
        # if VIRTUAL_ENV is set, use that.
        if PIPENV_VIRTUALENV:
            return PIPENV_VIRTUALENV

        if not self._virtualenv_location:  # Use cached version, if available.
            assert self.project_directory, "project not created"
            self._virtualenv_location = self.get_location_for_virtualenv()
        return self._virtualenv_location

    @property
    def virtualenv_src_location(self):
        if self.virtualenv_location:
            loc = os.sep.join([self.virtualenv_location, "src"])
        else:
            loc = os.sep.join([self.project_directory, "src"])
        vistir.path.mkdir_p(loc)
        return loc

    @property
    def download_location(self):
        if self._download_location is None:
            loc = os.sep.join([self.virtualenv_location, "downloads"])
            self._download_location = loc
        # Create the directory, if it doesn't exist.
        vistir.path.mkdir_p(self._download_location)
        return self._download_location

    @property
    def proper_names_db_path(self):
        if self._proper_names_db_path is None:
            self._proper_names_db_path = vistir.compat.Path(
                self.virtualenv_location, "pipenv-proper-names.txt"
            )
        self._proper_names_db_path.touch()  # Ensure the file exists.
        return self._proper_names_db_path

    @property
    def proper_names(self):
        with self.proper_names_db_path.open() as f:
            return f.read().splitlines()

    def register_proper_name(self, name):
        """Registers a proper name to the database."""
        with self.proper_names_db_path.open("a") as f:
            f.write(u"{0}\n".format(name))

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

    def clear_pipfile_cache(self):
        """Clear pipfile cache (e.g., so we can mutate parsed pipfile)"""
        _pipfile_cache.clear()

    def _parse_pipfile(self, contents):
        # If any outline tables are present...
        if ("[packages." in contents) or ("[dev-packages." in contents):
            data = toml.loads(contents)
            # Convert all outline tables to inline tables.
            for section in ("packages", "dev-packages"):
                for package in data.get(section, {}):
                    # Convert things to inline tables — fancy :)
                    if hasattr(data[section][package], "keys"):
                        _data = data[section][package]
                        data[section][package] = toml.TomlDecoder().get_empty_inline_table()
                        data[section][package].update(_data)
            toml_encoder = toml.TomlEncoder(preserve=True)
            # We lose comments here, but it's for the best.)
            try:
                return contoml.loads(toml.dumps(data, encoder=toml_encoder))

            except RuntimeError:
                return toml.loads(toml.dumps(data, encoder=toml_encoder))

        else:
            # Fallback to toml parser, for large files.
            try:
                return contoml.loads(contents)

            except Exception:
                return toml.loads(contents)

    @property
    def settings(self):
        """A dictionary of the settings added to the Pipfile."""
        return self.parsed_pipfile.get("pipenv", {})

    def has_script(self, name):
        try:
            return name in self.parsed_pipfile["scripts"]
        except KeyError:
            return False

    def build_script(self, name, extra_args=None):
        try:
            script = Script.parse(self.parsed_pipfile["scripts"][name])
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
            p["pipenv"] = settings
            # Write the changes to disk.
            self.write_toml(p)

    @property
    def _lockfile(self):
        """Pipfile.lock divided by PyPI and external dependencies."""
        pfile = pipfile.load(self.pipfile_location, inject_env=False)
        lockfile = json.loads(pfile.lock())
        for section in ("default", "develop"):
            lock_section = lockfile.get(section, {})
            for key in list(lock_section.keys()):
                norm_key = pep423_name(key)
                lockfile[section][norm_key] = lock_section.pop(key)
        return lockfile

    @property
    def lockfile_location(self):
        return "{0}.lock".format(self.pipfile_location)

    @property
    def lockfile_exists(self):
        return os.path.isfile(self.lockfile_location)

    @property
    def lockfile_content(self):
        return self.load_lockfile()

    def _get_editable_packages(self, dev=False):
        section = "dev-packages" if dev else "packages"
        packages = {
            k: v
            for k, v in self.parsed_pipfile.get(section, {}).items()
            if is_editable(v)
        }
        return packages

    def _get_vcs_packages(self, dev=False):
        section = "dev-packages" if dev else "packages"
        packages = {
            k: v
            for k, v in self.parsed_pipfile.get(section, {}).items()
            if is_vcs(v) or is_vcs(k)
        }
        return packages or {}

    @property
    def editable_packages(self):
        return self._get_editable_packages(dev=False)

    @property
    def editable_dev_packages(self):
        return self._get_editable_packages(dev=True)

    @property
    def vcs_packages(self):
        """Returns a list of VCS packages, for not pip-tools to consume."""
        return self._get_vcs_packages(dev=False)

    @property
    def vcs_dev_packages(self):
        """Returns a list of VCS packages, for not pip-tools to consume."""
        return self._get_vcs_packages(dev=True)

    @property
    def all_packages(self):
        """Returns a list of all packages."""
        p = dict(self.parsed_pipfile.get("dev-packages", {}))
        p.update(self.parsed_pipfile.get("packages", {}))
        return p

    @property
    def packages(self):
        """Returns a list of packages, for pip-tools to consume."""
        return self._build_package_list("packages")

    @property
    def dev_packages(self):
        """Returns a list of dev-packages, for pip-tools to consume."""
        return self._build_package_list("dev-packages")

    def touch_pipfile(self):
        """Simply touches the Pipfile, for later use."""
        with open("Pipfile", "a"):
            os.utime("Pipfile", None)

    @property
    def pipfile_is_empty(self):
        if not self.pipfile_exists:
            return True

        if not len(self.read_pipfile()):
            return True

        return False

    def create_pipfile(self, python=None):
        """Creates the Pipfile, filled with juicy defaults."""
        from .patched.notpip._internal import ConfigOptionParser
        from .patched.notpip._internal.cmdoptions import make_option_group, index_group

        config_parser = ConfigOptionParser(name=self.name)
        config_parser.add_option_group(make_option_group(index_group, config_parser))
        install = config_parser.option_groups[0]
        indexes = (
            " ".join(install.get_option("--extra-index-url").default)
            .lstrip("\n")
            .split("\n")
        )
        sources = [DEFAULT_SOURCE]
        for i, index in enumerate(indexes):
            if not index:
                continue

            source_name = "pip_index_{}".format(i)
            verify_ssl = index.startswith("https")
            sources.append(
                {u"url": index, u"verify_ssl": verify_ssl, u"name": source_name}
            )

        data = {
            u"source": sources,
            # Default packages.
            u"packages": {},
            u"dev-packages": {},
        }
        # Default requires.
        required_python = python
        if not python:
            if self.virtualenv_location:
                required_python = self.which("python", self.virtualenv_location)
            else:
                required_python = self.which("python")
        version = python_version(required_python) or PIPENV_DEFAULT_PYTHON_VERSION
        if version and len(version) >= 3:
            data[u"requires"] = {"python_version": version[: len("2.7")]}
        self.write_toml(data, "Pipfile")

    def write_toml(self, data, path=None):
        """Writes the given data structure out as TOML."""
        if path is None:
            path = self.pipfile_location
        try:
            formatted_data = contoml.dumps(data).rstrip()
        except Exception:
            for section in ("packages", "dev-packages"):
                for package in data.get(section, {}):
                    # Convert things to inline tables — fancy :)
                    if hasattr(data[section][package], "keys"):
                        _data = data[section][package]
                        data[section][package] = toml.TomlDecoder().get_empty_inline_table()
                        data[section][package].update(_data)
            formatted_data = toml.dumps(data).rstrip()

        if (
            vistir.compat.Path(path).absolute()
            == vistir.compat.Path(self.pipfile_location).absolute()
        ):
            newlines = self._pipfile_newlines
        else:
            newlines = DEFAULT_NEWLINES
        formatted_data = cleanup_toml(formatted_data)
        with io.open(path, "w", newline=newlines) as f:
            f.write(formatted_data)
        # pipfile is mutated!
        self.clear_pipfile_cache()

    def write_lockfile(self, content):
        """Write out the lockfile.
        """
        s = self._lockfile_encoder.encode(content)
        open_kwargs = {"newline": self._lockfile_newlines, "encoding": "utf-8"}
        with vistir.contextmanagers.atomic_open_for_write(
            self.lockfile_location, **open_kwargs
        ) as f:
            f.write(s)
            # Write newline at end of document. GH-319.
            # Only need '\n' here; the file object handles the rest.
            if not s.endswith(u"\n"):
                f.write(u"\n")

    @property
    def pipfile_sources(self):
        if "source" not in self.parsed_pipfile:
            return [DEFAULT_SOURCE]
        # We need to make copies of the source info so we don't
        # accidentally modify the cache. See #2100 where values are
        # written after the os.path.expandvars() call.
        return [
            {k: safe_expandvars(v) for k, v in source.items()}
            for source in self.parsed_pipfile["source"]
        ]

    @property
    def sources(self):
        if self.lockfile_exists and hasattr(self.lockfile_content, "keys"):
            meta_ = self.lockfile_content["_meta"]
            sources_ = meta_.get("sources")
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
                source = [s for s in sources if s.get("name") == name]
            elif url:
                source = [s for s in sources if url.startswith(s.get("url"))]
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
        key = "dev-packages" if dev else "packages"
        section = self.parsed_pipfile.get(key, {})
        package_name = pep423_name(package_name)
        for name in section.keys():
            if pep423_name(name) == package_name:
                return name
        return None

    def remove_package_from_pipfile(self, package_name, dev=False):
        # Read and append Pipfile.
        name = self.get_package_name_in_pipfile(package_name, dev)
        key = "dev-packages" if dev else "packages"
        p = self.parsed_pipfile
        if name:
            del p[key][name]
            self.write_toml(p)

    def add_package_to_pipfile(self, package, dev=False):
        from .vendor.requirementslib import Requirement

        # Read and append Pipfile.
        p = self.parsed_pipfile
        # Don't re-capitalize file URLs or VCSs.
        if not isinstance(package, Requirement):
            package = Requirement.from_line(package.strip())
        _, converted = package.pipfile_entry
        key = "dev-packages" if dev else "packages"
        # Set empty group if it doesn't exist yet.
        if key not in p:
            p[key] = {}
        name = self.get_package_name_in_pipfile(package.name, dev)
        if name and is_star(converted):
            # Skip for wildcard version
            return
        # Add the package to the group.
        p[key][name or package.normalized_name] = converted
        # Write Pipfile.
        self.write_toml(p)

    def src_name_from_url(self, index_url):
        name, _, tld_guess = six.moves.urllib.parse.urlsplit(index_url).netloc.rpartition(
            "."
        )
        src_name = name.replace(".", "")
        try:
            self.get_source(name=src_name)
        except SourceNotFound:
            name = src_name
        else:
            from random import randint
            name = "{0}-{1}".format(src_name, randint(1, 1000))
        return name

    def add_index_to_pipfile(self, index, verify_ssl=True):
        """Adds a given index to the Pipfile."""
        # Read and append Pipfile.
        p = self.parsed_pipfile
        try:
            self.get_source(url=index)
        except SourceNotFound:
            source = {"url": index, "verify_ssl": verify_ssl}
        else:
            return
        source["name"] = self.src_name_from_url(index)
        # Add the package to the group.
        if "source" not in p:
            p["source"] = [source]
        else:
            p["source"].append(source)
        # Write Pipfile.
        self.write_toml(p)

    def recase_pipfile(self):
        if self.ensure_proper_casing():
            self.write_toml(self.parsed_pipfile)

    def load_lockfile(self, expand_env_vars=True):
        with io.open(self.lockfile_location, encoding="utf-8") as lock:
            j = json.load(lock)
            self._lockfile_newlines = preferred_newlines(lock)
        # lockfile is just a string
        if not j or not hasattr(j, "keys"):
            return j

        if expand_env_vars:
            # Expand environment variables in Pipfile.lock at runtime.
            for i, source in enumerate(j["_meta"]["sources"][:]):
                j["_meta"]["sources"][i]["url"] = os.path.expandvars(
                    j["_meta"]["sources"][i]["url"]
                )

        return j

    def get_lockfile_hash(self):
        if not os.path.exists(self.lockfile_location):
            return

        try:
            lockfile = self.load_lockfile(expand_env_vars=False)
        except ValueError:
            # Lockfile corrupted
            return ""
        if "_meta" in lockfile and hasattr(lockfile, "keys"):
            return lockfile["_meta"].get("hash", {}).get("sha256")
        # Lockfile exists but has no hash at all
        return ""

    def calculate_pipfile_hash(self):
        # Update the lockfile if it is out-of-date.
        p = pipfile.load(self.pipfile_location, inject_env=False)
        return p.hash

    def ensure_proper_casing(self):
        """Ensures proper casing of Pipfile packages"""
        pfile = self.parsed_pipfile
        casing_changed = self.proper_case_section(pfile.get("packages", {}))
        casing_changed |= self.proper_case_section(pfile.get("dev-packages", {}))
        return casing_changed

    def proper_case_section(self, section):
        """Verify proper casing is retrieved, when available, for each
        dependency in the section.
        """
        # Casing for section.
        changed_values = False
        unknown_names = [k for k in section.keys() if k not in set(self.proper_names)]
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

    @property
    def _pyversion(self):
        include_dir = vistir.compat.Path(self.virtualenv_location) / "include"
        python_path = next(iter(list(include_dir.iterdir())), None)
        if python_path and python_path.name.startswith("python"):
            python_version = python_path.name.replace("python", "")
            py_version_short, abiflags = python_version[:3], python_version[3:]
            return {"py_version_short": py_version_short, "abiflags": abiflags}
        return {}

    @property
    def env_paths(self):
        import sysconfig
        location = self.virtualenv_location if self.virtualenv_location else sys.prefix
        prefix = vistir.compat.Path(location).as_posix()
        scheme = sysconfig._get_default_scheme()
        config = {
            "base": prefix,
            "installed_base": prefix,
            "platbase": prefix,
            "installed_platbase": prefix
        }
        config.update(self._pyversion)
        paths = {
            k: v.format(**config)
            for k, v in sysconfig._INSTALL_SCHEMES[scheme].items()
        }
        if "prefix" not in paths:
            paths["prefix"] = prefix
        return paths
