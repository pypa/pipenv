from __future__ import annotations

import dataclasses
import errno
import operator
import os
import sys
from collections import defaultdict
from dataclasses import field
from functools import cached_property
from itertools import chain
from pathlib import Path
from typing import (
    Any,
    DefaultDict,
    Generator,
    Iterator,
)

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
    parse_asdf_version_order,
    parse_pyenv_version_order,
    resolve_path,
)
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


@dataclasses.dataclass(unsafe_hash=True)
class SystemPath:
    global_search: bool = True
    paths: dict[str, PythonFinder | PathEntry] = field(
        default_factory=lambda: defaultdict(PathEntry)
    )
    executables_tracking: list[PathEntry] = field(default_factory=list)
    python_executables_tracking: dict[str, PathEntry] = field(
        default_factory=dict, init=False
    )
    path_order: list[str] = field(default_factory=list)
    python_version_dict: dict[tuple, Any] = field(
        default_factory=lambda: defaultdict(list)
    )
    version_dict_tracking: dict[tuple, list[PathEntry]] = field(
        default_factory=lambda: defaultdict(list)
    )
    only_python: bool = False
    pyenv_finder: PythonFinder | None = None
    asdf_finder: PythonFinder | None = None
    system: bool = False
    ignore_unsupported: bool = False
    finders_dict: dict[str, PythonFinder] = field(default_factory=dict)

    def __post_init__(self):
        # Initialize python_executables_tracking
        python_executables = {}
        for child in self.paths.values():
            if child.pythons:
                python_executables.update(dict(child.pythons))
        for _, finder in self.finders_dict.items():
            if finder.pythons:
                python_executables.update(dict(finder.pythons))
        self.python_executables_tracking = python_executables

        self.python_version_dict = defaultdict(list)
        self.pyenv_finder = self.pyenv_finder or None
        self.asdf_finder = self.asdf_finder or None
        self.path_order = [str(p) for p in self.path_order] or []
        self.finders_dict = self.finders_dict or {}

        # The part with 'paths' seems to be setting up 'executables'
        if self.paths:
            self.executables_tracking = [
                child
                for path_entry in self.paths.values()
                for child in path_entry.children_ref.values()
                if child.is_executable
            ]

    def _register_finder(self, finder_name, finder):
        if finder_name not in self.finders_dict:
            self.finders_dict[finder_name] = finder
        return self

    @property
    def finders(self) -> list[str]:
        return [k for k in self.finders_dict.keys()]

    @staticmethod
    def check_for_pyenv():
        return PYENV_INSTALLED or os.path.exists(resolve_path(PYENV_ROOT))

    @staticmethod
    def check_for_asdf():
        return ASDF_INSTALLED or os.path.exists(resolve_path(ASDF_DATA_DIR))

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

    def _handle_virtualenv_and_system_paths(self):
        venv = os.environ.get("VIRTUAL_ENV")
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        if venv:
            venv_path = Path(venv).resolve()
            venv_bin_path = venv_path / bin_dir
            if venv_bin_path.exists() and (self.system or self.global_search):
                self.path_order = [str(venv_bin_path), *self.path_order]
                self.paths[str(venv_bin_path)] = self.get_path(venv_bin_path)

        if self.system:
            syspath_bin = Path(sys.executable).resolve().parent
            if (syspath_bin / bin_dir).exists():
                syspath_bin = syspath_bin / bin_dir
            if str(syspath_bin) not in self.path_order:
                self.path_order = [str(syspath_bin), *self.path_order]
                self.paths[str(syspath_bin)] = PathEntry.create(
                    path=syspath_bin, is_root=True, only_python=False
                )

    def _run_setup(self) -> SystemPath:
        path_order = self.path_order[:]
        if self.global_search and "PATH" in os.environ:
            path_order += os.environ["PATH"].split(os.pathsep)
        path_order = list(dedup(path_order))
        path_instances = [
            Path(p.strip('"')).resolve()
            for p in path_order
            if exists_and_is_accessible(Path(p.strip('"')).resolve())
        ]

        # Update paths with PathEntry objects
        self.paths.update(
            {
                str(p): PathEntry.create(
                    path=p, is_root=True, only_python=self.only_python
                )
                for p in path_instances
            }
        )

        # Update path_order to use absolute paths
        self.path_order = [str(p) for p in path_instances]

        # Handle virtual environment and system paths
        self._handle_virtualenv_and_system_paths()

        return self

    def _get_last_instance(self, path) -> int:
        reversed_paths = reversed(self.path_order)
        paths = [resolve_path(p) for p in reversed_paths]
        normalized_target = resolve_path(path)
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
        path_order = before_path + [str(p) for p in paths] + after_path
        self.path_order = path_order
        return self

    def _remove_shims(self):
        path_copy = [p for p in self.path_order[:]]
        new_order = []
        for current_path in path_copy:
            if not current_path.endswith("shims"):
                normalized = resolve_path(current_path)
                new_order.append(normalized)
        new_order = [ensure_path(p) for p in new_order]
        self.path_order = new_order

    def _remove_path(self, path) -> SystemPath:
        path_copy = [p for p in reversed(self.path_order[:])]
        new_order = []
        target = resolve_path(path)
        path_map = {resolve_path(pth): pth for pth in self.paths.keys()}
        if target in path_map:
            del self.paths[path_map[target]]
        for current_path in path_copy:
            normalized = resolve_path(current_path)
            if normalized != target:
                new_order.append(normalized)
        new_order = [str(p) for p in reversed(new_order)]
        self.path_order = new_order
        return self

    def _setup_asdf(self) -> SystemPath:
        if "asdf" in self.finders and self.asdf_finder is not None:
            return self

        os_path = os.environ["PATH"].split(os.pathsep)
        asdf_data_dir = Path(ASDF_DATA_DIR)
        asdf_finder = PythonFinder.create(
            root=asdf_data_dir,
            ignore_unsupported=True,
            sort_function=parse_asdf_version_order,
            version_glob_path="installs/python/*",
        )
        asdf_index = None
        try:
            asdf_index = self._get_last_instance(asdf_data_dir)
        except ValueError:
            asdf_index = 0 if is_in_path(next(iter(os_path), ""), asdf_data_dir) else -1
        if asdf_index is None:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return self
        # * These are the root paths for the finder
        _ = [p for p in asdf_finder.roots]
        self._slice_in_paths(asdf_index, [str(asdf_finder.root)])
        self.paths[str(asdf_finder.root)] = asdf_finder
        self.paths.update(
            {str(root): asdf_finder.roots[root] for root in asdf_finder.roots}
        )
        self.asdf_finder = asdf_finder
        self._remove_path(asdf_data_dir / "shims")
        self._register_finder("asdf", asdf_finder)
        return self

    def _setup_pyenv(self) -> SystemPath:
        if "pyenv" in self.finders and self.pyenv_finder is not None:
            return self

        os_path = os.environ["PATH"].split(os.pathsep)
        pyenv_root = Path(PYENV_ROOT)
        pyenv_finder = PythonFinder.create(
            root=pyenv_root,
            sort_function=parse_pyenv_version_order,
            version_glob_path="versions/*",
            ignore_unsupported=self.ignore_unsupported,
        )
        try:
            pyenv_index = self._get_last_instance(pyenv_root)
        except ValueError:
            pyenv_index = 0 if is_in_path(next(iter(os_path), ""), pyenv_root) else -1
        if pyenv_index is None:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return self
        # * These are the root paths for the finder
        _ = [p for p in pyenv_finder.roots]
        self._slice_in_paths(pyenv_index, [str(pyenv_finder.root)])
        self.paths[str(pyenv_finder.root)] = pyenv_finder
        self.paths.update(
            {str(root): pyenv_finder.roots[root] for root in pyenv_finder.roots}
        )
        self.pyenv_finder = pyenv_finder
        self._remove_shims()
        self._register_finder("pyenv", pyenv_finder)
        return self

    def get_path(self, path) -> PythonFinder | PathEntry:
        if path is None:
            raise TypeError("A path must be provided in order to generate a path entry.")
        path_str = path if isinstance(path, str) else str(path.absolute())
        _path = self.paths.get(path_str)
        if not _path:
            _path = self.paths.get(path_str)
        if not _path and path_str in self.path_order and path.exists():
            _path = PathEntry.create(
                path=path.absolute(), is_root=True, only_python=self.only_python
            )
            self.paths[path_str] = _path
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
            if not path:
                continue
            python_version = finder(path)
            if python_version:
                yield python_version

    def _get_all_pythons(self, finder) -> Iterator:
        for python in self._filter_paths(finder):
            if python:
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

        if sort_by_path:
            found_version = self._find_version_by_path(
                sub_finder,
                alternate_sub_finder,
                name,
                minor,
                patch,
                pre,
                dev,
                arch,
                major,
            )
            if found_version:
                return found_version

        ver = next(iter(self.get_pythons(sub_finder)), None)
        if not ver and name and not any([minor, patch, pre, dev, arch, major]):
            ver = next(iter(self.get_pythons(alternate_sub_finder)), None)

        self._update_python_version_dict(ver)

        return ver

    def _find_version_by_path(self, sub_finder, alternate_sub_finder, name, *args):
        paths = [self.get_path(k) for k in self.path_order]
        for path in paths:
            found_version = sub_finder(path)
            if found_version:
                return found_version
        if name and not any(args):
            for path in paths:
                found_version = alternate_sub_finder(path)
                if found_version:
                    return found_version
        return None

    def _update_python_version_dict(self, ver):
        if ver:
            version_key = ver.as_python.version_tuple[:5]
            if version_key in self.python_version_dict:
                self.python_version_dict[version_key].append(ver)
            else:
                self.python_version_dict[version_key] = [ver]

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
        path_order = [str(path)]
        if path:
            path_order = [path]
            path_instance = ensure_path(path)
            path_entries.update(
                {
                    path_instance: PathEntry.create(
                        path=path_instance.resolve(),
                        is_root=True,
                        only_python=only_python,
                    )
                }
            )
            paths = [path, *paths]
        _path_objects = [ensure_path(p) for p in paths]
        path_entries.update(
            {
                str(p): PathEntry.create(
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
