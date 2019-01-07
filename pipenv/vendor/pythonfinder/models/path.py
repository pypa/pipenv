# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import copy
import operator
import os
import sys

from collections import defaultdict
from itertools import chain

import attr
import six

from cached_property import cached_property

from vistir.compat import Path, fs_str

from .mixins import BasePath
from ..environment import PYENV_INSTALLED, PYENV_ROOT, ASDF_INSTALLED, ASDF_DATA_DIR
from ..exceptions import InvalidPythonVersion
from ..utils import (
    ensure_path,
    filter_pythons,
    looks_like_python,
    optional_instance_of,
    path_is_known_executable,
    unnest,
    normalize_path,
    parse_pyenv_version_order,
    parse_asdf_version_order
)
from .python import PythonVersion


ASDF_SHIM_PATH = normalize_path(os.path.join(ASDF_DATA_DIR, "shims"))
PYENV_SHIM_PATH = normalize_path(os.path.join(PYENV_ROOT, "shims"))
SHIM_PATHS = [ASDF_SHIM_PATH, PYENV_SHIM_PATH]


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
    asdf_finder = attr.ib(default=None)
    system = attr.ib(default=False)
    _version_dict = attr.ib(default=attr.Factory(defaultdict))
    ignore_unsupported = attr.ib(default=False)

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
                if type(entry).__name__ == "VersionPath":
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
        if ASDF_INSTALLED:
            self._setup_asdf()
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

    def _get_last_instance(self, path):
        reversed_paths = reversed(self.path_order)
        paths = [normalize_path(p) for p in reversed_paths]
        normalized_target = normalize_path(path)
        last_instance = next(
            iter(p for p in paths if normalized_target in p), None
        )
        try:
            path_index = self.path_order.index(last_instance)
        except ValueError:
            return
        return path_index

    def _slice_in_paths(self, start_idx, paths):
        before_path = self.path_order[: start_idx + 1]
        after_path = self.path_order[start_idx + 2 :]
        self.path_order = (
            before_path + [p.as_posix() for p in paths] + after_path
        )

    def _remove_path(self, path):
        path_copy = [p for p in reversed(self.path_order[:])]
        new_order = []
        target = normalize_path(path)
        path_map = {
            normalize_path(pth): pth
            for pth in self.paths.keys()
        }
        if target in path_map:
            del self.paths[path_map.get(target)]
        for current_path in path_copy:
            normalized = normalize_path(current_path)
            if normalized != target:
                new_order.append(normalized)
        new_order = [p for p in reversed(new_order)]
        self.path_order = new_order

    def _setup_asdf(self):
        from .python import PythonFinder
        self.asdf_finder = PythonFinder.create(
            root=ASDF_DATA_DIR, ignore_unsupported=True,
            sort_function=parse_asdf_version_order, version_glob_path="installs/python/*")
        asdf_index = self._get_last_instance(ASDF_DATA_DIR)
        if not asdf_index:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return
        root_paths = [p for p in self.asdf_finder.roots]
        self._slice_in_paths(asdf_index, root_paths)
        self.paths.update(self.asdf_finder.roots)
        self._remove_path(normalize_path(os.path.join(ASDF_DATA_DIR, "shims")))
        self._register_finder("asdf", self.asdf_finder)

    def _setup_pyenv(self):
        from .python import PythonFinder

        self.pyenv_finder = PythonFinder.create(
            root=PYENV_ROOT, sort_function=parse_pyenv_version_order,
            version_glob_path="versions/*", ignore_unsupported=self.ignore_unsupported
        )
        pyenv_index = self._get_last_instance(PYENV_ROOT)
        if not pyenv_index:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return
        root_paths = [p for p in self.pyenv_finder.roots]
        self._slice_in_paths(pyenv_index, root_paths)

        self.paths.update(self.pyenv_finder.roots)
        self._remove_path(os.path.join(PYENV_ROOT, "shims"))
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
        _path = self.paths.get(path)
        if not _path:
            _path = self.paths.get(path.as_posix())
        if not _path and path.as_posix() in self.path_order:
            _path = PathEntry.create(
                path=path.absolute(), is_root=True, only_python=self.only_python
            )
            self.paths[path.as_posix()] = _path
        return _path

    def _get_paths(self):
        return (self.get_path(k) for k in self.path_order)

    @cached_property
    def path_entries(self):
        paths = self._get_paths()
        return paths

    def find_all(self, executable):
        """Search the path for an executable. Return all copies.

        :param executable: Name of the executable
        :type executable: str
        :returns: List[PathEntry]
        """
        sub_which = operator.methodcaller("which", name=executable)
        filtered = (sub_which(self.get_path(k)) for k in self.path_order)
        return list(filtered)

    def which(self, executable):
        """Search for an executable on the path.

        :param executable: Name of the executable to be located.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` object.
        """
        sub_which = operator.methodcaller("which", name=executable)
        filtered = (sub_which(self.get_path(k)) for k in self.path_order)
        return next(iter(f for f in filtered if f is not None), None)

    def _filter_paths(self, finder):
        return (
            pth for pth in unnest(finder(p) for p in self.path_entries if p is not None)
            if pth is not None
        )

    def _get_all_pythons(self, finder):
        paths = {p.path.as_posix(): p for p in self._filter_paths(finder)}
        paths.update(self.python_executables)
        return (p for p in paths.values() if p is not None)

    def get_pythons(self, finder):
        sort_key = operator.attrgetter("as_python.version_sort")
        return (
            k for k in sorted(
                (p for p in self._filter_paths(finder) if p.is_python),
                key=sort_key,
                reverse=True
            ) if k is not None
        )

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

        sub_finder = operator.methodcaller(
            "find_all_python_versions",
            major=major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
            name=name,
        )
        alternate_sub_finder = None
        if major and not (minor or patch or pre or dev or arch or name):
            alternate_sub_finder = operator.methodcaller(
                "find_all_python_versions",
                major=None,
                name=major
            )
        if os.name == "nt" and self.windows_finder:
            windows_finder_version = sub_finder(self.windows_finder)
            if windows_finder_version:
                return windows_finder_version
        values = list(self.get_pythons(sub_finder))
        if not values and alternate_sub_finder is not None:
            values = list(self.get_pythons(alternate_sub_finder))
        return values

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
        """Search for a specific python version on the path.

        :param major: Major python version to search for.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :param str name: The name of a python version, e.g. ``anaconda3-5.3.0``
        :return: A :class:`~pythonfinder.models.PathEntry` instance matching the version requested.
        :rtype: :class:`~pythonfinder.models.PathEntry`
        """

        if isinstance(major, six.string_types) and not minor and not patch:
            # Only proceed if this is in the format "x.y.z" or similar
            if major.count(".") > 0 and major[0].isdigit():
                version = major.split(".", 2)
                if len(version) > 3:
                    major, minor, patch, rest = version
                elif len(version) == 3:
                    major, minor, patch = version
                else:
                    major, minor = version
            else:
                name = "{0!s}".format(major)
                major = None
        sub_finder = operator.methodcaller(
            "find_python_version",
            major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
            name=name,
        )
        alternate_sub_finder = None
        if major and not (minor or patch or pre or dev or arch or name):
            alternate_sub_finder = operator.methodcaller(
                "find_all_python_versions",
                major=None,
                name=major
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
        ver = next(iter(self.get_pythons(sub_finder)), None)
        if not ver and alternate_sub_finder is not None:
            ver = next(iter(self.get_pythons(alternate_sub_finder)), None)
        if ver:
            if ver.as_python.version_tuple[:5] in self.python_version_dict:
                self.python_version_dict[ver.as_python.version_tuple[:5]].append(ver)
            else:
                self.python_version_dict[ver.as_python.version_tuple[:5]] = [ver]
        return ver

    @classmethod
    def create(
        cls,
        path=None,
        system=False,
        only_python=False,
        global_search=True,
        ignore_unsupported=True,
    ):
        """Create a new :class:`pythonfinder.models.SystemPath` instance.

        :param path: Search path to prepend when searching, defaults to None
        :param path: str, optional
        :param bool system: Whether to use the running python by default instead of searching, defaults to False
        :param bool only_python: Whether to search only for python executables, defaults to False
        :param bool ignore_unsupported: Whether to ignore unsupported python versions, if False, an error is raised, defaults to True
        :return: A new :class:`pythonfinder.models.SystemPath` instance.
        :rtype: :class:`pythonfinder.models.SystemPath`
        """

        path_entries = defaultdict(PathEntry)
        paths = []
        if ignore_unsupported:
            os.environ["PYTHONFINDER_IGNORE_UNSUPPORTED"] = fs_str("1")
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
                if not any(shim in normalize_path(str(p)) for shim in SHIM_PATHS)
            }
        )
        return cls(
            paths=path_entries,
            path_order=paths,
            only_python=only_python,
            system=system,
            global_search=global_search,
            ignore_unsupported=ignore_unsupported,
        )


@attr.s(slots=True)
class PathEntry(BasePath):
    path = attr.ib(default=None, validator=optional_instance_of(Path))
    _children = attr.ib(default=attr.Factory(dict))
    is_root = attr.ib(default=True)
    only_python = attr.ib(default=False)
    name = attr.ib()
    py_version = attr.ib()
    _pythons = attr.ib(default=attr.Factory(defaultdict))

    def __str__(self):
        return fs_str("{0}".format(self.path.as_posix()))

    def _filter_children(self):
        if self.only_python:
            children = filter_pythons(self.path)
        else:
            children = self.path.iterdir()
        return children

    def _gen_children(self):
        pass_name = self.name != self.path.name
        pass_args = {"is_root": False, "only_python": self.only_python}
        if pass_name:
            pass_args["name"] = self.name

        if not self.is_dir:
            yield (self.path.as_posix(), copy.deepcopy(self))
        elif self.is_root:
            for child in self._filter_children():
                if any(shim in normalize_path(str(child)) for shim in SHIM_PATHS):
                    continue
                if self.only_python:
                    try:
                        entry = PathEntry.create(path=child, **pass_args)
                    except (InvalidPythonVersion, ValueError):
                        continue
                else:
                    entry = PathEntry.create(path=child, **pass_args)
                yield (child.as_posix(), entry)
        return

    @cached_property
    def children(self):
        if not self._children:
            children = {}
            for child_key, child_val in self._gen_children():
                children[child_key] = child_val
            self._children = children
        return self._children

    @name.default
    def get_name(self):
        return self.path.name

    @py_version.default
    def get_py_version(self):
        from ..environment import IGNORE_UNSUPPORTED
        if self.is_dir:
            return None
        if self.is_python:
            py_version = None
            try:
                py_version = PythonVersion.from_path(path=self, name=self.name)
            except (InvalidPythonVersion, ValueError):
                py_version = None
            except Exception:
                if not IGNORE_UNSUPPORTED:
                    raise
            return py_version
        return

    @property
    def pythons(self):
        if not self._pythons:
            if self.is_dir:
                for path, entry in self.children.items():
                    _path = ensure_path(entry.path)
                    if entry.is_python:
                        self._pythons[_path.as_posix()] = entry
            else:
                if self.is_python:
                    _path = ensure_path(self.path)
                    self._pythons[_path.as_posix()] = self
        return self._pythons

    @cached_property
    def as_python(self):
        py_version = None
        if self.py_version:
            return self.py_version
        if not self.is_dir and self.is_python:
            try:
                from .python import PythonVersion
                py_version = PythonVersion.from_path(path=attr.evolve(self), name=self.name)
            except (ValueError, InvalidPythonVersion):
                py_version = None
        return py_version

    @classmethod
    def create(cls, path, is_root=False, only_python=False, pythons=None, name=None):
        """Helper method for creating new :class:`pythonfinder.models.PathEntry` instances.

        :param str path: Path to the specified location.
        :param bool is_root: Whether this is a root from the environment PATH variable, defaults to False
        :param bool only_python: Whether to search only for python executables, defaults to False
        :param dict pythons: A dictionary of existing python objects (usually from a finder), defaults to None
        :param str name: Name of the python version, e.g. ``anaconda3-5.3.0``
        :return: A new instance of the class.
        :rtype: :class:`pythonfinder.models.PathEntry`
        """

        target = ensure_path(path)
        guessed_name = False
        if not name:
            guessed_name = True
            name = target.name
        creation_args = {"path": target, "is_root": is_root, "only_python": only_python, "name": name}
        if pythons:
            creation_args["pythons"] = pythons
        _new = cls(**creation_args)
        if pythons and only_python:
            children = {}
            child_creation_args = {
                "is_root": False,
                "only_python": only_python
            }
            if not guessed_name:
                child_creation_args["name"] = name
            for pth, python in pythons.items():
                if any(shim in normalize_path(str(pth)) for shim in SHIM_PATHS):
                    continue
                pth = ensure_path(pth)
                children[pth.as_posix()] = PathEntry(
                    py_version=python,
                    path=pth,
                    **child_creation_args
                )
            _new._children = children
        return _new

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
            looks_like_python(self.path.name)
        )


@attr.s
class VersionPath(SystemPath):
    base = attr.ib(default=None, validator=optional_instance_of(Path))
    name = attr.ib(default=None)

    @classmethod
    def create(cls, path, only_python=True, pythons=None, name=None):
        """Accepts a path to a base python version directory.

        Generates the version listings for it"""
        from .path import PathEntry
        path = ensure_path(path)
        path_entries = defaultdict(PathEntry)
        bin_ = "{base}/bin"
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
