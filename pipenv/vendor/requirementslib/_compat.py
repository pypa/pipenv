# -*- coding=utf-8 -*-
# -*- coding=utf-8 -*-
import importlib


def do_import(module_path, subimport=None, old_path=None):
    internal = "pip._internal.{0}".format(module_path)
    old_path = old_path or module_path
    pip9 = "pip.{0}".format(old_path)
    try:
        _tmp = importlib.import_module(internal)
    except ImportError:
        _tmp = importlib.import_module(pip9)
    if subimport:
        return getattr(_tmp, subimport, _tmp)
    return _tmp


InstallRequirement = do_import("req.req_install", "InstallRequirement")
parse_requirements = do_import("req.req_file", "parse_requirements")
RequirementSet = do_import("req.req_set", "RequirementSet")
user_cache_dir = do_import("utils.appdirs", "user_cache_dir")
FAVORITE_HASH = do_import("utils.hashes", "FAVORITE_HASH")
is_file_url = do_import("download", "is_file_url")
url_to_path = do_import("download", "url_to_path")
path_to_url = do_import("download", "path_to_url")
is_archive_file = do_import("download", "is_archive_file")
_strip_extras = do_import("req.req_install", "_strip_extras")
PackageFinder = do_import("index", "PackageFinder")
FormatControl = do_import("index", "FormatControl")
Link = do_import("index", "Link")
Wheel = do_import("wheel", "Wheel")
Command = do_import("basecommand", "Command")
cmdoptions = do_import("cmdoptions")
get_installed_distributions = do_import(
    "utils.misc", "get_installed_distributions", old_path="utils"
)
is_installable_file = do_import("utils.misc", "is_installable_file", old_path="utils")
is_installable_dir = do_import("utils.misc", "is_installable_dir", old_path="utils")
PyPI = do_import("models.index", "PyPI")
