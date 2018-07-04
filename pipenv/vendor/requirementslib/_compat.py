# -*- coding=utf-8 -*-
import importlib
import six

# Use these imports as compatibility imports
try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path

try:
    from urllib.parse import urlparse, unquote
except ImportError:
    from urlparse import urlparse, unquote

if six.PY2:

    class FileNotFoundError(IOError):
        pass


else:

    class FileNotFoundError(FileNotFoundError):
        pass


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
user_cache_dir = do_import("utils.appdirs", "user_cache_dir")
FAVORITE_HASH = do_import("utils.hashes", "FAVORITE_HASH")
is_file_url = do_import("download", "is_file_url")
url_to_path = do_import("download", "url_to_path")
path_to_url = do_import("download", "path_to_url")
is_archive_file = do_import("download", "is_archive_file")
_strip_extras = do_import("req.req_install", "_strip_extras")
Link = do_import("index", "Link")
Wheel = do_import("wheel", "Wheel")
is_installable_file = do_import("utils.misc", "is_installable_file", old_path="utils")
is_installable_dir = do_import("utils.misc", "is_installable_dir", old_path="utils")
make_abstract_dist = do_import(
    "operations.prepare", "make_abstract_dist", old_path="req.req_set"
)
VcsSupport = do_import("vcs", "VcsSupport")
