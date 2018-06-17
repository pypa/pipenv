# -*- coding=utf-8 -*-
import importlib


def do_import(module_path, subimport=None, old_path=None, vendored_name=None):
    internal = 'pip._internal.{0}'.format(module_path)
    old_path = old_path or module_path
    pip9 = 'pip.{0}'.format(old_path)
    _tmp = None
    if vendored_name:
        vendor = '{0}._internal'.format(vendored_name)
        vendor = '{0}.{1}'.format(vendor, old_path if old_path else module_path)
        try:
            _tmp = importlib.import_module(vendor)
        except ImportError:
            pass
    if not _tmp:
        try:
            _tmp = importlib.import_module(internal)
        except ImportError:
            _tmp = importlib.import_module(pip9)
    if subimport:
        return getattr(_tmp, subimport, _tmp)
    return _tmp


InstallRequirement = do_import('req.req_install', 'InstallRequirement', vendored_name='notpip')
parse_requirements = do_import('req.req_file', 'parse_requirements', vendored_name='notpip')
RequirementSet = do_import('req.req_set', 'RequirementSet', vendored_name='notpip')
user_cache_dir = do_import('utils.appdirs', 'user_cache_dir', vendored_name='notpip')
FAVORITE_HASH = do_import('utils.hashes', 'FAVORITE_HASH', vendored_name='notpip')
is_file_url = do_import('download', 'is_file_url', vendored_name='notpip')
url_to_path = do_import('download', 'url_to_path', vendored_name='notpip')
PackageFinder = do_import('index', 'PackageFinder', vendored_name='notpip')
FormatControl = do_import('index', 'FormatControl', vendored_name='notpip')
Wheel = do_import('wheel', 'Wheel', vendored_name='notpip')
Command = do_import('basecommand', 'Command', vendored_name='notpip')
cmdoptions = do_import('cmdoptions', vendored_name='notpip')
get_installed_distributions = do_import('utils.misc', 'get_installed_distributions', old_path='utils', vendored_name='notpip')
PyPI = do_import('models.index', 'PyPI', vendored_name='notpip')
SafeFileCache = do_import('download', 'SafeFileCache', vendored_name='notpip')
InstallationError = do_import('exceptions', 'InstallationError', vendored_name='notpip')
