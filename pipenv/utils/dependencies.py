import os
from contextlib import contextmanager
from typing import Mapping, Sequence

from packaging.markers import Marker

from .constants import SCHEME_LIST, VCS_LIST
from .shell import temp_path


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


class HackedPythonVersion:
    """A Beautiful hack, which allows us to tell pip which version of Python we're using."""

    def __init__(self, python_version, python_path):
        self.python_version = python_version
        self.python_path = python_path

    def __enter__(self):
        # Only inject when the value is valid
        if self.python_version:
            os.environ["PIPENV_REQUESTED_PYTHON_VERSION"] = str(self.python_version)
        if self.python_path:
            os.environ["PIP_PYTHON_PATH"] = str(self.python_path)

    def __exit__(self, *args):
        # Restore original Python version information.
        try:
            del os.environ["PIPENV_REQUESTED_PYTHON_VERSION"]
        except KeyError:
            pass


def get_canonical_names(packages):
    """Canonicalize a list of packages and return a set of canonical names"""
    from pipenv.vendor.packaging.utils import canonicalize_name

    if not isinstance(packages, Sequence):
        if not isinstance(packages, str):
            return packages
        packages = [packages]
    return {canonicalize_name(pkg) for pkg in packages if pkg}


def pep440_version(version):
    """Normalize version to PEP 440 standards"""
    # Use pip built-in version parser.
    from pipenv.vendor.pip_shims import shims

    return str(shims.parse_version(version))


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    name = name.lower()
    if any(i not in name for i in (VCS_LIST + SCHEME_LIST)):
        return name.replace("_", "-")

    else:
        return name


def get_vcs_deps(project=None, dev=False, pypi_mirror=None, packages=None, reqs=None):
    from pipenv.vendor.requirementslib.models.requirements import Requirement

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
                    from pipenv.vendor.requirementslib.models.requirements import (
                        Requirement,
                    )

                    # from distutils.sysconfig import get_python_lib
                    # sys.path = [repo.checkout_directory, "", ".", get_python_lib(plat_specific=0)]
                    commit_hash = repo.get_commit_hash()
                    name = requirement.normalized_name
                    lockfile[name] = requirement.pipfile_entry[1]
                    lockfile[name]["ref"] = commit_hash
                    result.append(requirement)
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
    from pipenv.vendor.packaging.markers import default_environment

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
    from pipenv.vendor.requirementslib.utils import is_vcs

    name = pep423_name(dep["name"])
    lockfile = {}
    # We use this to determine if there are any markers on top level packages
    # So we can make sure those win out during resolution if the packages reoccur
    if "version" in dep and dep["version"] and not dep.get("editable", False):
        version = "{}".format(dep["version"])
        if not version.startswith("=="):
            version = f"=={version}"
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
        pipfile_fs_key = next(
            iter(k for k in ["path", "file"] if k in pipfile_entry), None
        )
    if fs_key and pipfile_fs_key and fs_key != pipfile_fs_key:
        lockfile[pipfile_fs_key] = pipfile_entry[pipfile_fs_key]
    elif fs_key is not None:
        lockfile[fs_key] = dep[fs_key]

    # If a package is **PRESENT** in the pipfile but has no markers, make sure we
    # **NEVER** include markers in the lockfile
    if "markers" in dep and dep.get("markers", "").strip():
        # First, handle the case where there is no top level dependency in the pipfile
        if not is_top_level:
            translated = translate_markers(dep).get("markers", "").strip()
            if translated:
                try:
                    lockfile["markers"] = translated
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


def convert_deps_to_pip(
    deps,
    project=None,
    r=True,
    include_index=True,
    include_hashes=True,
    include_markers=True,
):
    """ "Converts a Pipfile-formatted dependency to a pip-formatted one."""
    from pipenv.vendor.requirementslib.models.requirements import Requirement

    dependencies = []
    for dep_name, dep in deps.items():
        if project:
            project.clear_pipfile_cache()
        indexes = getattr(project, "pipfile_sources", []) if project is not None else []
        new_dep = Requirement.from_pipfile(dep_name, dep)
        if new_dep.index:
            include_index = True
        sources = indexes if include_index else None
        req = new_dep.as_line(
            sources=sources,
            include_hashes=include_hashes,
            include_markers=include_markers,
        ).strip()
        dependencies.append(req)
    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    from pipenv.vendor.vistir.path import create_tracked_tempfile

    f = create_tracked_tempfile(suffix="-requirements.txt", delete=False)
    f.write("\n".join(dependencies).encode("utf-8"))
    f.close()
    return f.name


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


@contextmanager
def locked_repository(requirement):
    from pipenv.vendor.vistir.path import create_tracked_tempdir

    if not requirement.is_vcs:
        return
    original_base = os.environ.pop("PIP_SHIMS_BASE_MODULE", None)
    os.environ["PIP_SHIMS_BASE_MODULE"] = "pipenv.patched.notpip"
    src_dir = create_tracked_tempdir(prefix="pipenv-", suffix="-src")
    try:
        with requirement.req.locked_vcs_repo(src_dir=src_dir) as repo:
            yield repo
    finally:
        if original_base:
            os.environ["PIP_SHIMS_BASE_MODULE"] = original_base
