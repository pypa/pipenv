# -*- coding=utf-8 -*-
from collections import namedtuple
from contextlib import contextmanager
from .utils import _parse, get_package, STRING_TYPES
import importlib
import os
from pipenv.patched.notpip import __version__ as pip_version
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
        path_info_tuple.start_version <= parsed_pip_version
        and path_info_tuple.end_version >= parsed_pip_version
    ):
        return 1
    return 0


def get_ordered_paths(module_paths, base_path):
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
    return search_order


def do_import(module_paths, base_path=BASE_IMPORT_PATH):
    search_order = get_ordered_paths(module_paths, base_path)
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


def pip_import(import_name, *module_paths):
    paths = []
    for pip_path in module_paths:
        if not isinstance(pip_path, (list, tuple)):
            module_path, start_version, end_version = module_paths
            new_path = path_info(module_path, _parse(start_version), _parse(end_version))
            paths.append(new_path)
            break
        else:
            module_path, start_version, end_version = pip_path
            paths.append(path_info(module_path, _parse(start_version), _parse(end_version)))
    return do_import(paths)


parse_version = pip_import("parse_version", "index.parse_version", "7", "9999")
_strip_extras = pip_import("_strip_extras", "req.req_install._strip_extras", "7", "9999")
cmdoptions = pip_import(
    "", ("cli.cmdoptions", "18.1", "9999"), ("cmdoptions", "7.0.0", "18.0"),
)
Command = pip_import("Command",
    ("cli.base_command.Command", "18.1", "9999"),
    ("basecommand.Command", "7.0.0", "18.0"),
)
ConfigOptionParser = pip_import("ConfigOptionParser",
    ("cli.parser.ConfigOptionParser", "18.1", "9999"),
    ("baseparser.ConfigOptionParser", "7.0.0", "18.0"),
)
DistributionNotFound = pip_import("DistributionNotFound", "exceptions.DistributionNotFound", "7.0.0", "9999")
FAVORITE_HASH = pip_import("FAVORITE_HASH", "utils.hashes.FAVORITE_HASH", "7.0.0", "9999")
FormatControl = pip_import("FormatControl", "index.FormatControl", "7.0.0", "9999")
get_installed_distributions = pip_import("get_installed_distributions",
    ("utils.misc.get_installed_distributions", "10", "9999"),
    ("utils.get_installed_distributions", "7", "9.0.3")
)
index_group = pip_import("index_group",
    ("cli.cmdoptions.index_group", "18.1", "9999"),
    ("cmdoptions.index_group", "7.0.0", "18.0"),
)
InstallRequirement = pip_import("InstallRequirement", "req.req_install.InstallRequirement", "7.0.0", "9999")
is_archive_file = pip_import("is_archive_file", "download.is_archive_file", "7.0.0", "9999")
is_file_url = pip_import("is_file_url", "download.is_file_url", "7.0.0", "9999")
unpack_url = pip_import("unpack_url", "download.unpack_url", "7.0.0", "9999")
is_installable_dir = pip_import("is_installable_dir",
    ("utils.misc.is_installable_dir", "10.0.0", "9999"),
    ("utils.is_installable_dir", "7.0.0", "9.0.3"),
)
Link = pip_import("Link", "index.Link", "7.0.0", "9999")
make_abstract_dist = pip_import("make_abstract_dist",
    ("operations.prepare.make_abstract_dist", "10.0.0", "9999"),
    ("req.req_set.make_abstract_dist", "7.0.0", "9.0.3"),
)
make_option_group = pip_import("make_option_group",
    ("cli.cmdoptions.make_option_group", "18.1", "9999"),
    ("cmdoptions.make_option_group", "7.0.0", "18.0"),
)
PackageFinder = pip_import("PackageFinder", "index.PackageFinder", "7.0.0", "9999")
parse_requirements = pip_import("parse_requirements", "req.req_file.parse_requirements", "7.0.0", "9999")
parse_version = pip_import("parse_version", "index.parse_version", "7.0.0", "9999")
path_to_url = pip_import("path_to_url", "download.path_to_url", "7.0.0", "9999")
PipError = pip_import("PipError", "exceptions.PipError", "7.0.0", "9999")
RequirementPreparer = pip_import("RequirementPreparer", "operations.prepare.RequirementPreparer", "7", "9999")
RequirementSet = pip_import("RequirementSet", "req.req_set.RequirementSet", "7.0.0", "9999")
RequirementTracker = pip_import("RequirementTracker", "req.req_tracker.RequirementTracker", "7.0.0", "9999")
Resolver = pip_import("Resolver", "resolve.Resolver", "7.0.0", "9999")
SafeFileCache = pip_import("SafeFileCache", "download.SafeFileCache", "7.0.0", "9999")
url_to_path = pip_import("url_to_path", "download.url_to_path", "7.0.0", "9999")
USER_CACHE_DIR = pip_import("USER_CACHE_DIR", "locations.USER_CACHE_DIR", "7.0.0", "9999")
VcsSupport = pip_import("VcsSupport", "vcs.VcsSupport", "7.0.0", "9999")
Wheel = pip_import("Wheel", "wheel.Wheel", "7.0.0", "9999")
WheelCache = pip_import("WheelCache", ("cache.WheelCache", "10.0.0", "9999"), ("wheel.WheelCache", "7", "9.0.3"))
WheelBuilder = pip_import("WheelBuilder", "wheel.WheelBuilder", "7.0.0", "9999")


if not RequirementTracker:

    @contextmanager
    def RequirementTracker():
        yield
