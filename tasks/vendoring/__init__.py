# -*- coding=utf-8 -*-
""""Vendoring script, python 3.5 needed"""
# Taken from pip
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/vendoring/__init__.py
from pathlib import Path
from pipenv._compat import TemporaryDirectory
from pipenv.utils import mkdir_p
# from tempfile import TemporaryDirectory
import tarfile
import zipfile
import os
import re
import shutil
import sys
import invoke
import requests

TASK_NAME = 'update'

LIBRARY_DIRNAMES = {
    'requirements-parser': 'requirements',
    'backports.shutil_get_terminal_size': 'backports/shutil_get_terminal_size',
    'backports.weakref': 'backports/weakref',
    'shutil_backports': 'backports/shutil_get_terminal_size',
    'python-dotenv': 'dotenv',
    'pip-tools': 'piptools',
    'setuptools': 'pkg_resources',
}

# from time to time, remove the no longer needed ones
HARDCODED_LICENSE_URLS = {
    'pytoml': 'https://github.com/avakar/pytoml/raw/master/LICENSE',
    'delegator.py': 'https://raw.githubusercontent.com/kennethreitz/delegator.py/master/LICENSE',
    'click-didyoumean': 'https://raw.githubusercontent.com/click-contrib/click-didyoumean/master/LICENSE',
    'click-completion': 'https://raw.githubusercontent.com/click-contrib/click-completion/master/LICENSE',
    'blindspin': 'https://raw.githubusercontent.com/kennethreitz/delegator.py/master/LICENSE',
    'shutilwhich': 'https://raw.githubusercontent.com/mbr/shutilwhich/master/LICENSE',
    'parse': 'https://raw.githubusercontent.com/techalchemy/parse/master/LICENSE',
    'semver': 'https://raw.githubusercontent.com/k-bx/python-semver/master/LICENSE.txt',
    'crayons': 'https://raw.githubusercontent.com/kennethreitz/crayons/master/LICENSE',
    'pip-tools': 'https://raw.githubusercontent.com/jazzband/pip-tools/master/LICENSE',
    'pew': 'https://raw.githubusercontent.com/berdario/pew/master/LICENSE',
    'pytoml': 'https://github.com/avakar/pytoml/raw/master/LICENSE',
    'webencodings': 'https://github.com/SimonSapin/python-webencodings/raw/'
                    'master/LICENSE',
}

FILE_WHITE_LIST = (
    'Makefile',
    'vendor.txt',
    'patched.txt',
    '__init__.py',
    'README.rst',
    'README.md',
    'appdirs.py',
    'safety.zip',
    'cacert.pem',
    'vendor_pip.txt',
)

LIBRARY_RENAMES = {
    'pip': 'pip9'
}

PATCHED_RENAMES = {
    'pip': 'notpip'
}


def drop_dir(path):
    if path.exists() and path.is_dir():
        shutil.rmtree(str(path))


def remove_all(paths):
    for path in paths:
        if path.is_dir():
            drop_dir(path)
        else:
            path.unlink()


def log(msg):
    print('[vendoring.%s] %s' % (TASK_NAME, msg))


def _get_git_root(ctx):
    return Path(ctx.run('git rev-parse --show-toplevel', hide=True).stdout.strip())


def _get_vendor_dir(ctx):
    return _get_git_root(ctx) / 'pipenv' / 'vendor'


def _get_patched_dir(ctx):
    return _get_git_root(ctx) / 'pipenv' / 'patched'


def clean_vendor(ctx, vendor_dir):
    # Old _vendor cleanup
    remove_all(vendor_dir.glob('*.pyc'))
    log('Cleaning %s' % vendor_dir)
    for item in vendor_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(str(item))
        elif "LICENSE" in item.name or "COPYING" in item.name:
            continue
        elif item.name not in FILE_WHITE_LIST:
            item.unlink()
        else:
            log('Skipping %s' % item)


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
        elif item.name.endswith('.py'):
            rewrite_file_imports(item, vendored_libs, vendor_dir)


def rewrite_file_imports(item, vendored_libs, vendor_dir):
    """Rewrite 'import xxx' and 'from xxx import' for vendored_libs"""
    text = item.read_text(encoding='utf-8')
    renames = PATCHED_RENAMES if vendor_dir.name == 'patched' else LIBRARY_RENAMES
    for k in LIBRARY_RENAMES.keys():
        if k not in vendored_libs:
            vendored_libs.append(k)
    for lib in vendored_libs:
        to_lib = lib
        if lib in renames:
            to_lib = renames[lib]
        text = re.sub(
            r'([\n\s]*)import %s([\n\s\.]+)' % lib,
            r'\1import %s\2' % to_lib,
            text,
        )
        text = re.sub(
            r'([\n\s]*)from %s([\s\.])+' % lib,
            r'\1from %s\2' % to_lib,
            text,
        )
        text = re.sub(
            r"(\n\s*)__import__\('%s([\s'\.])+" % lib,
            r"\1__import__('%s\2" % to_lib,
            text,
        )
    item.write_text(text, encoding='utf-8')


def apply_patch(ctx, patch_file_path):
    log('Applying patch %s' % patch_file_path.name)
    ctx.run('git apply --verbose %s' % patch_file_path)


@invoke.task
def update_safety(ctx):
    ignore_subdeps = ['pip', 'pip-egg-info', 'bin']
    ignore_files = ['pip-delete-this-directory.txt', 'PKG-INFO']
    vendor_dir = _get_patched_dir(ctx)
    log('Using vendor dir: %s' % vendor_dir)
    log('Downloading safety package files...')
    build_dir = vendor_dir / 'build'
    download_dir = TemporaryDirectory(prefix='pipenv-', suffix='-safety')
    if build_dir.exists() and build_dir.is_dir():
        drop_dir(build_dir)

    ctx.run(
        'pip download -b {0} --no-binary=:all: --no-clean -d {1} safety pyyaml'.format(
            str(build_dir), str(download_dir.name),
        )
    )
    safety_dir = build_dir / 'safety'
    yaml_build_dir = build_dir / 'pyyaml'
    main_file = safety_dir / '__main__.py'
    main_content = """
import sys
yaml_lib = 'yaml{0}'.format(sys.version_info[0])
locals()[yaml_lib] = __import__(yaml_lib)
sys.modules['yaml'] = sys.modules[yaml_lib]
from safety.cli import cli

# Disable insecure warnings.
import urllib3
from urllib3.exceptions import InsecureRequestWarning
urllib3.disable_warnings(InsecureRequestWarning)

cli(prog_name="safety")
    """.strip()
    with open(str(main_file), 'w') as fh:
        fh.write(main_content)

    with ctx.cd(str(safety_dir)):
        ctx.run('pip install --no-compile --no-binary=:all: -t . .')
        safety_dir = safety_dir.absolute()
        yaml_dir = safety_dir / 'yaml'
        if yaml_dir.exists():
            version_choices = ['2', '3']
            version_choices.remove(str(sys.version_info[0]))
            mkdir_p(str(safety_dir / 'yaml{0}'.format(sys.version_info[0])))
            for fn in yaml_dir.glob('*.py'):
                fn.rename(str(safety_dir.joinpath('yaml{0}'.format(sys.version_info[0]), fn.name)))
            if version_choices[0] == '2':
                lib = yaml_build_dir / 'lib' / 'yaml'
            else:
                lib = yaml_build_dir / 'lib3' / 'yaml'
            shutil.copytree(str(lib.absolute()), str(safety_dir / 'yaml{0}'.format(version_choices[0])))
        requests_dir = safety_dir / 'requests'
        cacert = vendor_dir / 'requests' / 'cacert.pem'
        if not cacert.exists():
            from pipenv.vendor import requests
            cacert = Path(requests.certs.where())
        target_cert = requests_dir / 'cacert.pem'
        target_cert.write_bytes(cacert.read_bytes())
        ctx.run("sed -i 's/r = requests.get(url=url, timeout=REQUEST_TIMEOUT, headers=headers)/r = requests.get(url=url, timeout=REQUEST_TIMEOUT, headers=headers, verify=False)/g' {0}".format(str(safety_dir / 'safety' / 'safety.py')))
        for egg in safety_dir.glob('*.egg-info'):
            drop_dir(egg.absolute())
        for dep in ignore_subdeps:
            dep_dir = safety_dir / dep
            if dep_dir.exists():
                drop_dir(dep_dir)
        for dep in ignore_files:
            fn = safety_dir / dep
            if fn.exists():
                fn.unlink()
    zip_name = '{0}/safety'.format(str(vendor_dir))
    shutil.make_archive(zip_name, format='zip', root_dir=str(safety_dir), base_dir='./')
    drop_dir(build_dir)
    download_dir.cleanup()


def rename_if_needed(ctx, vendor_dir, item):
    rename_dict = LIBRARY_RENAMES if vendor_dir.name != 'patched' else PATCHED_RENAMES
    new_path = None
    if item.name in rename_dict or item.name in LIBRARY_DIRNAMES:
        new_name = rename_dict.get(item.name, LIBRARY_DIRNAMES.get(item.name))
        new_path = item.parent / new_name
        log('Renaming %s => %s' % (item.name, new_path))
        # handle existing directories
        try:
            item.rename(str(new_path))
        except OSError:
            for child in item.iterdir():
                child.rename(str(new_path / child.name))


def write_backport_imports(ctx, vendor_dir):
    backport_dir = vendor_dir / 'backports'
    if not backport_dir.exists():
        return
    backport_init = backport_dir / '__init__.py'
    backport_libs = detect_vendored_libs(backport_dir)
    init_py_lines = backport_init.read_text().splitlines()
    for lib in backport_libs:
        lib_line = 'from . import {0}'.format(lib)
        if lib_line not in init_py_lines:
            log('Adding backport %s to __init__.py exports' % lib)
            init_py_lines.append(lib_line)
    backport_init.write_text('\n'.join(init_py_lines) + '\n')


def vendor(ctx, vendor_dir, rewrite=True):
    log('Reinstalling vendored libraries')
    is_patched = vendor_dir.name == 'patched'
    requirements_file = vendor_dir.name
    # We use --no-deps because we want to ensure that all of our dependencies
    # are added to vendor.txt, this includes all dependencies recursively up
    # the chain.
    ctx.run(
        'pip install -t {0} -r {0}/{1}.txt --no-compile --no-deps'.format(
            str(vendor_dir),
            requirements_file,
        )
    )
    remove_all(vendor_dir.glob('*.dist-info'))
    remove_all(vendor_dir.glob('*.egg-info'))

    # Cleanup setuptools unneeded parts
    drop_dir(vendor_dir / 'bin')
    drop_dir(vendor_dir / 'tests')

    # Detect the vendored packages/modules
    vendored_libs = detect_vendored_libs(vendor_dir)
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))

    # Apply pre-patches
    log("Applying pre-patches...")
    patch_dir = Path(__file__).parent / 'patches' / vendor_dir.name
    if is_patched:
        for patch in patch_dir.glob('*.patch'):
            if not patch.name.startswith('_post'):
                apply_patch(ctx, patch)

    # Global import rewrites
    log('Renaming specified libs...')
    for item in vendor_dir.iterdir():
        if item.is_dir():
            if item.name == 'requests' and not (item / 'cacert.pem').exists():
                if 'certifi' in vendored_libs:
                    cert = vendor_dir / 'certifi' / 'cacert.pem'
                    copy_to = item / 'cacert.pem'
                    copy_to.write_bytes(cert.read_bytes())
            if rewrite:
                log('Rewriting imports for %s...' % item)
                rewrite_imports(item, vendored_libs, vendor_dir)
            rename_if_needed(ctx, vendor_dir, item)
        elif item.name not in FILE_WHITE_LIST:
            if rewrite:
                rewrite_file_imports(item, vendored_libs, vendor_dir)
    write_backport_imports(ctx, vendor_dir)
    log('Applying post-patches...')
    patches = patch_dir.glob('*.patch' if not is_patched else '_post*.patch')
    for patch in patches:
        apply_patch(ctx, patch)
    if is_patched:
        piptools_vendor = vendor_dir / 'piptools' / '_vendored'
        if piptools_vendor.exists():
            drop_dir(piptools_vendor)


@invoke.task
def rewrite_all_imports(ctx):
    vendor_dir = _get_vendor_dir(ctx)
    log('Using vendor dir: %s' % vendor_dir)
    vendored_libs = detect_vendored_libs(vendor_dir)
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))
    log("Rewriting all imports related to vendored libs")
    for item in vendor_dir.iterdir():
        if item.is_dir():
            rewrite_imports(item, vendored_libs)
        elif item.name not in FILE_WHITE_LIST:
            rewrite_file_imports(item, vendored_libs)


@invoke.task
def download_licenses(ctx, vendor_dir, requirements_file='vendor.txt'):
    log('Downloading licenses')
    if not vendor_dir:
        vendor_dir = _get_vendor_dir(ctx)
    tmp_dir = vendor_dir / '__tmp__'
    ctx.run(
        'pip download -r {0}/{1} --no-binary :all: --no-deps -d {2}'.format(
            str(vendor_dir),
            requirements_file,
            str(tmp_dir),
        )
    )
    for sdist in tmp_dir.iterdir():
        extract_license(vendor_dir, sdist)
    drop_dir(tmp_dir)


def extract_license(vendor_dir, sdist):
    if sdist.stem.endswith('.tar'):
        ext = sdist.suffix[1:]
        with tarfile.open(sdist, mode='r:{}'.format(ext)) as tar:
            found = find_and_extract_license(vendor_dir, tar, tar.getmembers())
    elif sdist.suffix == '.zip':
        with zipfile.ZipFile(sdist) as zip:
            found = find_and_extract_license(vendor_dir, zip, zip.infolist())
    else:
        raise NotImplementedError('new sdist type!')

    if not found:
        log('License not found in {}, will download'.format(sdist.name))
        license_fallback(vendor_dir, sdist.name)


def find_and_extract_license(vendor_dir, tar, members):
    found = False
    for member in members:
        try:
            name = member.name
        except AttributeError:  # zipfile
            name = member.filename
        if 'LICENSE' in name or 'COPYING' in name:
            if '/test' in name:
                # some testing licenses in hml5lib and distlib
                log('Ignoring {}'.format(name))
                continue
            found = True
            extract_license_member(vendor_dir, tar, member, name)
    return found


def license_fallback(vendor_dir, sdist_name):
    """Hardcoded license URLs. Check when updating if those are still needed"""
    libname = libname_from_dir(sdist_name)
    if libname not in HARDCODED_LICENSE_URLS:
        raise ValueError('No hardcoded URL for {} license'.format(libname))

    url = HARDCODED_LICENSE_URLS[libname]
    _, _, name = url.rpartition('/')
    dest = license_destination(vendor_dir, libname, name)
    r = requests.get(url, allow_redirects=True)
    log('Downloading {}'.format(url))
    r.raise_for_status()
    dest.write_bytes(r.content)


def libname_from_dir(dirname):
    """Reconstruct the library name without it's version"""
    parts = []
    for part in dirname.split('-'):
        if part[0].isdigit():
            break
        parts.append(part)
    return '-'.join(parts)


def license_destination(vendor_dir, libname, filename):
    """Given the (reconstructed) library name, find appropriate destination"""
    normal = vendor_dir / libname
    if normal.is_dir():
        return normal / filename
    lowercase = vendor_dir / libname.lower()
    if lowercase.is_dir():
        return lowercase / filename
    rename_dict = LIBRARY_RENAMES if vendor_dir.name != 'patched' else PATCHED_RENAMES
    # Short circuit all logic if we are renaming the whole library
    if libname in rename_dict:
        return vendor_dir / rename_dict[libname] / filename
    if libname in LIBRARY_DIRNAMES:
        override = vendor_dir / LIBRARY_DIRNAMES[libname]
        if not override.exists() and override.parent.exists():
            # for flattened subdeps, specifically backports/weakref.py
            return (
                vendor_dir / override.parent
            ) / '{0}.{1}'.format(override.name, filename)
        return vendor_dir / LIBRARY_DIRNAMES[libname] / filename
    # fallback to libname.LICENSE (used for nondirs)
    return vendor_dir / '{}.{}'.format(libname, filename)


def extract_license_member(vendor_dir, tar, member, name):
    mpath = Path(name)  # relative path inside the sdist
    dirname = list(mpath.parents)[-2].name  # -1 is .
    libname = libname_from_dir(dirname)
    dest = license_destination(vendor_dir, libname, mpath.name)
    log('Extracting {} into {}'.format(name, dest))
    try:
        fileobj = tar.extractfile(member)
        dest.write_bytes(fileobj.read())
    except AttributeError:  # zipfile
        dest.write_bytes(tar.read(member))


@invoke.task()
def generate_patch(ctx, package_path, patch_description, base='HEAD'):
    pkg = Path(package_path)
    if len(pkg.parts) != 2 or pkg.parts[0] not in ('vendor', 'patched'):
        raise ValueError('example usage: generate-patch patched/pew some-description')
    patch_fn = '{0}-{1}.patch'.format(pkg.parts[1], patch_description)
    command = 'git diff {base} -p {root} > {out}'.format(
        base=base,
        root=Path('pipenv').joinpath(pkg),
        out=Path(__file__).parent.joinpath('patches', pkg.parts[0], patch_fn),
    )
    with ctx.cd(str(_get_git_root(ctx))):
        log(command)
        ctx.run(command)


@invoke.task(name=TASK_NAME)
def main(ctx):
    vendor_dir = _get_vendor_dir(ctx)
    patched_dir = _get_patched_dir(ctx)
    log('Using vendor dir: %s' % vendor_dir)
    clean_vendor(ctx, vendor_dir)
    clean_vendor(ctx, patched_dir)
    vendor(ctx, vendor_dir)
    vendor(ctx, patched_dir, rewrite=False)
    download_licenses(ctx, vendor_dir)
    download_licenses(ctx, patched_dir, 'patched.txt')
    for pip_dir in [vendor_dir / 'pip9', patched_dir / 'notpip']:
        _vendor_dir = pip_dir / '_vendor'
        vendor_src_file = vendor_dir / 'vendor_pip.txt'
        vendor_file = _vendor_dir / 'vendor.txt'
        vendor_file.write_bytes(vendor_src_file.read_bytes())
        download_licenses(ctx, _vendor_dir)
    # update_safety(ctx)
    log('Revendoring complete')
