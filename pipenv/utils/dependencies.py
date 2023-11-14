import ast
import configparser
import os
import re
import sys
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, AnyStr, Dict, List, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse, urlsplit, urlunsplit

from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.network.download import Downloader
from pipenv.patched.pip._internal.req.constructors import (
    install_req_from_editable,
    parse_req_from_line,
)
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.utils.misc import hide_url
from pipenv.patched.pip._internal.vcs.versioncontrol import VcsSupport
from pipenv.patched.pip._vendor import tomli
from pipenv.patched.pip._vendor.distlib.util import COMPARE_OP
from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.patched.pip._vendor.packaging.requirements import Requirement
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse
from pipenv.utils import err
from pipenv.utils.fileutils import (
    create_tracked_tempdir,
)
from pipenv.utils.requirementslib import (
    add_ssh_scheme_to_git_uri,
    get_pip_command,
    prepare_pip_source_args,
    unpack_url,
)

from .constants import (
    INSTALLABLE_EXTENSIONS,
    RELEVANT_PROJECT_FILES,
    REMOTE_SCHEMES,
    SCHEME_LIST,
    VCS_LIST,
    VCS_SCHEMES,
)
from .markers import PipenvMarkers


def get_version(pipfile_entry):
    if str(pipfile_entry) == "{}" or is_star(pipfile_entry):
        return ""

    if hasattr(pipfile_entry, "keys") and "version" in pipfile_entry:
        if is_star(pipfile_entry.get("version")):
            return ""
        version = pipfile_entry.get("version")
        if version is None:
            version = ""
        return version.strip().lstrip("(").rstrip(")")

    if isinstance(pipfile_entry, str):
        return pipfile_entry.strip().lstrip("(").rstrip(")")
    return ""


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
    from pipenv.patched.pip._vendor.packaging.markers import default_environment

    allowed_marker_keys = ["markers"] + list(default_environment().keys())
    provided_keys = list(pipfile_entry.keys()) if hasattr(pipfile_entry, "keys") else []
    pipfile_markers = set(provided_keys) & set(allowed_marker_keys)
    new_pipfile = dict(pipfile_entry).copy()
    marker_set = set()
    os_name_marker = None
    if "markers" in new_pipfile:
        marker_str = new_pipfile.pop("markers")
        if marker_str:
            marker = str(Marker(marker_str))
            if "extra" not in marker:
                marker_set.add(marker)
    for m in pipfile_markers:
        entry = f"{pipfile_entry[m]}"
        if m != "markers":
            if m != "os_name":
                marker_set.add(str(Marker(f"{m} {entry}")))
            new_pipfile.pop(m)
    if marker_set:
        markers_str = " and ".join(
            f"{s}" if " and " in s else s for s in sorted(dict.fromkeys(marker_set))
        )
        if os_name_marker:
            markers_str = f"({markers_str}) and {os_name_marker}"
        new_pipfile["markers"] = str(Marker(markers_str)).replace('"', "'")
    return new_pipfile


def unearth_hashes_for_dep(project, dep):
    hashes = []

    index_url = "https://pypi.org/simple/"
    source = "pypi"
    for source in project.sources:
        if source.get("name") == dep.get("index"):
            index_url = source.get("url")
            break

    # 1 Try to get hashes directly form index
    install_req, markers, _ = install_req_from_pipfile(dep["name"], dep)
    if not install_req or not install_req.req:
        return []
    if "https://pypi.org/simple/" in index_url:
        hashes = project.get_hashes_from_pypi(install_req, source)
    elif index_url:
        hashes = project.get_hashes_from_remote_index_urls(install_req, source)
    if hashes:
        return hashes

    return []


def clean_resolved_dep(project, dep, is_top_level=False, current_entry=None):
    from pipenv.patched.pip._vendor.packaging.requirements import (
        Requirement as PipRequirement,
    )

    name = dep["name"]
    lockfile = {}

    # Evaluate Markers
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
                pipfile_entry = translate_markers(dep)
                if pipfile_entry.get("markers"):
                    lockfile["markers"] = pipfile_entry.get("markers")
            except TypeError:
                pass

    version = dep.get("version", None)
    if version and not version.startswith("=="):
        version = f"=={version}"
    if version == "==*":
        if current_entry:
            version = current_entry.get("version")
            dep["version"] = version
        else:
            version = None

    is_vcs_or_file = False
    for vcs_type in VCS_LIST:
        if vcs_type in dep:
            if "[" in dep[vcs_type] and "]" in dep[vcs_type]:
                extras_section = dep[vcs_type].split("[").pop().replace("]", "")
                lockfile["extras"] = sorted(
                    [extra.strip() for extra in extras_section.split(",")]
                )
            if has_name_with_extras(dep[vcs_type]):
                lockfile[vcs_type] = dep[vcs_type].split("@ ", 1)[1]
            else:
                lockfile[vcs_type] = dep[vcs_type]
            lockfile["ref"] = dep.get("ref")
            if "subdirectory" in dep:
                lockfile["subdirectory"] = dep["subdirectory"]
            is_vcs_or_file = True

    if "editable" in dep:
        lockfile["editable"] = dep["editable"]

    preferred_file_keys = ["path", "file"]
    dependency_file_key = next(iter(k for k in preferred_file_keys if k in dep), None)
    if dependency_file_key:
        lockfile[dependency_file_key] = dep[dependency_file_key]
        is_vcs_or_file = True
        if "editable" in dep:
            lockfile["editable"] = dep["editable"]

    if version and not is_vcs_or_file:
        if isinstance(version, PipRequirement):
            if version.specifier:
                lockfile["version"] = str(version.specifier)
            if version.extras:
                lockfile["extras"] = sorted(version.extras)
        elif version:
            lockfile["version"] = version

    if dep.get("hashes"):
        lockfile["hashes"] = dep["hashes"]
    elif is_top_level:
        potential_hashes = unearth_hashes_for_dep(project, dep)
        if potential_hashes:
            lockfile["hashes"] = potential_hashes

    if dep.get("index"):
        lockfile["index"] = dep["index"]

    if dep.get("extras"):
        lockfile["extras"] = sorted(dep["extras"])

    # In case we lock a uri or a file when the user supplied a path
    # remove the uri or file keys from the entry and keep the path
    if dep and isinstance(dep, dict):
        for k in preferred_file_keys:
            if k in dep.keys():
                lockfile[k] = dep[k]
                break

    if "markers" in dep:
        markers = dep["markers"]
        if markers:
            markers = Marker(markers)
            if not markers.evaluate() and current_entry:
                current_entry.update(lockfile)
                return {name: current_entry}

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
            vcs = dep.link.scheme.split("+")[0]
            pipfile_dict[name][vcs] = dep.link.url_without_fragment
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
    if os.path.isdir(path):
        return True
    return False


def dependency_as_pip_install_line(
    dep_name: str,
    dep: Union[str, Mapping],
    include_hashes: bool,
    include_markers: bool,
    include_index: bool,
    indexes: list,
    constraint: bool = False,
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
                location = dep["file"] if "file" in dep else dep["path"]
                if location.startswith(("http:", "https:")):
                    line.append(f"{dep_name}{extras} @ {location}")
                else:
                    line.append(f"{location}{extras}")
                break
        else:
            # Normal/Named Requirements
            is_constraint = True
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
                line[-1] = f'{line[-1]}; {dep["markers"]}'

            if include_hashes and dep.get("hashes"):
                line.extend([f" --hash={hash}" for hash in dep["hashes"]])

            if include_index:
                if dep.get("index"):
                    indexes = [s for s in indexes if s.get("name") == dep["index"]]
                else:
                    indexes = [indexes[0]] if indexes else []
            index_list = prepare_pip_source_args(indexes)
            line.extend(index_list)
    elif vcs and vcs in dep:  # VCS Requirements
        extras = ""
        ref = ""
        if dep.get("ref"):
            ref = f"@{dep['ref']}"
        if "extras" in dep:
            extras = f"[{','.join(dep['extras'])}]"
        include_vcs = "" if f"{vcs}+" in dep[vcs] else f"{vcs}+"
        vcs_url = dep[vcs]
        # legacy format is the only format supported for editable installs https://github.com/pypa/pip/issues/9106
        if is_editable_path(dep[vcs]) or "file://" in dep[vcs]:
            if "#egg=" not in dep[vcs]:
                git_req = f"-e {include_vcs}{dep[vcs]}{ref}#egg={dep_name}{extras}"
            else:
                git_req = f"-e {include_vcs}{dep[vcs]}{ref}"
            if "subdirectory" in dep:
                git_req += f"&subdirectory={dep['subdirectory']}"
        else:
            if "#egg=" in vcs_url:
                vcs_url = vcs_url.split("#egg=")[0]
            git_req = f"{dep_name}{extras}@ {include_vcs}{vcs_url}{ref}"
            if "subdirectory" in dep:
                git_req += f"#subdirectory={dep['subdirectory']}"

        line.append(git_req)

    if constraint and not is_constraint:
        pip_line = ""
    else:
        pip_line = " ".join(line)
    return pip_line


def convert_deps_to_pip(
    deps,
    indexes=None,
    include_hashes=True,
    include_markers=True,
    include_index=False,
):
    """ "Converts a Pipfile-formatted dependency to a pip-formatted one."""
    dependencies = {}
    if indexes is None:
        indexes = []
    for dep_name, dep in deps.items():
        req = dependency_as_pip_install_line(
            dep_name, dep, include_hashes, include_markers, include_index, indexes
        )
        dependencies[dep_name] = req
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


def parse_pkginfo_file(content: str):
    """
    Parse a PKG-INFO file to get the package name.

    Parameters:
    content (str): Contents of the PKG-INFO file.

    Returns:
    str: Name of the package or None if not found.
    """
    for line in content.splitlines():
        if line.startswith("Name:"):
            return line.split("Name: ")[1].strip()

    return None


def parse_setup_file(content):
    # A dictionary to store variable names and their values
    variables = {}
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            # Extract variable assignments and store them
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if isinstance(node.value, ast.Str):  # for Python versions < 3.8
                            variables[target.id] = node.value.s
                        elif isinstance(node.value, ast.Constant) and isinstance(
                            node.value.value, str
                        ):
                            variables[target.id] = node.value.value

            # Check function calls to extract the 'name' attribute from the setup function
            if isinstance(node, ast.Call):
                if (
                    getattr(node.func, "id", "") == "setup"
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setup"
                ):
                    for keyword in node.keywords:
                        if keyword.arg == "name":
                            # If it's a variable, retrieve its value
                            if (
                                isinstance(keyword.value, ast.Name)
                                and keyword.value.id in variables
                            ):
                                return variables[keyword.value.id]
                            # Otherwise, check if it's directly provided
                            elif isinstance(keyword.value, ast.Str):
                                return keyword.value.s
                            elif isinstance(keyword.value, ast.Constant) and isinstance(
                                keyword.value.value, str
                            ):
                                return keyword.value.value
                            # Additional handling for Python versions and specific ways of defining the name
                            elif sys.version_info < (3, 9) and isinstance(
                                keyword.value, ast.Subscript
                            ):
                                if (
                                    isinstance(keyword.value.value, ast.Name)
                                    and keyword.value.value.id == "about"
                                ):
                                    if isinstance(
                                        keyword.value.slice, ast.Index
                                    ) and isinstance(keyword.value.slice.value, ast.Str):
                                        return keyword.value.slice.value.s
                                return keyword.value.s
                            elif sys.version_info >= (3, 9) and isinstance(
                                keyword.value, ast.Subscript
                            ):
                                if (
                                    isinstance(keyword.value.value, ast.Name)
                                    and isinstance(keyword.value.slice, ast.Str)
                                    and keyword.value.value.id == "about"
                                ):
                                    return keyword.value.slice.s
    except ValueError:
        pass  # We will not exec unsafe code to determine the name pre-resolver

    return None


def parse_cfg_file(content):
    config = configparser.ConfigParser()
    config.read_string(content)
    try:
        return config["metadata"]["name"]
    except configparser.NoSectionError:
        return None
    except KeyError:
        return None


def parse_toml_file(content):
    toml_dict = tomli.loads(content)
    if "project" in toml_dict and "name" in toml_dict["project"]:
        return toml_dict["project"]["name"]
    if "tool" in toml_dict and "poetry" in toml_dict["tool"]:
        return toml_dict["tool"]["poetry"]["name"]

    return None


def find_package_name_from_tarball(tarball_filepath):
    if tarball_filepath.startswith("file://") and os.name != "nt":
        tarball_filepath = tarball_filepath[7:]
    with tarfile.open(tarball_filepath, "r") as tar_ref:
        for filename in tar_ref.getnames():
            if filename.endswith(RELEVANT_PROJECT_FILES):
                with tar_ref.extractfile(filename) as file:
                    possible_name = find_package_name_from_filename(filename, file)
                    if possible_name:
                        return possible_name


def find_package_name_from_zipfile(zip_filepath):
    if zip_filepath.startswith("file://") and os.name != "nt":
        zip_filepath = zip_filepath[7:]
    with zipfile.ZipFile(zip_filepath, "r") as zip_ref:
        for filename in zip_ref.namelist():
            if filename.endswith(RELEVANT_PROJECT_FILES):
                with zip_ref.open(filename) as file:
                    possible_name = find_package_name_from_filename(file.name, file)
                    if possible_name:
                        return possible_name


def find_package_name_from_directory(directory):
    parsed_url = urlparse(directory)
    directory = (
        os.path.normpath(parsed_url.path)
        if parsed_url.scheme
        else os.path.normpath(directory)
    )
    if "#egg=" in directory:  # parse includes the fragment in py3.7 and py3.8
        expected_name = directory.split("#egg=")[1]
        return expected_name
    if os.name == "nt":
        if directory.startswith("\\") and (":\\" in directory or ":/" in directory):
            directory = directory[1:]
        if directory.startswith("\\\\"):
            directory = directory[1:]
    directory_contents = sorted(
        os.listdir(directory),
        key=lambda x: (os.path.isdir(os.path.join(directory, x)), x),
    )
    for filename in directory_contents:
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            if filename.endswith(RELEVANT_PROJECT_FILES):
                with open(filepath, "rb") as file:
                    possible_name = find_package_name_from_filename(filename, file)
                    if possible_name:
                        return possible_name
        elif os.path.isdir(filepath):
            possible_name = find_package_name_from_directory(filepath)
            if possible_name:
                return possible_name

    return None


def ensure_path_is_relative(file_path):
    abs_path = Path(file_path).resolve()
    current_dir = Path.cwd()

    # Check if the paths are on different drives
    if abs_path.drive != current_dir.drive:
        # If on different drives, return the absolute path
        return abs_path

    try:
        # Try to create a relative path
        return abs_path.relative_to(current_dir)
    except ValueError:
        # If the direct relative_to fails, manually compute the relative path
        common_parts = 0
        for part_a, part_b in zip(abs_path.parts, current_dir.parts):
            if part_a == part_b:
                common_parts += 1
            else:
                break

        # Number of ".." needed are the extra parts in the current directory
        # beyond the common parts
        up_levels = [".."] * (len(current_dir.parts) - common_parts)
        # The relative path is constructed by going up as needed and then
        # appending the non-common parts of the absolute path
        rel_parts = up_levels + list(abs_path.parts[common_parts:])
        relative_path = Path(*rel_parts)
        return str(relative_path)


def determine_path_specifier(package: InstallRequirement):
    if package.link:
        if package.link.scheme in ["http", "https"]:
            return package.link.url_without_fragment
        if package.link.scheme == "file":
            return ensure_path_is_relative(package.link.file_path)


def determine_vcs_specifier(package: InstallRequirement):
    if package.link and package.link.scheme in VCS_SCHEMES:
        vcs_specifier = package.link.url_without_fragment
        return vcs_specifier


def get_vcs_backend(vcs_type):
    backend = VcsSupport().get_backend(vcs_type)
    return backend


def generate_temp_dir_path():
    # Create a temporary directory using mkdtemp
    temp_dir = tempfile.mkdtemp()
    # Remove the created directory
    os.rmdir(temp_dir)
    return temp_dir


def determine_vcs_revision_hash(
    package: InstallRequirement, vcs_type: str, revision: str
):
    try:  # Windows python 3.7 will sometimes raise PermissionError cleaning up
        checkout_directory = generate_temp_dir_path()
        repo_backend = get_vcs_backend(vcs_type)
        repo_backend.obtain(checkout_directory, hide_url(package.link.url), verbosity=1)
        return repo_backend.get_revision(checkout_directory)
    except Exception as e:
        err.print(
            f"Error {e} obtaining {vcs_type} revision hash for {package}; falling back to {revision}."
        )
        return revision


@lru_cache(maxsize=None)
def determine_package_name(package: InstallRequirement):
    req_name = None
    if package.name:
        req_name = package.name
    elif "#egg=" in str(package):
        req_name = str(package).split("#egg=")[1]
        req_name = req_name.split("[")[0]
    elif "@ " in str(package):
        req_name = str(package).split("@ ")[0]
        req_name = req_name.split("[")[0]
    elif package.link and package.link.scheme in REMOTE_SCHEMES:
        try:  # Windows python 3.7 will sometimes raise PermissionError cleaning up
            with TemporaryDirectory() as td:
                cmd = get_pip_command()
                options, _ = cmd.parser.parse_args([])
                session = cmd._build_session(options)
                local_file = unpack_url(
                    link=package.link,
                    location=td,
                    download=Downloader(session, "off"),
                    verbosity=1,
                )
                if local_file.path.endswith(".whl") or local_file.path.endswith(".zip"):
                    req_name = find_package_name_from_zipfile(local_file.path)
                elif local_file.path.endswith(".tar.gz") or local_file.path.endswith(
                    ".tar.bz2"
                ):
                    req_name = find_package_name_from_tarball(local_file.path)
                else:
                    req_name = find_package_name_from_directory(local_file.path)
        except PermissionError:
            pass
    elif package.link and package.link.scheme in [
        "bzr+file",
        "git+file",
        "hg+file",
        "svn+file",
    ]:
        parsed_url = urlparse(package.link.url)
        repository_path = parsed_url.path
        repository_path = repository_path.rsplit("@", 1)[
            0
        ]  # extract the actual directory path
        repository_path = repository_path.split("#egg=")[0]
        req_name = find_package_name_from_directory(repository_path)
    elif package.link and package.link.scheme == "file":
        if package.link.file_path.endswith(".whl") or package.link.file_path.endswith(
            ".zip"
        ):
            req_name = find_package_name_from_zipfile(package.link.file_path)
        elif package.link.file_path.endswith(
            ".tar.gz"
        ) or package.link.file_path.endswith(".tar.bz2"):
            req_name = find_package_name_from_tarball(package.link.file_path)
        else:
            req_name = find_package_name_from_directory(package.link.file_path)
    if req_name:
        return req_name
    else:
        raise ValueError(f"Could not determine package name from {package}")


def find_package_name_from_filename(filename, file):
    if filename.endswith("METADATA"):
        content = file.read().decode()
        possible_name = parse_metadata_file(content)
        if possible_name:
            return possible_name

    if filename.endswith("PKG-INFO"):
        content = file.read().decode()
        possible_name = parse_pkginfo_file(content)
        if possible_name:
            return possible_name

    if filename.endswith("setup.py"):
        content = file.read().decode()
        possible_name = parse_setup_file(content)
        if possible_name:
            return possible_name

    if filename.endswith("setup.cfg"):
        content = file.read().decode()
        possible_name = parse_cfg_file(content)
        if possible_name:
            return possible_name

    if filename.endswith("pyproject.toml"):
        content = file.read().decode()
        possible_name = parse_toml_file(content)
        if possible_name:
            return possible_name
    return None


def create_link(link):
    # type: (AnyStr) -> Link

    if not isinstance(link, str):
        raise TypeError("must provide a string to instantiate a new link")

    return Link(link)


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

    # We can assume a lot of things if this is a local filesystem path.
    if "://" not in fixed_line:
        p = Path(fixed_line).absolute()  # type: Path
        p.as_posix()  # type: Optional[str]
        uri = p.as_uri()  # type: str
        link = create_link(uri)  # type: Link
        return link

    # This is an URI. We'll need to perform some elaborated parsing.
    parsed_url = urlsplit(fixed_line)  # type: SplitResult

    # Split the VCS part out if needed.
    original_scheme = parsed_url.scheme  # type: str
    if "+" in original_scheme:
        vcs_type, _, scheme = original_scheme.partition("+")
        parsed_url = parsed_url._replace(scheme=scheme)  # type: ignore
    else:
        pass

    # Re-attach VCS prefix to build a Link.
    link = create_link(
        urlunsplit(parsed_url._replace(scheme=original_scheme))  # type: ignore
    )

    return link


def has_name_with_extras(requirement):
    pattern = r"^([a-zA-Z0-9_-]+(\[[a-zA-Z0-9_-]+\])?) @ .*"
    match = re.match(pattern, requirement)
    return match is not None


def expand_env_variables(line) -> AnyStr:
    """Expand the env vars in a line following pip's standard.
    https://pip.pypa.io/en/stable/reference/pip_install/#id10.

    Matches environment variable-style values in '${MY_VARIABLE_1}' with
    the variable name consisting of only uppercase letters, digits or
    the '_'
    """

    def replace_with_env(match):
        value = os.getenv(match.group(1))
        return value if value else match.group()

    return re.sub(r"\$\{([A-Z0-9_]+)\}", replace_with_env, line)


def expansive_install_req_from_line(
    pip_line: str,
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
    expand_env: bool = False,
) -> (InstallRequirement, str):
    """Create an InstallRequirement from a pip-style requirement line.
    InstallRequirement is a pip internal construct that represents an installable requirement,
    and is used as an intermediary between the pip command and the resolver.
    :param pip_line: A pip-style requirement line.
    :param comes_from: The path to the requirements file the line was found in.
    :param use_pep517: Whether to use PEP 517/518 when installing the
        requirement.
    :param isolated: Whether to isolate the requirements when installing them. (likely unused)
    :param global_options: Extra global options to be used when installing the install req (likely unused)
    :param hash_options: Extra hash options to be used when installing the install req (likely unused)
    :param constraint: Whether the requirement is a constraint.
    :param line_source: The source of the line (e.g. "requirements.txt").
    :param user_supplied: Whether the requirement was directly provided by the user.
    :param config_settings: Configuration settings to be used when installing the install req (likely unused)
    :param expand_env: Whether to expand environment variables in the line. (definitely used)
    :return: A tuple of the InstallRequirement and the name of the package (if determined).
    """
    name = None
    pip_line = pip_line.strip("'").lstrip(" ")
    for new_req_symbol in ("@ ", " @ "):  # Check for new style pip lines
        if new_req_symbol in pip_line:
            pip_line_parts = pip_line.split(new_req_symbol, 1)
            name = pip_line_parts[0]
            pip_line = pip_line_parts[1]
    if pip_line.startswith("-e "):  # Editable requirements
        pip_line = pip_line.split("-e ")[1]
        return install_req_from_editable(pip_line, line_source), name

    if expand_env:
        pip_line = expand_env_variables(pip_line)

    vcs_part = pip_line
    for vcs in VCS_LIST:
        if vcs_part.startswith(f"{vcs}+"):
            link = get_link_from_line(vcs_part)
            install_req = InstallRequirement(
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
            return install_req, name
    if urlparse(pip_line).scheme in ("http", "https", "file") or any(
        pip_line.endswith(s) for s in INSTALLABLE_EXTENSIONS
    ):
        parts = parse_req_from_line(pip_line, line_source)
    else:
        # It's a requirement
        if "--index" in pip_line:
            pip_line = pip_line.split("--index")[0]
        if " -i " in pip_line:
            pip_line = pip_line.split(" -i ")[0]
        # handle local version identifiers (like the ones torch uses in their public index)
        if "+" in pip_line:
            pip_line = pip_line.split("+")[0]
        parts = parse_req_from_line(pip_line, line_source)

    install_req = InstallRequirement(
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
    return install_req, name


def file_path_from_pipfile(path_str, pipfile_entry):
    """Creates an installable file path from a pipfile entry.
    Handles local and remote paths, files and directories;
    supports extras and editable specification.
    Outputs a pip installable line.
    """
    if path_str.startswith(("http:", "https:", "ftp:")):
        req_str = path_str
    else:
        req_str = ensure_path_is_relative(path_str)

    if pipfile_entry.get("extras"):
        req_str = f"{req_str}[{','.join(pipfile_entry['extras'])}]"
    if pipfile_entry.get("editable", False):
        req_str = f"-e {req_str}"

    return req_str


def normalize_vcs_url(vcs_url):
    """Return vcs_url and possible vcs_ref from a given vcs_url."""
    # We have to handle the fact that some vcs urls have a ref in them
    # and some have a netloc with a username and password in them, and some have both
    vcs_ref = ""
    if "@" in vcs_url:
        parsed_url = urlparse(vcs_url)
        if "@" in parsed_url.path:
            url_parts = vcs_url.rsplit("@", 1)
            vcs_url = url_parts[0]
            vcs_ref = url_parts[1]
    return vcs_url, vcs_ref


def install_req_from_pipfile(name, pipfile):
    """Creates an InstallRequirement from a name and a pipfile entry.
    Handles VCS, local & remote paths, and regular named requirements.
    "file" and "path" entries are treated the same.
    """
    _pipfile = {}
    vcs = None
    if hasattr(pipfile, "keys"):
        _pipfile = dict(pipfile).copy()
    else:
        vcs = next(iter([vcs for vcs in VCS_LIST if pipfile.startswith(f"{vcs}+")]), None)
        if vcs is not None:
            _pipfile[vcs] = pipfile

    extras = _pipfile.get("extras", [])
    extras_str = ""
    if extras:
        extras_str = f"[{','.join(extras)}]"
    if not vcs:
        vcs = next(iter([vcs for vcs in VCS_LIST if vcs in _pipfile]), None)

    if vcs:
        vcs_url = _pipfile[vcs]
        subdirectory = _pipfile.get("subdirectory", "")
        if subdirectory:
            subdirectory = f"#subdirectory={subdirectory}"
        vcs_url, fallback_ref = normalize_vcs_url(vcs_url)
        req_str = f"{vcs_url}@{_pipfile.get('ref', fallback_ref)}{extras_str}"
        if not req_str.startswith(f"{vcs}+"):
            req_str = f"{vcs}+{req_str}"
        if f"{vcs}+file://" in req_str or _pipfile.get("editable", False):
            req_str = (
                f"-e {req_str}#egg={name}{extras_str}{subdirectory.replace('#', '&')}"
            )
        else:
            req_str = f"{name}{extras_str}@ {req_str}{subdirectory}"
    elif "path" in _pipfile:
        req_str = file_path_from_pipfile(_pipfile["path"], _pipfile)
    elif "file" in _pipfile:
        req_str = file_path_from_pipfile(_pipfile["file"], _pipfile)
    else:
        # We ensure version contains an operator. Default to equals (==)
        _pipfile["version"] = version = get_version(pipfile)
        if version and not is_star(version) and COMPARE_OP.match(version) is None:
            _pipfile["version"] = f"=={version}"
        if is_star(version) or version == "==*":
            version = ""
        req_str = f"{name}{extras_str}{version}"

    install_req, _ = expansive_install_req_from_line(
        req_str,
        comes_from=None,
        use_pep517=False,
        isolated=False,
        hash_options={"hashes": _pipfile.get("hashes", [])},
        constraint=False,
        expand_env=True,
    )
    markers = PipenvMarkers.from_pipfile(name, _pipfile)
    return install_req, markers, req_str


def from_pipfile(name, pipfile):
    install_req, markers, req_str = install_req_from_pipfile(name, pipfile)
    if markers:
        markers = str(markers)
        install_req.markers = Marker(markers)

    # Construct the requirement string for your Requirement class
    extras_str = ""
    if install_req.req and install_req.req.extras:
        extras_str = f"[{','.join(install_req.req.extras)}]"
    specifier = install_req.req.specifier if install_req.req else ""
    req_str = f"{install_req.name}{extras_str}{specifier}"
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
        # Constraints cannot contain extras
        dep_name = dep_name.split("[", 1)[0]
        # Creating a constraint as a canonical name plus a version specifier
        if isinstance(dep_version, str):
            if dep_version and not is_star(dep_version):
                if COMPARE_OP.match(dep_version) is None:
                    dep_version = f"=={dep_version}"
                c = f"{canonicalize_name(dep_name)}{dep_version}"
            else:
                c = canonicalize_name(dep_name)
        else:
            if not any(k in dep_version for k in ["path", "file", "uri"]):
                if dep_version.get("skip_resolver") is True:
                    continue
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

    if constraints:
        constraints_file.write("\n".join(constraints))
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
