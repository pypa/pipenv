# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import operator
import os

import six
from click import secho
from vistir.compat import lru_cache

from . import environment
from .exceptions import InvalidPythonVersion
from .models import path as pyfinder_path
from .utils import Iterable, filter_pythons, version_re

if environment.MYPY_RUNNING:
    from typing import Optional, Dict, Any, Union, List, Iterator
    from .models.path import Path, PathEntry
    from .models.windows import WindowsFinder
    from .models.path import SystemPath


class Finder(object):

    """
    A cross-platform Finder for locating python and other executables.

    Searches for python and other specified binaries starting in *path*, if supplied,
    but searching the bin path of ``sys.executable`` if *system* is ``True``, and then
    searching in the ``os.environ['PATH']`` if *global_search* is ``True``.  When *global_search*
    is ``False``, this search operation is restricted to the allowed locations of
    *path* and *system*.
    """

    def __init__(
        self, path=None, system=False, global_search=True, ignore_unsupported=True
    ):
        # type: (Optional[str], bool, bool, bool) -> None
        """Create a new :class:`~pythonfinder.pythonfinder.Finder` instance.

        :param path: A bin-directory search location, defaults to None
        :param path: str, optional
        :param system: Whether to include the bin-dir of ``sys.executable``, defaults to False
        :param system: bool, optional
        :param global_search: Whether to search the global path from os.environ, defaults to True
        :param global_search: bool, optional
        :param ignore_unsupported: Whether to ignore unsupported python versions, if False, an error is raised, defaults to True
        :param ignore_unsupported: bool, optional
        :returns: a :class:`~pythonfinder.pythonfinder.Finder` object.
        """

        self.path_prepend = path  # type: Optional[str]
        self.global_search = global_search  # type: bool
        self.system = system  # type: bool
        self.ignore_unsupported = ignore_unsupported  # type: bool
        self._system_path = None  # type: Optional[SystemPath]
        self._windows_finder = None  # type: Optional[WindowsFinder]

    def __hash__(self):
        # type: () -> int
        return hash(
            (self.path_prepend, self.system, self.global_search, self.ignore_unsupported)
        )

    def __eq__(self, other):
        # type: (Any) -> bool
        return self.__hash__() == other.__hash__()

    def create_system_path(self):
        # type: () -> SystemPath
        return pyfinder_path.SystemPath.create(
            path=self.path_prepend,
            system=self.system,
            global_search=self.global_search,
            ignore_unsupported=self.ignore_unsupported,
        )

    def reload_system_path(self):
        # type: () -> None
        """
        Rebuilds the base system path and all of the contained finders within it.

        This will re-apply any changes to the environment or any version changes on the system.
        """

        if self._system_path is not None:
            self._system_path.clear_caches()
        self._system_path = None
        six.moves.reload_module(pyfinder_path)
        self._system_path = self.create_system_path()

    def rehash(self):
        # type: () -> None
        if not self._system_path:
            self._system_path = self.create_system_path()
        self.find_all_python_versions.cache_clear()
        self.find_python_version.cache_clear()
        self.reload_system_path()
        filter_pythons.cache_clear()

    @property
    def system_path(self):
        # type: () -> SystemPath
        if self._system_path is None:
            self._system_path = self.create_system_path()
        return self._system_path

    @property
    def windows_finder(self):
        # type: () -> Optional[WindowsFinder]
        if os.name == "nt" and not self._windows_finder:
            from .models import WindowsFinder

            self._windows_finder = WindowsFinder()
        return self._windows_finder

    def which(self, exe):
        # type: (str) -> Optional[PathEntry]
        return self.system_path.which(exe)

    @lru_cache(maxsize=1024)
    def find_python_version(
        self, major=None, minor=None, patch=None, pre=None, dev=None, arch=None, name=None
    ):
        # type: (Optional[Union[str, int]], Optional[int], Optional[int], Optional[bool], Optional[bool], Optional[str], Optional[str]) -> PathEntry
        """
        Find the python version which corresponds most closely to the version requested.

        :param Union[str, int] major: The major version to look for, or the full version, or the name of the target version.
        :param Optional[int] minor: The minor version. If provided, disables string-based lookups from the major version field.
        :param Optional[int] patch: The patch version.
        :param Optional[bool] pre: If provided, specifies whether to search pre-releases.
        :param Optional[bool] dev: If provided, whether to search dev-releases.
        :param Optional[str] arch: If provided, which architecture to search.
        :param Optional[str] name: *Name* of the target python, e.g. ``anaconda3-5.3.0``
        :return: A new *PathEntry* pointer at a matching python version, if one can be located.
        :rtype: :class:`pythonfinder.models.path.PathEntry`
        """

        from .models import PythonVersion

        minor = int(minor) if minor is not None else minor
        patch = int(patch) if patch is not None else patch

        version_dict = {
            "minor": minor,
            "patch": patch,
        }  # type: Dict[str, Union[str, int, Any]]

        if (
            isinstance(major, six.string_types)
            and pre is None
            and minor is None
            and dev is None
            and patch is None
        ):
            if arch is None and "-" in major and major[0].isdigit():
                orig_string = "{0!s}".format(major)
                major, _, arch = major.rpartition("-")
                if arch.startswith("x"):
                    arch = arch.lstrip("x")
                if arch.lower().endswith("bit"):
                    arch = arch.lower().replace("bit", "")
                if not (arch.isdigit() and (int(arch) & int(arch) - 1) == 0):
                    major = orig_string
                    arch = None
                else:
                    arch = "{0}bit".format(arch)
                try:
                    version_dict = PythonVersion.parse(major)
                except (ValueError, InvalidPythonVersion):
                    if name is None:
                        name = "{0!s}".format(major)
                        major = None
                    version_dict = {}
            elif major[0].isalpha():
                name = "%s" % major
                major = None
            else:
                if "." in major and all(part.isdigit() for part in major.split(".")[:2]):
                    match = version_re.match(major)
                    version_dict = match.groupdict()
                    version_dict["is_prerelease"] = bool(
                        version_dict.get("prerel", False)
                    )
                    version_dict["is_devrelease"] = bool(version_dict.get("dev", False))
                else:
                    version_dict = {
                        "major": major,
                        "minor": minor,
                        "patch": patch,
                        "pre": pre,
                        "dev": dev,
                        "arch": arch,
                    }
            if version_dict.get("minor") is not None:
                minor = int(version_dict["minor"])
            if version_dict.get("patch") is not None:
                patch = int(version_dict["patch"])
            if version_dict.get("major") is not None:
                major = int(version_dict["major"])
            _pre = version_dict.get("is_prerelease", pre)
            pre = bool(_pre) if _pre is not None else pre
            _dev = version_dict.get("is_devrelease", dev)
            dev = bool(_dev) if _dev is not None else dev
            arch = (
                version_dict.get("architecture", None) if arch is None else arch
            )  # type: ignore
        if os.name == "nt" and self.windows_finder is not None:
            match = self.windows_finder.find_python_version(
                major=major,
                minor=minor,
                patch=patch,
                pre=pre,
                dev=dev,
                arch=arch,
                name=name,
            )
            if match:
                return match
        return self.system_path.find_python_version(
            major=major, minor=minor, patch=patch, pre=pre, dev=dev, arch=arch, name=name
        )

    @lru_cache(maxsize=1024)
    def find_all_python_versions(
        self, major=None, minor=None, patch=None, pre=None, dev=None, arch=None, name=None
    ):
        # type: (Optional[Union[str, int]], Optional[int], Optional[int], Optional[bool], Optional[bool], Optional[str], Optional[str]) -> List[PathEntry]
        version_sort = operator.attrgetter("as_python.version_sort")
        python_version_dict = getattr(self.system_path, "python_version_dict")
        if python_version_dict:
            paths = (
                path
                for version in python_version_dict.values()
                for path in version
                if path is not None and path.as_python
            )
            path_list = sorted(paths, key=version_sort, reverse=True)
            return path_list
        versions = self.system_path.find_all_python_versions(
            major=major, minor=minor, patch=patch, pre=pre, dev=dev, arch=arch, name=name
        )
        if not isinstance(versions, Iterable):
            versions = [versions]
        path_list = sorted(versions, key=version_sort, reverse=True)
        path_map = {}  # type: Dict[str, PathEntry]
        for path in path_list:
            try:
                resolved_path = path.path.resolve()
            except OSError:
                resolved_path = path.path.absolute()
            if not path_map.get(resolved_path.as_posix()):
                path_map[resolved_path.as_posix()] = path
        return list(path_map.values())
