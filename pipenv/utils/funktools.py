"""
A small collection of useful functional tools for working with iterables.
"""

import errno
import locale
import os
import stat
import subprocess
import time
import warnings
from functools import partial
from itertools import count, islice
from typing import Any, Iterable

DIRECTORY_CLEANUP_TIMEOUT = 1.0


def _is_iterable(elem: Any) -> bool:
    if getattr(elem, "__iter__", False) or isinstance(elem, Iterable):
        return True
    return False


def take(n: int, iterable: Iterable) -> Iterable:
    """Take n elements from the supplied iterable without consuming it.

    :param int n: Number of unique groups
    :param iter iterable: An iterable to split up
    """
    return list(islice(iterable, n))


def chunked(n: int, iterable: Iterable) -> Iterable:
    """Split an iterable into lists of length *n*.

    :param int n: Number of unique groups
    :param iter iterable: An iterable to split up

    """
    return iter(partial(take, n, iter(iterable)), [])


def unnest(elem: Iterable) -> Any:
    """Flatten an arbitrarily nested iterable.

    :param elem: An iterable to flatten
    :type elem: :class:`~collections.Iterable`
    >>> nested_iterable = (
            1234, (3456, 4398345, (234234)), (
                2396, (
                    928379, 29384, (
                        293759, 2347, (
                            2098, 7987, 27599
                        )
                    )
                )
            )
        )
    >>> list(unnest(nested_iterable))
    [1234, 3456, 4398345, 234234, 2396, 928379, 29384, 293759,
     2347, 2098, 7987, 27599]
    """

    if isinstance(elem, Iterable) and not isinstance(elem, str):
        for el in elem:
            if isinstance(el, Iterable) and not isinstance(el, str):
                yield from unnest(el)
            else:
                yield el
    else:
        yield elem


def dedup(iterable: Iterable) -> Iterable:
    """Deduplicate an iterable object like iter(set(iterable)) but order-
    preserved."""

    return iter(dict.fromkeys(iterable))


def is_readonly_path(fn: os.PathLike) -> bool:
    """check if a provided path exists and is readonly.

    permissions check is `bool(path.stat & stat.s_iread)` or `not
    os.access(path, os.w_ok)`
    """
    if os.path.exists(fn):
        file_stat = os.stat(fn).st_mode
        return not bool(file_stat & stat.s_iwrite) or not os.access(fn, os.w_ok)
    return False


def _wait_for_files(path):  # pragma: no cover
    """Retry with backoff up to 1 second to delete files from a directory.

    :param str path: The path to crawl to delete files from
    :return: A list of remaining paths or None
    :rtype: Optional[List[str]]
    """
    timeout = 0.001  # noqa:S101
    remaining = []
    while timeout < DIRECTORY_CLEANUP_TIMEOUT:
        remaining = []
        if os.path.isdir(path):
            L = os.listdir(path)
            for target in L:
                _remaining = _wait_for_files(target)
                if _remaining:
                    remaining.extend(_remaining)
            continue
        try:
            os.unlink(path)
        except FileNotFoundError as e:
            if e.errno == errno.ENOENT:
                return
        except (OSError, PermissionError):  # noqa:B014
            time.sleep(timeout)
            timeout *= 2
            remaining.append(path)
        else:
            return
    return remaining


def _walk_for_powershell(directory):
    for _, dirs, files in os.walk(directory):
        powershell = next(
            iter(fn for fn in files if fn.lower() == "powershell.exe"), None
        )
        if powershell is not None:
            return os.path.join(directory, powershell)
        for subdir in dirs:
            powershell = _walk_for_powershell(os.path.join(directory, subdir))
            if powershell:
                return powershell
    return None


def _get_powershell_path():
    paths = [
        os.path.expandvars(r"%windir%\{0}\WindowsPowerShell").format(subdir)
        for subdir in ("SysWOW64", "system32")
    ]
    powershell_path = next(iter(_walk_for_powershell(pth) for pth in paths), None)
    if not powershell_path:
        powershell_path = subprocess.run(["where", "powershell"], check=False)
    if powershell_path.stdout:
        return powershell_path.stdout.strip()


def _get_sid_with_powershell():
    powershell_path = _get_powershell_path()
    if not powershell_path:
        return None
    args = [
        powershell_path,
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Invoke-Expression '[System.Security.Principal.WindowsIdentity]::GetCurrent().user | Write-Host'",
    ]
    sid = subprocess.run(args, capture_output=True, check=False)
    return sid.stdout.strip()


def get_value_from_tuple(value, value_type):
    try:
        import winreg
    except ImportError:
        import _winreg as winreg
    if value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        if "\0" in value:
            return value[: value.index("\0")]
        return value
    return None


def query_registry_value(root, key_name, value):
    try:
        import winreg
    except ImportError:
        import _winreg as winreg
    try:
        with winreg.OpenKeyEx(root, key_name, 0, winreg.KEY_READ) as key:
            return get_value_from_tuple(*winreg.QueryValueEx(key, value))
    except OSError:
        return None


def _get_sid_from_registry():
    try:
        import winreg
    except ImportError:
        import _winreg as winreg
    var_names = ("%USERPROFILE%", "%HOME%")
    current_user_home = next(iter(os.path.expandvars(v) for v in var_names if v), None)
    root, subkey = (
        winreg.HKEY_LOCAL_MACHINE,
        r"Software\Microsoft\Windows NT\CurrentVersion\ProfileList",
    )
    subkey_names = []
    value = None
    matching_key = None
    try:
        with winreg.OpenKeyEx(root, subkey, 0, winreg.KEY_READ) as key:
            for i in count():
                key_name = winreg.EnumKey(key, i)
                subkey_names.append(key_name)
                value = query_registry_value(
                    root, rf"{subkey}\{key_name}", "ProfileImagePath"
                )
                if value and value.lower() == current_user_home.lower():
                    matching_key = key_name
                    break
    except OSError:
        pass
    if matching_key is not None:
        return matching_key


def _get_current_user():
    fns = (_get_sid_from_registry, _get_sid_with_powershell)
    for fn in fns:
        result = fn()
        if result:
            return result
    return None


def _find_icacls_exe():
    if os.name == "nt":
        paths = [
            os.path.expandvars(r"%windir%\{0}").format(subdir)
            for subdir in ("system32", "SysWOW64")
        ]
        for path in paths:
            icacls_path = next(
                iter(fn for fn in os.listdir(path) if fn.lower() == "icacls.exe"), None
            )
            if icacls_path is not None:
                icacls_path = os.path.join(path, icacls_path)
                return icacls_path
    return None


def set_write_bit(fn: str) -> None:
    """Set read-write permissions for the current user on the target path. Fail
    silently if the path doesn't exist.

    :param str fn: The target filename or path
    :return: None
    """
    if not os.path.exists(fn):
        return
    file_stat = os.stat(fn).st_mode
    os.chmod(fn, file_stat | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    if os.name == "nt":
        user_sid = _get_current_user()
        icacls_exe = _find_icacls_exe() or "icacls"

        if user_sid:
            c = subprocess.run(
                [
                    icacls_exe,
                    f"''{fn}''",
                    "/grant",
                    f"{user_sid}:WD",
                    "/T",
                    "/C",
                    "/Q",
                ],
                capture_output=True,
                # 2020-06-12 Yukihiko Shinoda
                # There are 3 way to get system default encoding in Stack Overflow.
                # see: https://stackoverflow.com/questions/37506535/how-to-get-the-system-default-encoding-in-python-2-x
                # I investigated these way by using Shift-JIS Windows.
                # >>> import locale
                # >>> locale.getpreferredencoding()
                # "cp932" (Shift-JIS)
                # >>> import sys
                # >>> sys.getdefaultencoding()
                # "utf-8"
                # >>> sys.stdout.encoding
                # "UTF8"
                encoding=locale.getpreferredencoding(),
                check=False,
            )
            if not c.err and c.returncode == 0:
                return

    if not os.path.isdir(fn):
        for path in [fn, os.path.dirname(fn)]:
            try:
                os.chflags(path, 0)
            except AttributeError:  # noqa: PERF203
                pass
        return None
    for root, dirs, files in os.walk(fn, topdown=False):
        for dir_ in [os.path.join(root, d) for d in dirs]:
            set_write_bit(dir_)
        for file_ in [os.path.join(root, f) for f in files]:
            set_write_bit(file_)


def handle_remove_readonly(func, path, exc):
    """Error handler for shutil.rmtree.

    Windows source repo folders are read-only by default, so this error handler
    attempts to set them as writeable and then proceed with deletion.

    :param function func: The caller function
    :param str path: The target path for removal
    :param Exception exc: The raised exception

    This function will call check :func:`is_readonly_path` before attempting to call
    :func:`set_write_bit` on the target path and try again.
    """

    PERM_ERRORS = (errno.EACCES, errno.EPERM, errno.ENOENT)
    default_warning_message = "Unable to remove file due to permissions restriction: {!r}"
    # split the initial exception out into its type, exception, and traceback
    exc_type, exc_exception, exc_tb = exc
    if is_readonly_path(path):
        # Apply write permission and call original function
        set_write_bit(path)
        try:
            func(path)
        except (OSError, FileNotFoundError, PermissionError) as e:  # pragma: no cover
            if e.errno in PERM_ERRORS:
                if e.errno == errno.ENOENT:
                    return
                remaining = None
                if os.path.isdir(path):
                    remaining = _wait_for_files(path)
                if remaining:
                    warnings.warn(
                        default_warning_message.format(path),
                        ResourceWarning,
                        stacklevel=2,
                    )
                else:
                    func(path, ignore_errors=True)
                return

    if exc_exception.errno in PERM_ERRORS:
        set_write_bit(path)
        remaining = _wait_for_files(path)
        try:
            func(path)
        except (OSError, FileNotFoundError, PermissionError) as e:  # noqa:B014
            if e.errno in PERM_ERRORS and e.errno != errno.ENOENT:  # File still exists
                warnings.warn(
                    default_warning_message.format(path),
                    ResourceWarning,
                    stacklevel=2,
                )
            return
    else:
        raise exc_exception
