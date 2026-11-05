"""iOS."""

from __future__ import annotations

import os.path

from .api import PlatformDirsABC


class IOS(PlatformDirsABC):  # ruff:ignore[too-many-public-methods]
    """Platform directories for iOS and iPadOS.

    Follows the app container layout from `Apple's File System Programming Guide
    <https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileSystemOverview/FileSystemOverview.html>`_.
    On iOS the home directory is the app's sandbox, so ``~`` below is the app's data container. An app has no
    system-wide directories, so each ``site_*_dir`` returns its ``user_*_dir``.

    Makes use of the `appname <platformdirs.api.PlatformDirsABC.appname>`, `version
    <platformdirs.api.PlatformDirsABC.version>`, `ensure_exists <platformdirs.api.PlatformDirsABC.ensure_exists>`.

    """

    @property
    def user_data_dir(self) -> str:
        """Data directory tied to the user, e.g. ``~/Library/Application Support/$appname/$version``."""
        return self._append_app_name_and_version(os.path.expanduser("~/Library/Application Support"), private=True)  # ruff:ignore[os-path-expanduser]  # Path.expanduser raises on an unknown home

    @property
    def site_data_dir(self) -> str:
        """Data directory shared by users, same as `user_data_dir`."""
        return self.user_data_dir

    @property
    def user_config_dir(self) -> str:
        """Config directory tied to the user, same as `user_data_dir`."""
        return self.user_data_dir

    @property
    def site_config_dir(self) -> str:
        """Config directory shared by users, same as `user_config_dir`."""
        return self.user_config_dir

    @property
    def user_cache_dir(self) -> str:
        """Cache directory tied to the user, e.g. ``~/Library/Caches/$appname/$version``."""
        return self._append_app_name_and_version(os.path.expanduser("~/Library/Caches"), private=True)  # ruff:ignore[os-path-expanduser]  # Path.expanduser raises on an unknown home

    @property
    def site_cache_dir(self) -> str:
        """Cache directory shared by users, same as `user_cache_dir`."""
        return self.user_cache_dir

    @property
    def user_state_dir(self) -> str:
        """State directory tied to the user, same as `user_data_dir`."""
        return self.user_data_dir

    @property
    def site_state_dir(self) -> str:
        """State directory shared by users, same as `user_state_dir`."""
        return self.user_state_dir

    @property
    def user_log_dir(self) -> str:
        """Log directory tied to the user, e.g. ``~/Library/Logs/$appname/$version``."""
        return self._append_app_name_and_version(os.path.expanduser("~/Library/Logs"), private=True)  # ruff:ignore[os-path-expanduser]  # Path.expanduser raises on an unknown home

    @property
    def site_log_dir(self) -> str:
        """Log directory shared by users, same as `user_log_dir`."""
        return self.user_log_dir

    @property
    def user_documents_dir(self) -> str:
        """Documents directory tied to the user, e.g. ``~/Documents``."""
        return os.path.expanduser("~/Documents")  # ruff:ignore[os-path-expanduser]

    # The app container has Documents but no other media folder, so the rest live inside it, as Qt places them.
    @property
    def user_downloads_dir(self) -> str:
        """Downloads directory tied to the user, e.g. ``~/Documents/Downloads``."""
        return os.path.expanduser("~/Documents/Downloads")  # ruff:ignore[os-path-expanduser]

    @property
    def user_pictures_dir(self) -> str:
        """Pictures directory tied to the user, e.g. ``~/Documents/Pictures``."""
        return os.path.expanduser("~/Documents/Pictures")  # ruff:ignore[os-path-expanduser]

    @property
    def user_videos_dir(self) -> str:
        """Videos directory tied to the user, e.g. ``~/Documents/Movies``."""
        return os.path.expanduser("~/Documents/Movies")  # ruff:ignore[os-path-expanduser]

    @property
    def user_music_dir(self) -> str:
        """Music directory tied to the user, e.g. ``~/Documents/Music``."""
        return os.path.expanduser("~/Documents/Music")  # ruff:ignore[os-path-expanduser]

    @property
    def user_desktop_dir(self) -> str:
        """Desktop directory tied to the user, e.g. ``~/Documents/Desktop``."""
        return os.path.expanduser("~/Documents/Desktop")  # ruff:ignore[os-path-expanduser]

    @property
    def user_projects_dir(self) -> str:
        """Projects directory tied to the user, e.g. ``~/Documents/Projects``."""
        return os.path.expanduser("~/Documents/Projects")  # ruff:ignore[os-path-expanduser]

    @property
    def user_publicshare_dir(self) -> str:
        """Public share directory tied to the user, e.g. ``~/Documents/Public``."""
        return os.path.expanduser("~/Documents/Public")  # ruff:ignore[os-path-expanduser]

    @property
    def user_templates_dir(self) -> str:
        """Templates directory tied to the user, e.g. ``~/Documents/Templates``."""
        return os.path.expanduser("~/Documents/Templates")  # ruff:ignore[os-path-expanduser]

    @property
    def user_fonts_dir(self) -> str:
        """Fonts directory tied to the user, e.g. ``~/Library/Fonts``."""
        return os.path.expanduser("~/Library/Fonts")  # ruff:ignore[os-path-expanduser]

    @property
    def user_preference_dir(self) -> str:
        """Preference directory tied to the user, same as `user_config_dir`."""
        # Apple reserves Library/Preferences for NSUserDefaults and tells apps not to create files there.
        return self.user_config_dir

    @property
    def user_bin_dir(self) -> str:
        """Bin directory tied to the user, e.g. ``~/.local/bin``."""
        return os.path.expanduser("~/.local/bin")  # ruff:ignore[os-path-expanduser]

    @property
    def site_bin_dir(self) -> str:
        """Bin directory shared by users, same as `user_bin_dir`."""
        return self.user_bin_dir

    @property
    def user_applications_dir(self) -> str:
        """Applications directory tied to the user, e.g. ``~/Applications``."""
        return os.path.expanduser("~/Applications")  # ruff:ignore[os-path-expanduser]

    @property
    def site_applications_dir(self) -> str:
        """Applications directory shared by users, same as `user_applications_dir`."""
        return self.user_applications_dir

    @property
    def user_runtime_dir(self) -> str:
        """Runtime directory tied to the user, e.g. ``~/tmp/$appname/$version``."""
        return self._append_app_name_and_version(os.path.expanduser("~/tmp"), private=True)  # ruff:ignore[os-path-expanduser]  # Path.expanduser raises on an unknown home

    @property
    def site_runtime_dir(self) -> str:
        """Runtime directory shared by users, same as `user_runtime_dir`."""
        return self.user_runtime_dir


__all__ = [
    "IOS",
]
