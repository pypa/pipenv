"""Android."""

from __future__ import annotations

import os
import re
import sys
from contextlib import suppress
from functools import cache, lru_cache
from typing import Final

from .api import PlatformDirsABC


class Android(PlatformDirsABC):  # ruff:ignore[too-many-public-methods]
    """Platform directories for Android.

    Follows the guidance `from here <https://android.stackexchange.com/a/216132>`_. Directories are typically located
    under the app's private storage (``/data/user/<userid>/<packagename>/``).

    Makes use of the `appname <platformdirs.api.PlatformDirsABC.appname>`, `version
    <platformdirs.api.PlatformDirsABC.version>`, `opinion <platformdirs.api.PlatformDirsABC.opinion>`, `ensure_exists
    <platformdirs.api.PlatformDirsABC.ensure_exists>`.

    """

    @property
    def user_data_dir(self) -> str:
        """Data directory tied to the user, e.g. ``/data/user/<userid>/<packagename>/files/<AppName>``."""
        return self._append_app_name_and_version(_require_android_folder(), "files", private=True)

    @property
    def site_data_dir(self) -> str:
        """Data directory shared by users, same as `user_data_dir`."""
        return self.user_data_dir

    @property
    def user_config_dir(self) -> str:
        """Config directory tied to the user, e.g. ``/data/user/<userid>/<packagename>/shared_prefs/<AppName>``."""
        return self._append_app_name_and_version(_require_android_folder(), "shared_prefs", private=True)

    @property
    def site_config_dir(self) -> str:
        """Config directory shared by users, same as `user_config_dir`."""
        return self.user_config_dir

    @property
    def user_cache_dir(self) -> str:
        """Cache directory tied to the user, e.g.,``/data/user/<userid>/<packagename>/cache/<AppName>``."""
        return self._append_app_name_and_version(_require_android_folder(), "cache", private=True)

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
        """Log directory tied to the user, same as `user_cache_dir` if not opinionated else ``log`` in it, e.g. ``/data/user/<userid>/<packagename>/cache/<AppName>/log``."""
        path = self.user_cache_dir
        if self.opinion:
            path = os.path.join(path, "log")  # ruff:ignore[os-path-join]
            self._optionally_create_directory(path, private=True)
        return path

    @property
    def site_log_dir(self) -> str:
        """Log directory shared by users, same as `user_log_dir`."""
        return self.user_log_dir

    @property
    def user_documents_dir(self) -> str:
        """Documents directory tied to the user e.g. ``/storage/emulated/0/Documents``."""
        return _android_public_folder("Documents")

    @property
    def user_downloads_dir(self) -> str:
        """Downloads directory tied to the user e.g. ``/storage/emulated/0/Download``."""
        return _android_public_folder("Download")

    @property
    def user_pictures_dir(self) -> str:
        """Pictures directory tied to the user e.g. ``/storage/emulated/0/Pictures``."""
        return _android_public_folder("Pictures")

    @property
    def user_videos_dir(self) -> str:
        """Videos directory tied to the user e.g. ``/storage/emulated/0/Movies``."""
        return _android_public_folder("Movies")

    @property
    def user_music_dir(self) -> str:
        """Music directory tied to the user e.g. ``/storage/emulated/0/Music``."""
        return _android_public_folder("Music")

    # Android lets apps create top-level shared folders only from its standard list, so these live in Documents.
    @property
    def user_desktop_dir(self) -> str:
        """Desktop directory tied to the user e.g. ``/storage/emulated/0/Documents/Desktop``."""
        return f"{_shared_storage()}/Documents/Desktop"

    @property
    def user_projects_dir(self) -> str:
        """Projects directory tied to the user e.g. ``/storage/emulated/0/Documents/Projects``."""
        return f"{_shared_storage()}/Documents/Projects"

    @property
    def user_publicshare_dir(self) -> str:
        """Public share directory tied to the user e.g. ``/storage/emulated/0/Documents/Public``."""
        return f"{_shared_storage()}/Documents/Public"

    @property
    def user_templates_dir(self) -> str:
        """Templates directory tied to the user e.g. ``/storage/emulated/0/Documents/Templates``."""
        return f"{_shared_storage()}/Documents/Templates"

    @property
    def user_fonts_dir(self) -> str:
        """Fonts directory tied to the user e.g. ``/storage/emulated/0/Documents/fonts``."""
        return f"{_shared_storage()}/Documents/fonts"

    @property
    def user_preference_dir(self) -> str:
        """Preference directory tied to the user, same as ``user_config_dir``."""
        return self.user_config_dir

    @property
    def user_bin_dir(self) -> str:
        """Bin directory tied to the user, e.g. ``/data/user/<userid>/<packagename>/files/bin``."""
        return os.path.join(_require_android_folder(), "files", "bin")  # ruff:ignore[os-path-join]

    @property
    def site_bin_dir(self) -> str:
        """Bin directory shared by users, same as `user_bin_dir`."""
        return self.user_bin_dir

    @property
    def user_applications_dir(self) -> str:
        """Applications directory tied to the user, same as `user_data_dir`."""
        return self.user_data_dir

    @property
    def site_applications_dir(self) -> str:
        """Applications directory shared by users, same as `user_applications_dir`."""
        return self.user_applications_dir

    @property
    def user_runtime_dir(self) -> str:
        """Runtime directory tied to the user, same as `user_cache_dir` if not opinionated else ``tmp`` in it, e.g. ``/data/user/<userid>/<packagename>/cache/<AppName>/tmp``."""
        path = self.user_cache_dir
        if self.opinion:
            path = os.path.join(path, "tmp")  # ruff:ignore[os-path-join]
            self._optionally_create_directory(path, private=True)
        return path

    @property
    def site_runtime_dir(self) -> str:
        """Runtime directory shared by users, same as `user_runtime_dir`."""
        return self.user_runtime_dir


def _require_android_folder() -> str:
    if (folder := _android_folder()) is None:
        msg = "cannot find the Android app folder: python4android and pyjnius failed and no app folder is on sys.path"
        raise RuntimeError(msg)
    return folder


@lru_cache(maxsize=1)
def _android_folder() -> str | None:
    """:returns: base folder for the Android OS or None if it cannot be found"""
    result = _python_for_android_folder()
    if result is None:
        # and if that fails, too, find an android folder looking at path on the sys.path
        # warning: only works for apps installed under /data, not adopted storage etc.
        pattern = re.compile(
            r"""
            (?P<folder>
                /data/(?:data|user/\d+)  # internal storage of the primary user or of user N
                /[^/]+                   # package name, one path segment
            )
            /files                       # the files directory the interpreter runs from
            """,
            re.VERBOSE,
        )
        for path in sys.path:
            if match := pattern.match(path):
                result = match["folder"]
                break
        else:
            result = None
    if result is None:
        # one last try: find an android folder looking at path on the sys.path taking adopted storage paths into
        # account
        pattern = re.compile(
            r"""
            (?P<folder>
                /mnt/expand/[a-fA-F0-9-]{36}  # adopted storage volume, named by its UUID
                /(?:data|user/\d+)             # the primary user or user N
                /[^/]+                         # package name, one path segment
            )
            /files                             # the files directory the interpreter runs from
            """,
            re.VERBOSE,
        )
        for path in sys.path:
            if match := pattern.match(path):
                result = match["folder"]
                break
        else:
            result = None
    return result


_USER_ID: Final = re.compile(
    r"""
    /user/         # the per-user data root, under /data or an adopted /mnt/expand volume
    (?P<user>\d+)  # the Android user id
    /              # followed by the package folder
    """,
    re.VERBOSE,
)


def _shared_storage() -> str:
    # Android mounts each user's shared storage at /storage/emulated/<user id>, and an app sees only its own user's.
    user = match["user"] if (match := _USER_ID.search(_android_folder() or "")) else "0"
    return f"/storage/emulated/{user}"


def _python_for_android_folder() -> str | None:
    with suppress(ImportError):
        from jnius import JavaException, autoclass  # ruff:ignore[import-outside-top-level]  # ty: ignore[unresolved-import]

        with suppress(JavaException):
            # A python-for-android service runs in its own process, where the activity is null.
            if (context := autoclass("org.kivy.android.PythonActivity").mActivity) is None:
                context = autoclass("org.kivy.android.PythonService").mService
            if context is not None:
                return context.getFilesDir().getParentFile().getAbsolutePath()
    return None


@cache
def _android_public_folder(name: str) -> str:
    with suppress(ImportError):
        from jnius import JavaException, autoclass  # ruff:ignore[import-outside-top-level]  # ty: ignore[unresolved-import]

        with suppress(JavaException):
            return autoclass("android.os.Environment").getExternalStoragePublicDirectory(name).getAbsolutePath()
    return f"{_shared_storage()}/{name}"


__all__ = [
    "Android",
]
