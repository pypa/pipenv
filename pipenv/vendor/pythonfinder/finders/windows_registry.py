from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from ..exceptions import InvalidPythonVersion
from ..models.python_info import PythonInfo
from ..utils.version_utils import parse_python_version
from .base_finder import BaseFinder

# Only import winreg on Windows
if os.name == "nt":
    import winreg
else:
    winreg = None


def get_registry_python_paths() -> list[str]:
    """
    Get a list of Python installation paths from the Windows registry.

    Returns:
        A list of paths to Python installations.
    """
    if os.name != "nt" or winreg is None:
        return []

    paths = []

    # PEP 514 registry keys
    python_core_key = r"Software\Python\PythonCore"
    python_key = r"Software\Python"

    # Registry views to search
    registry_views = []
    if hasattr(winreg, "KEY_WOW64_64KEY"):
        registry_views.append(winreg.KEY_WOW64_64KEY)
    if hasattr(winreg, "KEY_WOW64_32KEY"):
        registry_views.append(winreg.KEY_WOW64_32KEY)

    # Registry roots to search
    registry_roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]

    for root in registry_roots:
        for view in registry_views:
            # Try PythonCore first (standard Python installations)
            try:
                with winreg.OpenKey(
                    root, python_core_key, 0, winreg.KEY_READ | view
                ) as core_key:
                    for i in range(winreg.QueryInfoKey(core_key)[0]):
                        version = winreg.EnumKey(core_key, i)
                        try:
                            with winreg.OpenKey(
                                core_key,
                                f"{version}\\InstallPath",
                                0,
                                winreg.KEY_READ | view,
                            ) as install_key:
                                install_path, _ = winreg.QueryValueEx(install_key, "")
                                if install_path and os.path.exists(install_path):
                                    paths.append(install_path)

                                # Also check for ExecutablePath
                                try:
                                    exe_path, _ = winreg.QueryValueEx(
                                        install_key, "ExecutablePath"
                                    )
                                    if exe_path and os.path.exists(exe_path):
                                        exe_dir = os.path.dirname(exe_path)
                                        if exe_dir not in paths:
                                            paths.append(exe_dir)
                                except (FileNotFoundError, OSError):
                                    pass
                        except (FileNotFoundError, OSError):
                            continue
            except (FileNotFoundError, OSError):
                pass

            # Then try the more general Python key (for other distributions)
            try:
                with winreg.OpenKey(
                    root, python_key, 0, winreg.KEY_READ | view
                ) as python_root_key:
                    for i in range(winreg.QueryInfoKey(python_root_key)[0]):
                        company = winreg.EnumKey(python_root_key, i)
                        if company == "PythonCore":
                            continue  # Already handled above

                        try:
                            company_key = f"{python_key}\\{company}"
                            with winreg.OpenKey(
                                root, company_key, 0, winreg.KEY_READ | view
                            ) as company_key_handle:
                                for j in range(
                                    winreg.QueryInfoKey(company_key_handle)[0]
                                ):
                                    version = winreg.EnumKey(company_key_handle, j)
                                    try:
                                        version_key = (
                                            f"{company_key}\\{version}\\InstallPath"
                                        )
                                        with winreg.OpenKey(
                                            root, version_key, 0, winreg.KEY_READ | view
                                        ) as install_key:
                                            install_path, _ = winreg.QueryValueEx(
                                                install_key, ""
                                            )
                                            if install_path and os.path.exists(
                                                install_path
                                            ):
                                                paths.append(install_path)

                                            # Also check for ExecutablePath
                                            try:
                                                exe_path, _ = winreg.QueryValueEx(
                                                    install_key, "ExecutablePath"
                                                )
                                                if exe_path and os.path.exists(exe_path):
                                                    exe_dir = os.path.dirname(exe_path)
                                                    if exe_dir not in paths:
                                                        paths.append(exe_dir)
                                            except (FileNotFoundError, OSError):
                                                pass
                                    except (FileNotFoundError, OSError):
                                        continue
                        except (FileNotFoundError, OSError):
                            continue
            except (FileNotFoundError, OSError):
                pass

    return paths


class WindowsRegistryInfo:
    """
    Class to hold information about a Python installation from the Windows registry.
    """

    def __init__(
        self,
        company: str,
        tag: str,
        version: str,
        install_path: str,
        executable_path: str | None = None,
        sys_architecture: str | None = None,
    ):
        """
        Initialize a new WindowsRegistryInfo.

        Args:
            company: The company that distributes this Python.
            tag: The tag for this Python installation (usually the version).
            version: The version string for this Python.
            install_path: The installation path for this Python.
            executable_path: The path to the Python executable.
            sys_architecture: The system architecture for this Python.
        """
        self.company = company
        self.tag = tag
        self.version = version
        self.install_path = install_path
        self.executable_path = executable_path
        self.sys_architecture = sys_architecture


class WindowsRegistryFinder(BaseFinder):
    """
    Finder that searches for Python in the Windows registry (PEP 514).
    """

    def __init__(self, ignore_unsupported: bool = True):
        """
        Initialize a new WindowsRegistryFinder.

        Args:
            ignore_unsupported: Whether to ignore unsupported Python versions.
        """
        self.ignore_unsupported = ignore_unsupported
        self._python_versions: dict[Path, PythonInfo] = {}

    def _iter_registry_pythons(self) -> Iterator[tuple[str, str, WindowsRegistryInfo]]:
        """
        Iterate over all Python installations found in the Windows registry.

        Returns:
            An iterator of (company, tag, WindowsRegistryInfo) tuples.
        """
        if os.name != "nt" or winreg is None:
            return

        # PEP 514 registry keys
        python_core_key = r"Software\Python\PythonCore"
        python_key = r"Software\Python"

        # Registry views to search
        registry_views = []
        if hasattr(winreg, "KEY_WOW64_64KEY"):
            registry_views.append(winreg.KEY_WOW64_64KEY)
        if hasattr(winreg, "KEY_WOW64_32KEY"):
            registry_views.append(winreg.KEY_WOW64_32KEY)

        # Registry roots to search
        registry_roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]

        for root in registry_roots:
            for view in registry_views:
                # Try PythonCore first (standard Python installations)
                try:
                    with winreg.OpenKey(
                        root, python_core_key, 0, winreg.KEY_READ | view
                    ) as core_key:
                        for i in range(winreg.QueryInfoKey(core_key)[0]):
                            tag = winreg.EnumKey(core_key, i)
                            try:
                                with winreg.OpenKey(
                                    core_key,
                                    f"{tag}\\InstallPath",
                                    0,
                                    winreg.KEY_READ | view,
                                ) as install_key:
                                    install_path, _ = winreg.QueryValueEx(install_key, "")

                                    # Get executable path if available
                                    executable_path = None
                                    try:
                                        executable_path, _ = winreg.QueryValueEx(
                                            install_key, "ExecutablePath"
                                        )
                                    except (FileNotFoundError, OSError):
                                        # If ExecutablePath is not available, construct it
                                        if install_path:
                                            executable_path = os.path.join(
                                                install_path, "python.exe"
                                            )

                                    # Get system architecture if available
                                    sys_architecture = None
                                    try:
                                        with winreg.OpenKey(
                                            core_key,
                                            f"{tag}\\SysArchitecture",
                                            0,
                                            winreg.KEY_READ | view,
                                        ) as arch_key:
                                            sys_architecture, _ = winreg.QueryValueEx(
                                                arch_key, ""
                                            )
                                    except (FileNotFoundError, OSError):
                                        pass

                                    # Create registry info
                                    registry_info = WindowsRegistryInfo(
                                        company="PythonCore",
                                        tag=tag,
                                        version=tag,
                                        install_path=install_path,
                                        executable_path=executable_path,
                                        sys_architecture=sys_architecture,
                                    )

                                    yield ("PythonCore", tag, registry_info)
                            except (FileNotFoundError, OSError):
                                continue
                except (FileNotFoundError, OSError):
                    pass

                # Then try the more general Python key (for other distributions)
                try:
                    with winreg.OpenKey(
                        root, python_key, 0, winreg.KEY_READ | view
                    ) as python_root_key:
                        for i in range(winreg.QueryInfoKey(python_root_key)[0]):
                            company = winreg.EnumKey(python_root_key, i)
                            if company == "PythonCore":
                                continue  # Already handled above

                            try:
                                company_key = f"{python_key}\\{company}"
                                with winreg.OpenKey(
                                    root, company_key, 0, winreg.KEY_READ | view
                                ) as company_key_handle:
                                    for j in range(
                                        winreg.QueryInfoKey(company_key_handle)[0]
                                    ):
                                        tag = winreg.EnumKey(company_key_handle, j)
                                        try:
                                            version_key = (
                                                f"{company_key}\\{tag}\\InstallPath"
                                            )
                                            with winreg.OpenKey(
                                                root,
                                                version_key,
                                                0,
                                                winreg.KEY_READ | view,
                                            ) as install_key:
                                                install_path, _ = winreg.QueryValueEx(
                                                    install_key, ""
                                                )

                                                # Get executable path if available
                                                executable_path = None
                                                try:
                                                    (
                                                        executable_path,
                                                        _,
                                                    ) = winreg.QueryValueEx(
                                                        install_key, "ExecutablePath"
                                                    )
                                                except (FileNotFoundError, OSError):
                                                    # If ExecutablePath is not available, construct it
                                                    if install_path:
                                                        executable_path = os.path.join(
                                                            install_path, "python.exe"
                                                        )

                                                # Get system architecture if available
                                                sys_architecture = None
                                                try:
                                                    with winreg.OpenKey(
                                                        root,
                                                        f"{company_key}\\{tag}\\SysArchitecture",
                                                        0,
                                                        winreg.KEY_READ | view,
                                                    ) as arch_key:
                                                        (
                                                            sys_architecture,
                                                            _,
                                                        ) = winreg.QueryValueEx(
                                                            arch_key, ""
                                                        )
                                                except (FileNotFoundError, OSError):
                                                    pass

                                                # Create registry info
                                                registry_info = WindowsRegistryInfo(
                                                    company=company,
                                                    tag=tag,
                                                    version=tag,
                                                    install_path=install_path,
                                                    executable_path=executable_path,
                                                    sys_architecture=sys_architecture,
                                                )

                                                yield (company, tag, registry_info)
                                        except (FileNotFoundError, OSError):
                                            continue
                            except (FileNotFoundError, OSError):
                                continue
                except (FileNotFoundError, OSError):
                    pass

    def _create_python_info_from_registry(
        self, company: str, tag: str, registry_info: WindowsRegistryInfo
    ) -> PythonInfo | None:
        """
        Create a PythonInfo object from registry information.

        Args:
            company: The company that distributes this Python.
            tag: The tag for this Python installation (usually the version).
            registry_info: The registry information for this Python.

        Returns:
            A PythonInfo object, or None if the registry information is invalid.
        """
        # Determine the executable path
        executable_path = registry_info.executable_path
        if not executable_path:
            install_path = registry_info.install_path
            if install_path:
                executable_path = os.path.join(install_path, "python.exe")

        if not executable_path or not os.path.exists(executable_path):
            return None

        # Parse the version
        try:
            version_data = parse_python_version(registry_info.version)
        except InvalidPythonVersion:
            if not self.ignore_unsupported:
                raise
            return None

        # Create the PythonInfo object
        return PythonInfo(
            path=Path(executable_path),
            version_str=registry_info.version,
            major=version_data["major"],
            minor=version_data["minor"],
            patch=version_data["patch"],
            is_prerelease=version_data["is_prerelease"],
            is_postrelease=version_data["is_postrelease"],
            is_devrelease=version_data["is_devrelease"],
            is_debug=version_data["is_debug"],
            version=version_data["version"],
            architecture=registry_info.sys_architecture,
            company=company,
            name=f"{company}-{tag}",
            executable=executable_path,
        )

    def _iter_pythons(self) -> Iterator[PythonInfo]:
        """
        Iterate over all Python installations found in the Windows registry.

        Returns:
            An iterator of PythonInfo objects.
        """
        if os.name != "nt" or winreg is None:
            return

        for company, tag, registry_info in self._iter_registry_pythons():
            python_info = self._create_python_info_from_registry(
                company, tag, registry_info
            )
            if python_info:
                yield python_info

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
        # Parse the major version if it's a string
        if isinstance(major, str) and not any([minor, patch, pre, dev, arch]):
            version_dict = self.parse_major(major, minor, patch, pre, dev, arch)
            major = version_dict.get("major")
            minor = version_dict.get("minor")
            patch = version_dict.get("patch")
            pre = version_dict.get("is_prerelease")
            dev = version_dict.get("is_devrelease")
            arch = version_dict.get("arch")
            name = version_dict.get("name")

        # Find all Python versions
        python_versions = []
        for python_info in self._iter_pythons():
            if python_info.matches(major, minor, patch, pre, dev, arch, None, name):
                python_versions.append(python_info)

        # Sort by version
        return sorted(
            python_versions,
            key=lambda x: x.version_sort,
            reverse=True,
        )

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
        python_versions = self.find_all_python_versions(
            major, minor, patch, pre, dev, arch, name
        )
        return python_versions[0] if python_versions else None
