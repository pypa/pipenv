# -*- coding=utf-8 -*-
import os
import six
from .models import SystemPath


class Finder(object):
    def __init__(self, path=None, system=False):
        self.path_prepend = path
        self.system = system
        self._system_path = None
        self._windows_finder = None

    @property
    def system_path(self):
        if not self._system_path:
            self._system_path = SystemPath.create(
                path=self.path_prepend, system=self.system
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
            if "." in major:
                from .models import PythonVersion

                version_dict = PythonVersion.parse(major)
                major = version_dict["major"]
                minor = version_dict["minor"]
                patch = version_dict["patch"]
                pre = version_dict["is_prerelease"]
                dev = version_dict["is_devrelease"]
        if os.name == "nt":
            match = self.windows_finder.find_python_version(
                major, minor=minor, patch=patch, pre=pre, dev=dev
            )
            if match:
                return match
        return self.system_path.find_python_version(
            major, minor=minor, patch=patch, pre=pre, dev=dev
        )
