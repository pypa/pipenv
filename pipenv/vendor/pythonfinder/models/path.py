from __future__ import annotations

import errno
import operator
import os
import sys
from collections import ChainMap, defaultdict
from itertools import chain
from pathlib import Path
from typing import (
    Any,
    DefaultDict,
    Dict,
    Generator,
    Iterator,
    List,
    Optional,
    Tuple,
    Union,
)

from pipenv.patched.pip._vendor.pyparsing.core import cached_property
from pipenv.vendor.pydantic import Field, root_validator

from ..environment import (
    ASDF_DATA_DIR,
    ASDF_INSTALLED,
    PYENV_INSTALLED,
    PYENV_ROOT,
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
from .common import FinderBaseModel
from .mixins import PathEntry
from .python import PythonFinder


def exists_and_is_accessible(path):
    try:
        return path.exists()
    except PermissionError as pe:
        if pe.errno == errno.EACCES:  # Permission denied
            return False
        else:
            raise


class SystemPath(FinderBaseModel):
    global_search: bool = True
    paths: Dict[str, Union[PythonFinder, PathEntry]] = Field(
        default_factory=lambda: defaultdict(PathEntry)
    )
    executables_tracking: List[PathEntry] = Field(default_factory=lambda: list())
    python_executables_tracking: Dict[str, PathEntry] = Field(
        default_factory=lambda: dict()
    )
    path_order: List[str] = Field(default_factory=lambda: list())
    python_version_dict: Dict[Tuple, Any] = Field(
        default_factory=lambda: defaultdict(list)
    )
    version_dict_tracking: Dict[Tuple, List[PathEntry]] = Field(
        default_factory=lambda: defaultdict(list)
    )
    only_python: bool = False
    pyenv_finder: Optional[PythonFinder] = None
    asdf_finder: Optional[PythonFinder] = None
    system: bool = False
    ignore_unsupported: bool = False
    finders_dict: Dict[str, PythonFinder] = Field(default_factory=lambda: dict())

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
        self.python_executables_tracking = python_executables

    @root_validator(pre=True)
    def set_defaults(cls, values):
        values["python_version_dict"] = defaultdict(list)
        values["pyenv_finder"] = None
        values["asdf_finder"] = None
        values["path_order"] = []
        values["_finders"] = {}
        values["paths"] = defaultdict(PathEntry)
        paths = values.get("paths")
        if paths:
            values["executables"] = [
                p
                for p in ChainMap(
                    *(child.children_ref.values() for child in paths.values())
                )
                if p.is_executable
            ]
        return values

    def _register_finder(self, finder_name, finder):
        if finder_name not in self.finders_dict:
            self.finders_dict[finder_name] = finder
        return self

    @property
    def finders(self) -> list[str]:
        return [k for k in self.finders_dict.keys()]

    @staticmethod
    def check_for_pyenv():
        return PYENV_INSTALLED or os.path.exists(normalize_path(PYENV_ROOT))

    @staticmethod
    def check_for_asdf():
        return ASDF_INSTALLED or os.path.exists(normalize_path(ASDF_DATA_DIR))

    @property
    def executables(self) -> list[PathEntry]:
        if self.executables_tracking:
            return self.executables_tracking
        self.executables_tracking = [
            p
            for p in chain(
                *(child.children_ref.values() for child in self.paths.values())
            )
            if p.is_executable
        ]
        return self.executables_tracking

    @cached_property
    def python_executables(self) -> dict[str, PathEntry]:
        python_executables = {}
        for child in self.paths.values():
            if child.pythons:
                python_executables.update(dict(child.pythons))
        for _, finder in self.__finders.items():
            if finder.pythons:
                python_executables.update(dict(finder.pythons))
        self.python_executables_tracking = python_executables
        return self.python_executables_tracking

    @cached_property
    def version_dict(self) -> DefaultDict[tuple, list[PathEntry]]:
        self.version_dict_tracking = defaultdict(list)
        for _finder_name, finder in self.finders_dict.items():
            for version, entry in finder.versions.items():
                if entry not in self.version_dict_tracking[version] and entry.is_python:
                    self.version_dict_tracking[version].append(entry)
        for _, entry in self.python_executables.items():
            version = entry.as_python
            if not version:
                continue
            if not isinstance(version, tuple):
                version = version.version_tuple
            if version and entry not in self.version_dict_tracking[version]:
                self.version_dict_tracking[version].append(entry)
        return self.version_dict_tracking

    def _run_setup(self) -> SystemPath:
        path_order = self.path_order[:]
        if self.global_search and "PATH" in os.environ:
            path_order = path_order + os.environ["PATH"].split(os.pathsep)
        path_order = list(dedup(path_order))
        path_instances = [ensure_path(p.strip('"')) for p in path_order]
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
        #: slice in pyenv
        if self.check_for_pyenv() and "pyenv" not in self.finders:
            self._setup_pyenv()
        #: slice in asdf
        if self.check_for_asdf() and "asdf" not in self.finders:
            self._setup_asdf()
        venv = os.environ.get("VIRTUAL_ENV")
        if venv:
            venv = ensure_path(venv)
        if os.name == "nt":
            bin_dir = "Scripts"
        else:
            bin_dir = "bin"
        if venv and (self.system or self.global_search):
            path_order = [(venv / bin_dir).as_posix(), *self.path_order]
            self.path_order = path_order
            self.paths[venv] = self.get_path(venv.joinpath(bin_dir))
        if self.system:
            syspath = Path(sys.executable)
            syspath_bin = syspath.parent
            if syspath_bin.name != bin_dir and syspath_bin.joinpath(bin_dir).exists():
                syspath_bin = syspath_bin / bin_dir
            path_order = [syspath_bin.as_posix(), *self.path_order]
            self.paths[syspath_bin] = PathEntry.create(
                path=syspath_bin, is_root=True, only_python=False
            )
            self.path_order = path_order
        return self

    def _get_last_instance(self, path) -> int:
        reversed_paths = reversed(self.path_order)
        paths = [normalize_path(p) for p in reversed_paths]
        normalized_target = normalize_path(path)
        last_instance = next(iter(p for p in paths if normalized_target in p), None)
        if last_instance is None:
            raise ValueError(f"No instance found on path for target: {path!s}")
        path_index = self.path_order.index(last_instance)
        return path_index

    def _slice_in_paths(self, start_idx, paths) -> SystemPath:
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
        return self

    def _remove_shims(self):
        path_copy = [p for p in self.path_order[:]]
        new_order = []
        for current_path in path_copy:
            if not current_path.endswith("shims"):
                normalized = normalize_path(current_path)
                new_order.append(normalized)
        new_order = [ensure_path(p).as_posix() for p in new_order]
        self.path_order = new_order

    def _remove_path(self, path) -> SystemPath:
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

    def _setup_asdf(self) -> SystemPath:
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

    def _setup_pyenv(self) -> SystemPath:
        if "pyenv" in self.finders and self.pyenv_finder is not None:
            return self

        os_path = os.environ["PATH"].split(os.pathsep)

        pyenv_finder = PythonFinder.create(
            root=PYENV_ROOT,
            sort_function=parse_pyenv_version_order,
            version_glob_path="versions/*",
            ignore_unsupported=self.ignore_unsupported,
        )
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
        self._remove_shims()
        self._register_finder("pyenv", pyenv_finder)
        return self

    def get_path(self, path) -> PythonFinder | PathEntry:
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
            raise ValueError(f"Path not found or generated: {path!r}")
        return _path

    def _get_paths(self) -> Generator[PythonFinder | PathEntry, None, None]:
        for path in self.path_order:
            try:
                entry = self.get_path(path)
            except ValueError:
                continue
            else:
                yield entry

    @cached_property
    def path_entries(self) -> list[PythonFinder | PathEntry]:
        paths = list(self._get_paths())
        return paths

    def find_all(self, executable) -> list[PathEntry | PythonFinder]:
        """
        Search the path for an executable. Return all copies.

        :param executable: Name of the executable
        :type executable: str
        :returns: List[PathEntry]
        """

        sub_which = operator.methodcaller("which", executable)
        filtered = (sub_which(self.get_path(k)) for k in self.path_order)
        return list(filtered)

    def which(self, executable) -> PathEntry | None:
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
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
    ) -> list[PathEntry]:
        def sub_finder(obj):
            return obj.find_all_python_versions(major, minor, patch, pre, dev, arch, name)

        alternate_sub_finder = None
        if major and not (minor or patch or pre or dev or arch or name):

            def alternate_sub_finder(obj):
                return obj.find_all_python_versions(
                    None, None, None, None, None, None, major
                )

        values = list(self.get_pythons(sub_finder))
        if not values and alternate_sub_finder is not None:
            values = list(self.get_pythons(alternate_sub_finder))

        return values

    def find_python_version(
        self,
        major: str | int | None = None,
        minor: str | int | None = None,
        patch: str | int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
        sort_by_path: bool = False,
    ) -> PathEntry:
        def sub_finder(obj):
            return obj.find_python_version(major, minor, patch, pre, dev, arch, name)

        def alternate_sub_finder(obj):
            return obj.find_all_python_versions(None, None, None, None, None, None, name)

        major, minor, patch, name = split_version_and_name(major, minor, patch, name)
        if major and minor and patch:
            _tuple_pre = pre if pre is not None else False
            _tuple_dev = dev if dev is not None else False

        if sort_by_path:
            paths = [self.get_path(k) for k in self.path_order]
            for path in paths:
                found_version = sub_finder(path)
                if found_version:
                    return found_version
            if name and not (minor or patch or pre or dev or arch or major):
                for path in paths:
                    found_version = alternate_sub_finder(path)
                    if found_version:
                        return found_version

        ver = next(iter(self.get_pythons(sub_finder)), None)
        if not ver and name and not (minor or patch or pre or dev or arch or major):
            ver = next(iter(self.get_pythons(alternate_sub_finder)), None)

        if ver:
            if ver.as_python.version_tuple[:5] in self.python_version_dict:
                self.python_version_dict[ver.as_python.version_tuple[:5]].append(ver)
            else:
                self.python_version_dict[ver.as_python.version_tuple[:5]] = [ver]

        return ver

    @classmethod
    def create(
        cls,
        path: str | None = None,
        system: bool = False,
        only_python: bool = False,
        global_search: bool = True,
        ignore_unsupported: bool = True,
    ) -> SystemPath:
        """Create a new :class:`pythonfinder.models.SystemPath` instance.

        :param path: Search path to prepend when searching, defaults to None
        :param path: str, optional
        :param bool system: Whether to use the running python by default instead of searching, defaults to False
        :param bool only_python: Whether to search only for python executables, defaults to False
        :param bool ignore_unsupported: Whether to ignore unsupported python versions, if False, an error is raised, defaults to True
        :return: A new :class:`pythonfinder.models.SystemPath` instance.
        """

        path_entries = defaultdict(PathEntry)
        paths = []
        if ignore_unsupported:
            os.environ["PYTHONFINDER_IGNORE_UNSUPPORTED"] = "1"
        if global_search:
            if "PATH" in os.environ:
                paths = os.environ["PATH"].split(os.pathsep)
        path_order = []
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
            paths = [path, *paths]
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
