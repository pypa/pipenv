from __future__ import annotations

import hashlib
import json
import os
import sys

from functools import cached_property
from pathlib import Path
from urllib.parse import unquote

from pipenv.utils.constants import VCS_LIST
from pipenv.utils.dependencies import extract_vcs_url, normalize_editable_path_for_pip
from pipenv.vendor.tomlkit.items import SingleKey, Table

try:
    import tomllib as toml
except ImportError:
    from pipenv.patched.pip._vendor import tomli as toml

import contextlib

from pipenv.cmdparse import Script
from pipenv.environment import Environment
from pipenv.environments import Setting, is_in_virtualenv, normalize_pipfile_path
from pipenv.patched.pip._internal.commands.install import InstallCommand
from pipenv.patched.pip._internal.configuration import Configuration
from pipenv.patched.pip._internal.exceptions import ConfigurationError
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.utils.hashes import FAVORITE_HASH
from pipenv.utils import err
from pipenv.utils.constants import is_type_checking
from pipenv.utils.dependencies import (
    determine_package_name,
    determine_path_specifier,
    determine_vcs_specifier,
    expansive_install_req_from_line,
    get_canonical_names,
    is_editable,
    pep423_name,
    python_version,
)
from pipenv.utils.fileutils import open_file
from pipenv.utils.internet import (
    is_pypi_url,
    proper_case,
)
from pipenv.utils.lockfile import Lockfile
from pipenv.utils.shell import find_requirements
from pipenv.utils.settings import Settings
from pipenv.utils.sources import Sources
from pipenv.utils.toml import cleanup_toml, convert_toml_outline_tables
from pipenv.utils.venv_locator import VenvLocator
from pipenv.vendor import plette, tomlkit

if is_type_checking():
    from typing import Dict, List, Union

    TSource = Dict[str, Union[str, bool]]
    TPackageEntry = Dict[str, Union[bool, str, List[str]]]
    TPackage = Dict[str, TPackageEntry]
    TScripts = Dict[str, str]
    TPipenv = Dict[str, bool]
    TPipfile = Dict[str, Union[TPackage, TScripts, TPipenv, List[TSource]]]


DEFAULT_NEWLINES = "\n"
NON_CATEGORY_SECTIONS = {
    "build-system",
    "pipenv",
    "requires",
    "scripts",
    "source",
}


class _LockFileEncoder(json.JSONEncoder):
    """A specialized JSON encoder to convert loaded TOML data into a lock file.

    This adds a few characteristics to the encoder:

    * The JSON is always prettified with indents and spaces.
    * TOMLKit's container elements are seamlessly encodable.
    * The output is always UTF-8-encoded text, never binary, even on Python 2.
    """

    def __init__(self):
        super().__init__(indent=4, separators=(",", ": "), sort_keys=True)

    def default(self, obj):
        if isinstance(obj, Path):
            obj = obj.as_posix()
        return super().default(obj)

    def encode(self, obj):
        content = super().encode(obj)
        if not isinstance(content, str):
            content = content.decode("utf-8")
        return content


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


def _parse_pip_conf_indexes(
    configuration: Configuration,
) -> tuple[list[dict], list[dict]]:
    """Parse ``index-url`` and ``extra-index-url`` entries from a loaded pip
    :class:`Configuration` object.

    Returns a 2-tuple ``(pip_conf_indexes, pip_conf_extra_indexes)`` where:

    * *pip_conf_indexes* – sources built from ``index-url`` keys.
    * *pip_conf_extra_indexes* – sources built from ``extra-index-url`` keys.

    Each source dict has the shape ``{"url": str, "verify_ssl": bool, "name": str}``.

    The ``trusted-host`` value for a section is handled correctly whether pip
    returns a single hostname, a whitespace/newline-separated list, or a Python
    list (future-proof).
    """
    pip_conf_indexes: list[dict] = []
    pip_conf_extra_indexes: list[dict] = []

    # Build a flat merged config respecting pip's priority order (later
    # entries, i.e. higher-priority files, override earlier ones).
    merged_conf: dict[str, str] = {}
    for config_dict in configuration._dictionary.values():
        merged_conf.update(config_dict)

    for section_key, value in merged_conf.items():
        key_parts = section_key.split(".", 1)
        if len(key_parts) <= 1:
            continue
        section, option = key_parts

        if option not in ("index-url", "extra-index-url"):
            continue

        # Retrieve trusted-host for this section and normalise to a list of
        # hostnames.  Pip may return a single string (possibly containing
        # whitespace/newline-separated hostnames) or a list.
        try:
            trusted_hosts_raw = configuration.get_value(f"{section}.trusted-host")
            if isinstance(trusted_hosts_raw, str):
                trusted_hosts = trusted_hosts_raw.split()
            else:
                trusted_hosts = list(trusted_hosts_raw) if trusted_hosts_raw else []
        except ConfigurationError:
            trusted_hosts = []

        if option == "index-url":
            pip_conf_indexes.append(
                {
                    "url": value,
                    "verify_ssl": not any(th in value for th in trusted_hosts) and "https://" in value,
                    "name": f"pip_conf_index_{section}",
                }
            )
        else:
            # extra-index-url may list multiple URLs separated by whitespace
            # or newlines (pip supports multi-line values in config files).
            extra_urls = [u for u in value.split() if u]
            for i, url in enumerate(extra_urls):
                name_suffix = f"_{i}" if len(extra_urls) > 1 else ""
                pip_conf_extra_indexes.append(
                    {
                        "url": url,
                        "verify_ssl": not any(th in url for th in trusted_hosts) and "https://" in url,
                        "name": f"pip_conf_extra_index_{section}{name_suffix}",
                    }
                )

    return pip_conf_indexes, pip_conf_extra_indexes


class Project:
    """docstring for Project"""

    _lockfile_encoder = _LockFileEncoder()

    def __init__(self, python_version=None, chdir=True):
        self._name = None
        # The venv-location / download-dir / proper-names-db caches moved
        # to :class:`pipenv.utils.venv_locator.VenvLocator` in T_D.4.
        # Access them via ``project.venv_locator``.
        self._pipfile_location = None
        self._pipfile_newlines = DEFAULT_NEWLINES
        self._parsed_pipfile_cache = None
        self._parsed_pipfile_mtime_ns = None
        self._lockfile_newlines = DEFAULT_NEWLINES
        self._requirements_location = None
        self._original_dir = Path.cwd().resolve()
        self._environment = None
        self.python_version = python_version
        self.sessions = {}  # pip requests sessions
        self.s = Setting()
        # Load Pip configuration and merge index-url / extra-index-url entries.
        self.configuration = Configuration(isolated=False, load_only=None)
        self.configuration.load()
        pip_conf_indexes, pip_conf_extra_indexes = _parse_pip_conf_indexes(self.configuration)

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

        default_sources_toml = f"[[source]]\n{tomlkit.dumps(self.default_source)}"
        for pip_conf_index in pip_conf_indexes:
            default_sources_toml += f"\n\n[[source]]\n{tomlkit.dumps(pip_conf_index)}"
        for pip_conf_extra_index in pip_conf_extra_indexes:
            default_sources_toml += f"\n\n[[source]]\n{tomlkit.dumps(pip_conf_extra_index)}"
        plette.pipfiles.DEFAULT_SOURCE_TOML = default_sources_toml

        # Hack to skip this during pipenv run, or -r.
        if ("run" not in sys.argv) and chdir:
            with contextlib.suppress(TypeError, AttributeError):
                os.chdir(self.project_directory)

    def path_to(self, p: str) -> Path:
        """Returns the absolute path to a given relative path."""
        path = Path(p)
        if path.is_absolute():
            return path

        return Path(self._original_dir) / p

    def get_pipfile_section(self, section):
        """Returns the details from the section of the Project's Pipfile."""
        return self.parsed_pipfile.get(section, {})

    def get_package_categories(self, for_lockfile=False):
        """Ensure we get only package categories and that the default packages section is first."""
        categories = set(self.parsed_pipfile.keys())
        package_categories = categories - NON_CATEGORY_SECTIONS - {"packages", "dev-packages"}
        if for_lockfile:
            return ["default", "develop"] + list(package_categories)
        else:
            return ["packages", "dev-packages"] + list(package_categories)

    @classmethod
    def prepend_hash_types(cls, checksums, hash_type):
        cleaned_checksums = set()
        for checksum in checksums:
            if not checksum:
                continue
            if not checksum.startswith(f"{hash_type}:"):
                checksum = f"{hash_type}:{checksum}"
            cleaned_checksums.add(checksum)
        return sorted(cleaned_checksums)

    @staticmethod
    def get_file_hash(session, link):
        h = hashlib.new(FAVORITE_HASH)
        err.print(f"Downloading file {link.filename} to obtain hash...")
        with open_file(link.url, session) as fp:
            if fp is None:
                return None
            for chunk in iter(lambda: fp.read(8096), b""):
                h.update(chunk)
        return f"{h.name}:{h.hexdigest()}"

    @property
    def name(self) -> str:
        if self._name is None:
            self._name = Path(self.pipfile_location).parent.name
        return self._name

    @property
    def pipfile_exists(self) -> bool:
        return Path(self.pipfile_location).is_file()

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
        return str(Path(self.pipfile_location).parent.absolute())

    @property
    def requirements_exists(self) -> bool:
        return bool(self.requirements_location)

    @property
    def installed_packages(self):
        return self.environment.get_installed_packages()

    @property
    def installed_package_names(self):
        return get_canonical_names([pkg.name for pkg in self.installed_packages])

    @property
    def pipfile_package_names(self) -> dict[str, set[str]]:
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
            prefix = self.venv_locator.location
            python = None
        sources = self.sources.all if self.sources.all else [self.default_source]
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

    @cached_property
    def venv_locator(self) -> VenvLocator:
        """The ``VenvLocator`` subsystem (Initiative D, T_D.4).

        Access venv-related operations through this accessor — e.g.
        ``project.venv_locator.location`` (was ``virtualenv_location``),
        ``project.venv_locator.exists`` (was ``virtualenv_exists``),
        ``project.venv_locator.is_venv_in_project()``,
        ``project.venv_locator.which("python")``,
        ``project.venv_locator.python()``, etc.

        Per the T_D.1 inventory the bucket is read-only against the venv
        (creation lives in ``pipenv/utils/virtualenv.py``); no writers
        live here. See ``docs/dev/initiative-d-inventory.md``.
        """
        return VenvLocator(self)

    @property
    def proper_names(self) -> list[str]:
        with self.venv_locator.proper_names_db_path.open() as f:
            return f.read().splitlines()

    def register_proper_name(self, name: str) -> None:
        """Registers a proper name to the database."""
        with self.venv_locator.proper_names_db_path.open("a") as f:
            f.write(f"{name}\n")

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
    def requirements_location(self) -> str | None:
        if self._requirements_location is None:
            try:
                loc = find_requirements(max_depth=self.s.PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = None
            self._requirements_location = loc
        return self._requirements_location

    @property
    def parsed_pipfile(self) -> tomlkit.toml_document.TOMLDocument | TPipfile:
        """Parse Pipfile into a TOMLFile"""
        # Parsing tomlkit on every access is expensive (see gh perf branch): a
        # single lock call hit this 500+ times.  Cache the parsed document and
        # refresh it whenever the file's mtime changes so external edits still
        # work, while writes from pipenv itself invalidate the cache directly
        # via write_toml().
        if not self.pipfile_exists:
            return self._parse_pipfile("")
        try:
            mtime_ns = os.stat(self.pipfile_location).st_mtime_ns
        except OSError:
            mtime_ns = None
        if (
            self._parsed_pipfile_cache is not None
            and mtime_ns is not None
            and self._parsed_pipfile_mtime_ns == mtime_ns
        ):
            return self._parsed_pipfile_cache
        contents = self.read_pipfile()
        parsed = self._parse_pipfile(contents)
        self._parsed_pipfile_cache = parsed
        self._parsed_pipfile_mtime_ns = mtime_ns
        return parsed

    def read_pipfile(self) -> str:
        # Open the pipfile, read it into memory.
        if not self.pipfile_exists:
            return ""
        with open(self.pipfile_location) as f:
            contents = f.read()
            self._pipfile_newlines = preferred_newlines(f)

        return contents

    def _parse_pipfile(self, contents: str) -> tomlkit.toml_document.TOMLDocument | TPipfile:
        try:
            return tomlkit.parse(contents)
        except Exception:
            # We lose comments here, but it's for the best.)
            # Fallback to toml parser, for large files.
            return toml.loads(contents)

    @property
    def pipfile_build_requires(self) -> list[str]:
        """Returns a list of build-system requirements from the Pipfile [build-system] section.

        Reads the 'requires' key from the [build-system] section of the Pipfile.
        This allows specifying packages that must be installed before other packages
        can be resolved or installed (e.g., custom setuptools wrappers used in setup.py).

        Example Pipfile::

            [build-system]
            requires = ["stwrapper", "setuptools>=40.8.0", "wheel"]

        Returns an empty list if no [build-system] section or requires key is present.
        """
        if not self.pipfile_exists:
            return []
        build_system = self.parsed_pipfile.get("build-system", {})
        return list(build_system.get("requires", []))

    @cached_property
    def settings(self) -> Settings:
        """The ``Settings`` subsystem (Initiative D, T_D.3).

        Access ``[pipenv]``-section configuration through this accessor.
        ``Settings`` implements :class:`collections.abc.MutableMapping`
        so legacy call sites — ``project.settings.get(key, default)``,
        ``"key" in project.settings``, ``project.settings[key]`` —
        continue to work unchanged.

        The previous ``Project.update_settings`` method moved to
        :meth:`Settings.update`. The previous ``Project.use_pylock``
        property moved to :attr:`Settings.use_pylock`. See T_D.3 and
        ``docs/dev/initiative-d-inventory.md`` for the cluster boundary.
        """
        return Settings(self)

    def has_script(self, name: str) -> bool:
        try:
            return name in self.parsed_pipfile["scripts"]
        except KeyError:
            return False

    def build_script(self, name: str, extra_args: list[str] | None = None) -> Script:
        try:
            script = Script.parse(self.parsed_pipfile["scripts"][name])
        except KeyError:
            script = Script(name)
        if extra_args:
            script.extend(extra_args)
        return script

    @cached_property
    def lockfile(self) -> Lockfile:
        """The ``Lockfile`` subsystem (Initiative D, T_D.5).

        Access lockfile-related operations through this accessor — e.g.
        ``project.lockfile.content`` (was ``lockfile_content``),
        ``project.lockfile.exists`` (was ``lockfile_exists``),
        ``project.lockfile.location`` (was ``lockfile_location``),
        ``project.lockfile.any_exists`` (was ``any_lockfile_exists``),
        ``project.lockfile.write(data)`` (was ``write_lockfile``),
        ``project.lockfile.load()`` (was ``load_lockfile``),
        ``project.lockfile.meta()`` (was ``get_lockfile_meta``),
        ``project.lockfile.hash()`` (was ``get_lockfile_hash``),
        ``project.lockfile.as_dict(categories=...)`` (was the callable
        ``project.lockfile(...)`` method), etc.

        Per T_D.1 §8.1 maintainer sign-off pylock.toml support is not
        folded into this extraction; pylock seams in the subsystem carry
        ``# TODO(pylock):`` tags for the 2027 follow-up. The orchestrator
        ``Project.get_or_create_lockfile`` stays on ``Project``
        (coordinator bucket per T_D.1 §2). See
        ``docs/dev/initiative-d-inventory.md``.
        """
        return Lockfile(self)

    @property
    def _pipfile(self):
        from pipenv.utils.pipfile import Pipfile as ReqLibPipfile

        pf = ReqLibPipfile.load(self.pipfile_location)
        return pf

    def get_editable_packages(self, category):
        packages = {k: v for k, v in self.parsed_pipfile.get(category, {}).items() if is_editable(v)}
        return packages

    def _get_vcs_packages(self, dev=False):
        from pipenv.utils.dependencies import is_vcs

        section = "dev-packages" if dev else "packages"
        packages = {k: v for k, v in self.parsed_pipfile.get(section, {}).items() if is_vcs(v) or is_vcs(k)}
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

            source_name = f"pip_index_{i}"
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
            # When the virtualenv already exists (created moments ago by
            # ensure_virtualenv, or pre-existing), ask *its* interpreter for
            # the version.  Using self.which("python") instead resolves
            # "python" via PATH / pyenv shims and can return a *different*
            # Python than the one actually inside the virtualenv (e.g. the
            # pyenv global vs. the highest installed version that
            # find_all_python_versions() chose).  That disagreement causes a
            # spurious "Pipfile requires X but you are using Y" warning on
            # every subsequent pipenv invocation.  See GH-6571.
            if self.venv_locator.exists:
                required_python = self.venv_locator._which("python") or self.venv_locator.which("python")
            else:
                required_python = self.venv_locator.which("python")
        version = python_version(required_python) or self.s.PIPENV_DEFAULT_PYTHON_VERSION
        if version:
            data["requires"] = {"python_version": ".".join(version.split(".")[:2])}
        if python and version and len(version.split(".")) > 2:
            data["requires"].update({"python_full_version": version})
        self.write_toml(data)

    def get_or_create_lockfile(self, categories, from_pipfile=False):
        """Coordinator method that crosses Lockfile/Sources/Pipfile.

        Stays on ``Project`` per the T_D.1 §2 ``coordinator`` bucket.
        Reads through the extracted ``Lockfile`` and ``Sources``
        subsystems; this orchestration is the only legitimate
        cross-subsystem consumer of both.
        """
        from pipenv.utils.locking import Lockfile as Req_Lockfile

        if from_pipfile and self.pipfile_exists:
            lockfile_dict = {}
            categories = self.get_package_categories(for_lockfile=True)
            _lockfile = self.lockfile.as_dict(categories=categories)
            for category in categories:
                lockfile_dict[category] = _lockfile.get(category, {}).copy()
            lockfile_dict.update({"_meta": self.lockfile.meta()})
            lockfile = Req_Lockfile.from_data(path=self.lockfile.location, data=lockfile_dict, meta_from_project=False)
        elif self.lockfile.exists:
            try:
                lockfile = Req_Lockfile.load(self.lockfile.location)
            except OSError:
                lockfile = Req_Lockfile.from_data(self.lockfile.location, self.lockfile.content)
        # TODO(pylock): pylock branch — will fold into the format-detection layer.
        elif self.lockfile.pylock_exists:
            # Load from pylock.toml when no Pipfile.lock exists.
            # lockfile.content already handles pylock.toml → internal format conversion.
            lockfile_dict = self.lockfile.content.copy()
            sources = lockfile_dict.get("_meta", {}).get("sources", [])
            if not sources and self.pipfile_exists:
                sources = self.sources.pipfile_sources(expand_vars=False)
            elif not isinstance(sources, list):
                sources = [sources]
            if sources:
                lockfile_dict["_meta"]["sources"] = [Sources.populate_source(s) for s in sources]
            lockfile = Req_Lockfile.from_data(path=self.lockfile.location, data=lockfile_dict, meta_from_project=False)
        else:
            lockfile = Req_Lockfile.from_data(
                path=self.lockfile.location,
                data=self.lockfile.as_dict(),
                meta_from_project=False,
            )
        if lockfile.lockfile is not None:
            return lockfile
        if self.lockfile.any_exists and self.lockfile.content:
            lockfile_dict = self.lockfile.content.copy()
            sources = lockfile_dict.get("_meta", {}).get("sources", [])
            if not sources and self.pipfile_exists:
                sources = self.sources.pipfile_sources(expand_vars=False)
            elif not isinstance(sources, list):
                sources = [sources]
            if sources:
                lockfile_dict["_meta"]["sources"] = [Sources.populate_source(s) for s in sources]
            _created_lockfile = Req_Lockfile.from_data(path=self.lockfile.location, data=lockfile_dict, meta_from_project=False)
            lockfile.lockfile = lockfile.projectfile.model = _created_lockfile
            return lockfile
        else:
            return self.get_or_create_lockfile(categories=categories, from_pipfile=True)

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
                        document[category][package] = tomlkit.string(data[category][package])
            formatted_data = tomlkit.dumps(document).rstrip()

        is_pipfile = Path(path).resolve() == Path(self.pipfile_location).resolve()
        newlines = self._pipfile_newlines if is_pipfile else DEFAULT_NEWLINES
        formatted_data = cleanup_toml(formatted_data)
        with open(path, "w", newline=newlines) as f:
            f.write(formatted_data)
        if is_pipfile:
            self._parsed_pipfile_cache = None
            self._parsed_pipfile_mtime_ns = None

    @cached_property
    def sources(self) -> Sources:
        """The ``Sources`` subsystem (Initiative D, T_D.2).

        Access source-related operations through this accessor — e.g.
        ``project.sources.all`` for the source list, ``project.sources.default``
        for the first source, ``project.sources.pipfile_sources()`` for the
        Pipfile-only view, ``project.sources.get_source(...)``,
        ``project.sources.add_index_to_pipfile(...)``, etc.

        The previous in-``Project`` source methods were extracted into
        :class:`pipenv.utils.sources.Sources` in T_D.2 per the inventory
        in ``docs/dev/initiative-d-inventory.md``.
        """
        return Sources(self)

    def get_package_name_in_pipfile(self, package_name, category):
        section = self.parsed_pipfile.get(category, {})
        normalized_name = pep423_name(package_name)
        for name in section:
            if pep423_name(name) == normalized_name:
                return name
        return package_name  # Return original name if not found

    def get_pipfile_entry(self, package_name, category):
        name = self.get_package_name_in_pipfile(package_name, category)
        return self.parsed_pipfile.get(category, {}).get(name)

    def _sort_category(self, category) -> Table:
        # copy table or create table from dict-like object
        table = tomlkit.table()
        if isinstance(category, Table):
            table.update(category.value)
        else:
            table.update(category)

        # sort the table internally
        table._value._body.sort(key=lambda t: t[0] and t[0].key or "")
        for index, (key, _) in enumerate(table._value._body):
            assert isinstance(key, SingleKey)
            indices = table._value._map[key]
            if isinstance(indices, tuple):
                table._value._map[key] = (index,) + indices[1:]
            else:
                table._value._map[key] = index

        return table

    def remove_package_from_pipfile(self, package_name, category):
        # Read and append Pipfile.
        p = self.parsed_pipfile
        section = p.get(category, {})
        # Find the actual key in the section that matches the normalized name
        normalized_name = pep423_name(package_name)
        name = None
        for key in section:
            if pep423_name(key) == normalized_name:
                name = key
                break
        if name and name in section:
            del p[category][name]
            if self.settings.get("sort_pipfile"):
                p[category] = self._sort_category(p[category])
            self.write_toml(p)
            return True
        return False

    def reset_category_in_pipfile(self, category):
        # Read and append Pipfile.
        p = self.parsed_pipfile
        if category:
            del p[category]
            p[category] = {}
            self.write_toml(p)
            return True
        return False

    def remove_packages_from_pipfile(self, packages):
        parsed = self.parsed_pipfile
        packages = {pep423_name(pkg) for pkg in packages}
        for category in self.get_package_categories():
            pipfile_section = parsed.get(category, {})
            pipfile_packages = {pep423_name(pkg_name) for pkg_name in pipfile_section}
            to_remove = packages & pipfile_packages
            for pkg in to_remove:
                pkg_name = self.get_package_name_in_pipfile(pkg, category=category)
                if pkg_name:
                    del parsed[category][pkg_name]
        self.write_toml(parsed)

    def generate_package_pipfile_entry(self, package, pip_line, category=None, index_name=None, no_binary=False):
        """Generate a package entry from pip install line
        given the installreq package and the pip line that generated it.
        """
        # Don't re-capitalize file URLs or VCSs.
        if not isinstance(package, InstallRequirement):
            package, req_name = expansive_install_req_from_line(package.strip())
        else:
            _, req_name = expansive_install_req_from_line(pip_line.strip())

        if req_name is None:
            req_name = determine_package_name(package)
        path_specifier = determine_path_specifier(package)
        vcs_specifier = determine_vcs_specifier(package)
        name = self.get_package_name_in_pipfile(req_name, category=category)
        normalized_name = pep423_name(req_name)

        extras = package.extras
        specifier = "*"
        if package.req and package.specifier:
            specifier = str(package.specifier)

        # Construct package requirement
        entry = {}
        if extras:
            entry["extras"] = list(extras)
        if path_specifier:
            editable = pip_line.startswith("-e")
            # Strip "-e" prefix to get the raw package reference from the install line.
            raw_ref = pip_line[2:].strip() if editable else pip_line.strip()
            raw_ref = raw_ref.strip('"').strip("'")
            # Use "file" for remote HTTP/HTTPS URLs and explicit file:// URLs;
            # use "path" for plain local filesystem paths (e.g. ".", "./lib").
            is_http_url = path_specifier.startswith(("http:", "https:"))
            is_file_url = raw_ref.startswith("file:")
            key = "file" if (is_http_url or is_file_url) else "path"
            if is_file_url:
                # Preserve the original file:// URL exactly as the user typed it.
                entry[key] = unquote(raw_ref)
            else:
                entry[key] = unquote(normalize_editable_path_for_pip(path_specifier) if editable else str(path_specifier))
            if editable:
                entry["editable"] = editable
        elif vcs_specifier:
            for vcs in VCS_LIST:
                if vcs in package.link.scheme:
                    if pip_line.startswith("-e"):
                        entry["editable"] = True
                        pip_line = pip_line.replace("-e ", "")
                    if "[" in pip_line and "]" in pip_line:
                        extras_section = pip_line.split("[")[1].split("]")[0]
                        entry["extras"] = sorted([extra.strip() for extra in extras_section.split(",")])
                    if "@ " in pip_line:
                        vcs_part = pip_line.split("@ ", 1)[1]
                    else:
                        vcs_part = pip_line
                    vcs_parts = vcs_part.rsplit("@", 1)
                    if len(vcs_parts) > 1:
                        entry["ref"] = vcs_parts[1].split("#", 1)[0].strip()
                    vcs_url = vcs_parts[0].strip()
                    vcs_url = extract_vcs_url(vcs_url)
                    entry[vcs] = vcs_url

                    # Check and extract subdirectory fragment
                    if package.link.subdirectory_fragment:
                        entry["subdirectory"] = package.link.subdirectory_fragment
                    break
        else:
            entry["version"] = specifier

        if index_name:
            entry["index"] = index_name
        elif hasattr(package, "index"):
            entry["index"] = package.index

        # Include markers (e.g., sys_platform == 'win32') if present
        if package.markers:
            entry["markers"] = str(package.markers)

        # Store no_binary flag so pipenv re-applies --no-binary on future installs
        if no_binary:
            entry["no_binary"] = True

        if len(entry) == 1 and "version" in entry:
            return name, normalized_name, specifier
        else:
            return name, normalized_name, entry

    def add_package_to_pipfile(self, package, pip_line, dev=False, category=None, no_binary=False):
        category = category if category else "dev-packages" if dev else "packages"

        name, normalized_name, entry = self.generate_package_pipfile_entry(package, pip_line, category=category, no_binary=no_binary)

        return self.add_pipfile_entry_to_pipfile(name, normalized_name, entry, category=category)

    def add_pipfile_entry_to_pipfile(self, name, normalized_name, entry, category=None):
        newly_added = False

        # Read and append Pipfile.
        parsed_pipfile = self.parsed_pipfile

        # Set empty group if it doesn't exist yet.
        if category not in parsed_pipfile:
            parsed_pipfile[category] = {}

        section = parsed_pipfile.get(category, {})
        for entry_name in section.copy().keys():
            if entry_name.lower() == normalized_name.lower():
                del parsed_pipfile[category][entry_name]

        # Add the package to the group.
        if normalized_name not in parsed_pipfile[category]:
            newly_added = True

        parsed_pipfile[category][normalized_name] = entry

        if self.settings.get("sort_pipfile"):
            parsed_pipfile[category] = self._sort_category(parsed_pipfile[category])

        # Write Pipfile.
        self.write_toml(parsed_pipfile)
        return newly_added, category, normalized_name

    def add_packages_to_pipfile_batch(self, packages_data, dev=False, categories=None):
        """
        Add multiple packages to Pipfile in a single operation for better performance.

        Args:
            packages_data: List of tuples (package, pip_line) or list of dicts with package info
            dev: Whether to add to dev-packages section
            categories: List of categories to add packages to

        Returns:
            List of tuples (newly_added, category, normalized_name) for each package
        """
        if not packages_data:
            return []

        # Determine target categories
        if categories is None or (isinstance(categories, list) and not categories):
            categories = ["dev-packages" if dev else "packages"]
        elif isinstance(categories, str):
            categories = [categories]

        # Read Pipfile once
        parsed_pipfile = self.parsed_pipfile
        results = []

        # Ensure all categories exist
        for category in categories:
            if category not in parsed_pipfile:
                parsed_pipfile[category] = {}

        # Process all packages
        for package_data in packages_data:
            if isinstance(package_data, tuple) and len(package_data) == 2:
                package, pip_line = package_data

                # Generate entry for this package
                name, normalized_name, entry = self.generate_package_pipfile_entry(package, pip_line, category=categories[0])

                # Add to each specified category
                for category in categories:
                    newly_added = False

                    # Remove any existing entries with different casing
                    section = parsed_pipfile.get(category, {})
                    for entry_name in section.copy().keys():
                        if entry_name.lower() == normalized_name.lower():
                            del parsed_pipfile[category][entry_name]

                    # Check if this is a new package
                    if normalized_name not in parsed_pipfile[category]:
                        newly_added = True

                    # Add the package
                    parsed_pipfile[category][normalized_name] = entry
                    results.append((newly_added, category, normalized_name))

            elif isinstance(package_data, dict):
                # Handle pre-processed package data
                name = package_data.get("name")
                normalized_name = package_data.get("normalized_name")
                entry = package_data.get("entry")

                if name and normalized_name and entry:
                    for category in categories:
                        newly_added = False

                        # Remove any existing entries with different casing
                        section = parsed_pipfile.get(category, {})
                        for entry_name in section.copy().keys():
                            if entry_name.lower() == normalized_name.lower():
                                del parsed_pipfile[category][entry_name]

                        # Check if this is a new package
                        if normalized_name not in parsed_pipfile[category]:
                            newly_added = True

                        # Add the package
                        parsed_pipfile[category][normalized_name] = entry
                        results.append((newly_added, category, normalized_name))

        # Sort categories if requested
        if self.settings.get("sort_pipfile"):
            for category in categories:
                if category in parsed_pipfile:
                    parsed_pipfile[category] = self._sort_category(parsed_pipfile[category])

        # Write Pipfile once at the end
        self.write_toml(parsed_pipfile)
        return results

    def recase_pipfile(self):
        if self.ensure_proper_casing():
            self.write_toml(self.parsed_pipfile)

    def calculate_pipfile_hash(self):
        """Compute a SHA-256 hash of the Pipfile that is stable regardless of
        package-name casing or separator style (PEP 503 / #4699).

        ``Sphinx`` and ``sphinx``, ``my_pkg`` and ``my-pkg``, etc. all hash to
        the same value so that minor edits to a Pipfile that don't change the
        resolved environment don't trigger unnecessary re-locks.

        The hash algorithm mirrors plette's ``Pipfile.get_hash()`` exactly,
        except that every package-name key in ``[packages]``, ``[dev-packages]``
        and any custom categories is replaced by its PEP 503 canonical form
        before serialisation.
        """
        import hashlib
        import json

        from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

        _PIPFILE_SECTIONS = frozenset(
            (
                "source",
                "packages",
                "dev-packages",
                "requires",
                "scripts",
                "pipfile",
                "pipenv",
            )
        )

        def _normalize_section(section):
            """Return a new dict with all keys canonicalized (PEP 503)."""
            return {canonicalize_name(k): v for k, v in section.items()}

        with open(self.pipfile_location) as pf:
            p = plette.Pipfile.load(pf)

        raw = p._data
        data = {
            "_meta": {
                "sources": raw.get("source", {}),
                "requires": raw.get("requires", {}),
            },
            "default": _normalize_section(raw.get("packages", {})),
            "develop": _normalize_section(raw.get("dev-packages", {})),
        }
        for category, values in raw.items():
            if category in _PIPFILE_SECTIONS or category in (
                "default",
                "develop",
                "pipenv",
            ):
                continue
            data[category] = _normalize_section(values)

        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

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
        unknown_names = [k for k in section if k not in set(self.proper_names)]
        # Replace each package with proper casing.
        for dep in unknown_names:
            try:
                # Get new casing for package name.
                new_casing = proper_case(dep)
            except OSError:
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

    # ``finders``, ``finder``, ``which``, ``python`` and ``_which`` were
    # extracted into :class:`pipenv.utils.venv_locator.VenvLocator` in
    # T_D.4. Access them via ``project.venv_locator``.
