# -*- coding=utf-8 -*-
import datetime
import os
import pathlib
import re
import sys

import invoke

from parver import Version
from towncrier._builder import (
    find_fragments, render_fragments, split_fragments
)
from towncrier._settings import load_config

from pipenv.__version__ import __version__
from pipenv.vendor.vistir.contextmanagers import temp_environ

from .vendoring import _get_git_root, drop_dir


VERSION_FILE = 'pipenv/__version__.py'
ROOT = pathlib.Path(".").parent.parent.absolute()
PACKAGE_NAME = "pipenv"


def log(msg):
    print('[release] %s' % msg)


def get_version_file(ctx):
    return _get_git_root(ctx).joinpath(VERSION_FILE)


def find_version(ctx):
    version_file = get_version_file(ctx).read_text()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


def get_history_file(ctx):
    return _get_git_root(ctx).joinpath('HISTORY.txt')


def get_dist_dir(ctx):
    return _get_git_root(ctx) / 'dist'


def get_build_dir(ctx):
    return _get_git_root(ctx) / 'build'


def _render_log():
    """Totally tap into Towncrier internals to get an in-memory result.
    """
    config = load_config(ROOT)
    definitions = config['types']
    fragments, fragment_filenames = find_fragments(
        pathlib.Path(config['directory']).absolute(),
        config['sections'],
        None,
        definitions,
    )
    rendered = render_fragments(
        pathlib.Path(config['template']).read_text(encoding='utf-8'),
        config['issue_format'],
        split_fragments(fragments, definitions),
        definitions,
        config['underlines'][1:],
        False,  # Don't add newlines to wrapped text.
    )
    return rendered


@invoke.task
def release(ctx, dry_run=False):
    drop_dist_dirs(ctx)
    bump_version(ctx, dry_run=dry_run)
    version = find_version(ctx)
    tag_content = _render_log()
    if dry_run:
        ctx.run('towncrier --draft > CHANGELOG.draft.rst')
        log('would remove: news/*')
        log('would remove: CHANGELOG.draft.rst')
        log(f'Would commit with message: "Release v{version}"')
    else:
        ctx.run('towncrier')
        ctx.run("git add CHANGELOG.rst news/ {0}".format(get_version_file(ctx).as_posix()))
        ctx.run("git rm CHANGELOG.draft.rst")
        ctx.run(f'git commit -m "Release v{version}"')

    tag_content = tag_content.replace('"', '\\"')
    if dry_run:
        log(f"Generated tag content: {tag_content}")
        markdown = ctx.run("pandoc CHANGELOG.draft.rst -f rst -t markdown", hide=True).stdout.strip()
        content = clean_mdchangelog(ctx, markdown)
        log(f"would generate markdown: {content}")
    else:
        generate_markdown(ctx)
        clean_mdchangelog(ctx)
        ctx.run(f'git tag -a v{version} -m "Version v{version}\n\n{tag_content}"')
    build_dists(ctx)
    if dry_run:
        dist_pattern = f'{PACKAGE_NAME.replace("-", "[-_]")}-*'
        artifacts = list(ROOT.joinpath('dist').glob(dist_pattern))
        filename_display = '\n'.join(f'  {a}' for a in artifacts)
        log(f"Would upload dists: {filename_display}")
    else:
        upload_dists(ctx)
        bump_version(ctx, dev=True)


def drop_dist_dirs(ctx):
    log('Dropping Dist dir...')
    drop_dir(get_dist_dir(ctx))
    log('Dropping build dir...')
    drop_dir(get_build_dir(ctx))


@invoke.task
def build_dists(ctx):
    drop_dist_dirs(ctx)
    for py_version in ['3.6', '2.7']:
        env = {'PIPENV_PYTHON': py_version}
        with ctx.cd(ROOT.as_posix()), temp_environ():
            executable = ctx.run("python -c 'import sys; print(sys.executable)'", hide=True).stdout.strip()
            log('Building sdist using %s ....' % executable)
            os.environ["PIPENV_PYTHON"] = py_version
            ctx.run('pipenv install --dev', env=env)
            ctx.run('pipenv run pip install -e . --upgrade --upgrade-strategy=eager --no-use-pep517', env=env)
            log('Building wheel using python %s ....' % py_version)
            if py_version == '3.6':
                ctx.run('pipenv run python setup.py sdist bdist_wheel', env=env)
            else:
                ctx.run('pipenv run python setup.py bdist_wheel', env=env)


@invoke.task(build_dists)
def upload_dists(ctx, repo="pypi"):
    dist_pattern = f'{PACKAGE_NAME.replace("-", "[-_]")}-*'
    artifacts = list(ROOT.joinpath('dist').glob(dist_pattern))
    filename_display = '\n'.join(f'  {a}' for a in artifacts)
    print(f'[release] Will upload:\n{filename_display}')
    try:
        input('[release] Release ready. ENTER to upload, CTRL-C to abort: ')
    except KeyboardInterrupt:
        print('\nAborted!')
        return

    arg_display = ' '.join(f'"{n}"' for n in artifacts)
    ctx.run(f'twine upload --repository="{repo}" {arg_display}')



@invoke.task
def generate_markdown(ctx):
    log('Generating markdown from changelog...')
    ctx.run('pandoc CHANGELOG.rst -f rst -t markdown -o CHANGELOG.md')


@invoke.task
def generate_changelog(ctx, commit=False, draft=False):
    log('Generating changelog...')
    if draft:
        commit = False
        log('Writing draft to file...')
        ctx.run('towncrier --draft > CHANGELOG.draft.rst')
    else:
        ctx.run('towncrier')
    if commit:
        log('Committing...')
        ctx.run('git add CHANGELOG.rst')
        ctx.run('git rm CHANGELOG.draft.rst')
        ctx.run('git commit -m "Update changelog."')


@invoke.task
def clean_mdchangelog(ctx, content=None):
    changelog = None
    if not content:
        changelog = _get_git_root(ctx) / "CHANGELOG.md"
        content = changelog.read_text()
    content = re.sub(r"([^\n]+)\n?\s+\[[\\]+(#\d+)\]\(https://github\.com/pypa/[\w\-]+/issues/\d+\)", r"\1 \2", content, flags=re.MULTILINE)
    if changelog:
        changelog.write_text(content)
    else:
        return content


@invoke.task
def tag_version(ctx, push=False):
    version = find_version(ctx)
    version = Version.parse(version)
    log('Tagging revision: v%s' % version.normalize())
    ctx.run('git tag v%s' % version.normalize())
    if push:
        log('Pushing tags...')
        ctx.run('git push origin master')
        ctx.run('git push --tags')


@invoke.task
def bump_version(ctx, dry_run=False, dev=False, pre=False, tag=None, commit=False):
    current_version = Version.parse(__version__)
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    next_month = datetime.date.today().replace(month=today.month+1, day=1)
    next_year =  datetime.date.today().replace(year=today.year+1, month=1, day=1)
    if pre and not tag:
        print('Using "pre" requires a corresponding tag.')
        return
    if not (dev or pre or tag):
        new_version = current_version.replace(release=today.timetuple()[:3]).clear(pre=True, dev=True)
    if pre and dev:
        raise RuntimeError("Can't use 'pre' and 'dev' together!")
    if dev or pre:
        new_version = current_version.replace(release=tomorrow.timetuple()[:3]).clear(pre=True, dev=True)
        if dev:
            new_version = new_version.bump_dev()
        else:
            new_version = new_version.bump_pre(tag=tag)
    log('Updating version to %s' % new_version.normalize())
    version = find_version(ctx)
    log('Found current version: %s' % version)
    if dry_run:
        log('Would update to: %s' % new_version.normalize())
    else:
        log('Updating to: %s' % new_version.normalize())
        version_file = get_version_file(ctx)
        file_contents = version_file.read_text()
        version_file.write_text(file_contents.replace(version, str(new_version.normalize())))
        if commit:
            ctx.run('git add {0}'.format(version_file.as_posix()))
            log('Committing...')
            ctx.run('git commit -s -m "Bumped version."')
