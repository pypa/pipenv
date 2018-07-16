# -*- coding=utf-8 -*-
from __future__ import print_function, absolute_import
import os
import six
import operator
from .models import SystemPath


class Finder(object):
    def __init__(self, path=None, system=False, global_search=True):
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
        :returns: a :class:`~pythonfinder.pythonfinder.Finder` object.
        """

        self.path_prepend = path
        self.global_search = global_search
        self.system = system
        self._system_path = None
        self._windows_finder = None

    @property
    def system_path(self):
        if not self._system_path:
            self._system_path = SystemPath.create(
                path=self.path_prepend, system=self.system, global_search=self.global_search
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

    def find_python_version(self, major, minor=None, patch=None, pre=None, dev=None):
        from .models import PythonVersion
        if isinstance(major, six.string_types) and pre is None and minor is None and dev is None and patch is None:
            version_dict = PythonVersion.parse(major)
            major = version_dict.get("major", major)
            minor = version_dict.get("minor", minor)
            patch = version_dict.get("patch", patch)
            pre = version_dict.get("is_prerelease", pre) if pre is not None else pre
            dev = version_dict.get("is_devrelease", dev) if dev is not None else dev
        if os.name == "nt":
            match = self.windows_finder.find_python_version(
                major, minor=minor, patch=patch, pre=pre, dev=dev
            )
            if match:
                return match
        return self.system_path.find_python_version(
            major=major, minor=minor, patch=patch, pre=pre, dev=dev
        )

    def find_all_python_versions(self, major=None, minor=None, patch=None, pre=None, dev=None):
        version_sort = operator.attrgetter("as_python.version_sort")
        versions = []
        versions.extend([p for p in self.system_path.find_all_python_versions(major=major, minor=minor, patch=patch, pre=pre, dev=dev)])
        if os.name == 'nt':
            windows_versions = self.windows_finder.find_all_python_versions(major=major, minor=minor, patch=patch, pre=pre, dev=dev)
            versions = versions + list(windows_versions)
        return sorted(versions, key=version_sort, reverse=True)
