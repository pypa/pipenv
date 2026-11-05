"""macOS."""

from __future__ import annotations

import re
import sys
from typing import Final

from ._xdg import XDGMixin, _expand_user
from .api import PlatformDirsABC


class _MacOSDefaults(PlatformDirsABC):  # ruff:ignore[too-many-public-methods]
    """Default platform directories for macOS without XDG environment variable overrides.

    Follows the guidance from `Apple's File System Programming Guide
    <https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/MacOSXDirectories/MacOSXDirectories.html>`_.
    The XDG env var handling is in :class:`~platformdirs._xdg.XDGMixin`.

    """

    def _base_user_app_support_dir(self) -> str:
        return self._append_app_name_and_version(_expand_user("~/Library/Application Support"), private=True)

    def _base_site_dirs(self) -> list[str]:
        path_list = [self._join_app_name_and_version(f"{prefix}/share")] if (prefix := _homebrew_prefix()) else []
        path_list.append(self._join_app_name_and_version("/Library/Application Support"))
        return path_list

    @property
    def user_data_dir(self) -> str:
        """Data directory tied to the user, e.g. ``~/Library/Application Support/$appname/$version``."""
        return self._base_user_app_support_dir()

    @property
    def _site_data_dirs(self) -> list[str]:
        return self._base_site_dirs()

    @property
    def user_config_dir(self) -> str:
        """Config directory tied to the user, same as `user_data_dir`."""
        return self._base_user_app_support_dir()

    @property
    def _site_config_dirs(self) -> list[str]:
        return self._base_site_dirs()

    @property
    def user_cache_dir(self) -> str:
        """Cache directory tied to the user, e.g. ``~/Library/Caches/$appname/$version``."""
        return self._append_app_name_and_version(_expand_user("~/Library/Caches"), private=True)

    @property
    def _site_cache_dirs(self) -> list[str]:
        path_list = [self._join_app_name_and_version(f"{prefix}/var/cache")] if (prefix := _homebrew_prefix()) else []
        path_list.append(self._join_app_name_and_version("/Library/Caches"))
        return path_list

    @property
    def site_cache_dir(self) -> str:
        """Cache directory shared by users, e.g. ``/Library/Caches/$appname/$version``. If we're using a Python binary managed by `Homebrew <https://brew.sh>`_, the directory will be under the Homebrew prefix, e.g. ``$homebrew_prefix/var/cache/$appname/$version``. If `multipath <platformdirs.api.PlatformDirsABC.multipath>` is enabled, and we're in Homebrew, the response is a multi-path string separated by ":", e.g. ``$homebrew_prefix/var/cache/$appname/$version:/Library/Caches/$appname/$version``."""
        return self._select_site_dirs(self._site_cache_dirs)

    @property
    def user_state_dir(self) -> str:
        """State directory tied to the user, same as `user_data_dir` without ``$XDG_DATA_HOME``, e.g. ``~/Library/Application Support/$appname/$version``."""
        return self._base_user_app_support_dir()

    @property
    def site_state_dir(self) -> str:
        """State directory shared by users, the first entry of `site_data_dir` without ``$XDG_DATA_DIRS``, ignoring `multipath <platformdirs.api.PlatformDirsABC.multipath>`."""
        path = self._base_site_dirs()[0]
        self._optionally_create_directory(path, private=False)
        return path

    @property
    def user_log_dir(self) -> str:
        """Log directory tied to the user, e.g. ``~/Library/Logs/$appname/$version``."""
        return self._append_app_name_and_version(_expand_user("~/Library/Logs"), private=True)

    @property
    def site_log_dir(self) -> str:
        """Log directory shared by users, e.g. ``/Library/Logs/$appname/$version``."""
        return self._append_app_name_and_version("/Library/Logs", private=False)

    @property
    def user_documents_dir(self) -> str:
        """Documents directory tied to the user, e.g. ``~/Documents``."""
        return _expand_user("~/Documents")

    @property
    def user_downloads_dir(self) -> str:
        """Downloads directory tied to the user, e.g. ``~/Downloads``."""
        return _expand_user("~/Downloads")

    @property
    def user_pictures_dir(self) -> str:
        """Pictures directory tied to the user, e.g. ``~/Pictures``."""
        return _expand_user("~/Pictures")

    @property
    def user_videos_dir(self) -> str:
        """Videos directory tied to the user, e.g. ``~/Movies``."""
        return _expand_user("~/Movies")

    @property
    def user_music_dir(self) -> str:
        """Music directory tied to the user, e.g. ``~/Music``."""
        return _expand_user("~/Music")

    @property
    def user_desktop_dir(self) -> str:
        """Desktop directory tied to the user, e.g. ``~/Desktop``."""
        return _expand_user("~/Desktop")

    @property
    def user_projects_dir(self) -> str:
        """Projects directory tied to the user, e.g. ``~/Projects``."""
        return _expand_user("~/Projects")

    @property
    def user_publicshare_dir(self) -> str:
        """Public share directory tied to the user, e.g. ``~/Public``."""
        return _expand_user("~/Public")

    @property
    def user_templates_dir(self) -> str:
        """Templates directory tied to the user, e.g. ``~/Templates``."""
        return _expand_user("~/Templates")

    @property
    def user_fonts_dir(self) -> str:
        """Fonts directory tied to the user, e.g. ``~/Library/Fonts``."""
        return _expand_user("~/Library/Fonts")

    @property
    def user_preference_dir(self) -> str:
        """Preference directory tied to the user, e.g. ``~/Library/Preferences/AppName``."""
        return self._append_app_name_and_version(_expand_user("~/Library/Preferences"), private=True)

    @property
    def user_bin_dir(self) -> str:
        """Bin directory tied to the user, e.g. ``~/.local/bin``."""
        return _expand_user("~/.local/bin")

    @property
    def site_bin_dir(self) -> str:
        """Bin directory shared by users, e.g. ``/usr/local/bin``."""
        return "/usr/local/bin"

    @property
    def user_applications_dir(self) -> str:
        """Applications directory tied to the user, e.g. ``~/Applications``."""
        return _expand_user("~/Applications")

    @property
    def _site_applications_dirs(self) -> list[str]:
        return ["/Applications"]

    @property
    def user_runtime_dir(self) -> str:
        """Runtime directory tied to the user, e.g. ``~/Library/Caches/TemporaryItems/$appname/$version``."""
        return self._append_app_name_and_version(_expand_user("~/Library/Caches/TemporaryItems"), private=True)

    @property
    def site_runtime_dir(self) -> str:
        """Runtime directory shared by users, same as `user_runtime_dir`."""
        return self.user_runtime_dir


class MacOS(XDGMixin, _MacOSDefaults):
    """Platform directories for the macOS operating system.

    Follows the guidance from `Apple documentation
    <https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/MacOSXDirectories/MacOSXDirectories.html>`_.
    Makes use of the `appname <platformdirs.api.PlatformDirsABC.appname>`, `version
    <platformdirs.api.PlatformDirsABC.version>`, `ensure_exists <platformdirs.api.PlatformDirsABC.ensure_exists>`.

    XDG environment variables (e.g. ``$XDG_DATA_HOME``) are supported and take precedence over macOS defaults.

    """


# Homebrew links each Python formula as a framework build, and a virtual environment keeps it as sys.base_prefix.
_HOMEBREW_PYTHON: Final = re.compile(
    r"""
    (?P<prefix>.+)                 # $HOMEBREW_PREFIX, such as /opt/homebrew or /usr/local
    /opt/python[^/]*               # formula link: python, python3 or python@3.13
    /Frameworks/Python\.framework  # framework build
    /Versions/[^/]+                # interpreter version, such as 3.13
    """,
    re.VERBOSE,
)


def _homebrew_prefix() -> str | None:
    if match := _HOMEBREW_PYTHON.fullmatch(sys.base_prefix):
        return match["prefix"]
    return None


__all__ = [
    "MacOS",
]
