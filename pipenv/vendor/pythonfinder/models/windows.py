# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import operator

from collections import defaultdict

import attr

from ..exceptions import InvalidPythonVersion
from ..utils import ensure_path
from .mixins import BaseFinder
from .path import PathEntry
from .python import PythonVersion, VersionMap


@attr.s
class WindowsFinder(BaseFinder):
    paths = attr.ib(default=attr.Factory(list))
    version_list = attr.ib(default=attr.Factory(list))
    versions = attr.ib()
    pythons = attr.ib()

    def find_all_python_versions(
        self,
        major=None,
        minor=None,
        patch=None,
        pre=None,
        dev=None,
        arch=None,
        name=None,
    ):
        version_matcher = operator.methodcaller(
            "matches",
            major=major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
            name=name,
        )
        py_filter = filter(
            None, filter(lambda c: version_matcher(c), self.version_list)
        )
        version_sort = operator.attrgetter("version_sort")
        return [c.comes_from for c in sorted(py_filter, key=version_sort, reverse=True)]

    def find_python_version(
        self,
        major=None,
        minor=None,
        patch=None,
        pre=None,
        dev=None,
        arch=None,
        name=None,
    ):
        return next(
            (
                v
                for v in self.find_all_python_versions(
                    major=major,
                    minor=minor,
                    patch=patch,
                    pre=pre,
                    dev=dev,
                    arch=arch,
                    name=None,
                )
            ),
            None,
        )

    @versions.default
    def get_versions(self):
        versions = defaultdict(PathEntry)
        from pythonfinder._vendor.pep514tools import environment as pep514env

        env_versions = pep514env.findall()
        path = None
        for version_object in env_versions:
            install_path = getattr(version_object.info, "install_path", None)
            if install_path is None:
                continue
            try:
                path = ensure_path(install_path.__getattr__(""))
            except AttributeError:
                continue
            try:
                py_version = PythonVersion.from_windows_launcher(version_object)
            except InvalidPythonVersion:
                continue
            self.version_list.append(py_version)
            base_dir = PathEntry.create(
                path,
                is_root=True,
                only_python=True,
                pythons={py_version.comes_from.path: py_version},
            )
            versions[py_version.version_tuple[:5]] = base_dir
            self.paths.append(base_dir)
        return versions

    @pythons.default
    def get_pythons(self):
        pythons = defaultdict()
        for version in self.version_list:
            _path = ensure_path(version.comes_from.path)
            pythons[_path.as_posix()] = version.comes_from
        return pythons

    @classmethod
    def create(cls):
        return cls()
