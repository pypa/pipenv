from __future__ import annotations

import base64
import fnmatch
import hashlib
import io
import json
import operator
import os
import re
import sys
import urllib.parse
from json.decoder import JSONDecodeError
from pathlib import Path

import click

from pipenv.cmdparse import Script
from pipenv.environment import Environment
from pipenv.environments import Setting, is_in_virtualenv, normalize_pipfile_path
from pipenv.patched.pip._internal.commands.install import InstallCommand
from pipenv.patched.pip._internal.configuration import Configuration
from pipenv.patched.pip._internal.exceptions import ConfigurationError
from pipenv.patched.pip._vendor import pkg_resources
from pipenv.utils.constants import is_type_checking
from pipenv.utils.dependencies import (
    get_canonical_names,
    is_editable,
    is_star,
    pep423_name,
    python_version,
)
from pipenv.utils.internet import get_url_name, is_pypi_url, is_valid_url, proper_case
from pipenv.utils.shell import (
    find_requirements,
    find_windows_executable,
    get_workon_home,
    is_virtual_environment,
    load_path,
    looks_like_dir,
    safe_expandvars,
    system_which,
)
from pipenv.utils.toml import cleanup_toml, convert_toml_outline_tables
from pipenv.vendor import plette, toml, tomlkit, vistir
from pipenv.vendor.requirementslib.models.utils import get_default_pyproject_backend

try:
    # this is only in Python3.8 and later
    from functools import cached_property
except ImportError:
    # eventually distlib will remove cached property when they drop Python3.7
    from pipenv.patched.pip._vendor.distlib.util import cached_property

if is_type_checking():
    from typing import Dict, List, Optional, Set, Text, Tuple, Union

    TSource = Dict[Text, Union[Text, bool]]
    TPackageEntry = Dict[str, Union[bool, str, List[str]]]
    TPackage = Dict[str, TPackageEntry]
    TScripts = Dict[str, str]
    TPipenv = Dict[str, bool]
    TPipfile = Dict[str, Union[TPackage, TScripts, TPipenv, List[TSource]]]


DEFAULT_NEWLINES = "\n"
NON_CATEGORY_SECTIONS = {
    "pipenv",
    "requires",
    "scripts",
    "source",
}


class _LockFileEncoder(json.JSONEncoder):
    """A specilized JSON encoder to convert loaded TOML data into a lock file.

    This adds a few characteristics to the encoder:

    * The JSON is always prettified with indents and spaces.
    * TOMLKit's container elements are seamlessly encodable.
    * The output is always UTF-8-encoded text, never binary, even on Python 2.
    """

    def __init__(self):
        super(_LockFileEncoder, self).__init__(
            indent=4, separators=(",", ": "), sort_keys=True
        )

    def default(self, obj):
        if isinstance(obj, Path):
            obj = obj.as_posix()
        return super(_LockFileEncoder, self).default(obj)

    def encode(self, obj):
        content = super(_LockFileEncoder, self).encode(obj)
        if not isinstance(content, str):
            content = content.decode("utf-8")
        return content


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


# (path, file contents) => TOMLFile
# keeps track of pipfiles that we've seen so we do not need to re-parse 'em
_pipfile_cache = {}


class SourceNotFound(KeyError):
    pass


class Project:
    """docstring for Project"""

    _lockfile_encoder = _LockFileEncoder()

    def __init__(self, python_version=None, chdir=True):
        self._name = None
        self._virtualenv_location = None
        self._download_location = None
        self._proper_names_db_path = None
        self._pipfile_location = None
        self._pipfile_newlines = DEFAULT_NEWLINES
        self._lockfile_newlines = DEFAULT_NEWLINES
        self._requirements_location = None
        self._original_dir = os.path.abspath(os.curdir)
        self._environment = None
        self._build_system = {"requires": ["setuptools", "wheel"]}
        self.python_version = python_version
        self.s = Setting()
        # Load Pip configuration and get items
        self.configuration = Configuration(isolated=False, load_only=None)
        self.configuration.load()
        pip_conf_indexes = []
        for section_key, value in self.configuration.items():
            key_parts = section_key.split(".", 1)
            if key_parts[1] == "index-url":
                try:
                    trusted_hosts = self.configuration.get_value(
                        f"{key_parts[0]}.trusted-host"
                    )
                except ConfigurationError:
                    trusted_hosts = []
                pip_conf_indexes.append(
                    {
                        "url": value,
                        "verify_ssl": not any(
                            trusted_host in value for trusted_host in trusted_hosts
                        )
                        and "https://" in value,
                        "name": f"pip_conf_index_{key_parts[0]}",
                    }
                )

        if pip_conf_indexes:
            self.default_source = None
            for pip_conf_index in pip_conf_indexes:
                if self.default_source is None:
                    self.default_source = pip_conf_index
                if is_pypi_url(pip_conf_index["url"]):
                    self.default_source = pip_conf_index
            pip_conf_indexes.remove(self.default_source)
        elif self.s.PIPENV_TEST_INDEX:
            self.default_source = {
                "url": self.s.PIPENV_TEST_INDEX,
                "verify_ssl": True,
                "name": "custom",
            }
        else:
            self.default_source = {
                "url": "https://pypi.org/simple",
                "verify_ssl": True,
                "name": "pypi",
            }

        default_sources_toml = f"[[source]]\n{toml.dumps(self.default_source)}"
        for pip_conf_index in pip_conf_indexes:
            default_sources_toml += f"\n\n[[source]]\n{toml.dumps(pip_conf_index)}"
        plette.pipfiles.DEFAULT_SOURCE_TOML = default_sources_toml

        # Hack to skip this during pipenv run, or -r.
        if ("run" not in sys.argv) and chdir:
            try:
                os.chdir(self.project_directory)
            except (TypeError, AttributeError):
                pass

    def path_to(self, p: str) -> str:
        """Returns the absolute path to a given relative path."""
        if os.path.isabs(p):
            return p

        return os.sep.join([self._original_dir, p])

    def get_pipfile_section(self, section):
        """Returns the details from the section of the Project's Pipfile."""
        return self.parsed_pipfile.get(section, {})

    def get_package_categories(self, for_lockfile=False):
        """Ensure we get only package categories and that the default packages section is first."""
        categories = set(self.parsed_pipfile.keys())
        package_categories = (
            categories - NON_CATEGORY_SECTIONS - {"packages", "dev-packages"}
        )
        if for_lockfile:
            return ["default", "develop"] + list(package_categories)
        else:
            return ["packages", "dev-packages"] + list(package_categories)

    @property
    def name(self) -> str:
        if self._name is None:
            self._name = self.pipfile_location.split(os.sep)[-2]
        return self._name

    @property
    def pipfile_exists(self) -> bool:
        return os.path.isfile(self.pipfile_location)

    @property
    def required_python_version(self) -> str:
        if self.pipfile_exists:
            required = self.parsed_pipfile.get("requires", {}).get("python_full_version")
            if not required:
                required = self.parsed_pipfile.get("requires", {}).get("python_version")
            if required != "*":
                return required

    @property
    def project_directory(self) -> str:
        return os.path.abspath(os.path.join(self.pipfile_location, os.pardir))

    @property
    def requirements_exists(self) -> bool:
        return bool(self.requirements_location)

    def is_venv_in_project(self) -> bool:
        if self.s.PIPENV_VENV_IN_PROJECT is False:
            return False
        return self.s.PIPENV_VENV_IN_PROJECT or (
            self.project_directory
            and os.path.isdir(os.path.join(self.project_directory, ".venv"))
        )

    @property
    def virtualenv_exists(self) -> bool:
        if os.path.exists(self.virtualenv_location):
            if os.name == "nt":
                extra = ["Scripts", "activate.bat"]
            else:
                extra = ["bin", "activate"]
            return os.path.isfile(os.sep.join([self.virtualenv_location] + extra))

        return False

    def get_location_for_virtualenv(self) -> str:
        # If there's no project yet, set location based on config.
        if not self.project_directory:
            if self.is_venv_in_project():
                return os.path.abspath(".venv")
            return str(get_workon_home().joinpath(self.virtualenv_name))

        dot_venv = os.path.join(self.project_directory, ".venv")

        # If there's no .venv in project root, set location based on config.
        if not os.path.exists(dot_venv):
            if self.is_venv_in_project():
                return dot_venv
            return str(get_workon_home().joinpath(self.virtualenv_name))

        # If .venv in project root is a directory, use it.
        if os.path.isdir(dot_venv):
            return dot_venv

        # Now we assume .venv in project root is a file. Use its content.
        with io.open(dot_venv) as f:
            name = f.read().strip()

        # If .venv file is empty, set location based on config.
        if not name:
            return str(get_workon_home().joinpath(self.virtualenv_name))

        # If content looks like a path, use it as a relative path.
        # Otherwise, use directory named after content in WORKON_HOME.
        if looks_like_dir(name):
            path = Path(self.project_directory, name)
            return path.absolute().as_posix()
        return str(get_workon_home().joinpath(name))

    @property
    def working_set(self) -> pkg_resources.WorkingSet:
        sys_path = load_path(self.which("python"))
        return pkg_resources.WorkingSet(sys_path)

    @property
    def installed_packages(self):
        return self.environment.get_installed_packages()

    @property
    def installed_package_names(self) -> List[str]:
        return get_canonical_names([pkg.key for pkg in self.installed_packages])

    @property
    def lockfile_package_names(self) -> Dict[str, Set[str]]:
        results = {
            "combined": {},
        }
        for category in self.get_package_categories(for_lockfile=True):
            category_packages = get_canonical_names(
                self.lockfile_content[category].keys()
            )
            results[category] = set(category_packages)
            results["combined"] = results["combined"] | category_packages
        return results

    @property
    def pipfile_package_names(self) -> Dict[str, Set[str]]:
        result = {}
        combined = set()
        for category in self.get_package_categories():
            packages = self.get_pipfile_section(category)
            keys = get_canonical_names(packages.keys())
            combined |= keys
            result[category] = keys
        result["combined"] = combined
        return result

    def get_environment(self, allow_global: bool = False) -> Environment:
        is_venv = is_in_virtualenv()
        if allow_global and not is_venv:
            prefix = sys.prefix
            python = sys.executable
        else:
            prefix = self.virtualenv_location
            python = None
        sources = self.sources if self.sources else [self.default_source]
        environment = Environment(
            prefix=prefix,
            python=python,
            is_venv=is_venv,
            sources=sources,
            pipfile=self.parsed_pipfile,
            project=self,
        )
        return environment

    @property
    def environment(self) -> Environment:
        if not self._environment:
            allow_global = self.s.PIPENV_USE_SYSTEM
            self._environment = self.get_environment(allow_global=allow_global)
        return self._environment

    def get_outdated_packages(self) -> List[pkg_resources.Distribution]:
        return self.environment.get_outdated_packages(pre=self.pipfile.get("pre", False))

    @classmethod
    def _sanitize(cls, name: str) -> Tuple[str, str]:
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
        return re.sub(r'[ &$`!*@"()\[\]\\\r\n\t]', "_", name)[0:42]

    def _get_virtualenv_hash(self, name: str) -> str:
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
            not fnmatch.fnmatch("A", "a")
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
    def virtualenv_name(self) -> str:
        custom_name = self.s.PIPENV_CUSTOM_VENV_NAME
        if custom_name:
            return custom_name
        sanitized, encoded_hash = self._get_virtualenv_hash(self.name)
        suffix = ""
        if self.s.PIPENV_PYTHON:
            if os.path.isabs(self.s.PIPENV_PYTHON):
                suffix = "-{0}".format(os.path.basename(self.s.PIPENV_PYTHON))
            else:
                suffix = "-{0}".format(self.s.PIPENV_PYTHON)

        # If the pipfile was located at '/home/user/MY_PROJECT/Pipfile',
        # the name of its virtualenv will be 'my-project-wyUfYPqE'
        return sanitized + "-" + encoded_hash + suffix

    @property
    def virtualenv_location(self) -> str:
        # if VIRTUAL_ENV is set, use that.
        virtualenv_env = os.getenv("VIRTUAL_ENV")
        if (
            "PIPENV_ACTIVE" not in os.environ
            and not self.s.PIPENV_IGNORE_VIRTUALENVS
            and virtualenv_env
        ):
            return virtualenv_env

        if not self._virtualenv_location:  # Use cached version, if available.
            assert self.project_directory, "project not created"
            self._virtualenv_location = self.get_location_for_virtualenv()
        return self._virtualenv_location

    @property
    def virtualenv_src_location(self) -> str:
        if self.virtualenv_location:
            loc = os.sep.join([self.virtualenv_location, "src"])
        else:
            loc = os.sep.join([self.project_directory, "src"])
        os.makedirs(loc, exist_ok=True)
        return loc

    @property
    def download_location(self) -> str:
        if self._download_location is None:
            loc = os.sep.join([self.virtualenv_location, "downloads"])
            self._download_location = loc
        # Create the directory, if it doesn't exist.
        os.makedirs(self._download_location, exist_ok=True)
        return self._download_location

    @property
    def proper_names_db_path(self) -> str:
        if self._proper_names_db_path is None:
            self._proper_names_db_path = Path(
                self.virtualenv_location, "pipenv-proper-names.txt"
            )
        self._proper_names_db_path.touch()  # Ensure the file exists.
        return self._proper_names_db_path

    @property
    def proper_names(self) -> str:
        with self.proper_names_db_path.open() as f:
            return f.read().splitlines()

    def register_proper_name(self, name: str) -> None:
        """Registers a proper name to the database."""
        with self.proper_names_db_path.open("a") as f:
            f.write("{0}\n".format(name))

    @property
    def pipfile_location(self) -> str:

        from pipenv.utils.pipfile import find_pipfile

        if self.s.PIPENV_PIPFILE:
            return self.s.PIPENV_PIPFILE

        if self._pipfile_location is None:
            try:
                loc = find_pipfile(max_depth=self.s.PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = "Pipfile"
            self._pipfile_location = normalize_pipfile_path(loc)
        return self._pipfile_location

    @property
    def requirements_location(self) -> Optional[str]:
        if self._requirements_location is None:
            try:
                loc = find_requirements(max_depth=self.s.PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = None
            self._requirements_location = loc
        return self._requirements_location

    @property
    def parsed_pipfile(self) -> Union[tomlkit.toml_document.TOMLDocument, TPipfile]:
        """Parse Pipfile into a TOMLFile and cache it

        (call clear_pipfile_cache() afterwards if mutating)"""
        contents = self.read_pipfile()
        # use full contents to get around str/bytes 2/3 issues
        cache_key = (self.pipfile_location, contents)
        if cache_key not in _pipfile_cache:
            parsed = self._parse_pipfile(contents)
            _pipfile_cache[cache_key] = parsed
        return _pipfile_cache[cache_key]

    def read_pipfile(self) -> str:
        # Open the pipfile, read it into memory.
        if not self.pipfile_exists:
            return ""
        with io.open(self.pipfile_location) as f:
            contents = f.read()
            self._pipfile_newlines = preferred_newlines(f)

        return contents

    def clear_pipfile_cache(self) -> None:
        """Clear pipfile cache (e.g., so we can mutate parsed pipfile)"""
        _pipfile_cache.clear()

    def _parse_pipfile(
        self, contents: str
    ) -> Union[tomlkit.toml_document.TOMLDocument, TPipfile]:
        try:
            return tomlkit.parse(contents)
        except Exception:
            # We lose comments here, but it's for the best.)
            # Fallback to toml parser, for large files.
            return toml.loads(contents)

    def _read_pyproject(self) -> None:
        pyproject = self.path_to("pyproject.toml")
        if os.path.exists(pyproject):
            self._pyproject = toml.load(pyproject)
            build_system = self._pyproject.get("build-system", None)
            if not os.path.exists(self.path_to("setup.py")):
                if not build_system or not build_system.get("requires"):
                    build_system = {
                        "requires": ["setuptools>=40.8.0", "wheel"],
                        "build-backend": get_default_pyproject_backend(),
                    }
                self._build_system = build_system

    @property
    def build_requires(self) -> List[str]:
        return self._build_system.get("requires", ["setuptools>=40.8.0", "wheel"])

    @property
    def build_backend(self) -> str:
        return self._build_system.get("build-backend", get_default_pyproject_backend())

    @property
    def settings(self) -> Union[tomlkit.items.Table, Dict[str, Union[str, bool]]]:
        """A dictionary of the settings added to the Pipfile."""
        return self.parsed_pipfile.get("pipenv", {})

    def has_script(self, name: str) -> bool:
        try:
            return name in self.parsed_pipfile["scripts"]
        except KeyError:
            return False

    def build_script(self, name: str, extra_args: Optional[List[str]] = None) -> Script:
        try:
            script = Script.parse(self.parsed_pipfile["scripts"][name])
        except KeyError:
            script = Script(name)
        if extra_args:
            script.extend(extra_args)
        return script

    def update_settings(self, d: Dict[str, Union[str, bool]]) -> None:
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

    def _lockfile(self, categories=None):
        """Pipfile.lock divided by PyPI and external dependencies."""
        lockfile_loaded = False
        if self.lockfile_exists:
            try:
                lockfile = self.load_lockfile(expand_env_vars=False)
                lockfile_loaded = True
            except Exception:
                pass
        if not lockfile_loaded:
            with open(self.pipfile_location) as pf:
                lockfile = plette.Lockfile.with_meta_from(
                    plette.Pipfile.load(pf), categories=categories
                )
                lockfile = lockfile._data

        if categories is None:
            categories = self.get_package_categories(for_lockfile=True)
        for category in categories:
            lock_section = lockfile.get(category)
            if lock_section is None:
                lockfile[category] = lock_section = {}
            for key in list(lock_section.keys()):
                norm_key = pep423_name(key)
                specifier = lock_section[key]
                del lock_section[key]
                lockfile[category][norm_key] = specifier

        return lockfile

    @property
    def _pipfile(self):
        from .vendor.requirementslib.models.pipfile import Pipfile as ReqLibPipfile

        pf = ReqLibPipfile.load(self.pipfile_location)
        return pf

    @property
    def lockfile_location(self):
        return "{0}.lock".format(self.pipfile_location)

    @property
    def lockfile_exists(self):
        return os.path.isfile(self.lockfile_location)

    @property
    def lockfile_content(self):
        return self.load_lockfile()

    def get_editable_packages(self, category):
        packages = {
            k: v
            for k, v in self.parsed_pipfile.get(category, {}).items()
            if is_editable(v)
        }
        return packages

    def _get_vcs_packages(self, dev=False):
        from pipenv.vendor.requirementslib.utils import is_vcs

        section = "dev-packages" if dev else "packages"
        packages = {
            k: v
            for k, v in self.parsed_pipfile.get(section, {}).items()
            if is_vcs(v) or is_vcs(k)
        }
        return packages or {}

    @property
    def all_packages(self):
        """Returns a list of all packages."""
        packages = {}
        for category in self.get_package_categories():
            packages.update(self.parsed_pipfile.get(category, {}))
        return packages

    @property
    def packages(self):
        """Returns a list of packages."""
        return self.get_pipfile_section("packages")

    @property
    def dev_packages(self):
        """Returns a list of dev-packages."""
        return self.get_pipfile_section("dev-packages")

    @property
    def pipfile_is_empty(self):
        if not self.pipfile_exists:
            return True

        if not self.read_pipfile():
            return True

        return False

    def create_pipfile(self, python=None):
        """Creates the Pipfile, filled with juicy defaults."""
        # Inherit the pip's index configuration of install command.
        command = InstallCommand(name="InstallCommand", summary="pip Install command.")
        indexes = command.cmd_opts.get_option("--extra-index-url").default
        sources = [self.default_source]
        for i, index in enumerate(indexes):
            if not index:
                continue

            source_name = "pip_index_{}".format(i)
            verify_ssl = index.startswith("https")
            sources.append({"url": index, "verify_ssl": verify_ssl, "name": source_name})

        data = {
            "source": sources,
            # Default packages.
            "packages": {},
            "dev-packages": {},
        }
        # Default requires.
        required_python = python
        if not python:
            if self.virtualenv_location:
                required_python = self.which("python", self.virtualenv_location)
            else:
                required_python = self.which("python")
        version = python_version(required_python) or self.s.PIPENV_DEFAULT_PYTHON_VERSION
        if version:
            data["requires"] = {"python_version": ".".join(version.split(".")[:2])}
        if python and version and len(version.split(".")) > 2:
            data["requires"].update({"python_full_version": version})
        self.write_toml(data)

    @classmethod
    def populate_source(cls, source):
        """Derive missing values of source from the existing fields."""
        # Only URL parameter is mandatory, let the KeyError be thrown.
        if "name" not in source:
            source["name"] = get_url_name(source["url"])
        if "verify_ssl" not in source:
            source["verify_ssl"] = "https://" in source["url"]
        if not isinstance(source["verify_ssl"], bool):
            source["verify_ssl"] = str(source["verify_ssl"]).lower() == "true"
        return source

    def get_or_create_lockfile(self, categories, from_pipfile=False):
        from pipenv.vendor.requirementslib.models.lockfile import (
            Lockfile as Req_Lockfile,
        )

        if from_pipfile and self.pipfile_exists:
            lockfile_dict = {}
            categories = self.get_package_categories(for_lockfile=True)
            _lockfile = self._lockfile(categories=categories)
            for category in categories:
                lockfile_dict[category] = _lockfile.get(category, {}).copy()
            lockfile_dict.update({"_meta": self.get_lockfile_meta()})
            lockfile = Req_Lockfile.from_data(
                path=self.lockfile_location, data=lockfile_dict, meta_from_project=False
            )
        elif self.lockfile_exists:
            try:
                lockfile = Req_Lockfile.load(self.lockfile_location)
            except OSError:
                lockfile = Req_Lockfile.from_data(
                    self.lockfile_location, self.lockfile_content
                )
        else:
            lockfile = Req_Lockfile.from_data(
                path=self.lockfile_location,
                data=self._lockfile(),
                meta_from_project=False,
            )
        if lockfile._lockfile is not None:
            return lockfile
        if self.lockfile_exists and self.lockfile_content:
            lockfile_dict = self.lockfile_content.copy()
            sources = lockfile_dict.get("_meta", {}).get("sources", [])
            if not sources:
                sources = self.pipfile_sources(expand_vars=False)
            elif not isinstance(sources, list):
                sources = [sources]
            lockfile_dict["_meta"]["sources"] = [self.populate_source(s) for s in sources]
            _created_lockfile = Req_Lockfile.from_data(
                path=self.lockfile_location, data=lockfile_dict, meta_from_project=False
            )
            lockfile._lockfile = lockfile.projectfile.model = _created_lockfile
            return lockfile
        else:
            return self.get_or_create_lockfile(categories=categories, from_pipfile=True)

    def get_lockfile_meta(self):
        from .vendor.plette.lockfiles import PIPFILE_SPEC_CURRENT

        if "source" in self.parsed_pipfile:
            sources = [dict(source) for source in self.parsed_pipfile["source"]]
        else:
            sources = self.pipfile_sources(expand_vars=False)
        if not isinstance(sources, list):
            sources = [sources]
        return {
            "hash": {"sha256": self.calculate_pipfile_hash()},
            "pipfile-spec": PIPFILE_SPEC_CURRENT,
            "sources": [self.populate_source(s) for s in sources],
            "requires": self.parsed_pipfile.get("requires", {}),
        }

    def write_toml(self, data, path=None):
        """Writes the given data structure out as TOML."""
        if path is None:
            path = self.pipfile_location
        data = convert_toml_outline_tables(data, self)
        try:
            formatted_data = tomlkit.dumps(data).rstrip()
        except Exception:
            document = tomlkit.document()
            for category in self.get_package_categories():
                document[category] = tomlkit.table()
                # Convert things to inline tables — fancy :)
                for package in data.get(category, {}):
                    if hasattr(data[category][package], "keys"):
                        table = tomlkit.inline_table()
                        table.update(data[category][package])
                        document[category][package] = table
                    else:
                        document[category][package] = tomlkit.string(
                            data[category][package]
                        )
            formatted_data = tomlkit.dumps(document).rstrip()

        if Path(path).absolute() == Path(self.pipfile_location).absolute():
            newlines = self._pipfile_newlines
        else:
            newlines = DEFAULT_NEWLINES
        formatted_data = cleanup_toml(formatted_data)
        with io.open(path, "w", newline=newlines) as f:
            f.write(formatted_data)
        # pipfile is mutated!
        self.clear_pipfile_cache()

    def write_lockfile(self, content):
        """Write out the lockfile."""
        s = self._lockfile_encoder.encode(content)
        open_kwargs = {"newline": self._lockfile_newlines, "encoding": "utf-8"}
        with vistir.contextmanagers.atomic_open_for_write(
            self.lockfile_location, **open_kwargs
        ) as f:
            f.write(s)
            # Write newline at end of document. GH-319.
            # Only need '\n' here; the file object handles the rest.
            if not s.endswith("\n"):
                f.write("\n")

    def pipfile_sources(self, expand_vars=True):
        if self.pipfile_is_empty or "source" not in self.parsed_pipfile:
            return [self.default_source]
        # We need to make copies of the source info so we don't
        # accidentally modify the cache. See #2100 where values are
        # written after the os.path.expandvars() call.
        return [
            {k: safe_expandvars(v) if expand_vars else v for k, v in source.items()}
            for source in self.parsed_pipfile["source"]
        ]

    @property
    def sources(self):
        if self.lockfile_exists and hasattr(self.lockfile_content, "keys"):
            meta_ = self.lockfile_content.get("_meta", {})
            sources_ = meta_.get("sources")
            if sources_:
                return sources_

        else:
            return self.pipfile_sources()

    @property
    def sources_default(self):
        return self.sources[0]

    @property
    def index_urls(self):
        return [src.get("url") for src in self.sources]

    def find_source(self, source):
        """
        Given a source, find it.

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

    def get_source(self, name=None, url=None, refresh=False):
        from pipenv.utils.internet import is_url_equal

        def find_source(sources, name=None, url=None):
            source = None
            if name:
                source = next(
                    iter(s for s in sources if "name" in s and s["name"] == name), None
                )
            elif url:
                source = next(
                    iter(
                        s
                        for s in sources
                        if "url" in s and is_url_equal(url, s.get("url", ""))
                    ),
                    None,
                )
            if source is not None:
                return source

        sources = (self.sources, self.pipfile_sources())
        if refresh:
            self.clear_pipfile_cache()
            sources = reversed(sources)
        found = next(
            iter(find_source(source, name=name, url=url) for source in sources), None
        )
        target = next(iter(t for t in (name, url) if t is not None))
        if found is None:
            raise SourceNotFound(target)
        return found

    def get_package_name_in_pipfile(self, package_name, category):
        """Get the equivalent package name in pipfile"""
        section = self.parsed_pipfile.get(category, {})
        package_name = pep423_name(package_name)
        for name in section.keys():
            if pep423_name(name) == package_name:
                return name
        return None

    def remove_package_from_pipfile(self, package_name, category):
        # Read and append Pipfile.
        name = self.get_package_name_in_pipfile(package_name, category=category)
        p = self.parsed_pipfile
        if name:
            del p[category][name]
            self.write_toml(p)
            return True
        return False

    def remove_packages_from_pipfile(self, packages):
        parsed = self.parsed_pipfile
        packages = set([pep423_name(pkg) for pkg in packages])
        for category in self.get_package_categories():
            pipfile_section = parsed.get(category, {})
            pipfile_packages = set(
                [pep423_name(pkg_name) for pkg_name in pipfile_section.keys()]
            )
            to_remove = packages & pipfile_packages
            for pkg in to_remove:
                pkg_name = self.get_package_name_in_pipfile(pkg, category=category)
                del parsed[category][pkg_name]
        self.write_toml(parsed)

    def add_package_to_pipfile(self, package, dev=False, category=None):
        from .vendor.requirementslib import Requirement

        # Read and append Pipfile.
        p = self.parsed_pipfile
        # Don't re-capitalize file URLs or VCSs.
        if not isinstance(package, Requirement):
            package = Requirement.from_line(package.strip())
        req_name, converted = package.pipfile_entry
        category = category if category else "dev-packages" if dev else "packages"
        # Set empty group if it doesn't exist yet.
        if category not in p:
            p[category] = {}
        name = self.get_package_name_in_pipfile(req_name, category=category)
        if name and is_star(converted):
            # Skip for wildcard version
            return
        # Add the package to the group.
        p[category][name or pep423_name(req_name)] = converted
        # Write Pipfile.
        self.write_toml(p)

    def src_name_from_url(self, index_url):
        name, _, tld_guess = urllib.parse.urlsplit(index_url).netloc.rpartition(".")
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
        source = None
        try:
            source = self.get_source(url=index)
        except SourceNotFound:
            try:
                source = self.get_source(name=index)
            except SourceNotFound:
                pass
        if source is not None:
            return source["name"]
        source = {"url": index, "verify_ssl": verify_ssl}
        source["name"] = self.src_name_from_url(index)
        # Add the package to the group.
        if "source" not in p:
            p["source"] = [tomlkit.item(source)]
        else:
            p["source"].append(tomlkit.item(source))
        # Write Pipfile.
        self.write_toml(p)
        return source["name"]

    def recase_pipfile(self):
        if self.ensure_proper_casing():
            self.write_toml(self.parsed_pipfile)

    def load_lockfile(self, expand_env_vars=True):
        lockfile_modified = False
        with io.open(self.lockfile_location, encoding="utf-8") as lock:
            try:
                j = json.load(lock)
                self._lockfile_newlines = preferred_newlines(lock)
            except JSONDecodeError:
                click.secho(
                    "Pipfile.lock is corrupted; ignoring contents.",
                    fg="yellow",
                    bold=True,
                    err=True,
                )
                j = {}
        if not j.get("_meta"):
            with open(self.pipfile_location) as pf:
                default_lockfile = plette.Lockfile.with_meta_from(
                    plette.Pipfile.load(pf), categories=[]
                )
                j["_meta"] = default_lockfile._data["_meta"]
                lockfile_modified = True
        if j.get("default") is None:
            j["default"] = {}
            lockfile_modified = True
        if j.get("develop") is None:
            j["develop"] = {}
            lockfile_modified = True

        if lockfile_modified:
            self.write_lockfile(j)

        if expand_env_vars:
            # Expand environment variables in Pipfile.lock at runtime.
            for i, _ in enumerate(j["_meta"].get("sources", {})):
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
            return lockfile["_meta"].get("hash", {}).get("sha256") or ""
        # Lockfile exists but has no hash at all
        return ""

    def calculate_pipfile_hash(self):
        # Update the lockfile if it is out-of-date.
        with open(self.pipfile_location) as pf:
            p = plette.Pipfile.load(pf)
        return p.get_hash().value

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

    @cached_property
    def finders(self):
        from .vendor.pythonfinder import Finder

        scripts_dirname = "Scripts" if os.name == "nt" else "bin"
        scripts_dir = os.path.join(self.virtualenv_location, scripts_dirname)
        finders = [
            Finder(path=scripts_dir, global_search=gs, system=False)
            for gs in (False, True)
        ]
        return finders

    @property
    def finder(self):
        return next(iter(self.finders), None)

    def which(self, search, as_path=True):
        find = operator.methodcaller("which", search)
        result = next(iter(filter(None, (find(finder) for finder in self.finders))), None)
        if not result:
            result = self._which(search)
        else:
            if as_path:
                result = str(result.path)
        return result

    def _which(self, command, location=None, allow_global=False):
        if not allow_global and location is None:
            if self.virtualenv_exists:
                location = self.virtualenv_location
            else:
                location = os.environ.get("VIRTUAL_ENV", None)
        if not (location and os.path.exists(location)) and not allow_global:
            raise RuntimeError("location not created nor specified")

        version_str = "python{}".format(".".join([str(v) for v in sys.version_info[:2]]))
        is_python = command in ("python", os.path.basename(sys.executable), version_str)
        if not allow_global:
            if os.name == "nt":
                p = find_windows_executable(os.path.join(location, "Scripts"), command)
            else:
                p = os.path.join(location, "bin", command)
        else:
            if is_python:
                p = sys.executable
        if not os.path.exists(p):
            if is_python:
                p = sys.executable or system_which("python")
            else:
                p = system_which(command)
        return p
