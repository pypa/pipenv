# -*- coding=utf-8 -*-
from __future__ import absolute_import
import importlib
import os
from appdirs import user_cache_dir
os.environ["PIP_SHIMS_BASE_MODULE"] = str("pipenv.patched.notpip")
import pip_shims.shims
from pip_shims.models import ShimmedPathCollection, ImportTypes

InstallationCandidate = ShimmedPathCollection("InstallationCandidate", ImportTypes.CLASS)
InstallationCandidate.create_path("models.candidate", "18.0", "9999")
InstallationCandidate.create_path("index", "7.0.3", "10.9.9")

PIP_VERSION = tuple(map(int, pip_shims.shims.parsed_pip_version.parsed_version.base_version.split(".")))

RequirementTracker = pip_shims.shims.RequirementTracker

def do_import(module_path, subimport=None, old_path=None):
    old_path = old_path or module_path
    pip_path = os.environ.get("PIP_SHIMS_BASE_MODULE", "pip")
    prefixes = ["{}._internal".format(pip_path), pip_path]
    paths = [module_path, old_path]
    search_order = [
        "{0}.{1}".format(p, pth) for p in prefixes for pth in paths if pth is not None
    ]
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

if PIP_VERSION[:2] <= (20, 0):
    def install_req_from_parsed_requirement(req, **kwargs):
        return req

else:
    from pipenv.patched.notpip._internal.req.constructors import install_req_from_parsed_requirement

InstallRequirement = pip_shims.shims.InstallRequirement
InstallationError = pip_shims.shims.InstallationError
parse_requirements = pip_shims.shims.parse_requirements
RequirementSet = pip_shims.shims.RequirementSet
SafeFileCache = pip_shims.shims.SafeFileCache
FAVORITE_HASH = pip_shims.shims.FAVORITE_HASH
path_to_url = pip_shims.shims.path_to_url
url_to_path = pip_shims.shims.url_to_path
PackageFinder = pip_shims.shims.PackageFinder
FormatControl = pip_shims.shims.FormatControl
InstallCommand = pip_shims.shims.InstallCommand
Wheel = pip_shims.shims.Wheel
cmdoptions = pip_shims.shims.cmdoptions
get_installed_distributions = pip_shims.shims.get_installed_distributions
PyPI = pip_shims.shims.PyPI
stdlib_pkgs = pip_shims.shims.stdlib_pkgs
DEV_PKGS = pip_shims.shims.DEV_PKGS
Link = pip_shims.shims.Link
Session = do_import("_vendor.requests.sessions", "Session")
Resolver = pip_shims.shims.Resolver
VcsSupport = pip_shims.shims.VcsSupport
WheelCache = pip_shims.shims.WheelCache
pip_version = pip_shims.shims.pip_version
normalize_path = do_import("utils.misc", "normalize_path")
install_req_from_line = pip_shims.shims.install_req_from_line
install_req_from_editable = pip_shims.shims.install_req_from_editable

def parse_requirements(
    filename, session, finder=None, options=None, constraint=False, isolated=False
):
    for parsed_req in _parse_requirements(
        filename, session, finder=finder, options=options, constraint=constraint
    ):
        yield install_req_from_parsed_requirement(parsed_req, isolated=isolated)
