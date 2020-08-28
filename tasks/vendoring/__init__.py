# -*- coding=utf-8 -*-
# Taken from pip
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/vendoring/__init__.py
""""Vendoring script, python 3.5 needed"""

import io
import itertools
import json
import re
import shutil
import sys

# from tempfile import TemporaryDirectory
import tarfile
import zipfile

from pathlib import Path

import bs4
import invoke
import requests

from urllib3.util import parse_url as urllib3_parse

from pipenv.utils import mkdir_p
from pipenv.vendor.vistir.compat import NamedTemporaryFile, TemporaryDirectory
from pipenv.vendor.vistir.contextmanagers import open_file
from pipenv.vendor.requirementslib.models.lockfile import Lockfile, merge_items
import pipenv.vendor.parse as parse


TASK_NAME = "update"

LIBRARY_DIRNAMES = {
    "requirements-parser": "requirements",
    "backports.shutil_get_terminal_size": "backports/shutil_get_terminal_size",
    "backports.weakref": "backports/weakref",
    "backports.functools_lru_cache": "backports/functools_lru_cache",
    "python-dotenv": "dotenv",
    "pip-tools": "piptools",
    "setuptools": "pkg_resources",
    "msgpack-python": "msgpack",
    "attrs": "attr",
    "enum": "backports/enum",
}

PY2_DOWNLOAD = ["enum34"]

# from time to time, remove the no longer needed ones
HARDCODED_LICENSE_URLS = {
    "pytoml": "https://github.com/avakar/pytoml/raw/master/LICENSE",
    "cursor": "https://raw.githubusercontent.com/GijsTimmers/cursor/master/LICENSE",
    "delegator.py": "https://raw.githubusercontent.com/kennethreitz/delegator.py/master/LICENSE",
    "click-didyoumean": "https://raw.githubusercontent.com/click-contrib/click-didyoumean/master/LICENSE",
    "click-completion": "https://raw.githubusercontent.com/click-contrib/click-completion/master/LICENSE",
    "parse": "https://raw.githubusercontent.com/techalchemy/parse/master/LICENSE",
    "semver": "https://raw.githubusercontent.com/k-bx/python-semver/master/LICENSE.txt",
    "crayons": "https://raw.githubusercontent.com/kennethreitz/crayons/master/LICENSE",
    "pip-tools": "https://raw.githubusercontent.com/jazzband/pip-tools/master/LICENSE",
    "pytoml": "https://github.com/avakar/pytoml/raw/master/LICENSE",
    "webencodings": "https://github.com/SimonSapin/python-webencodings/raw/"
    "master/LICENSE",
    "requirementslib": "https://github.com/techalchemy/requirementslib/raw/master/LICENSE",
    "distlib": "https://github.com/vsajip/distlib/raw/master/LICENSE.txt",
    "pythonfinder": "https://raw.githubusercontent.com/techalchemy/pythonfinder/master/LICENSE.txt",
    "pyparsing": "https://raw.githubusercontent.com/pyparsing/pyparsing/master/LICENSE",
    "resolvelib": "https://raw.githubusercontent.com/sarugaku/resolvelib/master/LICENSE",
    "funcsigs": "https://raw.githubusercontent.com/aliles/funcsigs/master/LICENSE",
}

FILE_WHITE_LIST = (
    "Makefile",
    "vendor.txt",
    "patched.txt",
    "__init__.py",
    "README.rst",
    "README.md",
    "appdirs.py",
    "safety.zip",
    "cacert.pem",
    "vendor_pip.txt",
)

PATCHED_RENAMES = {"pip": "notpip"}

LIBRARY_RENAMES = {
    "pip": "pipenv.patched.notpip",
    "functools32": "pipenv.vendor.backports.functools_lru_cache",
    "enum34": "enum",
}


LICENSE_RENAMES = {"pythonfinder/LICENSE": "pythonfinder/pep514tools.LICENSE"}


def drop_dir(path):
    if path.exists() and path.is_dir():
        shutil.rmtree(str(path), ignore_errors=True)


def remove_all(paths):
    for path in paths:
        if path.is_dir():
            drop_dir(path)
        else:
            path.unlink()


def log(msg):
    print("[vendoring.%s] %s" % (TASK_NAME, msg))


def _get_git_root(ctx):
    return Path(ctx.run("git rev-parse --show-toplevel", hide=True).stdout.strip())


def _get_vendor_dir(ctx):
    return _get_git_root(ctx) / "pipenv" / "vendor"


def _get_patched_dir(ctx):
    return _get_git_root(ctx) / "pipenv" / "patched"


def clean_vendor(ctx, vendor_dir):
    # Old _vendor cleanup
    remove_all(vendor_dir.glob("*.pyc"))
    log("Cleaning %s" % vendor_dir)
    for item in vendor_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(str(item))
        elif item.name not in FILE_WHITE_LIST:
            item.unlink()
        else:
            log("Skipping %s" % item)


def detect_vendored_libs(vendor_dir):
    retval = []
    for item in vendor_dir.iterdir():
        if item.is_dir():
            retval.append(item.name)
        elif "LICENSE" in item.name or "COPYING" in item.name:
            continue
        elif item.name.endswith(".pyi"):
            continue
        elif item.name not in FILE_WHITE_LIST:
            retval.append(item.name[:-3])
    return retval


def rewrite_imports(package_dir, vendored_libs, vendor_dir):
    for item in package_dir.iterdir():
        if item.is_dir():
            rewrite_imports(item, vendored_libs, vendor_dir)
        elif item.name.endswith(".py"):
            rewrite_file_imports(item, vendored_libs, vendor_dir)


def rewrite_file_imports(item, vendored_libs, vendor_dir):
    """Rewrite 'import xxx' and 'from xxx import' for vendored_libs"""
    # log('Reading file: %s' % item)
    try:
        text = item.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = item.read_text(encoding="cp1252")
    renames = LIBRARY_RENAMES
    for k in LIBRARY_RENAMES.keys():
        if k not in vendored_libs:
            vendored_libs.append(k)
    for lib in vendored_libs:
        to_lib = lib
        if lib in renames:
            to_lib = renames[lib]
        text = re.sub(
            r"([\n\s]*)import %s([\n\s\.]+)" % lib, r"\1import %s\2" % to_lib, text,
        )
        text = re.sub(r"([\n\s]*)from %s([\s\.])+" % lib, r"\1from %s\2" % to_lib, text,)
        text = re.sub(
            r"(\n\s*)__import__\('%s([\s'\.])+" % lib,
            r"\1__import__('%s\2" % to_lib,
            text,
        )
    item.write_text(text, encoding="utf-8")


def apply_patch(ctx, patch_file_path):
    log("Applying patch %s" % patch_file_path.name)
    ctx.run("git apply --ignore-whitespace --verbose %s" % patch_file_path)


def _recursive_write_to_zip(zf, path, root=None):
    if path == Path(zf.filename):
        return
    if root is None:
        if not path.is_dir():
            raise ValueError('root is required for non-directory path')
        root = path
    if not path.is_dir():
        zf.write(str(path), str(path.relative_to(root)))
        return
    for c in path.iterdir():
        _recursive_write_to_zip(zf, c, root)


@invoke.task
def update_safety(ctx):
    ignore_subdeps = ["pip", "pip-egg-info", "bin", "pipenv", "virtualenv", "virtualenv-clone", "setuptools",]
    ignore_files = ["pip-delete-this-directory.txt", "PKG-INFO", "easy_install.py", "clonevirtualenv.py"]
    ignore_patterns = ["*.pyd", "*.so", "**/*.pyc", "*.pyc"]
    cmd_envvars = {
        "PIPENV_NO_INHERIT": "true",
        "PIPENV_IGNORE_VIRTUALENVS": "true",
        "PIPENV_VENV_IN_PROJECT": "true"
    }
    patched_dir = _get_patched_dir(ctx)
    vendor_dir = _get_vendor_dir(ctx)
    safety_dir = Path(__file__).absolute().parent.joinpath("safety")
    log("Using vendor dir: %s" % patched_dir)
    log("Downloading safety package files...")
    build_dir = patched_dir / "build"
    root = _get_git_root(ctx)
    with TemporaryDirectory(prefix="pipenv-", suffix="-safety") as download_dir:
        log("generating lockfile...")
        packages = "\n".join(["safety", "requests[security]"])
        env = {"PIPENV_PACKAGES": packages}
        resolve_cmd = "python {0}".format(root.joinpath("pipenv/resolver.py").as_posix())
        py27_resolve_cmd = "python2.7 {0}".format(root.joinpath("pipenv/resolver.py").as_posix())
        _, _, resolved = ctx.run(resolve_cmd, hide=True, env=env).stdout.partition("RESULTS:")
        _, _, resolved_py2 = ctx.run(py27_resolve_cmd, hide=True, env=env).stdout.partition("RESULTS:")
        resolved = json.loads(resolved.strip())
        resolved_py2 = json.loads(resolved_py2.strip())
        pkg_dict, pkg_dict_py2 = {}, {}
        for pkg in resolved:
            name = pkg.pop("name")
            pkg["version"] = "=={0}".format(pkg["version"])
            pkg_dict[name] = pkg
        for pkg in resolved_py2:
            name = pkg.pop("name")
            pkg["version"] = "=={0}".format(pkg["version"])
            pkg_dict_py2[name] = pkg
        merged = merge_items([pkg_dict, pkg_dict_py2])
        lf = Lockfile.create(safety_dir.as_posix())
        lf["default"] = merged
        lf.write()
        # envvars_no_deps = {"PIP_NO_DEPS": "true"}.update(cmd_envvars)
        # ctx.run("python -m pipenv run pip install safety", env=envvars_no_deps)
        # ctx.run("python -m pipenv run pip uninstall -y pipenv", env=cmd_envvars)
        # ctx.run("python -m pipenv install safety", env=cmd_envvars)
        # ctx.run("python -m pipenv run pip uninstall -y pipenv", env=cmd_envvars)
        # ctx.run("python2.7 -m pip install --upgrade --upgrade-strategy=eager -e {}".format(root.as_posix()))
        # ctx.run("python2.7 -m pipenv install safety", env=cmd_envvars)
        # requirements_txt = ctx.run("python2.7 -m pipenv lock -r", env=cmd_envvars, quiet=True).out
        requirements = [
            r.as_line(include_hashes=False, include_markers=False)
            for r in lf.requirements
        ]
        safety_dir.joinpath("requirements.txt").write_text("\n".join(requirements))
        if build_dir.exists() and build_dir.is_dir():
            log("dropping pre-existing build dir at {0}".format(build_dir.as_posix()))
            drop_dir(build_dir)
        pip_command = "pip download -b {0} --no-binary=:all: --no-clean --no-deps -d {1} pyyaml safety".format(
            build_dir.absolute().as_posix(), str(download_dir.name),
        )
        log("downloading deps via pip: {0}".format(pip_command))
        ctx.run(pip_command)
        safety_build_dir = build_dir / "safety"
        yaml_build_dir = build_dir / "pyyaml"
        lib_dir = safety_dir.joinpath("lib")

        with ctx.cd(str(safety_dir)):
            lib_dir.mkdir(exist_ok=True)
            install_cmd = "python2.7 -m pip install --ignore-requires-python -t {0} -r {1}".format(lib_dir.as_posix(), safety_dir.joinpath("requirements.txt").as_posix())
            log("installing dependencies: {0}".format(install_cmd))
            ctx.run(install_cmd)
            safety_dir = safety_dir.absolute()
            yaml_dir = lib_dir / "yaml"
            yaml_lib_dir_map = {
                "2": {
                    "current_path": yaml_build_dir / "lib/yaml",
                    "destination": lib_dir / "yaml2",
                },
                "3": {
                    "current_path": yaml_build_dir / "lib3/yaml",
                    "destination": lib_dir / "yaml3",
                },
            }
            if yaml_dir.exists():
                drop_dir(yaml_dir)
            log("Mapping yaml paths for python 2 and 3...")
            for py_version, path_dict in yaml_lib_dir_map.items():
                path_dict["current_path"].rename(path_dict["destination"])
            log("Ensuring certificates are available...")
            requests_dir = lib_dir / "requests"
            cacert = vendor_dir / "certifi" / "cacert.pem"
            if not cacert.exists():
                from pipenv.vendor import requests
                cacert = Path(requests.certs.where())
            target_cert = requests_dir / "cacert.pem"
            target_cert.write_bytes(cacert.read_bytes())
            log("dropping ignored files...")
            for pattern in ignore_patterns:
                for path in lib_dir.rglob(pattern):
                    log("removing {0!s}".format(path))
                    path.unlink()
            for dep in ignore_subdeps:
                if lib_dir.joinpath(dep).exists():
                    log("cleaning up {0}".format(dep))
                    drop_dir(lib_dir.joinpath(dep))
                for path in itertools.chain.from_iterable((
                    lib_dir.rglob("{0}*.egg-info".format(dep)),
                    lib_dir.rglob("{0}*.dist-info".format(dep))
                )):
                    log("cleaning up {0}".format(path))
                    drop_dir(path)
            for fn in ignore_files:
                for path in lib_dir.rglob(fn):
                    log("cleaning up {0}".format(path))
                    path.unlink()
        zip_name = "{0}/safety.zip".format(str(patched_dir))
        log("writing zipfile...")
        with zipfile.ZipFile(zip_name, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            _recursive_write_to_zip(zf, safety_dir)
        drop_dir(build_dir)
        drop_dir(lib_dir)


def rename_if_needed(ctx, vendor_dir, item):
    rename_dict = LIBRARY_RENAMES if vendor_dir.name != "patched" else PATCHED_RENAMES
    new_path = None
    if item.name in rename_dict or item.name in LIBRARY_DIRNAMES:
        new_name = rename_dict.get(item.name, LIBRARY_DIRNAMES.get(item.name))
        new_path = item.parent / new_name
        log("Renaming %s => %s" % (item.name, new_path))
        # handle existing directories
        try:
            item.rename(str(new_path))
        except OSError:
            for child in item.iterdir():
                child.rename(str(new_path / child.name))


def write_backport_imports(ctx, vendor_dir):
    backport_dir = vendor_dir / "backports"
    if not backport_dir.exists():
        return
    backport_init = backport_dir / "__init__.py"
    backport_libs = detect_vendored_libs(backport_dir)
    init_py_lines = backport_init.read_text().splitlines()
    for lib in backport_libs:
        lib_line = "from . import {0}".format(lib)
        if lib_line not in init_py_lines:
            log("Adding backport %s to __init__.py exports" % lib)
            init_py_lines.append(lib_line)
    backport_init.write_text("\n".join(init_py_lines) + "\n")


def _ensure_package_in_requirements(ctx, requirements_file, package):
    requirement = None
    log("using requirements file: %s" % requirements_file)
    req_file_lines = [l for l in requirements_file.read_text().splitlines()]
    if package:
        match = [r for r in req_file_lines if r.strip().lower().startswith(package)]
        matched_req = None
        if match:
            for m in match:
                specifiers = [m.index(s) for s in [">", "<", "=", "~"] if s in m]
                if m.lower() == package or (
                    specifiers and m[: min(specifiers)].lower() == package
                ):
                    matched_req = "{0}".format(m)
                    requirement = matched_req
                    log("Matched req: %r" % matched_req)
        if not matched_req:
            req_file_lines.append("{0}".format(package))
            log("Writing requirements file: %s" % requirements_file)
            requirements_file.write_text("\n".join(req_file_lines))
            requirement = "{0}".format(package)
    return requirement


def install_pyyaml(ctx, vendor_dir):
    build_dir = vendor_dir / "build"
    if build_dir.exists() and build_dir.is_dir():
        log("dropping pre-existing build dir at {0}".format(build_dir.as_posix()))
        drop_dir(build_dir)
    with TemporaryDirectory(prefix="pipenv-", suffix="-safety") as download_dir:
        pip_command = "pip download -b {0} --no-binary=:all: --no-clean --no-deps -d {1} pyyaml safety".format(
            build_dir.absolute().as_posix(), str(download_dir.name),
        )
        log("downloading deps via pip: {0}".format(pip_command))
        ctx.run(pip_command)
    safety_build_dir = build_dir / "safety"
    yaml_build_dir = build_dir / "pyyaml"
    yaml_dir = vendor_dir / "yaml"
    yaml_lib_dir_map = {
        "2": {
            "current_path": yaml_build_dir / "lib/yaml",
            "destination": vendor_dir / "yaml2",
        },
        "3": {
            "current_path": yaml_build_dir / "lib3/yaml",
            "destination": vendor_dir / "yaml3",
        },
    }
    if yaml_dir.exists():
        drop_dir(yaml_dir)
    log("Mapping yaml paths for python 2 and 3...")
    for py_version, path_dict in yaml_lib_dir_map.items():
        path_dict["current_path"].rename(path_dict["destination"])
        path_dict["destination"].joinpath("LICENSE").write_text(yaml_build_dir.joinpath("LICENSE").read_text())
    drop_dir(build_dir)


def install(ctx, vendor_dir, package=None):
    requirements_file = vendor_dir / "{0}.txt".format(vendor_dir.name)
    requirement = "-r {0}".format(requirements_file.as_posix())
    log("Using requirements file: %s" % requirement)
    if package:
        requirement = _ensure_package_in_requirements(ctx, requirements_file, package)
    # We use --no-deps because we want to ensure that all of our dependencies
    # are added to vendor.txt, this includes all dependencies recursively up
    # the chain.
    ctx.run(
        "pip install -t {0} --no-compile --no-deps --upgrade {1}".format(
            vendor_dir.as_posix(), requirement,
        )
    )
    # read licenses from distinfo files if possible
    for path in vendor_dir.glob("*.dist-info"):
        pkg, _, _ = path.stem.rpartition("-")
        license_file = path / "LICENSE"
        if not license_file.exists():
            continue
        if vendor_dir.joinpath(pkg).exists():
            vendor_dir.joinpath(pkg).joinpath("LICENSE").write_text(
                license_file.read_text()
            )
        elif vendor_dir.joinpath("{0}.py".format(pkg)).exists():
            vendor_dir.joinpath("{0}.LICENSE".format(pkg)).write_text(
                license_file.read_text()
            )
        else:
            pkg = pkg.replace("-", "?").replace("_", "?")
            matched_path = next(
                iter(pth for pth in vendor_dir.glob("{0}*".format(pkg))), None
            )
            if matched_path is not None:
                if matched_path.is_dir():
                    target = vendor_dir.joinpath(matched_path).joinpath("LICENSE")
                else:
                    target = vendor_dir.joinpath("{0}.LICENSE".format(matched_path))
                target.write_text(
                    license_file.read_text()
                )


def post_install_cleanup(ctx, vendor_dir):
    remove_all(vendor_dir.glob("*.dist-info"))
    remove_all(vendor_dir.glob("*.egg-info"))

    # Cleanup setuptools unneeded parts
    drop_dir(vendor_dir / "bin")
    drop_dir(vendor_dir / "tests")
    drop_dir(vendor_dir / "shutil_backports")
    remove_all(vendor_dir.glob("toml.py"))


@invoke.task
def apply_patches(ctx, patched=False, pre=False):
    if patched:
        vendor_dir = _get_patched_dir(ctx)
    else:
        vendor_dir = _get_vendor_dir(ctx)
    log("Applying pre-patches...")
    patch_dir = Path(__file__).parent / "patches" / vendor_dir.name
    if pre:
        if not patched:
            pass
        for patch in patch_dir.glob("*.patch"):
            if not patch.name.startswith("_post"):
                apply_patch(ctx, patch)
    else:
        patches = patch_dir.glob("*.patch" if not patched else "_post*.patch")
        for patch in patches:
            apply_patch(ctx, patch)


def vendor(ctx, vendor_dir, package=None, rewrite=True):
    log("Reinstalling vendored libraries")
    is_patched = vendor_dir.name == "patched"
    install(ctx, vendor_dir, package=package)
    log("Running post-install cleanup...")
    post_install_cleanup(ctx, vendor_dir)
    # Detect the vendored packages/modules
    vendored_libs = detect_vendored_libs(_get_vendor_dir(ctx))
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))

    # Apply pre-patches
    log("Applying pre-patches...")
    if is_patched:
        apply_patches(ctx, patched=is_patched, pre=True)
    log("Removing scandir library files...")
    for extension in ("*.so", "*.pyd", "*.egg-info", "*.dist-info"):
        remove_all(vendor_dir.glob(extension))
    for dirname in ("setuptools", "pkg_resources/_vendor", "pkg_resources/extern", "bin"):
        drop_dir(vendor_dir / dirname)

    # Global import rewrites
    log("Renaming specified libs...")
    for item in vendor_dir.iterdir():
        if item.is_dir():
            if rewrite and not package or (package and item.name.lower() in package):
                log("Rewriting imports for %s..." % item)
                rewrite_imports(item, vendored_libs, vendor_dir)
            rename_if_needed(ctx, vendor_dir, item)
        elif item.name not in FILE_WHITE_LIST:
            if rewrite and not package or (package and item.stem.lower() in package):
                rewrite_file_imports(item, vendored_libs, vendor_dir)
    write_backport_imports(ctx, vendor_dir)
    if not package:
        apply_patches(ctx, patched=is_patched, pre=False)
        if is_patched:
            piptools_vendor = vendor_dir / "piptools" / "_vendored"
            if piptools_vendor.exists():
                drop_dir(piptools_vendor)
            msgpack = vendor_dir / "notpip" / "_vendor" / "msgpack"
            if msgpack.exists():
                remove_all(msgpack.glob("*.so"))


@invoke.task
def redo_imports(ctx, library, vendor_dir=None):
    if vendor_dir is None:
        vendor_dir = _get_vendor_dir(ctx)
    else:
        vendor_dir = Path(vendor_dir).absolute()
    log("Using vendor dir: %s" % vendor_dir)
    vendored_libs = detect_vendored_libs(vendor_dir)
    item = vendor_dir / library
    library_name = vendor_dir / "{0}.py".format(library)
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))
    log("Rewriting imports for %s..." % item)
    if item.is_dir():
        rewrite_imports(item, vendored_libs, vendor_dir)
    else:
        rewrite_file_imports(library_name, vendored_libs, vendor_dir)

@invoke.task
def rewrite_all_imports(ctx):
    vendor_dir = _get_vendor_dir(ctx)
    log("Using vendor dir: %s" % vendor_dir)
    vendored_libs = detect_vendored_libs(vendor_dir)
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))
    log("Rewriting all imports related to vendored libs")
    for item in vendor_dir.iterdir():
        if item.is_dir():
            rewrite_imports(item, vendored_libs)
        elif item.name not in FILE_WHITE_LIST:
            rewrite_file_imports(item, vendored_libs)


@invoke.task
def packages_missing_licenses(
    ctx, vendor_dir=None, requirements_file="vendor.txt", package=None
):
    if not vendor_dir:
        vendor_dir = _get_vendor_dir(ctx)
    if package is not None:
        requirements = [package]
    else:
        requirements = vendor_dir.joinpath(requirements_file).read_text().splitlines()
    new_requirements = []
    LICENSE_EXTS = ("rst", "txt", "APACHE", "BSD", "md")
    LICENSES = [
        ".".join(lic)
        for lic in itertools.product(("LICENSE", "LICENSE-MIT"), LICENSE_EXTS)
    ]
    for i, req in enumerate(requirements):
        if req.startswith("git+"):
            pkg = req.strip().split("#egg=")[1]
        else:
            pkg = req.strip().split("=")[0]
        possible_pkgs = [pkg, pkg.replace("-", "_")]
        match_found = False
        if pkg in PY2_DOWNLOAD:
            match_found = True
            # print("pkg ===> %s" % pkg)
        if pkg in LIBRARY_DIRNAMES:
            possible_pkgs.append(LIBRARY_DIRNAMES[pkg])
        for pkgpath in possible_pkgs:
            pkgpath = vendor_dir.joinpath(pkgpath)
            py_path = pkgpath.parent / "{0}.py".format(pkgpath.stem)
            if pkgpath.exists() and pkgpath.is_dir():
                for license_path in LICENSES:
                    license_path = pkgpath.joinpath(license_path)
                    if license_path.exists():
                        match_found = True
                        # log("%s: Trying path %s... FOUND" % (pkg, license_path))
                        break
            elif pkgpath.exists() or py_path.exists():
                for license_path in LICENSES:
                    license_name = "{0}.{1}".format(pkgpath.stem, license_path)
                    license_path = pkgpath.parent / license_name
                    if license_path.exists():
                        match_found = True
                        # log("%s: Trying path %s... FOUND" % (pkg, license_path))
                        break
            if match_found:
                break
        if match_found:
            continue
        else:
            #  log("%s: No license found in %s" % (pkg, pkgpath))
            new_requirements.append(req)
    return new_requirements


@invoke.task
def download_licenses(
    ctx,
    vendor_dir=None,
    requirements_file="vendor.txt",
    package=None,
    only=False,
    patched=False,
):
    log("Downloading licenses")
    if not vendor_dir:
        if patched:
            vendor_dir = _get_patched_dir(ctx)
            requirements_file = "patched.txt"
        else:
            vendor_dir = _get_vendor_dir(ctx)
    requirements_file = vendor_dir / requirements_file
    requirements = packages_missing_licenses(
        ctx, vendor_dir, requirements_file, package=package
    )

    with NamedTemporaryFile(
        prefix="pipenv", suffix="vendor-reqs", delete=False, mode="w"
    ) as fh:
        fh.write("\n".join(requirements))
        new_requirements_file = fh.name
    new_requirements_file = Path(new_requirements_file)
    log(requirements)
    tmp_dir = vendor_dir / "__tmp__"
    # TODO: Fix this whenever it gets sorted out (see https://github.com/pypa/pip/issues/5739)
    cmd = "pip download --no-binary :all: --only-binary requests_download --no-deps"
    enum_cmd = "pip download --no-deps"
    ctx.run("pip install flit")  # needed for the next step
    for req in requirements_file.read_text().splitlines():
        if req.startswith("enum34"):
            exe_cmd = "{0} -d {1} {2}".format(enum_cmd, tmp_dir.as_posix(), req)
        else:
            exe_cmd = "{0} --no-build-isolation -d {1} {2}".format(
                cmd, tmp_dir.as_posix(), req
            )
        try:
            ctx.run(exe_cmd)
        except invoke.exceptions.UnexpectedExit as e:
            if "Disabling PEP 517 processing is invalid" not in e.result.stderr:
                log("WARNING: Failed to download license for {0}".format(req))
                continue
            parse_target = (
                "Disabling PEP 517 processing is invalid: project specifies a build "
                "backend of {backend} in pyproject.toml"
            )
            target = parse.parse(parse_target, e.result.stderr.strip())
            backend = target.named.get("backend")
            if backend is not None:
                if "." in backend:
                    backend, _, _ = backend.partition(".")
                ctx.run("pip install {0}".format(backend))
            ctx.run(
                "{0} --no-build-isolation -d {1} {2}".format(cmd, tmp_dir.as_posix(), req)
            )
    for sdist in tmp_dir.iterdir():
        extract_license(vendor_dir, sdist)
    new_requirements_file.unlink()
    drop_dir(tmp_dir)


def extract_license(vendor_dir, sdist):
    if sdist.stem.endswith(".tar"):
        ext = sdist.suffix[1:]
        with tarfile.open(sdist, mode="r:{}".format(ext)) as tar:
            found = find_and_extract_license(vendor_dir, tar, tar.getmembers())
    elif sdist.suffix in (".zip", ".whl"):
        with zipfile.ZipFile(sdist) as zip:
            found = find_and_extract_license(vendor_dir, zip, zip.infolist())
    else:
        raise NotImplementedError("new sdist type!")

    if not found:
        log("License not found in {}, will download".format(sdist.name))
        license_fallback(vendor_dir, sdist.name)


def find_and_extract_license(vendor_dir, tar, members):
    found = False
    for member in members:
        try:
            name = member.name
        except AttributeError:  # zipfile
            name = member.filename
        if "LICENSE" in name or "COPYING" in name:
            if "/test" in name:
                # some testing licenses in hml5lib and distlib
                log("Ignoring {}".format(name))
                continue
            found = True
            extract_license_member(vendor_dir, tar, member, name)
    return found


def license_fallback(vendor_dir, sdist_name):
    """Hardcoded license URLs. Check when updating if those are still needed"""
    libname = libname_from_dir(sdist_name)
    if libname not in HARDCODED_LICENSE_URLS:
        raise ValueError("No hardcoded URL for {} license".format(libname))

    url = HARDCODED_LICENSE_URLS[libname]
    _, _, name = url.rpartition("/")
    dest = license_destination(vendor_dir, libname, name)
    r = requests.get(url, allow_redirects=True)
    log("Downloading {}".format(url))
    r.raise_for_status()
    dest.write_bytes(r.content)


def libname_from_dir(dirname):
    """Reconstruct the library name without it's version"""
    parts = []
    for part in dirname.split("-"):
        if part[0].isdigit():
            break
        parts.append(part)
    return "-".join(parts)


def license_destination(vendor_dir, libname, filename):
    """Given the (reconstructed) library name, find appropriate destination"""
    normal = vendor_dir / libname
    if normal.is_dir():
        return normal / filename
    lowercase = vendor_dir / libname.lower().replace("-", "_")
    if lowercase.is_dir():
        return lowercase / filename
    rename_dict = LIBRARY_RENAMES if vendor_dir.name != "patched" else PATCHED_RENAMES
    # Short circuit all logic if we are renaming the whole library
    if libname in rename_dict:
        return vendor_dir / rename_dict[libname] / filename
    if libname in LIBRARY_DIRNAMES:
        override = vendor_dir / LIBRARY_DIRNAMES[libname]
        if not override.exists() and override.parent.exists():
            # for flattened subdeps, specifically backports/weakref.py
            return (vendor_dir / override.parent) / "{0}.{1}".format(
                override.name, filename
            )
        license_path = Path(LIBRARY_DIRNAMES[libname]) / filename
        if license_path.as_posix() in LICENSE_RENAMES:
            return vendor_dir / LICENSE_RENAMES[license_path.as_posix()]
        return vendor_dir / LIBRARY_DIRNAMES[libname] / filename
    # fallback to libname.LICENSE (used for nondirs)
    return vendor_dir / "{}.{}".format(libname, filename)


def extract_license_member(vendor_dir, tar, member, name):
    mpath = Path(name)  # relative path inside the sdist
    dirname = list(mpath.parents)[-2].name  # -1 is .
    libname = libname_from_dir(dirname)
    dest = license_destination(vendor_dir, libname, mpath.name)
    log("Extracting {} into {}".format(name, dest))
    try:
        fileobj = tar.extractfile(member)
        dest.write_bytes(fileobj.read())
    except AttributeError:  # zipfile
        dest.write_bytes(tar.read(member))


@invoke.task()
def generate_patch(ctx, package_path, patch_description, base="HEAD"):
    pkg = Path(package_path)
    if len(pkg.parts) != 2 or pkg.parts[0] not in ("vendor", "patched"):
        raise ValueError(
            "example usage: generate-patch patched/piptools some-description"
        )
    if patch_description:
        patch_fn = "{0}-{1}.patch".format(pkg.parts[1], patch_description)
    else:
        patch_fn = "{0}.patch".format(pkg.parts[1])
    command = "git diff {base} -p {root} > {out}".format(
        base=base,
        root=Path("pipenv").joinpath(pkg),
        out=Path(__file__).parent.joinpath("patches", pkg.parts[0], patch_fn),
    )
    with ctx.cd(str(_get_git_root(ctx))):
        log(command)
        ctx.run(command)


@invoke.task()
def update_pip_deps(ctx):
    patched_dir = _get_patched_dir(ctx)
    base_vendor_dir = _get_vendor_dir(ctx)
    base_vendor_file = base_vendor_dir / "vendor_pip.txt"
    pip_dir = patched_dir / "notpip"
    vendor_dir = pip_dir / "_vendor"
    vendor_file = vendor_dir / "vendor.txt"
    vendor_file.write_bytes(base_vendor_file.read_bytes())
    download_licenses(ctx, vendor_dir)


@invoke.task
def download_all_licenses(ctx, include_pip=False):
    vendor_dir = _get_vendor_dir(ctx)
    patched_dir = _get_patched_dir(ctx)
    download_licenses(ctx, vendor_dir)
    download_licenses(ctx, patched_dir, "patched.txt")
    if include_pip:
        update_pip_deps(ctx)


def unpin_file(contents):
    requirements = []
    for line in contents.splitlines():
        if "==" in line:
            line, _, _ = line.strip().partition("=")
        if not line.startswith("#"):
            requirements.append(line)
    return "\n".join(sorted(requirements))


def unpin_and_copy_requirements(ctx, requirement_file, name="requirements.txt"):
    with TemporaryDirectory() as tempdir:
        target = Path(tempdir.name).joinpath("requirements.txt")
        contents = unpin_file(requirement_file.read_text())
        target.write_text(contents)
        env = {
            "PIPENV_IGNORE_VIRTUALENVS": "1",
            "PIPENV_NOSPIN": "1",
            "PIPENV_PYTHON": "2.7",
        }
        with ctx.cd(tempdir.name):
            ctx.run("pipenv install -r {0}".format(target.as_posix()), env=env, hide=True)
            result = ctx.run("pipenv lock -r", env=env, hide=True).stdout.strip()
            ctx.run("pipenv --rm", env=env, hide=True)
            result = list(sorted([line.strip() for line in result.splitlines()[1:]]))
            new_requirements = requirement_file.parent.joinpath(name)
            requirement_file.rename(
                requirement_file.parent.joinpath("{}.bak".format(name))
            )
            new_requirements.write_text("\n".join(result))
    return result


@invoke.task
def unpin_and_update_vendored(ctx, vendor=True, patched=False):
    if vendor:
        vendor_file = _get_vendor_dir(ctx) / "vendor.txt"
        unpin_and_copy_requirements(ctx, vendor_file, name="vendor.txt")
    if patched:
        patched_file = _get_patched_dir(ctx) / "patched.txt"
        unpin_and_copy_requirements(ctx, patched_file, name="patched.txt")


@invoke.task(name=TASK_NAME)
def main(ctx, package=None):
    vendor_dir = _get_vendor_dir(ctx)
    patched_dir = _get_patched_dir(ctx)
    log("Using vendor dir: %s" % vendor_dir)
    if package:
        vendor(ctx, vendor_dir, package=package)
        download_licenses(ctx, vendor_dir, package=package)
        log("Vendored %s" % package)
        return
    clean_vendor(ctx, vendor_dir)
    clean_vendor(ctx, patched_dir)
    vendor(ctx, vendor_dir)
    install_pyyaml(ctx, patched_dir)
    vendor(ctx, patched_dir, rewrite=True)
    download_all_licenses(ctx, include_pip=True)
    # from .vendor_passa import vendor_passa
    # log("Vendoring passa...")
    # vendor_passa(ctx)
    # update_safety(ctx)
    log("Revendoring complete")


@invoke.task
def install_yaml(ctx):
    patched_dir = _get_patched_dir(ctx)
    install_pyyaml(ctx, patched_dir)


@invoke.task
def vendor_artifact(ctx, package, version=None):
    simple = requests.get("https://pypi.org/simple/{0}/".format(package))
    pkg_str = "{0}-{1}".format(package, version)
    soup = bs4.BeautifulSoup(simple.content)
    links = [
        a.attrs["href"] for a in soup.find_all("a") if a.getText().startswith(pkg_str)
    ]
    for link in links:
        dest_dir = _get_git_root(ctx) / "tests" / "pypi" / package
        if not dest_dir.exists():
            dest_dir.mkdir()
        _, _, dest_path = urllib3_parse(link).path.rpartition("/")
        dest_file = dest_dir / dest_path
        with io.open(dest_file.as_posix(), "wb") as target_handle:
            with open_file(link) as fp:
                shutil.copyfileobj(fp, target_handle)
