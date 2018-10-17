# -*- coding=utf-8 -*-
from __future__ import print_function, absolute_import
import os
import six
import operator
from .models import SystemPath


class Finder(object):
    def __init__(self, path=None, system=False, global_search=True, ignore_unsupported=False):
        """Finder A cross-platform Finder for locating python and other executables.

        Searches for python and other specified binaries starting in `path`, if supplied,
        but searching the bin path of `sys.executable` if `system=True`, and then
        searching in the `os.environ['PATH']` if `global_search=True`.  When `global_search`
        is `False`, this search operation is restricted to the allowed locations of 
        `path` and `system`.

        :param path: A bin-directory search location, defaults to None
        :param path: str, optional
        :param system: Whether to include the bin-dir of `sys.executable`, defaults to False
        :param system: bool, optional
        :param global_search: Whether to search the global path from os.environ, defaults to True
        :param global_search: bool, optional
        :param ignore_unsupported: Whether to ignore unsupported python versions, if False, an error is raised, defaults to True
        :param ignore_unsupported: bool, optional
        :returns: a :class:`~pythonfinder.pythonfinder.Finder` object.
        """

        self.path_prepend = path
        self.global_search = global_search
        self.system = system
        self.ignore_unsupported = ignore_unsupported
        self._system_path = None
        self._windows_finder = None

    @property
    def system_path(self):
        if not self._system_path:
            self._system_path = SystemPath.create(
                path=self.path_prepend,
                system=self.system,
                global_search=self.global_search,
                ignore_unsupported=self.ignore_unsupported,
            )
        return self._system_path

    @property
    def windows_finder(self):
        if os.name == "nt" and not self._windows_finder:
            from .models import WindowsFinder

            self._windows_finder = WindowsFinder()
        return self._windows_finder

    def which(self, exe):
        return self.system_path.which(exe)

    def find_python_version(
        self, major, minor=None, patch=None, pre=None, dev=None, arch=None
    ):
        from .models import PythonVersion

        if (
            isinstance(major, six.string_types)
            and pre is None
            and minor is None
            and dev is None
            and patch is None
        ):
            if arch is None and "-" in major:
                major, arch = major.rsplit("-", 1)
                if not arch.isdigit():
                    major = "{0}-{1}".format(major, arch)
                else:
                    arch = "{0}bit".format(arch)
            version_dict = PythonVersion.parse(major)
            major = version_dict.get("major", major)
            minor = version_dict.get("minor", minor)
            patch = version_dict.get("patch", patch)
            pre = version_dict.get("is_prerelease", pre) if pre is None else pre
            dev = version_dict.get("is_devrelease", dev) if dev is None else dev
            arch = version_dict.get("architecture", arch) if arch is None else arch
        if os.name == "nt":
            match = self.windows_finder.find_python_version(
                major, minor=minor, patch=patch, pre=pre, dev=dev, arch=arch
            )
            if match:
                return match
        return self.system_path.find_python_version(
            major=major, minor=minor, patch=patch, pre=pre, dev=dev, arch=arch
        )

    def find_all_python_versions(
        self, major=None, minor=None, patch=None, pre=None, dev=None, arch=None
    ):
        version_sort = operator.attrgetter("as_python.version_sort")
        python_version_dict = getattr(self.system_path, "python_version_dict")
        if python_version_dict:
            paths = filter(
                None,
                [
                    path
                    for version in python_version_dict.values()
                    for path in version
                    if path.as_python
                ],
            )
            paths = sorted(paths, key=version_sort, reverse=True)
            return paths
        versions = self.system_path.find_all_python_versions(
            major=major, minor=minor, patch=patch, pre=pre, dev=dev, arch=arch
        )
        if not isinstance(versions, list):
            versions = [versions]
        paths = sorted(versions, key=version_sort, reverse=True)
        path_map = {}
        for path in paths:
            try:
                resolved_path = path.path.resolve()
            except OSError:
                resolved_path = path.path.absolute()
            if not path_map.get(resolved_path.as_posix()):
                path_map[resolved_path.as_posix()] = path
        return list(path_map.values())
