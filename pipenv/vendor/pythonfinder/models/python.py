# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import copy
import platform
import operator
import logging

from collections import defaultdict

import attr

from packaging.version import Version, LegacyVersion
from packaging.version import parse as parse_version
from vistir.compat import Path

from ..environment import SYSTEM_ARCH, PYENV_ROOT, ASDF_DATA_DIR
from ..exceptions import InvalidPythonVersion
from .mixins import BaseFinder, BasePath
from ..utils import (
    _filter_none,
    ensure_path,
    get_python_version,
    optional_instance_of,
    unnest,
    is_in_path,
    parse_pyenv_version_order,
    parse_asdf_version_order,
    parse_python_version,
)

logger = logging.getLogger(__name__)


@attr.s(slots=True)
class PythonFinder(BaseFinder, BasePath):
    root = attr.ib(default=None, validator=optional_instance_of(Path))
    #: ignore_unsupported should come before versions, because its value is used
    #: in versions's default initializer.
    ignore_unsupported = attr.ib(default=True)
    #: The function to use to sort version order when returning an ordered verion set
    sort_function = attr.ib(default=None)
    paths = attr.ib(default=attr.Factory(list))
    roots = attr.ib(default=attr.Factory(defaultdict))
    #: Glob path for python versions off of the root directory
    version_glob_path = attr.ib(default="versions/*")
    versions = attr.ib()
    pythons = attr.ib()

    @property
    def expanded_paths(self):
        return (
            path for path in unnest(p for p in self.versions.values())
            if path is not None
        )

    @property
    def is_pyenv(self):
        return is_in_path(str(self.root), PYENV_ROOT)

    @property
    def is_asdf(self):
        return is_in_path(str(self.root), ASDF_DATA_DIR)

    def get_version_order(self):
        version_paths = [
            p for p in self.root.glob(self.version_glob_path)
            if not (p.parent.name == "envs" or p.name == "envs")
        ]
        versions = {v.name: v for v in version_paths}
        if self.is_pyenv:
            version_order = [versions[v] for v in parse_pyenv_version_order() if v in versions]
        elif self.is_asdf:
            version_order = [versions[v] for v in parse_asdf_version_order() if v in versions]
        for version in version_order:
            version_paths.remove(version)
        if version_order:
            version_order += version_paths
        else:
            version_order = version_paths
        return version_order

    @classmethod
    def version_from_bin_dir(cls, base_dir, name=None):
        from .path import PathEntry
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
        from .path import PathEntry
        versions = defaultdict()
        bin_ = "{base}/bin"
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
            except (ValueError, InvalidPythonVersion):
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
    def create(cls, root, sort_function=None, version_glob_path=None, ignore_unsupported=True):
        root = ensure_path(root)
        if not version_glob_path:
            version_glob_path = "versions/*"
        return cls(root=root, ignore_unsupported=ignore_unsupported,
                   sort_function=sort_function, version_glob_path=version_glob_path)

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


@attr.s(slots=True)
class PythonVersion(object):
    major = attr.ib(default=0)
    minor = attr.ib(default=None)
    patch = attr.ib(default=0)
    is_prerelease = attr.ib(default=False)
    is_postrelease = attr.ib(default=False)
    is_devrelease = attr.ib(default=False)
    is_debug = attr.ib(default=False)
    version = attr.ib(default=None)
    architecture = attr.ib(default=None)
    comes_from = attr.ib(default=None)
    executable = attr.ib(default=None)
    name = attr.ib(default=None)

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
        elif self.is_debug:
            release_sort = 1
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
            self.is_debug,
        )

    def matches(
        self,
        major=None,
        minor=None,
        patch=None,
        pre=False,
        dev=False,
        arch=None,
        debug=False,
        name=None,
    ):
        if arch:
            own_arch = self.get_architecture()
            if arch.isdigit():
                arch = "{0}bit".format(arch)
        return (
            (major is None or self.major == major)
            and (minor is None or self.minor == minor)
            and (patch is None or self.patch == patch)
            and (pre is None or self.is_prerelease == pre)
            and (dev is None or self.is_devrelease == dev)
            and (arch is None or own_arch == arch)
            and (debug is None or self.is_debug == debug)
            and (
                name is None
                or (name and self.name)
                and (self.name == name or self.name.startswith(name))
            )
        )

    def as_major(self):
        self_dict = attr.asdict(self, recurse=False, filter=_filter_none).copy()
        self_dict.update({"minor": None, "patch": None})
        return self.create(**self_dict)

    def as_minor(self):
        self_dict = attr.asdict(self, recurse=False, filter=_filter_none).copy()
        self_dict.update({"patch": None})
        return self.create(**self_dict)

    def as_dict(self):
        return {
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "is_prerelease": self.is_prerelease,
            "is_postrelease": self.is_postrelease,
            "is_devrelease": self.is_devrelease,
            "is_debug": self.is_debug,
            "version": self.version,
        }

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

        version_dict = parse_python_version(str(version))
        if not version_dict:
            raise ValueError("Not a valid python version: %r" % version)
        return version_dict

    def get_architecture(self):
        if self.architecture:
            return self.architecture
        arch, _ = platform.architecture(self.comes_from.path.as_posix())
        self.architecture = arch
        return self.architecture

    @classmethod
    def from_path(cls, path, name=None, ignore_unsupported=True):
        """Parses a python version from a system path.

        Raises:
            ValueError -- Not a valid python path

        :param path: A string or :class:`~pythonfinder.models.path.PathEntry`
        :type path: str or :class:`~pythonfinder.models.path.PathEntry` instance
        :param str name: Name of the python distribution in question
        :param bool ignore_unsupported: Whether to ignore or error on unsupported paths.
        :return: An instance of a PythonVersion.
        :rtype: :class:`~pythonfinder.models.python.PythonVersion`
        """

        from .path import PathEntry

        if not isinstance(path, PathEntry):
            path = PathEntry.create(path, is_root=False, only_python=True, name=name)
        from ..environment import IGNORE_UNSUPPORTED
        ignore_unsupported = ignore_unsupported or IGNORE_UNSUPPORTED
        if not path.is_python:
            if not (ignore_unsupported or IGNORE_UNSUPPORTED):
                raise ValueError("Not a valid python path: %s" % path.path)
        py_version = get_python_version(path.path.absolute().as_posix())
        instance_dict = cls.parse(py_version.strip())
        if not isinstance(instance_dict.get("version"), Version) and not ignore_unsupported:
            raise ValueError("Not a valid python path: %s" % path.path)
        if not name:
            name = path.name
        instance_dict.update(
            {"comes_from": path, "name": name}
        )
        return cls(**instance_dict)

    @classmethod
    def from_windows_launcher(cls, launcher_entry, name=None):
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
                "name": name
            }
        )
        py_version = cls.create(**creation_dict)
        comes_from = PathEntry.create(exe_path, only_python=True, name=name)
        comes_from.py_version = copy.deepcopy(py_version)
        py_version.comes_from = comes_from
        py_version.name = comes_from.name
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
            entries = self.versions[version.version_tuple]
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
