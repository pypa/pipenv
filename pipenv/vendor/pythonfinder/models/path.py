import errno
import operator
import os
from pathlib import Path
import sys
from collections import defaultdict, ChainMap
from typing import Any, Dict, List, Generator, Iterator, Optional, Tuple, Union

from pipenv.vendor.pydantic import BaseModel, Field, validator, root_validator
from pipenv.patched.pip._vendor.pyparsing.core import cached_property

from ..compat import fs_str
from ..environment import (
    ASDF_DATA_DIR,
    ASDF_INSTALLED,
    PYENV_INSTALLED,
    PYENV_ROOT,
    SHIM_PATHS,
)
from ..utils import (
    dedup,
    ensure_path,
    is_in_path,
    normalize_path,
    parse_asdf_version_order,
    parse_pyenv_version_order,
    split_version_and_name,
)
from .mixins import PathEntry
from .python import PythonFinder, PythonVersion
from .windows import WindowsFinder


def exists_and_is_accessible(path):
    try:
        return path.exists()
    except PermissionError as pe:
        if pe.errno == errno.EACCES:  # Permission denied
            return False
        else:
            raise


class SystemPath(BaseModel):
    global_search: bool = True
    paths: Dict[str, Union[PythonFinder, PathEntry]] = Field(default_factory=lambda: defaultdict(PathEntry))
    executables: List[PathEntry] = Field(default_factory=list)
    python_executables: Dict[str, PathEntry] = Field(default_factory=dict)
    path_order: List[str] = Field(default_factory=list)
    python_version_dict: Dict[Tuple, Any] = Field(default_factory=lambda: defaultdict(list))
    version_dict: Dict[Tuple, List[PathEntry]] = Field(default_factory=lambda: defaultdict(list))
    only_python: bool = False
    pyenv_finder: Optional[PythonFinder] = None
    asdf_finder: Optional[PythonFinder] = None
    windows_finder: Optional[WindowsFinder] = None
    system: bool = False
    ignore_unsupported: bool = False
    finders_dict: Dict[str, Union[WindowsFinder, PythonFinder]] = Field(default_factory=lambda: dict())

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        keep_untouched = (cached_property,)

    def __init__(self, **data):
        super().__init__(**data)
        python_executables = {}
        for child in self.paths.values():
            if child.pythons:
                python_executables.update(dict(child.pythons))
        for _, finder in self.finders_dict.items():
            if finder.pythons:
                python_executables.update(dict(finder.pythons))
        self.python_executables = python_executables

    @root_validator(pre=True)
    def set_defaults(cls, values):
        values['python_version_dict'] = defaultdict(list)
        values['pyenv_finder'] = None
        values['windows_finder'] = None
        values['asdf_finder'] = None
        values['path_order'] = []
        values['_finders'] = {}
        values['paths'] = defaultdict(PathEntry)
        return values

    @root_validator(pre=True)
    def set_executables(cls, values):
        paths = values.get('paths')
        if paths:
            values['executables'] = [
                p
                for p in ChainMap(*(child.children.values() for child in paths.values()))
                if p.is_executable
            ]
        return values

    def _register_finder(self, finder_name, finder):
        if finder_name not in self.finders_dict:
            self.finders_dict[finder_name] = finder
        return self

    def clear_caches(self):
        for key in ["executables", "python_executables", "version_dict", "path_entries"]:
            if key in self.__dict__:
                del self.__dict__[key]
        for finder in list(self.finders_dict.keys()):
            del self.finders_dict[finder]
        self.finders_dict = {}

    @property
    def finders(self):
        # type: () -> List[str]
        return [k for k in self.finders_dict.keys()]

    @staticmethod
    def check_for_pyenv():
        return PYENV_INSTALLED or os.path.exists(normalize_path(PYENV_ROOT))

    @staticmethod
    def check_for_asdf():
        return ASDF_INSTALLED or os.path.exists(normalize_path(ASDF_DATA_DIR))

    def set_version_dict(self):
        self.version_dict = defaultdict(list)
        for finder_name, finder in self.finders_dict.items():
            for version, entry in finder.versions.items():
                if finder_name == "windows":
                    if entry not in self.version_dict[version]:
                        self.version_dict[version].append(entry)
                    continue
                if entry not in self.version_dict[version] and entry.is_python:
                    self.version_dict[version].append(entry)
        for _, entry in self.python_executables.items():
            version = entry.as_python  # type: PythonVersion
            if not version:
                continue
            if not isinstance(version, tuple):
                version = version.version_tuple
            if version and entry not in self.version_dict[version]:
                self.version_dict[version].append(entry)

    def _run_setup(self) -> "SystemPath":
        path_order = self.path_order[:]
        if self.global_search and "PATH" in os.environ:
            path_order = path_order + os.environ["PATH"].split(os.pathsep)
        path_order = list(dedup(path_order))
        path_instances = [
            ensure_path(p.strip('"'))
            for p in path_order
            if not any(
                is_in_path(normalize_path(str(p)), normalize_path(shim))
                for shim in SHIM_PATHS
            )
        ]
        self.paths.update(
            {
                p.as_posix(): PathEntry.create(
                    path=p.absolute(), is_root=True, only_python=self.only_python
                )
                for p in path_instances
                if exists_and_is_accessible(p)
            }
        )
        self.path_order = [
            p.as_posix() for p in path_instances if exists_and_is_accessible(p)
        ]
        if os.name == "nt" and "windows" not in self.finders:
            self._setup_windows()
        #: slice in pyenv
        if self.check_for_pyenv() and "pyenv" not in self.finders:
            self._setup_pyenv()
        #: slice in asdf
        if self.check_for_asdf() and "asdf" not in self.finders:
            self._setup_asdf()
        venv = os.environ.get("VIRTUAL_ENV")
        if os.name == "nt":
            bin_dir = "Scripts"
        else:
            bin_dir = "bin"
        if venv and (self.system or self.global_search):
            p = ensure_path(venv)
            path_order = [(p / bin_dir).as_posix()] + self.path_order
            self.path_order = path_order
            self.paths[p] = self.get_path(p.joinpath(bin_dir))
        if self.system:
            syspath = Path(sys.executable)
            syspath_bin = syspath.parent
            if syspath_bin.name != bin_dir and syspath_bin.joinpath(bin_dir).exists():
                syspath_bin = syspath_bin / bin_dir
            path_order = [syspath_bin.as_posix()] + self.path_order
            self.paths[syspath_bin] = PathEntry.create(
                path=syspath_bin, is_root=True, only_python=False
            )
            self.path_order = path_order

    def _get_last_instance(self, path) -> int:
        reversed_paths = reversed(self.path_order)
        paths = [normalize_path(p) for p in reversed_paths]
        normalized_target = normalize_path(path)
        last_instance = next(iter(p for p in paths if normalized_target in p), None)
        if last_instance is None:
            raise ValueError("No instance found on path for target: {0!s}".format(path))
        path_index = self.path_order.index(last_instance)
        return path_index

    def _slice_in_paths(self, start_idx, paths) -> "SystemPath":
        before_path = []
        after_path = []
        if start_idx == 0:
            after_path = self.path_order[:]
        elif start_idx == -1:
            before_path = self.path_order[:]
        else:
            before_path = self.path_order[: start_idx + 1]
            after_path = self.path_order[start_idx + 2 :]
        path_order = before_path + [p.as_posix() for p in paths] + after_path
        self.path_order = path_order

    def _remove_path(self, path) -> "SystemPath":
        path_copy = [p for p in reversed(self.path_order[:])]
        new_order = []
        target = normalize_path(path)
        path_map = {normalize_path(pth): pth for pth in self.paths.keys()}
        if target in path_map:
            del self.paths[path_map[target]]
        for current_path in path_copy:
            normalized = normalize_path(current_path)
            if normalized != target:
                new_order.append(normalized)
        new_order = [ensure_path(p).as_posix() for p in reversed(new_order)]
        self.path_order = new_order
        return self

    def _setup_asdf(self) -> "SystemPath":
        if "asdf" in self.finders and self.asdf_finder is not None:
            return self

        os_path = os.environ["PATH"].split(os.pathsep)
        asdf_finder = PythonFinder.create(
            root=ASDF_DATA_DIR,
            ignore_unsupported=True,
            sort_function=parse_asdf_version_order,
            version_glob_path="installs/python/*",
        )
        asdf_index = None
        try:
            asdf_index = self._get_last_instance(ASDF_DATA_DIR)
        except ValueError:
            asdf_index = 0 if is_in_path(next(iter(os_path), ""), ASDF_DATA_DIR) else -1
        if asdf_index is None:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return self
        # * These are the root paths for the finder
        _ = [p for p in asdf_finder.roots]
        self._slice_in_paths(asdf_index, [asdf_finder.root])
        self.paths[asdf_finder.root] = asdf_finder
        self.paths.update(asdf_finder.roots)
        self.asdf_finder = asdf_finder
        self._remove_path(normalize_path(os.path.join(ASDF_DATA_DIR, "shims")))
        self._register_finder("asdf", asdf_finder)
        return self

    def _setup_pyenv(self) -> "SystemPath":
        if "pyenv" in self.finders and self.pyenv_finder is not None:
            return self

        os_path = os.environ["PATH"].split(os.pathsep)

        pyenv_finder = PythonFinder.create(
            root=PYENV_ROOT,
            sort_function=parse_pyenv_version_order,
            version_glob_path="versions/*",
            ignore_unsupported=self.ignore_unsupported,
        )
        pyenv_index = None
        try:
            pyenv_index = self._get_last_instance(PYENV_ROOT)
        except ValueError:
            pyenv_index = 0 if is_in_path(next(iter(os_path), ""), PYENV_ROOT) else -1
        if pyenv_index is None:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return self
        # * These are the root paths for the finder
        _ = [p for p in pyenv_finder.roots]
        self._slice_in_paths(pyenv_index, [pyenv_finder.root])
        self.paths[pyenv_finder.root] = pyenv_finder
        self.paths.update(pyenv_finder.roots)
        self.pyenv_finder = pyenv_finder
        self._remove_path(os.path.join(PYENV_ROOT, "shims"))
        self._register_finder("pyenv", pyenv_finder)
        return self

    def _setup_windows(self) -> "SystemPath":
        if "windows" in self.finders and self.windows_finder is not None:
            return self
        from .windows import WindowsFinder

        windows_finder = WindowsFinder()
        root_paths = (p for p in windows_finder.paths if p.is_root)
        path_addition = [p.path.as_posix() for p in root_paths]
        new_path_order = self.path_order[:] + path_addition
        new_paths = self.paths.copy()
        new_paths.update({p.path: p for p in root_paths})
        self.windows_finder = windows_finder
        self.path_order = new_path_order
        self.paths = new_paths
        self._register_finder("windows", windows_finder)
        return self

    def get_path(self, path) -> Union[PythonFinder, PathEntry]:
        if path is None:
            raise TypeError("A path must be provided in order to generate a path entry.")
        path = ensure_path(path)
        _path = self.paths.get(path)
        if not _path:
            _path = self.paths.get(path.as_posix())
        if not _path and path.as_posix() in self.path_order and path.exists():
            _path = PathEntry.create(
                path=path.absolute(), is_root=True, only_python=self.only_python
            )
            self.paths[path.as_posix()] = _path
        if not _path:
            raise ValueError("Path not found or generated: {0!r}".format(path))
        return _path

    def _get_paths(self) -> Generator[Union[PythonFinder, PathEntry, WindowsFinder], None, None]:
        for path in self.path_order:
            try:
                entry = self.get_path(path)
            except ValueError:
                continue
            else:
                yield entry

    @cached_property
    def path_entries(self) -> List[Union[PythonFinder, PathEntry, WindowsFinder]]:
        paths = list(self._get_paths())
        return paths

    def find_all(self, executable) -> List[Union["PathEntry", PythonFinder, WindowsFinder]]:
        """
        Search the path for an executable. Return all copies.

        :param executable: Name of the executable
        :type executable: str
        :returns: List[PathEntry]
        """

        sub_which = operator.methodcaller("which", executable)
        filtered = (sub_which(self.get_path(k)) for k in self.path_order)
        return list(filtered)

    def which(self, executable) -> Union["PathEntry", None]:
        """
        Search for an executable on the path.

        :param executable: Name of the executable to be located.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` object.
        """

        sub_which = operator.methodcaller("which", executable)
        filtered = (sub_which(self.get_path(k)) for k in self.path_order)
        return next(iter(f for f in filtered if f is not None), None)

    def _filter_paths(self, finder) -> Iterator:
        for path in self._get_paths():
            if path is None:
                continue
            python_versions = finder(path)
            if python_versions is not None:
                for python in python_versions:
                    if python is not None:
                        yield python

    def _get_all_pythons(self, finder) -> Iterator:
        for python in self._filter_paths(finder):
            if python is not None and python.is_python:
                yield python

    def get_pythons(self, finder) -> Iterator:
        def version_sort_key(entry):
            return entry.as_python.version_sort

        pythons = [entry for entry in self._get_all_pythons(finder)]
        for python in sorted(pythons, key=version_sort_key, reverse=True):
            if python is not None:
                yield python

    def find_all_python_versions(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
    ) -> List["PathEntry"]:
        """Search for a specific python version on the path. Return all copies

        :param major: Major python version to search for.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :param str name: The name of a python version, e.g. ``anaconda3-5.3.0``
        :return: A list of :class:`~pythonfinder.models.PathEntry` instances matching the version requested.
        :rtype: List[:class:`~pythonfinder.models.PathEntry`]
        """
        def version_matcher(py):
            return py.matches(major, minor, patch, pre, dev, arch, python_name=name)

        pythons = [py for py in self.version_dict.values() if version_matcher(py)]

        def version_sort(py):
            return py.version_sort

        return [
            c.comes_from
            for c in sorted(pythons, key=version_sort, reverse=True)
            if c.comes_from
        ]

    def find_python_version(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[Union[str, int]]
        patch=None,  # type: Optional[Union[str, int]]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
        sort_by_path=False,  # type: bool
    ) -> PathEntry:
        """Search for a specific python version on the path.

        :param major: Major python version to search for.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :param str name: The name of a python version, e.g. ``anaconda3-5.3.0``
        :param bool sort_by_path: Whether to sort by path -- default sort is by version(default: False)
        :return: A :class:`~pythonfinder.models.PathEntry` instance matching the version requested.
        :rtype: :class:`~pythonfinder.models.PathEntry`
        """
        major, minor, patch, name = split_version_and_name(major, minor, patch, name)

        return next(
            iter(
                v
                for v in self.find_all_python_versions(
                    major=major,
                    minor=minor,
                    patch=patch,
                    pre=pre,
                    dev=dev,
                    arch=arch,
                    name=name,
                )
            ),
            None,
        )

    @classmethod
    def create(
        cls,
        path=None,
        system=False,
        only_python=False,
        global_search=True,
        ignore_unsupported=True,
    ) -> "SystemPath":
        """Create a new :class:`pythonfinder.models.SystemPath` instance.

        :param path: Search path to prepend when searching, defaults to None
        :param path: str, optional
        :param bool system: Whether to use the running python by default instead of searching, defaults to False
        :param bool only_python: Whether to search only for python executables, defaults to False
        :param bool ignore_unsupported: Whether to ignore unsupported python versions, if False, an error is raised, defaults to True
        :return: A new :class:`pythonfinder.models.SystemPath` instance.
        :rtype: :class:`pythonfinder.models.SystemPath`
        """

        path_entries = defaultdict(PathEntry)
        paths = []
        if ignore_unsupported:
            os.environ["PYTHONFINDER_IGNORE_UNSUPPORTED"] = fs_str("1")
        if global_search:
            if "PATH" in os.environ:
                paths = os.environ["PATH"].split(os.pathsep)
        path_order = []  # type: List[str]
        if path:
            path_order = [path]
            path_instance = ensure_path(path)
            path_entries.update(
                {
                    path_instance.as_posix(): PathEntry.create(
                        path=path_instance.absolute(),
                        is_root=True,
                        only_python=only_python,
                    )
                }
            )
            paths = [path] + paths
        paths = [p for p in paths if not any(is_in_path(p, shim) for shim in SHIM_PATHS)]
        _path_objects = [ensure_path(p.strip('"')) for p in paths]
        path_entries.update(
            {
                p.as_posix(): PathEntry.create(
                    path=p.absolute(), is_root=True, only_python=only_python
                )
                for p in _path_objects
                if exists_and_is_accessible(p)
            }
        )
        instance = cls(
            paths=path_entries,
            path_order=path_order,
            only_python=only_python,
            system=system,
            global_search=global_search,
            ignore_unsupported=ignore_unsupported,
        )
        instance._run_setup()
        return instance

class VersionPath(SystemPath):
    base: Optional[Path] = None
    name: Optional[str] = None

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        # keep_untouched = (cached_property,)

    @validator('base', pre=True)
    def optional_instance_of_path(cls, value):
        if value is not None and not isinstance(value, Path):
            raise ValueError('The "base" attribute must be an instance of Path or None')
        return value

    @classmethod
    def create(cls, path, only_python=True, pythons=None, name=None):
        """Accepts a path to a base python version directory.

        Generates the version listings for it"""
        path = ensure_path(path)
        path_entries = defaultdict(PathEntry)
        bin_ = "{base}/bin"
        if path.as_posix().endswith(Path(bin_).name):
            path = path.parent
        bin_dir = ensure_path(bin_.format(base=path.as_posix()))
        if not name:
            name = path.name
        current_entry = PathEntry.create(
            bin_dir, is_root=True, only_python=True, pythons=pythons, name=name
        )
        path_entries[bin_dir.as_posix()] = current_entry
        return cls(name=name, base=bin_dir, paths=path_entries)
