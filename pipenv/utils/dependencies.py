import ast
import configparser
import os
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse, urlsplit, urlunsplit

from pipenv.patched.pip._internal.req.constructors import (
    install_req_from_editable,
    parse_req_from_line,
)
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.utils.urls import path_to_url, url_to_path
from pipenv.patched.pip._vendor import tomli
from pipenv.patched.pip._vendor.distlib.util import COMPARE_OP
from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.patched.pip._vendor.packaging.requirements import Requirement
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse
from pipenv.vendor.requirementslib.fileutils import (
    create_tracked_tempdir,
    get_converted_relative_path,
)
from pipenv.vendor.requirementslib.models.markers import PipenvMarkers
from pipenv.vendor.requirementslib.models.requirements import LinkInfo
from pipenv.vendor.requirementslib.models.utils import create_link, get_version
from pipenv.vendor.requirementslib.utils import (
    add_ssh_scheme_to_git_uri,
    prepare_pip_source_args,
    strip_ssh_from_git_uri,
)

from .constants import SCHEME_LIST, VCS_LIST


def python_version(path_to_python):
    from pipenv.vendor.pythonfinder.utils import get_python_version

    if not path_to_python:
        return None
    try:
        version = get_python_version(path_to_python)
    except Exception:
        return None
    return version


def clean_pkg_version(version):
    """Uses pip to prepare a package version string, from our internal version."""
    return pep440_version(str(version).replace("==", ""))


def get_lockfile_section_using_pipfile_category(category):
    if category == "dev-packages":
        lockfile_section = "develop"
    elif category == "packages":
        lockfile_section = "default"
    else:
        lockfile_section = category
    return lockfile_section


def get_pipfile_category_using_lockfile_section(category):
    if category == "develop":
        lockfile_section = "dev-packages"
    elif category == "default":
        lockfile_section = "packages"
    else:
        lockfile_section = category
    return lockfile_section


class HackedPythonVersion:
    """A hack, which allows us to tell resolver which version of Python we're using."""

    def __init__(self, python_path):
        self.python_path = python_path

    def __enter__(self):
        if self.python_path:
            os.environ["PIP_PYTHON_PATH"] = str(self.python_path)

    def __exit__(self, *args):
        pass


def get_canonical_names(packages):
    """Canonicalize a list of packages and return a set of canonical names"""
    from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

    if not isinstance(packages, Sequence):
        if not isinstance(packages, str):
            return packages
        packages = [packages]
    return {canonicalize_name(pkg) for pkg in packages if pkg}


def pep440_version(version):
    """Normalize version to PEP 440 standards"""
    return str(parse(version))


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    name = name.lower()
    if any(i not in name for i in (VCS_LIST + SCHEME_LIST)):
        return name.replace("_", "-")

    else:
        return name


def translate_markers(pipfile_entry):
    """Take a pipfile entry and normalize its markers

    Provide a pipfile entry which may have 'markers' as a key or it may have
    any valid key from `packaging.markers.marker_context.keys()` and standardize
    the format into {'markers': 'key == "some_value"'}.

    :param pipfile_entry: A dictionary of keys and values representing a pipfile entry
    :type pipfile_entry: dict
    :returns: A normalized dictionary with cleaned marker entries
    """
    if not isinstance(pipfile_entry, Mapping):
        raise TypeError("Entry is not a pipfile formatted mapping.")
    from pipenv.patched.pip._vendor.packaging.markers import default_environment

    allowed_marker_keys = ["markers"] + list(default_environment().keys())
    provided_keys = list(pipfile_entry.keys()) if hasattr(pipfile_entry, "keys") else []
    pipfile_markers = set(provided_keys) & set(allowed_marker_keys)
    new_pipfile = dict(pipfile_entry).copy()
    marker_set = set()
    if "markers" in new_pipfile:
        marker_str = new_pipfile.pop("markers")
        if marker_str:
            marker = str(Marker(marker_str))
            if "extra" not in marker:
                marker_set.add(marker)
    for m in pipfile_markers:
        entry = f"{pipfile_entry[m]}"
        if m != "markers":
            marker_set.add(str(Marker(f"{m} {entry}")))
            new_pipfile.pop(m)
    if marker_set:
        new_pipfile["markers"] = str(
            Marker(
                " or ".join(
                    f"{s}" if " and " in s else s
                    for s in sorted(dict.fromkeys(marker_set))
                )
            )
        ).replace('"', "'")
    return new_pipfile


def clean_resolved_dep(dep, dep_name=None, is_top_level=False, pipfile_entry=None):
    from pipenv.patched.pip._vendor.packaging.requirements import (
        Requirement as PipRequirement,
    )

    name = pep423_name(dep["name"])
    lockfile = {}

    version = dep.get("version", None)
    if version and not version.startswith("=="):
        version = f"=={version}"

    is_vcs_or_file = False
    for vcs_type in VCS_LIST:
        if vcs_type in dep:
            lockfile[vcs_type] = dep[vcs_type]
            lockfile["ref"] = dep.get("rev")
            is_vcs_or_file = True
    # if dep.link and dep.link.scheme in [
    #     "http",
    #     "https",
    #     "ftp",
    #     "git+http",
    #     "git+https",
    #     "git+ssh",
    #     "git+git",
    #     "hg+http",
    #     "hg+https",
    #     "hg+ssh",
    #     "svn+http",
    #     "svn+https",
    #     "svn+svn",
    #     "bzr+http",
    #     "bzr+https",
    #     "bzr+ssh",
    #     "bzr+sftp",
    #     "bzr+ftp",
    #     "bzr+lp",
    # ]:
    #     is_vcs_or_file = True

    if version and not is_vcs_or_file:
        if isinstance(version, PipRequirement):
            if version.specifier:
                lockfile["version"] = str(version.specifier)
            if version.extras:
                lockfile["extras"] = sorted(version.extras)
        elif version:
            lockfile["version"] = version

    if "editable" in dep:
        lockfile["editable"] = dep["editable"]

    preferred_file_keys = ["path", "file"]
    dependency_file_key = next(iter(k for k in preferred_file_keys if k in dep), None)
    if dependency_file_key:
        lockfile[dependency_file_key] = dep[dependency_file_key]
        if "editable" in dep:
            lockfile["editable"] = dep["editable"]
        if "extras" in dep:
            lockfile["extras"] = sorted(dep["extras"])

    if dep.get("hashes"):
        lockfile["hashes"] = dep["hashes"]

    if hasattr(dep, "index"):
        lockfile["index"] = dep.index

    # In case we lock a uri or a file when the user supplied a path
    # remove the uri or file keys from the entry and keep the path
    if pipfile_entry and isinstance(pipfile_entry, dict):
        for k in preferred_file_keys:
            if k in pipfile_entry.keys():
                lockfile[k] = pipfile_entry[k]
                break

    if "markers" in dep and dep.get("markers", "").strip():
        if not is_top_level:
            translated = translate_markers(dep).get("markers", "").strip()
            if translated:
                try:
                    lockfile["markers"] = translated
                except TypeError:
                    pass
        else:
            try:
                pipfile_entry = translate_markers(pipfile_entry)
                if pipfile_entry.get("markers"):
                    lockfile["markers"] = pipfile_entry.get("markers")
            except TypeError:
                pass

    return {name: lockfile}


def as_pipfile(dep: InstallRequirement) -> Dict[str, Any]:
    """Create a pipfile entry for the given InstallRequirement."""
    pipfile_dict = {}
    name = dep.name
    version = dep.req.specifier

    # Construct the pipfile entry
    pipfile_dict[name] = {
        "version": str(version),
        "editable": dep.editable,
        "extras": list(dep.extras),
    }

    if dep.link:
        # If it's a VCS link
        if dep.link.is_vcs:
            pipfile_dict[name]["vcs"] = dep.link.url_without_fragment
        # If it's a URL link
        elif dep.link.scheme.startswith("http"):
            pipfile_dict[name]["file"] = dep.link.url_without_fragment
        # If it's a local file
        elif dep.link.is_file:
            pipfile_dict[name]["path"] = dep.link.file_path

    # Convert any markers to their string representation
    if dep.markers:
        pipfile_dict[name]["markers"] = str(dep.markers)

    # If a hash is available, add it to the pipfile entry
    if dep.hash_options:
        pipfile_dict[name]["hashes"] = dep.hash_options

    return pipfile_dict


def is_star(val):
    return isinstance(val, str) and val == "*"


def is_pinned(val):
    if isinstance(val, Mapping):
        val = val.get("version")
    return isinstance(val, str) and val.startswith("==")


def is_pinned_requirement(ireq):
    """
    Returns whether an InstallRequirement is a "pinned" requirement.
    """
    if ireq.editable:
        return False

    if ireq.req is None or len(ireq.specifier) != 1:
        return False

    spec = next(iter(ireq.specifier))
    return spec.operator in {"==", "==="} and not spec.version.endswith(".*")


def is_editable_path(path):
    not_editable = [".whl", ".zip", ".tar", ".tar.gz", ".tgz"]
    if os.path.isfile(path):
        return False
    if os.path.isdir(path):
        return True
    if os.path.splitext(path)[1] in not_editable:
        return False
    for ext in not_editable:
        if path.endswith(ext):
            return False
    return True


def dependency_as_pip_install_line(
    dep_name, dep, include_hashes, include_markers, indexes, constraint=False
):
    if isinstance(dep, str):
        if is_star(dep):
            return dep_name
        elif not COMPARE_OP.match(dep):
            return f"{dep_name}=={dep}"
        return f"{dep_name}{dep}"
    line = []
    is_constraint = False
    vcs = next(iter([vcs for vcs in VCS_LIST if vcs in dep]), None)
    if not vcs:
        for k in ["file", "path"]:
            if k in dep:
                if is_editable_path(dep[k]):
                    line.append("-e")
                extras = ""
                if "extras" in dep:
                    extras = f"[{','.join(dep['extras'])}]"
                line.append(f"{dep[k]}{extras}")
                break
    include_index = False
    if vcs and vcs in dep:  # VCS Requirements
        extras = ""
        ref = ""
        if dep.get("ref"):
            ref = f"@{dep['ref']}"
        if "extras" in dep:
            extras = f"[{','.join(dep['extras'])}]"
        include_vcs = "" if f"{vcs}+" in dep[vcs] else f"{vcs}+"
        git_req = f"{include_vcs}{dep[vcs]}{ref}#egg={dep_name}{extras}"
        if "subdirectory" in dep:
            git_req += f"&subdirectory={dep['subdirectory']}"
        line.append(git_req)
    elif "file" in dep or "path" in dep:  # File Requirements
        pass
    else:  # Normal/Named Requirements
        is_constraint = True
        include_index = True
        line.append(dep_name)
        if "extras" in dep:
            line[-1] += f"[{','.join(dep['extras'])}]"
        if "version" in dep:
            version = dep["version"]
            if version and not is_star(version):
                if not COMPARE_OP.match(version):
                    version = f"=={version}"
                line[-1] += version

    if include_markers and dep.get("markers"):
        line.append(f'; {dep["markers"]}')

    if include_hashes and dep.get("hashes"):
        line.extend([f" --hash={hash}" for hash in dep["hashes"]])

    if include_index:
        if dep.get("index"):
            indexes = [s for s in indexes if s.get("name") == dep["index"]]
        else:
            indexes = [indexes[0]] if indexes else []
        index_list = prepare_pip_source_args(indexes)
        line.extend(index_list)

    if constraint and not is_constraint:
        pip_line = ""
    else:
        pip_line = " ".join(line)
    return pip_line


def convert_deps_to_pip(
    deps,
    project=None,
    include_index=True,
    include_hashes=True,
    include_markers=True,
    constraints_only=False,
):
    """ "Converts a Pipfile-formatted dependency to a pip-formatted one."""
    dependencies = []
    for dep_name, dep in deps.items():
        if project:
            project.clear_pipfile_cache()
        indexes = []
        if project:
            indexes = project.pipfile_sources()
        req = dependency_as_pip_install_line(
            dep_name, dep, include_hashes, include_markers, indexes
        )
        dependencies.append(req)
    return dependencies


def parse_metadata_file(content: str):
    """
    Parse a METADATA file to get the package name.

    Parameters:
    content (str): Contents of the METADATA file.

    Returns:
    str: Name of the package or None if not found.
    """

    for line in content.splitlines():
        if line.startswith("Name:"):
            return line.split("Name: ")[1].strip()

    return None


def parse_setup_file(content):
    module = ast.parse(content)
    for node in module.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if getattr(node.value.func, "id", None) == "setup":
                for keyword in node.value.keywords:
                    if keyword.arg == "name":
                        return keyword.value.s

    return None


def parse_cfg_file(filepath):
    config = configparser.ConfigParser()
    config.read(filepath)
    try:
        return config["metadata"]["name"]
    except configparser.NoSectionError:
        return None
    except KeyError:
        return None


def parse_toml_file(content):
    toml_dict = tomli.loads(content)
    if "tool" in toml_dict and "poetry" in toml_dict["tool"]:
        return toml_dict["tool"]["poetry"]["name"]

    return None


def find_package_name_from_tarball(tarball_filepath):
    with tarfile.open(tarball_filepath, "r") as tar_ref:
        for filename in tar_ref.getnames():
            if filename.endswith(("METADATA", "setup.py", "setup.cfg", "pyproject.toml")):
                with tar_ref.extractfile(filename) as file:
                    possible_name = find_package_name_from_filename(file.name, file)
                    if possible_name:
                        return possible_name


def find_package_name_from_zipfile(zip_filepath):
    with zipfile.ZipFile(zip_filepath, "r") as zip_ref:
        for filename in zip_ref.namelist():
            if filename.endswith(("METADATA", "setup.py", "setup.cfg", "pyproject.toml")):
                with zip_ref.open(filename) as file:
                    possible_name = find_package_name_from_filename(file.name, file)
                    if possible_name:
                        return possible_name


def find_package_name_from_directory(directory):
    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            if filename.endswith(("METADATA", "setup.py", "setup.cfg", "pyproject.toml")):
                with open(filepath, "rb") as file:
                    possible_name = find_package_name_from_filename(filename, file)
                    if possible_name:
                        return possible_name
        elif os.path.isdir(filepath):
            possible_name = find_package_name_from_directory(filepath)
            if possible_name:
                return possible_name

    return None


def find_package_name_from_filename(filename, file):
    if filename.endswith("METADATA"):
        content = file.read().decode()
        possible_name = parse_metadata_file(content)
        if possible_name:
            return possible_name

    if filename.endswith("setup.py"):
        content = file.read().decode()
        possible_name = parse_setup_file(content)
        if possible_name:
            return possible_name

    if filename.endswith("setup.cfg"):
        possible_name = parse_cfg_file(file)
        if possible_name:
            return possible_name

    if filename.endswith("pyproject.toml"):
        content = file.read().decode()
        possible_name = parse_toml_file(content)
        if possible_name:
            return possible_name
    return None


def get_link_from_line(line):
    """Parse link information from given requirement line. Return a
    6-tuple:

    - `vcs_type` indicates the VCS to use (e.g. "git"), or None.
    - `prefer` is either "file", "path" or "uri", indicating how the
        information should be used in later stages.
    - `relpath` is the relative path to use when recording the dependency,
        instead of the absolute path/URI used to perform installation.
        This can be None (to prefer the absolute path or URI).
    - `path` is the absolute file path to the package. This will always use
        forward slashes. Can be None if the line is a remote URI.
    - `uri` is the absolute URI to the package. Can be None if the line is
        not a URI.
    - `link` is an instance of :class:`pipenv.patched.pip._internal.index.Link`,
        representing a URI parse result based on the value of `uri`.
    This function is provided to deal with edge cases concerning URIs
    without a valid netloc. Those URIs are problematic to a straight
    ``urlsplit` call because they cannot be reliably reconstructed with
    ``urlunsplit`` due to a bug in the standard library:
    >>> from urllib.parse import urlsplit, urlunsplit
    >>> urlunsplit(urlsplit('git+file:///this/breaks'))
    'git+file:/this/breaks'
    >>> urlunsplit(urlsplit('file:///this/works'))
    'file:///this/works'
    See `https://bugs.python.org/issue23505#msg277350`.
    """

    # Git allows `git@github.com...` lines that are not really URIs.
    # Add "ssh://" so we can parse correctly, and restore afterward.
    fixed_line = add_ssh_scheme_to_git_uri(line)  # type: str
    added_ssh_scheme = fixed_line != line  # type: bool

    # We can assume a lot of things if this is a local filesystem path.
    if "://" not in fixed_line:
        p = Path(fixed_line).absolute()  # type: Path
        path = p.as_posix()  # type: Optional[str]
        uri = p.as_uri()  # type: str
        link = create_link(uri)  # type: Link
        relpath = None  # type: Optional[str]
        try:
            relpath = get_converted_relative_path(path)
        except ValueError:
            relpath = None
        return LinkInfo(None, "path", relpath, path, uri, link)

    # This is an URI. We'll need to perform some elaborated parsing.
    parsed_url = urlsplit(fixed_line)  # type: SplitResult
    original_url = parsed_url._replace()  # type: SplitResult

    # Split the VCS part out if needed.
    original_scheme = parsed_url.scheme  # type: str
    vcs_type = None  # type: Optional[str]
    if "+" in original_scheme:
        scheme = None  # type: Optional[str]
        vcs_type, _, scheme = original_scheme.partition("+")
        parsed_url = parsed_url._replace(scheme=scheme)  # type: ignore
    else:
        pass

    if parsed_url.scheme == "file" and parsed_url.path:
        # This is a "file://" URI. Use url_to_path and path_to_url to
        # ensure the path is absolute. Also we need to build relpath.
        path = Path(url_to_path(urlunsplit(parsed_url))).as_posix()
        try:
            relpath = get_converted_relative_path(path)
        except ValueError:
            relpath = None
        uri = path_to_url(path)
    else:
        # This is a remote URI. Simply use it.
        path = None
        relpath = None
        # Cut the fragment, but otherwise this is fixed_line.
        uri = urlunsplit(
            parsed_url._replace(scheme=original_scheme, fragment="")  # type: ignore
        )

    if added_ssh_scheme:
        original_uri = urlunsplit(
            original_url._replace(scheme=original_scheme, fragment="")  # type: ignore
        )
        uri = strip_ssh_from_git_uri(original_uri)

    # Re-attach VCS prefix to build a Link.
    link = create_link(
        urlunsplit(parsed_url._replace(scheme=original_scheme))  # type: ignore
    )

    return link


def expansive_install_req_from_line(
    name: str,
    comes_from: Optional[Union[str, InstallRequirement]] = None,
    *,
    use_pep517: Optional[bool] = None,
    isolated: bool = False,
    global_options: Optional[List[str]] = None,
    hash_options: Optional[Dict[str, List[str]]] = None,
    constraint: bool = False,
    line_source: Optional[str] = None,
    user_supplied: bool = False,
    config_settings: Optional[Dict[str, Union[str, List[str]]]] = None,
) -> InstallRequirement:
    """Creates an InstallRequirement from a name, which might be a
    requirement, directory containing 'setup.py', filename, or URL.

    :param line_source: An optional string describing where the line is from,
        for logging purposes in case of an error.
    """
    editable = ""
    if name.startswith("-e "):
        # Editable requirement
        name = name.split("-e ")[1]
        editable = "-e "

    if os.path.isfile(name) or os.path.isdir(name):
        if not name.startswith("file:") and not editable:
            name = f"{editable}file:" + name
        else:
            name = editable + name

        return install_req_from_editable(name, line_source)

    for vcs in VCS_LIST:
        if name.startswith(f"{vcs}+"):
            link = get_link_from_line(name)
            return InstallRequirement(
                None,
                comes_from,
                link=link,
                use_pep517=use_pep517,
                isolated=isolated,
                global_options=global_options,
                hash_options=hash_options,
                constraint=constraint,
                user_supplied=user_supplied,
            )
    if urlparse(name).scheme in ("http", "https", "file"):
        parts = parse_req_from_line(name, line_source)
    else:
        # It's a requirement
        parts = parse_req_from_line(name, line_source)

    return InstallRequirement(
        parts.requirement,
        comes_from,
        link=parts.link,
        markers=parts.markers,
        use_pep517=use_pep517,
        isolated=isolated,
        global_options=global_options,
        hash_options=hash_options,
        config_settings=config_settings,
        constraint=constraint,
        extras=parts.extras,
        user_supplied=user_supplied,
    )


def from_pipfile(name, pipfile):
    _pipfile = {}
    if hasattr(pipfile, "keys"):
        _pipfile = dict(pipfile).copy()

    extras = _pipfile.get("extras", [])
    extras_str = ""
    if extras:
        extras_str = f"[{','.join(extras)}]"
    vcs = next(iter([vcs for vcs in VCS_LIST if vcs in _pipfile]), None)

    if vcs:
        _pipfile["vcs"] = vcs
        req_str = f"{name}{extras_str} @ {_pipfile[vcs]}"
    elif "path" in _pipfile:
        req_str = f"-e {_pipfile['path']}{extras_str}"
    elif "file" in _pipfile:
        req_str = f"-e {_pipfile['file']}{extras_str}"
    elif "uri" in _pipfile:
        req_str = f"{name}{extras_str} @ {_pipfile['uri']}"
    else:
        # We ensure version contains an operator. Default to equals (==)
        _pipfile["version"] = version = get_version(pipfile)
        if version and not is_star(version) and COMPARE_OP.match(version) is None:
            _pipfile["version"] = f"=={version}"
        if is_star(version) or version == "==*":
            version = ""
        req_str = f"{name}{extras_str}{version}"

    install_req = expansive_install_req_from_line(
        req_str,
        comes_from=None,
        use_pep517=False,
        isolated=False,
        hash_options={"hashes": _pipfile.get("hashes", [])},
        constraint=False,
    )

    markers = PipenvMarkers.from_pipfile(name, _pipfile)
    if markers:
        markers = str(markers)
        install_req.markers = Marker(markers)

    # Construct the requirement string for your Requirement class
    extras_str = ""
    if install_req.req and install_req.req.extras:
        extras_str = f"[{','.join(install_req.req.extras)}]"
    req_str = f"{install_req.name}{extras_str}{install_req.req.specifier}"
    if install_req.markers:
        req_str += f"; {install_req.markers}"

    # Create the Requirement instance
    cls_inst = Requirement(req_str)

    return cls_inst


def get_constraints_from_deps(deps):
    """Get constraints from dictionary-formatted dependency"""
    constraints = set()
    for dep_name, dep_version in deps.items():
        c = None
        # Creating a constraint as a canonical name plus a version specifier
        if isinstance(dep_version, str):
            if dep_version and not is_star(dep_version):
                if COMPARE_OP.match(dep_version) is None:
                    dep_version = f"=={dep_version}"
                c = f"{canonicalize_name(dep_name)}{dep_version}"
            else:
                c = canonicalize_name(dep_name)
        else:
            if not any([k in dep_version for k in ["path", "file", "uri"]]):
                version = dep_version.get("version", None)
                if version and not is_star(version):
                    if COMPARE_OP.match(version) is None:
                        version = f"=={dep_version}"
                    c = f"{canonicalize_name(dep_name)}{version}"
                else:
                    c = canonicalize_name(dep_name)
        if c:
            constraints.add(c)
    return constraints


def prepare_constraint_file(
    constraints,
    directory=None,
    sources=None,
    pip_args=None,
):
    if not directory:
        directory = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")

    constraints = set(constraints)
    constraints_file = NamedTemporaryFile(
        mode="w",
        prefix="pipenv-",
        suffix="-constraints.txt",
        dir=directory,
        delete=False,
    )

    if sources and pip_args:
        skip_args = ("build-isolation", "use-pep517", "cache-dir")
        args_to_add = [
            arg for arg in pip_args if not any(bad_arg in arg for bad_arg in skip_args)
        ]
        requirementstxt_sources = " ".join(args_to_add) if args_to_add else ""
        requirementstxt_sources = requirementstxt_sources.replace(" --", "\n--")
        constraints_file.write(f"{requirementstxt_sources}\n")

    constraints_file.write("\n".join([c for c in constraints]))
    constraints_file.close()
    return constraints_file.name


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
        return pipfile_entry.get("editable", False) or any(
            pipfile_entry.get(key) for key in ("file", "path") + VCS_LIST
        )
    return False


@contextmanager
def locked_repository(requirement):
    if not requirement.is_vcs:
        return
    src_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-src")
    with requirement.req.locked_vcs_repo(src_dir=src_dir) as repo:
        yield repo
