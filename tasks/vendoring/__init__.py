# -*- coding=utf-8 -*-
""""Vendoring script, python 3.5 needed"""
# Taken from pip
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/vendoring/__init__.py
from pathlib import Path
from pipenv.utils import TemporaryDirectory, mkdir_p
import os
import re
import shutil
import invoke

TASK_NAME = 'update'

FILE_WHITE_LIST = (
    'Makefile',
    'vendor.txt',
    '__init__.py',
    'README.rst',
    'LICENSE*',
    'appdirs.py',
    '*.LICENSE'
)

FLATTEN = (
    'click-completion',
    'delegator',
    'docopt',
    'first',
    'parse',
    'pathlib2',
    'pipdeptree',
    'semver',
    'six',
    'toml',
)


def drop_dir(path):
    shutil.rmtree(str(path))


def remove_all(paths):
    for path in paths:
        if path.is_dir():
            drop_dir(path)
        else:
            path.unlink()


def log(msg):
    print('[vendoring.%s] %s' % (TASK_NAME, msg))


def _get_vendor_dir(ctx):
    git_root = ctx.run('git rev-parse --show-toplevel', hide=True).stdout
    return Path(git_root.strip()) / 'pipenv' / 'vendor'


def _get_patched_dir(ctx):
    git_root = ctx.run('git rev-parse --show-toplevel', hide=True).stdout
    return Path(git_root.strip()) / 'pipenv' / 'patched'


def clean_vendor(ctx, vendor_dir):
    # Old _vendor cleanup
    remove_all(vendor_dir.glob('*.pyc'))
    log('Cleaning %s' % vendor_dir)
    for item in vendor_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(str(item))
        elif item.name not in FILE_WHITE_LIST:
            item.unlink()
        else:
            log('Skipping %s' % item)


def detect_vendored_libs(vendor_dir):
    retval = []
    for item in vendor_dir.iterdir():
        if item.is_dir():
            retval.append(item.name)
        elif item.name.endswith(".pyi"):
            continue
        elif item.name not in FILE_WHITE_LIST:
            retval.append(item.name[:-3])
    return retval


def rewrite_imports(package_dir, vendored_libs):
    for item in package_dir.iterdir():
        if item.is_dir():
            rewrite_imports(item, vendored_libs)
        elif item.name.endswith('.py'):
            rewrite_file_imports(item, vendored_libs)


def rewrite_file_imports(item, vendored_libs):
    """Rewrite 'import xxx' and 'from xxx import' for vendored_libs"""
    text = item.read_text(encoding='utf-8')
    for lib in vendored_libs:
        text = re.sub(
            r'(\n\s*)import %s(\n\s*)' % lib,
            r'\1from .vendor import %s\2' % lib,
            text,
        )
        text = re.sub(
            r'(\n\s*)from %s' % lib,
            r'\1from .vendor.%s' % lib,
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
        'pip download -b {0} --no-binary=:all: --no-clean -d {1} safety'.format(
            str(build_dir), str(download_dir.name),
        )
    )
    safety_dir = build_dir / 'safety'
    main_file = safety_dir / '__main__.py'
    main_content = """
from safety.cli import cli

# Disable insecure warnings.
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

cli(prog_name="safety")
    """.strip()
    with open(str(main_file), 'w') as fh:
        fh.write(main_content)

    with ctx.cd(str(safety_dir)):
        ctx.run('pip install --no-compile --no-binary=:all: -t . .')
        safety_dir = safety_dir.absolute()
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


@invoke.task
def get_licenses(ctx):
    vendor_dir = _get_vendor_dir(ctx)
    log('Using vendor dir: %s' % vendor_dir)
    log('Downloading LICENSE files...')
    build_dir = vendor_dir / 'build'
    download_dir = TemporaryDirectory(prefix='pipenv-', suffix='-licenses')
    if build_dir.exists() and build_dir.is_dir():
        drop_dir(build_dir)

    ctx.run(
        'pip download -b {0} --no-binary=:all: --no-clean --no-deps -r {1}/vendor.txt -d {2}'.format(
            str(build_dir), str(vendor_dir), str(download_dir.name),
        )
    )
    for p in build_dir.glob('*/*LICENSE*'):
        parent = p.parent
        matches = [flat for flat in FLATTEN if parent.joinpath(flat).exists() or parent.name == flat]
        egg_info_dir = [e for e in parent.glob('*.egg-info')]
        if any(matches):
            from pipenv.utils import pep423_name
            pkg = pep423_name(matches[0]).lower()                        
            pkg_name = pkg if parent.joinpath(pkg).exists() else parent.name.lower()
            target_file = '{0}.LICENSE'.format(pkg_name)
            target_file = vendor_dir / target_file
        elif egg_info_dir:
            egg_info_dir = egg_info_dir[0]
            pkg_name = egg_info_dir.stem.lower()
            target_file = vendor_dir / pkg_name / p.name.lower()
            if '.' in pkg_name:
                target_file = vendor_dir.joinpath(*pkg_name.split('.')) / p.name
        else:
            target_dir = vendor_dir / parent.name
            if '.' in parent.name:
                target_dir = vendor_dir.joinpath(*parent.name.split('.'))
            target_file = target_dir / p.name.lower()
        mkdir_p(str(target_file.parent.absolute()))
        shutil.copyfile(str(p.absolute()), str(target_file.absolute()))
    drop_dir(build_dir)
    download_dir.cleanup()


def get_patched(ctx):
    log('Reinstalling patched libraries')
    patched_dir = _get_patched_dir(ctx)
    ctx.run(
        'pip install -t {0} -r {0}/patched.txt --no-compile --no-deps'.format(
            str(patched_dir),
        )
    )
    remove_all(patched_dir.glob('*.dist_info'))
    remove_all(patched_dir.glob('*.egg-info'))
    # Cleanup setuptools unneeded parts
    (patched_dir / 'easy_install.py').unlink()
    drop_dir(patched_dir / 'setuptools')
    drop_dir(patched_dir / 'pkg_resources' / '_vendor')
    drop_dir(patched_dir / 'pkg_resources' / 'extern')

    # Drop interpreter and OS specific msgpack libs.
    # Pip will rely on the python-only fallback instead.
    remove_all(patched_dir.glob('msgpack/*.so'))
    drop_dir(patched_dir / 'bin')
    drop_dir(patched_dir / 'tests')

    # Detect the vendored packages/modules
    vendored_libs = detect_vendored_libs(patched_dir)
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))

    # Global import rewrites
    log("Rewriting all imports related to vendored libs")
    for item in patched_dir.iterdir():
        if item.is_dir():
            rewrite_imports(item, vendored_libs)
        elif item.name not in FILE_WHITE_LIST:
            rewrite_file_imports(item, vendored_libs)

    # Special cases: apply stored patches
    log("Apply patches")
    patch_dir = Path(__file__).parent / 'patches'
    for patch in patch_dir.glob('*.patch'):
        apply_patch(ctx, patch)


def vendor(ctx, vendor_dir):
    log('Reinstalling vendored libraries')
    # We use --no-deps because we want to ensure that all of our dependencies
    # are added to vendor.txt, this includes all dependencies recursively up
    # the chain.
    ctx.run(
        'pip install -t {0} -r {0}/vendor.txt --no-compile --no-deps'.format(
            str(vendor_dir),
        )
    )
    remove_all(vendor_dir.glob('*.dist-info'))
    remove_all(vendor_dir.glob('*.egg-info'))

    # Cleanup setuptools unneeded parts
    (vendor_dir / 'easy_install.py').unlink()
    drop_dir(vendor_dir / 'setuptools')
    drop_dir(vendor_dir / 'pkg_resources' / '_vendor')
    drop_dir(vendor_dir / 'pkg_resources' / 'extern')

    # Drop interpreter and OS specific msgpack libs.
    # Pip will rely on the python-only fallback instead.
    remove_all(vendor_dir.glob('msgpack/*.so'))
    drop_dir(vendor_dir / 'bin')
    drop_dir(vendor_dir / 'tests')

    # Detect the vendored packages/modules
    vendored_libs = detect_vendored_libs(vendor_dir)
    log("Detected vendored libraries: %s" % ", ".join(vendored_libs))

    # Global import rewrites
    log("Rewriting all imports related to vendored libs")
    for item in vendor_dir.iterdir():
        if item.is_dir():
            rewrite_imports(item, vendored_libs)
        elif item.name not in FILE_WHITE_LIST:
            rewrite_file_imports(item, vendored_libs)


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
def update_stubs(ctx):
    vendor_dir = _get_vendor_dir(ctx)
    vendored_libs = detect_vendored_libs(vendor_dir)

    print("[vendoring.update_stubs] Add mypy stubs")

    extra_stubs_needed = {
        # Some projects need stubs other than a simple <name>.pyi
        "six": ["six.__init__", "six.moves"],
        # Some projects should not have stubs coz they're single file modules
        "appdirs": [],
    }

    for lib in vendored_libs:
        if lib not in extra_stubs_needed:
            (vendor_dir / (lib + ".pyi")).write_text("from %s import *" % lib)
            continue

        for selector in extra_stubs_needed[lib]:
            fname = selector.replace(".", os.sep) + ".pyi"
            if selector.endswith(".__init__"):
                selector = selector[:-9]

            f_path = vendor_dir / fname
            if not f_path.parent.exists():
                f_path.parent.mkdir()
            f_path.write_text("from %s import *" % selector)


@invoke.task(name=TASK_NAME, post=[update_stubs])
def main(ctx):
    vendor_dir = _get_vendor_dir(ctx)
    log('Using vendor dir: %s' % vendor_dir)
    clean_vendor(ctx, vendor_dir)
    vendor(ctx, vendor_dir)
    get_licenses(ctx)
    update_safety(ctx)
    log('Revendoring complete')
