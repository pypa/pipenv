# -*- coding=utf-8 -*-
import datetime
import invoke
import sys
from pipenv.__version__ import __version__
from parver import Version
from .vendoring import _get_git_root, drop_dir


VERSION_FILE = 'pipenv/__version__.py'


def log(msg):
    print('[release] %s' % msg)


def get_version_file(ctx):
    return _get_git_root(ctx).joinpath(VERSION_FILE)


def get_dist_dir(ctx):
    return _get_git_root(ctx) / 'dist'


def get_build_dir(ctx):
    return _get_git_root(ctx) / 'build'


def drop_dist_dirs(ctx):
    log('Dropping Dist dir...')
    drop_dir(get_dist_dir(ctx))
    log('Dropping build dir...')
    drop_dir(get_build_dir(ctx))


@invoke.task
def build_dists(ctx):
    drop_dist_dirs(ctx)
    log('Building sdist using %s ....' % sys.executable)
    for py_version in ['2.7', '3.6']:
        env = {'PIPENV_PYTHON': py_version}
        ctx.run('pipenv install --dev', env=env)
        if py_version == '3.6':
            ctx.run('pipenv run python setup.py sdist', env=env)
        log('Building wheel using python %s ....' % py_version)
        ctx.run('pipenv run python setup.py bdist_wheel', env=env)


@invoke.task(build_dists)
def upload_dists(ctx):
    log('Uploading distributions to pypi...')
    ctx.run('twine upload dist/*')


@invoke.task
def generate_changelog(ctx, commit=False, draft=False):
    log('Generating changelog...')
    if draft:
        commit = False
        log('Writing draft to file...')
        ctx.run('towncrier --draft > CHANGELOG.draft.rst')
    if commit:
        ctx.run('towncrier')
        log('Committing...')
        ctx.run('git add CHANGELOG.rst')
        ctx.run('git commit -m "Update changelog."')


@invoke.task
def tag_version(ctx, push=False):
    version = Version.parse(__version__)
    log('Tagging revision: v%s' % version)
    ctx.run('git tag v%s' % version)
    if push:
        log('Pushing tags...')
        ctx.run('git push --tags')


@invoke.task
def bump_version(ctx, dry_run=False, increment=True, release=False, dev=False, pre=False, tag=None, clear=False, commit=False,):
    current_version = Version.parse(__version__)
    today = datetime.date.today()
    next_month_number = today.month + 1 if today.month != 12 else 1
    next_year_number = today.year if next_month_number != 1 else today.year+1
    next_month = (next_year_number, next_month_number, 0)
    if pre and not tag:
        print('Using "pre" requires a corresponding tag.')
        return
    if release and not dev and not pre:
        new_version = current_version.replace(release=today.timetuple()[:3]).clear(pre=True, dev=True)
    elif release and (dev or pre):
        new_version = current_version.replace(release=today.timetuple()[:3])
        if dev:
            new_version = new_version.bump_dev()
        elif pre:
            new_version = new_version.bump_pre(tag=tag)
    else:
        new_version = current_version.replace(release=next_month)
        if dev:
            new_version = new_version.bump_dev()
        elif pre:
            new_version = new_version.bump_pre(tag=tag)
    if clear:
        new_version = new_version.clear(dev=True, pre=True, post=True)
    log('Updating version to %s' % new_version.normalize())
    version_file = get_version_file(ctx)
    file_contents = version_file.read_text()
    log('Found current version: %s' % __version__)
    if dry_run:
        log('Would update to: %s' % new_version.normalize())
    else:
        log('Updating to: %s' % new_version.normalize())
        version_file.write_text(file_contents.replace(__version__, str(new_version.normalize())))
        if commit:
            log('Committing...')
            ctx.run('git commit -s -m "Bumped version."')
