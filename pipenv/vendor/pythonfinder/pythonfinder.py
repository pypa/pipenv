from __future__ import annotations

import operator
from typing import Any, Optional

from .exceptions import InvalidPythonVersion
from .models.common import FinderBaseModel
from .models.path import PathEntry, SystemPath
from .models.python import PythonVersion
from .environment import set_asdf_paths, set_pyenv_paths
from .utils import Iterable, version_re


class Finder(FinderBaseModel):
    path_prepend: Optional[str] = None
    system: bool = False
    global_search: bool = True
    ignore_unsupported: bool = True
    sort_by_path: bool = False
    system_path: Optional[SystemPath] = None

    def __init__(self, **data) -> None:
        super().__init__(**data)
        self.system_path = self.create_system_path()

    @property
    def __hash__(self) -> int:
        return hash(
            (self.path_prepend, self.system, self.global_search, self.ignore_unsupported)
        )

    def __eq__(self, other) -> bool:
        return self.__hash__ == other.__hash__

    def create_system_path(self) -> SystemPath:
        set_asdf_paths()
        set_pyenv_paths()
        return SystemPath.create(
            path=self.path_prepend,
            system=self.system,
            global_search=self.global_search,
            ignore_unsupported=self.ignore_unsupported,
        )

    def which(self, exe) -> PathEntry | None:
        return self.system_path.which(exe)

    @classmethod
    def parse_major(
        cls,
        major: str | None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
    ) -> dict[str, Any]:
        major_is_str = major and isinstance(major, str)
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
            orig_string = f"{major!s}"
            major, _, arch = major.rpartition("-")
            if arch:
                arch = arch.lower().lstrip("x").replace("bit", "")
                if not (arch.isdigit() and (int(arch) & int(arch) - 1) == 0):
                    major = orig_string
                    arch = None
                else:
                    arch = f"{arch}bit"
            try:
                version_dict = PythonVersion.parse(major)
            except (ValueError, InvalidPythonVersion):
                if name is None:
                    name = f"{major!s}"
                    major = None
                version_dict = {}
        elif major and major[0].isalpha():
            return {"major": None, "name": major, "arch": arch}
        elif major and is_num:
            match = version_re.match(major)
            version_dict = match.groupdict() if match else {}
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

    def find_python_version(
        self,
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
        sort_by_path: bool = False,
    ) -> PathEntry | None:
        """
        Find the python version which corresponds most closely to the version requested.

        :param major: The major version to look for, or the full version, or the name of the target version.
        :param minor: The minor version. If provided, disables string-based lookups from the major version field.
        :param patch: The patch version.
        :param pre: If provided, specifies whether to search pre-releases.
        :param dev: If provided, whether to search dev-releases.
        :param arch: If provided, which architecture to search.
        :param name: *Name* of the target python, e.g. ``anaconda3-5.3.0``
        :param sort_by_path: Whether to sort by path -- default sort is by version(default: False)
        :return: A new *PathEntry* pointer at a matching python version, if one can be located.
        """
        minor = int(minor) if minor is not None else minor
        patch = int(patch) if patch is not None else patch

        if (
            isinstance(major, str)
            and pre is None
            and minor is None
            and dev is None
            and patch is None
        ):
            version_dict = self.parse_major(major, minor=minor, patch=patch, arch=arch)
            major = version_dict["major"]
            minor = version_dict.get("minor", minor)
            patch = version_dict.get("patch", patch)
            arch = version_dict.get("arch", arch)
            name = version_dict.get("name", name)
            _pre = version_dict.get("is_prerelease", pre)
            pre = bool(_pre) if _pre is not None else pre
            _dev = version_dict.get("is_devrelease", dev)
            dev = bool(_dev) if _dev is not None else dev
            if "architecture" in version_dict and isinstance(
                version_dict["architecture"], str
            ):
                arch = version_dict["architecture"]
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

    def find_all_python_versions(
        self,
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
    ) -> list[PathEntry]:
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
        path_list = sorted(
            filter(lambda v: v and v.as_python, versions), key=version_sort, reverse=True
        )
        path_map = {}
        for path in path_list:
            try:
                resolved_path = path.path.resolve()
            except OSError:
                resolved_path = path.path.absolute()
            if not path_map.get(resolved_path.as_posix()):
                path_map[resolved_path.as_posix()] = path
        return path_list
