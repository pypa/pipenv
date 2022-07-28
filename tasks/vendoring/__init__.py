# Taken from pip
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/vendoring/__init__.py
""""Vendoring script, python 3.5 needed"""

import itertools
import re
import shutil
import tarfile
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import bs4
import invoke
import requests
from urllib3.util import parse_url as urllib3_parse

TASK_NAME = "update"

LIBRARY_DIRNAMES = {
    "requirements-parser": "requirements",
    "backports.shutil_get_terminal_size": "backports/shutil_get_terminal_size",
    "python-dotenv": "dotenv",
    "setuptools": "pkg_resources",
    "msgpack-python": "msgpack",
    "attrs": "attr",
}

# from time to time, remove the no longer needed ones
HARDCODED_LICENSE_URLS = {
    "cursor": "https://raw.githubusercontent.com/GijsTimmers/cursor/master/LICENSE",
    "CacheControl": "https://raw.githubusercontent.com/ionrock/cachecontrol/master/LICENSE.txt",
    "click-didyoumean": "https://raw.githubusercontent.com/click-contrib/click-didyoumean/master/LICENSE",
    "click-completion": "https://raw.githubusercontent.com/click-contrib/click-completion/master/LICENSE",
    "parse": "https://raw.githubusercontent.com/techalchemy/parse/master/LICENSE",
    "pytoml": "https://github.com/avakar/pytoml/raw/master/LICENSE",
    "webencodings": "https://github.com/SimonSapin/python-webencodings/raw/"
    "master/LICENSE",
    "requirementslib": "https://github.com/techalchemy/requirementslib/raw/master/LICENSE",
    "distlib": "https://github.com/vsajip/distlib/raw/master/LICENSE.txt",
    "pythonfinder": "https://raw.githubusercontent.com/techalchemy/pythonfinder/master/LICENSE.txt",
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

PATCHED_RENAMES = {}

LIBRARY_RENAMES = {
    "pip": "pipenv.patched.pip",
    "pip_shims:": "pipenv.vendor.pip_shims",
    "requests": "pipenv.patched.pip._vendor.requests",
    "packaging": "pipenv.patched.pip._vendor.packaging",
}

GLOBAL_REPLACEMENT = [
    (r"(?<!\.)\bpip\._vendor", r"pipenv.patched.pip._vendor"),
    (r"(?<!\.)\bpip\._internal", r"pipenv.patched.pip._internal"),
    (r"(?<!\.)\bpippipenv\.patched\.notpip", r"pipenv.patched.pip"),
]


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
    print(f"[vendoring.{TASK_NAME}] {msg}")


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


def detect_all_vendored_libs(ctx):
    types = ("patched", "vendor")
    retval = {}

    for type_ in types:
        vendor_dir = _get_vendor_dir(ctx) if type_ == "vendor" else _get_patched_dir(ctx)

        for item in vendor_dir.iterdir():
            name = None
            if item.name == "__pycache__":
                continue
            elif item.is_dir():
                name = item.name
            elif "LICENSE" in item.name or "COPYING" in item.name:
                continue
            elif item.name.endswith(".pyi"):
                continue
            elif item.name not in FILE_WHITE_LIST:
                name = item.name[:-3]
            if name is not None and name not in LIBRARY_RENAMES:
                retval[name] = f"pipenv.{type_}.{name}"
    retval.update(LIBRARY_RENAMES)
    return retval


def detect_vendored_libs(vendor_dir):
    retval = []
    for item in vendor_dir.iterdir():
        if item.name == "__pycache__":
            continue
        elif item.is_dir():
            retval.append(item.name)
        elif "LICENSE" in item.name or "COPYING" in item.name:
            continue
        elif item.name.endswith(".pyi"):
            continue
        elif item.name not in FILE_WHITE_LIST:
            retval.append(item.name[:-3])
    return retval


def rewrite_imports(package_dir, vendored_libs):
    for item in package_dir.iterdir():
        if item.is_dir():
            rewrite_imports(item, vendored_libs)
        elif item.name.endswith(".py"):
            rewrite_file_imports(item, vendored_libs)


def rewrite_file_imports(item, vendored_libs):
    """Rewrite 'import xxx' and 'from xxx import' for vendored_libs"""
    # log('Reading file: %s' % item)
    try:
        text = item.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = item.read_text(encoding="cp1252")

    for lib, to_lib in vendored_libs.items():
        text = re.sub(
            r"^(?m)(\s*)import %s((?:\.\S*)?\s+as)" % lib,
            r"\1import %s\2" % to_lib,
            text,
        )
        text = re.sub(r"^(?m)(\s*)from %s([\s\.]+)" % lib, r"\1from %s\2" % to_lib, text)
        text = re.sub(
            r"^(?m)(\s*)import %s(\s*[,\n#])" % lib,
            r"\1import %s as %s\2" % (to_lib, lib),
            text,
        )
    for pattern, sub in GLOBAL_REPLACEMENT:
        text = re.sub(pattern, sub, text)
    item.write_text(text, encoding="utf-8")


def apply_patch(ctx, patch_file_path):
    log("Applying patch %s" % patch_file_path.name)
    ctx.run("git apply --ignore-whitespace --verbose %s" % patch_file_path)


def _recursive_write_to_zip(zf, path, root=None):
    if path == Path(zf.filename):
        return
    if root is None:
        if not path.is_dir():
            raise ValueError("root is required for non-directory path")
        root = path
    if not path.is_dir():
        zf.write(str(path), str(path.relative_to(root)))
        return
    for c in path.iterdir():
        _recursive_write_to_zip(zf, c, root)


def rename_if_needed(ctx, vendor_dir, item):
    rename_dict = LIBRARY_RENAMES if vendor_dir.name != "patched" else PATCHED_RENAMES
    new_path = None
    if item.name in rename_dict or item.name in LIBRARY_DIRNAMES:
        new_name = rename_dict.get(item.name, LIBRARY_DIRNAMES.get(item.name))
        new_path = item.parent / new_name
        log(f"Renaming {item.name} => {new_path}")
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
        lib_line = f"from . import {lib}"
        if lib_line not in init_py_lines:
            log("Adding backport %s to __init__.py exports" % lib)
            init_py_lines.append(lib_line)
    backport_init.write_text("\n".join(init_py_lines) + "\n")


def _ensure_package_in_requirements(ctx, requirements_file, package):
    requirement = None
    log("using requirements file: %s" % requirements_file)
    req_file_lines = [line for line in requirements_file.read_text().splitlines()]
    if package:
        match = [r for r in req_file_lines if r.strip().lower().startswith(package)]
        matched_req = None
        if match:
            for m in match:
                specifiers = [m.index(s) for s in [">", "<", "=", "~"] if s in m]
                if m.lower() == package or (
                    specifiers and m[: min(specifiers)].lower() == package
                ):
                    matched_req = f"{m}"
                    requirement = matched_req
                    log("Matched req: %r" % matched_req)
        if not matched_req:
            req_file_lines.append(f"{package}")
            log("Writing requirements file: %s" % requirements_file)
            requirements_file.write_text("\n".join(req_file_lines))
            requirement = f"{package}"
    return requirement


def install(ctx, vendor_dir, package=None):
    requirements_file = vendor_dir / f"{vendor_dir.name}.txt"
    requirement = f"-r {requirements_file.as_posix()}"
    log("Using requirements file: %s" % requirement)
    if package:
        requirement = _ensure_package_in_requirements(ctx, requirements_file, package)
    # We use --no-deps because we want to ensure that all of our dependencies
    # are added to vendor.txt, this includes all dependencies recursively up
    # the chain.
    ctx.run(
        "pip install -t {} --no-compile --no-deps --upgrade {}".format(
            vendor_dir.as_posix(),
            requirement,
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
        elif vendor_dir.joinpath(f"{pkg}.py").exists():
            vendor_dir.joinpath(f"{pkg}.LICENSE").write_text(license_file.read_text())
        else:
            pkg = pkg.replace("-", "?").replace("_", "?")
            matched_path = next(iter(pth for pth in vendor_dir.glob(f"{pkg}*")), None)
            if matched_path is not None:
                if matched_path.is_dir():
                    target = vendor_dir.joinpath(matched_path).joinpath("LICENSE")
                else:
                    target = vendor_dir.joinpath(f"{matched_path}.LICENSE")
                target.write_text(license_file.read_text())


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
    vendored_libs = detect_all_vendored_libs(ctx)
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
                rewrite_imports(item, vendored_libs)
            rename_if_needed(ctx, vendor_dir, item)
        elif item.name not in FILE_WHITE_LIST:
            if rewrite and not package or (package and item.stem.lower() in package):
                rewrite_file_imports(item, vendored_libs)
    write_backport_imports(ctx, vendor_dir)
    if not package:
        apply_patches(ctx, patched=is_patched, pre=False)
        if is_patched:
            piptools_vendor = vendor_dir / "piptools" / "_vendored"
            if piptools_vendor.exists():
                drop_dir(piptools_vendor)
            msgpack = vendor_dir / "pip" / "_vendor" / "msgpack"
            if msgpack.exists():
                remove_all(msgpack.glob("*.so"))


@invoke.task
def redo_imports(ctx, library, vendor_dir=None):
    if vendor_dir is None:
        vendor_dir = _get_vendor_dir(ctx)
    else:
        vendor_dir = Path(vendor_dir).absolute()
    log("Using vendor dir: %s" % vendor_dir)
    vendored_libs = detect_all_vendored_libs(ctx)
    item = vendor_dir / library
    library_name = vendor_dir / f"{library}.py"
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))
    log("Rewriting imports for %s..." % item)
    if item.is_dir():
        rewrite_imports(item, vendored_libs)
    else:
        rewrite_file_imports(library_name, vendored_libs)


@invoke.task
def rewrite_all_imports(ctx):
    vendor_dir = _get_vendor_dir(ctx)
    patched_dir = _get_patched_dir(ctx)
    log("Using vendor dir: %s" % vendor_dir)
    vendored_libs = detect_all_vendored_libs(ctx)
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))
    log("Rewriting all imports related to vendored libs")
    for item in itertools.chain(patched_dir.iterdir(), vendor_dir.iterdir()):
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
    for _, req in enumerate(requirements):
        if req.startswith("git+"):
            pkg = req.strip().split("#egg=")[1]
        else:
            pkg = req.strip().split("=")[0]
        possible_pkgs = [pkg, pkg.replace("-", "_")]
        match_found = False
        if pkg in LIBRARY_DIRNAMES:
            possible_pkgs.append(LIBRARY_DIRNAMES[pkg])
        for pkgpath in possible_pkgs:
            pkgpath = vendor_dir.joinpath(pkgpath)
            py_path = pkgpath.parent / f"{pkgpath.stem}.py"
            if pkgpath.exists() and pkgpath.is_dir():
                for license_path in LICENSES:
                    license_path = pkgpath.joinpath(license_path)
                    if license_path.exists():
                        match_found = True
                        # log("%s: Trying path %s... FOUND" % (pkg, license_path))
                        break
            elif pkgpath.exists() or py_path.exists():
                for license_path in LICENSES:
                    license_name = f"{pkgpath.stem}.{license_path}"
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
    import pipenv.vendor.parse as parse

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
    log(requirements)
    tmp_dir = vendor_dir / "__tmp__"
    # TODO: Fix this whenever it gets sorted out (see https://github.com/pypa/pip/issues/5739)
    cmd = "pip download --no-binary :all: --only-binary requests_download --no-deps"
    ctx.run("pip install flit")  # needed for the next step
    for req in requirements:
        exe_cmd = "{} --no-build-isolation -d {} {}".format(cmd, tmp_dir.as_posix(), req)
        try:
            ctx.run(exe_cmd)
        except invoke.exceptions.UnexpectedExit as e:
            if "Disabling PEP 517 processing is invalid" not in e.result.stderr:
                log(f"WARNING: Failed to download license for {req}")
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
                ctx.run(f"pip install {backend}")
            ctx.run(f"{cmd} --no-build-isolation -d {tmp_dir.as_posix()} {req}")
    for sdist in tmp_dir.iterdir():
        extract_license(vendor_dir, sdist)
    drop_dir(tmp_dir)


def extract_license(vendor_dir, sdist):
    if sdist.stem.endswith(".tar"):
        ext = sdist.suffix[1:]
        with tarfile.open(sdist, mode=f"r:{ext}") as tar:
            found = find_and_extract_license(vendor_dir, tar, tar.getmembers())
    elif sdist.suffix in (".zip", ".whl"):
        with zipfile.ZipFile(sdist) as zip:
            found = find_and_extract_license(vendor_dir, zip, zip.infolist())
    else:
        raise NotImplementedError("new sdist type!")

    if not found:
        log(f"License not found in {sdist.name}, will download")
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
                log(f"Ignoring {name}")
                continue
            found = True
            extract_license_member(vendor_dir, tar, member, name)
    return found


def license_fallback(vendor_dir, sdist_name):
    """Hardcoded license URLs. Check when updating if those are still needed"""
    libname = libname_from_dir(sdist_name)
    if libname not in HARDCODED_LICENSE_URLS:
        raise ValueError(f"No hardcoded URL for {libname} license")

    url = HARDCODED_LICENSE_URLS[libname]
    _, _, name = url.rpartition("/")
    dest = license_destination(vendor_dir, libname, name)
    r = requests.get(url, allow_redirects=True, verify=False)
    log(f"Downloading {url}")
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
            return (vendor_dir / override.parent) / "{}.{}".format(
                override.name, filename
            )
        license_path = Path(LIBRARY_DIRNAMES[libname]) / filename
        if license_path.as_posix() in LICENSE_RENAMES:
            return vendor_dir / LICENSE_RENAMES[license_path.as_posix()]
        return vendor_dir / LIBRARY_DIRNAMES[libname] / filename
    # fallback to libname.LICENSE (used for nondirs)
    return vendor_dir / f"{libname}.{filename}"


def extract_license_member(vendor_dir, tar, member, name):
    mpath = Path(name)  # relative path inside the sdist
    dirname = list(mpath.parents)[-2].name  # -1 is .
    libname = libname_from_dir(dirname)
    dest = license_destination(vendor_dir, libname, mpath.name)
    log(f"Extracting {name} into {dest}")
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
        patch_fn = f"{pkg.parts[1]}-{patch_description}.patch"
    else:
        patch_fn = f"{pkg.parts[1]}.patch"
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
    pip_dir = patched_dir / "pip"
    vendor_dir = pip_dir / "_vendor"
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
    tempdir = TemporaryDirectory()
    target = Path(tempdir.name).joinpath("requirements.txt")
    contents = unpin_file(requirement_file.read_text())
    target.write_text(contents)
    env = {
        "PIPENV_IGNORE_VIRTUALENVS": "1",
        "PIPENV_NOSPIN": "1",
        "PIPENV_PYTHON": "3.6",
    }
    with ctx.cd(tempdir.name):
        ctx.run(f"pipenv install -r {target.as_posix()}", env=env, hide=True)
        result = ctx.run("pipenv lock -r", env=env, hide=True).stdout.strip()
        ctx.run("pipenv --rm", env=env, hide=True)
        result = list(sorted(line.strip() for line in result.splitlines()[1:]))
        new_requirements = requirement_file.parent.joinpath(name)
        requirement_file.rename(requirement_file.parent.joinpath(f"{name}.bak"))
        new_requirements.write_text("\n".join(result))
    return result


@invoke.task
def update_safety(ctx):
    """This used to be a thing. It was removed by frostming.
    It was doing a whole lot of other things besides updating safety.
    """
    pass


@invoke.task
def unpin_and_update_vendored(ctx, vendor=False, patched=True):
    if vendor:
        vendor_file = _get_vendor_dir(ctx) / "vendor.txt"
        unpin_and_copy_requirements(ctx, vendor_file, name="vendor.txt")
    if patched:
        patched_file = _get_patched_dir(ctx) / "patched.txt"
        unpin_and_copy_requirements(ctx, patched_file, name="patched.txt")


@invoke.task(name=TASK_NAME)
def main(ctx, package=None, type=None):
    vendor_dir = _get_vendor_dir(ctx)
    patched_dir = _get_patched_dir(ctx)
    if type == "vendor":
        target_dirs = [vendor_dir]
    elif type == "patched":
        target_dirs = [patched_dir]
    else:
        target_dirs = [vendor_dir, patched_dir]
    if package:
        if type is None or type == "vendor":
            log("Using vendor dir: %s" % vendor_dir)
            vendor(ctx, vendor_dir, package=package)
            download_licenses(ctx, vendor_dir, package=package)
        elif type == "patched":
            log("Using patched dir: %s" % patched_dir)
            vendor(ctx, patched_dir, package=package)
            download_licenses(ctx, patched_dir, package=package)
        log("Vendored %s" % package)
        return
    for package_dir in target_dirs:
        clean_vendor(ctx, package_dir)
        if package_dir == patched_dir:
            vendor(ctx, patched_dir, rewrite=True)
        else:
            vendor(ctx, package_dir)
        req_txt = "vendor.txt" if package_dir == vendor_dir else "patched.txt"
        download_licenses(ctx, package_dir, req_txt)
        if package_dir == patched_dir:
            update_pip_deps(ctx)
    log("Revendoring complete")


@invoke.task
def vendor_artifact(ctx, package, version=None):
    from pipenv.vendor.vistir.contextmanagers import open_file

    simple = requests.get(f"https://pypi.org/simple/{package}/")
    pkg_str = f"{package}-{version}"
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
        with open(dest_file.as_posix(), "wb") as target_handle:
            with open_file(link) as fp:
                shutil.copyfileobj(fp, target_handle)
