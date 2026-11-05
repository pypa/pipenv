"""Unix."""

from __future__ import annotations

import os
import re
import stat
import sys
import warnings
from contextlib import suppress
from pathlib import Path
from tempfile import gettempdir
from typing import Final, NoReturn

from ._xdg import XDGMixin, _expand_user, _xdg_dir
from .api import PlatformDirsABC, RuntimeDirWarning

if sys.platform == "win32":

    def getuid() -> NoReturn:
        msg = "should only be used on Unix"
        raise RuntimeError(msg)

else:
    from os import getuid


class _UnixDefaults(PlatformDirsABC):  # ruff:ignore[too-many-public-methods]
    """Default directories for Unix/Linux without XDG environment variable overrides.

    The XDG env var handling is in :class:`~platformdirs._xdg.XDGMixin`.

    """

    @property
    def _use_site(self) -> bool:
        return self.use_site_for_root and getuid() == 0

    @property
    def user_data_dir(self) -> str:
        """Data directory tied to the user, e.g. ``~/.local/share/$appname/$version`` or ``$XDG_DATA_HOME/$appname/$version``."""
        return self._append_app_name_and_version(_expand_user("~/.local/share"), private=True)

    @property
    def _site_data_dirs(self) -> list[str]:
        return [self._join_app_name_and_version("/usr/local/share"), self._join_app_name_and_version("/usr/share")]

    @property
    def user_config_dir(self) -> str:
        """Config directory tied to the user, e.g. ``~/.config/$appname/$version`` or ``$XDG_CONFIG_HOME/$appname/$version``."""
        return self._append_app_name_and_version(_expand_user("~/.config"), private=True)

    @property
    def _site_config_dirs(self) -> list[str]:
        return [self._join_app_name_and_version("/etc/xdg")]

    @property
    def user_cache_dir(self) -> str:
        """Cache directory tied to the user, e.g. ``~/.cache/$appname/$version`` or ``$XDG_CACHE_HOME/$appname/$version``."""
        return self._append_app_name_and_version(_expand_user("~/.cache"), private=True)

    @property
    def site_cache_dir(self) -> str:
        """Cache directory shared by users, e.g. ``/var/cache/$appname/$version``."""
        return self._append_app_name_and_version("/var/cache", private=False)

    @property
    def user_state_dir(self) -> str:
        """State directory tied to the user, e.g. ``~/.local/state/$appname/$version`` or ``$XDG_STATE_HOME/$appname/$version``."""
        return self._append_app_name_and_version(_expand_user("~/.local/state"), private=True)

    @property
    def site_state_dir(self) -> str:
        """State directory shared by users, e.g. ``/var/lib/$appname/$version``."""
        return self._append_app_name_and_version("/var/lib", private=False)

    @property
    def user_log_dir(self) -> str:
        """Log directory tied to the user, same as `user_state_dir` if not opinionated else ``log`` in it."""
        path = self.user_state_dir
        if self.opinion:
            path = os.path.join(path, "log")  # ruff:ignore[os-path-join]
            self._optionally_create_directory(path, private=True)
        return path

    @property
    def site_log_dir(self) -> str:
        """Log directory shared by users, e.g. ``/var/log/$appname/$version``.

        Unlike `user_log_dir`, ``opinion`` has no effect since ``/var/log`` is inherently a log directory.

        """
        return self._append_app_name_and_version("/var/log", private=False)

    @property
    def user_documents_dir(self) -> str:
        """Documents directory tied to the user, e.g. ``~/Documents``."""
        return self._user_media_dir("XDG_DOCUMENTS_DIR", "~/Documents")

    @property
    def user_downloads_dir(self) -> str:
        """Downloads directory tied to the user, e.g. ``~/Downloads``."""
        return self._user_media_dir("XDG_DOWNLOAD_DIR", "~/Downloads")

    @property
    def user_pictures_dir(self) -> str:
        """Pictures directory tied to the user, e.g. ``~/Pictures``."""
        return self._user_media_dir("XDG_PICTURES_DIR", "~/Pictures")

    @property
    def user_videos_dir(self) -> str:
        """Videos directory tied to the user, e.g. ``~/Videos``."""
        return self._user_media_dir("XDG_VIDEOS_DIR", "~/Videos")

    @property
    def user_music_dir(self) -> str:
        """Music directory tied to the user, e.g. ``~/Music``."""
        return self._user_media_dir("XDG_MUSIC_DIR", "~/Music")

    @property
    def user_desktop_dir(self) -> str:
        """Desktop directory tied to the user, e.g. ``~/Desktop``."""
        return self._user_media_dir("XDG_DESKTOP_DIR", "~/Desktop")

    @property
    def user_projects_dir(self) -> str:
        """Projects directory tied to the user, e.g. ``~/Projects``."""
        return self._user_media_dir("XDG_PROJECTS_DIR", "~/Projects")

    @property
    def user_publicshare_dir(self) -> str:
        """Public share directory tied to the user, e.g. ``~/Public``."""
        return self._user_media_dir("XDG_PUBLICSHARE_DIR", "~/Public")

    @property
    def user_templates_dir(self) -> str:
        """Templates directory tied to the user, e.g. ``~/Templates``."""
        return self._user_media_dir("XDG_TEMPLATES_DIR", "~/Templates")

    def _user_media_dir(self, key: str, default: str) -> str:
        if path := _get_user_dirs_folder(key):
            self._optionally_create_media_directory(path)
            return path
        return _expand_user(default)

    @property
    def user_fonts_dir(self) -> str:
        """Fonts directory tied to the user, e.g. ``~/.local/share/fonts``."""
        return f"{_expand_user('~/.local/share')}/fonts"

    @property
    def user_preference_dir(self) -> str:
        """Preference directory tied to the user, same as ``user_config_dir``."""
        return self.user_config_dir

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
        """Applications directory tied to the user, e.g. ``~/.local/share/applications``."""
        return f"{_expand_user('~/.local/share')}{os.sep}applications"

    @property
    def _site_applications_dirs(self) -> list[str]:
        return [os.path.join(p, "applications") for p in ["/usr/local/share", "/usr/share"]]  # ruff:ignore[os-path-join]

    def _default_runtime_dir(self) -> str:
        if sys.platform.startswith("openbsd"):
            path = f"/tmp/run/user/{getuid()}"  # ruff:ignore[hardcoded-temp-file]
        elif sys.platform.startswith(("freebsd", "netbsd")):
            path = f"/var/run/user/{getuid()}"
        else:
            path = f"/run/user/{getuid()}"
        return path if os.path.lexists(path) and not _runtime_dir_problem(path) else self._temp_runtime_dir()

    def _temp_runtime_dir(self) -> str:
        # Another user can pre-create this predictable name, and XDG requires an owned runtime dir with mode 0700.
        path = f"{gettempdir()}/runtime-{getuid()}"
        with suppress(FileExistsError):
            self._optionally_create_directory(path, private=True)
        if problem := _runtime_dir_problem(path, check_mode=False):
            msg = f"runtime directory {problem}; set XDG_RUNTIME_DIR instead"
            raise PermissionError(msg)
        # Earlier releases created this directory with the default 0755.
        if self.ensure_exists:
            Path(path).chmod(_RUNTIME_DIR_MODE)
        return path

    @property
    def site_runtime_dir(self) -> str:
        """Runtime directory shared by users, e.g. ``/run/$appname/$version`` or ``$XDG_RUNTIME_DIR/$appname/$version``.

        Note that this behaves almost exactly like `user_runtime_dir` if ``$XDG_RUNTIME_DIR`` is set, but will fall back
        to paths associated to the root user instead of a regular logged-in user if it's not set.

        If you wish to ensure that a logged-in root user path is returned e.g. ``/run/user/0``, use `user_runtime_dir`
        instead.

        For FreeBSD/OpenBSD/NetBSD, it would return ``/var/run/$appname/$version`` if ``$XDG_RUNTIME_DIR`` is not set.

        """
        if sys.platform.startswith(("freebsd", "openbsd", "netbsd")):
            path = "/var/run"
        else:
            path = "/run"
        return self._append_app_name_and_version(path, private=False)


class Unix(XDGMixin, _UnixDefaults):
    """On Unix/Linux, we follow the `XDG Basedir Spec <https://specifications.freedesktop.org/basedir/latest/>`_.

    The spec allows overriding directories with environment variables. The examples shown are the default values,
    alongside the name of the environment variable that overrides them. Makes use of the `appname
    <platformdirs.api.PlatformDirsABC.appname>`, `version <platformdirs.api.PlatformDirsABC.version>`, `multipath
    <platformdirs.api.PlatformDirsABC.multipath>`, `opinion <platformdirs.api.PlatformDirsABC.opinion>`, `ensure_exists
    <platformdirs.api.PlatformDirsABC.ensure_exists>`.

    """

    @property
    def user_data_dir(self) -> str:
        """Data directory tied to the user, or site equivalent when root with ``use_site_for_root``."""
        return self.site_data_dir if self._use_site else super().user_data_dir

    @property
    def user_config_dir(self) -> str:
        """Config directory tied to the user, or site equivalent when root with ``use_site_for_root``."""
        return self.site_config_dir if self._use_site else super().user_config_dir

    @property
    def user_cache_dir(self) -> str:
        """Cache directory tied to the user, or site equivalent when root with ``use_site_for_root``."""
        return self.site_cache_dir if self._use_site else super().user_cache_dir

    @property
    def user_state_dir(self) -> str:
        """State directory tied to the user, or site equivalent when root with ``use_site_for_root``."""
        return self.site_state_dir if self._use_site else super().user_state_dir

    @property
    def user_log_dir(self) -> str:
        """Log directory tied to the user, or site equivalent when root with ``use_site_for_root``."""
        return self.site_log_dir if self._use_site else super().user_log_dir

    @property
    def user_applications_dir(self) -> str:
        """Applications directory tied to the user, or site equivalent when root with ``use_site_for_root``."""
        return self.site_applications_dir if self._use_site else super().user_applications_dir

    @property
    def user_runtime_dir(self) -> str:
        """Runtime directory tied to the user, e.g. ``$XDG_RUNTIME_DIR/$appname/$version``.

        Accepts ``$XDG_RUNTIME_DIR`` only as a directory, not a symlink, that the user owns with mode ``0700``, as the
        XDG spec requires, and creates a missing one that way under ``ensure_exists``. When the variable is unset or
        fails that check, emits one :class:`~platformdirs.RuntimeDirWarning` per cause and falls back to the platform
        default (``/tmp/run/user/<uid>`` on OpenBSD, ``/var/run/user/<uid>`` on FreeBSD/NetBSD, ``/run/user/<uid>``
        elsewhere) if it passes the same check, else to ``runtime-<uid>`` in the temporary directory. Root with
        ``use_site_for_root`` gets the site equivalent.

        :raises PermissionError: if the temporary fallback is a symlink, not a directory, or owned by another user.

        """
        if self._use_site:
            # XDGMixin.site_runtime_dir reads $XDG_RUNTIME_DIR, which belongs to the user who started the root process.
            return super(XDGMixin, self).site_runtime_dir
        if not (path := _xdg_dir("XDG_RUNTIME_DIR")):
            reason = "XDG_RUNTIME_DIR is not set"
        else:
            with suppress(OSError):
                self._optionally_create_directory(path, private=True)
            if not (problem := _runtime_dir_problem(path)):
                return self._append_app_name_and_version(path, private=True)
            reason = f"XDG_RUNTIME_DIR {problem}"
        _warn_once(f"{reason}, falling back to {(fallback := self._default_runtime_dir())}")
        return self._append_app_name_and_version(fallback, private=True)

    @property
    def user_bin_dir(self) -> str:
        """Bin directory tied to the user, or site equivalent when root with ``use_site_for_root``."""
        return self.site_bin_dir if self._use_site else super().user_bin_dir

    @property
    def user_data_path(self) -> Path:
        """Data path tied to the user, or the first site entry when root with ``use_site_for_root``."""
        return self.site_data_path if self._use_site else super().user_data_path

    @property
    def user_config_path(self) -> Path:
        """Config path tied to the user, or the first site entry when root with ``use_site_for_root``."""
        return self.site_config_path if self._use_site else super().user_config_path

    @property
    def user_preference_path(self) -> Path:
        """Preference path tied to the user, or the first site config entry when root with ``use_site_for_root``."""
        return self.site_config_path if self._use_site else super().user_preference_path

    @property
    def user_applications_path(self) -> Path:
        """Applications path tied to the user, or the first site entry when root with ``use_site_for_root``."""
        return self.site_applications_path if self._use_site else super().user_applications_path


_USER_DIRS_LINE: Final = re.compile(
    r"""
    [ \t]*(?P<key>\w+)[ \t]*=[ \t]*  # KEY=, blanks allowed around the key and after the =
    (?:
        "(?P<quoted>(?:[^"\\]|\\.)*)"  # a double-quoted value with backslash escapes, text after it ignored
        |(?P<bare>[^"\s].*?)          # or an unquoted value, up to
        (?:[ \t]+\#.*|[ \t]*)$         # a comment, which sh starts at a word-initial #, or the line end
    )
    """,
    re.VERBOSE,
)


def _get_user_dirs_folder(key: str) -> str | None:
    """Return directory from user-dirs.dirs config file.

    ``xdg-user-dirs-update`` writes shell assignments, so match each line like ``xdg-user-dir`` does and keep the last
    valid assignment to ``key``.

    See https://freedesktop.org/wiki/Software/xdg-user-dirs/.

    """
    config_home = _xdg_dir("XDG_CONFIG_HOME") or _expand_user("~/.config")
    user_dirs_config_path = Path(config_home) / "user-dirs.dirs"
    if not user_dirs_config_path.exists():
        return None
    folder = None
    # the file holds raw path bytes, and surrogateescape round-trips undecodable ones like os.fsdecode
    with user_dirs_config_path.open(encoding=sys.getfilesystemencoding(), errors="surrogateescape") as stream:
        for line in stream:
            if (entry := _USER_DIRS_LINE.match(line)) and entry["key"] == key:
                folder = _resolve_user_dirs_value(entry) or folder
    return folder


def _resolve_user_dirs_value(entry: re.Match[str]) -> str | None:
    value = entry["bare"] if entry["quoted"] is None else entry["quoted"]
    if value == "$HOME" or value.startswith("$HOME/"):
        prefix, value = _expand_user("~"), value.removeprefix("$HOME")
    elif value.startswith("/"):
        prefix = ""
    else:
        return None
    if entry["quoted"] is not None:
        # xdg-user-dirs-update backslash-escapes $, `, " and \ inside the quotes.
        value = re.sub(r"\\(.)", r"\1", value)
    return prefix + value


def _runtime_dir_problem(path: str, *, check_mode: bool = True) -> str | None:
    """Return why ``path`` fails the checks of Qt's ``checkXdgRuntimeDir``, or ``None`` if it passes or is missing."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        return f"{path} cannot be checked: {error.strerror}"
    mode = info.st_mode & 0o777
    checks = (
        (stat.S_ISLNK(info.st_mode), "is a symlink"),
        (not stat.S_ISDIR(info.st_mode), "is not a directory"),
        (info.st_uid != (uid := getuid()), f"is owned by uid {info.st_uid}, not {uid}"),
        (check_mode and mode != _RUNTIME_DIR_MODE, f"has mode {mode:04o}, not {_RUNTIME_DIR_MODE:04o}"),
    )
    return next((f"{path} {problem}" for failed, problem in checks if failed), None)


def _warn_once(message: str) -> None:
    # Each read of user_runtime_dir repeats the check, so a warning per read would flood long-running programs.
    if message not in _WARNED:
        _WARNED.add(message)
        warnings.warn(message, RuntimeDirWarning, stacklevel=3)


_WARNED: Final[set[str]] = set()
_RUNTIME_DIR_MODE: Final = 0o700


__all__ = [
    "Unix",
]
