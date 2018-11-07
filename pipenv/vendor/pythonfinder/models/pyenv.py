# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import logging
import operator

from collections import defaultdict

import attr
import sysconfig

from vistir.compat import Path

from ..utils import (
    ensure_path,
    optional_instance_of,
    get_python_version,
    filter_pythons,
    unnest,
)
from .mixins import BaseFinder, BasePath
from .path import SystemPath, PathEntry
from .python import PythonVersion


logger = logging.getLogger(__name__)


@attr.s
class PyenvFinder(BaseFinder, BasePath):
    root = attr.ib(default=None, validator=optional_instance_of(Path))
    #: ignore_unsupported should come before versions, because its value is used
    #: in versions's default initializer.
    ignore_unsupported = attr.ib(default=True)
    paths = attr.ib(default=attr.Factory(list))
    roots = attr.ib(default=attr.Factory(defaultdict))
    versions = attr.ib()
    pythons = attr.ib()

    @property
    def expanded_paths(self):
        return (
            path for path in unnest(p for p in self.versions.values())
            if path is not None
        )

    def get_version_order(self):
        version_order_file = self.root.joinpath("version").read_text(encoding="utf-8")
        version_paths = [
            p for p in self.root.glob("versions/*")
            if not (p.parent.name == "envs" or p.name == "envs")
        ]
        versions = {v.name: v for v in version_paths}
        version_order = [versions[v] for v in version_order_file.splitlines() if v in versions]
        for version in version_order:
            version_paths.remove(version)
        version_order += version_paths
        return version_order

    @classmethod
    def version_from_bin_dir(cls, base_dir, name=None):
        py_version = None
        version_path = PathEntry.create(
            path=base_dir.absolute().as_posix(),
            only_python=True,
            name=base_dir.parent.name,
        )
        py_version = next(iter(version_path.find_all_python_versions()), None)
        return py_version

    @versions.default
    def get_versions(self):
        versions = defaultdict()
        bin_ = sysconfig._INSTALL_SCHEMES['posix_prefix']["scripts"]
        for p in self.get_version_order():
            bin_dir = Path(bin_.format(base=p.as_posix()))
            version_path = None
            if bin_dir.exists():
                version_path = PathEntry.create(
                    path=bin_dir.absolute().as_posix(),
                    only_python=False,
                    name=p.name,
                    is_root=True,
                )
            version = None
            try:
                version = PythonVersion.parse(p.name)
            except ValueError:
                entry = next(iter(version_path.find_all_python_versions()), None)
                if not entry:
                    if self.ignore_unsupported:
                        continue
                    raise
                else:
                    version = entry.py_version.as_dict()
            except Exception:
                if not self.ignore_unsupported:
                    raise
                logger.warning(
                    "Unsupported Python version %r, ignoring...", p.name, exc_info=True
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
                version.get("is_debug"),
            )
            self.roots[p] = version_path
            versions[version_tuple] = version_path
            self.paths.append(version_path)
        return versions

    @pythons.default
    def get_pythons(self):
        pythons = defaultdict()
        for p in self.paths:
            pythons.update(p.pythons)
        return pythons

    @classmethod
    def create(cls, root, ignore_unsupported=True):
        root = ensure_path(root)
        return cls(root=root, ignore_unsupported=ignore_unsupported)

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
        py = operator.attrgetter("as_python")
        pythons = (
            py_ver for py_ver in (py(p) for p in self.pythons.values() if p is not None)
            if py_ver is not None
        )
        # pythons = filter(None, [p.as_python for p in self.pythons.values()])
        matching_versions = filter(lambda py: version_matcher(py), pythons)
        version_sort = operator.attrgetter("version_sort")
        return sorted(matching_versions, key=version_sort, reverse=True)

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
            "matches",
            major=major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
            name=name,
        )
        pythons = filter(None, [p.as_python for p in self.pythons.values()])
        matching_versions = filter(lambda py: version_matcher(py), pythons)
        version_sort = operator.attrgetter("version_sort")
        return next(iter(c for c in sorted(matching_versions, key=version_sort, reverse=True)), None)


@attr.s
class VersionPath(SystemPath):
    base = attr.ib(default=None, validator=optional_instance_of(Path))
    name = attr.ib(default=None)

    @classmethod
    def create(cls, path, only_python=True, pythons=None, name=None):
        """Accepts a path to a base python version directory.

        Generates the pyenv version listings for it"""
        path = ensure_path(path)
        path_entries = defaultdict(PathEntry)
        bin_ = sysconfig._INSTALL_SCHEMES[sysconfig._get_default_scheme()]["scripts"]
        if path.as_posix().endswith(Path(bin_).name):
            path = path.parent
        bin_dir = ensure_path(bin_.format(base=path.as_posix()))
        if not name:
            name = path.name
        current_entry = PathEntry.create(
            bin_dir, is_root=True, only_python=True, pythons=pythons, name=name
        )
        path_entries[bin_dir.as_posix()] = current_entry
        return cls(name=name, base=bin_dir, paths=path_entries)
