# -*- coding=utf-8 -*-
import attr
import operator
from collections import defaultdict
from . import BaseFinder
from .path import PathEntry
from .python import PythonVersion
from ..utils import ensure_path


@attr.s
class WindowsFinder(BaseFinder):
    paths = attr.ib(default=attr.Factory(list))
    version_list = attr.ib(default=attr.Factory(list))
    versions = attr.ib()

    def find_python_version(self, major, minor=None, patch=None, pre=None, dev=None):
        version_matcher = operator.methodcaller(
            "matches", major, minor=minor, patch=patch, pre=pre, dev=dev
        )
        py_filter = filter(
            None, filter(lambda c: version_matcher(c), self.version_list)
        )
        version_sort = operator.attrgetter("version")
        return next(
            (c.comes_from for c in sorted(py_filter, key=version_sort, reverse=True)), None
        )

    @versions.default
    def get_versions(self):
        versions = defaultdict(PathEntry)
        from pythonfinder._vendor.pep514tools import environment as pep514env

        env_versions = pep514env.findall()
        path = None
        for version_object in env_versions:
            path = ensure_path(version_object.info.install_path.__getattr__(""))
            py_version = PythonVersion.from_windows_launcher(version_object)
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

    @classmethod
    def create(cls):
        return cls()
