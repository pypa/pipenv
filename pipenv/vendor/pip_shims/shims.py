# -*- coding=utf-8 -*-
from collections import namedtuple
from contextlib import contextmanager
from .utils import _parse, get_package, STRING_TYPES
import importlib
import os
from pip import __version__ as pip_version
import sys


has_modutil = False
if sys.version_info[:2] >= (3, 7):
    try:
        import modutil
    except ImportError:
        has_modutil = False
    else:
        has_modutil = True


BASE_IMPORT_PATH = os.environ.get("PIP_SHIMS_BASE_MODULE", "pip")
path_info = namedtuple("PathInfo", "path start_version end_version")
parsed_pip_version = _parse(pip_version)


def is_valid(path_info_tuple):
    if (
        path_info_tuple.start_version >= parsed_pip_version
        and path_info_tuple.end_version <= parsed_pip_version
    ):
        return 1
    return 0


def do_import(module_paths, base_path=BASE_IMPORT_PATH):
    if not isinstance(module_paths, list):
        module_paths = [module_paths]
    prefix_order = [pth.format(base_path) for pth in ["{0}._internal", "{0}"]]
    if _parse(pip_version) < _parse("10.0.0"):
        prefix_order = reversed(prefix_order)
    paths = sorted(module_paths, key=is_valid, reverse=True)
    search_order = [
        "{0}.{1}".format(p, pth.path)
        for p in prefix_order
        for pth in paths
        if pth is not None
    ]
    imported = None
    if has_modutil:
        pkgs = [get_package(pkg) for pkg in search_order]
        imports = [
            modutil.lazy_import(__name__, {to_import}) for to_import, pkg in pkgs
        ]
        imp_getattrs = [imp_getattr for mod, imp_getattr in imports]
        chained = modutil.chained___getattr__(__name__, *imp_getattrs)
        imported = None
        for to_import, pkg in pkgs:
            _, _, module_name = to_import.rpartition(".")
            try:
                imported = chained(module_name)
            except (modutil.ModuleAttributeError, ImportError):
                continue
            else:
                if not imported:
                    continue
                return getattr(imported, pkg)
        if not imported:
            return
        return imported
    for to_import in search_order:
        to_import, package = get_package(to_import)
        try:
            imported = importlib.import_module(to_import)
        except ImportError:
            continue
        else:
            return getattr(imported, package)
    return imported


parse_version = do_import(
    [path_info("index.parse_version", _parse("7.0.0"), _parse("9999"))]
)
_strip_extras = do_import(
    [path_info("req.req_install._strip_extras", _parse("7.0.0"), _parse("9999"))]
)
cmdoptions = do_import(
    [
        path_info("cli.cmdoptions", _parse("18.1"), _parse("9999")),
        path_info("cmdoptions", _parse("7.0.0"), _parse("18.0")),
    ]
)
Command = do_import(
    [
        path_info("cli.base_command.Command", _parse("18.1"), _parse("9999")),
        path_info("basecommand.Command", _parse("7.0.0"), _parse("18.0")),
    ]
)
ConfigOptionParser = do_import(
    [
        path_info("cli.parser.ConfigOptionParser", _parse("18.1"), _parse("9999")),
        path_info("baseparser.ConfigOptionParser", _parse("7.0.0"), _parse("18.0")),
    ]
)
DistributionNotFound = do_import(
    [path_info("exceptions.DistributionNotFound", _parse("7.0.0"), _parse("9999"))]
)
FAVORITE_HASH = do_import(
    [path_info("utils.hashes.FAVORITE_HASH", _parse("7.0.0"), _parse("9999"))]
)
FormatControl = do_import(
    [path_info("index.FormatControl", _parse("7.0.0"), _parse("9999"))]
)
get_installed_distributions = do_import(
    [
        path_info(
            "utils.misc.get_installed_distributions", _parse("10.0.0"), _parse("9999")
        ),
        path_info(
            "utils.get_installed_distributions", _parse("7.0.0"), _parse("9.0.3")
        ),
    ]
)
index_group = do_import(
    [
        path_info("cli.cmdoptions.index_group", _parse("18.1"), _parse("9999")),
        path_info("cmdoptions.index_group", _parse("7.0.0"), _parse("18.0")),
    ]
)
InstallRequirement = do_import(
    [path_info("req.req_install.InstallRequirement", _parse("7.0.0"), _parse("9999"))]
)
is_archive_file = do_import(
    [path_info("download.is_archive_file", _parse("7.0.0"), _parse("9999"))]
)
is_file_url = do_import(
    [path_info("download.is_file_url", _parse("7.0.0"), _parse("9999"))]
)
is_installable_dir = do_import(
    [
        path_info("utils.misc.is_installable_dir", _parse("10.0.0"), _parse("9999")),
        path_info("utils.is_installable_dir", _parse("7.0.0"), _parse("9.0.3")),
    ]
)
Link = do_import([path_info("index.Link", _parse("7.0.0"), _parse("9999"))])
make_abstract_dist = do_import(
    [
        path_info(
            "operations.prepare.make_abstract_dist", _parse("10.0.0"), _parse("9999")
        ),
        path_info("req.req_set.make_abstract_dist", _parse("7.0.0"), _parse("9.0.3")),
    ]
)
make_option_group = do_import(
    [
        path_info("cli.cmdoptions.make_option_group", _parse("18.1"), _parse("9999")),
        path_info("cmdoptions.make_option_group", _parse("7.0.0"), _parse("18.0")),
    ]
)
PackageFinder = do_import(
    [path_info("index.PackageFinder", _parse("7.0.0"), _parse("9999"))]
)
parse_requirements = do_import(
    [path_info("req.req_file.parse_requirements", _parse("7.0.0"), _parse("9999"))]
)
parse_version = do_import(
    [path_info("index.parse_version", _parse("7.0.0"), _parse("9999"))]
)
path_to_url = do_import(
    [path_info("download.path_to_url", _parse("7.0.0"), _parse("9999"))]
)
PipError = do_import(
    [path_info("exceptions.PipError", _parse("7.0.0"), _parse("9999"))]
)
RequirementPreparer = do_import(
    [
        path_info(
            "operations.prepare.RequirementPreparer", _parse("7.0.0"), _parse("9999")
        )
    ]
)
RequirementSet = do_import(
    [path_info("req.req_set.RequirementSet", _parse("7.0.0"), _parse("9999"))]
)
RequirementTracker = do_import(
    [path_info("req.req_tracker.RequirementTracker", _parse("7.0.0"), _parse("9999"))]
)
Resolver = do_import([path_info("resolve.Resolver", _parse("7.0.0"), _parse("9999"))])
SafeFileCache = do_import(
    [path_info("download.SafeFileCache", _parse("7.0.0"), _parse("9999"))]
)
url_to_path = do_import(
    [path_info("download.url_to_path", _parse("7.0.0"), _parse("9999"))]
)
USER_CACHE_DIR = do_import(
    [path_info("locations.USER_CACHE_DIR", _parse("7.0.0"), _parse("9999"))]
)
VcsSupport = do_import([path_info("vcs.VcsSupport", _parse("7.0.0"), _parse("9999"))])
Wheel = do_import([path_info("wheel.Wheel", _parse("7.0.0"), _parse("9999"))])
WheelCache = do_import([path_info("cache.WheelCache", _parse("7.0.0"), _parse("9999"))])


if not RequirementTracker:

    @contextmanager
    def RequirementTracker():
        yield
