import functools
import logging
import os
import pathlib
import sys
import sysconfig
from typing import Dict, Iterator, List, Optional, Tuple

from pipenv.patched.notpip._internal.models.scheme import SCHEME_KEYS, Scheme
from pipenv.patched.notpip._internal.utils.compat import WINDOWS
from pipenv.patched.notpip._internal.utils.deprecation import deprecated

from . import _distutils, _sysconfig
from .base import (
    USER_CACHE_DIR,
    get_major_minor_version,
    get_src_prefix,
    is_osx_framework,
    site_packages,
    user_site,
)

__all__ = [
    "USER_CACHE_DIR",
    "get_bin_prefix",
    "get_bin_user",
    "get_major_minor_version",
    "get_platlib",
    "get_prefixed_libs",
    "get_purelib",
    "get_scheme",
    "get_src_prefix",
    "site_packages",
    "user_site",
]


logger = logging.getLogger(__name__)

if os.environ.get("_PIP_LOCATIONS_NO_WARN_ON_MISMATCH"):
    _MISMATCH_LEVEL = logging.DEBUG
else:
    _MISMATCH_LEVEL = logging.WARNING


def _looks_like_red_hat_patched_platlib_purelib(scheme: Dict[str, str]) -> bool:
    platlib = scheme["platlib"]
    if "/lib64/" not in platlib:
        return False
    unpatched = platlib.replace("/lib64/", "/lib/")
    return unpatched.replace("$platbase/", "$base/") == scheme["purelib"]


@functools.lru_cache(maxsize=None)
def _looks_like_red_hat_patched() -> bool:
    """Red Hat patches platlib in unix_prefix and unix_home, but not purelib.

    This is the only way I can see to tell a Red Hat-patched Python.
    """
    from distutils.command.install import INSTALL_SCHEMES  # type: ignore

    return all(
        k in INSTALL_SCHEMES
        and _looks_like_red_hat_patched_platlib_purelib(INSTALL_SCHEMES[k])
        for k in ("unix_prefix", "unix_home")
    )


@functools.lru_cache(maxsize=None)
def _looks_like_debian_patched() -> bool:
    """Debian adds two additional schemes."""
    from distutils.command.install import INSTALL_SCHEMES  # type: ignore

    return "deb_system" in INSTALL_SCHEMES and "unix_local" in INSTALL_SCHEMES


def _fix_abiflags(parts: Tuple[str]) -> Iterator[str]:
    ldversion = sysconfig.get_config_var("LDVERSION")
    abiflags: str = getattr(sys, "abiflags", None)

    # LDVERSION does not end with sys.abiflags. Just return the path unchanged.
    if not ldversion or not abiflags or not ldversion.endswith(abiflags):
        yield from parts
        return

    # Strip sys.abiflags from LDVERSION-based path components.
    for part in parts:
        if part.endswith(ldversion):
            part = part[: (0 - len(abiflags))]
        yield part


def _default_base(*, user: bool) -> str:
    if user:
        base = sysconfig.get_config_var("userbase")
    else:
        base = sysconfig.get_config_var("base")
    assert base is not None
    return base


@functools.lru_cache(maxsize=None)
def _warn_mismatched(old: pathlib.Path, new: pathlib.Path, *, key: str) -> None:
    issue_url = "https://github.com/pypa/pip/issues/10151"
    message = (
        "Value for %s does not match. Please report this to <%s>"
        "\ndistutils: %s"
        "\nsysconfig: %s"
    )
    logger.log(_MISMATCH_LEVEL, message, key, issue_url, old, new)


def _warn_if_mismatch(old: pathlib.Path, new: pathlib.Path, *, key: str) -> bool:
    if old == new:
        return False
    _warn_mismatched(old, new, key=key)
    return True


@functools.lru_cache(maxsize=None)
def _log_context(
    *,
    user: bool = False,
    home: Optional[str] = None,
    root: Optional[str] = None,
    prefix: Optional[str] = None,
) -> None:
    parts = [
        "Additional context:",
        "user = %r",
        "home = %r",
        "root = %r",
        "prefix = %r",
    ]

    logger.log(_MISMATCH_LEVEL, "\n".join(parts), user, home, root, prefix)


def get_scheme(
    dist_name: str,
    user: bool = False,
    home: Optional[str] = None,
    root: Optional[str] = None,
    isolated: bool = False,
    prefix: Optional[str] = None,
) -> Scheme:
    old = _distutils.get_scheme(
        dist_name,
        user=user,
        home=home,
        root=root,
        isolated=isolated,
        prefix=prefix,
    )
    new = _sysconfig.get_scheme(
        dist_name,
        user=user,
        home=home,
        root=root,
        isolated=isolated,
        prefix=prefix,
    )

    base = prefix or home or _default_base(user=user)
    warning_contexts = []
    for k in SCHEME_KEYS:
        # Extra join because distutils can return relative paths.
        old_v = pathlib.Path(base, getattr(old, k))
        new_v = pathlib.Path(getattr(new, k))

        if old_v == new_v:
            continue

        # distutils incorrectly put PyPy packages under ``site-packages/python``
        # in the ``posix_home`` scheme, but PyPy devs said they expect the
        # directory name to be ``pypy`` instead. So we treat this as a bug fix
        # and not warn about it. See bpo-43307 and python/cpython#24628.
        skip_pypy_special_case = (
            sys.implementation.name == "pypy"
            and home is not None
            and k in ("platlib", "purelib")
            and old_v.parent == new_v.parent
            and old_v.name.startswith("python")
            and new_v.name.startswith("pypy")
        )
        if skip_pypy_special_case:
            continue

        # sysconfig's ``osx_framework_user`` does not include ``pythonX.Y`` in
        # the ``include`` value, but distutils's ``headers`` does. We'll let
        # CPython decide whether this is a bug or feature. See bpo-43948.
        skip_osx_framework_user_special_case = (
            user
            and is_osx_framework()
            and k == "headers"
            and old_v.parent.parent == new_v.parent
            and old_v.parent.name.startswith("python")
        )
        if skip_osx_framework_user_special_case:
            continue

        # On Red Hat and derived Linux distributions, distutils is patched to
        # use "lib64" instead of "lib" for platlib.
        if k == "platlib" and _looks_like_red_hat_patched():
            continue

        # Both Debian and Red Hat patch Python to place the system site under
        # /usr/local instead of /usr. Debian also places lib in dist-packages
        # instead of site-packages, but the /usr/local check should cover it.
        skip_linux_system_special_case = (
            not (user or home or prefix)
            and old_v.parts[1:3] == ("usr", "local")
            and len(new_v.parts) > 1
            and new_v.parts[1] == "usr"
            and (len(new_v.parts) < 3 or new_v.parts[2] != "local")
            and (_looks_like_red_hat_patched() or _looks_like_debian_patched())
        )
        if skip_linux_system_special_case:
            continue

        # On Python 3.7 and earlier, sysconfig does not include sys.abiflags in
        # the "pythonX.Y" part of the path, but distutils does.
        skip_sysconfig_abiflag_bug = (
            sys.version_info < (3, 8)
            and not WINDOWS
            and k in ("headers", "platlib", "purelib")
            and tuple(_fix_abiflags(old_v.parts)) == new_v.parts
        )
        if skip_sysconfig_abiflag_bug:
            continue

        warning_contexts.append((old_v, new_v, f"scheme.{k}"))

    if not warning_contexts:
        return old

    # Check if this path mismatch is caused by distutils config files. Those
    # files will no longer work once we switch to sysconfig, so this raises a
    # deprecation message for them.
    default_old = _distutils.distutils_scheme(
        dist_name,
        user,
        home,
        root,
        isolated,
        prefix,
        ignore_config_files=True,
    )
    if any(default_old[k] != getattr(old, k) for k in SCHEME_KEYS):
        deprecated(
            "Configuring installation scheme with distutils config files "
            "is deprecated and will no longer work in the near future. If you "
            "are using a Homebrew or Linuxbrew Python, please see discussion "
            "at https://github.com/Homebrew/homebrew-core/issues/76621",
            replacement=None,
            gone_in=None,
        )
        return old

    # Post warnings about this mismatch so user can report them back.
    for old_v, new_v, key in warning_contexts:
        _warn_mismatched(old_v, new_v, key=key)
    _log_context(user=user, home=home, root=root, prefix=prefix)

    return old


def get_bin_prefix() -> str:
    old = _distutils.get_bin_prefix()
    new = _sysconfig.get_bin_prefix()
    if _warn_if_mismatch(pathlib.Path(old), pathlib.Path(new), key="bin_prefix"):
        _log_context()
    return old


def get_bin_user() -> str:
    return _sysconfig.get_scheme("", user=True).scripts


def get_purelib() -> str:
    """Return the default pure-Python lib location."""
    old = _distutils.get_purelib()
    new = _sysconfig.get_purelib()
    if _warn_if_mismatch(pathlib.Path(old), pathlib.Path(new), key="purelib"):
        _log_context()
    return old


def get_platlib() -> str:
    """Return the default platform-shared lib location."""
    old = _distutils.get_platlib()
    new = _sysconfig.get_platlib()
    if _warn_if_mismatch(pathlib.Path(old), pathlib.Path(new), key="platlib"):
        _log_context()
    return old


def get_prefixed_libs(prefix: str) -> List[str]:
    """Return the lib locations under ``prefix``."""
    old_pure, old_plat = _distutils.get_prefixed_libs(prefix)
    new_pure, new_plat = _sysconfig.get_prefixed_libs(prefix)

    warned = [
        _warn_if_mismatch(
            pathlib.Path(old_pure),
            pathlib.Path(new_pure),
            key="prefixed-purelib",
        ),
        _warn_if_mismatch(
            pathlib.Path(old_plat),
            pathlib.Path(new_plat),
            key="prefixed-platlib",
        ),
    ]
    if any(warned):
        _log_context(prefix=prefix)

    if old_pure == old_plat:
        return [old_pure]
    return [old_pure, old_plat]
