# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

from collections import defaultdict

import attr

from vistir.compat import Path

from ..utils import ensure_path, optional_instance_of
from .mixins import BaseFinder
from .path import VersionPath
from .python import PythonVersion


@attr.s
class PyenvFinder(BaseFinder):
    root = attr.ib(default=None, validator=optional_instance_of(Path))
    versions = attr.ib()
    pythons = attr.ib()

    @versions.default
    def get_versions(self):
        versions = defaultdict(VersionPath)
        for p in self.root.glob("versions/*"):
            version = PythonVersion.parse(p.name)
            version_tuple = (
                version.get("major"),
                version.get("minor"),
                version.get("patch"),
                version.get("is_prerelease"),
                version.get("is_devrelease"),
            )
            versions[version_tuple] = VersionPath.create(
                path=p.resolve(), only_python=True
            )
        return versions

    @pythons.default
    def get_pythons(self):
        pythons = defaultdict()
        for v in self.versions.values():
            for p in v.paths.values():
                _path = ensure_path(p.path)
                if p.is_python:
                    pythons[_path] = p
        return pythons

    @classmethod
    def create(cls, root):
        root = ensure_path(root)
        return cls(root=root)
