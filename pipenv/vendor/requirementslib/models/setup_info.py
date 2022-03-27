# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import ast
import atexit
import configparser
import contextlib
import importlib
import operator
import os
import shutil
import sys
from collections.abc import Iterable, Mapping
from functools import lru_cache, partial
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse
from weakref import finalize

import pipenv.vendor.attr as attr
import packaging.specifiers
import packaging.utils
import packaging.version
import pep517.envbuild
import pep517.wrappers
from pipenv.vendor.distlib.wheel import Wheel
from pipenv.vendor.packaging.markers import Marker
from pipenv.vendor.pip_shims.utils import call_function_with_correct_args
from pipenv.vendor.platformdirs import user_cache_dir
from pipenv.vendor.vistir.contextmanagers import cd, temp_path
from pipenv.vendor.vistir.misc import run
from pipenv.vendor.vistir.path import create_tracked_tempdir, ensure_mkdir_p, mkdir_p, rmtree

from ..environment import MYPY_RUNNING
from ..exceptions import RequirementError
from .utils import (
    get_default_pyproject_backend,
    get_name_variants,
    get_pyproject,
    init_requirement,
    split_vcs_method_from_uri,
    strip_extras_markers_from_requirement,
)

try:
    import pkg_resources.extern.packaging.requirements as pkg_resources_requirements
except ModuleNotFoundError:
    pkg_resources_requirements = None

try:
    from setuptools.dist import Distribution, distutils
except ImportError:
    import distutils
    from distutils.core import Distribution

from contextlib import ExitStack
from os import scandir

if MYPY_RUNNING:
    from typing import (
        Any,
        AnyStr,
        Dict,
        Generator,
        List,
        Optional,
        Sequence,
        Set,
        Text,
        Tuple,
        TypeVar,
        Union,
    )

    import pipenv.vendor.requests as requests
    from pipenv.vendor.packaging.requirements import Requirement as PackagingRequirement
    from pipenv.vendor.pip_shims.shims import InstallRequirement, PackageFinder
    from pkg_resources import DistInfoDistribution, EggInfoDistribution, PathMetadata
    from pkg_resources import Requirement as PkgResourcesRequirement

    TRequirement = TypeVar("TRequirement")
    RequirementType = TypeVar(
        "RequirementType", covariant=True, bound=PackagingRequirement
    )
    MarkerType = TypeVar("MarkerType", covariant=True, bound=Marker)
    STRING_TYPE = Union[str, bytes, Text]
    S = TypeVar("S", bytes, str, Text)
    AST_SEQ = TypeVar("AST_SEQ", ast.Tuple, ast.List)


CACHE_DIR = os.environ.get("PIPENV_CACHE_DIR", user_cache_dir("pipenv"))

# The following are necessary for people who like to use "if __name__" conditionals
# in their setup.py scripts
_setup_stop_after = None
_setup_distribution = None


def pep517_subprocess_runner(cmd, cwd=None, extra_environ=None):
    # type: (List[AnyStr], Optional[AnyStr], Optional[Mapping[S, S]]) -> None
    """The default method of calling the wrapper subprocess."""
    env = os.environ.copy()
    if extra_environ:
        env.update(extra_environ)

    run(
        cmd,
        cwd=cwd,
        env=env,
        block=True,
        combine_stderr=True,
        return_object=False,
        write_to_stdout=False,
        nospin=True,
    )


class BuildEnv(pep517.envbuild.BuildEnvironment):
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
        run(
            cmd,
            block=True,
            combine_stderr=True,
            return_object=False,
            write_to_stdout=False,
            nospin=True,
        )


class HookCaller(pep517.wrappers.Pep517HookCaller):
    def __init__(self, source_dir, build_backend, backend_path=None):
        super().__init__(source_dir, build_backend, backend_path=backend_path)
        self.source_dir = os.path.abspath(source_dir)
        self.build_backend = build_backend
        self._subprocess_runner = pep517_subprocess_runner
        if backend_path:
            backend_path = [
                pep517.wrappers.norm_and_check(self.source_dir, p) for p in backend_path
            ]
        self.backend_path = backend_path


def make_base_requirements(reqs):
    # type: (Sequence[STRING_TYPE]) -> Set[BaseRequirement]
    requirements = set()
    if not isinstance(reqs, (list, tuple, set)):
        reqs = [reqs]
    for req in reqs:
        if isinstance(req, BaseRequirement):
            requirements.add(req)
        elif pkg_resources_requirements is not None and isinstance(
            req, pkg_resources_requirements.Requirement
        ):
            requirements.add(BaseRequirement.from_req(req))
        elif req and isinstance(req, str) and not req.startswith("#"):
            requirements.add(BaseRequirement.from_string(req))
    return requirements


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

        with file.open(encoding="utf-8") as f:
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

            if getattr(elem, "target", None) and elem.target.id == name:
                return elem.value

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


@contextlib.contextmanager
def _suppress_distutils_logs():
    # type: () -> Generator[None, None, None]
    """Hack to hide noise generated by `setup.py develop`.

    There isn't a good way to suppress them now, so let's monky-patch.
    See https://bugs.python.org/issue25392.
    """

    f = distutils.log.Log._log

    def _log(log, level, msg, args):
        if level >= distutils.log.ERROR:
            f(log, level, msg, args)

    distutils.log.Log._log = _log
    yield
    distutils.log.Log._log = f


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


@ensure_mkdir_p(mode=0o775)
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
    return src_dir


@lru_cache()
def ensure_reqs(reqs):
    # type: (List[Union[S, PkgResourcesRequirement]]) -> List[PkgResourcesRequirement]
    import pkg_resources

    if not isinstance(reqs, Iterable):
        raise TypeError("Expecting an Iterable, got %r" % reqs)
    new_reqs = []
    for req in reqs:
        if not req:
            continue
        if isinstance(req, str):
            req = pkg_resources.Requirement.parse("{0}".format(str(req)))
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
    src_root=None,  # type: Optional[STRING_TYPE]
    src_dir=None,  # type: Optional[STRING_TYPE]
    editable=False,  # type: bool
):
    # type: (...) -> Dict[STRING_TYPE, STRING_TYPE]
    download_dir = os.path.join(CACHE_DIR, "pkgs")  # type: STRING_TYPE
    mkdir_p(download_dir)

    wheel_download_dir = os.path.join(CACHE_DIR, "wheels")  # type: STRING_TYPE
    mkdir_p(wheel_download_dir)
    if src_dir is None:
        if editable and src_root is not None:
            src_dir = src_root
        elif src_root is not None:
            src_dir = _get_src_dir(root=src_root)  # type: STRING_TYPE
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


def iter_metadata(path, pkg_name=None, metadata_type="egg-info"):
    # type: (AnyStr, Optional[AnyStr], AnyStr) -> Generator
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


def get_distinfo_dist(path, pkg_name=None):
    # type: (S, Optional[S]) -> Optional[DistInfoDistribution]
    import pkg_resources

    dist_dir = next(iter(find_distinfo(path, pkg_name=pkg_name)), None)
    if dist_dir is not None:
        metadata_dir = dist_dir.path
        base_dir = os.path.dirname(metadata_dir)
        dist = next(iter(pkg_resources.find_distributions(base_dir)), None)
        if dist is not None:
            return dist
    return None


def get_egginfo_dist(path, pkg_name=None):
    # type: (S, Optional[S]) -> Optional[EggInfoDistribution]
    import pkg_resources

    egg_dir = next(iter(find_egginfo(path, pkg_name=pkg_name)), None)
    if egg_dir is not None:
        metadata_dir = egg_dir.path
        base_dir = os.path.dirname(metadata_dir)
        path_metadata = pkg_resources.PathMetadata(base_dir, metadata_dir)
        dist_iter = pkg_resources.distributions_from_metadata(path_metadata.egg_info)
        dist = next(iter(dist_iter), None)
        if dist is not None:
            return dist
    return None


def get_metadata(path, pkg_name=None, metadata_type=None):
    # type: (S, Optional[S], Optional[S]) -> Dict[S, Union[S, List[RequirementType], Dict[S, RequirementType]]]
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


@lru_cache()
def get_extra_name_from_marker(marker):
    # type: (MarkerType) -> Optional[S]
    if not marker:
        raise ValueError("Invalid value for marker: {0!r}".format(marker))
    if not getattr(marker, "_markers", None):
        raise TypeError("Expecting a marker instance, received {0!r}".format(marker))
    for elem in marker._markers:
        if isinstance(elem, tuple) and elem[0].value == "extra":
            return elem[2].value
    return None


def get_metadata_from_wheel(wheel_path):
    # type: (S) -> Dict[Any, Any]
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
    extras_keys = getattr(metadata, "extras", [])  # type: List[STRING_TYPE]
    extras = {
        k: [] for k in extras_keys
    }  # type: Dict[STRING_TYPE, List[RequirementType]]
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
    # type: (Union[PathMetadata, EggInfoDistribution, DistInfoDistribution]) -> Dict[S, Union[S, List[RequirementType], Dict[S, RequirementType]]]
    try:
        requires = dist.requires()
    except Exception:
        requires = []
    try:
        dep_map = dist._build_dep_map()
    except Exception:
        dep_map = {}
    deps = []  # type: List[PkgResourcesRequirement]
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
    # type: (str, Optional[str]) -> Distribution
    """Run a `setup.py` script with a target **egg_base** if provided.

    :param S script_path: The path to the `setup.py` script to run
    :param Optional[S] egg_base: The metadata directory to build in
    :raises FileNotFoundError: If the provided `script_path` does not exist
    :return: The metadata dictionary
    :rtype: Dict[Any, Any]
    """

    if not os.path.exists(script_path):
        raise FileNotFoundError(script_path)
    target_cwd = os.path.dirname(os.path.abspath(script_path))
    if egg_base is None:
        egg_base = os.path.join(target_cwd, "reqlib-metadata")
    with temp_path(), cd(target_cwd), _suppress_distutils_logs():
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
                contents = f.read().replace(br"\r\n", br"\n")
                exec(contents, g)
        # We couldn't import everything needed to run setup
        except Exception:
            python = os.environ.get("PIP_PYTHON_PATH", sys.executable)
            out, _ = run(
                [python, "setup.py"] + args,
                cwd=target_cwd,
                block=True,
                combine_stderr=False,
                return_object=False,
                nospin=True,
            )
        finally:
            _setup_stop_after = None
            sys.argv = save_argv
            _setup_distribution = get_metadata(egg_base, metadata_type="egg")
        dist = _setup_distribution
    return dist


@attr.s(slots=True, frozen=True)
class BaseRequirement(object):
    name = attr.ib(default="", eq=True, order=True)  # type: STRING_TYPE
    requirement = attr.ib(
        default=None, eq=True, order=True
    )  # type: Optional[PkgResourcesRequirement]

    def __str__(self):
        # type: () -> S
        return "{0}".format(str(self.requirement))

    def as_dict(self):
        # type: () -> Dict[STRING_TYPE, Optional[PkgResourcesRequirement]]
        return {self.name: self.requirement}

    def as_tuple(self):
        # type: () -> Tuple[STRING_TYPE, Optional[PkgResourcesRequirement]]
        return (self.name, self.requirement)

    @classmethod
    @lru_cache()
    def from_string(cls, line):
        # type: (S) -> BaseRequirement
        line = line.strip()
        req = init_requirement(line)
        return cls.from_req(req)

    @classmethod
    @lru_cache()
    def from_req(cls, req):
        # type: (PkgResourcesRequirement) -> BaseRequirement
        name = None
        key = getattr(req, "key", None)
        name = getattr(req, "name", None)
        project_name = getattr(req, "project_name", None)
        if key is not None:
            name = key
        if name is None:
            name = project_name
        return cls(name=name, requirement=req)


@attr.s(slots=True, frozen=True)
class Extra(object):
    name = attr.ib(default=None, eq=True, order=True)  # type: STRING_TYPE
    requirements = attr.ib(factory=frozenset, eq=True, order=True, type=frozenset)

    def __str__(self):
        # type: () -> S
        return "{0}: {{{1}}}".format(
            self.name, ", ".join([r.name for r in self.requirements])
        )

    def add(self, req):
        # type: (BaseRequirement) -> "Extra"
        if req not in self.requirements:
            current_set = set(self.requirements)
            current_set.add(req)
            return attr.evolve(self, requirements=frozenset(current_set))
        return self

    def as_dict(self):
        # type: () -> Dict[STRING_TYPE, Tuple[RequirementType, ...]]
        return {self.name: tuple([r.requirement for r in self.requirements])}


@attr.s(slots=True, eq=True, hash=True)
class SetupInfo(object):
    name = attr.ib(default=None, eq=True)  # type: STRING_TYPE
    base_dir = attr.ib(default=None, eq=True, hash=False)  # type: STRING_TYPE
    _version = attr.ib(default=None, eq=True)  # type: STRING_TYPE
    _requirements = attr.ib(
        type=frozenset, factory=frozenset, eq=True, hash=True
    )  # type: Optional[frozenset]
    build_requires = attr.ib(default=None, eq=True)  # type: Optional[Tuple]
    build_backend = attr.ib(eq=True)  # type: STRING_TYPE
    setup_requires = attr.ib(default=None, eq=True)  # type: Optional[Tuple]
    python_requires = attr.ib(
        default=None, eq=True
    )  # type: Optional[packaging.specifiers.SpecifierSet]
    _extras_requirements = attr.ib(default=None, eq=True)  # type: Optional[Tuple]
    setup_cfg = attr.ib(type=Path, default=None, eq=True, hash=False)
    setup_py = attr.ib(type=Path, default=None, eq=True, hash=False)
    pyproject = attr.ib(type=Path, default=None, eq=True, hash=False)
    ireq = attr.ib(
        default=None, eq=True, hash=False
    )  # type: Optional[InstallRequirement]
    extra_kwargs = attr.ib(default=attr.Factory(dict), type=dict, eq=False, hash=False)
    metadata = attr.ib(default=None)  # type: Optional[Tuple[STRING_TYPE]]
    stack = attr.ib(default=None, eq=False)  # type: Optional[ExitStack]
    _finalizer = attr.ib(default=None, eq=False)  # type: Any

    def __attrs_post_init__(self):
        self._finalizer = finalize(self, self.stack.close)

    @build_backend.default
    def get_build_backend(self):
        # type: () -> STRING_TYPE
        return get_default_pyproject_backend()

    @property
    def requires(self):
        # type: () -> Dict[S, RequirementType]
        if self._requirements is None:
            self._requirements = frozenset()
            self.get_info()
        return {req.name: req.requirement for req in self._requirements}

    @property
    def extras(self):
        # type: () -> Dict[S, Optional[Any]]
        if self._extras_requirements is None:
            self._extras_requirements = ()
            self.get_info()
        extras_dict = {}
        extras = set(self._extras_requirements)
        for section, deps in extras:
            if isinstance(deps, BaseRequirement):
                extras_dict[section] = deps.requirement
            elif isinstance(deps, (list, tuple)):
                extras_dict[section] = [d.requirement for d in deps]
        return extras_dict

    @property
    def version(self):
        # type: () -> Optional[str]
        if not self._version:
            info = self.get_info()
            self._version = info.get("version", None)
        return self._version

    @property
    def egg_base(self):
        # type: () -> S
        base = None  # type: Optional[STRING_TYPE]
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

    def update_from_dict(self, metadata):
        name = metadata.get("name", self.name)
        if isinstance(name, str):
            self.name = self.name if self.name else name
        version = metadata.get("version", None)
        if version:
            try:
                packaging.version.parse(version)
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
        self._requirements = (
            frozenset() if self._requirements is None else self._requirements
        )
        requirements = set(self._requirements)
        install_requires = make_base_requirements(metadata.get("install_requires", []))
        requirements |= install_requires
        setup_requires = make_base_requirements(metadata.get("setup_requires", []))
        if self.setup_requires is None:
            self.setup_requires = ()
        self.setup_requires = tuple(set(self.setup_requires) | setup_requires)
        if self.ireq.editable:
            requirements |= setup_requires
        # TODO: Should this be a specifierset?
        self.python_requires = metadata.get("python_requires", self.python_requires)
        extras_require = metadata.get("extras_require", {})
        extras_tuples = []
        if self._extras_requirements is None:
            self._extras_requirements = ()
        for section in set(extras_require) - {v[0] for v in self._extras_requirements}:
            extras = extras_require[section]
            extras_set = make_base_requirements(extras)
            if self.ireq and self.ireq.extras and section in self.ireq.extras:
                requirements |= extras_set
            extras_tuples.append((section, tuple(extras_set)))
        self._extras_requirements += tuple(extras_tuples)
        build_backend = metadata.get("build_backend", "setuptools.build_meta:__legacy__")
        if not self.build_backend:
            self.build_backend = build_backend
        self._requirements = frozenset(requirements)

    def get_extras_from_ireq(self):
        # type: () -> None
        if self.ireq and self.ireq.extras:
            for extra in self.ireq.extras:
                if extra in self.extras:
                    extras = make_base_requirements(self.extras[extra])
                    self._requirements = frozenset(set(self._requirements) | extras)
                else:
                    extras = tuple(make_base_requirements(extra))
                    self._extras_requirements += (extra, extras)

    def parse_setup_cfg(self):
        # type: () -> Dict[STRING_TYPE, Any]
        if self.setup_cfg is not None and self.setup_cfg.exists():
            try:
                parsed = setuptools_parse_setup_cfg(self.setup_cfg.as_posix())
            except Exception:
                parsed = parse_setup_cfg(self.setup_cfg.as_posix())
            if not parsed:
                return {}
            return parsed
        return {}

    def parse_setup_py(self):
        # type: () -> Dict[STRING_TYPE, Any]
        if self.setup_py is not None and self.setup_py.exists():
            parsed = ast_parse_setup_py(self.setup_py.as_posix())
            if not parsed:
                return {}
            return parsed
        return {}

    def run_setup(self):
        # type: () -> "SetupInfo"
        if self.setup_py is not None and self.setup_py.exists():
            dist = run_setup(self.setup_py.as_posix(), egg_base=self.egg_base)
            target_cwd = self.setup_py.parent.as_posix()
            with temp_path(), cd(target_cwd):
                if not dist:
                    metadata = self.get_egg_metadata()
                    if metadata:
                        return self.populate_metadata(metadata)

                if isinstance(dist, Mapping):
                    self.populate_metadata(dist)
                    return
                name = dist.get_name()
                if name:
                    self.name = name
                update_dict = {}
                if dist.python_requires:
                    update_dict["python_requires"] = dist.python_requires
                update_dict["extras_require"] = {}
                if dist.extras_require:
                    for extra, extra_requires in dist.extras_require:
                        extras_tuple = make_base_requirements(extra_requires)
                        update_dict["extras_require"][extra] = extras_tuple
                update_dict["install_requires"] = make_base_requirements(
                    dist.get_requires()
                )
                if dist.setup_requires:
                    update_dict["setup_requires"] = make_base_requirements(
                        dist.setup_requires
                    )
                version = dist.get_version()
                if version:
                    update_dict["version"] = version
                return self.update_from_dict(update_dict)

    @property
    def pep517_config(self):
        config = {}
        config.setdefault("--global-option", [])
        return config

    def build_wheel(self):
        # type: () -> S
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

        parsed = urlparse(str(self.ireq.link))
        subdir = parse_qs(parsed.fragment).get('subdirectory', [])
        if subdir:
            directory = f"{self.base_dir}/{subdir[0]}"
        else:
            directory = self.base_dir
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
    def build_sdist(self):
        # type: () -> S
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

    def build(self):
        # type: () -> "SetupInfo"
        dist_path = None
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
            return self.run_setup()
        return self

    def reload(self):
        # type: () -> Dict[S, Any]
        """Wipe existing distribution info metadata for rebuilding.

        Erases metadata from **self.egg_base** and unsets
        **self.requirements** and **self.extras**.
        """
        for metadata_dir in os.listdir(self.egg_base):
            shutil.rmtree(metadata_dir, ignore_errors=True)
        self.metadata = None
        self._requirements = frozenset()
        self._extras_requirements = ()
        self.get_info()

    def get_metadata_from_wheel(self, wheel_path):
        # type: (S) -> Dict[Any, Any]
        """Given a path to a wheel, return the metadata from that wheel.

        :return: A dictionary of metadata from the provided wheel
        :rtype: Dict[Any, Any]
        """

        metadata_dict = get_metadata_from_wheel(wheel_path)
        return metadata_dict

    def get_egg_metadata(self, metadata_dir=None, metadata_type=None):
        # type: (Optional[AnyStr], Optional[AnyStr]) -> Dict[Any, Any]
        """Given a metadata directory, return the corresponding metadata
        dictionary.

        :param Optional[str] metadata_dir: Root metadata path, default: `os.getcwd()`
        :param Optional[str] metadata_type: Type of metadata to search for, default None
        :return: A metadata dictionary built from the metadata in the given location
        :rtype: Dict[Any, Any]
        """

        package_indicators = [self.pyproject, self.setup_py, self.setup_cfg]
        metadata_dirs = []  # type: List[STRING_TYPE]
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

    def populate_metadata(self, metadata):
        # type: (Dict[Any, Any]) -> "SetupInfo"
        """Populates the metadata dictionary from the supplied metadata.

        :return: The current instance.
        :rtype: `SetupInfo`
        """

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
        cleaned = metadata.copy()
        cleaned.update(
            {
                "install_requires": metadata.get("requires", []),
                "extras_require": metadata.get("extras", {}),
            }
        )
        if cleaned:
            self.update_from_dict(cleaned.copy())
        else:
            self.update_from_dict(metadata)
        return self

    def run_pyproject(self):
        # type: () -> "SetupInfo"
        """Populates the **pyproject.toml** metadata if available.

        :return: The current instance
        :rtype: `SetupInfo`
        """
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

    def get_initial_info(self):
        # type: () -> Dict[S, Any]
        parse_setupcfg = False
        parse_setuppy = False
        self.run_pyproject()
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

        return self.get_info()

    def get_info(self):
        # type: () -> Dict[S, Any]
        if self.metadata is None:
            with cd(self.base_dir):
                self.build()

        if self.setup_py and self.setup_py.exists() and self.metadata is None:
            if not self.requires or not self.name:
                try:
                    with cd(self.base_dir):
                        self.run_setup()
                except Exception:
                    with cd(self.base_dir):
                        metadata = self.get_egg_metadata()
                        if metadata:
                            self.populate_metadata(metadata)
                if self.metadata is None or not self.name:
                    with cd(self.base_dir):
                        metadata = self.get_egg_metadata()
                        if metadata:
                            self.populate_metadata(metadata)

        return self.as_dict()

    def as_dict(self):
        # type: () -> Dict[STRING_TYPE, Any]
        prop_dict = {
            "name": self.name,
            "version": self.version if self._version else None,
            "base_dir": self.base_dir,
            "ireq": self.ireq,
            "build_backend": self.build_backend,
            "build_requires": self.build_requires,
            "requires": self.requires if self._requirements else None,
            "setup_requires": self.setup_requires,
            "python_requires": self.python_requires,
            "extras": self.extras if self._extras_requirements else None,
            "extra_kwargs": self.extra_kwargs,
            "setup_cfg": self.setup_cfg,
            "setup_py": self.setup_py,
            "pyproject": self.pyproject,
        }
        return {k: v for k, v in prop_dict.items() if v}

    @classmethod
    def from_requirement(cls, requirement, finder=None):
        # type: (TRequirement, Optional[PackageFinder]) -> Optional[SetupInfo]
        ireq = requirement.as_ireq()
        subdir = getattr(requirement.req, "subdirectory", None)
        return cls.from_ireq(ireq, subdir=subdir, finder=finder)

    @classmethod
    @lru_cache()
    def from_ireq(cls, ireq, subdir=None, finder=None, session=None):
        # type: (InstallRequirement, Optional[AnyStr], Optional[PackageFinder], Optional[requests.Session]) -> Optional[SetupInfo]
        import pip_shims.shims

        if not ireq.link:
            return None
        if ireq.link.is_wheel:
            return None
        stack = ExitStack()
        if not session:
            cmd = pip_shims.shims.InstallCommand()
            options, _ = cmd.parser.parse_args([])
            session = cmd._build_session(options)
        stack.enter_context(pip_shims.shims.global_tempdir_manager())
        vcs, uri = split_vcs_method_from_uri(ireq.link.url_without_fragment)
        parsed = urlparse(uri)
        if "file" in parsed.scheme:
            url_path = parsed.path
            if "@" in url_path:
                url_path, _, _ = url_path.rpartition("@")
            parsed = parsed._replace(path=url_path)
            uri = urlunparse(parsed)
        path = None
        is_file = False
        if ireq.link.scheme == "file" or uri.startswith("file://"):
            is_file = True
            if "file:/" in uri and "file:///" not in uri:
                uri = uri.replace("file:/", "file:///")
            path = pip_shims.shims.url_to_path(uri)
        kwargs = _prepare_wheel_building_kwargs(ireq)
        is_artifact_or_vcs = getattr(
            ireq.link, "is_vcs", getattr(ireq.link, "is_artifact", False)
        )
        is_vcs = True if vcs else is_artifact_or_vcs

        if not (ireq.editable and is_file and is_vcs):
            if ireq.is_wheel:
                only_download = True
                download_dir = kwargs["wheel_download_dir"]
            else:
                only_download = False
                download_dir = kwargs["download_dir"]
        elif path is not None and os.path.isdir(path):
            raise RequirementError(
                "The file URL points to a directory not installable: {}".format(ireq.link)
            )
        # this ensures the build dir is treated as the temporary build location
        # and the source dir is treated as permanent / not deleted by pip
        build_location_func = getattr(ireq, "build_location", None)
        if build_location_func is None:
            build_location_func = getattr(ireq, "ensure_build_location", None)
        if not ireq.source_dir:
            build_kwargs = {
                "build_dir": kwargs["build_dir"],
                "autodelete": False,
                "parallel_builds": True,
            }
            call_function_with_correct_args(build_location_func, **build_kwargs)
            ireq.ensure_has_source_dir(kwargs["src_dir"])
            pip_shims.shims.shim_unpack(
                download_dir=download_dir,
                ireq=ireq,
                only_download=only_download,
                session=session,
                hashes=ireq.hashes(False),
            )
        created = cls.create(
            ireq.source_dir, subdirectory=subdir, ireq=ireq, kwargs=kwargs, stack=stack
        )
        return created

    @classmethod
    def create(
        cls,
        base_dir,  # type: str
        subdirectory=None,  # type: Optional[str]
        ireq=None,  # type: Optional[InstallRequirement]
        kwargs=None,  # type: Optional[Dict[str, str]]
        stack=None,  # type: Optional[ExitStack]
    ):
        # type: (...) -> Optional[SetupInfo]
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
        if stack is None:
            stack = ExitStack()
        creation_kwargs["stack"] = stack
        if ireq:
            creation_kwargs["ireq"] = ireq
        created = cls(**creation_kwargs)
        created.get_initial_info()
        return created
