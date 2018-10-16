# -*- coding: utf-8 -*-
import errno
import logging
import os
import re
import shutil
import sys

import crayons
import parse
import six
import stat
import warnings

from click import echo as click_echo
from first import first
from vistir.misc import fs_str

try:
    from weakref import finalize
except ImportError:
    try:
        from .vendor.backports.weakref import finalize
    except ImportError:

        class finalize(object):
            def __init__(self, *args, **kwargs):
                logging.warn("weakref.finalize unavailable, not cleaning...")

            def detach(self):
                return False


logging.basicConfig(level=logging.ERROR)

from distutils.spawn import find_executable
from contextlib import contextmanager
from . import environments
from .pep508checker import lookup

six.add_move(six.MovedAttribute("Mapping", "collections", "collections.abc"))
from six.moves.urllib.parse import urlparse
from six.moves import Mapping

if six.PY2:

    class ResourceWarning(Warning):
        pass


specifiers = [k for k in lookup.keys()]
# List of version control systems we support.
VCS_LIST = ("git", "svn", "hg", "bzr")
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")
requests_session = None


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
    import delegator

    if not path_to_python:
        return None
    try:
        c = delegator.run([path_to_python, "--version"], block=False)
    except Exception:
        return None
    c.block()
    version = parse_python_version(c.out.strip() or c.err.strip())
    try:
        version = u"{major}.{minor}.{micro}".format(**version)
    except TypeError:
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
        pip_args.extend(["-i", sources[0]["url"]])
        # Trust the host if it's not verified.
        if not sources[0].get("verify_ssl", True):
            pip_args.extend(
                ["--trusted-host", urlparse(sources[0]["url"]).hostname]
            )
        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                pip_args.extend(["--extra-index-url", source["url"]])
                # Trust the host if it's not verified.
                if not source.get("verify_ssl", True):
                    pip_args.extend(
                        ["--trusted-host", urlparse(source["url"]).hostname]
                    )
    return pip_args


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
    from .patched.notpip._internal import basecommand
    from .patched.notpip._internal.req import parse_requirements
    from .patched.notpip._internal.exceptions import DistributionNotFound
    from .patched.notpip._vendor.requests.exceptions import HTTPError
    from pipenv.patched.piptools.resolver import Resolver
    from pipenv.patched.piptools.repositories.pypi import PyPIRepository
    from pipenv.patched.piptools.scripts.compile import get_pip_command
    from pipenv.patched.piptools import logging as piptools_logging
    from pipenv.patched.piptools.exceptions import NoCandidateFound
    from .vendor.requirementslib.models.requirements import Requirement
    from ._compat import TemporaryDirectory, NamedTemporaryFile

    class PipCommand(basecommand.Command):
        """Needed for pip-tools."""

        name = "PipCommand"

    constraints = []
    cleanup_req_dir = False
    if not req_dir:
        req_dir = TemporaryDirectory(suffix="-requirements", prefix="pipenv-")
        cleanup_req_dir = True
    for dep in deps:
        if not dep:
            continue
        url = None
        indexes, trusted_hosts, remainder = parse_indexes(dep)
        if indexes:
            url = indexes[0]
        dep = " ".join(remainder)
        req = Requirement.from_line(dep)

        # extra_constraints = []

        if url:
            index_lookup[req.name] = project.get_source(url=url).get("name")
        # strip the marker and re-add it later after resolution
        # but we will need a fallback in case resolution fails
        # eg pypiwin32
        if req.markers:
            markers_lookup[req.name] = req.markers.replace('"', "'")
        constraints.append(req.constraint_line)

    pip_command = get_pip_command()
    constraints_file = None
    pip_args = []
    if sources:
        pip_args = prepare_pip_source_args(sources, pip_args)
    if environments.is_verbose():
        print("Using pip: {0}".format(" ".join(pip_args)))
    with NamedTemporaryFile(
        mode="w",
        prefix="pipenv-",
        suffix="-constraints.txt",
        dir=req_dir.name,
        delete=False,
    ) as f:
        if sources:
            requirementstxt_sources = " ".join(pip_args) if pip_args else ""
            requirementstxt_sources = requirementstxt_sources.replace(" --", "\n--")
            f.write(u"{0}\n".format(requirementstxt_sources))
        f.write(u"\n".join([_constraint for _constraint in constraints]))
        constraints_file = f.name
    pip_options, _ = pip_command.parser.parse_args(pip_args)
    pip_options.cache_dir = environments.PIPENV_CACHE_DIR
    session = pip_command._build_session(pip_options)
    pypi = PyPIRepository(pip_options=pip_options, use_json=False, session=session)
    constraints = parse_requirements(
        constraints_file, finder=pypi.finder, session=pypi.session, options=pip_options
    )
    constraints = [c for c in constraints]
    if environments.is_verbose():
        logging.log.verbose = True
        piptools_logging.log.verbose = True
    resolved_tree = set()
    resolver = Resolver(
        constraints=constraints, repository=pypi, clear_caches=clear, prereleases=pre
    )
    # pre-resolve instead of iterating to avoid asking pypi for hashes of editable packages
    hashes = None
    try:
        results = resolver.resolve(max_rounds=environments.PIPENV_MAX_ROUNDS)
        hashes = resolver.resolve_hashes(results)
        resolved_tree.update(results)
    except (NoCandidateFound, DistributionNotFound, HTTPError) as e:
        click_echo(
            "{0}: Your dependencies could not be resolved. You likely have a "
            "mismatch in your sub-dependencies.\n  "
            "First try clearing your dependency cache with {1}, then try the original command again.\n "
            "Alternatively, you can use {2} to bypass this mechanism, then run "
            "{3} to inspect the situation.\n  "
            "Hint: try {4} if it is a pre-release dependency."
            "".format(
                crayons.red("Warning", bold=True),
                crayons.red("$ pipenv lock --clear"),
                crayons.red("$ pipenv install --skip-lock"),
                crayons.red("$ pipenv graph"),
                crayons.red("$ pipenv lock --pre"),
            ),
            err=True,
        )
        click_echo(crayons.blue(str(e)), err=True)
        if "no version found at all" in str(e):
            click_echo(
                crayons.blue(
                    "Please check your version specifier and version number. See PEP440 for more information."
                )
            )
        if cleanup_req_dir:
            req_dir.cleanup()
        raise RuntimeError
    if cleanup_req_dir:
        req_dir.cleanup()
    return (resolved_tree, hashes, markers_lookup, resolver)


def venv_resolve_deps(
    deps,
    which,
    project,
    pre=False,
    clear=False,
    allow_global=False,
    pypi_mirror=None,
):
    from .vendor.vistir.misc import fs_str
    from .vendor import delegator
    from . import resolver
    import json

    if not deps:
        return []
    resolver = escape_grouped_arguments(resolver.__file__.rstrip("co"))
    cmd = "{0} {1} {2} {3} {4}".format(
        escape_grouped_arguments(which("python", allow_global=allow_global)),
        resolver,
        "--pre" if pre else "",
        "--clear" if clear else "",
        "--system" if allow_global else "",
    )
    with temp_environ():
        os.environ = {fs_str(k): fs_str(val) for k, val in os.environ.items()}
        os.environ["PIPENV_PACKAGES"] = str("\n".join(deps))
        if pypi_mirror:
            os.environ["PIPENV_PYPI_MIRROR"] = str(pypi_mirror)
        os.environ["PIPENV_VERBOSITY"] = str(environments.PIPENV_VERBOSITY)
        c = delegator.run(cmd, block=True)
    try:
        assert c.return_code == 0
    except AssertionError:
        if environments.is_verbose():
            click_echo(c.out, err=True)
            click_echo(c.err, err=True)
        else:
            click_echo(c.err[(int(len(c.err) / 2) - 1):], err=True)
        sys.exit(c.return_code)
    if environments.is_verbose():
        click_echo(c.out.split("RESULTS:")[0], err=True)
    try:
        return json.loads(c.out.split("RESULTS:")[1].strip())

    except IndexError:
        raise RuntimeError("There was a problem with locking.")


def resolve_deps(
    deps,
    which,
    project,
    sources=None,
    python=False,
    clear=False,
    pre=False,
    allow_global=False,
):
    """Given a list of dependencies, return a resolved list of dependencies,
    using pip-tools -- and their hashes, using the warehouse API / pip.
    """
    from .patched.notpip._vendor.requests.exceptions import ConnectionError
    from .vendor.requirementslib.models.requirements import Requirement
    from ._compat import TemporaryDirectory

    index_lookup = {}
    markers_lookup = {}
    python_path = which("python", allow_global=allow_global)
    backup_python_path = sys.executable
    results = []
    if not deps:
        return results
    # First (proper) attempt:
    req_dir = TemporaryDirectory(prefix="pipenv-", suffix="-requirements")
    with HackedPythonVersion(python_version=python, python_path=python_path):
        try:
            resolved_tree, hashes, markers_lookup, resolver = actually_resolve_deps(
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
                resolved_tree, hashes, markers_lookup, resolver = actually_resolve_deps(
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
                req_dir.cleanup()
                sys.exit(1)
    for result in resolved_tree:
        if not result.editable:
            req = Requirement.from_ireq(result)
            name = pep423_name(req.name)
            version = str(req.get_version())
            index = index_lookup.get(result.name)
            req.index = index
            collected_hashes = []
            if result in hashes:
                collected_hashes = list(hashes.get(result))
            elif any(
                "python.org" in source["url"] or "pypi.org" in source["url"]
                for source in sources
            ):
                pkg_url = "https://pypi.org/pypi/{0}/json".format(name)
                session = _get_requests_session()
                try:
                    # Grab the hashes from the new warehouse API.
                    r = session.get(pkg_url, timeout=10)
                    api_releases = r.json()["releases"]
                    cleaned_releases = {}
                    for api_version, api_info in api_releases.items():
                        api_version = clean_pkg_version(api_version)
                        cleaned_releases[api_version] = api_info
                    for release in cleaned_releases[version]:
                        collected_hashes.append(release["digests"]["sha256"])
                    collected_hashes = ["sha256:" + s for s in collected_hashes]
                except (ValueError, KeyError, ConnectionError):
                    if environments.is_verbose():
                        click_echo(
                            "{0}: Error generating hash for {1}".format(
                                crayons.red("Warning", bold=True), name
                            )
                        )
            # # Collect un-collectable hashes (should work with devpi).
            # try:
            #     collected_hashes = collected_hashes + list(
            #         list(resolver.resolve_hashes([result]).items())[0][1]
            #     )
            # except (ValueError, KeyError, ConnectionError, IndexError):
            #     if verbose:
            #         print('Error generating hash for {}'.format(name))
            req.hashes = sorted(set(collected_hashes))
            name, _entry = req.pipfile_entry
            entry = {}
            if isinstance(_entry, six.string_types):
                entry["version"] = _entry.lstrip("=")
            else:
                entry.update(_entry)
                entry["version"] = version
            entry["name"] = name
            # if index:
            #     d.update({"index": index})
            if markers_lookup.get(result.name):
                entry.update({"markers": markers_lookup.get(result.name)})
            entry = translate_markers(entry)
            results.append(entry)
    req_dir.cleanup()
    return results


def multi_split(s, split):
    """Splits on multiple given separators."""
    for r in split:
        s = s.replace(r, "|")
    return [i for i in s.split("|") if len(i) > 0]


def is_star(val):
    return isinstance(val, six.string_types) and val == "*"


def is_pinned(val):
    if isinstance(val, Mapping):
        val = val.get("version")
    return isinstance(val, six.string_types) and val.startswith("==")


def convert_deps_to_pip(deps, project=None, r=True, include_index=True):
    """"Converts a Pipfile-formatted dependency to a pip-formatted one."""
    from ._compat import NamedTemporaryFile
    from .vendor.requirementslib.models.requirements import Requirement

    dependencies = []
    for dep_name, dep in deps.items():
        indexes = project.sources if hasattr(project, "sources") else []
        new_dep = Requirement.from_pipfile(dep_name, dep)
        if new_dep.index:
            include_index = True
        req = new_dep.as_line(sources=indexes if include_index else None).strip()
        dependencies.append(req)
    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    f = NamedTemporaryFile(suffix="-requirements.txt", delete=False)
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
            os.mkdir(newdir)


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


def strip_ssh_from_git_uri(uri):
    """Return git+ssh:// formatted URI to git+git@ format"""
    if isinstance(uri, six.string_types):
        uri = uri.replace("git+ssh://", "git+")
    return uri


def clean_git_uri(uri):
    """Cleans VCS uris from pip format"""
    if isinstance(uri, six.string_types):
        # Add scheme for parsing purposes, this is also what pip does
        if uri.startswith("git+") and "://" not in uri:
            uri = uri.replace("git+", "git+ssh://")
    return uri


def is_editable(pipfile_entry):
    if hasattr(pipfile_entry, "get"):
        return pipfile_entry.get("editable", False) and any(
            pipfile_entry.get(key) for key in ("file", "path") + VCS_LIST
        )
    return False


def is_installable_file(path):
    """Determine if a path can potentially be installed"""
    from .patched.notpip._internal.utils.misc import is_installable_dir
    from .patched.notpip._internal.utils.packaging import specifiers
    from .patched.notpip._internal.download import is_archive_file
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
    from .patched.notpip._internal.index import parse_version

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


def split_section(input_file, section_suffix, test_function):
    """
    Split a pipfile or a lockfile section out by section name and test function

        :param dict input_file: A dictionary containing either a pipfile or lockfile
        :param str section_suffix: A string of the name of the section
        :param func test_function: A test function to test against the value in the key/value pair

    >>> split_section(my_lockfile, 'vcs', is_vcs)
    {
        'default': {
            "six": {
                "hashes": [
                    "sha256:832dc0e10feb1aa2c68dcc57dbb658f1c7e65b9b61af69048abc87a2db00a0eb",
                    "sha256:70e8a77beed4562e7f14fe23a786b54f6296e34344c23bc42f07b15018ff98e9"
                ],
                "version": "==1.11.0"
            }
        },
        'default-vcs': {
            "e1839a8": {
                "editable": true,
                "path": "."
            }
        }
    }
    """
    pipfile_sections = ("packages", "dev-packages")
    lockfile_sections = ("default", "develop")
    if any(section in input_file for section in pipfile_sections):
        sections = pipfile_sections
    elif any(section in input_file for section in lockfile_sections):
        sections = lockfile_sections
    else:
        # return the original file if we can't find any pipfile or lockfile sections
        return input_file

    for section in sections:
        split_dict = {}
        entries = input_file.get(section, {})
        for k in list(entries.keys()):
            if test_function(entries.get(k)):
                split_dict[k] = entries.pop(k)
        input_file["-".join([section, section_suffix])] = split_dict
    return input_file


def split_file(file_dict):
    """Split VCS and editable dependencies out from file."""
    from .vendor.requirementslib.utils import is_vcs
    sections = {
        "vcs": is_vcs,
        "editable": lambda x: hasattr(x, "keys") and x.get("editable"),
    }
    for k, func in sections.items():
        file_dict = split_section(file_dict, k, func)
    return file_dict


def merge_deps(
    file_dict,
    project,
    dev=False,
    requirements=False,
    ignore_hashes=False,
    blocking=False,
    only=False,
):
    """
    Given a file_dict, merges dependencies and converts them to pip dependency lists.
        :param dict file_dict: The result of calling :func:`pipenv.utils.split_file`
        :param :class:`pipenv.project.Project` project: Pipenv project
        :param bool dev=False: Flag indicating whether dev dependencies are to be installed
        :param bool requirements=False: Flag indicating whether to use a requirements file
        :param bool ignore_hashes=False:
        :param bool blocking=False:
        :param bool only=False:
        :return: Pip-converted 3-tuples of [deps, requirements_deps]
    """
    deps = []
    requirements_deps = []
    for section in list(file_dict.keys()):
        # Turn develop-vcs into ['develop', 'vcs']
        section_name, suffix = (
            section.rsplit("-", 1)
            if "-" in section and not section == "dev-packages"
            else (section, None)
        )
        if not file_dict[section] or section_name not in (
            "dev-packages",
            "packages",
            "default",
            "develop",
        ):
            continue

        is_dev = section_name in ("dev-packages", "develop")
        if is_dev and not dev:
            continue

        if ignore_hashes:
            for k, v in file_dict[section]:
                if "hash" in v:
                    del v["hash"]
        # Block and ignore hashes for all suffixed sections (vcs/editable)
        no_hashes = True if suffix else ignore_hashes
        block = True if suffix else blocking
        include_index = True if not suffix else False
        converted = convert_deps_to_pip(
            file_dict[section], project, r=False, include_index=include_index
        )
        deps.extend((d, no_hashes, block) for d in converted)
        if dev and is_dev and requirements:
            requirements_deps.extend((d, no_hashes, block) for d in converted)
    return deps, requirements_deps


def recase_file(file_dict):
    """Recase file before writing to output."""
    if "packages" in file_dict or "dev-packages" in file_dict:
        sections = ("packages", "dev-packages")
    elif "default" in file_dict or "develop" in file_dict:
        sections = ("default", "develop")
    for section in sections:
        file_section = file_dict.get(section, {})
        # Try to properly case each key if we can.
        for key in list(file_section.keys()):
            try:
                cased_key = proper_case(key)
            except IOError:
                cased_key = key
            file_section[cased_key] = file_section.pop(key)
    return file_dict


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

    raise


def escape_cmd(cmd):
    if any(special_char in cmd for special_char in ["<", ">", "&", ".", "^", "|", "?"]):
        cmd = '\"{0}\"'.format(cmd)
    return cmd


@contextmanager
def atomic_open_for_write(target, binary=False, newline=None, encoding=None):
    """Atomically open `target` for writing.

    This is based on Lektor's `atomic_open()` utility, but simplified a lot
    to handle only writing, and skip many multi-process/thread edge cases
    handled by Werkzeug.

    How this works:

    * Create a temp file (in the same directory of the actual target), and
      yield for surrounding code to write to it.
    * If some thing goes wrong, try to remove the temp file. The actual target
      is not touched whatsoever.
    * If everything goes well, close the temp file, and replace the actual
      target with this new file.
    """
    from ._compat import NamedTemporaryFile

    mode = "w+b" if binary else "w"
    f = NamedTemporaryFile(
        dir=os.path.dirname(target),
        prefix=".__atomic-write",
        mode=mode,
        encoding=encoding,
        newline=newline,
        delete=False,
    )
    # set permissions to 0644
    os.chmod(f.name, stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        yield f
    except BaseException:
        f.close()
        try:
            os.remove(f.name)
        except OSError:
            pass
        raise
    else:
        f.close()
        try:
            os.remove(target)  # This is needed on Windows.
        except OSError:
            pass
        os.rename(f.name, target)  # No os.replace() on Python 2.


def safe_expandvars(value):
    """Call os.path.expandvars if value is a string, otherwise do nothing.
    """
    if isinstance(value, six.string_types):
        return os.path.expandvars(value)
    return value


def extract_uri_from_vcs_dep(dep):
    valid_keys = VCS_LIST + ("uri", "file")
    if hasattr(dep, "keys"):
        return first(dep[k] for k in valid_keys if k in dep) or None
    return None


def get_vcs_deps(
    project,
    pip_freeze=None,
    which=None,
    clear=False,
    pre=False,
    allow_global=False,
    dev=False,
    pypi_mirror=None,
):
    from ._compat import TemporaryDirectory, Path
    import atexit
    from .vendor.requirementslib.models.requirements import Requirement

    section = "vcs_dev_packages" if dev else "vcs_packages"
    reqs = []
    lockfile = {}
    try:
        packages = getattr(project, section)
    except AttributeError:
        return [], []
    if os.environ.get("PIP_SRC"):
        src_dir = Path(
            os.environ.get("PIP_SRC", os.path.join(project.virtualenv_location, "src"))
        )
        src_dir.mkdir(mode=0o775, exist_ok=True)
    else:
        src_dir = TemporaryDirectory(prefix="pipenv-lock-dir")
        atexit.register(src_dir.cleanup)
    for pkg_name, pkg_pipfile in packages.items():
        requirement = Requirement.from_pipfile(pkg_name, pkg_pipfile)
        name = requirement.normalized_name
        commit_hash = None
        if requirement.is_vcs:
            with locked_repository(requirement) as repo:
                commit_hash = repo.get_commit_hash()
                lockfile[name] = requirement.pipfile_entry[1]
                lockfile[name]['ref'] = commit_hash
        reqs.append(requirement)
    return reqs, lockfile


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
    from notpip._vendor.distlib.markers import DEFAULT_CONTEXT as marker_context
    from .vendor.packaging.markers import Marker
    from .vendor.vistir.misc import dedup

    allowed_marker_keys = ["markers"] + [k for k in marker_context.keys()]
    provided_keys = list(pipfile_entry.keys()) if hasattr(pipfile_entry, "keys") else []
    pipfile_markers = [k for k in provided_keys if k in allowed_marker_keys]
    new_pipfile = dict(pipfile_entry).copy()
    marker_set = set()
    if "markers" in new_pipfile:
        marker_set.add(str(Marker(new_pipfile.get("markers"))))
    for m in pipfile_markers:
        entry = "{0}".format(pipfile_entry[m])
        if m != "markers":
            marker_set.add(str(Marker("{0}{1}".format(m, entry))))
            new_pipfile.pop(m)
    if marker_set:
        new_pipfile["markers"] = str(Marker(" or ".join(["{0}".format(s) if " and " in s else s
                                        for s in sorted(dedup(marker_set))]))).replace('"', "'")
    return new_pipfile


def clean_resolved_dep(dep, is_top_level=False, pipfile_entry=None):
    name = pep423_name(dep["name"])
    # We use this to determine if there are any markers on top level packages
    # So we can make sure those win out during resolution if the packages reoccur
    dep_keys = (
        [k for k in getattr(pipfile_entry, "keys", list)()] if is_top_level else []
    )
    lockfile = {"version": "=={0}".format(dep["version"])}
    for key in ["hashes", "index", "extras"]:
        if key in dep:
            lockfile[key] = dep[key]
    # In case we lock a uri or a file when the user supplied a path
    # remove the uri or file keys from the entry and keep the path
    if pipfile_entry and any(k in pipfile_entry for k in ["file", "path"]):
        fs_key = next((k for k in ["path", "file"] if k in pipfile_entry), None)
        lockfile_key = next((k for k in ["uri", "file", "path"] if k in lockfile), None)
        if fs_key != lockfile_key:
            try:
                del lockfile[lockfile_key]
            except KeyError:
                # pass when there is no lock file, usually because it's the first time
                pass
            lockfile[fs_key] = pipfile_entry[fs_key]

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
    from .vendor.vistir.misc import fs_str
    src_dir = create_tracked_tempdir(prefix="pipenv-src")
    if not requirement.is_vcs:
        return
    original_base = os.environ.pop("PIP_SHIMS_BASE_MODULE", None)
    os.environ["PIP_SHIMS_BASE_MODULE"] = fs_str("pipenv.patched.notpip")
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
    parser.add_argument("--index", "-i", "--index-url", metavar="index_url",
                                                            action="store", nargs="?",)
    parser.add_argument("--extra-index-url", "--extra-index", metavar="extra_indexes",
                                                            action="append")
    parser.add_argument("--trusted-host", metavar="trusted_hosts", action="append")
    args, remainder = parser.parse_known_args(line.split())
    index = [] if not args.index else [args.index,]
    extra_indexes = [] if not args.extra_index_url else args.extra_index_url
    indexes = index + extra_indexes
    trusted_hosts = args.trusted_host if args.trusted_host else []
    return indexes, trusted_hosts, remainder
