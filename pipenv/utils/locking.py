import copy
import itertools
import os
import re
import stat
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.resolver.schema import LockedRequirement
from pipenv.utils.dependencies import (
    clean_resolved_dep,
    expansive_install_req_from_line,
    is_editable,
    is_vcs,
    merge_items,
    pep423_name,
    translate_markers,
)
from pipenv.utils.exceptions import (
    LockfileCorruptException,
    MissingParameter,
    PipfileNotFound,
)
from pipenv.utils.pipfile import DEFAULT_NEWLINES, ProjectFile
from pipenv.vendor.plette import lockfiles


def merge_markers(entry, markers):
    if not isinstance(markers, list):
        markers = [markers]
    for marker in markers:
        if not isinstance(marker, str):
            marker = str(marker)
        if "markers" not in entry:
            entry["markers"] = marker
        elif marker not in entry["markers"]:
            entry["markers"] = f"({entry['markers']}) and ({marker})"


def get_locked_dep(project, dep, pipfile_section, current_entry=None):
    # initialize default values
    is_top_level = False

    # if the dependency has a name, find corresponding entry in pipfile
    if isinstance(dep, dict) and dep.get("name"):
        dep_name = pep423_name(dep["name"])
        for pipfile_key, pipfile_entry in pipfile_section.items():
            if pep423_name(pipfile_key) == dep_name or pipfile_key == dep_name:
                is_top_level = True
                if isinstance(pipfile_entry, dict):
                    # Copy before mutating: pipfile_section is the cached
                    # parsed_pipfile, so popping in place strips the original
                    # Pipfile entry and corrupts the next write_toml.
                    pipfile_entry = {
                        k: v
                        for k, v in pipfile_entry.items()
                        if k not in ("version", "ref")
                    }
                    dep.update(pipfile_entry)
                break

    # clean the dependency
    lockfile_entry = clean_resolved_dep(project, dep, is_top_level, current_entry)

    # get the lockfile version and compare with pipfile version
    lockfile_name, lockfile_dict = lockfile_entry.copy().popitem()
    lockfile_entry[lockfile_name] = lockfile_dict

    return lockfile_entry


def prepare_lockfile(
    project,
    results: Sequence[Union[LockedRequirement, Dict[str, Any]]],
    pipfile,
    lockfile_section,
    old_lock_data=None,
):
    """Convert the resolver's typed output into the TOML-ready lockfile shape.

    Since T_F.3 B3, ``results`` is expected to be a ``Sequence`` of
    :class:`pipenv.resolver.schema.LockedRequirement` instances — the
    typed envelope that the resolver subprocess (or in-process branch)
    now hands back.  Each entry is converted via
    :meth:`LockedRequirement.to_lockfile_dict`, then handed through the
    existing project-side post-processing
    (:func:`pipenv.utils.locking.get_locked_dep`) which applies things the
    typed schema deliberately does NOT carry: project-relative file-URL
    rewriting (gh-6119), top-level hash unearthing, and ``version="*"``
    fallback to the previous lockfile entry.

    Legacy ``dict``-shaped entries are still accepted as a transitional
    convenience so callers that have not yet been migrated continue to
    work; this fallback will be removed once T_F.3 Wave B is fully
    landed.  No new code should rely on it.
    """
    if old_lock_data is None:
        old_lock_data = {}
    for dep in results:
        if not dep:
            continue
        if isinstance(dep, LockedRequirement):
            dep_dict = dep.to_lockfile_dict()
        else:
            dep_dict = dep
        dep_name = dep_dict["name"]
        current_entry = None
        if dep_name in old_lock_data:
            current_entry = old_lock_data[dep_name]
        lockfile_entry = get_locked_dep(project, dep_dict, pipfile, current_entry)

        # If the current dependency doesn't exist in the lockfile, add it
        if dep_name not in lockfile_section:
            lockfile_section[dep_name] = lockfile_entry[dep_name]
        else:
            # If the dependency exists, update the details
            current_entry = lockfile_section[dep_name]
            if not isinstance(current_entry, dict):
                lockfile_section[dep_name] = lockfile_entry[dep_name]
            else:
                # If the current entry is a dict, merge the new details
                lockfile_section[dep_name].update(lockfile_entry[dep_name])
                lockfile_section[dep_name] = translate_markers(lockfile_section[dep_name])
    return lockfile_section


@contextmanager
def atomic_open_for_write(target, binary=False, newline=None, encoding=None) -> None:
    """Atomically open `target` for writing.
    This is based on Lektor's `atomic_open()` utility, but simplified a lot
    to handle only writing, and skip many multiprocess/thread edge cases
    handled by Werkzeug.
    :param target: Target filename to write (string or Path)
    :param bool binary: Whether to open in binary mode, default False
    :param Optional[str] newline: The newline character to use when writing, determined
        from system if not supplied.
    :param Optional[str] encoding: The encoding to use when writing, defaults to system
        encoding.
    How this works:
    * Create a temp file (in the same directory of the actual target), and
      yield for surrounding code to write to it.
    * If something goes wrong, try to remove the temp file. The actual target
      is not touched whatsoever.
    * If everything goes well, close the temp file, and replace the actual
      target with this new file.
    . code:: python
        >>> fn = "test_file.txt"
        >>> def read_test_file(filename=fn):
                with open(filename, 'r') as fh:
                    print(fh.read().strip())
        >>> with open(fn, "w") as fh:
                fh.write("this is some test text")
        >>> read_test_file()
        this is some test text
        >>> def raise_exception_while_writing(filename):
                with open(filename, "w") as fh:
                    fh.write("writing some new text")
                    raise RuntimeError("Uh oh, hope your file didn't get overwritten")
        >>> raise_exception_while_writing(fn)
        Traceback (most recent call last):
            ...
        RuntimeError: Uh oh, hope your file didn't get overwritten
        >>> read_test_file()
        writing some new text
        >>> def raise_exception_while_writing(filename):
                with atomic_open_for_write(filename) as fh:
                    fh.write("Overwriting all the text from before with even newer text")
                    raise RuntimeError("But did it get overwritten now?")
        >>> raise_exception_while_writing(fn)
            Traceback (most recent call last):
                ...
            RuntimeError: But did it get overwritten now?
        >>> read_test_file()
            writing some new text
    """
    # Convert target to Path object
    target_path = Path(target)

    # Create mode string
    mode = "w+b" if binary else "w"

    # Create temporary file in the same directory as the target
    f = NamedTemporaryFile(
        dir=str(target_path.parent),
        prefix=".__atomic-write",
        mode=mode,
        encoding=encoding,
        newline=newline,
        delete=False,
    )

    # Get path object for the temporary file
    temp_path = Path(f.name)

    # Set permissions to 0644
    with suppress(OSError):
        temp_path.chmod(stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    try:
        yield f
    except BaseException:
        f.close()
        with suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise
    else:
        f.close()
        try:
            # This is needed on Windows
            target_path.unlink(missing_ok=True)
        except OSError:
            pass

        # Rename the temporary file to the target
        # Note: Path.rename() is equivalent to os.rename()
        temp_path.rename(target_path)


@dataclass
class Lockfile:
    lockfile: lockfiles.Lockfile
    path: Path = field(
        default_factory=lambda: Path(os.curdir).joinpath("Pipfile.lock").absolute()
    )
    _requirements: Optional[List[Any]] = field(default_factory=list)
    _dev_requirements: Optional[List[Any]] = field(default_factory=list)
    projectfile: ProjectFile = None
    newlines: str = DEFAULT_NEWLINES

    def __post_init__(self):
        if not self.path:
            self.path = Path(os.curdir).absolute()
        if not self.projectfile:
            self.projectfile = self.load_projectfile(os.curdir, create=False)
        if not self.lockfile:
            self.lockfile = self.projectfile.model

    @property
    def section_keys(self):
        return set(self.lockfile.keys()) - {"_meta"}

    @property
    def extended_keys(self):
        return list(itertools.product(self.section_keys, ["", "vcs", "editable"]))

    def get(self, k):
        return self.__getitem__(k)

    def __contains__(self, k):
        check_lockfile = k in self.extended_keys or self.lockfile.__contains__(k)
        if check_lockfile:
            return True
        return super().__contains__(k)

    def __setitem__(self, k, v):
        lockfile = self.lockfile
        lockfile.__setitem__(k, v)

    def __getitem__(self, k, *args, **kwargs):
        retval = None
        lockfile = self.lockfile
        try:
            retval = lockfile[k]
        except KeyError:
            if "-" in k:
                section, _, pkg_type = k.rpartition("-")
                vals = getattr(lockfile.get(section, {}), "_data", {})
                if pkg_type == "vcs":
                    retval = {k: v for k, v in vals.items() if is_vcs(v)}
                elif pkg_type == "editable":
                    retval = {k: v for k, v in vals.items() if is_editable(v)}
            if retval is None:
                raise
        else:
            retval = getattr(retval, "_data", retval)
        return retval

    def __getattr__(self, k, *args, **kwargs):
        lockfile = self.lockfile
        try:
            return super().__getattribute__(k)
        except AttributeError:
            retval = getattr(lockfile, k, None)
        if retval is not None:
            return retval
        return super().__getattribute__(k, *args, **kwargs)

    def get_deps(self, dev=False, only=True):
        deps = {}
        if dev:
            deps.update(self.develop._data)
            if only:
                return deps
        deps = merge_items([deps, self.default._data])
        return deps

    @classmethod
    def read_projectfile(cls, path):
        pf = ProjectFile.read(path, lockfiles.Lockfile, invalid_ok=True)
        return pf

    @classmethod
    def lockfile_from_pipfile(cls, pipfile_path):
        from pipenv.utils.pipfile import Pipfile

        # Convert to Path object
        path = Path(pipfile_path)

        if path.is_file():
            # Ensure we have an absolute path
            if not path.is_absolute():
                path = path.resolve()

            # Load the Pipfile from the parent directory
            pipfile = Pipfile.load(path.parent)
            return lockfiles.Lockfile.with_meta_from(pipfile.pipfile)

        raise PipfileNotFound(pipfile_path)

    @classmethod
    def load_projectfile(
        cls, path: Optional[str] = None, create: bool = True, data: Optional[Dict] = None
    ) -> "ProjectFile":
        if not path:
            path = os.curdir
        path = Path(path).absolute()
        project_path = path if path.is_dir() else path.parent
        lockfile_path = path if path.is_file() else project_path / "Pipfile.lock"
        if not project_path.exists():
            raise OSError(f"Project does not exist: {project_path.as_posix()}")
        elif not lockfile_path.exists() and not create:
            raise FileNotFoundError(
                f"Lockfile does not exist: {lockfile_path.as_posix()}"
            )
        projectfile = cls.read_projectfile(lockfile_path.as_posix())
        if not lockfile_path.exists():
            if not data:
                pipfile = project_path.joinpath("Pipfile")
                lf = cls.lockfile_from_pipfile(pipfile)
            else:
                lf = lockfiles.Lockfile(data)
            projectfile.model = lf
        else:
            if data:
                raise ValueError("Cannot pass data when loading existing lockfile")
            with open(lockfile_path.as_posix()) as f:
                projectfile.model = lockfiles.Lockfile.load(f)
        return projectfile

    @classmethod
    def from_data(
        cls, path: Optional[str], data: Optional[Dict], meta_from_project: bool = True
    ) -> "Lockfile":
        if path is None:
            raise MissingParameter("path")
        if data is None:
            raise MissingParameter("data")
        if not isinstance(data, dict):
            raise TypeError("Expecting a dictionary for parameter 'data'")

        # Convert to Path object and resolve to absolute path
        path_obj = Path(path).resolve()

        # Determine project directory
        if path_obj.is_dir():
            project_path = path_obj
        elif not path_obj.is_dir() and path_obj.parent.is_dir():
            project_path = path_obj.parent

        # Create paths for Pipfile and Pipfile.lock
        pipfile_path = project_path / "Pipfile"
        lockfile_path = project_path / "Pipfile.lock"

        if meta_from_project:
            lockfile = cls.lockfile_from_pipfile(pipfile_path)
            lockfile.update(data)
        else:
            lockfile = lockfiles.Lockfile(data)

        projectfile = ProjectFile(
            line_ending=DEFAULT_NEWLINES,
            location=str(
                lockfile_path
            ),  # Convert to string if ProjectFile expects a string
            model=lockfile,
        )

        return cls(
            projectfile=projectfile,
            lockfile=lockfile,
            newlines=projectfile.line_ending,
            path=lockfile_path,  # No need to convert to Path again if already expecting Path
        )

    @classmethod
    def load(cls, path: Optional[str], create: bool = True) -> "Lockfile":
        try:
            projectfile = cls.load_projectfile(path, create=create)
        except JSONDecodeError:
            # Convert to Path object and resolve to absolute path
            path_obj = Path(path).resolve()

            # Determine if the path is a directory or file
            if path_obj.is_dir():
                path_obj = path_obj / "Pipfile.lock"

            # Create backup path
            formatted_path = str(path_obj)
            backup_path = f"{formatted_path}.bak"

            # Show error and create backup
            LockfileCorruptException.show(formatted_path, backup_path=backup_path)
            path_obj.rename(backup_path)

            # Try loading again after backing up corrupted file
            cls.load(formatted_path, create=True)

        # Create Path object from projectfile location
        lockfile_path = Path(projectfile.location)

        # Create instance with required arguments
        creation_args = {
            "projectfile": projectfile,
            "lockfile": projectfile.model,
            "newlines": projectfile.line_ending,
            "path": lockfile_path,
        }
        return cls(**creation_args)

    @classmethod
    def create(cls, path: Optional[str], create: bool = True) -> "Lockfile":
        return cls.load(path, create=create)

    def get_section(self, name: str) -> Optional[Dict]:
        return self.lockfile.get(name)

    @property
    def develop(self) -> Dict:
        return self.lockfile.develop

    @property
    def default(self) -> Dict:
        return self.lockfile.default

    @staticmethod
    def _pip_marker(marker_str: str) -> Optional[str]:
        """Strip pylock.toml-specific ``dependency_groups`` conditions from a
        marker string so that the result is valid PEP 508 for pip.

        Pipenv already filters packages by dependency group before calling pip,
        so pip never needs to evaluate these conditions itself.

        Patterns produced by PylockFile.from_lockfile:
          * ``'dev' in dependency_groups``
            → no marker (return None)
          * ``('dev' in dependency_groups) and (python_version >= '3.10')``
            → ``python_version >= '3.10'``
        """
        if "dependency_groups" not in marker_str:
            return marker_str
        m = re.match(
            r"^\([^)]*\bdependency_groups\b[^)]*\)\s+and\s+\((.+)\)$",
            marker_str,
            re.DOTALL,
        )
        if m:
            return m.group(1)
        return None

    def get_requirements(
        self, dev: bool = True, only: bool = False, categories: Optional[List[str]] = None
    ) -> Iterator[InstallRequirement]:
        from pipenv.utils.dependencies import requirement_from_lockfile

        if categories:
            deps = {}
            for category in categories:
                if category == "packages":
                    category = "default"
                elif category == "dev-packages":
                    category = "develop"
                try:
                    category_deps = self[category]
                except KeyError:
                    category_deps = {}
                    self.lockfile[category] = category_deps
                deps = merge_items([deps, category_deps])
        else:
            deps = self.get_deps(dev=dev, only=only)
        for package_name, package_info in deps.items():
            pip_line = requirement_from_lockfile(
                package_name, package_info, include_hashes=False, include_markers=False
            )
            # Strip pylock.toml-specific dependency_groups conditions before
            # passing to pip — pip only understands standard PEP 508 markers.
            raw_marker = (
                package_info.get("markers") if isinstance(package_info, dict) else None
            )
            pip_marker = self._pip_marker(raw_marker) if raw_marker else raw_marker
            if pip_marker != raw_marker:
                pip_info = dict(package_info)
                if pip_marker:
                    pip_info["markers"] = pip_marker
                else:
                    pip_info.pop("markers", None)
                pip_line_specified = requirement_from_lockfile(
                    package_name, pip_info, include_hashes=True, include_markers=True
                )
            else:
                pip_line_specified = requirement_from_lockfile(
                    package_name, package_info, include_hashes=True, include_markers=True
                )
            install_req, _ = expansive_install_req_from_line(pip_line)
            # Set markers from the lockfile entry onto install_req so that
            # environment marker evaluation (e.g. python_version < '3.11') can
            # be performed when deciding whether to install the package.
            if not install_req.markers and pip_marker:
                from pipenv.patched.pip._vendor.packaging.markers import (
                    Marker as PipMarker,
                )

                try:
                    install_req.markers = PipMarker(pip_marker)
                except Exception:
                    pass
            yield install_req, pip_line_specified

    def requirements_list(self, category: str) -> List[Dict]:
        if self.lockfile.get(category):
            return [
                {name: entry._data} for name, entry in self.lockfile[category].items()
            ]
        return []

    def write(self) -> None:
        self.projectfile.model = copy.deepcopy(self.lockfile)
        self.projectfile.write()
