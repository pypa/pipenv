from __future__ import annotations

import hashlib
import json
import os
import sys

from functools import cached_property
from pathlib import Path

from pipenv.utils.dependencies import (
    get_canonical_names,
)
from pipenv.utils.fileutils import open_file
from pipenv.patched.pip._internal.utils.hashes import FAVORITE_HASH

import contextlib

from pipenv.environment import Environment
from pipenv.environments import Setting, is_in_virtualenv
from pipenv.patched.pip._internal.configuration import Configuration
from pipenv.patched.pip._internal.exceptions import ConfigurationError

# ``InstallCommand`` lazily imported inside ``Project.init_pipfile``
# (the only call site).  The eager import pulls ~79 ms of pip-
# internal command / network machinery into every ``pipenv``
# invocation, including ones that never instantiate a Project that
# initialises a Pipfile.
from pipenv.utils import err
from pipenv.utils.constants import is_type_checking
from pipenv.utils.dependencies import python_version
from pipenv.utils.internet import is_pypi_url
from pipenv.utils.lockfile import Lockfile
from pipenv.utils.pipfile import DEFAULT_NEWLINES, Pipfile
from pipenv.utils.settings import Settings
from pipenv.utils.sources import Sources
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
        # Per-subsystem state lives inside the subsystem instances:
        # - Pipfile parse cache + location + newlines: ``project.pipfile``
        #   (T_D.6).
        # - Venv discovery / hashing state: ``project.venv_locator``
        #   (T_D.4).
        self._lockfile_newlines = DEFAULT_NEWLINES
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
                os.chdir(self.pipfile.project_directory)

    def path_to(self, p: str) -> Path:
        """Returns the absolute path to a given relative path."""
        path = Path(p)
        if path.is_absolute():
            return path

        return Path(self._original_dir) / p

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

    @cached_property
    def pipfile(self) -> Pipfile:
        """The ``Pipfile`` subsystem (Initiative D, T_D.6).

        Access Pipfile-related state and operations through this
        accessor — e.g. ``project.pipfile.parsed`` (was
        ``parsed_pipfile``), ``project.pipfile.location`` (was
        ``pipfile_location``), ``project.pipfile.exists`` (was
        ``pipfile_exists``), ``project.pipfile.write_toml(...)`` (was
        ``write_toml``), ``project.pipfile.add_package(...)`` (was
        ``add_package_to_pipfile``), ``project.pipfile.calculate_hash()``
        (was ``calculate_pipfile_hash``), etc.

        Fifth and final Initiative-D extraction (after Sources T_D.2,
        Settings T_D.3, VenvLocator T_D.4, Lockfile T_D.5). The 38
        Pipfile-bucket methods on the old ``Project`` god-class moved
        into :class:`pipenv.utils.pipfile.Pipfile` per
        ``docs/dev/initiative-d-inventory.md``.

        Naming-collision note: the legacy plette-wrapper class
        previously named ``Pipfile`` in
        :mod:`pipenv.utils.pipfile` was renamed to ``PlettePipfile`` in
        T_D.6; only :meth:`pipenv.utils.locking.Lockfile.lockfile_from_pipfile`
        references it.
        """
        return Pipfile(self)

    @property
    def installed_packages(self):
        return self.environment.get_installed_packages()

    @property
    def installed_package_names(self):
        return get_canonical_names([pkg.name for pkg in self.installed_packages])

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
            pipfile=self.pipfile.parsed,
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

    def create_pipfile(self, python=None):
        """Creates the Pipfile, filled with juicy defaults.

        Stays on ``Project`` per the T_D.1 §2 ``coordinator`` bucket —
        it spans Sources (default_source), VenvLocator (which-python),
        Settings (PIPENV_DEFAULT_PYTHON_VERSION) and Pipfile (write).
        """
        # Inherit the pip's index configuration of install command.
        from pipenv.patched.pip._internal.commands.install import InstallCommand

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
        self.pipfile.write_toml(data)

    def get_or_create_lockfile(self, categories, from_pipfile=False):
        """Coordinator method that crosses Lockfile/Sources/Pipfile.

        Stays on ``Project`` per the T_D.1 §2 ``coordinator`` bucket.
        Reads through the extracted ``Lockfile`` and ``Sources``
        subsystems; this orchestration is the only legitimate
        cross-subsystem consumer of all three.
        """
        from pipenv.utils.locking import Lockfile as Req_Lockfile

        if from_pipfile and self.pipfile.exists:
            lockfile_dict = {}
            categories = self.pipfile.get_package_categories(for_lockfile=True)
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
            if not sources and self.pipfile.exists:
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
            if not sources and self.pipfile.exists:
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

    # ``parsed_pipfile`` / ``pipfile_location`` / ``pipfile_exists`` /
    # ``read_pipfile`` / ``pipfile_is_empty`` / ``name`` /
    # ``project_directory`` / ``required_python_version`` /
    # ``requirements_location`` / ``requirements_exists`` /
    # ``get_pipfile_section`` / ``get_package_categories`` /
    # ``pipfile_package_names`` / ``write_toml`` / ``has_script`` /
    # ``build_script`` / ``proper_names`` / ``register_proper_name`` /
    # ``pipfile_build_requires`` / ``calculate_pipfile_hash`` /
    # ``all_packages`` / ``packages`` / ``dev_packages`` /
    # ``get_editable_packages`` / ``get_package_name_in_pipfile`` /
    # ``get_pipfile_entry`` / ``remove_package_from_pipfile`` /
    # ``remove_packages_from_pipfile`` / ``reset_category_in_pipfile`` /
    # ``generate_package_pipfile_entry`` / ``add_package_to_pipfile`` /
    # ``add_pipfile_entry_to_pipfile`` / ``add_packages_to_pipfile_batch`` /
    # ``recase_pipfile`` / ``ensure_proper_casing`` /
    # ``proper_case_section`` moved to ``pipenv.utils.pipfile.Pipfile``
    # in T_D.6. Access via ``project.pipfile``.
    #
    # ``finders``, ``finder``, ``which``, ``python`` and ``_which`` were
    # extracted into :class:`pipenv.utils.venv_locator.VenvLocator` in
    # T_D.4. Access them via ``project.venv_locator``.
