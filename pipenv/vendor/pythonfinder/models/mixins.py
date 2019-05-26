# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import abc
import operator
from collections import defaultdict

import attr
import six
from cached_property import cached_property
from vistir.compat import fs_str

from ..environment import MYPY_RUNNING
from ..exceptions import InvalidPythonVersion
from ..utils import (
    KNOWN_EXTS,
    Sequence,
    expand_paths,
    looks_like_python,
    path_is_known_executable,
)

if MYPY_RUNNING:
    from .path import PathEntry
    from .python import PythonVersion
    from typing import (
        Optional,
        Union,
        Any,
        Dict,
        Iterator,
        List,
        DefaultDict,
        Generator,
        Tuple,
        TypeVar,
        Type,
    )
    from vistir.compat import Path

    BaseFinderType = TypeVar("BaseFinderType")


@attr.s
class BasePath(object):
    path = attr.ib(default=None)  # type: Path
    _children = attr.ib(default=attr.Factory(dict))  # type: Dict[str, PathEntry]
    only_python = attr.ib(default=False)  # type: bool
    name = attr.ib(type=str)
    _py_version = attr.ib(default=None)  # type: Optional[PythonVersion]
    _pythons = attr.ib(
        default=attr.Factory(defaultdict)
    )  # type: DefaultDict[str, PathEntry]

    def __str__(self):
        # type: () -> str
        return fs_str("{0}".format(self.path.as_posix()))

    def which(self, name):
        # type: (str) -> Optional[PathEntry]
        """Search in this path for an executable.

        :param executable: The name of an executable to search for.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` instance.
        """

        valid_names = [name] + [
            "{0}.{1}".format(name, ext).lower() if ext else "{0}".format(name).lower()
            for ext in KNOWN_EXTS
        ]
        children = self.children
        found = None
        if self.path is not None:
            found = next(
                (
                    children[(self.path / child).as_posix()]
                    for child in valid_names
                    if (self.path / child).as_posix() in children
                ),
                None,
            )
        return found

    def __del__(self):
        for key in ["as_python", "is_dir", "is_python", "is_executable", "py_version"]:
            if key in self.__dict__:
                del self.__dict__[key]
        self._children = {}
        for key in list(self._pythons.keys()):
            del self._pythons[key]
        self._pythons = None
        self._py_version = None
        self.path = None

    @property
    def children(self):
        # type: () -> Dict[str, PathEntry]
        if not self.is_dir:
            return {}
        return self._children

    @cached_property
    def as_python(self):
        # type: () -> PythonVersion
        py_version = None
        if self.py_version:
            return self.py_version
        if not self.is_dir and self.is_python:
            try:
                from .python import PythonVersion

                py_version = PythonVersion.from_path(  # type: ignore
                    path=self, name=self.name
                )
            except (ValueError, InvalidPythonVersion):
                pass
        if py_version is None:
            pass
        return py_version  # type: ignore

    @name.default
    def get_name(self):
        # type: () -> Optional[str]
        if self.path:
            return self.path.name
        return None

    @cached_property
    def is_dir(self):
        # type: () -> bool
        if not self.path:
            return False
        try:
            ret_val = self.path.is_dir()
        except OSError:
            ret_val = False
        return ret_val

    @cached_property
    def is_executable(self):
        # type: () -> bool
        if not self.path:
            return False
        return path_is_known_executable(self.path)

    @cached_property
    def is_python(self):
        # type: () -> bool
        if not self.path:
            return False
        return self.is_executable and (looks_like_python(self.path.name))

    def get_py_version(self):
        # type: () -> Optional[PythonVersion]
        from ..environment import IGNORE_UNSUPPORTED

        if self.is_dir:
            return None
        if self.is_python:
            py_version = None
            from .python import PythonVersion

            try:
                py_version = PythonVersion.from_path(  # type: ignore
                    path=self, name=self.name
                )
            except (InvalidPythonVersion, ValueError):
                py_version = None
            except Exception:
                if not IGNORE_UNSUPPORTED:
                    raise
            return py_version
        return None

    @cached_property
    def py_version(self):
        # type: () -> Optional[PythonVersion]
        if not self._py_version:
            py_version = self.get_py_version()
            self._py_version = py_version
        else:
            py_version = self._py_version
        return py_version

    def _iter_pythons(self):
        # type: () -> Iterator
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
            yield self  # type: ignore

    @property
    def pythons(self):
        # type: () -> DefaultDict[Union[str, Path], PathEntry]
        if not self._pythons:
            from .path import PathEntry

            self._pythons = defaultdict(PathEntry)
            for python in self._iter_pythons():
                python_path = python.path.as_posix()  # type: ignore
                self._pythons[python_path] = python
        return self._pythons

    def __iter__(self):
        # type: () -> Iterator
        for entry in self.children.values():
            yield entry

    def __next__(self):
        # type: () -> Generator
        return next(iter(self))

    def next(self):
        # type: () -> Generator
        return self.__next__()

    def find_all_python_versions(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
    ):
        # type: (...) -> List[PathEntry]
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

        call_method = "find_all_python_versions" if self.is_dir else "find_python_version"
        sub_finder = operator.methodcaller(
            call_method, major, minor, patch, pre, dev, arch, name
        )
        if not self.is_dir:
            return sub_finder(self)
        unnested = [sub_finder(path) for path in expand_paths(self)]
        version_sort = operator.attrgetter("as_python.version_sort")
        unnested = [p for p in unnested if p is not None and p.as_python is not None]
        paths = sorted(unnested, key=version_sort, reverse=True)
        return list(paths)

    def find_python_version(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
    ):
        # type: (...) -> Optional[PathEntry]
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

        version_matcher = operator.methodcaller(
            "matches", major, minor, patch, pre, dev, arch, python_name=name
        )
        if not self.is_dir:
            if self.is_python and self.as_python and version_matcher(self.py_version):
                return self  # type: ignore

        matching_pythons = [
            [entry, entry.as_python.version_sort]
            for entry in self._iter_pythons()
            if (
                entry is not None
                and entry.as_python is not None
                and version_matcher(entry.py_version)
            )
        ]
        results = sorted(matching_pythons, key=operator.itemgetter(1, 0), reverse=True)
        return next(iter(r[0] for r in results if r is not None), None)


@six.add_metaclass(abc.ABCMeta)
class BaseFinder(object):
    def __init__(self):
        #: Maps executable paths to PathEntries
        from .path import PathEntry

        self._pythons = defaultdict(PathEntry)  # type: DefaultDict[str, PathEntry]
        self._versions = defaultdict(PathEntry)  # type: Dict[Tuple, PathEntry]

    def get_versions(self):
        # type: () -> DefaultDict[Tuple, PathEntry]
        """Return the available versions from the finder"""
        raise NotImplementedError

    @classmethod
    def create(cls, *args, **kwargs):
        # type: (Any, Any) -> BaseFinderType
        raise NotImplementedError

    @property
    def version_paths(self):
        # type: () -> Any
        return self._versions.values()

    @property
    def expanded_paths(self):
        # type: () -> Any
        return (p.paths.values() for p in self.version_paths)

    @property
    def pythons(self):
        # type: () -> DefaultDict[str, PathEntry]
        return self._pythons

    @pythons.setter
    def pythons(self, value):
        # type: (DefaultDict[str, PathEntry]) -> None
        self._pythons = value
