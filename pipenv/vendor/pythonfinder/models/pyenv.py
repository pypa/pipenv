# -*- coding=utf-8 -*-
import attr
from collections import defaultdict
from . import BaseFinder
from .path import VersionPath
from .python import PythonVersion
from ..utils import optional_instance_of, ensure_path


try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path


@attr.s
class PyenvFinder(BaseFinder):
    root = attr.ib(default=None, validator=optional_instance_of(Path))
    versions = attr.ib()

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
            versions[version_tuple] = VersionPath.create(path=p, only_python=True)
        return versions

    @classmethod
    def create(cls, root):
        root = ensure_path(root)
        return cls(root=root)
