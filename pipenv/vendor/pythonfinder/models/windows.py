# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import operator
from collections import defaultdict

import pipenv.vendor.attr as attr

from ..environment import MYPY_RUNNING
from ..exceptions import InvalidPythonVersion
from ..utils import ensure_path
from .mixins import BaseFinder
from .path import PathEntry
from .python import PythonVersion, VersionMap

if MYPY_RUNNING:
    from typing import Any, DefaultDict, List, Optional, Tuple, Type, TypeVar, Union

    FinderType = TypeVar("FinderType")


@attr.s
class WindowsFinder(BaseFinder):
    paths = attr.ib(default=attr.Factory(list), type=list)
    version_list = attr.ib(default=attr.Factory(list), type=list)
    _versions = attr.ib()  # type: DefaultDict[Tuple, PathEntry]
    _pythons = attr.ib()  # type: DefaultDict[str, PathEntry]

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
        # type (...) -> List[PathEntry]
        version_matcher = operator.methodcaller(
            "matches", major, minor, patch, pre, dev, arch, python_name=name
        )
        pythons = [py for py in self.version_list if version_matcher(py)]
        version_sort = operator.attrgetter("version_sort")
        return [
            c.comes_from
            for c in sorted(pythons, key=version_sort, reverse=True)
            if c.comes_from
        ]

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

    @_versions.default
    def get_versions(self):
        # type: () -> DefaultDict[Tuple, PathEntry]
        versions = defaultdict(PathEntry)  # type: DefaultDict[Tuple, PathEntry]
        from pipenv.vendor.pythonfinder._vendor.pep514tools import environment as pep514env

        env_versions = pep514env.findall()
        path = None
        for version_object in env_versions:
            install_path = getattr(version_object.info, "install_path", None)
            name = getattr(version_object, "tag", None)
            company = getattr(version_object, "company", None)
            if install_path is None:
                continue
            try:
                path = ensure_path(install_path.__getattr__(""))
            except AttributeError:
                continue
            if not path.exists():
                continue
            try:
                py_version = PythonVersion.from_windows_launcher(
                    version_object, name=name, company=company
                )
            except (InvalidPythonVersion, AttributeError):
                continue
            if py_version is None:
                continue
            self.version_list.append(py_version)
            python_path = (
                py_version.comes_from.path
                if py_version.comes_from
                else py_version.executable
            )
            python_kwargs = {python_path: py_version} if python_path is not None else {}
            base_dir = PathEntry.create(
                path, is_root=True, only_python=True, pythons=python_kwargs
            )
            versions[py_version.version_tuple[:5]] = base_dir
            self.paths.append(base_dir)
        return versions

    @property
    def versions(self):
        # type: () -> DefaultDict[Tuple, PathEntry]
        if not self._versions:
            self._versions = self.get_versions()
        return self._versions

    @_pythons.default
    def get_pythons(self):
        # type: () -> DefaultDict[str, PathEntry]
        pythons = defaultdict()  # type: DefaultDict[str, PathEntry]
        for version in self.version_list:
            _path = ensure_path(version.comes_from.path)
            pythons[_path.as_posix()] = version.comes_from
        return pythons

    @property
    def pythons(self):
        # type: () -> DefaultDict[str, PathEntry]
        return self._pythons

    @pythons.setter
    def pythons(self, value):
        # type: (DefaultDict[str, PathEntry]) -> None
        self._pythons = value

    @classmethod
    def create(cls, *args, **kwargs):
        # type: (Type[FinderType], Any, Any) -> FinderType
        return cls()
