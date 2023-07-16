import os
from contextlib import contextmanager
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

from pipenv.patched.pip._internal.req.constructors import parse_req_from_line
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._vendor.distlib.util import COMPARE_OP
from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.patched.pip._vendor.packaging.requirements import Requirement
from pipenv.patched.pip._vendor.packaging.version import parse
from pipenv.vendor.requirementslib.fileutils import create_tracked_tempdir
from pipenv.vendor.requirementslib.models.markers import PipenvMarkers
from pipenv.vendor.requirementslib.models.utils import get_version
from pipenv.vendor.requirementslib.utils import prepare_pip_source_args

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

    :param pipfile_entry: A dictionariy of keys and values representing a pipfile entry
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


def clean_resolved_dep(dep, is_top_level=False, pipfile_entry=None):
    from pipenv.patched.pip._vendor.packaging.requirements import (
        Requirement as PipRequirement,
    )

    name = pep423_name(dep["name"])
    lockfile = {}

    version = dep.get("version", None)

    is_vcs_or_file = False
    for vcs_type in VCS_LIST:
        if vcs_type in dep:
            lockfile[vcs_type] = dep[vcs_type]
            lockfile["ref"] = dep.get("rev")
            is_vcs_or_file = True

    if version and not is_vcs_or_file:
        if isinstance(version, PipRequirement):
            if version.specifier:
                lockfile["version"] = str(version.specifier)
            if version.extras:
                lockfile["extras"] = sorted(version.extras)

    if "editable" in dep:
        lockfile["editable"] = dep["editable"]

    preferred_file_keys = ["path", "file"]
    dependency_file_key = next(iter(k for k in preferred_file_keys if k in dep), None)
    if dependency_file_key:
        lockfile[dependency_file_key] = dep[dependency_file_key]

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


def req_as_line2(dep_name, dep, include_hashes, include_markers, sources):
    """Creates a requirement line from a requirement name and an InstallRequirement"""
    line = []
    if dep.link:
        if dep.link.is_vcs:  # VCS Requirements
            line.append(f"{dep.link.url}#egg={dep_name}")
            if dep.link.revision and not dep.link.is_artifact:
                line.append(f"@{dep.link.revision}")
            if include_markers and dep.marker:
                line.append(f"; {dep.marker}")
        else:  # URL or local file path Requirements
            line.append(f"{dep.link.egg_fragment} @ {dep.link.url_without_fragment}")
            if include_markers and dep.marker:
                line.append(f"; {dep.marker}")
    else:  # PyPI package
        line.append(f"{dep_name}")
        if dep.specifier:
            line.append(f"{dep.specifier}")
        if include_hashes and dep.hashes():
            line.append(f"\n--hash={dep.hashes()}")
        if include_markers and dep.marker:
            line.append(f"; {dep.marker}")
    line.append("\n")

    if hasattr(dep, "index"):
        sources = [s for s in sources if s.get("name") == dep.ndex]
    else:
        sources = [sources[0]]
    source_list = prepare_pip_source_args(sources)
    line.extend(source_list)

    pip_line = "".join(line)
    return pip_line


def req_as_line(dep_name, dep, include_hashes, include_markers, sources):
    if isinstance(dep, str):
        if is_star(dep):
            return dep_name
        elif not COMPARE_OP.match(dep):
            return f"{dep_name}=={dep}"
        return f"{dep_name}{dep}"
    line = []
    vcs = next(iter([vcs for vcs in VCS_LIST if vcs in dep]), None)

    if vcs and vcs in dep:  # VCS Requirements
        extras = ""
        ref = ""
        if dep.get("rev"):
            ref = f"@{dep['ref']}"
        if "extras" in dep:
            extras = f"[{','.join(dep['extras'])}]"
        git_req = f"{dep_name}{extras} @ {dep[vcs]}{ref}"
        if "subdirectory" in dep:
            git_req += f"#subdirectory={dep['subdirectory']}"
        line.append(git_req)
    elif "file" in dep:  # File Requirements
        extras = ""
        if "extras" in dep:
            extras = f"[{','.join(dep['extras'])}]"
        line.append(f"{dep_name}{extras} @ {dep['file']}")
    elif "path" in dep:  # Editable Requirements
        if dep.get("editable"):
            line.append("-e")
        line.append(dep["path"])
    else:  # Normal/Named Requirements
        line.append(dep_name)
        if "extras" in dep:
            line[-1] += f"[{','.join(dep['extras'])}]"
        if "version" in dep:
            version = dep["version"]
            if version and not is_star(version) and COMPARE_OP.match(version):
                version = f"=={version}"
                line[-1] += version

    if include_markers and dep.get("markers"):
        line.append(f'; {dep["markers"]}')

    if include_hashes and dep.get("hashes"):
        line.extend([f"--hash={hash}" for hash in dep["hashes"]])

    if dep.get("index"):
        sources = [s for s in sources if s.get("name") == dep["index"]]
    else:
        sources = [sources[0]]
    source_list = prepare_pip_source_args(sources)
    line.extend(source_list)

    pip_line = " ".join(line)
    return pip_line


def convert_deps_to_pip(
    deps,
    project=None,
    include_index=True,
    include_hashes=True,
    include_markers=True,
):
    """ "Converts a Pipfile-formatted dependency to a pip-formatted one."""
    dependencies = []
    for dep_name, dep in deps.items():
        if project:
            project.clear_pipfile_cache()
        indexes = []
        if project:
            indexes = project.pipfile_sources()
        sources = indexes
        req = req_as_line(dep_name, dep, include_hashes, include_markers, sources)
        dependencies.append(req)
    return dependencies


def install_req_from_line(
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
    if name.startswith("-e "):
        # Editable requirement
        editable_path = name.split("-e ")[1]
        if os.path.isdir(editable_path):
            name = editable_path
        else:
            name = os.path.abspath(editable_path)

    if (
        os.path.isfile(name)
        or os.path.isdir(name)
        or urlparse(name).scheme in ("http", "https", "file")
    ):
        # It's a local file, directory or URL. Extract the base name, and
        # then the package name.
        if urlparse(name).scheme == "":
            # It's a local file or directory
            base_name = os.path.basename(name)
        else:
            # It's a URL
            base_name = os.path.basename(urlparse(name).path)
        package_name, _ = os.path.splitext(base_name)
        package_name = package_name.split("-")[0]
    else:
        # It's a requirement
        package_name = name

    parts = parse_req_from_line(package_name, line_source)

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
    _pipfile["version"] = get_version(pipfile)

    # We ensure version contains an operator. Default to equals (==)
    if (
        _pipfile["version"]
        and not is_star(_pipfile["version"])
        and COMPARE_OP.match(_pipfile["version"]) is None
    ):
        _pipfile["version"] = "=={}".format(_pipfile["version"])
    vcs = next(iter([vcs for vcs in VCS_LIST if vcs in _pipfile]), None)

    if vcs:
        _pipfile["vcs"] = vcs
        req_str = f"{name}@{_pipfile[vcs]}"

    elif any(key in _pipfile for key in ["path", "file", "uri"]):
        req_str = f"{name}@{_pipfile['path']}"

    else:
        req_str = f"{name}{_pipfile['version']}"

    extras = _pipfile.get("extras", [])
    if extras:
        req_str += f"[{','.join(extras)}]"

    install_req = install_req_from_line(
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
    req_str = f"{install_req.name}{install_req.req.specifier}"
    if install_req.req.extras:
        req_str += f"[{','.join(install_req.req.extras)}]"
    if install_req.markers:
        req_str += f"; {install_req.markers}"

    # Create the Requirement instance
    cls_inst = Requirement(req_str)

    return cls_inst


def get_constraints_from_deps(deps):
    """Get constraints from dictionary-formatted dependency"""
    from pip._vendor.packaging.utils import canonicalize_name

    from pipenv.patched.pip._vendor.distlib.util import COMPARE_OP

    constraints = []
    for dep_name, dep_version in deps.items():
        # Creating a constraint as a canonical name plus a version specifier
        if not is_star(dep_version) and COMPARE_OP.match(dep_version) is None:
            dep_version = f"=={dep_version}"
        c = f"{canonicalize_name(dep_name)}{dep_version}"
        constraints.append(c)
    return constraints


def prepare_constraint_file(
    constraints,
    directory=None,
    sources=None,
    pip_args=None,
):
    if not directory:
        directory = create_tracked_tempdir(suffix="-requirements", prefix="pipenv-")

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
