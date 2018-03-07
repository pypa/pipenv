# -*- coding: utf-8 -*-

import contextlib
import codecs
import logging
import os
import sys
import shutil
import shlex
import signal
import time
import tempfile
from glob import glob
import json as simplejson

import background
import click
import click_completion
import crayons
import dotenv
import delegator
import pexpect
import requests
import pipfile
import pipdeptree
import semver
from pipreqs import pipreqs
from blindspin import spinner

from requests.packages import urllib3
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from .project import Project
from .utils import (
    convert_deps_from_pip, convert_deps_to_pip, is_required_version,
    proper_case, pep423_name, split_file, merge_deps, venv_resolve_deps, shellquote, is_vcs,
    python_version, find_windows_executable, is_file, prepare_pip_source_args,
    temp_environ, is_valid_url, download_file, get_requirement, need_update_check,
    touch_update_stamp, is_pinned, is_star, TemporaryDirectory
)
from .__version__ import __version__
from . import pep508checker, progress
from .environments import (
    PIPENV_COLORBLIND, PIPENV_NOSPIN, PIPENV_SHELL_FANCY,
    PIPENV_VENV_IN_PROJECT, PIPENV_TIMEOUT, PIPENV_SKIP_VALIDATION,
    PIPENV_HIDE_EMOJIS, PIPENV_INSTALL_TIMEOUT, PYENV_ROOT,
    PYENV_INSTALLED, PIPENV_YES, PIPENV_DONT_LOAD_ENV,
    PIPENV_DEFAULT_PYTHON_VERSION, PIPENV_MAX_SUBPROCESS,
    PIPENV_DONT_USE_PYENV, SESSION_IS_INTERACTIVE, PIPENV_USE_SYSTEM,
    PIPENV_DOTENV_LOCATION, PIPENV_SHELL
)

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from backports.shutil_get_terminal_size import get_terminal_size
else:
    from shutil import get_terminal_size

# Packages that should be ignored later.
BAD_PACKAGES = (
    'setuptools', 'pip', 'wheel', 'six', 'packaging', 'distribute'
    'pyparsing', 'appdirs',
)

# Are we using the default Python?
USING_DEFAULT_PYTHON = True

if not PIPENV_HIDE_EMOJIS:
    now = time.localtime()

    # Halloween easter-egg.
    if ((now.tm_mon == 10) and (now.tm_mday == 30)) or ((now.tm_mon == 10) and (now.tm_mday == 31)):
        INSTALL_LABEL = '🎃   '

    # Christmas easter-egg.
    elif ((now.tm_mon == 12) and (now.tm_mday == 24)) or ((now.tm_mon == 12) and (now.tm_mday == 25)):
        INSTALL_LABEL = '🎅   '

    else:
        INSTALL_LABEL = '🐍   '

    INSTALL_LABEL2 = crayons.normal('☤  ', bold=True)
    STARTING_LABEL = '    '
else:
    INSTALL_LABEL = '   '
    INSTALL_LABEL2 = '   '
    STARTING_LABEL = '   '

# Enable shell completion.
click_completion.init()

# Disable colors, for the soulless.
if PIPENV_COLORBLIND:
    crayons.disable()

# Disable spinner, for cleaner build logs (the unworthy).
if PIPENV_NOSPIN:
    @contextlib.contextmanager  # noqa: F811
    def spinner():
        yield


def which(command, location=None, allow_global=False):
    if location is None:
        location = project.virtualenv_location

    if not allow_global:
        if os.name == 'nt':
            p = find_windows_executable(os.path.join(location, 'Scripts'), command)
        else:
            p = os.sep.join([location] + ['bin/{0}'.format(command)])
    else:
        if command == 'python':
            p = sys.executable

    return p


# Disable warnings for Python 2.6.
if 'urllib3' in globals():
    urllib3.disable_warnings(InsecureRequestWarning)

project = Project(which=which)


def load_dot_env():
    """Loads .env file into sys.environ."""
    if not PIPENV_DONT_LOAD_ENV:
        # If the project doesn't exist yet, check current directory for a .env file
        project_directory = project.project_directory or '.'

        denv = dotenv.find_dotenv(PIPENV_DOTENV_LOCATION or os.sep.join([project_directory, '.env']))
        if os.path.isfile(denv):
            click.echo(crayons.normal('Loading .env environment variables…', bold=True), err=True)
        dotenv.load_dotenv(denv, override=True)


def add_to_path(p):
    """Adds a given path to the PATH."""
    if p not in os.environ['PATH']:
        os.environ['PATH'] = '{0}{1}{2}'.format(p, os.pathsep, os.environ['PATH'])


@background.task
def check_for_updates():
    """Background thread -- beautiful, isn't it?"""
    try:
        touch_update_stamp()
        r = requests.get('https://pypi.python.org/pypi/pipenv/json', timeout=0.5)
        latest = max(map(semver.parse_version_info, r.json()['releases'].keys()))
        current = semver.parse_version_info(__version__)

        if latest > current:
            click.echo('{0}: {1} is now available. You get bonus points for upgrading ($ {})!'.format(
                crayons.green('Courtesy Notice'),
                crayons.yellow('Pipenv {v.major}.{v.minor}.{v.patch}'.format(v=latest)),
                crayons.red('pipenv --update')
            ), err=True)
    except Exception:
        pass


def ensure_latest_self(user=False):
    """Updates Pipenv to latest version, cleverly."""
    touch_update_stamp()
    try:
        r = requests.get('https://pypi.python.org/pypi/pipenv/json', timeout=2)
    except requests.RequestException as e:
        click.echo(crayons.red(e))
        sys.exit(1)
    latest = max(map(semver.parse_version_info, r.json()['releases'].keys()))
    current = semver.parse_version_info(__version__)

    if current < latest:

        import site

        click.echo('{0}: {1} is now available. Automatically upgrading!'.format(
            crayons.green('Courtesy Notice'),
            crayons.yellow('Pipenv {v.major}.{v.minor}.{v.patch}'.format(v=latest)),
        ), err=True)

        # Resolve user site, enable user mode automatically.
        if site.ENABLE_USER_SITE and site.USER_SITE in sys.modules['pipenv'].__file__:
            args = ['install', '--user', '--upgrade', 'pipenv', '--no-cache']
        else:
            args = ['install', '--upgrade', 'pipenv', '--no-cache']

        os.environ['PIP_PYTHON_VERSION'] = str('.'.join(map(str, sys.version_info[:3])))
        os.environ['PIP_PYTHON_PATH'] = str(sys.executable)

        sys.modules['pip'].main(args)

        click.echo('{0} to {1}!'.format(
            crayons.green('Pipenv updated'),
            crayons.yellow('{v.major}.{v.minor}.{v.patch}'.format(v=latest))
        ))
    else:
        click.echo(crayons.green('All good!'))


def cleanup_virtualenv(bare=True):
    """Removes the virtualenv directory from the system."""

    if not bare:
        click.echo(crayons.red('Environment creation aborted.'))

    try:
        # Delete the virtualenv.
        shutil.rmtree(project.virtualenv_location, ignore_errors=True)
    except OSError as e:
        click.echo(e)


def ensure_latest_pip():
    """Updates pip to the latest version."""

    # Ensure that pip is installed.
    try:
        c = delegator.run('"{0}" install pip'.format(which_pip()))

        # Check if version is out of date.
        if 'however' in c.err:
            # If version is out of date, update.
            click.echo(crayons.normal(u'Pip is out of date… updating to latest.', bold=True))

            windows = '-m' if os.name == 'nt' else ''

            c = delegator.run('"{0}" install {1} pip --upgrade'.format(which_pip(), windows), block=False)
            click.echo(crayons.blue(c.out))
    except AttributeError:
        pass


def import_requirements(r=None, dev=False):
    import pip
    from pip.req.req_file import parse_requirements
    # Parse requirements.txt file with Pip's parser.
    # Pip requires a `PipSession` which is a subclass of requests.Session.
    # Since we're not making any network calls, it's initialized to nothing.

    if r:
        assert os.path.isfile(r)

    # Default path, if none is provided.
    if r is None:
        r = project.requirements_location

    with open(r, 'r') as f:
        contents = f.read()

    indexes = []
    # Find and add extra indexes.
    for line in contents.split('\n'):
        if line.startswith(('-i ', '--index ', '--index-url ')):
            indexes.append(line.split()[1])

    reqs = [f for f in parse_requirements(r, session=pip._vendor.requests)]

    for package in reqs:
        if package.name not in BAD_PACKAGES:
            if package.link is not None:
                package_string = (
                    '-e {0}'.format(
                        package.link
                    ) if package.editable else str(package.link)
                )
                project.add_package_to_pipfile(package_string, dev=dev)
            else:
                project.add_package_to_pipfile(str(package.req), dev=dev)

    for index in indexes:
        project.add_index_to_pipfile(index)

    project.recase_pipfile()


def ensure_environment():
    # Skip this on Windows...
    if os.name != 'nt':
        if 'LANG' not in os.environ:
            click.echo(
                '{0}: the environment variable {1} is not set!'
                '\nWe recommend setting this in {2} (or equivalent) for '
                'proper expected behavior.'.format(
                    crayons.red('Warning', bold=True),
                    crayons.normal('LANG', bold=True),
                    crayons.green('~/.profile')
                ), err=True
            )


def import_from_code(path='.'):
    rs = []
    try:
        for r in pipreqs.get_all_imports(path):
            if r not in BAD_PACKAGES:
                rs.append(r)
        pkg_names = pipreqs.get_pkg_names(rs)
        return [proper_case(r) for r in pkg_names]
    except Exception:
        return []


def ensure_pipfile(validate=True, skip_requirements=False):
    """Creates a Pipfile for the project, if it doesn't exist."""

    global USING_DEFAULT_PYTHON

    # Assert Pipfile exists.
    if project.pipfile_is_empty:

        # If there's a requirements file, but no Pipfile...
        if project.requirements_exists and not skip_requirements:
            click.echo(crayons.normal(u'requirements.txt found, instead of Pipfile! Converting…', bold=True))

            # Create a Pipfile...
            python = which('python') if not USING_DEFAULT_PYTHON else None
            project.create_pipfile(python=python)

            with spinner():
                # Import requirements.txt.
                import_requirements()

            # Warn the user of side-effects.
            click.echo(
                u'{0}: Your {1} now contains pinned versions, if your {2} did. \n'
                'We recommend updating your {1} to specify the {3} version, instead.'
                ''.format(
                    crayons.red('Warning', bold=True),
                    crayons.normal('Pipfile', bold=True),
                    crayons.normal('requirements.txt', bold=True),
                    crayons.normal('"*"', bold=True)
                )
            )

        else:
            click.echo(crayons.normal(u'Creating a Pipfile for this project…', bold=True), err=True)

            # Create the pipfile if it doesn't exist.
            python = which('python') if not USING_DEFAULT_PYTHON else False
            project.create_pipfile(python=python)

    # Validate the Pipfile's contents.
    if validate and project.virtualenv_exists and not PIPENV_SKIP_VALIDATION:
        # Ensure that Pipfile is using proper casing.
        p = project.parsed_pipfile
        changed = ensure_proper_casing(pfile=p)

        # Write changes out to disk.
        if changed:
            click.echo(crayons.normal(u'Fixing package names in Pipfile…', bold=True), err=True)
            project.write_toml(p)


def find_a_system_python(python):
    """Finds a system python, given a version (e.g. 2 / 2.7 / 3.6.2), or a full path."""
    if python.startswith('py'):
        return system_which(python)
    elif os.path.isabs(python):
        return python
    else:
        possibilities = [
            'python',
            'python{0}'.format(python[0]),
        ]
        if len(python) >= 2:
            possibilities.extend(
                [
                    'python{0}{1}'.format(python[0], python[2]),
                    'python{0}.{1}'.format(python[0], python[2]),
                    'python{0}.{1}m'.format(python[0], python[2])
                ]
            )

        # Reverse the list, so we find specific ones first.
        possibilities = reversed(possibilities)

        for possibility in possibilities:
            # Windows compatibility.
            if os.name == 'nt':
                possibility = '{0}.exe'.format(possibility)

            pythons = system_which(possibility, mult=True)

            for p in pythons:
                version = python_version(p)
                if (version or '').startswith(python):
                    return p


def ensure_python(three=None, python=None):

    def abort():
        click.echo(
            'You can specify specific versions of Python with:\n  {0}'.format(
                crayons.red('$ pipenv --python {0}'.format(os.sep.join(('path', 'to', 'python'))))
            ), err=True
        )
        sys.exit(1)

    def activate_pyenv():
        import pip
        """Adds all pyenv installations to the PATH."""
        if PYENV_INSTALLED:
            if PYENV_ROOT:
                pyenv_paths = {}
                for found in glob(
                    '{0}{1}versions{1}*'.format(
                        PYENV_ROOT,
                        os.sep
                    )
                ):
                    pyenv_paths[os.path.split(found)[1]] = '{0}{1}bin'.format(found, os.sep)

                for version_str, pyenv_path in pyenv_paths.items():
                    version = pip._vendor.packaging.version.parse(version_str)
                    if version.is_prerelease and pyenv_paths.get(version.base_version):
                        continue
                    add_to_path(pyenv_path)
            else:
                click.echo(
                    '{0}: PYENV_ROOT is not set. New python paths will '
                    'probably not be exported properly after installation.'
                    ''.format(
                        crayons.red('Warning', bold=True),
                    ), err=True
                )

    global USING_DEFAULT_PYTHON

    # Add pyenv paths to PATH.
    activate_pyenv()

    path_to_python = None
    USING_DEFAULT_PYTHON = (three is None and not python)

    # Find out which python is desired.
    if not python:
        python = convert_three_to_python(three, python)

    if not python:
        python = project.required_python_version

    if not python:
        python = PIPENV_DEFAULT_PYTHON_VERSION

    if python:
        path_to_python = find_a_system_python(python)

    if not path_to_python and python is not None:
        # We need to install Python.
        click.echo(
            u'{0}: Python {1} {2}'.format(
                crayons.red('Warning', bold=True),
                crayons.blue(python),
                u'was not found on your system…',
            ), err=True
        )
        # Pyenv is installed
        if not PYENV_INSTALLED:
            abort()
        else:
            if (not PIPENV_DONT_USE_PYENV) and (SESSION_IS_INTERACTIVE):
                version_map = {
                    # TODO: Keep this up to date!
                    # These versions appear incompatible with pew:
                    # '2.5': '2.5.6',
                    '2.6': '2.6.9',
                    '2.7': '2.7.14',
                    # '3.1': '3.1.5',
                    # '3.2': '3.2.6',
                    '3.3': '3.3.7',
                    '3.4': '3.4.8',
                    '3.5': '3.5.5',
                    '3.6': '3.6.4',
                }
                try:
                    if len(python.split('.')) == 2:
                        # Find the latest version of Python available.

                        version = version_map[python]
                    else:
                        version = python
                except KeyError:
                    abort()

                s = (
                    '{0} {1} {2}'.format(
                        'Would you like us to install',
                        crayons.green('CPython {0}'.format(version)),
                        'with pyenv?'
                    )
                )

                # Prompt the user to continue...
                if not (PIPENV_YES or click.confirm(s, default=True)):
                    abort()
                else:

                    # Tell the user we're installing Python.
                    click.echo(
                        u'{0} {1} {2} {3}{4}'.format(
                            crayons.normal(u'Installing', bold=True),
                            crayons.green(u'CPython {0}'.format(version), bold=True),
                            crayons.normal(u'with pyenv', bold=True),
                            crayons.normal(u'(this may take a few minutes)'),
                            crayons.normal(u'…', bold=True)
                        )
                    )

                    with spinner():
                        # Install Python.
                        c = delegator.run(
                            'pyenv install {0} -s'.format(version),
                            timeout=PIPENV_INSTALL_TIMEOUT,
                            block=False
                        )

                        # Wait until the process has finished...
                        c.block()

                        try:
                            assert c.return_code == 0
                        except AssertionError:
                            click.echo(u'Something went wrong…')
                            click.echo(crayons.blue(c.err), err=True)

                        # Print the results, in a beautiful blue...
                        click.echo(crayons.blue(c.out), err=True)

                    # Add new paths to PATH.
                    activate_pyenv()

                    # Find the newly installed Python, hopefully.
                    path_to_python = find_a_system_python(version)

                    try:
                        assert python_version(path_to_python) == version
                    except AssertionError:
                        click.echo(
                            '{0}: The Python you just installed is not available on your {1}, apparently.'
                            ''.format(
                                crayons.red('Warning', bold=True),
                                crayons.normal('PATH', bold=True)
                            ), err=True
                        )
                        sys.exit(1)

    return path_to_python


def ensure_virtualenv(three=None, python=None, site_packages=False):
    """Creates a virtualenv, if one doesn't exist."""

    def abort():
        sys.exit(1)

    global USING_DEFAULT_PYTHON

    if not project.virtualenv_exists:
        try:
            # Ensure environment variables are set properly.
            ensure_environment()

            # Ensure Python is available.
            python = ensure_python(three=three, python=python)

            # Create the virtualenv.
            # Abort if --system (or running in a virtualenv).
            if PIPENV_USE_SYSTEM:
                click.echo(
                    crayons.red(
                        'You are attempting to re-create a virtualenv that '
                        'Pipenv did not create. Aborting.'
                    )
                )
                sys.exit(1)
            do_create_virtualenv(python=python, site_packages=site_packages)

        except KeyboardInterrupt:
            # If interrupted, cleanup the virtualenv.
            cleanup_virtualenv(bare=False)
            sys.exit(1)

    # If --three, --two, or --python were passed...
    elif (python) or (three is not None) or (site_packages is not False):

        USING_DEFAULT_PYTHON = False

        # Ensure python is installed before deleting existing virtual env
        ensure_python(three=three, python=python)

        click.echo(crayons.red('Virtualenv already exists!'), err=True)
        # If VIRTUAL_ENV is set, there is a possibility that we are
        # going to remove the active virtualenv that the user cares
        # about, so confirm first.
        if 'VIRTUAL_ENV' in os.environ:
            if not (PIPENV_YES or click.confirm('Remove existing virtualenv?', default=True)):
                abort()
        click.echo(crayons.normal(u'Removing existing virtualenv…', bold=True), err=True)

        # Remove the virtualenv.
        cleanup_virtualenv(bare=True)

        # Call this function again.
        ensure_virtualenv(three=three, python=python, site_packages=site_packages)


def ensure_project(three=None, python=None, validate=True, system=False, warn=True, site_packages=False, deploy=False, skip_requirements=False):
    """Ensures both Pipfile and virtualenv exist for the project."""

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True

    if not project.pipfile_exists:
        project.touch_pipfile()

    # Skip virtualenv creation when --system was used.
    if not system:
        ensure_virtualenv(three=three, python=python, site_packages=site_packages)

        if warn:
            # Warn users if they are using the wrong version of Python.
            if project.required_python_version:

                path_to_python = which('python')

                if project.required_python_version not in (python_version(path_to_python) or ''):
                    click.echo(
                        '{0}: Your Pipfile requires {1} {2}, '
                        'but you are using {3} ({4}).'.format(
                            crayons.red('Warning', bold=True),
                            crayons.normal('python_version', bold=True),
                            crayons.blue(project.required_python_version),
                            crayons.blue(python_version(path_to_python)),
                            crayons.green(shorten_path(path_to_python))
                        ), err=True
                    )
                    if not deploy:
                        click.echo(
                            '  {0} will surely fail.'
                            ''.format(crayons.red('$ pipenv check')),
                            err=True
                        )
                    else:
                        click.echo(crayons.red('Deploy aborted.'), err=True)
                        sys.exit(1)

    # Ensure the Pipfile exists.
    ensure_pipfile(validate=validate, skip_requirements=skip_requirements)


def ensure_proper_casing(pfile):
    """Ensures proper casing of Pipfile packages, writes changes to disk."""

    casing_changed = proper_case_section(pfile.get('packages', {}))
    casing_changed |= proper_case_section(pfile.get('dev-packages', {}))

    return casing_changed


def proper_case_section(section):
    """Verify proper casing is retrieved, when available, for each
    dependency in the section.
    """

    # Casing for section.
    changed_values = False
    unknown_names = [k for k in section.keys() if k not in set(project.proper_names)]

    # Replace each package with proper casing.
    for dep in unknown_names:
        try:
            # Get new casing for package name.
            new_casing = proper_case(dep)
        except IOError:
            # Unable to normalize package name.
            continue

        if new_casing != dep:
            changed_values = True
            project.register_proper_name(new_casing)

            # Replace old value with new value.
            old_value = section[dep]
            section[new_casing] = old_value
            del section[dep]

    # Return whether or not values have been changed.
    return changed_values


def shorten_path(location, bold=False):
    """Returns a visually shorter representation of a given system path."""
    original = location
    short = os.sep.join([s[0] if len(s) > (len('2long4')) else s for s in location.split(os.sep)])
    short = short.split(os.sep)
    short[-1] = original.split(os.sep)[-1]
    if bold:
        short[-1] = str(crayons.normal(short[-1], bold=True))

    return os.sep.join(short)
    # return short


def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""

    if not virtualenv:
        location = project.pipfile_location

        # Shorten the virtual display of the path to the virtualenv.
        if not bare:
            location = shorten_path(location)

        if not location:
            click.echo(
                'No Pipfile present at project home. Consider running '
                '{0} first to automatically generate a Pipfile for you.'
                ''.format(crayons.green('`pipenv install`')), err=True)
        elif not bare:
            click.echo(
                'Pipfile found at {0}.\n  Considering this to be the project home.'
                ''.format(crayons.green(location)), err=True)
            pass
        else:
            click.echo(project.project_directory)

    else:
        location = project.virtualenv_location

        if not bare:
            click.echo('Virtualenv location: {0}'.format(crayons.green(location)), err=True)
        else:
            click.echo(location)


def do_install_dependencies(
    dev=False, only=False, bare=False, requirements=False, allow_global=False,
    ignore_hashes=False, skip_lock=False, verbose=False, concurrent=True, requirements_dir=None
):
    """"Executes the install functionality.

    If requirements is True, simply spits out a requirements format to stdout.
    """

    def cleanup_procs(procs, concurrent):
        for c in procs:

            if concurrent:
                c.block()

            if 'Ignoring' in c.out:
                click.echo(crayons.yellow(c.out.strip()))

            if verbose:
                click.echo(crayons.blue(c.out or c.err))

            # The Installation failed...
            if c.return_code != 0:

                # Save the Failed Dependency for later.
                failed_deps_list.append((c.dep, c.ignore_hash))

                # Alert the user.
                click.echo(
                    '{0} {1}! Will try again.'.format(
                        crayons.red('An error occurred while installing'),
                        crayons.green(c.dep.split('--hash')[0].strip())
                    )
                )

    if requirements:
        bare = True

    blocking = (not concurrent)

    # Load the lockfile if it exists, or if only is being used (e.g. lock is being used).
    if skip_lock or only or not project.lockfile_exists:
        if not bare:
            click.echo(crayons.normal(u'Installing dependencies from Pipfile…', bold=True))
            lockfile = split_file(project._lockfile)
    else:
        with open(project.lockfile_location) as f:
            lockfile = split_file(simplejson.load(f))

        if not bare:
            click.echo(
                crayons.normal(
                    u'Installing dependencies from Pipfile.lock ({0})…'.format(
                        lockfile['_meta'].get('hash', {}).get('sha256')[-6:]
                    ),
                    bold=True
                )
            )

    # Allow pip to resolve dependencies when in skip-lock mode.
    no_deps = (not skip_lock)

    deps_list, dev_deps_list = merge_deps(
        lockfile,
        project,
        dev=dev,
        requirements=requirements,
        ignore_hashes=ignore_hashes,
        blocking=blocking,
        only=only
    )
    failed_deps_list = []

    if requirements:

        # Comment out packages that shouldn't be included in
        # requirements.txt, for pip.

        # Additional package selectors, specific to pip's --hash checking mode.
        for l in (deps_list, dev_deps_list):
            for i, dep in enumerate(l):
                if '--hash' in l[i][0]:
                    l[i] = list(l[i])
                    l[i][0] = (l[i][0].split('--hash')[0].strip())

        # Output only default dependencies
        if not dev:
            click.echo('\n'.join(d[0] for d in sorted(deps_list)))
            sys.exit(0)

        # Output only dev dependencies
        if dev:
            click.echo('\n'.join(d[0] for d in sorted(dev_deps_list)))
            sys.exit(0)

    procs = []

    deps_list_bar = progress.bar(deps_list, label=INSTALL_LABEL if os.name != 'nt' else '')

    for dep, ignore_hash, block in deps_list_bar:
        if len(procs) < PIPENV_MAX_SUBPROCESS:
            # Use a specific index, if specified.
            index = None
            if ' -i ' in dep:
                dep, index = dep.split(' -i ')
                dep = '{0} {1}'.format(dep, ' '.join(index.split()[1:])).strip()
                index = index.split()[0]

            # Install the module.
            c = pip_install(
                dep,
                ignore_hashes=ignore_hash,
                allow_global=allow_global,
                no_deps=no_deps,
                verbose=verbose,
                block=block,
                index=index,
                requirements_dir=requirements_dir
            )

            c.dep = dep
            c.ignore_hash = ignore_hash

            procs.append(c)

        if len(procs) >= PIPENV_MAX_SUBPROCESS or len(procs) == len(deps_list):
            cleanup_procs(procs, concurrent)
            procs = []

    cleanup_procs(procs, concurrent)

    # Iterate over the hopefully-poorly-packaged dependencies...
    if failed_deps_list:

        click.echo(crayons.normal(u'Installing initially–failed dependencies…', bold=True))

        for dep, ignore_hash in progress.bar(failed_deps_list, label=INSTALL_LABEL2):
            index = None
            if ' -i ' in dep:
                dep, index = dep.split(' -i ')
                dep = '{0} {1}'.format(dep, ' '.join(index.split()[1:])).strip()
                index = index.split()[0]

            # Install the module.
            c = pip_install(
                dep,
                ignore_hashes=ignore_hash,
                allow_global=allow_global,
                no_deps=no_deps,
                verbose=verbose,
                index=index,
                requirements_dir=requirements_dir
            )

            # The Installation failed...
            if c.return_code != 0:

                # We echo both c.out and c.err because pip returns error details on out.
                click.echo(crayons.blue(format_pip_output(c.out)))
                click.echo(crayons.blue(format_pip_error(c.err)), err=True)

                # Return the subprocess' return code.
                sys.exit(c.return_code)
            else:
                click.echo('{0} {1}{2}'.format(
                    crayons.green('Success installing'),
                    crayons.green(dep.split('--hash')[0].strip()),
                    crayons.green('!')
                ))


def convert_three_to_python(three, python):
    """Converts a Three flag into a Python flag, and raises customer warnings
    in the process, if needed.
    """

    if not python:
        if three is False:
            return '2'

        elif three is True:
            return '3'
    else:
        return python


def do_create_virtualenv(python=None, site_packages=False):
    """Creates a virtualenv."""

    click.echo(crayons.normal(u'Creating a virtualenv for this project…', bold=True), err=True)

    # The user wants the virtualenv in the project.
    if PIPENV_VENV_IN_PROJECT:
        cmd = ['virtualenv', project.virtualenv_location, '--prompt=({0})'.format(project.name)]

        # Pass site-packages flag to virtualenv, if desired...
        if site_packages:
            cmd.append('--system-site-packages')
    else:
        # Default: use pew.
        cmd = [sys.executable, '-m', 'pipenv.pew', 'new', project.virtualenv_name, '-d']

    # Pass a Python version to virtualenv, if needed.
    if python:
        click.echo(u'{0} {1} {2}'.format(
            crayons.normal('Using', bold=True),
            crayons.red(python, bold=True),
            crayons.normal(u'to create virtualenv…', bold=True)
        ), err=True)

    # Use virtualenv's -p python.
    if python:
        cmd = cmd + ['-p', python]

    # Actually create the virtualenv.
    with spinner():
        try:
            c = delegator.run(cmd, block=False, timeout=PIPENV_TIMEOUT)
        except OSError:
            click.echo(
                '{0}: it looks like {1} is not in your {2}. '
                'We cannot continue until this is resolved.'
                ''.format(
                    crayons.red('Warning', bold=True),
                    crayons.red(cmd[0]),
                    crayons.normal('PATH', bold=True)
                ), err=True
            )
            sys.exit(1)

    click.echo(crayons.blue(c.out), err=True)

    # Enable site-packages, if desired...
    if not PIPENV_VENV_IN_PROJECT and site_packages:

        click.echo(crayons.normal(u'Making site-packages available…', bold=True), err=True)

        os.environ['VIRTUAL_ENV'] = project.virtualenv_location
        delegator.run('pipenv run pew toggleglobalsitepackages')
        del os.environ['VIRTUAL_ENV']

    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)


def parse_download_fname(fname, name):
    fname, fextension = os.path.splitext(fname)

    if fextension == '.whl':
        fname = '-'.join(fname.split('-')[:-3])

    if fname.endswith('.tar'):
        fname, _ = os.path.splitext(fname)

    # Substring out package name (plus dash) from file name to get version.
    version = fname[len(name) + 1:]

    # Ignore implicit post releases in version number.
    if '-' in version and version.split('-')[1].isdigit():
        version = version.split('-')[0]

    return version


def get_downloads_info(names_map, section):
    info = []

    p = project.parsed_pipfile

    for fname in os.listdir(project.download_location):
        # Get name from filename mapping.
        name = list(convert_deps_from_pip(names_map[fname]))[0]
        # Get the version info from the filenames.
        version = parse_download_fname(fname, name)

        # Get the hash of each file.
        cmd = '"{0}" hash "{1}"'.format(
            which_pip(),
            os.sep.join([project.download_location, fname])
        )

        c = delegator.run(cmd)
        hash = c.out.split('--hash=')[1].strip()

        # Verify we're adding the correct version from Pipfile
        # and not one from a dependency.
        specified_version = p[section].get(name, '')
        if is_required_version(version, specified_version):
            info.append(dict(name=name, version=version, hash=hash))

    return info


def do_lock(verbose=False, system=False, clear=False, pre=False, keep_outdated=False, write=True):
    """Executes the freeze functionality."""

    cached_lockfile = {}
    if keep_outdated:
        if not project.lockfile_exists:
            click.echo('{0}: Pipfile.lock must exist to use --keep-outdated!'.format(
                crayons.red('Warning', bold=True)
            ))
            sys.exit(1)
        cached_lockfile = project.lockfile_content

    project.destroy_lockfile()

    if write:
        # Alert the user of progress.
        click.echo(
            u'{0} {1} {2}'.format(
                crayons.normal('Locking'),
                crayons.red('[dev-packages]'),
                crayons.normal('dependencies…')
            ),
            err=True
        )

    # Create the lockfile.
    lockfile = project._lockfile

    # Cleanup lockfile.
    for section in ('default', 'develop'):
        for k, v in lockfile[section].copy().items():
            if not hasattr(v, 'keys'):
                del lockfile[section][k]

    # Ensure that develop inherits from default.
    dev_packages = project.dev_packages.copy()

    for dev_package in project.dev_packages:
        if dev_package in project.packages:
            dev_packages[dev_package] = project.packages[dev_package]

    # Resolve dev-package dependencies, with pip-tools.
    deps = convert_deps_to_pip(dev_packages, project, r=False, include_index=True)

    results = venv_resolve_deps(
        deps,
        which=which,
        verbose=verbose,
        project=project,
        clear=clear,
        pre=pre,
    )

    # Add develop dependencies to lockfile.
    for dep in results:
        # Add version information to lockfile.
        lockfile['develop'].update({dep['name']: {'version': '=={0}'.format(dep['version'])}})

        # Add Hashes to lockfile
        lockfile['develop'][dep['name']]['hashes'] = sorted(dep['hashes'])

        # Add index metadata to lockfile.
        if 'index' in dep:
            lockfile['develop'][dep['name']]['index'] = dep['index']

        # Add PEP 508 specifier metadata to lockfile.
        if 'markers' in dep:
            lockfile['develop'][dep['name']]['markers'] = dep['markers']

    # Add refs for VCS installs.
    # TODO: be smarter about this.
    vcs_deps = convert_deps_to_pip(project.vcs_dev_packages, project, r=False)
    pip_freeze = delegator.run('{0} freeze'.format(which_pip())).out

    if vcs_deps:
        for line in pip_freeze.strip().split('\n'):
            # if the line doesn't match a vcs dependency in the Pipfile,
            # ignore it
            if not any(dep in line for dep in vcs_deps):
                continue

            try:
                installed = convert_deps_from_pip(line)
                name = list(installed.keys())[0]

                if is_vcs(installed[name]):
                    lockfile['develop'].update(installed)

            except IndexError:
                pass

    if write:
        # Alert the user of progress.
        click.echo(
            u'{0} {1} {2}'.format(
                crayons.normal('Locking'),
                crayons.red('[packages]'),
                crayons.normal('dependencies…')
            ),
            err=True
        )

    # Resolve package dependencies, with pip-tools.
    deps = convert_deps_to_pip(project.packages, project, r=False, include_index=True)
    results = venv_resolve_deps(
        deps,
        which=which,
        verbose=verbose,
        project=project,
        clear=clear,
        pre=pre,
    )

    # Add default dependencies to lockfile.
    for dep in results:
        # Add version information to lockfile.
        lockfile['default'].update({dep['name']: {'version': '=={0}'.format(dep['version'])}})

        # Add Hashes to lockfile
        lockfile['default'][dep['name']]['hashes'] = sorted(dep['hashes'])

        # Add index metadata to lockfile.
        if 'index' in dep:
            lockfile['default'][dep['name']]['index'] = dep['index']

        # Add PEP 508 specifier metadata to lockfile.
        if 'markers' in dep:
            lockfile['default'][dep['name']]['markers'] = dep['markers']

    # Add refs for VCS installs.
    # TODO: be smarter about this.
    vcs_deps = convert_deps_to_pip(project.vcs_packages, project, r=False)
    pip_freeze = delegator.run('{0} freeze'.format(which_pip())).out

    for dep in vcs_deps:
        for line in pip_freeze.strip().split('\n'):
            try:
                installed = convert_deps_from_pip(line)
                name = list(installed.keys())[0]

                if is_vcs(installed[name]):
                    # Convert name to PEP 423 name.
                    installed = {pep423_name(name): installed[name]}

                    lockfile['default'].update(installed)
            except IndexError:
                pass

    # Support for --keep-outdated…
    if keep_outdated:
        for section_name, section in (('default', project.packages), ('develop', project.dev_packages)):
            for package_specified in section:
                norm_name = pep423_name(package_specified)
                if not is_pinned(section[package_specified]):
                    lockfile[section_name][norm_name] = cached_lockfile[section_name][norm_name]

    # Overwrite any develop packages with default packages.
    for default_package in lockfile['default']:
        if default_package in lockfile['develop']:
            lockfile['develop'][default_package] = lockfile['default'][default_package]

    if write:

        # Write out the lockfile.
        with open(project.lockfile_location, 'w') as f:
            simplejson.dump(lockfile, f, indent=4, separators=(',', ': '), sort_keys=True)
            # Write newline at end of document. GH Issue #319.
            f.write('\n')

        click.echo(
            '{0}'.format(
                crayons.normal(
                    'Updated Pipfile.lock ({0})!'.format(
                        lockfile['_meta'].get('hash', {}).get('sha256')[-6:]
                    ),
                    bold=True
                )
            ),
            err=True
        )
    else:
        return lockfile


def activate_virtualenv(source=True):
    """Returns the string to activate a virtualenv."""

    # Suffix and source command for other shells.
    suffix = ''
    command = '.' if source else ''

    # Support for fish shell.
    if PIPENV_SHELL and 'fish' in PIPENV_SHELL:
        suffix = '.fish'
        command = 'source'

    # Support for csh shell.
    if PIPENV_SHELL and 'csh' in PIPENV_SHELL:
        suffix = '.csh'
        command = 'source'

    # Escape any spaces located within the virtualenv path to allow
    # for proper activation.
    venv_location = project.virtualenv_location.replace(' ', r'\ ')

    if source:
        return '{2} {0}/bin/activate{1}'.format(venv_location, suffix, command)
    else:
        return '{0}/bin/activate'.format(venv_location)


def do_activate_virtualenv(bare=False):
    """Executes the activate virtualenv functionality."""
    # Check for environment marker, and skip if it's set.
    if 'PIPENV_ACTIVE' not in os.environ:
        if not bare:
            click.echo('To activate this project\'s virtualenv, run the following:\n $ {0}'.format(
                crayons.red('pipenv shell'))
            )
        else:
            click.echo(activate_virtualenv())


def do_purge(bare=False, downloads=False, allow_global=False, verbose=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            click.echo(crayons.normal(u'Clearing out downloads directory…', bold=True))
        shutil.rmtree(project.download_location)
        return

    freeze = delegator.run('"{0}" freeze'.format(which_pip(allow_global=allow_global))).out

    # Remove comments from the output, if any.
    installed = [line for line in freeze.splitlines() if not line.lstrip().startswith('#')]

    # Remove setuptools and friends from installed, if present.
    for package_name in BAD_PACKAGES:
        for i, package in enumerate(installed):
            if package.startswith(package_name):
                del installed[i]

    actually_installed = []

    for package in installed:
        try:
            dep = convert_deps_from_pip(package)
        except AssertionError:
            dep = None

        if dep and not is_vcs(dep):

            dep = [k for k in dep.keys()][0]
            # TODO: make this smarter later.
            if not dep.startswith('-e ') and not dep.startswith('git+'):
                actually_installed.append(dep)

    if not bare:
        click.echo(u'Found {0} installed package(s), purging…'.format(len(actually_installed)))
    command = '"{0}" uninstall {1} -y'.format(which_pip(allow_global=allow_global), ' '.join(actually_installed))

    if verbose:
        click.echo('$ {0}'.format(command))

    c = delegator.run(command)

    if not bare:
        click.echo(crayons.blue(c.out))
        click.echo(crayons.green('Environment now purged and fresh!'))


def do_init(
    dev=False, requirements=False, allow_global=False, ignore_pipfile=False,
    skip_lock=False, verbose=False, system=False, concurrent=True, deploy=False,
    pre=False, keep_outdated=False, requirements_dir=None
):
    """Executes the init functionality."""

    if not system:
        if not project.virtualenv_exists:
            try:
                do_create_virtualenv()
            except KeyboardInterrupt:
                cleanup_virtualenv(bare=False)
                sys.exit(1)

    # Ensure the Pipfile exists.
    ensure_pipfile()

    if not requirements_dir:
        requirements_dir = TemporaryDirectory(suffix='-requirements', prefix='pipenv-')

    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if (project.lockfile_exists and not ignore_pipfile) and not skip_lock:

        # Open the lockfile.
        with codecs.open(project.lockfile_location, 'r') as f:
            lockfile = simplejson.load(f)

        # Update the lockfile if it is out-of-date.
        p = pipfile.load(project.pipfile_location)

        # Check that the hash of the Lockfile matches the lockfile's hash.
        if not lockfile['_meta'].get('hash', {}).get('sha256') == p.hash:

            old_hash = lockfile['_meta'].get('hash', {}).get('sha256')[-6:]
            new_hash = p.hash[-6:]
            if deploy:
                click.echo(
                    crayons.red(
                        'Your Pipfile.lock ({0}) is out of date. Expected: ({1}).'.format(
                            old_hash,
                            new_hash
                        )
                    )
                )
                click.echo(crayons.normal('Aborting deploy.', bold=True), err=True)
                requirements_dir.cleanup()
                sys.exit(1)
            else:
                click.echo(
                    crayons.red(
                        u'Pipfile.lock ({0}) out of date, updating to ({1})…'.format(
                            old_hash,
                            new_hash
                        ),
                        bold=True),
                    err=True
                )

                do_lock(system=system, pre=pre)

    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists and not skip_lock:
        click.echo(crayons.normal(u'Pipfile.lock not found, creating…', bold=True), err=True)
        do_lock(system=system, pre=pre, keep_outdated=keep_outdated, verbose=verbose)

    do_install_dependencies(dev=dev, requirements=requirements, allow_global=allow_global,
                            skip_lock=skip_lock, verbose=verbose, concurrent=concurrent,
                            requirements_dir=requirements_dir.name)
    requirements_dir.cleanup()

    # Activate virtualenv instructions.
    if not allow_global and not deploy:
        do_activate_virtualenv()


def pip_install(
    package_name=None, r=None, allow_global=False, ignore_hashes=False,
    no_deps=True, verbose=False, block=True, index=None, pre=False,
    selective_upgrade=False, requirements_dir=None
):
    import pip

    if verbose:
        click.echo(crayons.normal('Installing {0!r}'.format(package_name), bold=True), err=True)
        pip.logger.setLevel(logging.INFO)

    # Create files for hash mode.
    if not package_name.startswith('-e ') and (not ignore_hashes) and (r is None):
        fd, r = tempfile.mkstemp(prefix='pipenv-', suffix='-requirement.txt', dir=requirements_dir)
        with os.fdopen(fd, 'w') as f:
            f.write(package_name)

    # Install dependencies when a package is a VCS dependency.
    try:
        req = get_requirement(package_name.split('--hash')[0].split('--trusted-host')[0]).vcs
    except (pip._vendor.pyparsing.ParseException, ValueError) as e:
        click.echo('{0}: {1}'.format(crayons.red('WARNING'), e), err=True)
        click.echo(
            '{0}... You will have to reinstall any packages that failed to install.'.format(
                crayons.red('ABORTING INSTALL')
            ), err=True
        )
        click.echo(
            'You may have to manually run {0} when you are finished.'.format(
                crayons.normal('pipenv lock', bold=True)
            )
        )
        sys.exit(1)
    if req:
        no_deps = False

        # Don't specify a source directory when using --system.
        if not allow_global and ('PIP_SRC' not in os.environ):
            src = '--src {0}'.format(shellquote(project.virtualenv_src_location))
        else:
            src = ''
    else:
        src = ''

    # Try installing for each source in project.sources.
    if index:
        sources = [{'url': index}]
    else:
        sources = project.sources

    for source in sources:
        if package_name.startswith('-e '):
            install_reqs = ' -e "{0}"'.format(package_name.split('-e ')[1])
        elif r:
            install_reqs = ' -r {0}'.format(r)
        else:
            install_reqs = ' "{0}"'.format(package_name)

        # Skip hash-checking mode, when appropriate.
        if r:
            with open(r) as f:
                if '--hash' not in f.read():
                    ignore_hashes = True
        else:
            if '--hash' not in install_reqs:
                ignore_hashes = True

        verbose_flag = '--verbose' if verbose else ''

        if not ignore_hashes:
            install_reqs += ' --require-hashes'

        no_deps = '--no-deps' if no_deps else ''
        pre = '--pre' if pre else ''

        quoted_pip = which_pip(allow_global=allow_global)
        quoted_pip = shellquote(quoted_pip)
        upgrade_strategy = '--upgrade-strategy=only-if-needed' if selective_upgrade else ''

        pip_command = '{0} install {4} {5} {6} {7} {3} {1} {2} --exists-action w'.format(
            quoted_pip,
            install_reqs,
            ' '.join(prepare_pip_source_args([source])),
            no_deps,
            pre,
            src,
            verbose_flag,
            upgrade_strategy
        )

        if verbose:
            click.echo('$ {0}'.format(pip_command), err=True)

        c = delegator.run(pip_command, block=block)
        if c.return_code == 0:
            break

    # Return the result of the first one that runs ok, or the last one that didn't work.
    return c


def pip_download(package_name):
    for source in project.sources:
        cmd = '"{0}" download "{1}" -i {2} -d {3}'.format(
            which_pip(),
            package_name,
            source['url'],
            project.download_location
        )
        c = delegator.run(cmd)
        if c.return_code == 0:
            break
    return c


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""
    if allow_global:
        if 'VIRTUAL_ENV' in os.environ:
            return which('pip', location=os.environ['VIRTUAL_ENV'])

        for p in ('pip', 'pip2', 'pip3'):
            where = system_which(p)
            if where:
                return where

    return which('pip')


def system_which(command, mult=False):
    """Emulates the system's which. Returns None if not found."""

    _which = 'which -a' if not os.name == 'nt' else 'where'

    c = delegator.run('{0} {1}'.format(_which, command))
    try:
        # Which Not found...
        if c.return_code == 127:
            click.echo(
                '{}: the {} system utility is required for Pipenv to find Python installations properly.'
                '\n  Please install it.'.format(
                    crayons.red('Warning', bold=True),
                    crayons.red(_which)
                ), err=True
            )
        assert c.return_code == 0
    except AssertionError:
        return None if not mult else []

    result = c.out.strip() or c.err.strip()

    if mult:
        return result.split('\n')
    else:
        return result.split('\n')[0]


def format_help(help):
    """Formats the help string."""
    help = help.replace('Options:', str(crayons.normal('Options:', bold=True)))

    help = help.replace('Usage: pipenv', str('Usage: {0}'.format(crayons.normal('pipenv', bold=True))))

    help = help.replace('  check', str(crayons.red('  check', bold=True)))
    help = help.replace('  clean', str(crayons.red('  clean', bold=True)))
    help = help.replace('  graph', str(crayons.red('  graph', bold=True)))
    help = help.replace('  install', str(crayons.magenta('  install', bold=True)))
    help = help.replace('  lock', str(crayons.green('  lock', bold=True)))
    help = help.replace('  open', str(crayons.red('  open', bold=True)))
    help = help.replace('  run', str(crayons.yellow('  run', bold=True)))
    help = help.replace('  shell', str(crayons.yellow('  shell', bold=True)))
    help = help.replace('  sync', str(crayons.green('  sync', bold=True)))
    help = help.replace('  uninstall', str(crayons.magenta('  uninstall', bold=True)))
    help = help.replace('  update', str(crayons.green('  update', bold=True)))

    additional_help = """
Usage Examples:
   Create a new project using Python 3.6, specifically:
   $ {1}

   Install all dependencies for a project (including dev):
   $ {2}

   Create a lockfile containing pre-releases:
   $ {6}

   Show a graph of your installed dependencies:
   $ {4}

   Check your installed dependencies for security vulnerabilities:
   $ {7}

   Install a local setup.py into your virtual environment/Pipfile:
   $ {5}

   Use a lower-level pip command:
   $ {8}

Commands:""".format(
        crayons.red('pipenv --three'),
        crayons.red('pipenv --python 3.6'),
        crayons.red('pipenv install --dev'),
        crayons.red('pipenv lock'),
        crayons.red('pipenv graph'),
        crayons.red('pipenv install -e .'),
        crayons.red('pipenv lock --pre'),
        crayons.red('pipenv check'),
        crayons.red('pipenv run pip freeze'),
    )

    help = help.replace('Commands:', additional_help)

    return help


def format_pip_error(error):
    error = error.replace('Expected', str(crayons.green('Expected', bold=True)))
    error = error.replace('Got', str(crayons.red('Got', bold=True)))
    error = error.replace('THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE', str(crayons.red('THESE PACKAGES DO NOT MATCH THE HASHES FROM Pipfile.lock!', bold=True)))
    error = error.replace('someone may have tampered with them', str(crayons.red('someone may have tampered with them')))

    error = error.replace('option to pip install', 'option to \'pipenv install\'')
    return error


def format_pip_output(out, r=None):
    def gen(out):
        for line in out.split('\n'):
            # Remove requirements file information from pip output.
            if '(from -r' in line:
                yield line[:line.index('(from -r')]
            else:
                yield line

    out = '\n'.join([l for l in gen(out)])
    return out


# |\/| /\ |) [-   ]3 `/
# . . .-. . . . . .-. .-. . .   .-. .-. .-. .-. .-.
# |<  |-  |\| |\| |-   |  |-|   |(  |-   |   |   /
# ' ` `-' ' ` ' ` `-'  '  ' `   ' ' `-' `-'  '  `-'

def warn_in_virtualenv():
    if PIPENV_USE_SYSTEM:
        # Only warn if pipenv isn't already active.
        if 'PIPENV_ACTIVE' not in os.environ:
            click.echo(
                '{0}: Pipenv found itself running within a virtual environment, '
                'so it will automatically use that environment, instead of '
                'creating its own for any project.'.format(
                    crayons.green('Courtesy Notice')
                ), err=True
            )


def ensure_lockfile(keep_outdated=False):
    """Ensures that the lockfile is up–to–date."""
    pre = project.settings.get('allow_prereleases')
    if not keep_outdated:
        keep_outdated = project.settings.get('keep_outdated')

    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if project.lockfile_exists:

        # Open the lockfile.
        with codecs.open(project.lockfile_location, 'r') as f:
            lockfile = simplejson.load(f)

        # Update the lockfile if it is out-of-date.
        p = pipfile.load(project.pipfile_location)

        # Check that the hash of the Lockfile matches the lockfile's hash.
        if not lockfile['_meta'].get('hash', {}).get('sha256') == p.hash:

            old_hash = lockfile['_meta'].get('hash', {}).get('sha256')[-6:]
            new_hash = p.hash[-6:]

            click.echo(
                crayons.red(
                    u'Pipfile.lock ({0}) out of date, updating to ({1})…'.format(
                        old_hash,
                        new_hash
                    ),
                    bold=True),
                err=True
            )

            do_lock(pre=pre, keep_outdated=keep_outdated)
    else:
        do_lock(pre=pre, keep_outdated=keep_outdated)


def do_py(system=False):
    try:
        click.echo(which('python', allow_global=system))
    except AttributeError:
        click.echo(crayons.red('No project found!'))

def do_outdated():
    packages = {}
    results = delegator.run('{0} freeze'.format(which('pip'))).out.strip().split('\n')
    for result in results:
        packages.update(convert_deps_from_pip(result))

    updated_packages = {}

    lockfile = do_lock(write=False)
    for section in ('develop', 'default'):
        for package in lockfile[section]:
            try:
                updated_packages[package] = lockfile[section][package]['version']
            except KeyError:
                pass

    outdated = []
    for package in packages:
        if package in updated_packages:
            if updated_packages[package] != packages[package]:
                outdated.append((package, updated_packages[package], packages[package]))

    for package, new_version, old_version in outdated:
        click.echo('Package {0!r} out–of–date: {1!r} installed, {2!r} available.'.format(package, old_version, new_version))

    sys.exit(bool(outdated))



def do_install(
    package_name=False, more_packages=False, dev=False, three=False,
    python=False, system=False, lock=True, ignore_pipfile=False,
    skip_lock=False, verbose=False, requirements=False, sequential=False,
    pre=False, code=False, deploy=False, keep_outdated=False,
    selective_upgrade=False
):
    import pip

    requirements_directory = TemporaryDirectory(suffix='-requirements', prefix='pipenv-')
    if selective_upgrade:
        keep_outdated = True

    if not more_packages:
        more_packages = []

    # Don't search for requirements.txt files if the user provides one
    skip_requirements = True if requirements else False

    concurrent = (not sequential)

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, system=system, warn=True, deploy=deploy, skip_requirements=skip_requirements)

    # Load the --pre settings from the Pipfile.
    if not pre:
        pre = project.settings.get('allow_prereleases')

    if not keep_outdated:
        keep_outdated = project.settings.get('keep_outdated')

    remote = requirements and is_valid_url(requirements)

    # Warn and exit if --system is used without a pipfile.
    if system and package_name:
        click.echo(
            '{0}: --system is intended to be used for Pipfile installation, '
            'not installation of specific packages. Aborting.'.format(
                crayons.red('Warning', bold=True)
            ), err=True
        )
        click.echo('See also: --deploy flag.', err=True)
        requirements_directory.cleanup()
        sys.exit(1)

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True

    # Check if the file is remote or not
    if remote:
        fd, temp_reqs = tempfile.mkstemp(prefix='pipenv-', suffix='-requirement.txt', dir=requirements_directory.name)
        requirements_url = requirements

        # Download requirements file
        click.echo(crayons.normal(u'Remote requirements file provided! Downloading…', bold=True), err=True)
        try:
            download_file(requirements, temp_reqs)
        except IOError:
            click.echo(
                crayons.red(
                   u'Unable to find requirements file at {0}.'.format(crayons.normal(requirements))
                ),
                err=True
            )
            requirements_directory.cleanup()
            sys.exit(1)
        # Replace the url with the temporary requirements file
        requirements = temp_reqs
        remote = True

    if requirements:
        error, traceback = None, None
        click.echo(crayons.normal(u'Requirements file provided! Importing into Pipfile…', bold=True), err=True)
        try:
            import_requirements(r=project.path_to(requirements), dev=dev)
        except (UnicodeDecodeError, pip.exceptions.PipError) as e:
            # Don't print the temp file path if remote since it will be deleted.
            req_path = requirements_url if remote else project.path_to(requirements)
            error = (u'Unexpected syntax in {0}. Are you sure this is a '
                      'requirements.txt style file?'.format(req_path))
            traceback = e
        except AssertionError as e:
            error = (u'Requirements file doesn\'t appear to exist. Please ensure the file exists in your '
                      'project directory or you provided the correct path.')
            traceback = e
        finally:
            # If requirements file was provided by remote url delete the temporary file
            if remote:
                os.close(fd)  # Close for windows to allow file cleanup.
                os.remove(project.path_to(temp_reqs))

            if error and traceback:
                click.echo(crayons.red(error))
                click.echo(crayons.blue(str(traceback)), err=True)
                requirements_directory.cleanup()
                sys.exit(1)

    if code:
        click.echo(crayons.normal(u'Discovering imports from local codebase…', bold=True))
        for req in import_from_code(code):
            click.echo('  Found {0}!'.format(crayons.green(req)))
            project.add_package_to_pipfile(req)

    # Capture -e argument and assign it to following package_name.
    more_packages = list(more_packages)
    if package_name == '-e':
        package_name = ' '.join([package_name, more_packages.pop(0)])

    # Capture . argument and assign it to nothing
    if package_name == '.':
        package_name = False

    # Allow more than one package to be provided.
    package_names = [package_name, ] + more_packages

    # Install all dependencies, if none was provided.
    if package_name is False:
        # Update project settings with pre preference.
        if pre:
            project.update_settings({'allow_prereleases': pre})
        if keep_outdated:
            project.update_settings({'keep_outdated': keep_outdated})

        do_init(
            dev=dev, allow_global=system, ignore_pipfile=ignore_pipfile, system=system,
            skip_lock=skip_lock, verbose=verbose, concurrent=concurrent, deploy=deploy,
            pre=pre, requirements_dir=requirements_directory
        )
        requirements_directory.cleanup()
        sys.exit(0)

    # Support for --selective-upgrade.
    if selective_upgrade:

        for i, package_name in enumerate(package_names[:]):
            section = project.packages if not dev else project.dev_packages
            package = convert_deps_from_pip(package_name)
            package__name = list(package.keys())[0]
            package__val = list(package.values())[0]

            try:
                if not is_star(section[package__name]) and is_star(package__val):
                    package_names[i] = '{0}{1}'.format(package_name, section[package__name])
            except KeyError:
                pass

    for package_name in package_names:
        click.echo(crayons.normal(u'Installing {0}…'.format(crayons.green(package_name, bold=True)), bold=True))

        # pip install:
        with spinner():

            c = pip_install(
                package_name,
                ignore_hashes=True,
                allow_global=system,
                selective_upgrade=selective_upgrade,
                no_deps=False,
                verbose=verbose,
                pre=pre,
                requirements_dir=requirements_directory.name
            )

            # Warn if --editable wasn't passed.
            try:
                converted = convert_deps_from_pip(package_name)
            except ValueError as e:
                click.echo('{0}: {1}'.format(crayons.red('WARNING'), e))
                requirements_directory.cleanup()
                sys.exit(1)

            key = [k for k in converted.keys()][0]
            if is_vcs(key) or is_vcs(converted[key]) and not converted[key].get('editable'):
                click.echo(
                    '{0}: You installed a VCS dependency in non–editable mode. '
                    'This will work fine, but sub-dependencies will not be resolved by {1}.'
                    '\n  To enable this sub–dependency functionality, specify that this dependency is editable.'
                    ''.format(
                        crayons.red('Warning', bold=True),
                        crayons.red('$ pipenv lock')
                    )
                )

        click.echo(crayons.blue(format_pip_output(c.out)))

        # Ensure that package was successfully installed.
        try:
            assert c.return_code == 0
        except AssertionError:
            click.echo(
                '{0} An error occurred while installing {1}!'.format(
                    crayons.red('Error: ', bold=True),
                    crayons.green(package_name)
                ), err=True)
            click.echo(crayons.blue(format_pip_error(c.err)), err=True)
            requirements_directory.cleanup()
            sys.exit(1)

        click.echo(
            '{0} {1} {2} {3}{4}'.format(
                crayons.normal('Adding', bold=True),
                crayons.green(package_name, bold=True),
                crayons.normal("to Pipfile's", bold=True),
                crayons.red('[dev-packages]' if dev else '[packages]', bold=True),
                crayons.normal('…', bold=True),
            )
        )

        # Add the package to the Pipfile.
        try:
            project.add_package_to_pipfile(package_name, dev)
        except ValueError as e:
            click.echo('{0} {1}'.format(crayons.red('ERROR (PACKAGE NOT INSTALLED):'), e))

        # Update project settings with pre preference.
        if pre:
            project.update_settings({'allow_prereleases': pre})
        if keep_outdated:
            project.update_settings({'keep_outdated': keep_outdated})

    if lock and not skip_lock:
        do_init(dev=dev, allow_global=system, concurrent=concurrent, verbose=verbose, keep_outdated=keep_outdated, requirements_dir=requirements_directory)
        requirements_directory.cleanup()


def do_uninstall(
    package_name=False, more_packages=False, three=None, python=False,
    system=False, lock=False, all_dev=False, all=False, verbose=False,
    keep_outdated=False
):

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python)

    # Load the --pre settings from the Pipfile.
    pre = project.settings.get('allow_prereleases')


    package_names = (package_name,) + more_packages
    pipfile_remove = True

    # Un-install all dependencies, if --all was provided.
    if all is True:
        click.echo(
            crayons.normal(u'Un-installing all packages from virtualenv…', bold=True)
        )
        do_purge(allow_global=system, verbose=verbose)
        sys.exit(0)

    # Uninstall [dev-packages], if --dev was provided.
    if all_dev:
        if 'dev-packages' not in project.parsed_pipfile:
            click.echo(
                crayons.normal('No {0} to uninstall.'.format(
                    crayons.red('[dev-packages]')), bold=True
                )
            )
            sys.exit(0)

        click.echo(
            crayons.normal(u'Un-installing {0}…'.format(
                crayons.red('[dev-packages]')), bold=True
            )
        )
        package_names = project.parsed_pipfile['dev-packages']
        package_names = package_names.keys()

    if package_name is False and not all_dev:
        click.echo(crayons.red('No package provided!'), err=True)
        sys.exit(1)

    for package_name in package_names:

        click.echo(u'Un-installing {0}…'.format(
            crayons.green(package_name))
        )

        cmd = '"{0}" uninstall {1} -y'.format(
            which_pip(allow_global=system),
            package_name
        )
        if verbose:
            click.echo('$ {0}'.format(cmd))

        c = delegator.run(cmd)

        click.echo(crayons.blue(c.out))

        if pipfile_remove:
            norm_name = pep423_name(package_name)

            in_dev_packages = (norm_name in project._pipfile.get('dev-packages', {}))
            in_packages = (norm_name in project._pipfile.get('packages', {}))

            if not in_dev_packages and not in_packages:
                click.echo(
                    'No package {0} to remove from Pipfile.'.format(
                        crayons.green(package_name)
                    )
                )
                continue

            click.echo(
                u'Removing {0} from Pipfile…'.format(
                    crayons.green(package_name)
                )
            )

            # Remove package from both packages and dev-packages.
            project.remove_package_from_pipfile(package_name, dev=True)
            project.remove_package_from_pipfile(package_name, dev=False)

    if lock:
        do_lock(system=system, pre=pre, keep_outdated=keep_outdated)


def do_shell(three=None, python=False, fancy=False, shell_args=None):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    # Set an environment variable, so we know we're in the environment.
    os.environ['PIPENV_ACTIVE'] = '1'

    compat = (not fancy)

    # Support shell compatibility mode.
    if PIPENV_SHELL_FANCY:
        compat = False

    # Compatibility mode:
    if compat:
        if PIPENV_SHELL:
            shell = os.path.abspath(PIPENV_SHELL)
        else:
            click.echo(
                crayons.red(
                    'Please ensure that the {0} environment variable '
                    'is set before activating shell.'.format(crayons.normal('SHELL', bold=True))
                ), err=True
            )
            sys.exit(1)

        click.echo(
            crayons.normal(
                'Spawning environment shell ({0}). Use {1} to leave.'.format(
                    crayons.red(shell),
                    crayons.normal("'exit'", bold=True)
                ), bold=True
            ), err=True
        )

        cmd = "{0} -i'".format(shell)
        args = []

    # Standard (properly configured shell) mode:
    else:
        if PIPENV_VENV_IN_PROJECT:
            # use .venv as the target virtualenv name
            workon_name = '.venv'
        else:
            workon_name = project.virtualenv_name

        cmd = sys.executable
        args = ['-m', 'pipenv.pew', 'workon', workon_name]

    # Grab current terminal dimensions to replace the hardcoded default
    # dimensions of pexpect
    terminal_dimensions = get_terminal_size()

    try:
        with temp_environ():
            if PIPENV_VENV_IN_PROJECT:
                os.environ['WORKON_HOME'] = project.project_directory

            c = pexpect.spawn(
                cmd,
                args,
                dimensions=(
                    terminal_dimensions.lines,
                    terminal_dimensions.columns
                )
            )

    # Windows!
    except AttributeError:
        import subprocess
        # Tell pew to use the project directory as its workon_home
        with temp_environ():
            if PIPENV_VENV_IN_PROJECT:
                os.environ['WORKON_HOME'] = project.project_directory
            p = subprocess.Popen([cmd] + list(args), shell=True, universal_newlines=True)
            p.communicate()
            sys.exit(p.returncode)

    # Activate the virtualenv if in compatibility mode.
    if compat:
        c.sendline(activate_virtualenv())

    # Send additional arguments to the subshell.
    if shell_args:
        c.sendline(' '.join(shell_args))

    # Handler for terminal resizing events
    # Must be defined here to have the shell process in its context, since we
    # can't pass it as an argument
    def sigwinch_passthrough(sig, data):
        terminal_dimensions = get_terminal_size()
        c.setwinsize(terminal_dimensions.lines, terminal_dimensions.columns)
    signal.signal(signal.SIGWINCH, sigwinch_passthrough)

    # Interact with the new shell.
    c.interact(escape_character=None)
    c.close()
    sys.exit(c.exitstatus)


def inline_activate_virtualenv():
    try:
        activate_this = which('activate_this.py')
        with open(activate_this) as f:
            code = compile(f.read(), activate_this, 'exec')
            exec(code, dict(__file__=activate_this))
    # Catch all errors, just in case.
    except Exception:
        click.echo(
            u'{0}: There was an unexpected error while activating your virtualenv. Continuing anyway…'
            ''.format(crayons.red('Warning', bold=True)),
            err=True
        )


def do_run(command, args, three=None, python=False):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    load_dot_env()

    # Script was found…
    if command in project.scripts:
        command = ' '.join(project.scripts[command])

    # Separate out things that were passed in as a string.
    _c = list(command.split())
    command = _c.pop(0)
    if _c:
        args = list(args)
        for __c in reversed(_c):
            args.insert(0, __c)

    # Activate virtualenv under the current interpreter's environment
    inline_activate_virtualenv()

    # Windows!
    if os.name == 'nt':
        import subprocess
        p = subprocess.Popen([command] + list(args), shell=True, universal_newlines=True)
        p.communicate()
        sys.exit(p.returncode)
    else:
        command_path = system_which(command)
        if not command_path:
            click.echo(
                '{0}: the command {1} could not be found within {2} or Pipfile\'s {3}.'
                ''.format(
                    crayons.red('Error', bold=True),
                    crayons.red(command),
                    crayons.normal('PATH', bold=True),
                    crayons.normal('[scripts]', bold=True)
                ), err=True
            )
            sys.exit(1)

        # Execute the command.
        os.execl(command_path, command_path, *args)
        pass


def do_check(three=None, python=False, system=False, unused=False, args=None):

    if not system:
        # Ensure that virtualenv is available.
        ensure_project(three=three, python=python, validate=False, warn=False)

    if not args:
        args = []

    if unused:
        deps_required = [k for k in project.packages.keys()]
        deps_needed = import_from_code(unused)

        for dep in deps_needed:
            try:
                deps_required.remove(dep)
            except ValueError:
                pass

        if deps_required:
            click.echo(crayons.normal('The following dependencies appear unused, and may be safe for removal:'))
            for dep in deps_required:
                click.echo('  - {0}'.format(crayons.green(dep)))
            sys.exit(1)
        else:
            sys.exit(0)

    click.echo(
        crayons.normal(u'Checking PEP 508 requirements…', bold=True)
    )

    if system:
        python = system_which('python')
    else:
        python = which('python')

    # Run the PEP 508 checker in the virtualenv.
    c = delegator.run('"{0}" {1}'.format(python, shellquote(pep508checker.__file__.rstrip('cdo'))))
    results = simplejson.loads(c.out)

    # Load the pipfile.
    p = pipfile.Pipfile.load(project.pipfile_location)

    failed = False
    # Assert each specified requirement.
    for marker, specifier in p.data['_meta']['requires'].items():

        if marker in results:
            try:
                assert results[marker] == specifier
            except AssertionError:
                failed = True
                click.echo(
                    'Specifier {0} does not match {1} ({2}).'
                    ''.format(
                        crayons.green(marker),
                        crayons.blue(specifier),
                        crayons.red(results[marker])
                    ), err=True
                )
    if failed:
        click.echo(crayons.red('Failed!'), err=True)
        sys.exit(1)
    else:
        click.echo(crayons.green('Passed!'))

    click.echo(
        crayons.normal(u'Checking installed package safety…', bold=True)
    )

    path = pep508checker.__file__.rstrip('cdo')
    path = os.sep.join(__file__.split(os.sep)[:-1] + ['patched', 'safety.zip'])

    if not system:
        python = which('python')
    else:
        python = system_which('python')

    c = delegator.run('"{0}" {1} check --json --key=1ab8d58f-5122e025-83674263-bc1e79e0'.format(python, shellquote(path)))
    try:
        results = simplejson.loads(c.out)
    except ValueError:
        click.echo('An error occurred:', err=True)
        click.echo(c.err, err=True)
        sys.exit(1)

    for (package, resolved, installed, description, vuln) in results:
        click.echo(
            '{0}: {1} {2} resolved ({3} installed)!'.format(
                crayons.normal(vuln, bold=True),
                crayons.green(package),
                crayons.red(resolved, bold=False),
                crayons.red(installed, bold=True)
            )
        )

        click.echo('{0}'.format(description))
        click.echo()

    if not results:
        click.echo(crayons.green('All good!'))
    else:
        sys.exit(1)


def do_graph(bare=False, json=False, reverse=False):
    try:
        python_path = which('python')
    except AttributeError:
        click.echo(
            u'{0}: {1}'.format(
                crayons.red('Warning', bold=True),
                u'Unable to display currently–installed dependency graph information here. '
                u'Please run within a Pipenv project.',
            ), err=True
        )
        sys.exit(1)

    if reverse and json:
        click.echo(
            u'{0}: {1}'.format(
                crayons.red('Warning', bold=True),
                u'Using both --reverse and --json together is not supported. '
                u'Please select one of the two options.',
            ), err=True
        )
        sys.exit(1)

    flag = ''
    if json:
        flag = '--json'
    if reverse:
        flag = '--reverse'

    if not project.virtualenv_exists:
        click.echo(
            u'{0}: No virtualenv has been created for this project yet! Consider '
            u'running {1} first to automatically generate one for you or see'
            u'{2} for further instructions.'.format(
                crayons.red('Warning', bold=True),
                crayons.green('`pipenv install`'),
                crayons.green('`pipenv install --help`')
            ), err=True
        )
        sys.exit(1)


    cmd = '"{0}" {1} {2}'.format(
        python_path,
        shellquote(pipdeptree.__file__.rstrip('cdo')),
        flag
    )

    # Run dep-tree.
    c = delegator.run(cmd)

    if not bare:

        if json:
            data = []
            for d in simplejson.loads(c.out):

                if d['package']['key'] not in BAD_PACKAGES:
                    data.append(d)

            click.echo(simplejson.dumps(data, indent=4))
            sys.exit(0)
        else:
            for line in c.out.split('\n'):

                # Ignore bad packages as top level.
                if line.split('==')[0] in BAD_PACKAGES and not reverse:
                    continue

                # Bold top-level packages.
                if not line.startswith(' '):
                    click.echo(crayons.normal(line, bold=True))

                # Echo the rest.
                else:
                    click.echo(crayons.normal(line, bold=False))
    else:
        click.echo(c.out)

    # Return its return code.
    sys.exit(c.return_code)


def do_sync(
    ctx,
    install,
    dev=False,
    three=None,
    python=None,
    dry_run=False,
    bare=False,
    dont_upgrade=False,
    user=False,
    verbose=False,
    clear=False,
    unused=False,
    sequential=False
):
    requirements_dir = TemporaryDirectory(suffix='-requirements', prefix='pipenv-')
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    concurrent = (not sequential)

    ensure_lockfile()

    # Install everything.
    do_init(dev=dev, verbose=verbose, concurrent=concurrent, requirements_dir=requirements_dir)
    requirements_dir.cleanup()

    click.echo(
        crayons.green('All dependencies are now up-to-date!')
    )


def do_clean(
    ctx,
    three=None,
    python=None,
    dry_run=False,
    bare=False,
    verbose=False
):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    ensure_lockfile()

    installed_packages = delegator.run(
        '{0} freeze'.format(which('pip'))
    ).out.strip().split('\n')

    installed_package_names = []
    for installed in installed_packages:
        r = get_requirement(installed, verbose=verbose)

        # Ignore editable installations.
        if not r.editable:
            installed_package_names.append(r.name.lower())
        else:
            if verbose:
                click.echo('Ignoring {0}.'.format(repr(r.name)), err=True)

    # Remove known "bad packages" from the list.
    for bad_package in BAD_PACKAGES:
        if bad_package in installed_package_names:
            if verbose:
                click.echo('Ignoring {0}.'.format(repr(bad_package)), err=True)
            del installed_package_names[installed_package_names.index(bad_package)]

    # Intelligently detect if --dev should be used or not.
    develop = [k.lower() for k in project.lockfile_content['develop'].keys()]
    default = [k.lower() for k in project.lockfile_content['default'].keys()]

    for used_package in set(develop + default):
        if used_package in installed_package_names:
            del installed_package_names[installed_package_names.index(used_package)]

    failure = False
    for apparent_bad_package in installed_package_names:
        if dry_run:
            click.echo(apparent_bad_package)
        else:
            click.echo(crayons.white('Uninstalling {0}…'.format(repr(apparent_bad_package)), bold=True))

            # Uninstall the package.
            c = delegator.run('{0} uninstall {1} -y'.format(which('pip'), apparent_bad_package))
            if c.return_code != 0:
                failure = True

    sys.exit(int(failure))
