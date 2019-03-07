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

from .mixins import BaseFinder, BasePath
from .python import PythonVersion
from ..environment import (
    ASDF_DATA_DIR,
    ASDF_INSTALLED,
    MYPY_RUNNING,
    PYENV_INSTALLED,
    PYENV_ROOT,
    SHIM_PATHS,
)
from ..exceptions import InvalidPythonVersion
from ..utils import (
    Iterable,
    Sequence,
    ensure_path,
    expand_paths,
    filter_pythons,
    is_in_path,
    looks_like_python,
    normalize_path,
    optional_instance_of,
    parse_asdf_version_order,
    parse_pyenv_version_order,
    path_is_known_executable,
    unnest,
)

if MYPY_RUNNING:
    from typing import (
        Optional,
        Dict,
        DefaultDict,
        Iterator,
        List,
        Union,
        Tuple,
        Generator,
        Callable,
        Type,
        Any,
        TypeVar,
    )
    from .python import PythonFinder
    from .windows import WindowsFinder

    FinderType = TypeVar("FinderType", BaseFinder, PythonFinder, WindowsFinder)
    ChildType = Union[PythonFinder, "PathEntry"]
    PathType = Union[PythonFinder, "PathEntry"]


@attr.s
class SystemPath(object):
    global_search = attr.ib(default=True)
    paths = attr.ib(
        default=attr.Factory(defaultdict)
    )  # type: DefaultDict[str, Union[PythonFinder, PathEntry]]
    _executables = attr.ib(default=attr.Factory(list))  # type: List[PathEntry]
    _python_executables = attr.ib(
        default=attr.Factory(dict)
    )  # type: Dict[str, PathEntry]
    path_order = attr.ib(default=attr.Factory(list))  # type: List[str]
    python_version_dict = attr.ib()  # type: DefaultDict[Tuple, List[PythonVersion]]
    only_python = attr.ib(default=False, type=bool)
    pyenv_finder = attr.ib(
        default=None, validator=optional_instance_of("PythonFinder")
    )  # type: Optional[PythonFinder]
    asdf_finder = attr.ib(default=None)  # type: Optional[PythonFinder]
    system = attr.ib(default=False, type=bool)
    _version_dict = attr.ib(
        default=attr.Factory(defaultdict)
    )  # type: DefaultDict[Tuple, List[PathEntry]]
    ignore_unsupported = attr.ib(default=False, type=bool)

    __finders = attr.ib(
        default=attr.Factory(dict)
    )  # type: Dict[str, Union[WindowsFinder, PythonFinder]]

    def _register_finder(self, finder_name, finder):
        # type: (str, Union[WindowsFinder, PythonFinder]) -> None
        if finder_name not in self.__finders:
            self.__finders[finder_name] = finder

    def clear_caches(self):
        for key in ["executables", "python_executables", "version_dict", "path_entries"]:
            if key in self.__dict__:
                del self.__dict__[key]
        self._executables = []
        self._python_executables = {}
        self.python_version_dict = defaultdict(list)
        self._version_dict = defaultdict(list)

    def __del__(self):
        self.clear_caches()
        self.path_order = []
        self.pyenv_finder = None
        self.asdf_finder = None
        self.paths = defaultdict(PathEntry)

    @property
    def finders(self):
        # type: () -> List[str]
        return [k for k in self.__finders.keys()]

    @python_version_dict.default
    def create_python_version_dict(self):
        # type: () -> DefaultDict[Tuple, List[PythonVersion]]
        return defaultdict(list)

    @cached_property
    def executables(self):
        # type: () -> List[PathEntry]
        self.executables = [
            p
            for p in chain(*(child.children.values() for child in self.paths.values()))
            if p.is_executable
        ]
        return self.executables

    @cached_property
    def python_executables(self):
        # type: () -> Dict[str, PathEntry]
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
        # type: () -> DefaultDict[Tuple, List[PathEntry]]
        self._version_dict = defaultdict(
            list
        )  # type: DefaultDict[Tuple, List[PathEntry]]
        for finder_name, finder in self.__finders.items():
            for version, entry in finder.versions.items():
                if finder_name == "windows":
                    if entry not in self._version_dict[version]:
                        self._version_dict[version].append(entry)
                    continue
                if entry not in self._version_dict[version] and entry.is_python:
                    self._version_dict[version].append(entry)
        for p, entry in self.python_executables.items():
            version = entry.as_python
            if not version:
                continue
            if not isinstance(version, tuple):
                version = version.version_tuple
            if version and entry not in self._version_dict[version]:
                self._version_dict[version].append(entry)
        return self._version_dict

    def __attrs_post_init__(self):
        # type: () -> None
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
            self.paths[p] = self.get_path(p.joinpath(bin_dir))
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
        # type: (str) -> int
        reversed_paths = reversed(self.path_order)
        paths = [normalize_path(p) for p in reversed_paths]
        normalized_target = normalize_path(path)
        last_instance = next(iter(p for p in paths if normalized_target in p), None)
        if last_instance is None:
            raise ValueError("No instance found on path for target: {0!s}".format(path))
        path_index = self.path_order.index(last_instance)
        return path_index

    def _slice_in_paths(self, start_idx, paths):
        # type: (int, List[Path]) -> None
        before_path = []  # type: List[str]
        after_path = []  # type: List[str]
        if start_idx == 0:
            after_path = self.path_order[:]
        elif start_idx == -1:
            before_path = self.path_order[:]
        else:
            before_path = self.path_order[: start_idx + 1]
            after_path = self.path_order[start_idx + 2 :]
        self.path_order = before_path + [p.as_posix() for p in paths] + after_path

    def _remove_path(self, path):
        # type: (str) -> None
        path_copy = [p for p in reversed(self.path_order[:])]
        new_order = []
        target = normalize_path(path)
        path_map = {normalize_path(pth): pth for pth in self.paths.keys()}
        if target in path_map:
            del self.paths[path_map[target]]
        for current_path in path_copy:
            normalized = normalize_path(current_path)
            if normalized != target:
                new_order.append(normalized)
        new_order = [p for p in reversed(new_order)]
        self.path_order = new_order

    def _setup_asdf(self):
        # type: () -> None
        from .python import PythonFinder

        os_path = os.environ["PATH"].split(os.pathsep)
        self.asdf_finder = PythonFinder.create(
            root=ASDF_DATA_DIR,
            ignore_unsupported=True,
            sort_function=parse_asdf_version_order,
            version_glob_path="installs/python/*",
        )
        asdf_index = None
        try:
            asdf_index = self._get_last_instance(ASDF_DATA_DIR)
        except ValueError:
            pyenv_index = 0 if is_in_path(next(iter(os_path), ""), PYENV_ROOT) else -1
        if asdf_index is None:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return
        root_paths = [p for p in self.asdf_finder.roots]
        self._slice_in_paths(asdf_index, [self.asdf_finder.root])
        self.paths[self.asdf_finder.root] = self.asdf_finder
        self.paths.update(self.asdf_finder.roots)
        self._remove_path(normalize_path(os.path.join(ASDF_DATA_DIR, "shims")))
        self._register_finder("asdf", self.asdf_finder)

    def reload_finder(self, finder_name):
        # type: (str) -> None
        if finder_name is None:
            raise TypeError("Must pass a string as the name of the target finder")
        finder_attr = "{0}_finder".format(finder_name)
        setup_attr = "_setup_{0}".format(finder_name)
        try:
            current_finder = getattr(self, finder_attr)  # type: Any
        except AttributeError:
            raise ValueError("Must pass a valid finder to reload.")
        try:
            setup_fn = getattr(self, setup_attr)
        except AttributeError:
            raise ValueError("Finder has no valid setup function: %s" % finder_name)
        if current_finder is None:
            # TODO: This is called 'reload', should we load a new finder for the first
            # time here? lets just skip that for now to avoid unallowed finders
            pass
        if (finder_name == "pyenv" and not PYENV_INSTALLED) or (
            finder_name == "asdf" and not ASDF_INSTALLED
        ):
            # Don't allow loading of finders that aren't explicitly 'installed' as it were
            pass
        setattr(self, finder_attr, None)
        if finder_name in self.__finders:
            del self.__finders[finder_name]
        setup_fn()

    def _setup_pyenv(self):
        # type: () -> None
        from .python import PythonFinder

        os_path = os.environ["PATH"].split(os.pathsep)

        self.pyenv_finder = PythonFinder.create(
            root=PYENV_ROOT,
            sort_function=parse_pyenv_version_order,
            version_glob_path="versions/*",
            ignore_unsupported=self.ignore_unsupported,
        )
        pyenv_index = None
        try:
            pyenv_index = self._get_last_instance(PYENV_ROOT)
        except ValueError:
            pyenv_index = 0 if is_in_path(next(iter(os_path), ""), PYENV_ROOT) else -1
        if pyenv_index is None:
            # we are in a virtualenv without global pyenv on the path, so we should
            # not write pyenv to the path here
            return

        root_paths = [p for p in self.pyenv_finder.roots]
        self._slice_in_paths(pyenv_index, [self.pyenv_finder.root])
        self.paths[self.pyenv_finder.root] = self.pyenv_finder
        self.paths.update(self.pyenv_finder.roots)
        self._remove_path(os.path.join(PYENV_ROOT, "shims"))
        self._register_finder("pyenv", self.pyenv_finder)

    def _setup_windows(self):
        # type: () -> None
        from .windows import WindowsFinder

        self.windows_finder = WindowsFinder.create()
        root_paths = (p for p in self.windows_finder.paths if p.is_root)
        path_addition = [p.path.as_posix() for p in root_paths]
        self.path_order = self.path_order[:] + path_addition
        self.paths.update({p.path: p for p in root_paths})
        self._register_finder("windows", self.windows_finder)

    def get_path(self, path):
        # type: (Union[str, Path]) -> PathType
        if path is None:
            raise TypeError("A path must be provided in order to generate a path entry.")
        path = ensure_path(path)
        _path = self.paths.get(path)
        if not _path:
            _path = self.paths.get(path.as_posix())
        if not _path and path.as_posix() in self.path_order:
            _path = PathEntry.create(
                path=path.absolute(), is_root=True, only_python=self.only_python
            )
            self.paths[path.as_posix()] = _path
        if not _path:
            raise ValueError("Path not found or generated: {0!r}".format(path))
        return _path

    def _get_paths(self):
        # type: () -> Iterator
        for path in self.path_order:
            try:
                entry = self.get_path(path)
            except ValueError:
                continue
            else:
                yield entry

    @cached_property
    def path_entries(self):
        # type: () -> List[Union[PathEntry, FinderType]]
        paths = list(self._get_paths())
        return paths

    def find_all(self, executable):
        # type: (str) -> List[Union[PathEntry, FinderType]]
        """
        Search the path for an executable. Return all copies.

        :param executable: Name of the executable
        :type executable: str
        :returns: List[PathEntry]
        """

        sub_which = operator.methodcaller("which", executable)
        filtered = (sub_which(self.get_path(k)) for k in self.path_order)
        return list(filtered)

    def which(self, executable):
        # type: (str) -> Union[PathEntry, None]
        """
        Search for an executable on the path.

        :param executable: Name of the executable to be located.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` object.
        """

        sub_which = operator.methodcaller("which", executable)
        filtered = (sub_which(self.get_path(k)) for k in self.path_order)
        return next(iter(f for f in filtered if f is not None), None)

    def _filter_paths(self, finder):
        # type: (Callable) -> Iterator
        for path in self._get_paths():
            if path is None:
                continue
            python_versions = finder(path)
            if python_versions is not None:
                for python in python_versions:
                    if python is not None:
                        yield python

    def _get_all_pythons(self, finder):
        # type: (Callable) -> Iterator
        for python in self._filter_paths(finder):
            if python is not None and python.is_python:
                yield python

    def get_pythons(self, finder):
        # type: (Callable) -> Iterator
        sort_key = operator.attrgetter("as_python.version_sort")
        pythons = [entry for entry in self._get_all_pythons(finder)]
        for python in sorted(pythons, key=sort_key, reverse=True):
            if python is not None:
                yield python

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
        # type (...) -> List[PathEntry]
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
            "find_all_python_versions", major, minor, patch, pre, dev, arch, name
        )
        alternate_sub_finder = None
        if major and not (minor or patch or pre or dev or arch or name):
            alternate_sub_finder = operator.methodcaller(
                "find_all_python_versions", None, None, None, None, None, None, major
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
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[Union[str, int]]
        patch=None,  # type: Optional[Union[str, int]]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
    ):
        # type: (...) -> PathEntry
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
            if major.isdigit() or (major.count(".") > 0 and major[0].isdigit()):
                version = major.split(".", 2)
                if isinstance(version, (tuple, list)):
                    if len(version) > 3:
                        major, minor, patch, rest = version
                    elif len(version) == 3:
                        major, minor, patch = version
                    elif len(version) == 2:
                        major, minor = version
                    else:
                        major = major[0]
                else:
                    major = major
                    name = None
            else:
                name = "{0!s}".format(major)
                major = None
        sub_finder = operator.methodcaller(
            "find_python_version", major, minor, patch, pre, dev, arch, name
        )
        alternate_sub_finder = None
        if name and not (minor or patch or pre or dev or arch or major):
            alternate_sub_finder = operator.methodcaller(
                "find_all_python_versions", None, None, None, None, None, None, name
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
        path=None,  # type: str
        system=False,  # type: bool
        only_python=False,  # type: bool
        global_search=True,  # type: bool
        ignore_unsupported=True,  # type: bool
    ):
        # type: (...) -> SystemPath
        """Create a new :class:`pythonfinder.models.SystemPath` instance.

        :param path: Search path to prepend when searching, defaults to None
        :param path: str, optional
        :param bool system: Whether to use the running python by default instead of searching, defaults to False
        :param bool only_python: Whether to search only for python executables, defaults to False
        :param bool ignore_unsupported: Whether to ignore unsupported python versions, if False, an error is raised, defaults to True
        :return: A new :class:`pythonfinder.models.SystemPath` instance.
        :rtype: :class:`pythonfinder.models.SystemPath`
        """

        path_entries = defaultdict(
            PathEntry
        )  # type: DefaultDict[str, Union[PythonFinder, PathEntry]]
        paths = []  # type: List[str]
        if ignore_unsupported:
            os.environ["PYTHONFINDER_IGNORE_UNSUPPORTED"] = fs_str("1")
        if global_search:
            if "PATH" in os.environ:
                paths = os.environ["PATH"].split(os.pathsep)
        if path:
            paths = [path] + paths
        paths = [p for p in paths if not any(is_in_path(p, shim) for shim in SHIM_PATHS)]
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
            ignore_unsupported=ignore_unsupported,
        )


@attr.s(slots=True)
class PathEntry(BasePath):
    is_root = attr.ib(default=True, type=bool)

    def __del__(self):
        if "_children" in self.__dict__:
            del self.__dict__["_children"]
        BasePath.__del__(self)

    def _filter_children(self):
        # type: () -> Iterator[Path]
        if self.only_python:
            children = filter_pythons(self.path)
        else:
            children = self.path.iterdir()
        return children

    def _gen_children(self):
        # type: () -> Iterator
        from ..environment import get_shim_paths

        shim_paths = get_shim_paths()
        pass_name = self.name != self.path.name
        pass_args = {"is_root": False, "only_python": self.only_python}
        if pass_name:
            if self.name is not None and isinstance(self.name, six.string_types):
                pass_args["name"] = self.name  # type: ignore
            elif self.path is not None and isinstance(self.path.name, six.string_types):
                pass_args["name"] = self.path.name  # type: ignore

        if not self.is_dir:
            yield (self.path.as_posix(), self)
        elif self.is_root:
            for child in self._filter_children():
                if any(is_in_path(str(child), shim) for shim in shim_paths):
                    continue
                if self.only_python:
                    try:
                        entry = PathEntry.create(path=child, **pass_args)  # type: ignore
                    except (InvalidPythonVersion, ValueError):
                        continue
                else:
                    entry = PathEntry.create(path=child, **pass_args)  # type: ignore
                yield (child.as_posix(), entry)
        return

    @cached_property
    def children(self):
        # type: () -> Dict[str, PathEntry]
        children = getattr(self, "_children", {})  # type: Dict[str, PathEntry]
        if not children:
            for child_key, child_val in self._gen_children():
                children[child_key] = child_val
            self._children = children
        return self._children

    @classmethod
    def create(cls, path, is_root=False, only_python=False, pythons=None, name=None):
        # type: (Union[str, Path], bool, bool, Dict[str, PythonVersion], Optional[str]) -> PathEntry
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
        creation_args = {
            "path": target,
            "is_root": is_root,
            "only_python": only_python,
            "name": name,
        }
        if pythons:
            creation_args["pythons"] = pythons
        _new = cls(**creation_args)
        if pythons and only_python:
            children = {}
            child_creation_args = {"is_root": False, "only_python": only_python}
            if not guessed_name:
                child_creation_args["name"] = _new.name  # type: ignore
            for pth, python in pythons.items():
                if any(shim in normalize_path(str(pth)) for shim in SHIM_PATHS):
                    continue
                pth = ensure_path(pth)
                children[pth.as_posix()] = PathEntry(  # type: ignore
                    py_version=python, path=pth, **child_creation_args
                )
            _new._children = children
        return _new


@attr.s
class VersionPath(SystemPath):
    base = attr.ib(default=None, validator=optional_instance_of(Path))  # type: Path
    name = attr.ib(default=None)  # type: str

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
