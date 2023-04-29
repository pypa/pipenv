import operator
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

from pipenv.vendor.pydantic import Field

from ..exceptions import InvalidPythonVersion
from ..utils import ensure_path
from .mixins import PathEntry
from .python import PythonVersion


class WindowsFinder(PathEntry):
    paths: Optional[List] = Field(default_factory=list)
    version_list: Optional[List] = Field(default_factory=list)
    versions: Optional[Dict[Tuple, PathEntry]]

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        # keep_untouched = (cached_property,)

    def __init__(self, **data):
        super().__init__(**data)
        if not self.versions:
            self.versions = self.get_versions()
        self.get_pythons()

    @property
    def version_paths(self) -> Any:
        return self.versions.values()

    @property
    def expanded_paths(self) -> Any:
        return (p.paths.values() for p in self.version_paths)

    def find_all_python_versions(
        self,
        major: Optional[Union[str, int]] = None,
        minor: Optional[int] = None,
        patch: Optional[int] = None,
        pre: Optional[bool] = None,
        dev: Optional[bool] = None,
        arch: Optional[str] = None,
        name: Optional[str] = None,
    ) -> List[PathEntry]:
        def version_matcher(py):
            return py.matches(major, minor, patch, pre, dev, arch, python_name=name)

        pythons = [py for py in self.version_list if version_matcher(py)]

        def version_sort(py):
            return py.version_sort

        return [
            c.comes_from
            for c in sorted(pythons, key=version_sort, reverse=True)
            if c.comes_from
        ]

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
        return next(
            iter(
                v
                for v in self.find_all_python_versions(
                    major=major,
                    minor=minor,
                    patch=patch,
                    pre=pre,
                    dev=dev,
                    arch=arch,
                    name=name,
                )
            ),
            None,
        )

    def get_versions(self) -> Dict[Tuple, PathEntry]:
        versions = defaultdict(PathEntry)
        from pipenv.vendor.pythonfinder._vendor.pep514tools import environment as pep514env

        env_versions = pep514env.findall()
        for version_object in env_versions:
            install_path = getattr(version_object.info, "install_path", None)
            name = getattr(version_object, "tag", None)
            company = getattr(version_object, "company", None)
            if install_path is None:
                continue
            try:
                path = ensure_path(install_path.__getattr__(""))
            except AttributeError:
                continue
            if not path.exists():
                continue
            try:
                py_version = PythonVersion.from_windows_launcher(
                    version_object, name=name, company=company
                )
            except (InvalidPythonVersion, AttributeError):
                continue
            if py_version is None:
                continue
            self.version_list.append(py_version)
            python_path = (
                py_version.comes_from.path
                if py_version.comes_from
                else py_version.executable
            )
            python_kwargs = {python_path: py_version} if python_path is not None else {}
            base_dir = PathEntry.create(
                path, is_root=True, only_python=True, pythons=python_kwargs
            )
            versions[py_version.version_tuple[:5]] = base_dir
            self.paths.append(base_dir)
        return versions

    def get_pythons(self) -> Dict[str, PathEntry]:
        pythons = defaultdict()
        for version in self.version_list:
            _path = ensure_path(version.comes_from.path)
            pythons[_path.as_posix()] = version.comes_from
        return pythons

    @classmethod
    def create(cls, *args, **kwargs) -> "FinderType":
        return cls(is_root=True)
