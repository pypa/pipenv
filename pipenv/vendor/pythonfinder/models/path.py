# -*- coding=utf-8 -*-
import attr
import operator
import os
import sys
from collections import defaultdict
from . import BasePath
from .python import PythonVersion
from ..environment import PYENV_INSTALLED, PYENV_ROOT
from ..utils import (
    optional_instance_of,
    filter_pythons,
    path_is_known_executable,
    is_python_name,
    ensure_path,
)

try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path


@attr.s
class SystemPath(object):
    paths = attr.ib(default=attr.Factory(defaultdict))
    _executables = attr.ib(default=attr.Factory(list))
    _python_executables = attr.ib(default=attr.Factory(list))
    path_order = attr.ib(default=attr.Factory(list))
    python_version_dict = attr.ib()
    only_python = attr.ib(default=False)
    pyenv_finder = attr.ib(default=None, validator=optional_instance_of("PyenvPath"))
    system = attr.ib(default=False)

    @property
    def executables(self):
        if not self._executables:
            self._executables = [p for p in self.paths.values() if p.is_executable]
        return self._executables

    @property
    def python_executables(self):
        if not self._python_executables:
            self._python_executables = [p for p in self.paths.values() if p.is_python]
        return self._python_executables

    @python_version_dict.default
    def get_python_version_dict(self):
        version_dict = defaultdict(list)
        for p in self.python_executables:
            try:
                version_object = PythonVersion.from_path(p)
            except ValueError:
                continue
            version_dict[version_object.version_tuple].append(version_object)
        return version_dict

    def __attrs_post_init__(self):
        #: slice in pyenv
        if not self.__class__ == SystemPath:
            return
        if os.name == "nt":
            self._setup_windows()
        if PYENV_INSTALLED:
            self._setup_pyenv()
        venv = os.environ.get('VIRTUAL_ENV')
        if venv:
            if os.name == 'nt':
                bin_dir = 'Scripts'
            else:
                bin_dir = 'bin'
            p = Path(venv)
            self.path_order = [(p / bin_dir).as_posix()] + self.path_order
            self.paths[p] = PathEntry.create(
                path=p, is_root=True, only_python=False
            )
        if self.system:
            syspath = Path(sys.executable)
            self.path_order = [syspath.parent.as_posix()] + self.path_order
            self.paths[syspath.parent.as_posix()] = PathEntry.create(
                path=syspath.parent, is_root=True, only_python=True
            )

    def _setup_pyenv(self):
        from .pyenv import PyenvFinder

        last_pyenv = next(
            (p for p in reversed(self.path_order) if PYENV_ROOT.lower() in p.lower()),
            None,
        )
        pyenv_index = self.path_order.index(last_pyenv)
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

    def _setup_windows(self):
        from .windows import WindowsFinder

        self.windows_finder = WindowsFinder.create()
        root_paths = (p for p in self.windows_finder.paths if p.is_root)
        path_addition = [p.path.as_posix() for p in root_paths]
        self.path_order = self.path_order[:] + path_addition
        self.paths.update({p.path: p for p in root_paths})

    def get_path(self, path):
        _path = self.paths.get(path)
        if not _path and path in self.path_order:
            self.paths[path] = PathEntry.create(
                path=path, is_root=True, only_python=self.only_python
            )
        return self.paths.get(path)

    def which(self, executable):
        """Search for an executable on the path.

        :param executable: Name of the executable to be located.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` object.
        """
        sub_which = operator.methodcaller("which", name=executable)
        return next(
            (sub_which(self.get_path(k)) for k in self.path_order), None
        )

    def find_python_version(self, major, minor=None, patch=None, pre=None, dev=None):
        """Search for a specific python version on the path.

        :param major: Major python version to search for.
        :type major: int
        :param minor: Minor python version to search for, defaults to None
        :param minor: int, optional
        :param path: Patch python version to search for, defaults to None
        :param path: int, optional
        :return: A :class:`~pythonfinder.models.PathEntry` instance matching the version requested.
        :rtype: :class:`~pythonfinder.models.PathEntry`
        """

        sub_finder = operator.methodcaller(
            "find_python_version", major, minor=minor, patch=patch, pre=pre, dev=dev
        )
        if os.name == "nt" and self.windows_finder:
            windows_finder_version = sub_finder(self.windows_finder)
            if windows_finder_version:
                return windows_finder_version
        paths = [self.get_path(k) for k in self.path_order]
        path_filter = filter(None, [sub_finder(p) for p in paths])
        version_sort = operator.attrgetter("as_python.version")
        return next(
            (c for c in sorted(path_filter, key=version_sort, reverse=True)), None
        )

    @classmethod
    def create(cls, path=None, system=False, only_python=False):
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
        paths = os.environ.get("PATH").split(os.pathsep)
        if path:
            paths = [path] + paths
        _path_objects = [ensure_path(p.strip('"')) for p in paths]
        paths = [p.as_posix() for p in _path_objects]
        path_entries.update(
            {
                p.as_posix(): PathEntry.create(
                    path=p, is_root=True, only_python=only_python
                )
                for p in _path_objects
            }
        )
        return cls(paths=path_entries, path_order=paths, only_python=only_python, system=system)


@attr.s
class PathEntry(BasePath):
    path = attr.ib(default=None, validator=optional_instance_of(Path))
    _children = attr.ib(default=attr.Factory(dict))
    is_root = attr.ib(default=True)
    only_python = attr.ib(default=False)
    py_version = attr.ib(default=None)
    pythons = attr.ib(default=None)

    def _filter_children(self):
        if self.only_python:
            children = filter_pythons(self.path)
        else:
            children = self.path.iterdir()
        return children

    @property
    def children(self):
        if not self._children and self.is_dir and self.is_root:
            self._children = {
                child.as_posix(): PathEntry(path=child, is_root=False)
                for child in self._filter_children()
            }
        return self._children

    @property
    def as_python(self):
        if not self.is_dir and self.is_python:
            if not self.py_version:
                try:
                    from .python import PythonVersion

                    self.py_version = PythonVersion.from_path(self.path)
                except ValueError:
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
        _new = cls(
            path=target, is_root=is_root, only_python=only_python, pythons=pythons
        )
        if pythons and only_python:
            children = {}
            for pth, python in pythons.items():
                pth = ensure_path(pth)
                children[pth.as_posix()] = PathEntry(
                    path=pth, is_root=False, only_python=only_python, py_version=python
                )
            _new._children = children
        return _new

    @property
    def name(self):
        return self.path.name

    @property
    def is_dir(self):
        return self.path.is_dir()

    @property
    def is_executable(self):
        return path_is_known_executable(self.path)

    @property
    def is_python(self):
        return self.is_executable and (
            self.py_version or is_python_name(self.path.name)
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
