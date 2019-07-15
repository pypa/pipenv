# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import ast
import atexit
import contextlib
import importlib
import os
import shutil
import sys
from functools import partial

import attr
import packaging.specifiers
import packaging.utils
import packaging.version
import pep517.envbuild
import pep517.wrappers
import pkg_resources.extern.packaging.requirements as pkg_resources_requirements
import six
from appdirs import user_cache_dir
from distlib.wheel import Wheel
from packaging.markers import Marker
from six.moves import configparser
from six.moves.urllib.parse import unquote, urlparse, urlunparse
from vistir.compat import FileNotFoundError, Iterable, Mapping, Path, lru_cache
from vistir.contextmanagers import cd, temp_path
from vistir.misc import run
from vistir.path import create_tracked_tempdir, ensure_mkdir_p, mkdir_p, rmtree

from .utils import (
    get_default_pyproject_backend,
    get_name_variants,
    get_pyproject,
    init_requirement,
    read_source,
    split_vcs_method_from_uri,
    strip_extras_markers_from_requirement,
)
from ..environment import MYPY_RUNNING
from ..exceptions import RequirementError

try:
    from setuptools.dist import distutils, Distribution
except ImportError:
    import distutils
    from distutils.core import Distribution


try:
    from os import scandir
except ImportError:
    from scandir import scandir


if MYPY_RUNNING:
    from typing import (
        Any,
        Callable,
        Dict,
        List,
        Generator,
        Optional,
        Union,
        Tuple,
        TypeVar,
        Text,
        Set,
        AnyStr,
        Sequence,
    )
    from pip_shims.shims import InstallRequirement, PackageFinder
    from pkg_resources import (
        PathMetadata,
        DistInfoDistribution,
        EggInfoDistribution,
        Requirement as PkgResourcesRequirement,
    )
    from packaging.requirements import Requirement as PackagingRequirement

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
        self.source_dir = os.path.abspath(source_dir)
        self.build_backend = build_backend
        self._subprocess_runner = pep517_subprocess_runner
        if backend_path:
            backend_path = [
                pep517.wrappers.norm_and_check(self.source_dir, p) for p in backend_path
            ]
        self.backend_path = backend_path


def parse_special_directives(setup_entry, package_dir=None):
    # type: (S, Optional[STRING_TYPE]) -> S
    rv = setup_entry
    if not package_dir:
        package_dir = os.getcwd()
    if setup_entry.startswith("file:"):
        _, path = setup_entry.split("file:")
        path = path.strip()
        if os.path.exists(path):
            rv = read_source(path)
    elif setup_entry.startswith("attr:"):
        _, resource = setup_entry.split("attr:")
        resource = resource.strip()
        with temp_path():
            sys.path.insert(0, package_dir)
            if "." in resource:
                resource, _, attribute = resource.rpartition(".")
            package, _, path = resource.partition(".")
            base_path = os.path.join(package_dir, package)
            if path:
                path = os.path.join(base_path, os.path.join(*path.split(".")))
            else:
                path = base_path
            if not os.path.exists(path) and os.path.exists("{0}.py".format(path)):
                path = "{0}.py".format(path)
            elif os.path.isdir(path):
                path = os.path.join(path, "__init__.py")
            rv = ast_parse_attribute_from_file(path, attribute)
            if rv:
                return str(rv)
            module = importlib.import_module(resource)
            rv = getattr(module, attribute)
            if not isinstance(rv, six.string_types):
                rv = str(rv)
    return rv


def make_base_requirements(reqs):
    # type: (Sequence[STRING_TYPE]) -> Set[BaseRequirement]
    requirements = set()
    if not isinstance(reqs, (list, tuple, set)):
        reqs = [reqs]
    for req in reqs:
        if isinstance(req, BaseRequirement):
            requirements.add(req)
        elif isinstance(req, pkg_resources_requirements.Requirement):
            requirements.add(BaseRequirement.from_req(req))
        elif req and isinstance(req, six.string_types) and not req.startswith("#"):
            requirements.add(BaseRequirement.from_string(req))
    return requirements


def setuptools_parse_setup_cfg(path):
    from setuptools.config import read_configuration

    parsed = read_configuration(path)
    results = parsed.get("metadata", {})
    results.update({parsed.get("options", {})})
    results["install_requires"] = make_base_requirements(
        results.get("install_requires", [])
    )
    extras = {}
    for extras_section, extras in results.get("extras_require", {}).items():
        new_reqs = tuple(make_base_requirements(extras))
        if new_reqs:
            extras[extras_section] = new_reqs
    results["extras_require"] = extras
    results["setup_requires"] = make_base_requirements(results.get("setup_requires", []))
    return results


def get_package_dir_from_setupcfg(parser, base_dir=None):
    # type: (configparser.ConfigParser, STRING_TYPE) -> Text
    if base_dir is not None:
        package_dir = base_dir
    else:
        package_dir = os.getcwd()
    if parser.has_option("options", "packages.find"):
        pkg_dir = parser.get("options", "packages.find")
        if isinstance(package_dir, Mapping):
            package_dir = os.path.join(package_dir, pkg_dir.get("where"))
    elif parser.has_option("options", "packages"):
        pkg_dir = parser.get("options", "packages")
        if "find:" in pkg_dir:
            _, pkg_dir = pkg_dir.split("find:")
            pkg_dir = pkg_dir.strip()
        package_dir = os.path.join(package_dir, pkg_dir)
    elif os.path.exists(os.path.join(package_dir, "setup.py")):
        setup_py = ast_parse_setup_py(os.path.join(package_dir, "setup.py"))
        if "package_dir" in setup_py:
            package_lookup = setup_py["package_dir"]
            if not isinstance(package_lookup, Mapping):
                package_dir = package_lookup
            package_dir = package_lookup.get(
                next(iter(list(package_lookup.keys()))), package_dir
            )
    if not os.path.isabs(package_dir):
        if not base_dir:
            package_dir = os.path.join(os.path.getcwd(), package_dir)
        else:
            package_dir = os.path.join(base_dir, package_dir)
    return package_dir


def get_name_and_version_from_setupcfg(parser, package_dir):
    # type: (configparser.ConfigParser, STRING_TYPE) -> Tuple[Optional[S], Optional[S]]
    name, version = None, None
    if parser.has_option("metadata", "name"):
        name = parse_special_directives(parser.get("metadata", "name"), package_dir)
    if parser.has_option("metadata", "version"):
        version = parse_special_directives(parser.get("metadata", "version"), package_dir)
    return name, version


def get_extras_from_setupcfg(parser):
    # type: (configparser.ConfigParser) -> Dict[STRING_TYPE, Tuple[BaseRequirement, ...]]
    extras = {}  # type: Dict[STRING_TYPE, Tuple[BaseRequirement, ...]]
    if "options.extras_require" not in parser.sections():
        return extras
    extras_require_section = parser.options("options.extras_require")
    for section in extras_require_section:
        if section in ["options", "metadata"]:
            continue
        section_contents = parser.get("options.extras_require", section)
        section_list = section_contents.split("\n")
        section_extras = tuple(make_base_requirements(section_list))
        if section_extras:
            extras[section] = section_extras
    return extras


def parse_setup_cfg(setup_cfg_path):
    # type: (S) -> Dict[S, Union[S, None, Set[BaseRequirement], List[S], Dict[STRING_TYPE, Tuple[BaseRequirement]]]]
    if not os.path.exists(setup_cfg_path):
        raise FileNotFoundError(setup_cfg_path)
    try:
        return setuptools_parse_setup_cfg(setup_cfg_path)
    except Exception:
        pass
    default_opts = {
        "metadata": {"name": "", "version": ""},
        "options": {
            "install_requires": "",
            "python_requires": "",
            "build_requires": "",
            "setup_requires": "",
            "extras": "",
            "packages.find": {"where": "."},
        },
    }
    parser = configparser.ConfigParser(default_opts)
    parser.read(setup_cfg_path)
    results = {}
    base_dir = os.path.dirname(os.path.abspath(setup_cfg_path))
    package_dir = get_package_dir_from_setupcfg(parser, base_dir=base_dir)
    name, version = get_name_and_version_from_setupcfg(parser, package_dir)
    results["name"] = name
    results["version"] = version
    install_requires = set()  # type: Set[BaseRequirement]
    if parser.has_option("options", "install_requires"):
        install_requires = make_base_requirements(
            parser.get("options", "install_requires").split("\n")
        )
    results["install_requires"] = install_requires
    if parser.has_option("options", "python_requires"):
        results["python_requires"] = parse_special_directives(
            parser.get("options", "python_requires"), package_dir
        )
    if parser.has_option("options", "build_requires"):
        results["build_requires"] = parser.get("options", "build_requires")
    results["extras_require"] = get_extras_from_setupcfg(parser)
    return results


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
        if isinstance(req, six.string_types):
            req = pkg_resources.Requirement.parse("{0}".format(str(req)))
        # req = strip_extras_markers_from_requirement(req)
        new_reqs.append(req)
    return new_reqs


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
        elif ireq is None and src_root is not None and not editable:
            src_dir = _get_src_dir(root=src_root)  # type: STRING_TYPE
        elif ireq is not None and ireq.editable and src_root is not None:
            src_dir = _get_src_dir(root=src_root)
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


def iter_metadata(path, pkg_name=None, metadata_type="egg-info"):
    # type: (AnyStr, Optional[AnyStr], AnyStr) -> Generator
    if pkg_name is not None:
        pkg_variants = get_name_variants(pkg_name)
    non_matching_dirs = []
    with contextlib.closing(ScandirCloser(path)) as path_iterator:
        for entry in path_iterator:
            if entry.is_dir():
                entry_name, ext = os.path.splitext(entry.name)
                if ext.endswith(metadata_type):
                    if pkg_name is None or entry_name.lower() in pkg_variants:
                        yield entry
                elif not entry.name.endswith(metadata_type):
                    non_matching_dirs.append(entry)
        for entry in non_matching_dirs:
            for dir_entry in iter_metadata(
                entry.path, pkg_name=pkg_name, metadata_type=metadata_type
            ):
                yield dir_entry


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
    if not isinstance(wheel_path, six.string_types):
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


class Analyzer(ast.NodeVisitor):
    def __init__(self):
        self.name_types = []
        self.function_map = {}  # type: Dict[Any, Any]
        self.functions = []
        self.strings = []
        self.assignments = {}
        self.binOps = []
        self.binOps_map = {}
        super(Analyzer, self).__init__()

    def generic_visit(self, node):
        if isinstance(node, ast.Call):
            self.functions.append(node)
            self.function_map.update(ast_unparse(node, initial_mapping=True))
        if isinstance(node, ast.Name):
            self.name_types.append(node)
        if isinstance(node, ast.Str):
            self.strings.append(node)
        if isinstance(node, ast.Assign):
            self.assignments.update(ast_unparse(node, initial_mapping=True))
        super(Analyzer, self).generic_visit(node)

    def visit_BinOp(self, node):
        left = ast_unparse(node.left, initial_mapping=True)
        right = ast_unparse(node.right, initial_mapping=True)
        node.left = left
        node.right = right
        self.binOps.append(node)

    def unmap_binops(self):
        for binop in self.binOps:
            self.binOps_map[binop] = ast_unparse(binop, analyzer=self)

    def match_assignment_str(self, match):
        return next(
            iter(k for k in self.assignments if getattr(k, "id", "") == match), None
        )

    def match_assignment_name(self, match):
        return next(
            iter(k for k in self.assignments if getattr(k, "id", "") == match.id), None
        )


def ast_unparse(item, initial_mapping=False, analyzer=None, recurse=True):  # noqa:C901
    # type: (Any, bool, Optional[Analyzer], bool) -> Union[List[Any], Dict[Any, Any], Tuple[Any, ...], STRING_TYPE]
    unparse = partial(
        ast_unparse, initial_mapping=initial_mapping, analyzer=analyzer, recurse=recurse
    )
    if isinstance(item, ast.Dict):
        unparsed = dict(zip(unparse(item.keys), unparse(item.values)))
    elif isinstance(item, ast.List):
        unparsed = [unparse(el) for el in item.elts]
    elif isinstance(item, ast.Tuple):
        unparsed = tuple([unparse(el) for el in item.elts])
    elif isinstance(item, ast.Str):
        unparsed = item.s
    elif isinstance(item, ast.Subscript):
        unparsed = unparse(item.value)
    elif isinstance(item, ast.BinOp):
        if analyzer and item in analyzer.binOps_map:
            unparsed = analyzer.binOps_map[item]
        elif isinstance(item.op, ast.Add):
            if not initial_mapping:
                right_item = unparse(item.right)
                left_item = unparse(item.left)
                if not all(
                    isinstance(side, (six.string_types, int, float, list, tuple))
                    for side in (left_item, right_item)
                ):
                    item.left = left_item
                    item.right = right_item
                    unparsed = item
                else:
                    unparsed = right_item + left_item
            else:
                unparsed = item
        elif isinstance(item.op, ast.Sub):
            unparsed = unparse(item.left) - unparse(item.right)
    elif isinstance(item, ast.Name):
        if not initial_mapping:
            unparsed = item.id
            if analyzer and recurse:
                if item in analyzer.assignments:
                    items = unparse(analyzer.assignments[item])
                    unparsed = items.get(item.id, item.id)
                else:
                    assignment = analyzer.match_assignment_name(item)
                    if assignment is not None:
                        items = unparse(analyzer.assignments[assignment])
                        unparsed = items.get(item.id, item.id)
        else:
            unparsed = item
    elif six.PY3 and isinstance(item, ast.NameConstant):
        unparsed = item.value
    elif isinstance(item, ast.Attribute):
        attr_name = getattr(item, "value", None)
        attr_attr = getattr(item, "attr", None)
        name = None
        if initial_mapping:
            unparsed = item
        elif attr_name and not recurse:
            name = attr_name
        else:
            name = unparse(attr_name) if attr_name is not None else attr_attr
        if name and attr_attr:
            if not initial_mapping and isinstance(name, six.string_types):
                unparsed = ".".join([item for item in (name, attr_attr) if item])
            else:
                unparsed = item
        elif attr_attr and not name and not initial_mapping:
            unparsed = attr_attr
        else:
            unparsed = name if not unparsed else unparsed
    elif isinstance(item, ast.Call):
        unparsed = {}
        if isinstance(item.func, ast.Name):
            func_name = unparse(item.func)
        elif isinstance(item.func, ast.Attribute):
            func_name = unparse(item.func)
        if func_name:
            unparsed[func_name] = {}
            for keyword in item.keywords:
                unparsed[func_name].update(unparse(keyword))
    elif isinstance(item, ast.keyword):
        unparsed = {unparse(item.arg): unparse(item.value)}
    elif isinstance(item, ast.Assign):
        # XXX: DO NOT UNPARSE THIS
        # XXX: If we unparse this it becomes impossible to map it back
        # XXX: To the original node in the AST so we can find the
        # XXX: Original reference
        if not initial_mapping:
            target = unparse(next(iter(item.targets)), recurse=False)
            val = unparse(item.value, recurse=False)
            if isinstance(target, (tuple, set, list)):
                unparsed = dict(zip(target, val))
            else:
                unparsed = {target: val}
        else:
            unparsed = {next(iter(item.targets)): item}
    elif isinstance(item, Mapping):
        unparsed = {}
        for k, v in item.items():
            try:
                unparsed[unparse(k)] = unparse(v)
            except TypeError:
                unparsed[k] = unparse(v)
    elif isinstance(item, (list, tuple)):
        unparsed = type(item)([unparse(el) for el in item])
    elif isinstance(item, six.string_types):
        unparsed = item
    else:
        return item
    return unparsed


def ast_parse_attribute_from_file(path, attribute):
    # type: (S) -> Any
    analyzer = ast_parse_file(path)
    target_value = None
    for k, v in analyzer.assignments.items():
        name = ""
        if isinstance(k, ast.Name):
            name = k.id
        elif isinstance(k, ast.Attribute):
            fn = ast_unparse(k)
            if isinstance(fn, six.string_types):
                _, _, name = fn.rpartition(".")
        if name == attribute:
            target_value = ast_unparse(v, analyzer=analyzer)
            break
    if isinstance(target_value, Mapping) and attribute in target_value:
        return target_value[attribute]
    return target_value


def ast_parse_file(path):
    # type: (S) -> Analyzer
    tree = ast.parse(read_source(path))
    ast_analyzer = Analyzer()
    ast_analyzer.visit(tree)
    return ast_analyzer


def ast_parse_setup_py(path):
    # type: (S) -> Dict[Any, Any]
    ast_analyzer = ast_parse_file(path)
    setup = {}  # type: Dict[Any, Any]
    ast_analyzer.unmap_binops()
    for k, v in ast_analyzer.function_map.items():
        fn_name = ""
        if isinstance(k, ast.Name):
            fn_name = k.id
        elif isinstance(k, ast.Attribute):
            fn = ast_unparse(k)
            if isinstance(fn, six.string_types):
                _, _, fn_name = fn.rpartition(".")
        if fn_name == "setup":
            setup = v
    cleaned_setup = ast_unparse(setup, analyzer=ast_analyzer)
    return cleaned_setup


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
        local_dict = {}
        if sys.version_info < (3, 5):
            save_argv = sys.argv
        else:
            save_argv = sys.argv.copy()
        try:
            global _setup_distribution, _setup_stop_after
            _setup_stop_after = "run"
            sys.argv[0] = script_name
            sys.argv[1:] = args
            with open(script_name, "rb") as f:
                contents = f.read()
                if six.PY3:
                    contents.replace(br"\r\n", br"\n")
                else:
                    contents.replace(r"\r\n", r"\n")
                if sys.version_info < (3, 5):
                    exec(contents, g, local_dict)
                else:
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
    name = attr.ib(default="", cmp=True)  # type: STRING_TYPE
    requirement = attr.ib(
        default=None, cmp=True
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
    name = attr.ib(default=None, cmp=True)  # type: STRING_TYPE
    requirements = attr.ib(factory=frozenset, cmp=True, type=frozenset)

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


@attr.s(slots=True, cmp=True, hash=True)
class SetupInfo(object):
    name = attr.ib(default=None, cmp=True)  # type: STRING_TYPE
    base_dir = attr.ib(default=None, cmp=True, hash=False)  # type: STRING_TYPE
    _version = attr.ib(default=None, cmp=True)  # type: STRING_TYPE
    _requirements = attr.ib(
        type=frozenset, factory=frozenset, cmp=True, hash=True
    )  # type: Optional[frozenset]
    build_requires = attr.ib(default=None, cmp=True)  # type: Optional[Tuple]
    build_backend = attr.ib(cmp=True)  # type: STRING_TYPE
    setup_requires = attr.ib(default=None, cmp=True)  # type: Optional[Tuple]
    python_requires = attr.ib(
        default=None, cmp=True
    )  # type: Optional[packaging.specifiers.SpecifierSet]
    _extras_requirements = attr.ib(default=None, cmp=True)  # type: Optional[Tuple]
    setup_cfg = attr.ib(type=Path, default=None, cmp=True, hash=False)
    setup_py = attr.ib(type=Path, default=None, cmp=True, hash=False)
    pyproject = attr.ib(type=Path, default=None, cmp=True, hash=False)
    ireq = attr.ib(
        default=None, cmp=True, hash=False
    )  # type: Optional[InstallRequirement]
    extra_kwargs = attr.ib(default=attr.Factory(dict), type=dict, cmp=False, hash=False)
    metadata = attr.ib(default=None)  # type: Optional[Tuple[STRING_TYPE]]

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

    @classmethod
    def get_setup_cfg(cls, setup_cfg_path):
        # type: (S) -> Dict[S, Union[S, None, Set[BaseRequirement], List[S], Tuple[S, Tuple[BaseRequirement]]]]
        return parse_setup_cfg(setup_cfg_path)

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
        if isinstance(name, six.string_types):
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
        for section in set(list(extras_require.keys())) - set(list(self.extras.keys())):
            extras = extras_require[section]
            extras_set = make_base_requirements(extras)
            if self.ireq and self.ireq.extras and section in self.ireq.extras:
                requirements |= extras_set
            extras_tuples.append((section, tuple(extras_set)))
        if self._extras_requirements is None:
            self._extras_requirements = ()
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
            parsed = self.get_setup_cfg(self.setup_cfg.as_posix())
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
        if not self.pyproject.exists():
            build_requires = ", ".join(['"{0}"'.format(r) for r in self.build_requires])
            self.pyproject.write_text(
                u"""
[build-system]
requires = [{0}]
build-backend = "{1}"
            """.format(
                    build_requires, self.build_backend
                ).strip()
            )
        return build_pep517(
            self.base_dir,
            self.extra_kwargs["build_dir"],
            config_settings=self.pep517_config,
            dist_type="wheel",
        )

    # noinspection PyPackageRequirements
    def build_sdist(self):
        # type: () -> S
        if not self.pyproject.exists():
            if not self.build_requires:
                build_requires = '"setuptools", "wheel"'
            else:
                build_requires = ", ".join(
                    ['"{0}"'.format(r) for r in self.build_requires]
                )
            self.pyproject.write_text(
                u"""
[build-system]
requires = [{0}]
build-backend = "{1}"
            """.format(
                    build_requires, self.build_backend
                ).strip()
            )
        return build_pep517(
            self.base_dir,
            self.extra_kwargs["build_dir"],
            config_settings=self.pep517_config,
            dist_type="sdist",
        )

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

            Erases metadata from **self.egg_base** and unsets **self.requirements**
            and **self.extras**.
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
        """Given a metadata directory, return the corresponding metadata dictionary.

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
        cleaned.update({"install_requires": metadata.get("requires", [])})
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
        if self.setup_cfg and self.setup_cfg.exists():
            parse_setupcfg = True
        if self.setup_py and self.setup_py.exists():
            parse_setuppy = True
        if parse_setuppy or parse_setupcfg:
            with cd(self.base_dir):
                if parse_setuppy:
                    self.update_from_dict(self.parse_setup_py())
                if parse_setupcfg:
                    self.update_from_dict(self.parse_setup_cfg())
            if self.name is not None and any(
                [
                    self.requires,
                    self.setup_requires,
                    self._extras_requirements,
                    self.build_backend,
                ]
            ):
                return self.as_dict()
        return self.get_info()

    def get_info(self):
        # type: () -> Dict[S, Any]
        with cd(self.base_dir):
            self.run_pyproject()
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
    def from_ireq(cls, ireq, subdir=None, finder=None):
        # type: (InstallRequirement, Optional[AnyStr], Optional[PackageFinder]) -> Optional[SetupInfo]
        import pip_shims.shims

        if not ireq.link:
            return None
        if ireq.link.is_wheel:
            return None
        if not finder:
            from .dependencies import get_finder

            finder = get_finder()
        _, uri = split_vcs_method_from_uri(unquote(ireq.link.url_without_fragment))
        parsed = urlparse(uri)
        if "file" in parsed.scheme:
            url_path = parsed.path
            if "@" in url_path:
                url_path, _, _ = url_path.rpartition("@")
            parsed = parsed._replace(path=url_path)
            uri = urlunparse(parsed)
        path = None
        if ireq.link.scheme == "file" or uri.startswith("file://"):
            if "file:/" in uri and "file:///" not in uri:
                uri = uri.replace("file:/", "file:///")
            path = pip_shims.shims.url_to_path(uri)
        kwargs = _prepare_wheel_building_kwargs(ireq)
        ireq.source_dir = kwargs["src_dir"]
        if not (
            ireq.editable
            and pip_shims.shims.is_file_url(ireq.link)
            and not ireq.link.is_artifact
        ):
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
        ireq.build_location(kwargs["build_dir"])
        src_dir = ireq.ensure_has_source_dir(kwargs["src_dir"])
        ireq._temp_build_dir.path = kwargs["build_dir"]

        ireq.populate_link(finder, False, False)
        pip_shims.shims.unpack_url(
            ireq.link,
            src_dir,
            download_dir,
            only_download=only_download,
            session=finder.session,
            hashes=ireq.hashes(False),
            progress_bar="off",
        )
        created = cls.create(src_dir, subdirectory=subdir, ireq=ireq, kwargs=kwargs)
        return created

    @classmethod
    def create(cls, base_dir, subdirectory=None, ireq=None, kwargs=None):
        # type: (AnyStr, Optional[AnyStr], Optional[InstallRequirement], Optional[Dict[AnyStr, AnyStr]]) -> Optional[SetupInfo]
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
