# -*- coding=utf-8 -*-
import importlib

from pip_shims import pip_version
import pkg_resources

def do_import(module_path, subimport=None, old_path=None, vendored_name=None):
    old_path = old_path or module_path
    prefix = vendored_name if vendored_name else "pip"
    prefixes = ["{0}._internal".format(prefix), "{0}".format(prefix)]
    paths = [module_path, old_path]
    search_order = ["{0}.{1}".format(p, pth) for p in prefixes for pth in paths if pth is not None]
    package = subimport if subimport else None
    for to_import in search_order:
        if not subimport:
            to_import, _, package = to_import.rpartition(".")
        try:
            imported = importlib.import_module(to_import)
        except ImportError:
            continue
        else:
            return getattr(imported, package)


InstallRequirement = do_import('req.req_install', 'InstallRequirement', vendored_name="notpip")
parse_requirements = do_import('req.req_file', 'parse_requirements', vendored_name="notpip")
RequirementSet = do_import('req.req_set', 'RequirementSet', vendored_name="notpip")
user_cache_dir = do_import('utils.appdirs', 'user_cache_dir', vendored_name="notpip")
FAVORITE_HASH = do_import('utils.hashes', 'FAVORITE_HASH', vendored_name="notpip")
is_file_url = do_import('download', 'is_file_url', vendored_name="notpip")
url_to_path = do_import('download', 'url_to_path', vendored_name="notpip")
PackageFinder = do_import('index', 'PackageFinder', vendored_name="notpip")
FormatControl = do_import('index', 'FormatControl', vendored_name="notpip")
Wheel = do_import('wheel', 'Wheel', vendored_name="notpip")
Command = do_import('cli.base_command', 'Command', old_path='basecommand', vendored_name="notpip")
cmdoptions = do_import('cli.cmdoptions', old_path='cmdoptions', vendored_name="notpip")
get_installed_distributions = do_import('utils.misc', 'get_installed_distributions', old_path='utils', vendored_name="notpip")
PyPI = do_import('models.index', 'PyPI', vendored_name='notpip')
SafeFileCache = do_import('download', 'SafeFileCache', vendored_name='notpip')
InstallationError = do_import('exceptions', 'InstallationError', vendored_name='notpip')

# pip 18.1 has refactored InstallRequirement constructors use by pip-tools.
if pkg_resources.parse_version(pip_version) < pkg_resources.parse_version('18.1'):
    install_req_from_line = InstallRequirement.from_line
    install_req_from_editable = InstallRequirement.from_editable
else:
    install_req_from_line = do_import('req.constructors', 'install_req_from_line', vendored_name="notpip")
    install_req_from_editable = do_import('req.constructors', 'install_req_from_editable', vendored_name="notpip")

