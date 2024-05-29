from __future__ import annotations

import dataclasses
import os
from collections import defaultdict
from dataclasses import field
from typing import (
    TYPE_CHECKING,
    Any,
    Generator,
    Iterator,
)

from ..exceptions import InvalidPythonVersion
from ..utils import (
    KNOWN_EXTS,
    ensure_path,
    expand_paths,
    filter_pythons,
    looks_like_python,
    path_is_known_executable,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .python import PythonVersion


@dataclasses.dataclass(unsafe_hash=True)
class PathEntry:
    is_root: bool = False
    name: str | None = None
    path: Path | None = None
    children_ref: dict[str, Any] = field(default_factory=dict)
    only_python: bool | None = False
    py_version_ref: Any | None = None
    pythons_ref: dict[str, Any] | None = field(
        default_factory=lambda: defaultdict(lambda: None)
    )
    is_dir_ref: bool | None = None
    is_executable_ref: bool | None = None
    is_python_ref: bool | None = None

    def __post_init__(self):
        if not self.children_ref:
            self._gen_children()

    def __str__(self) -> str:
        return f"{self.path}"

    def __lt__(self, other) -> bool:
        return self.path < other.path

    def __lte__(self, other) -> bool:
        return self.path <= other.path

    def __gt__(self, other) -> bool:
        return self.path > other.path

    def __gte__(self, other) -> bool:
        return self.path >= other.path

    def __eq__(self, other) -> bool:
        return self.path == other.path

    def which(self, name) -> PathEntry | None:
        """Search in this path for an executable.

        :param executable: The name of an executable to search for.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` instance.
        """

        valid_names = [name] + [
            f"{name}.{ext}".lower() if ext else f"{name}".lower() for ext in KNOWN_EXTS
        ]
        children = self.children
        found = None
        if self.path is not None:
            found = next(
                (
                    children[(self.path / child)]
                    for child in valid_names
                    if (self.path / child) in children
                ),
                None,
            )
        return found

    @property
    def as_python(self) -> PythonVersion:
        py_version = None
        if self.py_version_ref:
            return self.py_version_ref
        if not self.is_dir and self.is_python:
            from .python import PythonVersion

            try:
                py_version = PythonVersion.from_path(path=self, name=self.name)
            except (ValueError, InvalidPythonVersion):
                pass
        self.py_version_ref = py_version
        return self.py_version_ref

    @property
    def is_dir(self) -> bool:
        if self.is_dir_ref is None:
            try:
                ret_val = self.path.is_dir()
            except OSError:
                ret_val = False
            self.is_dir_ref = ret_val
        return self.is_dir_ref

    @is_dir.setter
    def is_dir(self, val) -> None:
        self.is_dir_ref = val

    @is_dir.deleter
    def is_dir(self) -> None:
        self.is_dir_ref = None

    @property
    def is_executable(self) -> bool:
        if self.is_executable_ref is None:
            if not self.path:
                self.is_executable_ref = False
            else:
                self.is_executable_ref = path_is_known_executable(self.path)
        return self.is_executable_ref

    @is_executable.setter
    def is_executable(self, val) -> None:
        self.is_executable_ref = val

    @is_executable.deleter
    def is_executable(self) -> None:
        self.is_executable_ref = None

    @property
    def is_python(self) -> bool:
        if self.is_python_ref is None:
            if not self.path:
                self.is_python_ref = False
            else:
                self.is_python_ref = self.is_executable and (
                    looks_like_python(self.path.name)
                )
        return self.is_python_ref

    @is_python.setter
    def is_python(self, val) -> None:
        self.is_python_ref = val

    @is_python.deleter
    def is_python(self) -> None:
        self.is_python_ref = None

    def get_py_version(self):
        from ..environment import IGNORE_UNSUPPORTED

        if self.is_dir:
            return None
        if self.is_python:
            py_version = None
            from .python import PythonVersion

            try:
                py_version = PythonVersion.from_path(path=self, name=self.name)
            except (InvalidPythonVersion, ValueError):
                py_version = None
            except Exception:
                if not IGNORE_UNSUPPORTED:
                    raise
            return py_version
        return None

    @property
    def py_version(self) -> PythonVersion | None:
        if not self.py_version_ref:
            py_version = self.get_py_version()
            self.py_version_ref = py_version
        else:
            py_version = self.py_version_ref
        return py_version

    def _iter_pythons(self) -> Iterator:
        if self.is_dir:
            for entry in self.children.values():
                if entry is None:
                    continue
                elif entry.is_dir:
                    for python in entry._iter_pythons():
                        yield python
                elif entry.is_python and entry.as_python is not None:
                    yield entry
        elif self.is_python and self.as_python is not None:
            yield self

    @property
    def pythons(self) -> dict[str | Path, PathEntry]:
        if not self.pythons_ref:
            self.pythons_ref = defaultdict(PathEntry)
            for python in self._iter_pythons():
                python_path = python.path
                self.pythons_ref[python_path] = python
        return self.pythons_ref

    def __iter__(self) -> Iterator:
        yield from self.children.values()

    def __next__(self) -> Generator:
        return next(iter(self))

    def next(self) -> Generator:
        return self.__next__()

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
        """

        call_method = "find_all_python_versions" if self.is_dir else "find_python_version"

        def sub_finder(obj):
            return getattr(obj, call_method)(major, minor, patch, pre, dev, arch, name)

        if not self.is_dir:
            return sub_finder(self)

        unnested = [sub_finder(path) for path in expand_paths(self)]

        def version_sort(path_entry):
            return path_entry.as_python.version_sort

        unnested = [p for p in unnested if p is not None and p.as_python is not None]
        paths = sorted(unnested, key=version_sort, reverse=True)
        return list(paths)

    def find_python_version(
        self,
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
    ) -> PathEntry | None:
        """Search or self for the specified Python version and return the first match.

        :param major: Major version number.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :param str name: The name of a python version, e.g. ``anaconda3-5.3.0``
        :returns: A :class:`~pythonfinder.models.PathEntry` instance matching the version requested.
        """

        def version_matcher(py_version):
            return py_version.matches(
                major, minor, patch, pre, dev, arch, python_name=name
            )

        if not self.is_dir:
            if self.is_python and self.as_python and version_matcher(self.py_version):
                return self

        for entry in self._iter_pythons():
            if entry is not None and entry.as_python is not None:
                if version_matcher(entry.as_python):
                    return entry

    def _filter_children(self) -> Iterator[Path]:
        if not os.access(str(self.path), os.R_OK):
            return iter([])
        if self.only_python:
            children = filter_pythons(self.path)
        else:
            children = self.path.iterdir()
        return children

    def _gen_children(self):
        if self.is_dir and self.is_root and self.path is not None:
            # Assuming _filter_children returns an iterator over child paths
            for child_path in self._filter_children():
                pass_name = self.name != self.path.name
                pass_args = {"is_root": False, "only_python": self.only_python}
                if pass_name:
                    if self.name is not None and isinstance(self.name, str):
                        pass_args["name"] = self.name
                    elif self.path is not None and isinstance(self.path.name, str):
                        pass_args["name"] = self.path.name

                try:
                    entry = PathEntry.create(path=child_path, **pass_args)
                    self.children_ref[child_path] = entry
                except (InvalidPythonVersion, ValueError):
                    continue  # Or handle as needed

    @property
    def children(self) -> dict[str, PathEntry]:
        return self.children_ref

    @classmethod
    def create(
        cls,
        path: str | Path,
        is_root: bool = False,
        only_python: bool = False,
        pythons: dict[str, PythonVersion] | None = None,
        name: str | None = None,
    ) -> PathEntry:
        """Helper method for creating new :class:`PathEntry` instances.

        :param str path: Path to the specified location.
        :param bool is_root: Whether this is a root from the environment PATH variable, defaults to False
        :param bool only_python: Whether to search only for python executables, defaults to False
        :param dict pythons: A dictionary of existing python objects (usually from a finder), defaults to None
        :param str name: Name of the python version, e.g. ``anaconda3-5.3.0``
        :return: A new instance of the class.
        """
        target = ensure_path(path)
        guessed_name = False
        if not name:
            guessed_name = True
            name = target.name
        creation_args = {
            "path": target,
            "is_root": is_root,
            "only_python": only_python,
            "name": name,
        }
        if pythons:
            creation_args["pythons"] = pythons
        _new = cls(**creation_args)
        if pythons and only_python:
            children = {}
            child_creation_args = {"is_root": False, "only_python": only_python}
            if not guessed_name:
                child_creation_args["name"] = _new.name
            for pth, python in pythons.items():
                pth = ensure_path(pth)
                children[str(path)] = PathEntry(
                    py_version=python, path=pth, **child_creation_args
                )
            _new.children_ref = children
        return _new
