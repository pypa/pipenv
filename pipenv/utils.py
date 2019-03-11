# -*- coding: utf-8 -*-
import contextlib
import errno
import logging
import os
import posixpath
import re
import shutil
import stat
import sys
import warnings

from contextlib import contextmanager
from distutils.spawn import find_executable

import six
import toml
import tomlkit

from click import echo as click_echo
six.add_move(six.MovedAttribute("Mapping", "collections", "collections.abc"))  # noqa
six.add_move(six.MovedAttribute("Sequence", "collections", "collections.abc"))  # noqa
six.add_move(six.MovedAttribute("Set", "collections", "collections.abc"))  # noqa
from six.moves import Mapping, Sequence, Set
from six.moves.urllib.parse import urlparse
from .vendor.vistir.compat import ResourceWarning, lru_cache
from .vendor.vistir.misc import fs_str

import crayons
import parse

from . import environments
from .exceptions import PipenvUsageError, PipenvCmdError
from .pep508checker import lookup
from .vendor.urllib3 import util as urllib3_util


if environments.MYPY_RUNNING:
    from typing import Tuple, Dict, Any, List, Union, Optional, Text
    from .vendor.requirementslib.models.requirements import Requirement, Line
    from .project import Project


logging.basicConfig(level=logging.ERROR)

specifiers = [k for k in lookup.keys()]
# List of version control systems we support.
VCS_LIST = ("git", "svn", "hg", "bzr")
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")
requests_session = None  # type: ignore


def _get_requests_session():
    """Load requests lazily."""
    global requests_session
    if requests_session is not None:
        return requests_session
    import requests

    requests_session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        max_retries=environments.PIPENV_MAX_RETRIES
    )
    requests_session.mount("https://pypi.org/pypi", adapter)
    return requests_session


def cleanup_toml(tml):
    toml = tml.split("\n")
    new_toml = []
    # Remove all empty lines from TOML.
    for line in toml:
        if line.strip():
            new_toml.append(line)
    toml = "\n".join(new_toml)
    new_toml = []
    # Add newlines between TOML sections.
    for i, line in enumerate(toml.split("\n")):
        # Skip the first line.
        if line.startswith("["):
            if i > 0:
                # Insert a newline before the heading.
                new_toml.append("")
        new_toml.append(line)
    # adding new line at the end of the TOML file
    new_toml.append("")
    toml = "\n".join(new_toml)
    return toml


def convert_toml_outline_tables(parsed):
    """Converts all outline tables to inline tables."""
    def convert_tomlkit_table(section):
        for key, value in section._body:
            if not key:
                continue
            if hasattr(value, "keys") and not isinstance(value, tomlkit.items.InlineTable):
                table = tomlkit.inline_table()
                table.update(value.value)
                section[key.key] = table

    def convert_toml_table(section):
        for package, value in section.items():
            if hasattr(value, "keys") and not isinstance(value, toml.decoder.InlineTableDict):
                table = toml.TomlDecoder().get_empty_inline_table()
                table.update(value)
                section[package] = table

    is_tomlkit_parsed = isinstance(parsed, tomlkit.container.Container)
    for section in ("packages", "dev-packages"):
        table_data = parsed.get(section, {})
        if not table_data:
            continue
        if is_tomlkit_parsed:
            convert_tomlkit_table(table_data)
        else:
            convert_toml_table(table_data)

    return parsed


def run_command(cmd, *args, catch_exceptions=True, **kwargs):
    """
    Take an input command and run it, handling exceptions and error codes and returning
    its stdout and stderr.

    :param cmd: The list of command and arguments.
    :type cmd: list
    :param bool catch_exceptions: Whether to catch and raise exceptions on failure
    :returns: A 2-tuple of the output and error from the command
    :rtype: Tuple[str, str]
    :raises: exceptions.PipenvCmdError
    """

    from pipenv.vendor import delegator
    from ._compat import decode_output
    from .cmdparse import Script
    if isinstance(cmd, (six.string_types, list, tuple)):
        cmd = Script.parse(cmd)
    if not isinstance(cmd, Script):
        raise TypeError("Command input must be a string, list or tuple")
    if "env" not in kwargs:
        kwargs["env"] = os.environ.copy()
    try:
        cmd_string = cmd.cmdify()
    except TypeError:
        click_echo("Error turning command into string: {0}".format(cmd), err=True)
        sys.exit(1)
    if environments.is_verbose():
        click_echo("Running command: $ {0}".format(cmd_string, err=True))
    c = delegator.run(cmd_string, *args, **kwargs)
    c.block()
    if environments.is_verbose():
        click_echo("Command output: {0}".format(
            crayons.blue(decode_output(c.out))
        ), err=True)
    if not c.ok and catch_exceptions:
        raise PipenvCmdError(cmd_string, c.out, c.err, c.return_code)
    return c


def parse_python_version(output):
    """Parse a Python version output returned by `python --version`.

    Return a dict with three keys: major, minor, and micro. Each value is a
    string containing a version part.

    Note: The micro part would be `'0'` if it's missing from the input string.
    """
    version_line = output.split("\n", 1)[0]
    version_pattern = re.compile(
        r"""
        ^                   # Beginning of line.
        Python              # Literally "Python".
        \s                  # Space.
        (?P<major>\d+)      # Major = one or more digits.
        \.                  # Dot.
        (?P<minor>\d+)      # Minor = one or more digits.
        (?:                 # Unnamed group for dot-micro.
            \.              # Dot.
            (?P<micro>\d+)  # Micro = one or more digit.
        )?                  # Micro is optional because pypa/pipenv#1893.
        .*                  # Trailing garbage.
        $                   # End of line.
    """,
        re.VERBOSE,
    )

    match = version_pattern.match(version_line)
    if not match:
        return None
    return match.groupdict(default="0")


def python_version(path_to_python):
    from .vendor.pythonfinder.utils import get_python_version

    if not path_to_python:
        return None
    try:
        version = get_python_version(path_to_python)
    except Exception:
        return None
    return version


def escape_grouped_arguments(s):
    """Prepares a string for the shell (on Windows too!)

    Only for use on grouped arguments (passed as a string to Popen)
    """
    if s is None:
        return None

    # Additional escaping for windows paths
    if os.name == "nt":
        s = "{}".format(s.replace("\\", "\\\\"))
    return '"' + s.replace("'", "'\\''") + '"'


def clean_pkg_version(version):
    """Uses pip to prepare a package version string, from our internal version."""
    return six.u(pep440_version(str(version).replace("==", "")))


class HackedPythonVersion(object):
    """A Beautiful hack, which allows us to tell pip which version of Python we're using."""

    def __init__(self, python_version, python_path):
        self.python_version = python_version
        self.python_path = python_path

    def __enter__(self):
        # Only inject when the value is valid
        if self.python_version:
            os.environ["PIP_PYTHON_VERSION"] = str(self.python_version)
        if self.python_path:
            os.environ["PIP_PYTHON_PATH"] = str(self.python_path)

    def __exit__(self, *args):
        # Restore original Python version information.
        try:
            del os.environ["PIP_PYTHON_VERSION"]
        except KeyError:
            pass


def prepare_pip_source_args(sources, pip_args=None):
    if pip_args is None:
        pip_args = []
    if sources:
        # Add the source to notpip.
        package_url = sources[0].get("url")
        if not package_url:
            raise PipenvUsageError("[[source]] section does not contain a URL.")
        pip_args.extend(["-i", package_url])
        # Trust the host if it's not verified.
        if not sources[0].get("verify_ssl", True):
            url_parts = urllib3_util.parse_url(package_url)
            url_port = ":{0}".format(url_parts.port) if url_parts.port else ""
            pip_args.extend(
                ["--trusted-host", "{0}{1}".format(url_parts.host, url_port)]
            )
        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                url = source.get("url")
                if not url:  # not harmless, just don't continue
                    continue
                pip_args.extend(["--extra-index-url", url])
                # Trust the host if it's not verified.
                if not source.get("verify_ssl", True):
                    url_parts = urllib3_util.parse_url(url)
                    url_port = ":{0}".format(url_parts.port) if url_parts.port else ""
                    pip_args.extend(
                        ["--trusted-host", "{0}{1}".format(url_parts.host, url_port)]
                    )
    return pip_args


@lru_cache()
def get_pipenv_sitedir():
    # type: () -> Optional[str]
    import pkg_resources
    site_dir = next(
        iter(d for d in pkg_resources.working_set if d.key.lower() == "pipenv"), None
    )
    if site_dir is not None:
        return site_dir.location
    return None


class Resolver(object):
    def __init__(self, constraints, req_dir, project, sources, clear=False, pre=False):
        from pipenv.patched.piptools import logging as piptools_logging
        if environments.is_verbose():
            logging.log.verbose = True
            piptools_logging.log.verbose = True
        self.initial_constraints = constraints
        self.req_dir = req_dir
        self.project = project
        self.sources = sources
        self.resolved_tree = set()
        self.hashes = {}
        self.clear = clear
        self.pre = pre
        self.results = None
        self._pip_args = None
        self._constraints = None
        self._parsed_constraints = None
        self._resolver = None
        self._repository = None
        self._session = None
        self._constraint_file = None
        self._pip_options = None
        self._pip_command = None
        self._retry_attempts = 0

    def __repr__(self):
        return (
            "<Resolver (constraints={self.initial_constraints}, req_dir={self.req_dir}, "
            "sources={self.sources})>".format(self=self)
        )

    @staticmethod
    @lru_cache()
    def _get_pip_command():
        from .vendor.pip_shims.shims import Command

        class PipCommand(Command):
            """Needed for pip-tools."""

            name = "PipCommand"

        from pipenv.patched.piptools.scripts.compile import get_pip_command
        return get_pip_command()

    @classmethod
    def get_metadata(
        cls,
        deps,  # type: List[str]
        index_lookup,  # type: Dict[str, str]
        markers_lookup,  # type: Dict[str, str]
        project,  # type: Project
        sources  # type: Dict[str, str]
    ):
        # type: (...) -> Tuple[Set[str], Dict[str, Dict[str, Union[str, bool, List[str]]]], Dict[str, str], Dict[str, str]]
        constraints = set()  # type: Set[str]
        skipped = dict()  # type: Dict[str, Dict[str, Union[str, bool, List[str]]]]
        if index_lookup is None:
            index_lookup = {}
        if markers_lookup is None:
            markers_lookup = {}
        for dep in deps:
            if not dep:
                continue
            req, req_idx, markers_idx = cls.parse_line(
                dep, index_lookup=index_lookup, markers_lookup=markers_lookup, project=project
            )
            index_lookup.update(req_idx)
            markers_lookup.update(markers_idx)
            constraint_update, lockfile_update = cls.get_deps_from_req(req)
            constraints |= constraint_update
            skipped.update(lockfile_update)
        return constraints, skipped, index_lookup, markers_lookup

    @classmethod
    def parse_line(
        cls,
        line,  # type: str
        index_lookup=None,  # type: Dict[str, str]
        markers_lookup=None,  # type: Dict[str, str]
        project=None  # type: Optional[Project]
    ):
        # type: (...) -> Tuple[Requirement, Dict[str, str], Dict[str, str]]
        from .vendor.requirementslib.models.requirements import Requirement
        from .exceptions import ResolutionFailure
        if index_lookup is None:
            index_lookup = {}
        if markers_lookup is None:
            markers_lookup = {}
        if project is None:
            from .project import Project
            project = Project()
        url = None
        indexes, trusted_hosts, remainder = parse_indexes(line)
        if indexes:
            url = indexes[0]
        line = " ".join(remainder)
        try:
            req = Requirement.from_line(line)
        except ValueError:
            raise ResolutionFailure("Failed to resolve requirement from line: {0!s}".format(line))
        if url:
            index_lookup[req.normalized_name] = project.get_source(
                url=url, refresh=True).get("name")
        # strip the marker and re-add it later after resolution
        # but we will need a fallback in case resolution fails
        # eg pypiwin32
        if req.markers:
            markers_lookup[req.normalized_name] = req.markers.replace('"', "'")
        return req, index_lookup, markers_lookup

    @classmethod
    def get_deps_from_line(cls, line):
        # type: (str) -> Tuple[Set[str], Dict[str, Dict[str, Union[str, bool, List[str]]]]]
        req, _, _ = cls.parse_line(line)
        return cls.get_deps_from_req(req)

    @classmethod
    def get_deps_from_req(cls, req):
        # type: (Requirement) -> Tuple[Set[str], Dict[str, Dict[str, Union[str, bool, List[str]]]]]
        from requirementslib.models.utils import _requirement_to_str_lowercase_name
        constraints = set()  # type: Set[str]
        locked_deps = dict()  # type: Dict[str, Dict[str, Union[str, bool, List[str]]]]
        if req.is_file_or_url or req.is_vcs and not req.is_wheel:
            # for local packages with setup.py files and potential direct url deps:
            if req.is_vcs:
                req_list, lockfile = get_vcs_deps(reqs=[req])
                req = next(iter(req for req in req_list if req is not None), req_list)
                entry = lockfile[pep423_name(req.normalized_name)]
            else:
                _, entry = req.pipfile_entry
            parsed_line = req.req.parsed_line  # type: Line
            setup_info = None  # type: Any
            name = req.normalized_name
            setup_info = req.req.setup_info
            locked_deps[pep423_name(name)] = entry
            requirements = [v for v in getattr(setup_info, "requires", {}).values()]
            for r in requirements:
                if getattr(r, "url", None) and not getattr(r, "editable", False):
                    if r is not None:
                        if not r.url:
                            continue
                        line = _requirement_to_str_lowercase_name(r)
                        new_req, _, _ = cls.parse_line(line)
                    if r.marker and not r.marker.evaluate():
                        new_constraints = {}
                        _, new_entry = req.pipfile_entry
                        new_lock = {
                            pep_423_name(new_req.normalized_name): new_entry
                        }
                    else:
                        new_constraints, new_lock = cls.get_deps_from_req(new_req)
                    locked_deps.update(new_lock)
                    constraints |= new_constraints
                else:
                    if r is not None:
                        line = _requirement_to_str_lowercase_name(r)
                        constraints.add(line)
            # ensure the top level entry remains as provided
            # note that we shouldn't pin versions for editable vcs deps
            if (not req.is_vcs or (req.is_vcs and not req.editable)):
                if req.specifiers:
                    locked_deps[name]["version"] = req.specifiers
                elif parsed_line.setup_info and parsed_line.setup_info.version:
                    locked_deps[name]["version"] = "=={}".format(
                        parsed_line.setup_info.version
                    )
            # if not req.is_vcs:
            locked_deps.update({name: entry})
            if req.is_vcs and req.editable:
                constraints.add(req.constraint_line)
            if req.is_file_or_url and req.req.is_local and req.editable and (
                    req.req.setup_path is not None and os.path.exists(req.req.setup_path)):
                constraints.add(req.constraint_line)
        else:
            constraints.add(req.constraint_line)
            return constraints, locked_deps
        return constraints, locked_deps

    @property
    def pip_command(self):
        if self._pip_command is None:
            self._pip_command = self._get_pip_command()
        return self._pip_command

    def prepare_pip_args(self):
        pip_args = []
        if self.sources:
            pip_args = prepare_pip_source_args(self.sources, pip_args)
        return pip_args

    @property
    def pip_args(self):
        if self._pip_args is None:
            self._pip_args = self.prepare_pip_args()
        return self._pip_args

    def prepare_constraint_file(self):
        from pipenv.vendor.vistir.path import create_tracked_tempfile
        constraints_file = create_tracked_tempfile(
            mode="w",
            prefix="pipenv-",
            suffix="-constraints.txt",
            dir=self.req_dir,
            delete=False,
        )
        if self.sources:
            requirementstxt_sources = " ".join(self.pip_args) if self.pip_args else ""
            requirementstxt_sources = requirementstxt_sources.replace(" --", "\n--")
            constraints_file.write(u"{0}\n".format(requirementstxt_sources))
        constraints = self.initial_constraints
        constraints_file.write(u"\n".join([c for c in constraints]))
        constraints_file.close()
        return constraints_file.name

    @property
    def constraint_file(self):
        if self._constraint_file is None:
            self._constraint_file = self.prepare_constraint_file()
        return self._constraint_file

    @property
    def pip_options(self):
        if self._pip_options is None:
            pip_options, _ = self.pip_command.parser.parse_args(self.pip_args)
            pip_options.cache_dir = environments.PIPENV_CACHE_DIR
            self._pip_options = pip_options
        if environments.is_verbose():
            click_echo(
                crayons.blue("Using pip: {0}".format(" ".join(self.pip_args))), err=True
            )
        return self._pip_options

    @property
    def session(self):
        if self._session is None:
            self._session = self.pip_command._build_session(self.pip_options)
        return self._session

    @property
    def repository(self):
        if self._repository is None:
            from pipenv.patched.piptools.repositories.pypi import PyPIRepository
            self._repository = PyPIRepository(
                pip_options=self.pip_options, use_json=False, session=self.session
            )
        return self._repository

    @property
    def constraints(self):
        if self._constraints is None:
            from pip_shims.shims import parse_requirements
            self._constraints = parse_requirements(
                self.constraint_file, finder=self.repository.finder, session=self.session,
                options=self.pip_options
            )
        return self._constraints

    @property
    def parsed_constraints(self):
        if self._parsed_constraints is None:
            self._parsed_constraints = [c for c in self.constraints]
        return self._parsed_constraints

    def get_resolver(self, clear=False, pre=False):
        from pipenv.patched.piptools.resolver import Resolver
        self._resolver = Resolver(
            constraints=self.parsed_constraints, repository=self.repository,
            clear_caches=clear, prereleases=pre,
        )

    @property
    def resolver(self):
        if self._resolver is None:
            self.get_resolver(clear=self.clear, pre=self.pre)
        return self._resolver

    def resolve(self):
        from pipenv.vendor.pip_shims.shims import DistributionNotFound
        from pipenv.vendor.requests.exceptions import HTTPError
        from pipenv.patched.piptools.exceptions import NoCandidateFound
        from pipenv.patched.piptools.cache import CorruptCacheError
        from .exceptions import CacheError, ResolutionFailure
        try:
            results = self.resolver.resolve(max_rounds=environments.PIPENV_MAX_ROUNDS)
        except CorruptCacheError as e:
            if environments.PIPENV_IS_CI or self.clear:
                if self._retry_attempts < 3:
                    self.get_resolver(clear=True, pre=self.pre)
                    self._retry_attempts += 1
                    self.resolve()
            else:
                raise CacheError(e.path)
        except (NoCandidateFound, DistributionNotFound, HTTPError) as e:
            raise ResolutionFailure(message=str(e))
        else:
            self.results = results
            self.resolved_tree.update(results)
            return self.resolved_tree

    @classmethod
    def prepend_hash_types(cls, checksums):
        cleaned_checksums = []
        for checksum in checksums:
            if not checksum:
                continue
            if not checksum.startswith("sha256:"):
                checksum = "sha256:{0}".format(checksum)
            cleaned_checksums.append(checksum)
        return cleaned_checksums

    def collect_hashes(self, ireq):
        from .vendor.requests import ConnectionError
        collected_hashes = []
        if ireq in self.hashes:
            collected_hashes += list(self.hashes.get(ireq, []))
        if self._should_include_hash(ireq):
            try:
                hash_map = self.get_hash(ireq)
                collected_hashes += list(hash_map)
            except (ValueError, KeyError, IndexError, ConnectionError):
                pass
        elif any(
            "python.org" in source["url"] or "pypi.org" in source["url"]
            for source in self.sources
        ):
            pkg_url = "https://pypi.org/pypi/{0}/json".format(ireq.name)
            session = _get_requests_session()
            try:
                # Grab the hashes from the new warehouse API.
                r = session.get(pkg_url, timeout=10)
                api_releases = r.json()["releases"]
                cleaned_releases = {}
                for api_version, api_info in api_releases.items():
                    api_version = clean_pkg_version(api_version)
                    cleaned_releases[api_version] = api_info
                version = ""
                if ireq.specifier:
                    spec = next(iter(s for s in list(ireq.specifier._specs)), None)
                    if spec:
                        version = spec.version
                for release in cleaned_releases[version]:
                    collected_hashes.append(release["digests"]["sha256"])
                collected_hashes = self.prepend_hash_types(collected_hashes)
            except (ValueError, KeyError, ConnectionError):
                if environments.is_verbose():
                    click_echo(
                        "{0}: Error generating hash for {1}".format(
                            crayons.red("Warning", bold=True), ireq.name
                        ), err=True
                    )
        return collected_hashes

    @staticmethod
    def _should_include_hash(ireq):
        from pipenv.vendor.vistir.compat import Path, to_native_string
        from pipenv.vendor.vistir.path import url_to_path

        # We can only hash artifacts.
        try:
            if not ireq.link.is_artifact:
                return False
        except AttributeError:
            return False

        # But we don't want normal pypi artifcats since the normal resolver
        # handles those
        if is_pypi_url(ireq.link.url):
            return False

        # We also don't want to try to hash directories as this will fail
        # as these are editable deps and are not hashable.
        if (ireq.link.scheme == "file" and
                Path(to_native_string(url_to_path(ireq.link.url))).is_dir()):
            return False
        return True

    def get_hash(self, ireq, ireq_hashes=None):
        """
        Retrieve hashes for a specific ``InstallRequirement`` instance.

        :param ireq: An ``InstallRequirement`` to retrieve hashes for
        :type ireq: :class:`~pip_shims.InstallRequirement`
        :return: A set of hashes.
        :rtype: Set
        """

        # We _ALWAYS MUST PRIORITIZE_ the inclusion of hashes from local sources
        # PLEASE *DO NOT MODIFY THIS* TO CHECK WHETHER AN IREQ ALREADY HAS A HASH
        # RESOLVED. The resolver will pull hashes from PyPI and only from PyPI.
        # The entire purpose of this approach is to include missing hashes.
        # This fixes a race condition in resolution for missing dependency caches
        # see pypa/pipenv#3289
        if self._should_include_hash(ireq) and (
            not ireq_hashes or ireq.link.scheme == "file"
        ):
            if not ireq_hashes:
                ireq_hashes = set()
            new_hashes = self.resolver.repository._hash_cache.get_hash(ireq.link)
            ireq_hashes = add_to_set(ireq_hashes, new_hashes)
        else:
            ireq_hashes = set(ireq_hashes)
        # The _ONLY CASE_ where we flat out set the value is if it isn't present
        # It's a set, so otherwise we *always* need to do a union update
        if ireq not in self.hashes:
            return ireq_hashes
        else:
            return self.hashes[ireq] | ireq_hashes

    def resolve_hashes(self):
        if self.results is not None:
            resolved_hashes = self.resolver.resolve_hashes(self.results)
            for ireq, ireq_hashes in resolved_hashes.items():
                self.hashes[ireq] = self.get_hash(ireq, ireq_hashes=ireq_hashes)
            return self.hashes


def _show_warning(message, category, filename, lineno, line):
    warnings.showwarning(message=message, category=category, filename=filename,
                         lineno=lineno, file=sys.stderr, line=line)
    sys.stderr.flush()


def actually_resolve_deps(
    deps,
    index_lookup,
    markers_lookup,
    project,
    sources,
    clear,
    pre,
    req_dir=None,
):
    from pipenv.vendor.vistir.path import create_tracked_tempdir
    from pipenv.vendor.requirementslib.models.requirements import Requirement

    if not req_dir:
        req_dir = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")
    warning_list = []

    with warnings.catch_warnings(record=True) as warning_list:
        constraints, skipped, index_lookup, markers_lookup = Resolver.get_metadata(
            deps, index_lookup, markers_lookup, project, sources,
        )
        resolver = Resolver(constraints, req_dir, project, sources, clear=clear, pre=pre)
        resolved_tree = resolver.resolve()
        hashes = resolver.resolve_hashes()
        reqs = [(Requirement.from_ireq(ireq), ireq) for ireq in resolved_tree]
        results = {}
        for req, ireq in reqs:
            if (req.vcs and req.editable and not req.is_direct_url):
                continue
            collected_hashes = resolver.collect_hashes(ireq)
            if collected_hashes:
                req = req.add_hashes(collected_hashes)
            elif resolver._should_include_hash(ireq):
                existing_hashes = hashes.get(ireq, set())
                discovered_hashes = existing_hashes | resolver.get_hash(ireq)
                if discovered_hashes:
                    req = req.add_hashes(discovered_hashes)
                resolver.hashes[ireq] = discovered_hashes
            if req.specifiers:
                version = str(req.get_version())
            else:
                version = None
            index = index_lookup.get(req.normalized_name)
            markers = markers_lookup.get(req.normalized_name)
            req.index = index
            name, pf_entry = req.pipfile_entry
            name = pep423_name(req.name)
            entry = {}
            if isinstance(pf_entry, six.string_types):
                entry["version"] = pf_entry.lstrip("=")
            else:
                entry.update(pf_entry)
                if version is not None:
                    entry["version"] = version
                if req.line_instance.is_direct_url:
                    entry["file"] = req.req.uri
            if collected_hashes:
                entry["hashes"] = sorted(set(collected_hashes))
            entry["name"] = name
            if index:  # and index != next(iter(project.sources), {}).get("name"):
                entry.update({"index": index})
            if markers:
                entry.update({"markers": markers})
            entry = translate_markers(entry)
            if name in results:
                results[name].update(entry)
            else:
                results[name] = entry
        for k in list(skipped.keys()):
            req = Requirement.from_pipfile(k, skipped[k])
            ref = None
            if req.is_vcs:
                ref = req.commit_hash
            ireq = req.as_ireq()
            entry = skipped[k].copy()
            entry["name"] = req.name
            ref = ref if ref is not None else entry.get("ref")
            if ref:
                entry["ref"] = ref
            if resolver._should_include_hash(ireq):
                collected_hashes = resolver.collect_hashes(ireq)
                if collected_hashes:
                    entry["hashes"] = sorted(set(collected_hashes))
            if k in results:
                results[k].update(entry)
            else:
                results[k] = entry
        results = list(results.values())
    for warning in warning_list:
        _show_warning(warning.message, warning.category, warning.filename, warning.lineno,
                      warning.line)
    return (results, hashes, markers_lookup, resolver, skipped)


@contextlib.contextmanager
def create_spinner(text, nospin=None, spinner_name=None):
    from .vendor.vistir import spin
    from .vendor.vistir.misc import fs_str
    if not spinner_name:
        spinner_name = environments.PIPENV_SPINNER
    if nospin is None:
        nospin = environments.PIPENV_NOSPIN
    with spin.create_spinner(
            spinner_name=spinner_name,
            start_text=fs_str(text),
            nospin=nospin, write_to_stdout=False
    ) as sp:
        yield sp


def resolve(cmd, sp):
    import delegator
    from .cmdparse import Script
    from .vendor.pexpect.exceptions import EOF, TIMEOUT
    from .vendor.vistir.compat import to_native_string
    EOF.__module__ = "pexpect.exceptions"
    from ._compat import decode_output
    c = delegator.run(Script.parse(cmd).cmdify(), block=False, env=os.environ.copy())
    _out = decode_output("")
    result = None
    out = to_native_string("")
    while True:
        try:
            result = c.expect(u"\n", timeout=environments.PIPENV_INSTALL_TIMEOUT)
        except (EOF, TIMEOUT):
            pass
        if result is None:
            break
        _out = c.subprocess.before
        if _out is not None:
            _out = decode_output("{0}".format(_out))
            out += _out
            sp.text = to_native_string("{0}".format(_out[:100]))
        if environments.is_verbose():
            if _out is not None:
                sp._hide_cursor()
                sp.write(_out.rstrip())
                sp._show_cursor()
    c.block()
    if c.return_code != 0:
        sp.red.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format(
            "Locking Failed!"
        ))
        click_echo(c.out.strip(), err=True)
        click_echo(c.err.strip(), err=True)
        sys.exit(c.return_code)
    return c


def get_locked_dep(dep, pipfile_section, prefer_pipfile=True):
    # the prefer pipfile flag is not used yet, but we are introducing
    # it now for development purposes
    # TODO: Is this implementation clear? How can it be improved?
    entry = None
    cleaner_kwargs = {
        "is_top_level": False,
        "pipfile_entry": None
    }
    if isinstance(dep, Mapping) and dep.get("name", ""):
        dep_name = pep423_name(dep["name"])
        name = next(iter(
            k for k in pipfile_section.keys()
            if pep423_name(k) == dep_name
        ), None)
        entry = pipfile_section[name] if name else None

    if entry:
        cleaner_kwargs.update({"is_top_level": True, "pipfile_entry": entry})
    lockfile_entry = clean_resolved_dep(dep, **cleaner_kwargs)
    if entry and isinstance(entry, Mapping):
        version = entry.get("version", "") if entry else ""
    else:
        version = entry if entry else ""
    lockfile_name, lockfile_dict = lockfile_entry.copy().popitem()
    lockfile_version = lockfile_dict.get("version", "")
    # Keep pins from the lockfile
    if prefer_pipfile and lockfile_version != version and version.startswith("=="):
        lockfile_dict["version"] = version
    lockfile_entry[lockfile_name] = lockfile_dict
    return lockfile_entry


def prepare_lockfile(results, pipfile, lockfile):
    # from .vendor.requirementslib.utils import is_vcs
    for dep in results:
        if not dep:
            continue
        # Merge in any relevant information from the pipfile entry, including
        # markers, normalized names, URL info, etc that we may have dropped during lock
        # if not is_vcs(dep):
        lockfile_entry = get_locked_dep(dep, pipfile)
        name = next(iter(k for k in lockfile_entry.keys()))
        current_entry = lockfile.get(name)
        if current_entry:
            if not isinstance(current_entry, Mapping):
                lockfile[name] = lockfile_entry[name]
            else:
                lockfile[name].update(lockfile_entry[name])
        else:
            lockfile[name] = lockfile_entry[name]
    return lockfile


def venv_resolve_deps(
    deps,
    which,
    project,
    pre=False,
    clear=False,
    allow_global=False,
    pypi_mirror=None,
    dev=False,
    pipfile=None,
    lockfile=None
):
    """
    Resolve dependencies for a pipenv project, acts as a portal to the target environment.

    Regardless of whether a virtual environment is present or not, this will spawn
    a subproces which is isolated to the target environment and which will perform
    dependency resolution.  This function reads the output of that call and mutates
    the provided lockfile accordingly, returning nothing.

    :param List[:class:`~requirementslib.Requirement`] deps: A list of dependencies to resolve.
    :param Callable which: [description]
    :param project: The pipenv Project instance to use during resolution
    :param Optional[bool] pre: Whether to resolve pre-release candidates, defaults to False
    :param Optional[bool] clear: Whether to clear the cache during resolution, defaults to False
    :param Optional[bool] allow_global: Whether to use *sys.executable* as the python binary, defaults to False
    :param Optional[str] pypi_mirror: A URL to substitute any time *pypi.org* is encountered, defaults to None
    :param Optional[bool] dev: Whether to target *dev-packages* or not, defaults to False
    :param pipfile: A Pipfile section to operate on, defaults to None
    :type pipfile: Optional[Dict[str, Union[str, Dict[str, bool, List[str]]]]]
    :param Dict[str, Any] lockfile: A project lockfile to mutate, defaults to None
    :raises RuntimeError: Raised on resolution failure
    :return: Nothing
    :rtype: None
    """

    from .vendor.vistir.misc import fs_str
    from .vendor.vistir.compat import Path, JSONDecodeError
    from .vendor.vistir.path import create_tracked_tempdir
    from . import resolver
    from ._compat import decode_for_output
    import json

    results = []
    pipfile_section = "dev-packages" if dev else "packages"
    lockfile_section = "develop" if dev else "default"
    if not deps:
        if not project.pipfile_exists:
            return None
        deps = project.parsed_pipfile.get(pipfile_section, {})
    if not deps:
        return None

    if not pipfile:
        pipfile = getattr(project, pipfile_section, {})
    if not lockfile:
        lockfile = project._lockfile
    req_dir = create_tracked_tempdir(prefix="pipenv", suffix="requirements")
    cmd = [
        which("python", allow_global=allow_global),
        Path(resolver.__file__.rstrip("co")).as_posix()
    ]
    if pre:
        cmd.append("--pre")
    if clear:
        cmd.append("--clear")
    if allow_global:
        cmd.append("--system")
    if dev:
        cmd.append("--dev")
    with temp_environ():
        os.environ.update({fs_str(k): fs_str(val) for k, val in os.environ.items()})
        if pypi_mirror:
            os.environ["PIPENV_PYPI_MIRROR"] = str(pypi_mirror)
        os.environ["PIPENV_VERBOSITY"] = str(environments.PIPENV_VERBOSITY)
        os.environ["PIPENV_REQ_DIR"] = fs_str(req_dir)
        os.environ["PIP_NO_INPUT"] = fs_str("1")
        os.environ["PIPENV_SITE_DIR"] = get_pipenv_sitedir()
        with create_spinner(text=decode_for_output("Locking...")) as sp:
            # This conversion is somewhat slow on local and file-type requirements since
            # we now download those requirements / make temporary folders to perform
            # dependency resolution on them, so we are including this step inside the
            # spinner context manager for the UX improvement
            sp.write(decode_for_output("Building requirements..."))
            deps = convert_deps_to_pip(
                deps, project, r=False, include_index=True
            )
            constraints = set(deps)
            os.environ["PIPENV_PACKAGES"] = str("\n".join(constraints))
            sp.write(decode_for_output("Resolving dependencies..."))
            c = resolve(cmd, sp)
            results = c.out.strip()
            sp.green.ok(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
    if environments.is_verbose():
        click_echo(results.split("RESULTS:")[1], err=True)
    try:
        results = json.loads(results.split("RESULTS:")[1].strip())

    except (IndexError, JSONDecodeError):
        click_echo(c.out.strip(), err=True)
        click_echo(c.err.strip(), err=True)
        raise RuntimeError("There was a problem with locking.")
    if lockfile_section not in lockfile:
        lockfile[lockfile_section] = {}
    prepare_lockfile(results, pipfile, lockfile[lockfile_section])


def resolve_deps(
    deps,
    which,
    project,
    sources=None,
    python=False,
    clear=False,
    pre=False,
    allow_global=False,
    req_dir=None
):
    """Given a list of dependencies, return a resolved list of dependencies,
    using pip-tools -- and their hashes, using the warehouse API / pip.
    """
    index_lookup = {}
    markers_lookup = {}
    python_path = which("python", allow_global=allow_global)
    if not os.environ.get("PIP_SRC"):
        os.environ["PIP_SRC"] = project.virtualenv_src_location
    backup_python_path = sys.executable
    results = []
    if not deps:
        return results
    # First (proper) attempt:
    req_dir = req_dir if req_dir else os.environ.get("req_dir", None)
    if not req_dir:
        from .vendor.vistir.path import create_tracked_tempdir
        req_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-requirements")
    with HackedPythonVersion(python_version=python, python_path=python_path):
        try:
            resolved_tree, hashes, markers_lookup, resolver, skipped = actually_resolve_deps(
                deps,
                index_lookup,
                markers_lookup,
                project,
                sources,
                clear,
                pre,
                req_dir=req_dir,
            )
        except RuntimeError:
            # Don't exit here, like usual.
            resolved_tree = None
    # Second (last-resort) attempt:
    if resolved_tree is None:
        with HackedPythonVersion(
            python_version=".".join([str(s) for s in sys.version_info[:3]]),
            python_path=backup_python_path,
        ):
            try:
                # Attempt to resolve again, with different Python version information,
                # particularly for particularly particular packages.
                resolved_tree, hashes, markers_lookup, resolver, skipped = actually_resolve_deps(
                    deps,
                    index_lookup,
                    markers_lookup,
                    project,
                    sources,
                    clear,
                    pre,
                    req_dir=req_dir,
                )
            except RuntimeError:
                sys.exit(1)
    return resolved_tree


def is_star(val):
    return isinstance(val, six.string_types) and val == "*"


def is_pinned(val):
    if isinstance(val, Mapping):
        val = val.get("version")
    return isinstance(val, six.string_types) and val.startswith("==")


def convert_deps_to_pip(deps, project=None, r=True, include_index=True):
    """"Converts a Pipfile-formatted dependency to a pip-formatted one."""
    from .vendor.requirementslib.models.requirements import Requirement

    dependencies = []
    for dep_name, dep in deps.items():
        if project:
            project.clear_pipfile_cache()
        indexes = getattr(project, "pipfile_sources", []) if project is not None else []
        new_dep = Requirement.from_pipfile(dep_name, dep)
        if new_dep.index:
            include_index = True
        req = new_dep.as_line(sources=indexes if include_index else None).strip()
        dependencies.append(req)
    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    from .vendor.vistir.path import create_tracked_tempfile
    f = create_tracked_tempfile(suffix="-requirements.txt", delete=False)
    f.write("\n".join(dependencies).encode("utf-8"))
    f.close()
    return f.name


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
        raise OSError(
            "a file with the same name as the desired dir, '{0}', already exists.".format(
                newdir
            )
        )

    else:
        head, tail = os.path.split(newdir)
        if head and not os.path.isdir(head):
            mkdir_p(head)
        if tail:
            # Even though we've checked that the directory doesn't exist above, it might exist
            # now if some other process has created it between now and the time we checked it.
            try:
                os.mkdir(newdir)
            except OSError as exn:
                # If we failed because the directory does exist, that's not a problem -
                # that's what we were trying to do anyway. Only re-raise the exception
                # if we failed for some other reason.
                if exn.errno != errno.EEXIST:
                    raise


def is_required_version(version, specified_version):
    """Check to see if there's a hard requirement for version
    number provided in the Pipfile.
    """
    # Certain packages may be defined with multiple values.
    if isinstance(specified_version, dict):
        specified_version = specified_version.get("version", "")
    if specified_version.startswith("=="):
        return version.strip() == specified_version.split("==")[1].strip()

    return True


def is_editable(pipfile_entry):
    if hasattr(pipfile_entry, "get"):
        return pipfile_entry.get("editable", False) and any(
            pipfile_entry.get(key) for key in ("file", "path") + VCS_LIST
        )
    return False


def is_installable_file(path):
    """Determine if a path can potentially be installed"""
    from .vendor.pip_shims.shims import is_installable_dir, is_archive_file
    from .patched.notpip._internal.utils.packaging import specifiers
    from ._compat import Path

    if hasattr(path, "keys") and any(
        key for key in path.keys() if key in ["file", "path"]
    ):
        path = urlparse(path["file"]).path if "file" in path else path["path"]
    if not isinstance(path, six.string_types) or path == "*":
        return False

    # If the string starts with a valid specifier operator, test if it is a valid
    # specifier set before making a path object (to avoid breaking windows)
    if any(path.startswith(spec) for spec in "!=<>~"):
        try:
            specifiers.SpecifierSet(path)
        # If this is not a valid specifier, just move on and try it as a path
        except specifiers.InvalidSpecifier:
            pass
        else:
            return False

    if not os.path.exists(os.path.abspath(path)):
        return False

    lookup_path = Path(path)
    absolute_path = "{0}".format(lookup_path.absolute())
    if lookup_path.is_dir() and is_installable_dir(absolute_path):
        return True

    elif lookup_path.is_file() and is_archive_file(absolute_path):
        return True

    return False


def is_file(package):
    """Determine if a package name is for a File dependency."""
    if hasattr(package, "keys"):
        return any(key for key in package.keys() if key in ["file", "path"])

    if os.path.exists(str(package)):
        return True

    for start in SCHEME_LIST:
        if str(package).startswith(start):
            return True

    return False


def pep440_version(version):
    """Normalize version to PEP 440 standards"""
    from .vendor.pip_shims.shims import parse_version

    # Use pip built-in version parser.
    return str(parse_version(version))


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    name = name.lower()
    if any(i not in name for i in (VCS_LIST + SCHEME_LIST)):
        return name.replace("_", "-")

    else:
        return name


def proper_case(package_name):
    """Properly case project name from pypi.org."""
    # Hit the simple API.
    r = _get_requests_session().get(
        "https://pypi.org/pypi/{0}/json".format(package_name), timeout=0.3, stream=True
    )
    if not r.ok:
        raise IOError(
            "Unable to find package {0} in PyPI repository.".format(package_name)
        )

    r = parse.parse("https://pypi.org/pypi/{name}/json", r.url)
    good_name = r["name"]
    return good_name


def get_windows_path(*args):
    """Sanitize a path for windows environments

    Accepts an arbitrary list of arguments and makes a clean windows path"""
    return os.path.normpath(os.path.join(*args))


def find_windows_executable(bin_path, exe_name):
    """Given an executable name, search the given location for an executable"""
    requested_path = get_windows_path(bin_path, exe_name)
    if os.path.isfile(requested_path):
        return requested_path

    try:
        pathext = os.environ["PATHEXT"]
    except KeyError:
        pass
    else:
        for ext in pathext.split(os.pathsep):
            path = get_windows_path(bin_path, exe_name + ext.strip().lower())
            if os.path.isfile(path):
                return path

    return find_executable(exe_name)


def path_to_url(path):
    from ._compat import Path

    return Path(normalize_drive(os.path.abspath(path))).as_uri()


def normalize_path(path):
    return os.path.expandvars(os.path.expanduser(
        os.path.normcase(os.path.normpath(os.path.abspath(str(path))))
    ))


def get_url_name(url):
    if not isinstance(url, six.string_types):
        return
    return urllib3_util.parse_url(url).host


def get_canonical_names(packages):
    """Canonicalize a list of packages and return a set of canonical names"""
    from .vendor.packaging.utils import canonicalize_name

    if not isinstance(packages, Sequence):
        if not isinstance(packages, six.string_types):
            return packages
        packages = [packages,]
    return set([canonicalize_name(pkg) for pkg in packages if pkg])


def walk_up(bottom):
    """Mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """
    bottom = os.path.realpath(bottom)
    # Get files in current dir.
    try:
        names = os.listdir(bottom)
    except Exception:
        return

    dirs, nondirs = [], []
    for name in names:
        if os.path.isdir(os.path.join(bottom, name)):
            dirs.append(name)
        else:
            nondirs.append(name)
    yield bottom, dirs, nondirs

    new_path = os.path.realpath(os.path.join(bottom, ".."))
    # See if we are at the top.
    if new_path == bottom:
        return

    for x in walk_up(new_path):
        yield x


def find_requirements(max_depth=3):
    """Returns the path of a Pipfile in parent directories."""
    i = 0
    for c, d, f in walk_up(os.getcwd()):
        i += 1
        if i < max_depth:
            if "requirements.txt":
                r = os.path.join(c, "requirements.txt")
                if os.path.isfile(r):
                    return r

    raise RuntimeError("No requirements.txt found!")


# Borrowed from Pew.
# See https://github.com/berdario/pew/blob/master/pew/_utils.py#L82
@contextmanager
def temp_environ():
    """Allow the ability to set os.environ temporarily"""
    environ = dict(os.environ)
    try:
        yield

    finally:
        os.environ.clear()
        os.environ.update(environ)


@contextmanager
def temp_path():
    """Allow the ability to set os.environ temporarily"""
    path = [p for p in sys.path]
    try:
        yield
    finally:
        sys.path = [p for p in path]


def load_path(python):
    from ._compat import Path
    import delegator
    import json
    python = Path(python).as_posix()
    json_dump_commmand = '"import json, sys; print(json.dumps(sys.path));"'
    c = delegator.run('"{0}" -c {1}'.format(python, json_dump_commmand))
    if c.return_code == 0:
        return json.loads(c.out.strip())
    else:
        return []


def is_valid_url(url):
    """Checks if a given string is an url"""
    pieces = urlparse(url)
    return all([pieces.scheme, pieces.netloc])


def is_pypi_url(url):
    return bool(re.match(r"^http[s]?:\/\/pypi(?:\.python)?\.org\/simple[\/]?$", url))


def replace_pypi_sources(sources, pypi_replacement_source):
    return [pypi_replacement_source] + [
        source for source in sources if not is_pypi_url(source["url"])
    ]


def create_mirror_source(url):
    return {
        "url": url,
        "verify_ssl": url.startswith("https://"),
        "name": urlparse(url).hostname,
    }


def download_file(url, filename):
    """Downloads file from url to a path with filename"""
    r = _get_requests_session().get(url, stream=True)
    if not r.ok:
        raise IOError("Unable to download file")

    with open(filename, "wb") as f:
        f.write(r.content)


def normalize_drive(path):
    """Normalize drive in path so they stay consistent.

    This currently only affects local drives on Windows, which can be
    identified with either upper or lower cased drive names. The case is
    always converted to uppercase because it seems to be preferred.

    See: <https://github.com/pypa/pipenv/issues/1218>
    """
    if os.name != "nt" or not isinstance(path, six.string_types):
        return path

    drive, tail = os.path.splitdrive(path)
    # Only match (lower cased) local drives (e.g. 'c:'), not UNC mounts.
    if drive.islower() and len(drive) == 2 and drive[1] == ":":
        return "{}{}".format(drive.upper(), tail)

    return path


def is_readonly_path(fn):
    """Check if a provided path exists and is readonly.

    Permissions check is `bool(path.stat & stat.S_IREAD)` or `not os.access(path, os.W_OK)`
    """
    if os.path.exists(fn):
        return (os.stat(fn).st_mode & stat.S_IREAD) or not os.access(fn, os.W_OK)

    return False


def set_write_bit(fn):
    if isinstance(fn, six.string_types) and not os.path.exists(fn):
        return
    os.chmod(fn, stat.S_IWRITE | stat.S_IWUSR | stat.S_IRUSR)
    return


def rmtree(directory, ignore_errors=False):
    shutil.rmtree(
        directory, ignore_errors=ignore_errors, onerror=handle_remove_readonly
    )


def handle_remove_readonly(func, path, exc):
    """Error handler for shutil.rmtree.

    Windows source repo folders are read-only by default, so this error handler
    attempts to set them as writeable and then proceed with deletion."""
    # Check for read-only attribute
    default_warning_message = (
        "Unable to remove file due to permissions restriction: {!r}"
    )
    # split the initial exception out into its type, exception, and traceback
    exc_type, exc_exception, exc_tb = exc
    if is_readonly_path(path):
        # Apply write permission and call original function
        set_write_bit(path)
        try:
            func(path)
        except (OSError, IOError) as e:
            if e.errno in [errno.EACCES, errno.EPERM]:
                warnings.warn(default_warning_message.format(path), ResourceWarning)
                return

    if exc_exception.errno in [errno.EACCES, errno.EPERM]:
        warnings.warn(default_warning_message.format(path), ResourceWarning)
        return

    raise exc


def escape_cmd(cmd):
    if any(special_char in cmd for special_char in ["<", ">", "&", ".", "^", "|", "?"]):
        cmd = '\"{0}\"'.format(cmd)
    return cmd


def safe_expandvars(value):
    """Call os.path.expandvars if value is a string, otherwise do nothing.
    """
    if isinstance(value, six.string_types):
        return os.path.expandvars(value)
    return value


def get_vcs_deps(
    project=None,
    dev=False,
    pypi_mirror=None,
    packages=None,
    reqs=None
):
    from .vendor.requirementslib.models.requirements import Requirement

    section = "vcs_dev_packages" if dev else "vcs_packages"
    if reqs is None:
        reqs = []
    lockfile = {}
    if not reqs:
        if not project and not packages:
            raise ValueError(
                "Must supply either a project or a pipfile section to lock vcs dependencies."
            )
        if not packages:
            try:
                packages = getattr(project, section)
            except AttributeError:
                return [], []
        reqs = [Requirement.from_pipfile(name, entry) for name, entry in packages.items()]
    result = []
    for requirement in reqs:
        name = requirement.normalized_name
        commit_hash = None
        if requirement.is_vcs:
            try:
                with temp_path(), locked_repository(requirement) as repo:
                    from pipenv.vendor.requirementslib.models.requirements import Requirement
                    # from distutils.sysconfig import get_python_lib
                    # sys.path = [repo.checkout_directory, "", ".", get_python_lib(plat_specific=0)]
                    commit_hash = repo.get_commit_hash()
                    name = requirement.normalized_name
                    version = requirement._specifiers = "=={0}".format(requirement.req.setup_info.version)
                    lockfile[name] = requirement.pipfile_entry[1]
                    lockfile[name]['ref'] = commit_hash
                    result.append(requirement)
                    version = requirement.specifiers
                    if not version and requirement.specifiers:
                        version = requirement.specifiers
                    if version:
                        lockfile[name]['version'] = version
            except OSError:
                continue
    return result, lockfile


def translate_markers(pipfile_entry):
    """Take a pipfile entry and normalize its markers

    Provide a pipfile entry which may have 'markers' as a key or it may have
    any valid key from `packaging.markers.marker_context.keys()` and standardize
    the format into {'markers': 'key == "some_value"'}.

    :param pipfile_entry: A dictionariy of keys and values representing a pipfile entry
    :type pipfile_entry: dict
    :returns: A normalized dictionary with cleaned marker entries
    """
    if not isinstance(pipfile_entry, Mapping):
        raise TypeError("Entry is not a pipfile formatted mapping.")
    from .vendor.distlib.markers import DEFAULT_CONTEXT as marker_context
    from .vendor.packaging.markers import Marker
    from .vendor.vistir.misc import dedup

    allowed_marker_keys = ["markers"] + [k for k in marker_context.keys()]
    provided_keys = list(pipfile_entry.keys()) if hasattr(pipfile_entry, "keys") else []
    pipfile_markers = [k for k in provided_keys if k in allowed_marker_keys]
    new_pipfile = dict(pipfile_entry).copy()
    marker_set = set()
    if "markers" in new_pipfile:
        marker = str(Marker(new_pipfile.pop("markers")))
        if 'extra' not in marker:
            marker_set.add(marker)
    for m in pipfile_markers:
        entry = "{0}".format(pipfile_entry[m])
        if m != "markers":
            marker_set.add(str(Marker("{0}{1}".format(m, entry))))
            new_pipfile.pop(m)
    if marker_set:
        new_pipfile["markers"] = str(Marker(" or ".join(
            "{0}".format(s) if " and " in s else s
            for s in sorted(dedup(marker_set))
        ))).replace('"', "'")
    return new_pipfile


def clean_resolved_dep(dep, is_top_level=False, pipfile_entry=None):
    from .vendor.requirementslib.utils import is_vcs
    name = pep423_name(dep["name"])
    lockfile = {}
    # We use this to determine if there are any markers on top level packages
    # So we can make sure those win out during resolution if the packages reoccur
    if "version" in dep:
        version = "{0}".format(dep["version"])
        if not version.startswith("=="):
            version = "=={0}".format(version)
        lockfile["version"] = version
    if is_vcs(dep):
        ref = dep.get("ref", None)
        if ref is not None:
            lockfile["ref"] = ref
        vcs_type = next(iter(k for k in dep.keys() if k in VCS_LIST), None)
        if vcs_type:
            lockfile[vcs_type] = dep[vcs_type]
        if "subdirectory" in dep:
            lockfile["subdirectory"] = dep["subdirectory"]
    for key in ["hashes", "index", "extras", "editable"]:
        if key in dep:
            lockfile[key] = dep[key]
    # In case we lock a uri or a file when the user supplied a path
    # remove the uri or file keys from the entry and keep the path
    fs_key = next(iter(k for k in ["path", "file"] if k in dep), None)
    pipfile_fs_key = None
    if pipfile_entry:
        pipfile_fs_key = next(iter(k for k in ["path", "file"] if k in pipfile_entry), None)
    if fs_key and pipfile_fs_key and fs_key != pipfile_fs_key:
        lockfile[pipfile_fs_key] = pipfile_entry[pipfile_fs_key]
    elif fs_key is not None:
        lockfile[fs_key] = dep[fs_key]

    # If a package is **PRESENT** in the pipfile but has no markers, make sure we
    # **NEVER** include markers in the lockfile
    if "markers" in dep:
        # First, handle the case where there is no top level dependency in the pipfile
        if not is_top_level:
            try:
                lockfile["markers"] = translate_markers(dep)["markers"]
            except TypeError:
                pass
        # otherwise make sure we are prioritizing whatever the pipfile says about the markers
        # If the pipfile says nothing, then we should put nothing in the lockfile
        else:
            try:
                pipfile_entry = translate_markers(pipfile_entry)
                lockfile["markers"] = pipfile_entry.get("markers")
            except TypeError:
                pass
    return {name: lockfile}


def get_workon_home():
    from ._compat import Path

    workon_home = os.environ.get("WORKON_HOME")
    if not workon_home:
        if os.name == "nt":
            workon_home = "~/.virtualenvs"
        else:
            workon_home = os.path.join(
                os.environ.get("XDG_DATA_HOME", "~/.local/share"), "virtualenvs"
            )
    # Create directory if it does not already exist
    expanded_path = Path(os.path.expandvars(workon_home)).expanduser()
    mkdir_p(str(expanded_path))
    return expanded_path


def is_virtual_environment(path):
    """Check if a given path is a virtual environment's root.

    This is done by checking if the directory contains a Python executable in
    its bin/Scripts directory. Not technically correct, but good enough for
    general usage.
    """
    if not path.is_dir():
        return False
    for bindir_name in ('bin', 'Scripts'):
        for python in path.joinpath(bindir_name).glob('python*'):
            try:
                exeness = python.is_file() and os.access(str(python), os.X_OK)
            except OSError:
                exeness = False
            if exeness:
                return True
    return False


@contextmanager
def locked_repository(requirement):
    from .vendor.vistir.path import create_tracked_tempdir
    if not requirement.is_vcs:
        return
    original_base = os.environ.pop("PIP_SHIMS_BASE_MODULE", None)
    os.environ["PIP_SHIMS_BASE_MODULE"] = fs_str("pipenv.patched.notpip")
    src_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-src")
    try:
        with requirement.req.locked_vcs_repo(src_dir=src_dir) as repo:
            yield repo
    finally:
        if original_base:
            os.environ["PIP_SHIMS_BASE_MODULE"] = original_base


@contextmanager
def chdir(path):
    """Context manager to change working directories."""
    from ._compat import Path
    if not path:
        return
    prev_cwd = Path.cwd().as_posix()
    if isinstance(path, Path):
        path = path.as_posix()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(prev_cwd)


def looks_like_dir(path):
    seps = (sep for sep in (os.path.sep, os.path.altsep) if sep is not None)
    return any(sep in path for sep in seps)


def parse_indexes(line):
    from argparse import ArgumentParser
    parser = ArgumentParser("indexes")
    parser.add_argument(
        "--index", "-i", "--index-url",
        metavar="index_url", action="store", nargs="?",
    )
    parser.add_argument(
        "--extra-index-url", "--extra-index",
        metavar="extra_indexes",action="append",
    )
    parser.add_argument("--trusted-host", metavar="trusted_hosts", action="append")
    args, remainder = parser.parse_known_args(line.split())
    index = [] if not args.index else [args.index,]
    extra_indexes = [] if not args.extra_index_url else args.extra_index_url
    indexes = index + extra_indexes
    trusted_hosts = args.trusted_host if args.trusted_host else []
    return indexes, trusted_hosts, remainder


@contextmanager
def sys_version(version_tuple):
    """
    Set a temporary sys.version_info tuple

    :param version_tuple: a fake sys.version_info tuple
    """

    old_version = sys.version_info
    sys.version_info = version_tuple
    yield
    sys.version_info = old_version


def add_to_set(original_set, element):
    """Given a set and some arbitrary element, add the element(s) to the set"""
    if not element:
        return original_set
    if isinstance(element, Set):
        original_set |= element
    elif isinstance(element, (list, tuple)):
        original_set |= set(element)
    else:
        original_set.add(element)
    return original_set


def is_url_equal(url, other_url):
    # type: (str, str) -> bool
    """
    Compare two urls by scheme, host, and path, ignoring auth

    :param str url: The initial URL to compare
    :param str url: Second url to compare to the first
    :return: Whether the URLs are equal without **auth**, **query**, and **fragment**
    :rtype: bool

    >>> is_url_equal("https://user:pass@mydomain.com/some/path?some_query",
                     "https://user2:pass2@mydomain.com/some/path")
    True

    >>> is_url_equal("https://user:pass@mydomain.com/some/path?some_query",
                 "https://mydomain.com/some?some_query")
    False
    """
    if not isinstance(url, six.string_types):
        raise TypeError("Expected string for url, received {0!r}".format(url))
    if not isinstance(other_url, six.string_types):
        raise TypeError("Expected string for url, received {0!r}".format(other_url))
    parsed_url = urllib3_util.parse_url(url)
    parsed_other_url = urllib3_util.parse_url(other_url)
    unparsed = parsed_url._replace(auth=None, query=None, fragment=None).url
    unparsed_other = parsed_other_url._replace(auth=None, query=None, fragment=None).url
    return unparsed == unparsed_other


@lru_cache()
def make_posix(path):
    # type: (str) -> str
    """
    Convert a path with possible windows-style separators to a posix-style path
    (with **/** separators instead of **\\** separators).

    :param Text path: A path to convert.
    :return: A converted posix-style path
    :rtype: Text

    >>> make_posix("c:/users/user/venvs/some_venv\\Lib\\site-packages")
    "c:/users/user/venvs/some_venv/Lib/site-packages"

    >>> make_posix("c:\\users\\user\\venvs\\some_venv")
    "c:/users/user/venvs/some_venv"
    """
    if not isinstance(path, six.string_types):
        raise TypeError("Expected a string for path, received {0!r}...".format(path))
    starts_with_sep = path.startswith(os.path.sep)
    separated = normalize_path(path).split(os.path.sep)
    if isinstance(separated, (list, tuple)):
        path = posixpath.join(*separated)
        if starts_with_sep:
            path = "/{0}".format(path)
    return path


def get_pipenv_dist(pkg="pipenv", pipenv_site=None):
    from .resolver import find_site_path
    pipenv_libdir = os.path.dirname(os.path.abspath(__file__))
    if pipenv_site is None:
        pipenv_site = os.path.dirname(pipenv_libdir)
    pipenv_dist, _ = find_site_path(pkg, site_dir=pipenv_site)
    return pipenv_dist


def find_python(finder, line=None):
    """
    Given a `pythonfinder.Finder` instance and an optional line, find a corresponding python

    :param finder: A :class:`pythonfinder.Finder` instance to use for searching
    :type finder: :class:pythonfinder.Finder`
    :param str line: A version, path, name, or nothing, defaults to None
    :return: A path to python
    :rtype: str
    """

    if line and not isinstance(line, six.string_types):
        raise TypeError(
            "Invalid python search type: expected string, received {0!r}".format(line)
        )
    if line and os.path.isabs(line):
        if os.name == "nt":
            line = posixpath.join(*line.split(os.path.sep))
        return line
    if not finder:
        from pipenv.vendor.pythonfinder import Finder
        finder = Finder(global_search=True)
    if not line:
        result = next(iter(finder.find_all_python_versions()), None)
    elif line and line[0].isdigit() or re.match(r'[\d\.]+', line):
        result = finder.find_python_version(line)
    else:
        result = finder.find_python_version(name=line)
    if not result:
        result = finder.which(line)
    if not result and not line.startswith("python"):
        line = "python{0}".format(line)
        result = find_python(finder, line)
    if not result:
        result = next(iter(finder.find_all_python_versions()), None)
    if result:
        if not isinstance(result, six.string_types):
            return result.path.as_posix()
        return result
    return


def is_python_command(line):
    """
    Given an input, checks whether the input is a request for python or notself.

    This can be a version, a python runtime name, or a generic 'python' or 'pythonX.Y'

    :param str line: A potential request to find python
    :returns: Whether the line is a python lookup
    :rtype: bool
    """

    if not isinstance(line, six.string_types):
        raise TypeError("Not a valid command to check: {0!r}".format(line))

    from pipenv.vendor.pythonfinder.utils import PYTHON_IMPLEMENTATIONS
    is_version = re.match(r'[\d\.]+', line)
    if (line.startswith("python") or is_version or
            any(line.startswith(v) for v in PYTHON_IMPLEMENTATIONS)):
        return True
    # we are less sure about this but we can guess
    if line.startswith("py"):
        return True
    return False
