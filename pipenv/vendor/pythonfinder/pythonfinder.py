# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import importlib
import operator
import os

import pipenv.vendor.six as six
from pipenv.vendor.click import secho

from . import environment
from .compat import lru_cache
from .exceptions import InvalidPythonVersion
from .utils import Iterable, filter_pythons, version_re

if environment.MYPY_RUNNING:
    from typing import Any, Dict, Iterator, List, Optional, Text, Union

    from .models.path import Path, PathEntry, SystemPath
    from .models.windows import WindowsFinder

    STRING_TYPE = Union[str, Text, bytes]


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
        self,
        path=None,
        system=False,
        global_search=True,
        ignore_unsupported=True,
        sort_by_path=False,
    ):
        # type: (Optional[str], bool, bool, bool, bool) -> None
        """Create a new :class:`~pythonfinder.pythonfinder.Finder` instance.

        :param path: A bin-directory search location, defaults to None
        :param path: str, optional
        :param system: Whether to include the bin-dir of ``sys.executable``, defaults to False
        :param system: bool, optional
        :param global_search: Whether to search the global path from os.environ, defaults to True
        :param global_search: bool, optional
        :param ignore_unsupported: Whether to ignore unsupported python versions, if False, an
            error is raised, defaults to True
        :param ignore_unsupported: bool, optional
        :param bool sort_by_path: Whether to always sort by path
        :returns: a :class:`~pythonfinder.pythonfinder.Finder` object.
        """

        self.path_prepend = path  # type: Optional[str]
        self.global_search = global_search  # type: bool
        self.system = system  # type: bool
        self.sort_by_path = sort_by_path  # type: bool
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
        pyfinder_path = importlib.import_module("pythonfinder.models.path")
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
            self._system_path = self._system_path.clear_caches()
            self._system_path = None
        pyfinder_path = importlib.import_module("pythonfinder.models.path")
        six.moves.reload_module(pyfinder_path)
        self._system_path = self.create_system_path()

    def rehash(self):
        # type: () -> "Finder"
        if not self._system_path:
            self._system_path = self.create_system_path()
        self.find_all_python_versions.cache_clear()
        self.find_python_version.cache_clear()
        if self._windows_finder is not None:
            self._windows_finder = None
        filter_pythons.cache_clear()
        self.reload_system_path()
        return self

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

    @classmethod
    def parse_major(
        cls,
        major,  # type: Optional[str]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
    ):
        # type: (...) -> Dict[str, Union[int, str, bool, None]]
        from .models import PythonVersion

        major_is_str = major and isinstance(major, six.string_types)
        is_num = (
            major
            and major_is_str
            and all(part.isdigit() for part in major.split(".")[:2])
        )
        major_has_arch = (
            arch is None
            and major
            and major_is_str
            and "-" in major
            and major[0].isdigit()
        )
        name = None
        if major and major_has_arch:
            orig_string = "{0!s}".format(major)
            major, _, arch = major.rpartition("-")
            if arch:
                arch = arch.lower().lstrip("x").replace("bit", "")
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
        elif major and major[0].isalpha():
            return {"major": None, "name": major, "arch": arch}
        elif major and is_num:
            match = version_re.match(major)
            version_dict = match.groupdict() if match else {}  # type: ignore
            version_dict.update(
                {
                    "is_prerelease": bool(version_dict.get("prerel", False)),
                    "is_devrelease": bool(version_dict.get("dev", False)),
                }
            )
        else:
            version_dict = {
                "major": major,
                "minor": minor,
                "patch": patch,
                "pre": pre,
                "dev": dev,
                "arch": arch,
            }
        if not version_dict.get("arch") and arch:
            version_dict["arch"] = arch
        version_dict["minor"] = (
            int(version_dict["minor"]) if version_dict.get("minor") is not None else minor
        )
        version_dict["patch"] = (
            int(version_dict["patch"]) if version_dict.get("patch") is not None else patch
        )
        version_dict["major"] = (
            int(version_dict["major"]) if version_dict.get("major") is not None else major
        )
        if not (version_dict["major"] or version_dict.get("name")):
            version_dict["major"] = major
            if name:
                version_dict["name"] = name
        return version_dict

    @lru_cache(maxsize=1024)
    def find_python_version(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
        sort_by_path=False,  # type: bool
    ):
        # type: (...) -> Optional[PathEntry]
        """
        Find the python version which corresponds most closely to the version requested.

        :param Union[str, int] major: The major version to look for, or the full version, or the name of the target version.
        :param Optional[int] minor: The minor version. If provided, disables string-based lookups from the major version field.
        :param Optional[int] patch: The patch version.
        :param Optional[bool] pre: If provided, specifies whether to search pre-releases.
        :param Optional[bool] dev: If provided, whether to search dev-releases.
        :param Optional[str] arch: If provided, which architecture to search.
        :param Optional[str] name: *Name* of the target python, e.g. ``anaconda3-5.3.0``
        :param bool sort_by_path: Whether to sort by path -- default sort is by version(default: False)
        :return: A new *PathEntry* pointer at a matching python version, if one can be located.
        :rtype: :class:`pythonfinder.models.path.PathEntry`
        """

        minor = int(minor) if minor is not None else minor
        patch = int(patch) if patch is not None else patch

        version_dict = {
            "minor": minor,
            "patch": patch,
            "name": name,
            "arch": arch,
        }  # type: Dict[str, Union[str, int, Any]]

        if (
            isinstance(major, six.string_types)
            and pre is None
            and minor is None
            and dev is None
            and patch is None
        ):
            version_dict = self.parse_major(major, minor=minor, patch=patch, arch=arch)
            major = version_dict["major"]
            minor = version_dict.get("minor", minor)  # type: ignore
            patch = version_dict.get("patch", patch)  # type: ignore
            arch = version_dict.get("arch", arch)  # type: ignore
            name = version_dict.get("name", name)  # type: ignore
            _pre = version_dict.get("is_prerelease", pre)
            pre = bool(_pre) if _pre is not None else pre
            _dev = version_dict.get("is_devrelease", dev)
            dev = bool(_dev) if _dev is not None else dev
            if "architecture" in version_dict and isinstance(
                version_dict["architecture"], six.string_types
            ):
                arch = version_dict["architecture"]  # type: ignore
        if os.name == "nt" and self.windows_finder is not None:
            found = self.windows_finder.find_python_version(
                major=major,
                minor=minor,
                patch=patch,
                pre=pre,
                dev=dev,
                arch=arch,
                name=name,
            )
            if found:
                return found
        return self.system_path.find_python_version(
            major=major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
            name=name,
            sort_by_path=self.sort_by_path,
        )

    @lru_cache(maxsize=1024)
    def find_all_python_versions(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
    ):
        # type: (...) -> List[PathEntry]
        version_sort = operator.attrgetter("as_python.version_sort")
        python_version_dict = getattr(self.system_path, "python_version_dict", {})
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
        # This list has already been mostly sorted on windows, we don't need to reverse it again
        path_list = sorted(
            filter(lambda v: v and v.as_python, versions), key=version_sort, reverse=True
        )
        path_map = {}  # type: Dict[str, PathEntry]
        for path in path_list:
            try:
                resolved_path = path.path.resolve()
            except OSError:
                resolved_path = path.path.absolute()
            if not path_map.get(resolved_path.as_posix()):
                path_map[resolved_path.as_posix()] = path
        return path_list
