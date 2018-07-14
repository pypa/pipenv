# -*- coding=utf-8 -*-
from __future__ import print_function, absolute_import
import os
import six
from .models import SystemPath


class Finder(object):
    def __init__(self, path=None, system=False, global_search=True):
        """Cross-platform Finder for locating python and other executables.

        Searches for python and other specified binaries starting in `path`,
        if supplied, but searching the bin path of `sys.executable` if
        `system=True`, and then searching in the `os.environ['PATH']` if
        `global_search=True`.

        When `global_search` is `False`, this search operation is restricted to
        the allowed locations of `path` and `system`.

        :param path: A bin-directory search location, or None to ignore.
        :type path: str or None
        :param system: Whether to include the bin-dir of `sys.executable`,
            defaults to False
        :type system: bool
        :param global_search: Whether to search the global path from
            os.environ, defaults to True.
        :type global_search: bool
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
                path=self.path_prepend, system=self.system,
                global_search=self.global_search,
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
        if (
            major
            and not minor
            and not patch
            and not pre
            and not dev
            and isinstance(major, six.string_types)
        ):
            from .models import PythonVersion
            version_dict = {}
            if "." in major:
                version_dict = PythonVersion.parse(major)
            elif len(major) == 1:
                version_dict = {
                    'major': int(major),
                    'minor': None,
                    'patch': None,
                    'is_prerelease': False,
                    'is_devrelease': False
                }
            major = version_dict.get("major", major)
            minor = version_dict.get("minor", minor)
            patch = version_dict.get("patch", patch)
            pre = version_dict.get("is_prerelease", pre)
            dev = version_dict.get("is_devrelease", dev)
        if os.name == "nt":
            match = self.windows_finder.find_python_version(
                major, minor=minor, patch=patch, pre=pre, dev=dev
            )
            if match:
                return match
        return self.system_path.find_python_version(
            major, minor=minor, patch=patch, pre=pre, dev=dev
        )
