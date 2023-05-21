import ast
import atexit
import configparser
import contextlib
import errno
import locale
import os
import shutil
import stat
import subprocess as sp
import sys
import time
import warnings
from collections.abc import Iterable, Mapping
from contextlib import ExitStack
from functools import lru_cache
from itertools import count
from os import scandir
from pathlib import Path
from typing import Any, AnyStr, Callable, Dict, Generator, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlparse, urlunparse

from pipenv.patched.pip._vendor.distlib.wheel import Wheel
from pipenv.vendor.pep517 import envbuild, wrappers
from pipenv.patched.pip._internal.network.download import Downloader
from pipenv.patched.pip._internal.operations.prepare import unpack_url
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.utils.temp_dir import global_tempdir_manager
from pipenv.patched.pip._vendor.packaging.requirements import Requirement as PackagingRequirement
from pipenv.patched.pip._vendor.packaging.specifiers import SpecifierSet
from pipenv.patched.pip._vendor.packaging.version import parse
from pipenv.patched.pip._vendor.pkg_resources import (
    DistInfoDistribution,
    EggInfoDistribution,
    PathMetadata,
    Requirement,
    distributions_from_metadata,
    find_distributions,
)
from pipenv.patched.pip._vendor.platformdirs import user_cache_dir
from pipenv.patched.pip._vendor.pyparsing.core import cached_property
from pipenv.vendor.pydantic import Field

from ..fileutils import cd, create_tracked_tempdir, temp_path, url_to_path
from ..utils import get_pip_command
from .common import ReqLibBaseModel
from .old_pip_utils import _copy_source_tree
from .utils import (
    HashableRequirement,
    convert_to_hashable_requirement,
    get_default_pyproject_backend,
    get_name_variants,
    get_pyproject,
    init_requirement,
    split_vcs_method_from_uri,
    strip_extras_markers_from_requirement,
)

CACHE_DIR = os.environ.get("PIPENV_CACHE_DIR", user_cache_dir("pipenv"))

# The following are necessary for people who like to use "if __name__" conditionals
# in their setup.py scripts
_setup_stop_after = None
_setup_distribution = None


def pep517_subprocess_runner(cmd, cwd=None, extra_environ=None) -> None:
    """The default method of calling the wrapper subprocess."""
    env = os.environ.copy()
    if extra_environ:
        env.update(extra_environ)

    sp.run(cmd, cwd=cwd, env=env, stdout=sp.PIPE, stderr=sp.STDOUT)


class BuildEnv(envbuild.BuildEnvironment):
    def pip_install(self, reqs):
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--ignore-installed",
            "--prefix",
            self.path,
        ] + list(reqs)

        sp.run(cmd, stderr=sp.PIPE, stdout=sp.PIPE)


class HookCaller(wrappers.Pep517HookCaller):
    def __init__(self, source_dir, build_backend, backend_path=None):
        super().__init__(source_dir, build_backend, backend_path=backend_path)
        self.source_dir = os.path.abspath(source_dir)
        self.build_backend = build_backend
        self._subprocess_runner = pep517_subprocess_runner
        if backend_path:
            backend_path = [
                wrappers.norm_and_check(self.source_dir, p) for p in backend_path
            ]
        self.backend_path = backend_path


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


def is_readonly_path(fn: os.PathLike) -> bool:
    """check if a provided path exists and is readonly.

    permissions check is `bool(path.stat & stat.s_iread)` or `not
    os.access(path, os.w_ok)`
    """
    if os.path.exists(fn):
        file_stat = os.stat(fn).st_mode
        return not bool(file_stat & stat.s_iwrite) or not os.access(fn, os.w_ok)
    return False


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
        powershell_path = sp.run(["where", "powershell"])
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
    sid = sp.run(args, capture_output=True)
    return sid.stdout.strip()


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
                    root, r"{0}\{1}".format(subkey, key_name), "ProfileImagePath"
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


def _wait_for_files(path):  # pragma: no cover
    """Retry with backoff up to 1 second to delete files from a directory.

    :param str path: The path to crawl to delete files from
    :return: A list of remaining paths or None
    :rtype: Optional[List[str]]
    """
    timeout = 0.001
    remaining = []
    while timeout < 1.0:
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
        except (OSError, IOError, PermissionError):  # noqa:B014
            time.sleep(timeout)
            timeout *= 2
            remaining.append(path)
        else:
            return
    return remaining


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
            c = sp.run(
                [
                    icacls_exe,
                    "''{}''".format(fn),
                    "/grant",
                    "{}:WD".format(user_sid),
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
            )
            if not c.err and c.returncode == 0:
                return

    if not os.path.isdir(fn):
        for path in [fn, os.path.dirname(fn)]:
            try:
                os.chflags(path, 0)
            except AttributeError:
                pass
        return None
    for root, dirs, files in os.walk(fn, topdown=False):
        for dir_ in [os.path.join(root, d) for d in dirs]:
            set_write_bit(dir_)
        for file_ in [os.path.join(root, f) for f in files]:
            set_write_bit(file_)


def make_base_requirements(reqs) -> Tuple:
    requirements = ()
    if not isinstance(reqs, (list, tuple, set)):
        reqs = [reqs]
    for req in reqs:
        if isinstance(req, BaseRequirement):
            requirements += (req,)
        elif isinstance(req, Requirement):
            requirements += (BaseRequirement.from_req(req),)
        elif req and isinstance(req, str) and not req.startswith("#"):
            requirements += (BaseRequirement.from_string(req),)
    return requirements


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
        except (  # noqa:B014
            OSError,
            IOError,
            FileNotFoundError,
            PermissionError,
        ) as e:  # pragma: no cover
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
        except (OSError, IOError, FileNotFoundError, PermissionError) as e:  # noqa:B014
            if e.errno in PERM_ERRORS:
                if e.errno != errno.ENOENT:  # File still exists
                    warnings.warn(
                        default_warning_message.format(path),
                        ResourceWarning,
                        stacklevel=2,
                    )
            return
    else:
        raise exc_exception


def rmtree(
    directory: str, ignore_errors: bool = False, onerror: Optional[Callable] = None
) -> None:
    """Stand-in for :func:`~shutil.rmtree` with additional error-handling.

    This version of `rmtree` handles read-only paths, especially in the case of index
    files written by certain source control systems.

    :param str directory: The target directory to remove
    :param bool ignore_errors: Whether to ignore errors, defaults to False
    :param func onerror: An error handling function, defaults to :func:`handle_remove_readonly`

    .. note::

       Setting `ignore_errors=True` may cause this to silently fail to delete the path
    """

    if onerror is None:
        onerror = handle_remove_readonly
    try:
        shutil.rmtree(directory, ignore_errors=ignore_errors, onerror=onerror)
    except (IOError, OSError, FileNotFoundError, PermissionError) as exc:  # noqa:B014
        # Ignore removal failures where the file doesn't exist
        if exc.errno != errno.ENOENT:
            raise


def suppress_unparsable(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Unparsable:
        return None


class Unparsable(ValueError):
    """Not able to parse from setup.py."""


class SetupReader:
    """Class that reads a setup.py file without executing it."""

    @classmethod
    def read_setup_py(cls, file: Path, raising: bool = True) -> "Dict[str, Any]":

        with file.open(encoding="utf-8-sig") as f:
            content = f.read()

        body = ast.parse(content).body

        setup_call, body = cls._find_setup_call(body)
        if not setup_call:
            return {}

        if raising:

            def caller(func, *args, **kwargs):
                return func(*args, **kwargs)

        else:
            caller = suppress_unparsable

        return {
            "name": caller(cls._find_single_string, setup_call, body, "name"),
            "version": caller(cls._find_single_string, setup_call, body, "version"),
            "install_requires": caller(cls._find_install_requires, setup_call, body),
            "extras_require": caller(cls._find_extras_require, setup_call, body),
            "python_requires": caller(
                cls._find_single_string, setup_call, body, "python_requires"
            ),
        }

    @staticmethod
    def read_setup_cfg(file: Path) -> "Dict[str, Any]":
        parser = configparser.ConfigParser()

        parser.read(str(file))

        name = None
        version = None
        if parser.has_option("metadata", "name"):
            name = parser.get("metadata", "name")

        if parser.has_option("metadata", "version"):
            version = parser.get("metadata", "version")

        install_requires = []
        extras_require: "Dict[str, List[str]]" = {}
        python_requires = None
        if parser.has_section("options"):
            if parser.has_option("options", "install_requires"):
                for dep in parser.get("options", "install_requires").split("\n"):
                    dep = dep.strip()
                    if not dep:
                        continue

                    install_requires.append(dep)

            if parser.has_option("options", "python_requires"):
                python_requires = parser.get("options", "python_requires")

        if parser.has_section("options.extras_require"):
            for group in parser.options("options.extras_require"):
                extras_require[group] = []
                deps = parser.get("options.extras_require", group)
                for dep in deps.split("\n"):
                    dep = dep.strip()
                    if not dep:
                        continue

                    extras_require[group].append(dep)

        return {
            "name": name,
            "version": version,
            "install_requires": install_requires,
            "extras_require": extras_require,
            "python_requires": python_requires,
        }

    @classmethod
    def _find_setup_call(
        cls, elements: "List[Any]"
    ) -> "Tuple[Optional[ast.Call], Optional[List[Any]]]":
        funcdefs = []
        for i, element in enumerate(elements):
            if isinstance(element, ast.If) and i == len(elements) - 1:
                # Checking if the last element is an if statement
                # and if it is 'if __name__ == "__main__"' which
                # could contain the call to setup()
                test = element.test
                if not isinstance(test, ast.Compare):
                    continue

                left = test.left
                if not isinstance(left, ast.Name):
                    continue

                if left.id != "__name__":
                    continue

                setup_call, body = cls._find_sub_setup_call([element])
                if not setup_call:
                    continue

                return setup_call, body + elements
            if not isinstance(element, ast.Expr):
                if isinstance(element, ast.FunctionDef):
                    funcdefs.append(element)

                continue

            value = element.value
            if not isinstance(value, ast.Call):
                continue

            func = value.func
            if not (isinstance(func, ast.Name) and func.id == "setup") and not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "setuptools"
                and func.attr == "setup"
            ):
                continue

            return value, elements

        # Nothing, we inspect the function definitions
        return cls._find_sub_setup_call(funcdefs)

    @classmethod
    def _find_sub_setup_call(
        cls, elements: "List[Any]"
    ) -> "Tuple[Optional[ast.Call], Optional[List[Any]]]":
        for element in elements:
            if not isinstance(element, (ast.FunctionDef, ast.If)):
                continue

            setup_call = cls._find_setup_call(element.body)
            if setup_call != (None, None):
                setup_call, body = setup_call

                body = elements + body

                return setup_call, body

        return None, None

    @classmethod
    def _find_install_requires(cls, call: ast.Call, body: "Iterable[Any]") -> "List[str]":
        value = cls._find_in_call(call, "install_requires")
        if value is None:
            # Trying to find in kwargs
            kwargs = cls._find_call_kwargs(call)

            if kwargs is None:
                return []

            if not isinstance(kwargs, ast.Name):
                raise Unparsable()

            variable = cls._find_variable_in_body(body, kwargs.id)
            if not isinstance(variable, (ast.Dict, ast.Call)):
                raise Unparsable()

            if isinstance(variable, ast.Call):
                if not isinstance(variable.func, ast.Name):
                    raise Unparsable()

                if variable.func.id != "dict":
                    raise Unparsable()

                value = cls._find_in_call(variable, "install_requires")
            else:
                value = cls._find_in_dict(variable, "install_requires")

        if value is None:
            return []

        if isinstance(value, ast.List):
            return [el.s for el in value.elts]
        elif isinstance(value, ast.Name):
            variable = cls._find_variable_in_body(body, value.id)

            if variable is not None and isinstance(variable, ast.List):
                return [el.s for el in variable.elts]

        raise Unparsable()

    @classmethod
    def _find_extras_require(
        cls, call: ast.Call, body: "Iterable[Any]"
    ) -> "Dict[str, List[str]]":
        extras_require: "Dict[str, List[str]]" = {}
        value = cls._find_in_call(call, "extras_require")
        if value is None:
            # Trying to find in kwargs
            kwargs = cls._find_call_kwargs(call)

            if kwargs is None:
                return extras_require

            if not isinstance(kwargs, ast.Name):
                raise Unparsable()

            variable = cls._find_variable_in_body(body, kwargs.id)
            if not isinstance(variable, (ast.Dict, ast.Call)):
                raise Unparsable()

            if isinstance(variable, ast.Call):
                if not isinstance(variable.func, ast.Name):
                    raise Unparsable()

                if variable.func.id != "dict":
                    raise Unparsable()

                value = cls._find_in_call(variable, "extras_require")
            else:
                value = cls._find_in_dict(variable, "extras_require")

        if value is None:
            return extras_require

        if isinstance(value, ast.Dict):
            for key, val in zip(value.keys, value.values):
                if isinstance(val, ast.Name):
                    val = cls._find_variable_in_body(body, val.id)

                if isinstance(val, ast.List):
                    extras_require[key.s] = [e.s for e in val.elts]
                else:
                    raise Unparsable()
        elif isinstance(value, ast.Name):
            variable = cls._find_variable_in_body(body, value.id)

            if variable is None or not isinstance(variable, ast.Dict):
                raise Unparsable()

            for key, val in zip(variable.keys, variable.values):
                if isinstance(val, ast.Name):
                    val = cls._find_variable_in_body(body, val.id)

                if isinstance(val, ast.List):
                    extras_require[key.s] = [e.s for e in val.elts]
                else:
                    raise Unparsable()
        else:
            raise Unparsable()

        return extras_require

    @classmethod
    def _find_single_string(
        cls, call: ast.Call, body: "List[Any]", name: str
    ) -> "Optional[str]":
        value = cls._find_in_call(call, name)
        if value is None:
            # Trying to find in kwargs
            kwargs = cls._find_call_kwargs(call)
            if kwargs is None:
                return None

            if not isinstance(kwargs, ast.Name):
                raise Unparsable()

            variable = cls._find_variable_in_body(body, kwargs.id)
            if not isinstance(variable, (ast.Dict, ast.Call)):
                raise Unparsable()

            if isinstance(variable, ast.Call):
                if not isinstance(variable.func, ast.Name):
                    raise Unparsable()

                if variable.func.id != "dict":
                    raise Unparsable()

                value = cls._find_in_call(variable, name)
            else:
                value = cls._find_in_dict(variable, name)

        if value is None:
            return None

        if isinstance(value, ast.Str):
            return value.s
        elif isinstance(value, ast.Name):
            variable = cls._find_variable_in_body(body, value.id)

            if variable is not None and isinstance(variable, ast.Str):
                return variable.s

        raise Unparsable()

    @staticmethod
    def _find_in_call(call: ast.Call, name: str) -> "Optional[Any]":
        for keyword in call.keywords:
            if keyword.arg == name:
                return keyword.value
        return None

    @staticmethod
    def _find_call_kwargs(call: ast.Call) -> "Optional[Any]":
        kwargs = None
        for keyword in call.keywords:
            if keyword.arg is None:
                kwargs = keyword.value

        return kwargs

    @staticmethod
    def _find_variable_in_body(body: "Iterable[Any]", name: str) -> "Optional[Any]":
        for elem in body:

            if not isinstance(elem, (ast.Assign, ast.AnnAssign)):
                continue

            if isinstance(elem, ast.AnnAssign):
                if not isinstance(elem.target, ast.Name):
                    continue
                if elem.value and elem.target.id == name:
                    return elem.value
            else:
                for target in elem.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == name:
                        return elem.value
        return None

    @staticmethod
    def _find_in_dict(dict_: ast.Dict, name: str) -> "Optional[Any]":
        for key, val in zip(dict_.keys, dict_.values):
            if isinstance(key, ast.Str) and key.s == name:
                return val
        return None


def setuptools_parse_setup_cfg(path):
    try:
        # v61.0.0 of setuptools deprecated setuptools.config.read_configuration
        from setuptools.config.setupcfg import read_configuration
    except ImportError:
        from setuptools.config import read_configuration

    parsed = read_configuration(path)
    results = parsed.get("metadata", {})
    results.update(parsed.get("options", {}))
    if "install_requires" in results:
        results["install_requires"] = make_base_requirements(
            results.get("install_requires", [])
        )
    if "extras_require" in results:
        extras = {}
        for extras_section, extras_reqs in results.get("extras_require", {}).items():
            new_reqs = tuple(make_base_requirements(extras_reqs))
            if new_reqs:
                extras[extras_section] = new_reqs
        results["extras_require"] = extras
    if "setup_requires" in results:
        results["setup_requires"] = make_base_requirements(
            results.get("setup_requires", [])
        )
    return results


def parse_setup_cfg(path: str) -> "Dict[str, Any]":
    return SetupReader.read_setup_cfg(Path(path))


def build_pep517(source_dir, build_dir, config_settings=None, dist_type="wheel"):
    if config_settings is None:
        config_settings = {}
    requires, backend = get_pyproject(source_dir)
    hookcaller = HookCaller(source_dir, backend)
    if dist_type == "sdist":
        get_requires_fn = hookcaller.get_requires_for_build_sdist
        build_fn = hookcaller.build_sdist
    else:
        get_requires_fn = hookcaller.get_requires_for_build_wheel
        build_fn = hookcaller.build_wheel

    with BuildEnv() as env:
        env.pip_install(requires)
        reqs = get_requires_fn(config_settings)
        env.pip_install(reqs)
        return build_fn(build_dir, config_settings)


def _get_src_dir(root):
    # type: (AnyStr) -> AnyStr
    src = os.environ.get("PIP_SRC")
    if src:
        return src
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env is not None:
        return os.path.join(virtual_env, "src")
    if root is not None:
        # Intentionally don't match pip's behavior here -- this is a temporary copy
        src_dir = create_tracked_tempdir(prefix="requirementslib-", suffix="-src")
    else:
        src_dir = os.path.join(root, "src")

    os.makedirs(src_dir, mode=0o775)
    return src_dir


@lru_cache()
def ensure_reqs(reqs):
    # type: (List[Union[Requirement]]) -> List[Requirement]

    if not isinstance(reqs, Iterable):
        raise TypeError("Expecting an Iterable, got %r" % reqs)
    new_reqs = []
    for req in reqs:
        if not req:
            continue
        if isinstance(req, str):
            req = Requirement.parse("{0}".format(str(req)))
        # req = strip_extras_markers_from_requirement(req)
        new_reqs.append(req)
    return new_reqs


def any_valid_values(data: "Dict[str, Any]", fields: "Iterable[str]") -> bool:
    def is_valid(value: "Any") -> bool:
        if isinstance(value, (list, tuple)):
            return all(map(is_valid, value))
        elif isinstance(value, dict):
            return all(map(is_valid, value.values()))
        return isinstance(value, str)

    fields = [field for field in fields if field in data]
    return fields and all(is_valid(data[field]) for field in fields)


def _prepare_wheel_building_kwargs(
    ireq=None,  # type: Optional[InstallRequirement]
    src_root=None,  # type: Optional[str]
    src_dir=None,  # type: Optional[str]
    editable=False,  # type: bool
):
    # type: (...) -> Dict[str, str]
    download_dir = os.path.join(CACHE_DIR, "pkgs")  # type: str
    os.makedirs(download_dir, exist_ok=True)

    wheel_download_dir = os.path.join(CACHE_DIR, "wheels")  # type: str
    os.makedirs(wheel_download_dir, exist_ok=True)
    if src_dir is None:
        if editable and src_root is not None:
            src_dir = src_root
        elif src_root is not None:
            src_dir = _get_src_dir(root=src_root)  # type: str
        else:
            src_dir = create_tracked_tempdir(prefix="reqlib-src")

    # Let's always resolve in isolation
    if src_dir is None:
        src_dir = create_tracked_tempdir(prefix="reqlib-src")
    build_dir = create_tracked_tempdir(prefix="reqlib-build")

    return {
        "build_dir": build_dir,
        "src_dir": src_dir,
        "download_dir": download_dir,
        "wheel_download_dir": wheel_download_dir,
    }


class ScandirCloser(object):
    def __init__(self, path):
        self.iterator = scandir(path)

    def __next__(self):
        return next(iter(self.iterator))

    def __iter__(self):
        return self

    def next(self):
        return self.__next__()

    def close(self):
        if getattr(self.iterator, "close", None):
            self.iterator.close()
        else:
            pass


def _is_venv_dir(path):
    # type: (AnyStr) -> bool
    if os.name == "nt":
        return os.path.isfile(os.path.join(path, "Scripts/python.exe")) or os.path.isfile(
            os.path.join(path, "Scripts/activate")
        )
    else:
        return os.path.isfile(os.path.join(path, "bin/python")) or os.path.isfile(
            os.path.join(path, "bin/activate")
        )


def iter_metadata(path, pkg_name=None, metadata_type="egg-info") -> Generator:
    if pkg_name is not None:
        pkg_variants = get_name_variants(pkg_name)
    dirs_to_search = [path]
    while dirs_to_search:
        p = dirs_to_search.pop(0)
        # Skip when the directory is like a venv
        if _is_venv_dir(p):
            continue
        with contextlib.closing(ScandirCloser(p)) as path_iterator:
            for entry in path_iterator:
                if entry.is_dir():
                    entry_name, ext = os.path.splitext(entry.name)
                    if ext.endswith(metadata_type):
                        if pkg_name is None or entry_name.lower() in pkg_variants:
                            yield entry
                    elif not entry.name.endswith(metadata_type):
                        dirs_to_search.append(entry.path)


def find_egginfo(target, pkg_name=None):
    # type: (AnyStr, Optional[AnyStr]) -> Generator
    egg_dirs = (
        egg_dir
        for egg_dir in iter_metadata(target, pkg_name=pkg_name)
        if egg_dir is not None
    )
    if pkg_name:
        yield next(iter(eggdir for eggdir in egg_dirs if eggdir is not None), None)
    else:
        for egg_dir in egg_dirs:
            yield egg_dir


def find_distinfo(target, pkg_name=None):
    # type: (AnyStr, Optional[AnyStr]) -> Generator
    dist_dirs = (
        dist_dir
        for dist_dir in iter_metadata(
            target, pkg_name=pkg_name, metadata_type="dist-info"
        )
        if dist_dir is not None
    )
    if pkg_name:
        yield next(iter(dist for dist in dist_dirs if dist is not None), None)
    else:
        for dist_dir in dist_dirs:
            yield dist_dir


def get_distinfo_dist(path, pkg_name=None) -> Optional[DistInfoDistribution]:
    dist_dir = next(iter(find_distinfo(path, pkg_name=pkg_name)), None)
    if dist_dir is not None:
        metadata_dir = dist_dir.path
        base_dir = os.path.dirname(metadata_dir)
        dist = next(iter(find_distributions(base_dir)), None)
        if dist is not None:
            return dist
    return None


def get_egginfo_dist(path, pkg_name=None) -> Optional[EggInfoDistribution]:
    egg_dir = next(iter(find_egginfo(path, pkg_name=pkg_name)), None)
    if egg_dir is not None:
        metadata_dir = egg_dir.path
        base_dir = os.path.dirname(metadata_dir)
        path_metadata = PathMetadata(base_dir, metadata_dir)
        dist_iter = distributions_from_metadata(path_metadata.egg_info)
        dist = next(iter(dist_iter), None)
        if dist is not None:
            return dist
    return None


def get_metadata(path, pkg_name=None, metadata_type=None):
    wheel_allowed = metadata_type == "wheel" or metadata_type is None
    egg_allowed = metadata_type == "egg" or metadata_type is None
    dist = None  # type: Optional[Union[DistInfoDistribution, EggInfoDistribution]]
    if wheel_allowed:
        dist = get_distinfo_dist(path, pkg_name=pkg_name)
    if egg_allowed and dist is None:
        dist = get_egginfo_dist(path, pkg_name=pkg_name)
    if dist is not None:
        return get_metadata_from_dist(dist)
    return {}


def get_extra_name_from_marker(marker):
    if not marker:
        raise ValueError("Invalid value for marker: {0!r}".format(marker))
    if not getattr(marker, "_markers", None):
        raise TypeError("Expecting a marker instance, received {0!r}".format(marker))
    for elem in marker._markers:
        if isinstance(elem, tuple) and elem[0].value == "extra":
            return elem[2].value
    return None


def get_metadata_from_wheel(wheel_path) -> Dict[Any, Any]:
    if not isinstance(wheel_path, str):
        raise TypeError("Expected string instance, received {0!r}".format(wheel_path))
    try:
        dist = Wheel(wheel_path)
    except Exception:
        pass
    metadata = dist.metadata
    name = metadata.name
    version = metadata.version
    requires = []
    extras_keys = getattr(metadata, "extras", [])  # type: List[str]
    extras = {k: [] for k in extras_keys}  # type: Dict[str, List[PackagingRequirement]]
    for req in getattr(metadata, "run_requires", []):
        parsed_req = init_requirement(req)
        parsed_marker = parsed_req.marker
        if parsed_marker:
            extra = get_extra_name_from_marker(parsed_marker)
            if extra is None:
                requires.append(parsed_req)
                continue
            if extra not in extras:
                extras[extra] = []
            parsed_req = strip_extras_markers_from_requirement(parsed_req)
            extras[extra].append(parsed_req)
        else:
            requires.append(parsed_req)
    return {"name": name, "version": version, "requires": requires, "extras": extras}


def get_metadata_from_dist(dist):
    try:
        requires = dist.requires()
    except Exception:
        requires = []
    try:
        dep_map = dist._build_dep_map()
    except Exception:
        dep_map = {}
    deps = []  # type: List[Requirement]
    extras = {}
    for k in dep_map.keys():
        if k is None:
            deps.extend(dep_map.get(k))
            continue
        else:
            extra = None
            _deps = dep_map.get(k)
            if k.startswith(":python_version"):
                marker = k.replace(":", "; ")
            else:
                if ":python_version" in k:
                    extra, _, marker = k.partition(":")
                    marker = "; {0}".format(marker)
                else:
                    marker = ""
                    extra = "{0}".format(k)
            _deps = ensure_reqs(
                tuple(["{0}{1}".format(str(req), marker) for req in _deps])
            )
            if extra:
                extras[extra] = _deps
            else:
                deps.extend(_deps)
    requires.extend(deps)
    return {
        "name": dist.project_name,
        "version": dist.version,
        "requires": requires,
        "extras": extras,
    }


def ast_parse_setup_py(path: str, raising: bool = True) -> "Dict[str, Any]":
    return SetupReader.read_setup_py(Path(path), raising)


def run_setup(script_path, egg_base=None):
    """Run a `setup.py` script with a target **egg_base** if provided.

    :param script_path: The path to the `setup.py` script to run
    :param Optional egg_base: The metadata directory to build in
    :raises FileNotFoundError: If the provided `script_path` does not exist
    :return: The metadata dictionary
    :rtype: Dict[Any, Any]
    """

    if not os.path.exists(script_path):
        raise FileNotFoundError(script_path)
    target_cwd = os.path.dirname(os.path.abspath(script_path))
    if egg_base is None:
        egg_base = os.path.join(target_cwd, "reqlib-metadata")
    with temp_path(), cd(target_cwd):
        # This is for you, Hynek
        # see https://github.com/hynek/environ_config/blob/69b1c8a/setup.py
        args = ["egg_info"]
        if egg_base:
            args += ["--egg-base", egg_base]
        script_name = os.path.basename(script_path)
        g = {"__file__": script_name, "__name__": "__main__"}
        sys.path.insert(0, target_cwd)

        save_argv = sys.argv.copy()
        try:
            global _setup_distribution, _setup_stop_after
            _setup_stop_after = "run"
            sys.argv[0] = script_name
            sys.argv[1:] = args
            with open(script_name, "rb") as f:
                contents = f.read().replace(rb"\r\n", rb"\n")
                exec(contents, g)
        # We couldn't import everything needed to run setup
        except Exception:
            python = os.environ.get("PIP_PYTHON_PATH", sys.executable)

            sp.run(
                [python, "setup.py"] + args,
                cwd=target_cwd,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
            )
        finally:
            _setup_stop_after = None
            sys.argv = save_argv
            _setup_distribution = get_metadata(egg_base, metadata_type="egg")
        dist = _setup_distribution
    return dist


class BaseRequirement(ReqLibBaseModel):
    name: str = ""
    requirement: Optional[HashableRequirement] = None

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        keep_untouched = (cached_property,)

    def __setattr__(self, name, value):
        if name == "requirement" and isinstance(value, Requirement):
            value = convert_to_hashable_requirement(value)
        super().__setattr__(name, value)

    def __str__(self) -> str:
        return "{0}".format(str(self.requirement))

    def __hash__(self):
        return hash((self.name, str(self.requirement)))

    def as_dict(self) -> Dict[str, Optional[Requirement]]:
        return {self.name: self.requirement}

    def as_tuple(self) -> Tuple[str, Optional[Requirement]]:
        return (self.name, self.requirement)

    @classmethod
    @lru_cache()
    def from_string(cls, line: str) -> "HashableRequirement":
        line = line.strip()
        req = init_requirement(line)
        return cls.from_req(req)

    @classmethod
    @lru_cache()
    def from_req(cls, req: Requirement) -> "HashableRequirement":
        name = None
        key = getattr(req, "key", None)
        name = getattr(req, "name", None)
        project_name = getattr(req, "project_name", None)
        if key is not None:
            name = key
        if name is None:
            name = project_name
        hashable_req = convert_to_hashable_requirement(req)
        return cls(name=name, requirement=hashable_req)


class SetupInfo(ReqLibBaseModel):
    name: Optional[str] = None
    base_dir: Optional[str] = None
    _version: Optional[str] = None
    _requirements: Optional[Tuple] = None
    build_requires: Optional[Tuple] = None
    build_backend: Optional[str] = None
    setup_requires: Optional[Tuple] = None
    python_requires: Optional[SpecifierSet] = None
    _extras_requirements: Optional[Tuple] = None
    setup_cfg: Optional[Path] = None
    setup_py: Optional[Path] = None
    pyproject: Optional[Path] = None
    ireq: Optional[InstallRequirement] = None
    extra_kwargs: Optional[Dict] = Field(default_factory=dict)
    metadata: Optional[Tuple[str]] = None
    _is_built: bool = False
    _ran_setup: bool = False

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        keep_untouched = (cached_property,)

    def __init__(self, **data):
        super().__init__(**data)
        self._is_built = False
        self._ran_setup = False
        if not self.build_backend:
            self.build_backend = "setuptools.build_meta:__legacy__"
        if self._requirements is None:
            self._requirements = ()
        self.get_initial_info()
        self.get_info()

    def __hash__(self):
        return hash(
            (
                self.name,
                self._version,
                self._requirements,
                self.build_requires,
                self.build_backend,
                self.setup_requires,
                self.python_requires,
                self._extras_requirements,
                self.setup_cfg,
                self.setup_py,
                self.pyproject,
                self.ireq,
            )
        )

    def __eq__(self, other):
        if not isinstance(other, SetupInfo):
            return NotImplemented
        return (
            self.name == other.name
            and self._version == other._version
            and self._requirements == other._requirements
            and self.build_requires == other.build_requires
        )

    @cached_property
    def requires(self) -> Dict[str, HashableRequirement]:
        if self._requirements is None:
            self._requirements = ()
        return {req.name: req.requirement for req in self._requirements}

    @cached_property
    def extras(self) -> Dict[str, Optional[Any]]:
        if self._extras_requirements is None:
            self._extras_requirements = ()
        extras_dict = {}
        extras = set(self._extras_requirements)
        for section, deps in extras:
            if isinstance(deps, BaseRequirement):
                extras_dict[section] = deps.requirement
            elif isinstance(deps, (list, tuple)):
                extras_dict[section] = [d.requirement for d in deps]
        return extras_dict

    @property
    def version(self) -> Optional[str]:
        if not self._version:
            info = self.as_dict()
            self._version = info.get("version", None)
        return self._version

    @property
    def egg_base(self) -> str:
        base = None  # type: Optional[str]
        if self.setup_py.exists():
            base = self.setup_py.parent
        elif self.pyproject.exists():
            base = self.pyproject.parent
        elif self.setup_cfg.exists():
            base = self.setup_cfg.parent
        if base is None:
            base = Path(self.base_dir)
        if base is None:
            base = Path(self.extra_kwargs["src_dir"])
        egg_base = base.joinpath("reqlib-metadata")
        if not egg_base.exists():
            atexit.register(rmtree, egg_base.as_posix())
        egg_base.mkdir(parents=True, exist_ok=True)
        return egg_base.as_posix()

    def update_from_dict(self, metadata: Dict[str, Any]) -> None:
        name = metadata.get("name", self.name)
        if isinstance(name, str):
            self.name = self.name if self.name else name
        version = metadata.get("version", None)
        if version:
            try:
                parse(version)
            except TypeError:
                version = self.version if self.version else None
            else:
                version = version
        if version:
            self._version = version
        build_requires = metadata.get("build_requires", [])
        if self.build_requires is None:
            self.build_requires = ()
        self.build_requires = tuple(set(self.build_requires) | set(build_requires))
        self._requirements = () if self._requirements is None else self._requirements
        requirements = self._requirements
        install_requires = make_base_requirements(metadata.get("install_requires", []))
        requirements += install_requires
        setup_requires = make_base_requirements(metadata.get("setup_requires", []))
        if self.setup_requires is None:
            self.setup_requires = ()
        self.setup_requires = tuple(self.setup_requires + setup_requires)
        requirements += self.setup_requires
        self.python_requires = metadata.get("python_requires", self.python_requires)
        extras_require = metadata.get("extras_require", {})
        extras_tuples = []
        if self._extras_requirements is None:
            self._extras_requirements = ()
        for section in set(extras_require) - {v[0] for v in self._extras_requirements}:
            extras = extras_require[section]
            extras_set = make_base_requirements(extras)
            if self.ireq and self.ireq.extras and section in self.ireq.extras:
                requirements += extras_set
            extras_tuples.append((section, tuple(extras_set)))
        self._extras_requirements += tuple(extras_tuples)
        self.build_backend = metadata.get(
            "build_backend", "setuptools.build_meta:__legacy__"
        )
        self._requirements = requirements

    def get_extras_from_ireq(self) -> None:
        if self.ireq and self.ireq.extras:
            for extra in self.ireq.extras:
                if extra in self.extras:
                    extras = make_base_requirements(self.extras[extra])
                    self._requirements = self._requirements + extras
                else:
                    extras = tuple(make_base_requirements(extra))
                    self._extras_requirements += (extra, extras)

    def parse_setup_cfg(self) -> Dict[str, Any]:
        if self.setup_cfg is not None and self.setup_cfg.exists():
            try:
                parsed = setuptools_parse_setup_cfg(self.setup_cfg.as_posix())
            except Exception:
                parsed = parse_setup_cfg(self.setup_cfg.as_posix())
            if not parsed:
                return {}
            return parsed
        return {}

    def parse_setup_py(self) -> Dict[str, Any]:
        if self.setup_py is not None and self.setup_py.exists():
            parsed = ast_parse_setup_py(self.setup_py.as_posix())
            if not parsed:
                return {}
            return parsed
        return {}

    def run_setup(self) -> None:
        if not self._ran_setup and self.setup_py is not None and self.setup_py.exists():
            dist = run_setup(self.setup_py.as_posix(), egg_base=self.egg_base)
            target_cwd = self.setup_py.parent.as_posix()
            with temp_path(), cd(target_cwd):
                if not dist:
                    metadata = self.get_egg_metadata()
                    if metadata:
                        self.populate_metadata(metadata)
                elif isinstance(dist, Mapping):
                    self.populate_metadata(dist)
                self._ran_setup = True

    @property
    def pep517_config(self) -> Dict[str, Any]:
        config = {}
        config.setdefault("--global-option", [])
        return config

    def build_wheel(self) -> str:
        need_delete = False
        if not self.pyproject.exists():
            if not self.build_requires:
                build_requires = '"setuptools", "wheel"'
            else:
                build_requires = ", ".join(
                    ['"{0}"'.format(r) for r in self.build_requires]
                )
            self.pyproject.write_text(
                str(
                    """
[build-system]
requires = [{0}]
build-backend = "{1}"
                """.format(
                        build_requires, self.build_backend
                    ).strip()
                )
            )
            need_delete = True
        directory = self.base_dir
        if self.ireq and self.ireq.link:
            parsed = urlparse(str(self.ireq.link))
            subdir = parse_qs(parsed.fragment).get("subdirectory", [])
            if subdir:
                directory = f"{self.base_dir}/{subdir[0]}"
        result = build_pep517(
            directory,
            self.extra_kwargs["build_dir"],
            config_settings=self.pep517_config,
            dist_type="wheel",
        )
        if need_delete:
            self.pyproject.unlink()
        return result

    # noinspection PyPackageRequirements
    def build_sdist(self) -> str:
        need_delete = False
        if not self.pyproject.exists():
            if not self.build_requires:
                build_requires = '"setuptools", "wheel"'
            else:
                build_requires = ", ".join(
                    ['"{0}"'.format(r) for r in self.build_requires]
                )
            self.pyproject.write_text(
                str(
                    """
[build-system]
requires = [{0}]
build-backend = "{1}"
                """.format(
                        build_requires, self.build_backend
                    ).strip()
                )
            )
            need_delete = True
        result = build_pep517(
            self.base_dir,
            self.extra_kwargs["build_dir"],
            config_settings=self.pep517_config,
            dist_type="sdist",
        )
        if need_delete:
            self.pyproject.unlink()
        return result

    def build(self) -> None:
        if self._is_built:
            return
        metadata = None
        try:
            dist_path = self.build_wheel()
            metadata = self.get_metadata_from_wheel(
                os.path.join(self.extra_kwargs["build_dir"], dist_path)
            )
        except Exception:
            try:
                dist_path = self.build_sdist()
                metadata = self.get_egg_metadata(metadata_type="egg")
                if metadata:
                    self.populate_metadata(metadata)
            except Exception:
                pass
        if metadata:
            self.populate_metadata(metadata)
        if not self.metadata or not self.name:
            metadata = self.get_egg_metadata()
            if metadata:
                self.populate_metadata(metadata)
        if not self.metadata or not self.name:
            self.run_setup()
        self._is_built = True

    def get_metadata_from_wheel(self, wheel_path) -> Dict[Any, Any]:
        """Given a path to a wheel, return the metadata from that wheel.

        :return: A dictionary of metadata from the provided wheel
        :rtype: Dict[Any, Any]
        """

        metadata_dict = get_metadata_from_wheel(wheel_path)
        return metadata_dict

    def get_egg_metadata(self, metadata_dir=None, metadata_type=None) -> Dict[Any, Any]:
        """Given a metadata directory, return the corresponding metadata
        dictionary.

        :param Optional[str] metadata_dir: Root metadata path, default: `os.getcwd()`
        :param Optional[str] metadata_type: Type of metadata to search for, default None
        :return: A metadata dictionary built from the metadata in the given location
        """

        package_indicators = [self.pyproject, self.setup_py, self.setup_cfg]
        metadata_dirs = []  # type: List[str]
        if any([fn is not None and fn.exists() for fn in package_indicators]):
            metadata_dirs = [
                self.extra_kwargs["build_dir"],
                self.egg_base,
                self.extra_kwargs["src_dir"],
            ]
        if metadata_dir is not None:
            metadata_dirs = [metadata_dir] + metadata_dirs
        metadata = [
            get_metadata(d, pkg_name=self.name, metadata_type=metadata_type)
            for d in metadata_dirs
            if os.path.exists(d)
        ]
        metadata = next(iter(d for d in metadata if d), None)
        return metadata

    def populate_metadata(self, metadata) -> "SetupInfo":
        """Populates the metadata dictionary from the supplied metadata."""

        _metadata = ()
        for k, v in metadata.items():
            if k == "extras" and isinstance(v, dict):
                extras = ()
                for extra, reqs in v.items():
                    extras += ((extra, tuple(reqs)),)
                _metadata += extras
            elif isinstance(v, (list, tuple)):
                _metadata += (k, tuple(v))
            else:
                _metadata += (k, v)
        self.metadata = _metadata
        self.setup_requires = make_base_requirements(metadata.get("requires", ()))
        self._requirements += tuple(self.setup_requires)
        name = metadata.get("name")
        if name:
            self.name = name
        version = metadata.get("version")
        if version:
            self._version = version
        extras_require = metadata.get("extras", ())
        extras_tuples = []
        for section in set(extras_require):
            extras = extras_require[section]
            extras_set = make_base_requirements(extras)
            if self.ireq and self.ireq.extras and section in self.ireq.extras:
                self._requirements += extras_set
            extras_tuples.append((section, tuple(extras_set)))
        return self

    def run_pyproject(self) -> "SetupInfo":
        """Populates the **pyproject.toml** metadata if available."""
        if self.pyproject and self.pyproject.exists():
            result = get_pyproject(self.pyproject.parent)
            if result is not None:
                requires, backend = result
                if self.build_requires is None:
                    self.build_requires = ()
                if backend:
                    self.build_backend = backend
                else:
                    self.build_backend = get_default_pyproject_backend()
                if requires:
                    self.build_requires = tuple(set(requires) | set(self.build_requires))
                else:
                    self.build_requires = ("setuptools", "wheel")
        return self

    def get_initial_info(self) -> Dict[str, Any]:
        parse_setupcfg = False
        parse_setuppy = False
        self.run_pyproject()
        self.run_setup()
        if self.setup_cfg and self.setup_cfg.exists():
            parse_setupcfg = True
        if self.setup_py and self.setup_py.exists():
            parse_setuppy = True
        if (
            self.build_backend.startswith("setuptools")
            and parse_setuppy
            or parse_setupcfg
        ):
            parsed = {}
            try:
                with cd(self.base_dir):
                    if parse_setuppy:
                        parsed.update(self.parse_setup_py())
                    if parse_setupcfg:
                        parsed.update(self.parse_setup_cfg())
            except Unparsable:
                pass
            else:
                self.update_from_dict(parsed)
                return self.as_dict()

        return self.as_dict()

    def get_info(self) -> None:
        if self.metadata is None:
            self.build()

        if self.setup_py and self.setup_py.exists():
            try:
                self.run_setup()
            except Exception:
                metadata = self.get_egg_metadata()
                if metadata:
                    self.populate_metadata(metadata)
            if self.metadata is None or not self.name:
                metadata = self.get_egg_metadata()
                if metadata:
                    self.populate_metadata(metadata)

    def as_dict(self) -> Dict[str, Any]:
        prop_dict = {
            "name": self.name,
            "version": self.version if self._version else None,
            "base_dir": self.base_dir,
            "ireq": self.ireq,
            "build_backend": self.build_backend,
            "build_requires": self.build_requires,
            "requires": self.requires,
            "setup_requires": self.setup_requires,
            "python_requires": self.python_requires,
            "extras": self.extras,
            "extra_kwargs": self.extra_kwargs,
            "setup_cfg": self.setup_cfg,
            "setup_py": self.setup_py,
            "pyproject": self.pyproject,
        }
        return {k: v for k, v in prop_dict.items() if v}

    @classmethod
    def from_requirement(cls, requirement, finder=None) -> Optional["SetupInfo"]:
        ireq = requirement.ireq
        subdir = getattr(requirement.req, "subdirectory", None)
        return cls.from_ireq(ireq, subdir=subdir, finder=finder)

    @classmethod
    def from_ireq(
        cls, ireq, subdir=None, finder=None, session=None
    ) -> Optional["SetupInfo"]:
        if not ireq:
            return None
        if not ireq.link:
            return None
        if ireq.link.is_wheel:
            return None
        stack = ExitStack()
        if not session:
            cmd = get_pip_command()
            options, _ = cmd.parser.parse_args([])
            session = cmd._build_session(options)
        stack.enter_context(global_tempdir_manager())
        vcs, uri = split_vcs_method_from_uri(ireq.link.url_without_fragment)
        parsed = urlparse(uri)
        if "file" in parsed.scheme:
            url_path = parsed.path
            if "@" in url_path:
                url_path, _, _ = url_path.rpartition("@")
            parsed = parsed._replace(path=url_path)
            uri = urlunparse(parsed)
        is_file = False
        if ireq.link.scheme == "file" or uri.startswith("file://"):
            is_file = True
        kwargs = _prepare_wheel_building_kwargs(ireq)
        is_artifact_or_vcs = getattr(
            ireq.link, "is_vcs", getattr(ireq.link, "is_artifact", False)
        )
        is_vcs = True if vcs else is_artifact_or_vcs
        download_dir = None
        if not (ireq.editable and is_file and is_vcs):
            if ireq.is_wheel:
                download_dir = kwargs["wheel_download_dir"]
            else:
                download_dir = kwargs["download_dir"]
        # this ensures the build dir is treated as the temporary build location
        # and the source dir is treated as permanent / not deleted by pip
        build_location_func = getattr(ireq, "build_location", None)
        if build_location_func is None:
            build_location_func = getattr(ireq, "ensure_build_location", None)
        if not ireq.source_dir:
            if subdir:
                directory = f"{kwargs['build_dir']}/{subdir}"
            else:
                directory = kwargs["build_dir"]
            build_kwargs = {
                "build_dir": directory,
                "autodelete": False,
                "parallel_builds": True,
            }
            build_location_func(**build_kwargs)
            ireq.ensure_has_source_dir(kwargs["src_dir"])
            location = None
            if ireq.source_dir:
                location = ireq.source_dir

            if ireq.link.is_existing_dir():
                if os.path.isdir(location):
                    rmtree(location)
                _copy_source_tree(ireq.link.file_path, location)
            else:
                unpack_url(
                    link=ireq.link,
                    location=location,
                    download=Downloader(session, "off"),
                    verbosity=1,
                    download_dir=download_dir,
                    hashes=ireq.hashes(True),
                )
        created = cls.create(
            ireq.source_dir,
            subdirectory=subdir,
            ireq=ireq,
            kwargs=kwargs,
        )
        return created

    @classmethod
    def create(
        cls,
        base_dir: str,
        subdirectory: Optional[str] = None,
        ireq: Optional[InstallRequirement] = None,
        kwargs: Optional[Dict[str, str]] = None,
    ) -> Optional["SetupInfo"]:
        if not base_dir or base_dir is None:
            return None

        creation_kwargs = {"extra_kwargs": kwargs}
        if not isinstance(base_dir, Path):
            base_dir = Path(base_dir)
        creation_kwargs["base_dir"] = base_dir.as_posix()
        pyproject = base_dir.joinpath("pyproject.toml")

        if subdirectory is not None:
            base_dir = base_dir.joinpath(subdirectory)
        setup_py = base_dir.joinpath("setup.py")
        setup_cfg = base_dir.joinpath("setup.cfg")
        creation_kwargs["pyproject"] = pyproject
        creation_kwargs["setup_py"] = setup_py
        creation_kwargs["setup_cfg"] = setup_cfg
        if ireq:
            creation_kwargs["ireq"] = ireq
        created = cls(**creation_kwargs)
        created.get_initial_info()
        return created
