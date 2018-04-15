# -*- coding=utf-8 -*-
""""Vendoring script, python 3.5 needed"""
# Taken from pip
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/vendoring/__init__.py
from pathlib import Path
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

    # Special cases: apply stored patches
    log("Apply patches")
    patch_dir = Path(__file__).parent / 'patches'
    for patch in patch_dir.glob('*.patch'):
        apply_patch(ctx, patch)


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
    log('Revendoring complete')
