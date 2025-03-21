from __future__ import annotations

import dataclasses
import os
import platform
import sys
from dataclasses import field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from packaging.version import Version


@dataclasses.dataclass
class PythonInfo:
    """
    A simple dataclass to store Python version information.
    This replaces the complex PythonVersion class from the original implementation.
    """
    path: Path
    version_str: str
    major: int
    minor: Optional[int] = None
    patch: Optional[int] = None
    is_prerelease: bool = False
    is_postrelease: bool = False
    is_devrelease: bool = False
    is_debug: bool = False
    version: Optional[Version] = None
    architecture: Optional[str] = None
    company: Optional[str] = None
    name: Optional[str] = None
    executable: Optional[Union[str, Path]] = None
    
    @property
    def is_python(self) -> bool:
        """
        Check if this is a valid Python executable.
        """
        return True  # Since this object is only created for valid Python executables
        
    @property
    def as_python(self) -> 'PythonInfo':
        """
        Return self as a PythonInfo object.
        This is for compatibility with the test suite.
        """
        return self

    @property
    def version_tuple(self) -> Tuple[int, Optional[int], Optional[int], bool, bool, bool]:
        """
        Provides a version tuple for using as a dictionary key.
        """
        return (
            self.major,
            self.minor,
            self.patch,
            self.is_prerelease,
            self.is_devrelease,
            self.is_debug,
        )

    @property
    def version_sort(self) -> Tuple[int, int, int, int, int]:
        """
        A tuple for sorting against other instances of the same class.
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
            self.minor or 0,
            self.patch or 0,
            release_sort,
        )

    def matches(
        self,
        major: Optional[int] = None,
        minor: Optional[int] = None,
        patch: Optional[int] = None,
        pre: Optional[bool] = None,
        dev: Optional[bool] = None,
        arch: Optional[str] = None,
        debug: Optional[bool] = None,
        python_name: Optional[str] = None,
    ) -> bool:
        """
        Check if this Python version matches the specified criteria.
        """
        if arch:
            own_arch = self.architecture or self._get_architecture()
            if arch.isdigit():
                arch = f"{arch}bit"

        return (
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
                and (self.name == python_name or self.name.startswith(python_name))
            )
        )

    def _get_architecture(self) -> str:
        """
        Get the architecture of this Python version.
        """
        if self.architecture:
            return self.architecture

        arch = None
        if self.path:
            arch, _ = platform.architecture(str(self.path))
        elif self.executable:
            arch, _ = platform.architecture(str(self.executable))

        if arch is None:
            arch, _ = platform.architecture(sys.executable)

        self.architecture = arch
        return arch

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert this PythonInfo to a dictionary.
        """
        return {
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "is_prerelease": self.is_prerelease,
            "is_postrelease": self.is_postrelease,
            "is_devrelease": self.is_devrelease,
            "is_debug": self.is_debug,
            "version": self.version,
            "company": self.company,
        }
    
    def __eq__(self, other: object) -> bool:
        """
        Check if this PythonInfo is equal to another PythonInfo.
        
        Two PythonInfo objects are considered equal if they have the same path.
        """
        if not isinstance(other, PythonInfo):
            return NotImplemented
        return self.path == other.path
    
    def __lt__(self, other: object) -> bool:
        """
        Check if this PythonInfo is less than another PythonInfo.
        
        This is used for sorting PythonInfo objects by version.
        """
        if not isinstance(other, PythonInfo):
            return NotImplemented
        return self.version_sort < other.version_sort
