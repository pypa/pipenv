# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import logging

from collections import defaultdict

import attr
import sysconfig

from vistir.compat import Path

from ..utils import ensure_path, optional_instance_of, get_python_version, filter_pythons
from .mixins import BaseFinder
from .path import VersionPath
from .python import PythonVersion


logger = logging.getLogger(__name__)


@attr.s
class PyenvFinder(BaseFinder):
    root = attr.ib(default=None, validator=optional_instance_of(Path))
    # ignore_unsupported should come before versions, because its value is used
    # in versions's default initializer.
    ignore_unsupported = attr.ib(default=False)
    versions = attr.ib()
    pythons = attr.ib()

    @classmethod
    def version_from_bin_dir(cls, base_dir):
        pythons = [py for py in filter_pythons(base_dir)]
        py_version = None
        for py in pythons:
            version = get_python_version(py.as_posix())
            try:
                py_version = PythonVersion.parse(version)
            except Exception:
                continue
            if py_version:
                return py_version
        return

    @versions.default
    def get_versions(self):
        versions = defaultdict(VersionPath)
        bin_ = sysconfig._INSTALL_SCHEMES[sysconfig._get_default_scheme()]["scripts"]
        for p in self.root.glob("versions/*"):
            if p.parent.name == "envs":
                continue
            try:
                version = PythonVersion.parse(p.name)
            except ValueError:
                bin_dir = Path(bin_.format(base=p.as_posix()))
                if bin_dir.exists():
                    version = self.version_from_bin_dir(bin_dir)
                if not version:
                    if not self.ignore_unsupported:
                        raise
                    continue
            except Exception:
                if not self.ignore_unsupported:
                    raise
                logger.warning(
                    'Unsupported Python version %r, ignoring...',
                    p.name, exc_info=True
                )
                continue
            if not version:
                continue
            version_tuple = (
                version.get("major"),
                version.get("minor"),
                version.get("patch"),
                version.get("is_prerelease"),
                version.get("is_devrelease"),
                version.get("is_debug")
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
    def create(cls, root, ignore_unsupported=False):
        root = ensure_path(root)
        return cls(root=root, ignore_unsupported=ignore_unsupported)
