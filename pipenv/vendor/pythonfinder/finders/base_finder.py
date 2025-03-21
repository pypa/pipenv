from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ..models.python_info import PythonInfo


class BaseFinder(abc.ABC):
    """
    Abstract base class for all Python finders.
    """

    @abc.abstractmethod
    def find_all_python_versions(
        self,
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
    ) -> list[PythonInfo]:
        """
        Find all Python versions matching the specified criteria.

        Args:
            major: Major version number or full version string.
            minor: Minor version number.
            patch: Patch version number.
            pre: Whether to include pre-releases.
            dev: Whether to include dev-releases.
            arch: Architecture to include, e.g. '64bit'.
            name: The name of a python version, e.g. ``anaconda3-5.3.0``.

        Returns:
            A list of PythonInfo objects matching the criteria.
        """
        pass

    @abc.abstractmethod
    def find_python_version(
        self,
        major: str | int | None = None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
        name: str | None = None,
    ) -> PythonInfo | None:
        """
        Find a Python version matching the specified criteria.

        Args:
            major: Major version number or full version string.
            minor: Minor version number.
            patch: Patch version number.
            pre: Whether to include pre-releases.
            dev: Whether to include dev-releases.
            arch: Architecture to include, e.g. '64bit'.
            name: The name of a python version, e.g. ``anaconda3-5.3.0``.

        Returns:
            A PythonInfo object matching the criteria, or None if not found.
        """
        pass

    def which(self, executable: str) -> Path | None:
        """
        Find an executable in the paths searched by this finder.

        Args:
            executable: The name of the executable to find.

        Returns:
            The path to the executable, or None if not found.
        """
        return None

    def parse_major(
        self,
        major: str | None,
        minor: int | None = None,
        patch: int | None = None,
        pre: bool | None = None,
        dev: bool | None = None,
        arch: str | None = None,
    ) -> dict[str, int | str | bool | None]:
        """
        Parse a major version string into a dictionary of version components.

        Args:
            major: Major version number or full version string.
            minor: Minor version number.
            patch: Patch version number.
            pre: Whether to include pre-releases.
            dev: Whether to include dev-releases.
            arch: Architecture to include, e.g. '64bit'.

        Returns:
            A dictionary containing the parsed version components.
        """
        from ..utils.version_utils import parse_python_version

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
                version_dict = parse_python_version(major)
            except Exception:
                if name is None:
                    name = f"{major!s}"
                    major = None
                version_dict = {}
        elif major and major[0].isalpha():
            return {"major": None, "name": major, "arch": arch}
        elif major and is_num:
            import re

            version_re = re.compile(
                r"(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>(?<=\.)[0-9]+))?\.?"
                r"(?:(?P<prerel>[abc]|rc|dev)(?:(?P<prerelversion>\d+(?:\.\d+)*))?)"
                r"?(?P<postdev>(\.post(?P<post>\d+))?(\.dev(?P<dev>\d+))?)?"
            )
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
