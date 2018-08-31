# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import copy
import operator
import os
import sys

from collections import defaultdict
from itertools import chain

import attr

from cached_property import cached_property

from vistir.compat import Path, fs_str

from .mixins import BasePath
from ..environment import PYENV_INSTALLED, PYENV_ROOT
from ..exceptions import InvalidPythonVersion
from ..utils import (
    ensure_path, filter_pythons, looks_like_python, optional_instance_of,
    path_is_known_executable, unnest
)
from .python import PythonVersion


@attr.s
class SystemPath(object):
    global_search = attr.ib(default=True)
    paths = attr.ib(default=attr.Factory(defaultdict))
    _executables = attr.ib(default=attr.Factory(list))
    _python_executables = attr.ib(default=attr.Factory(list))
    path_order = attr.ib(default=attr.Factory(list))
    python_version_dict = attr.ib(default=attr.Factory(defaultdict))
    only_python = attr.ib(default=False)
    pyenv_finder = attr.ib(default=None, validator=optional_instance_of("PyenvPath"))
    system = attr.ib(default=False)
    _version_dict = attr.ib(default=attr.Factory(defaultdict))

    __finders = attr.ib(default=attr.Factory(dict))

    def _register_finder(self, finder_name, finder):
        if finder_name not in self.__finders:
            self.__finders[finder_name] = finder

    @cached_property
    def executables(self):
        self.executables = [
            p
            for p in chain(*(child.children.values() for child in self.paths.values()))
            if p.is_executable
        ]
        return self.executables

    @cached_property
    def python_executables(self):
        python_executables = {}
        for child in self.paths.values():
            if child.pythons:
                python_executables.update(dict(child.pythons))
        for finder_name, finder in self.__finders.items():
            if finder.pythons:
                python_executables.update(dict(finder.pythons))
        self._python_executables = python_executables
        return self._python_executables

    @cached_property
    def version_dict(self):
        self._version_dict = defaultdict(list)
        for finder_name, finder in self.__finders.items():
            for version, entry in finder.versions.items():
                if finder_name == "windows":
                    if entry not in self._version_dict[version]:
                        self._version_dict[version].append(entry)
                    continue
                if isinstance(entry, VersionPath):
                    for path in entry.paths.values():
                        if path not in self._version_dict[version] and path.is_python:
                            self._version_dict[version].append(path)
                        continue
                    continue
                elif entry not in self._version_dict[version] and entry.is_python:
                    self._version_dict[version].append(entry)
        for p, entry in self.python_executables.items():
            version = entry.as_python
            if not version:
                continue
            version = version.version_tuple
            if version and entry not in self._version_dict[version]:
                self._version_dict[version].append(entry)
        return self._version_dict

    def __attrs_post_init__(self):
        #: slice in pyenv
        if not self.__class__ == SystemPath:
            return
        if os.name == "nt":
            self._setup_windows()
        if PYENV_INSTALLED:
            self._setup_pyenv()
        venv = os.environ.get("VIRTUAL_ENV")
        if os.name == "nt":
            bin_dir = "Scripts"
        else:
            bin_dir = "bin"
        if venv and (self.system or self.global_search):
            p = ensure_path(venv)
            self.path_order = [(p / bin_dir).as_posix()] + self.path_order
            self.paths[p] = PathEntry.create(path=p, is_root=True, only_python=False)
        if self.system:
            syspath = Path(sys.executable)
            syspath_bin = syspath.parent
            if syspath_bin.name != bin_dir and syspath_bin.joinpath(bin_dir).exists():
                syspath_bin = syspath_bin / bin_dir
            self.path_order = [syspath_bin.as_posix()] + self.path_order
            self.paths[syspath_bin] = PathEntry.create(
                path=syspath_bin, is_root=True, only_python=False
            )

    def _setup_pyenv(self):
        from .pyenv import PyenvFinder

        last_pyenv = next(
            (p for p in reversed(self.path_order) if PYENV_ROOT.lower() in p.lower()),
            None,
        )
        try:
            pyenv_index = self.path_order.index(last_pyenv)
        except ValueError:
            return
        self.pyenv_finder = PyenvFinder.create(root=PYENV_ROOT)
        # paths = (v.paths.values() for v in self.pyenv_finder.versions.values())
        root_paths = (
            p for path in self.pyenv_finder.expanded_paths for p in path if p.is_root
        )
        before_path = self.path_order[: pyenv_index + 1]
        after_path = self.path_order[pyenv_index + 2 :]
        self.path_order = (
            before_path + [p.path.as_posix() for p in root_paths] + after_path
        )
        self.paths.update({p.path: p for p in root_paths})
        self._register_finder("pyenv", self.pyenv_finder)

    def _setup_windows(self):
        from .windows import WindowsFinder

        self.windows_finder = WindowsFinder.create()
        root_paths = (p for p in self.windows_finder.paths if p.is_root)
        path_addition = [p.path.as_posix() for p in root_paths]
        self.path_order = self.path_order[:] + path_addition
        self.paths.update({p.path: p for p in root_paths})
        self._register_finder("windows", self.windows_finder)

    def get_path(self, path):
        path = ensure_path(path)
        _path = self.paths.get(path.as_posix())
        if not _path and path.as_posix() in self.path_order:
            _path = PathEntry.create(
                path=path.absolute(), is_root=True, only_python=self.only_python
            )
            self.paths[path.as_posix()] = _path
        return _path

    def find_all(self, executable):
        """Search the path for an executable. Return all copies.

        :param executable: Name of the executable
        :type executable: str
        :returns: List[PathEntry]
        """
        sub_which = operator.methodcaller("which", name=executable)
        filtered = filter(None, (sub_which(self.get_path(k)) for k in self.path_order))
        return [f for f in filtered]

    def which(self, executable):
        """Search for an executable on the path.

        :param executable: Name of the executable to be located.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` object.
        """
        sub_which = operator.methodcaller("which", name=executable)
        filtered = filter(None, (sub_which(self.get_path(k)) for k in self.path_order))
        return next((f for f in filtered), None)

    def find_all_python_versions(
        self, major=None, minor=None, patch=None, pre=None, dev=None, arch=None
    ):
        """Search for a specific python version on the path. Return all copies

        :param major: Major python version to search for.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :return: A list of :class:`~pythonfinder.models.PathEntry` instances matching the version requested.
        :rtype: List[:class:`~pythonfinder.models.PathEntry`]
        """

        sub_finder = operator.methodcaller(
            "find_all_python_versions",
            major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
        )
        if os.name == "nt" and self.windows_finder:
            windows_finder_version = sub_finder(self.windows_finder)
            if windows_finder_version:
                return windows_finder_version
        paths = (self.get_path(k) for k in self.path_order)
        path_filter = filter(
            None, unnest((sub_finder(p) for p in paths if p is not None))
        )
        version_sort = operator.attrgetter("as_python.version_sort")
        return [c for c in sorted(path_filter, key=version_sort, reverse=True)]

    def find_python_version(
        self, major=None, minor=None, patch=None, pre=None, dev=None, arch=None
    ):
        """Search for a specific python version on the path.

        :param major: Major python version to search for.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :return: A :class:`~pythonfinder.models.PathEntry` instance matching the version requested.
        :rtype: :class:`~pythonfinder.models.PathEntry`
        """

        sub_finder = operator.methodcaller(
            "find_python_version",
            major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
        )
        if major and minor and patch:
            _tuple_pre = pre if pre is not None else False
            _tuple_dev = dev if dev is not None else False
            version_tuple = (major, minor, patch, _tuple_pre, _tuple_dev)
            version_tuple_pre = (major, minor, patch, True, False)
        if os.name == "nt" and self.windows_finder:
            windows_finder_version = sub_finder(self.windows_finder)
            if windows_finder_version:
                return windows_finder_version
        paths = (self.get_path(k) for k in self.path_order)
        path_filter = filter(None, (sub_finder(p) for p in paths if p is not None))
        version_sort = operator.attrgetter("as_python.version_sort")
        ver = next(
            (c for c in sorted(path_filter, key=version_sort, reverse=True)), None
        )
        if ver:
            if ver.as_python.version_tuple[:5] in self.python_version_dict:
                self.python_version_dict[ver.as_python.version_tuple[:5]].append(ver)
            else:
                self.python_version_dict[ver.as_python.version_tuple[:5]] = [ver]
        return ver

    @classmethod
    def create(cls, path=None, system=False, only_python=False, global_search=True):
        """Create a new :class:`pythonfinder.models.SystemPath` instance.

        :param path: Search path to prepend when searching, defaults to None
        :param path: str, optional
        :param system: Whether to use the running python by default instead of searching, defaults to False
        :param system: bool, optional
        :param only_python: Whether to search only for python executables, defaults to False
        :param only_python: bool, optional
        :return: A new :class:`pythonfinder.models.SystemPath` instance.
        :rtype: :class:`pythonfinder.models.SystemPath`
        """

        path_entries = defaultdict(PathEntry)
        paths = []
        if global_search:
            paths = os.environ.get("PATH").split(os.pathsep)
        if path:
            paths = [path] + paths
        _path_objects = [ensure_path(p.strip('"')) for p in paths]
        paths = [p.as_posix() for p in _path_objects]
        path_entries.update(
            {
                p.as_posix(): PathEntry.create(
                    path=p.absolute(), is_root=True, only_python=only_python
                )
                for p in _path_objects
            }
        )
        return cls(
            paths=path_entries,
            path_order=paths,
            only_python=only_python,
            system=system,
            global_search=global_search,
        )


@attr.s
class PathEntry(BasePath):
    path = attr.ib(default=None, validator=optional_instance_of(Path))
    _children = attr.ib(default=attr.Factory(dict))
    is_root = attr.ib(default=True)
    only_python = attr.ib(default=False)
    py_version = attr.ib(default=None)
    pythons = attr.ib()

    def __str__(self):
        return fs_str("{0}".format(self.path.as_posix()))

    def _filter_children(self):
        if self.only_python:
            children = filter_pythons(self.path)
        else:
            children = self.path.iterdir()
        return children

    @cached_property
    def children(self):
        if not self._children and self.is_dir and self.is_root:
            self._children = {
                child.as_posix(): PathEntry.create(path=child, is_root=False)
                for child in self._filter_children()
            }
        elif not self.is_dir:
            self._children = {self.path.as_posix(): self}
        return self._children

    @pythons.default
    def get_pythons(self):
        pythons = defaultdict()
        if self.is_dir:
            for path, entry in self.children.items():
                _path = ensure_path(entry.path)
                if entry.is_python:
                    pythons[_path.as_posix()] = entry
        else:
            if self.is_python:
                _path = ensure_path(self.path)
                pythons[_path.as_posix()] = copy.deepcopy(self)
        return pythons

    @cached_property
    def as_python(self):
        if not self.is_dir and self.is_python:
            if not self.py_version:
                try:
                    from .python import PythonVersion

                    self.py_version = PythonVersion.from_path(self.path)
                except (ValueError, InvalidPythonVersion):
                    self.py_version = None
        return self.py_version

    @classmethod
    def create(cls, path, is_root=False, only_python=False, pythons=None):
        """Helper method for creating new :class:`pythonfinder.models.PathEntry` instances.

        :param path: Path to the specified location.
        :type path: str
        :param is_root: Whether this is a root from the environment PATH variable, defaults to False
        :param is_root: bool, optional
        :param only_python: Whether to search only for python executables, defaults to False
        :param only_python: bool, optional
        :param pythons: A dictionary of existing python objects (usually from a finder), defaults to None
        :param pythons: dict, optional
        :return: A new instance of the class.
        :rtype: :class:`pythonfinder.models.PathEntry`
        """

        target = ensure_path(path)
        creation_args = {"path": target, "is_root": is_root, "only_python": only_python}
        if pythons:
            creation_args["pythons"] = pythons
        _new = cls(**creation_args)
        if pythons and only_python:
            children = {}
            for pth, python in pythons.items():
                pth = ensure_path(pth)
                children[pth.as_posix()] = PathEntry(
                    path=pth, is_root=False, only_python=only_python, py_version=python
                )
            _new._children = children
        return _new

    @cached_property
    def name(self):
        return self.path.name

    @cached_property
    def is_dir(self):
        try:
            ret_val = self.path.is_dir()
        except OSError:
            ret_val = False
        return ret_val

    @cached_property
    def is_executable(self):
        return path_is_known_executable(self.path)

    @cached_property
    def is_python(self):
        return self.is_executable and (
            self.py_version or looks_like_python(self.path.name)
        )


@attr.s
class VersionPath(SystemPath):
    base = attr.ib(default=None, validator=optional_instance_of(Path))

    @classmethod
    def create(cls, path, only_python=True, pythons=None):
        """Accepts a path to a base python version directory.

        Generates the pyenv version listings for it"""
        path = ensure_path(path)
        path_entries = defaultdict(PathEntry)
        if not path.name.lower() in ["scripts", "bin"]:
            bin_name = "Scripts" if os.name == "nt" else "bin"
            bin_dir = path / bin_name
        else:
            bin_dir = path
        current_entry = PathEntry.create(
            bin_dir, is_root=True, only_python=True, pythons=pythons
        )
        path_entries[bin_dir.as_posix()] = current_entry
        return cls(base=bin_dir, paths=path_entries)
