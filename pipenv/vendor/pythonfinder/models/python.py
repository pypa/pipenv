# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import copy
import platform

from collections import defaultdict

import attr

from packaging.version import Version
from packaging.version import parse as parse_version

from vistir.compat import Path

from ..environment import SYSTEM_ARCH
from ..utils import (
    _filter_none, ensure_path, get_python_version, optional_instance_of
)


@attr.s
class PythonVersion(object):
    major = attr.ib(default=0)
    minor = attr.ib(default=None)
    patch = attr.ib(default=0)
    is_prerelease = attr.ib(default=False)
    is_postrelease = attr.ib(default=False)
    is_devrelease = attr.ib(default=False)
    version = attr.ib(default=None, validator=optional_instance_of(Version))
    architecture = attr.ib(default=None)
    comes_from = attr.ib(default=None)
    executable = attr.ib(default=None)

    @property
    def version_sort(self):
        """version_sort tuple for sorting against other instances of the same class.

        Returns a tuple of the python version but includes a point for non-dev,
        and a point for non-prerelease versions.  So released versions will have 2 points
        for this value.  E.g. `(3, 6, 6, 2)` is a release, `(3, 6, 6, 1)` is a prerelease,
        `(3, 6, 6, 0)` is a dev release, and `(3, 6, 6, 3)` is a postrelease.
        """
        release_sort = 2
        if self.is_postrelease:
            release_sort = 3
        elif self.is_prerelease:
            release_sort = 1
        elif self.is_devrelease:
            release_sort = 0
        return (self.major, self.minor, self.patch if self.patch else 0, release_sort)

    @property
    def version_tuple(self):
        """Provides a version tuple for using as a dictionary key.

        :return: A tuple describing the python version meetadata contained.
        :rtype: tuple
        """

        return (
            self.major,
            self.minor,
            self.patch,
            self.is_prerelease,
            self.is_devrelease,
        )

    def matches(
        self, major=None, minor=None, patch=None, pre=False, dev=False, arch=None
    ):
        if arch and arch.isdigit():
            arch = "{0}bit".format(arch)
        return (
            (major is None or self.major == major)
            and (minor is None or self.minor == minor)
            and (patch is None or self.patch == patch)
            and (pre is None or self.is_prerelease == pre)
            and (dev is None or self.is_devrelease == dev)
            and (arch is None or self.architecture == arch)
        )

    def as_major(self):
        self_dict = attr.asdict(self, recurse=False, filter=_filter_none).copy()
        self_dict.update({"minor": None, "patch": None})
        return self.create(**self_dict)

    def as_minor(self):
        self_dict = attr.asdict(self, recurse=False, filter=_filter_none).copy()
        self_dict.update({"patch": None})
        return self.create(**self_dict)

    @classmethod
    def parse(cls, version):
        """Parse a valid version string into a dictionary

        Raises:
            ValueError -- Unable to parse version string
            ValueError -- Not a valid python version

        :param version: A valid version string
        :type version: str
        :return: A dictionary with metadata about the specified python version.
        :rtype: dict.
        """

        try:
            version = parse_version(str(version))
        except TypeError:
            raise ValueError("Unable to parse version: %s" % version)
        if not version or not version.release:
            raise ValueError("Not a valid python version: %r" % version)
            return
        if len(version.release) >= 3:
            major, minor, patch = version.release[:3]
        elif len(version.release) == 2:
            major, minor = version.release
            patch = None
        else:
            major = version.release[0]
            minor = None
            patch = None
        return {
            "major": major,
            "minor": minor,
            "patch": patch,
            "is_prerelease": version.is_prerelease,
            "is_postrelease": version.is_postrelease,
            "is_devrelease": version.is_devrelease,
            "version": version,
        }

    @classmethod
    def from_path(cls, path):
        """Parses a python version from a system path.

        Raises:
            ValueError -- Not a valid python path

        :param path: A string or :class:`~pythonfinder.models.path.PathEntry`
        :type path: str or :class:`~pythonfinder.models.path.PathEntry` instance
        :param launcher_entry: A python launcher environment object.
        :return: An instance of a PythonVersion.
        :rtype: :class:`~pythonfinder.models.python.PythonVersion`
        """

        from .path import PathEntry

        if not isinstance(path, PathEntry):
            path = PathEntry.create(path, is_root=False, only_python=True)
        if not path.is_python:
            raise ValueError("Not a valid python path: %s" % path.path)
            return
        py_version = get_python_version(str(path.path))
        instance_dict = cls.parse(py_version)
        if not isinstance(instance_dict.get("version"), Version):
            raise ValueError("Not a valid python path: %s" % path.path)
            return
        architecture, _ = platform.architecture(path.path.as_posix())
        instance_dict.update({"comes_from": path, "architecture": architecture})
        return cls(**instance_dict)

    @classmethod
    def from_windows_launcher(cls, launcher_entry):
        """Create a new PythonVersion instance from a Windows Launcher Entry

        :param launcher_entry: A python launcher environment object.
        :return: An instance of a PythonVersion.
        :rtype: :class:`~pythonfinder.models.python.PythonVersion`
        """

        from .path import PathEntry

        creation_dict = cls.parse(launcher_entry.info.version)
        base_path = ensure_path(launcher_entry.info.install_path.__getattr__(""))
        default_path = base_path / "python.exe"
        if not default_path.exists():
            default_path = base_path / "Scripts" / "python.exe"
        exe_path = ensure_path(
            getattr(launcher_entry.info.install_path, "executable_path", default_path)
        )
        creation_dict.update(
            {
                "architecture": getattr(
                    launcher_entry.info, "sys_architecture", SYSTEM_ARCH
                ),
                "executable": exe_path,
            }
        )
        py_version = cls.create(**creation_dict)
        comes_from = PathEntry.create(exe_path, only_python=True)
        comes_from.py_version = copy.deepcopy(py_version)
        py_version.comes_from = comes_from
        return py_version

    @classmethod
    def create(cls, **kwargs):
        if "architecture" in kwargs:
            if kwargs["architecture"].isdigit():
                kwargs["architecture"] = "{0}bit".format(kwargs["architecture"])
        return cls(**kwargs)


@attr.s
class VersionMap(object):
    versions = attr.ib(default=attr.Factory(defaultdict(list)))

    def add_entry(self, entry):
        version = entry.as_python
        if version:
            entries = versions[version.version_tuple]
            paths = {p.path for p in self.versions.get(version.version_tuple, [])}
            if entry.path not in paths:
                self.versions[version.version_tuple].append(entry)

    def merge(self, target):
        for version, entries in target.versions.items():
            if version not in self.versions:
                self.versions[version] = entries
            else:
                current_entries = {p.path for p in self.versions.get(version)}
                new_entries = {p.path for p in entries}
                new_entries -= current_entries
                self.versions[version].append(
                    [e for e in entries if e.path in new_entries]
                )
