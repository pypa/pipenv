import logging
import operator
import os
import platform
import sys
from collections import defaultdict
from pathlib import Path, WindowsPath
from typing import Callable, DefaultDict, Dict, List, Optional, Tuple, Union, Generator, Iterator

from pipenv.patched.pip._vendor.packaging.version import Version
from pipenv.vendor.pydantic import BaseModel, Field, validator

from ..environment import ASDF_DATA_DIR, PYENV_ROOT, SYSTEM_ARCH
from ..exceptions import InvalidPythonVersion
from ..utils import (
    ensure_path,
    expand_paths,
    get_python_version,
    guess_company,
    is_in_path,
    looks_like_python,
    parse_asdf_version_order,
    parse_pyenv_version_order,
    parse_python_version,
    unnest,
)
from .mixins import PathEntry


logger = logging.getLogger(__name__)


class PythonFinder(PathEntry):
    root: Path
    ignore_unsupported: bool = True
    version_glob_path: str = "versions/*"
    sort_function: Optional[Callable] = None
    roots: Dict = Field(default_factory=lambda: defaultdict())
    paths: List = Field(default_factory=lambda: list())
    shim_dir: str = "shims"
    versions: Dict = Field(default_factory=lambda: defaultdict())

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        # keep_untouched = (cached_property,)

    def __init__(self, **data):
        super().__init__(**data)
        if not self.children:
            self.children = children = {}
            for child_key, child_val in self._gen_children():
                children[child_key] = child_val
            self.children = children
        if not self.pythons:
            self.pythons = defaultdict(PathEntry)
            for python in self._iter_pythons():
                python_path = python.path.as_posix()
                self.pythons[python_path] = python

    @validator('root', pre=True, always=True)
    def optional_instance_of_path(cls, value):
        if value is not None:
            return Path(value)
        return None

    @property
    def expanded_paths(self):
        # type: () -> Generator
        return (
            path for path in unnest(p for p in self.versions.values()) if path is not None
        )

    @property
    def is_pyenv(self):
        # type: () -> bool
        return is_in_path(str(self.root), PYENV_ROOT)

    @property
    def is_asdf(self):
        # type: () -> bool
        return is_in_path(str(self.root), ASDF_DATA_DIR)

    def get_version_order(self):
        # type: () -> List[Path]
        version_paths = [
            p
            for p in self.root.glob(self.version_glob_path)
            if not (p.parent.name == "envs" or p.name == "envs")
        ]
        versions = {v.name: v for v in version_paths}
        version_order = []  # type: List[Path]
        if self.is_pyenv:
            version_order = [
                versions[v] for v in parse_pyenv_version_order() if v in versions
            ]
        elif self.is_asdf:
            version_order = [
                versions[v] for v in parse_asdf_version_order() if v in versions
            ]
        for version in version_order:
            if version in version_paths:
                version_paths.remove(version)
        if version_order:
            version_order += version_paths
        else:
            version_order = version_paths
        return version_order

    def get_bin_dir(self, base):
        # type: (Union[Path, str]) -> Path
        if isinstance(base, str):
            base = Path(base)
        if os.name == "nt":
            return base
        return base / "bin"

    @classmethod
    def version_from_bin_dir(cls, entry) -> Optional[PathEntry]:
        py_version = next(iter(entry.find_all_python_versions()), None)
        return py_version

    def _iter_version_bases(self) -> Iterator[Tuple[Path, PathEntry]]:
        for p in self.get_version_order():
            bin_dir = self.get_bin_dir(p)
            if bin_dir.exists() and bin_dir.is_dir():
                entry = PathEntry.create(
                    path=bin_dir.absolute(), only_python=False, name=p.name, is_root=True
                )
                self.roots[p] = entry
                yield (p, entry)

    def _iter_versions(self) -> Iterator[Tuple[Path, PathEntry, Tuple]]:
        for base_path, entry in self._iter_version_bases():
            version = None
            version_entry = None
            try:
                version = PythonVersion.parse(entry.name)
            except (ValueError, InvalidPythonVersion):
                version_entry = next(iter(entry.find_all_python_versions()), None)
                if version is None:
                    if not self.ignore_unsupported:
                        raise
                    continue
                if version_entry is not None:
                    version = version_entry.py_version.as_dict()
            except Exception:
                if not self.ignore_unsupported:
                    raise
                logger.warning(
                    "Unsupported Python version %r, ignoring...",
                    base_path.name,
                    exc_info=True,
                )
                continue
            if version is not None:
                version_tuple = (
                    version.get("major"),
                    version.get("minor"),
                    version.get("patch"),
                    version.get("is_prerelease"),
                    version.get("is_devrelease"),
                    version.get("is_debug"),
                )
                yield (base_path, entry, version_tuple)

    def _iter_pythons(self) -> Iterator:
        for path, entry, version_tuple in self._iter_versions():
            if path.as_posix() in self.pythons:
                yield self.pythons[path.as_posix()]
            elif version_tuple not in self.versions:
                for python in entry.find_all_python_versions():
                    yield python
            else:
                yield self.versions[version_tuple]

    def get_pythons(self):
        return self.pythons

    @classmethod
    def create(cls, root, sort_function, version_glob_path=None, ignore_unsupported=True):
        root = ensure_path(root)
        if not version_glob_path:
            version_glob_path = "versions/*"
        instance = cls(
            root=root,
            path=root,
            ignore_unsupported=ignore_unsupported,  # type: ignore
            version_glob_path=version_glob_path,
        )
        instance.sort_function = sort_function
        return instance

    def find_all_python_versions(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
    ) -> List[PathEntry]:
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

        call_method = "find_all_python_versions" if self.is_dir else "find_python_version"
        sub_finder = operator.methodcaller(
            call_method, major, minor, patch, pre, dev, arch, name
        )
        if not any([major, minor, patch, name]):
            pythons = [
                next(iter(py for py in base.find_all_python_versions()), None)
                for _, base in self._iter_version_bases()
            ]
        else:
            pythons = [sub_finder(path) for path in self.paths]
        pythons = expand_paths(pythons, True)
        version_sort = operator.attrgetter("as_python.version_sort")
        paths = [
            p for p in sorted(pythons, key=version_sort, reverse=True) if p is not None
        ]
        return paths

    def find_python_version(
        self,
        major=None,  # type: Optional[Union[str, int]]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: Optional[bool]
        dev=None,  # type: Optional[bool]
        arch=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
    ) -> Optional[PathEntry]:
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

        sub_finder = operator.methodcaller(
            "find_python_version", major, minor, patch, pre, dev, arch, name
        )
        version_sort = operator.attrgetter("as_python.version_sort")
        unnested = [sub_finder(self.roots[path]) for path in self.roots]
        unnested = [
            p
            for p in unnested
            if p is not None and p.is_python and p.as_python is not None
        ]
        paths = sorted(list(unnested), key=version_sort, reverse=True)
        return next(iter(p for p in paths if p is not None), None)

    def which(self, name) -> Optional[PathEntry]:
        """Search in this path for an executable.

        :param executable: The name of an executable to search for.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` instance.
        """

        matches = (p.which(name) for p in self.paths)
        non_empty_match = next(iter(m for m in matches if m is not None), None)
        return non_empty_match


class PythonVersion(BaseModel):
    major: int = 0
    minor: Optional[int] = None
    patch: Optional[int] = None
    is_prerelease: bool = False
    is_postrelease: bool = False
    is_devrelease: bool = False
    is_debug: bool = False
    version: Optional[Version] = None
    architecture: Optional[str] = None
    comes_from: Optional['PathEntry'] = None
    executable: Optional[Union[str, WindowsPath, Path]] = None
    company: Optional[str] = None
    name: Optional[str] = None

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        # keep_untouched = (cached_property,)

    @property
    def version_sort(self) -> Tuple[int, int, Optional[int], int, int]:
        """
        A tuple for sorting against other instances of the same class.

        Returns a tuple of the python version but includes points for core python,
        non-dev,  and non-prerelease versions.  So released versions will have 2 points
        for this value.  E.g. ``(1, 3, 6, 6, 2)`` is a release, ``(1, 3, 6, 6, 1)`` is a
        prerelease, ``(1, 3, 6, 6, 0)`` is a dev release, and ``(1, 3, 6, 6, 3)`` is a
        postrelease.  ``(0, 3, 7, 3, 2)`` represents a non-core python release, e.g. by
        a repackager of python like Continuum.
        """
        company_sort = 1 if (self.company and self.company == "PythonCore") else 0
        release_sort = 2
        if self.is_postrelease:
            release_sort = 3
        elif self.is_prerelease:
            release_sort = 1
        elif self.is_devrelease:
            release_sort = 0
        elif self.is_debug:
            release_sort = 1
        return (
            company_sort,
            self.major,
            self.minor,
            self.patch if self.patch else 0,
            release_sort,
        )

    @property
    def version_tuple(self) -> Tuple[int, int, int, bool, bool, bool]:
        """
        Provides a version tuple for using as a dictionary key.

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
        major=None,  # type: Optional[int]
        minor=None,  # type: Optional[int]
        patch=None,  # type: Optional[int]
        pre=None,  # type: bool
        dev=None,  # type: bool
        arch=None,  # type: Optional[str]
        debug=None,  # type: bool
        python_name=None,  # type: Optional[str]
    ) -> bool:
        result = False
        if arch:
            own_arch = self.get_architecture()
            if arch.isdigit():
                arch = "{0}bit".format(arch)
        if (
            (major is None or self.major == major)
            and (minor is None or self.minor == minor)
            and (patch is None or self.patch == patch)
            and (pre is None or self.is_prerelease == pre)
            and (dev is None or self.is_devrelease == dev)
            and (arch is None or own_arch == arch)
            and (debug is None or self.is_debug == debug)
            and (
                python_name is None
                or (python_name and self.name)
                and (self.name == python_name or self.name.startswith(python_name) or
                     python_name.endswith("python") or python_name.endswith("python.exe"))
            )
        ):
            result = True
        return result

    def update_metadata(self, metadata) -> None:
        """
        Update the metadata on the current :class:`pythonfinder.models.python.PythonVersion`

        Given a parsed version dictionary from :func:`pythonfinder.utils.parse_python_version`,
        update the instance variables of the current version instance to reflect the newly
        supplied values.
        """

        for key in metadata:
            try:
                _ = getattr(self, key)
            except AttributeError:
                continue
            else:
                setattr(self, key, metadata[key])

    @classmethod
    def parse(cls, version) -> Dict[str, Union[str, int, Version]]:
        """
        Parse a valid version string into a dictionary

        Raises:
            ValueError -- Unable to parse version string
            ValueError -- Not a valid python version
            TypeError -- NoneType or unparsable type passed in

        :param str version: A valid version string
        :return: A dictionary with metadata about the specified python version.
        """

        if version is None:
            raise TypeError("Must pass a value to parse!")
        version_dict = parse_python_version(str(version))
        if not version_dict:
            raise ValueError("Not a valid python version: %r" % version)
        return version_dict

    def get_architecture(self) -> str:
        if self.architecture:
            return self.architecture
        arch = None
        if self.comes_from is not None:
            arch, _ = platform.architecture(self.comes_from.path.as_posix())
        elif self.executable is not None:
            arch, _ = platform.architecture(self.executable)
        if arch is None:
            arch, _ = platform.architecture(sys.executable)
        self.architecture = arch
        return self.architecture

    @classmethod
    def from_path(cls, path, name=None, ignore_unsupported=True, company=None) -> "PythonVersion":
        """
        Parses a python version from a system path.

        Raises:
            ValueError -- Not a valid python path

        :param path: A string or :class:`~pythonfinder.models.path.PathEntry`
        :type path: str or :class:`~pythonfinder.models.path.PathEntry` instance
        :param str name: Name of the python distribution in question
        :param bool ignore_unsupported: Whether to ignore or error on unsupported paths.
        :param Optional[str] company: The company or vendor packaging the distribution.
        """

        from .path import PathEntry

        if not isinstance(path, PathEntry):
            path = PathEntry.create(path, is_root=False, only_python=True, name=name)
        from ..environment import IGNORE_UNSUPPORTED

        ignore_unsupported = ignore_unsupported or IGNORE_UNSUPPORTED
        path_name = getattr(path, "name", path.path.name)  # str
        if not path.is_python:
            if not (ignore_unsupported or IGNORE_UNSUPPORTED):
                raise ValueError("Not a valid python path: %s" % path.path)
        try:
            instance_dict = cls.parse(path_name)
        except Exception:
            instance_dict = cls.parse_executable(path.path.absolute().as_posix())
        else:
            if instance_dict.get("minor") is None and looks_like_python(path.path.name):
                instance_dict = cls.parse_executable(path.path.absolute().as_posix())

        if (
            not isinstance(instance_dict.get("version"), Version)
            and not ignore_unsupported
        ):
            raise ValueError("Not a valid python path: %s" % path)
        if instance_dict.get("patch") is None:
            instance_dict = cls.parse_executable(path.path.absolute().as_posix())
        if name is None:
            name = path_name
        if company is None:
            company = guess_company(path.path.as_posix())
        instance_dict.update(
            {"comes_from": path, "name": name, "executable": path.path.as_posix()}
        )
        return cls(**instance_dict)  # type: ignore

    @classmethod
    def parse_executable(cls, path) -> Dict[str, Optional[Union[str, int, Version]]]:
        result_dict = {}
        result_version = None
        if path is None:
            raise TypeError("Must pass a valid path to parse.")
        if not isinstance(path, str):
            path = path.as_posix()
        # if not looks_like_python(path):
        #     raise ValueError("Path %r does not look like a valid python path" % path)
        try:
            result_version = get_python_version(path)
        except Exception:
            raise ValueError("Not a valid python path: %r" % path)
        if result_version is None:
            raise ValueError("Not a valid python path: %s" % path)
        result_dict = cls.parse(result_version.strip())
        return result_dict

    @classmethod
    def from_windows_launcher(cls, launcher_entry, name=None, company=None) -> "PythonVersion":
        """Create a new PythonVersion instance from a Windows Launcher Entry

        :param launcher_entry: A python launcher environment object.
        :param Optional[str] name: The name of the distribution.
        :param Optional[str] company: The name of the distributing company.
        """
        creation_dict = cls.parse(launcher_entry.info.version)
        base_path = ensure_path(launcher_entry.info.install_path.__getattr__(""))
        default_path = base_path / "python.exe"
        if not default_path.exists():
            default_path = base_path / "Scripts" / "python.exe"
        exe_path = ensure_path(
            getattr(launcher_entry.info.install_path, "executable_path", default_path)
        )
        company = getattr(launcher_entry, "company", guess_company(exe_path.as_posix()))
        creation_dict.update(
            {
                "architecture": getattr(
                    launcher_entry.info, "sys_architecture", SYSTEM_ARCH
                ),
                "executable": exe_path,
                "name": name,
                "company": company,
            }
        )
        py_version = cls.create(**creation_dict)
        comes_from = PathEntry.create(exe_path, only_python=True, name=name)
        py_version.comes_from = comes_from
        py_version.name = comes_from.name
        return py_version

    @classmethod
    def create(cls, **kwargs) -> "PythonVersion":
        if "architecture" in kwargs:
            if kwargs["architecture"].isdigit():
                kwargs["architecture"] = "{0}bit".format(kwargs["architecture"])
        return cls(**kwargs)


class VersionMap(BaseModel):
    versions: DefaultDict[Tuple[int, Optional[int], Optional[int], bool, bool, bool], List[PathEntry]] = defaultdict(list)

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        # keep_untouched = (cached_property,)

    def add_entry(self, entry):
        version = entry.as_python
        if version:
            _ = self.versions[version.version_tuple]
            paths = {p.path for p in self.versions.get(version.version_tuple, [])}
            if entry.path not in paths:
                self.versions[version.version_tuple].append(entry)

    def merge(self, target):
        for version, entries in target.versions.items():
            if version not in self.versions:
                self.versions[version] = entries
            else:
                current_entries = {
                    p.path
                    for p in self.versions[version]
                    if version in self.versions
                }
                new_entries = {p.path for p in entries}
                new_entries -= current_entries
                self.versions[version].extend(
                    [e for e in entries if e.path in new_entries]
                )
