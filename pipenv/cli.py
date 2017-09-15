# -*- coding: utf-8 -*-
import contextlib
import codecs
import json
import os
import sys
import distutils.spawn
import shutil
import signal
import time
import tempfile

import background
import click
import click_completion
import crayons
import delegator
import pexpect
import requests
import pip
import pipfile
import pipdeptree
import requirements
import semver
from blindspin import spinner
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from pip.req.req_file import parse_requirements

from .project import Project
from .utils import (
    convert_deps_from_pip, convert_deps_to_pip, is_required_version,
    proper_case, pep423_name, split_vcs, resolve_deps, shellquote, is_vcs,
    python_version
)
from .__version__ import __version__
from . import pep508checker, progress
from .environments import (
    PIPENV_COLORBLIND, PIPENV_NOSPIN, PIPENV_SHELL_COMPAT,
    PIPENV_VENV_IN_PROJECT, PIPENV_USE_SYSTEM, PIPENV_TIMEOUT,
    PIPENV_SKIP_VALIDATION, PIPENV_HIDE_EMOJIS
)

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from backports.shutil_get_terminal_size import get_terminal_size
else:
    from shutil import get_terminal_size

xyzzy = """
 _______   __                                           __
/       \ /  |                                         /  |
$$$$$$$  |$$/   ______    ______   _______   __     __ $$ |
$$ |__$$ |/  | /      \  /      \ /       \ /  \   /  |$$ |
$$    $$/ $$ |/$$$$$$  |/$$$$$$  |$$$$$$$  |$$  \ /$$/ $$ |
$$$$$$$/  $$ |$$ |  $$ |$$    $$ |$$ |  $$ | $$  /$$/  $$/
$$ |      $$ |$$ |__$$ |$$$$$$$$/ $$ |  $$ |  $$ $$/    __
$$ |      $$ |$$    $$/ $$       |$$ |  $$ |   $$$/    /  |
$$/       $$/ $$$$$$$/   $$$$$$$/ $$/   $$/     $/     $$/
              $$ |
              $$ |
              $$/
"""

# Packages that should be ignored later.
BAD_PACKAGES = (
    'setuptools', 'pip', 'wheel', 'six', 'packaging', 'distribute'
    'pyparsing', 'appdirs', 'pipenv'
)

# Are we using the default Python?
USING_DEFAULT_PYTHON = True

if not PIPENV_HIDE_EMOJIS:
    now = time.localtime()

    # Halloween easter-egg.
    if ((now.tm_mon == 10) and (now.tm_day == 30)) or ((now.tm_mon == 10) and (now.tm_day == 31)):
        INSTALL_LABEL = '🎃   '

    # Chrismas easter-egg.
    elif ((now.tm_mon == 12) and (now.tm_day == 24)) or ((now.tm_mon == 12) and (now.tm_day == 25)):
        INSTALL_LABEL = '🎅   '

    else:
        INSTALL_LABEL = '🐍   '

    INSTALL_LABEL2 = crayons.white('☤  ', bold=True)
else:
    INSTALL_LABEL = '   '
    INSTALL_LABEL2 = '   '

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


def puts(s, err=False):
    """Better than click.echo, apparently."""

    if sys.version_info[1] < 3:

        if isinstance(s, unicode):
            s = s.encode('utf-8')

    return click.echo(s, err=False)


# Disable warnings for Python 2.6.
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

project = Project()


@background.task
def check_for_updates():
    """Background thread -- beautiful, isn't it?"""
    try:
        r = requests.get('https://pypi.python.org/pypi/pipenv/json', timeout=0.5)
        latest = sorted([semver.parse_version_info(v) for v in list(r.json()['releases'].keys())])[-1]
        current = semver.parse_version_info(__version__)

        if latest > current:
            puts('{0}: {1} is now available. You get bonus points for upgrading ($ {})!'.format(
                crayons.green('Courtesy Notice'),
                crayons.yellow('Pipenv {v.major}.{v.minor}.{v.patch}'.format(v=latest)),
                crayons.red('pipenv --update')
            ), err=True)
    except Exception:
        pass


def ensure_latest_self(user=False):
    """Updates Pipenv to latest version, cleverly."""
    try:
        r = requests.get('https://pypi.python.org/pypi/pipenv/json', timeout=2)
    except requests.RequestException as e:
        click.echo(crayons.red(e))
        sys.exit(1)
    latest = sorted([semver.parse_version_info(v) for v in list(r.json()['releases'].keys())])[-1]
    current = semver.parse_version_info(__version__)

    if current < latest:

        import site

        puts('{0}: {1} is now available. Automatically upgrading!'.format(
            crayons.green('Courtesy Notice'),
            crayons.yellow('Pipenv {v.major}.{v.minor}.{v.patch}'.format(v=latest)),
        ), err=True)

        # Resolve user site, enable user mode automatically.
        if site.ENABLE_USER_SITE and site.USER_SITE in sys.modules['pipenv'].__file__:
            args = ['install', '--upgrade', 'pipenv']
        else:
            args = ['install', '--user', '--upgrade', 'pipenv']

        sys.modules['pip'].main(args)

        puts('{0} to {1}!'.format(
            crayons.green('Pipenv updated'),
            crayons.yellow('{v.major}.{v.minor}.{v.patch}'.format(v=latest))
        ))
    else:
        puts(crayons.green('All good!'))


def cleanup_virtualenv(bare=True):
    """Removes the virtualenv directory from the system."""

    if not bare:
        puts(crayons.red('Environment creation aborted.'))

    try:
        # Delete the virtualenv.
        shutil.rmtree(project.virtualenv_location)
    except OSError:
        pass


def ensure_latest_pip():
    """Updates pip to the latest version."""

    # Ensure that pip is installed.
    try:
        c = delegator.run('"{0}" install pip'.format(which_pip()))

        # Check if version is out of date.
        if 'however' in c.err:
            # If version is out of date, update.
            puts(crayons.white(u'Pip is out of date… updating to latest.', bold=True))

            windows = '-m' if os.name == 'nt' else ''

            c = delegator.run('"{0}" install {1} pip --upgrade'.format(which_pip()), windows, block=False)
            puts(crayons.blue(c.out))
    except AttributeError:
        pass


def import_requirements(r=None):
    # Parse requirements.txt file with Pip's parser.
    # Pip requires a `PipSession` which is a subclass of requests.Session.
    # Since we're not making any network calls, it's initialized to nothing.

    if r:
        assert os.path.isfile(r)

    # Default path, if none is provided.
    if r is None:
        r = project.requirements_location

    reqs = [f for f in parse_requirements(r, session=pip._vendor.requests)]

    for package in reqs:
        if package.name not in BAD_PACKAGES:
            if package.link is not None:
                package_string = (
                    '-e {0}'.format(
                        package.link
                    ) if package.editable else str(package.link)
                )
                project.add_package_to_pipfile(package_string)
            else:
                project.add_package_to_pipfile(str(package.req))

    project.recase_pipfile()


def ensure_environment():
    # Skip this on Windows...
    if os.name != 'nt':
        if 'LANG' not in os.environ:
            puts(
                '{0}: the environment variable {1} is not set!'
                '\nWe recommend setting this in {2} (or equivalent) for '
                'proper expected behavior.'.format(
                    crayons.red('Warning', bold=True),
                    crayons.white('LANG', bold=True),
                    crayons.green('~/.profile')
                ), err=True
            )


def ensure_pipfile(validate=True):
    """Creates a Pipfile for the project, if it doesn't exist."""

    global USING_DEFAULT_PYTHON

    # Assert Pipfile exists.
    if project.pipfile_is_empty:

        # If there's a requirements file, but no Pipfile...
        if project.requirements_exists:
            puts(crayons.white(u'Requirements.txt found, instead of Pipfile! Converting…', bold=True))

            # Create a Pipfile...
            python = which('python') if not USING_DEFAULT_PYTHON else False
            project.create_pipfile(python=python)

            # Import requirements.txt.
            import_requirements()

            # Warn the user of side-effects.
            click.echo(
                u'{0}: Your {1} now contains pinned versions, if your {2} did. \n'
                'We recommend updating your {1} to specify the {3} version, instead.'
                ''.format(
                    crayons.red('Warning', bold=True),
                    crayons.white('Pipfile', bold=True),
                    crayons.white('requirements.txt', bold=True),
                    crayons.white('"*"', bold=True)
                )
            )

        else:
            puts(crayons.white(u'Creating a Pipfile for this project…', bold=True), err=True)

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
            puts(crayons.white(u'Fixing package names in Pipfile…', bold=True), err=True)
            project.write_toml(p)


def find_a_system_python(python):
    """Finds a system python, given a version (e.g. 2.7 / 3.6), or a full path."""
    if python.startswith('py'):
        return system_which(python)
    elif os.path.isabs(python):
        return python
    else:
        possibilities = [
            'python',
            'python{0}'.format(python[0]),
            'python{0}{1}'.format(python[0], python[2]),
            'python{0}.{1}'.format(python[0], python[2])
        ]
        for possibility in possibilities:
            # Windows compatibility.
            if os.name == 'nt':
                possibility = '{0}.exe'.format(possibility)

            version = python_version(system_which(possibility))
            if version:
                if python in version:
                    return system_which(possibility)


def ensure_python(three=None, python=None):

    global USING_DEFAULT_PYTHON

    path_to_python = None
    USING_DEFAULT_PYTHON = (three is None and not python)

    # Find out which python is desired.
    if not python:
        python = convert_three_to_python(three, python)

    if not python:
        python = project.required_python_version

    if python:
        path_to_python = find_a_system_python(python)

    if not path_to_python and python is not None:
        # We need to install Python.
        puts(
            u'{0}: Python {1} {2}'.format(
                crayons.red('Warning', bold=True),
                crayons.blue(python),
                u'was not found on your system… ',
            ), err=True
        )
        puts(
            'You can specify specific versions of Python with:\n  {0}'.format(
                crayons.red('$ pipenv --python {0}'.format(os.sep.join(('path', 'to', 'python'))))
            ), err=True
        )
        sys.exit(1)

    return path_to_python


def ensure_virtualenv(three=None, python=None):
    """Creates a virtualenv, if one doesn't exist."""

    global USING_DEFAULT_PYTHON

    if not project.virtualenv_exists:
        try:
            # Ensure environment variables are set properly.
            ensure_environment()

            # Ensure Python is available.
            python = ensure_python(three=three, python=python)

            # Create the virtualenv.
            do_create_virtualenv(python=python)

        except KeyboardInterrupt:
            # If interrupted, cleanup the virtualenv.
            cleanup_virtualenv(bare=False)
            sys.exit(1)

    # If --three, --two, or --python were passed...
    elif (python) or (three is not None):
        puts(crayons.red('Virtualenv already exists!'), err=True)
        puts(crayons.white(u'Removing existing virtualenv…', bold=True), err=True)

        USING_DEFAULT_PYTHON = False

        # Remove the virtualenv.
        cleanup_virtualenv(bare=True)

        # Call this function again.
        ensure_virtualenv(three=three, python=python)


def ensure_project(three=None, python=None, validate=True, system=False, warn=True):
    """Ensures both Pipfile and virtualenv exist for the project."""

    if not project.pipfile_exists:
        project.touch_pipfile()

    # Skip virtualenv creation when --system was used.
    if not system:
        ensure_virtualenv(three=three, python=python)

        if warn:
            # Warn users if they are using the wrong version of Python.
            if project.required_python_version:

                path_to_python = which('python')

                if project.required_python_version not in (python_version(path_to_python) or ''):
                    puts(
                        '{0}: Your Pipfile requires {1} {2}, '
                        'but you are using {3} ({4}).'.format(
                            crayons.red('Warning', bold=True),
                            crayons.white('python_version', bold=True),
                            crayons.blue(project.required_python_version),
                            crayons.blue(python_version(path_to_python)),
                            crayons.green(shorten_path(path_to_python))
                        ), err=True
                    )
                    # if not project.lockfile_exists:
                    #     puts('Pipfile.lock does not exist. Aborting.')
                    #     sys.exit(1)
                    puts(
                        '  {0} will surely fail.'
                        ''.format(crayons.red('$ pipenv check')),
                        err=True
                    )

    # Ensure the Pipfile exists.
    ensure_pipfile(validate=validate)


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
        short[-1] = str(crayons.white(short[-1], bold=True))

    return os.sep.join(short)
    # return short


def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""

    if not virtualenv:
        location = project.pipfile_location

        # Shorten the virual display of the path to the virtualenv.
        location = shorten_path(location)

        if not location:
            puts(
                'No Pipfile present at project home. Consider running '
                '{0} first to automatically generate a Pipfile for you.'
                ''.format(crayons.green('`pipenv install`')), err=True)
        elif not bare:
            puts(
                'Pipfile found at {0}.\n  Considering this to be the project home.'
                ''.format(crayons.green(location)), err=True)
        else:
            puts(location)

    else:
        location = project.virtualenv_location

        if not bare:
            puts('Virtualenv location: {0}'.format(crayons.green(location)), err=True)
        else:
            puts(location)


def do_install_dependencies(
    dev=False, only=False, bare=False, requirements=False, allow_global=False,
    ignore_hashes=False, skip_lock=False, verbose=False
):
    """"Executes the install functionality."""

    if requirements:
        bare = True

    # Load the lockfile if it exists, or if only is being used (e.g. lock is being used).
    if skip_lock or only or not project.lockfile_exists:
        if not bare:
            puts(crayons.white(u'Installing dependencies from Pipfile…', bold=True))
            lockfile = split_vcs(project._lockfile)
    else:
        if not bare:
            puts(crayons.white(u'Installing dependencies from Pipfile.lock…', bold=True))
        with open(project.lockfile_location) as f:
            lockfile = split_vcs(json.load(f))

    # Allow pip to resolve dependencies when in skip-lock mode.
    no_deps = (not skip_lock)

    deps = {}
    vcs_deps = {}

    # Add development deps if --dev was passed.
    if dev:
        deps.update(lockfile['develop'])
        vcs_deps.update(lockfile.get('develop-vcs', {}))

    # Install default dependencies, always.
    deps.update(lockfile['default'] if not only else {})
    vcs_deps.update(lockfile.get('default-vcs', {}))

    if ignore_hashes:
        # Remove hashes from generated requirements.
        for k, v in deps.items():
            if 'hash' in v:
                del v['hash']

    # Convert the deps to pip-compatible arguments.
    deps_list = [(d, ignore_hashes) for d in convert_deps_to_pip(deps, r=False)]
    failed_deps_list = []

    if len(vcs_deps):
        deps_list.extend((d, True) for d in convert_deps_to_pip(vcs_deps, r=False))

    # --requirements was passed.
    if requirements:
        puts('\n'.join(d[0] for d in deps_list))
        sys.exit(0)

    # pip install:
    for dep, ignore_hash in progress.bar(deps_list, label=INSTALL_LABEL if os.name != 'nt' else ''):

        # Install the module.
        c = pip_install(
            dep,
            ignore_hashes=ignore_hash,
            allow_global=allow_global,
            no_deps=no_deps,
            verbose=verbose
        )

        # The Installtion failed...
        if c.return_code != 0:

            # Save the Failed Dependency for later.
            failed_deps_list.append((dep, ignore_hash))

            # Alert the user.
            puts(
                '{0} {1}! Will try again.'.format(
                    crayons.red('An error occured while installing'),
                    crayons.green(dep.split('--hash')[0].strip())
                )
            )

    # Iterate over the hopefully-poorly-packaged dependencies...
    if failed_deps_list:

        puts(crayons.white(u'Installing initially–failed dependencies…', bold=True))

        for dep, ignore_hash in progress.bar(failed_deps_list, label=INSTALL_LABEL2):
            # Install the module.
            c = pip_install(
                dep,
                ignore_hashes=ignore_hash,
                allow_global=allow_global,
                no_deps=no_deps,
                verbose=verbose
            )

            # The Installtion failed...
            if c.return_code != 0:

                # We echo both c.out and c.err because pip returns error details on out.
                puts(crayons.blue(format_pip_output(c.out)))
                puts(crayons.blue(format_pip_error(c.err)))

                # Return the subprocess' return code.
                sys.exit(c.return_code)
            else:
                puts('{0} {1}{2}'.format(
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
            if os.name == 'nt':
                puts(
                    '{0} If you are running on Windows, you should use '
                    'the {1} option, instead.'
                    ''.format(
                        crayons.red('Warning!', bold=True),
                        crayons.green('--python')
                    ), err=True
                )

            return 'python2'

        elif three is True:
            if os.name == 'nt':
                puts(
                    '{0} If you are running on Windows, you should use '
                    'the {1} option, instead.'
                    ''.format(
                        crayons.red('Warning!', bold=True),
                        crayons.green('--python')
                    ), err=True
                )

            return 'python3'
    else:
        return python


def do_create_virtualenv(python=None):
    """Creates a virtualenv."""

    puts(crayons.white(u'Creating a virtualenv for this project…', bold=True), err=True)

    # The user wants the virtualenv in the project.
    if PIPENV_VENV_IN_PROJECT:
        cmd = ['virtualenv', project.virtualenv_location, '--prompt=({0})'.format(project.name)]
    else:
        # Default: use pew.
        cmd = ['pew', 'new', project.virtualenv_name, '-d']

    # Pass a Python version to virtualenv, if needed.
    if python:
        puts('{0} {1} {2}'.format(
            crayons.white('Using', bold=True),
            crayons.red(python, bold=True),
            crayons.white(u'to create virtualenv…', bold=True)
        ))

    # Use virutalenv's -p python.
    if python:
        cmd = cmd + ['-p', python]

    # Actually create the virtualenv.
    with spinner():
        try:
            c = delegator.run(cmd, block=False, timeout=PIPENV_TIMEOUT)
        except OSError:
            puts(
                '{0}: it looks like {1} is not in your {2}. '
                'We cannot continue until this is resolved.'
                ''.format(
                    crayons.red('Warning', bold=True),
                    crayons.red(cmd[0]),
                    crayons.white('PATH', bold=True)
                ), err=True
            )
            sys.exit(1)

    puts(crayons.blue(c.out), err=True)

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


def do_lock(verbose=False):
    """Executes the freeze functionality."""

    # Create the lockfile.
    lockfile = project._lockfile
    py_version = which('python') if project.required_python_version else None

    # Cleanup lockfile.
    for section in ('default', 'develop'):
        for k, v in lockfile[section].copy().items():
            if not hasattr(v, 'keys'):
                del lockfile[section][k]

    for section in ['dev_packages', 'packages']:
        # Alert the user of progress.
        puts(
            u'{0} {1} {2}'.format(
                crayons.white('Locking'),
                crayons.red('[{0}]'.format(section.replace('_', '-'))),
                crayons.white('dependencies…')
            ),
            err=True
        )

        
        for subsection in ['', 'vcs_', 'file_']:
            project_target = '{0}{1}'.format(subsection, section)
            deps = convert_deps_to_pip(getattr(project, project_target), r=False)
            default = resolve_deps(
                deps,
                sources=project.sources,
                verbose=verbose,
                python=py_version
            )
            
            action = {
                'vcs_': delegator.run('{0} freeze'.format(which_pip())).out,
                'file_': default,
                '': default
            }
            
            lockfile_section = 'default' if section == 'packages' else 'develop'
            
            if subsection == 'vcs_':
                # Add refs for VCS installs.
                # TODO: be smarter about this.
                for dep in deps:
                    for line in action.get(subsection).strip().split('\n'):
                        try:
                            installed = convert_deps_from_pip(line)
                            name = list(installed.keys())[0]
                            
                            if is_vcs(installed[name]):
                                lockfile[lockfile_section].update(installed)
                        except IndexError:
                            pass
            
            else:
                # Add dependencies to lockfile
                for dep in action.get(subsection):
                    lockfile[lockfile_section].update(
                        {
                            dep['name']: {'version': '=={0}'.format(dep['version'])}
                        }
                    )
                    lockfile[lockfile_section][dep['name']]['hashes'] = dep['hashes']

    # Run the PEP 508 checker in the virtualenv, add it to the lockfile.
    cmd = '"{0}" {1}'.format(which('python'), shellquote(pep508checker.__file__.rstrip('cdo')))
    c = delegator.run(cmd)
    lockfile['_meta']['host-environment-markers'] = json.loads(c.out)

    # Write out the lockfile.
    with open(project.lockfile_location, 'w') as f:
        json.dump(lockfile, f, indent=4, separators=(',', ': '), sort_keys=True)
        # Write newline at end of document. GH Issue #319.
        f.write('\n')

    puts('{0}'.format(crayons.white('Updated Pipfile.lock!', bold=True)), err=True)


def activate_virtualenv(source=True):
    """Returns the string to activate a virtualenv."""

    # Suffix for other shells.
    suffix = ''

    # Support for fish shell.
    if 'fish' in os.environ['SHELL']:
        suffix = '.fish'

    # Support for csh shell.
    if 'csh' in os.environ['SHELL']:
        suffix = '.csh'

    # Escape any spaces located within the virtualenv path to allow
    # for proper activation.
    venv_location = project.virtualenv_location.replace(' ', r'\ ')

    if source:
        return 'source {0}/bin/activate{1}'.format(venv_location, suffix)
    else:
        return '{0}/bin/activate'.format(venv_location)


def do_activate_virtualenv(bare=False):
    """Executes the activate virtualenv functionality."""
    # Check for environment marker, and skip if it's set.
    if 'PIPENV_ACTIVE' not in os.environ:
        if not bare:
            puts('To activate this project\'s virtualenv, run the following:\n $ {0}'.format(
                crayons.red('pipenv shell'))
            )
        else:
            puts(activate_virtualenv())


def do_purge(bare=False, downloads=False, allow_global=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            puts(crayons.white(u'Clearing out downloads directory…', bold=True))
        shutil.rmtree(project.download_location)
        return

    freeze = delegator.run('"{0}" freeze'.format(which_pip(allow_global=allow_global))).out
    installed = freeze.split()

    # Remove setuptools and friends from installed, if present.
    for package_name in BAD_PACKAGES:
        for i, package in enumerate(installed):
            if package.startswith(package_name):
                del installed[i]

    if not bare:
        puts(u'Found {0} installed package(s), purging…'.format(len(installed)))
    command = '"{0}" uninstall {1} -y'.format(which_pip(allow_global=allow_global), ' '.join(installed))
    c = delegator.run(command)

    if not bare:
        puts(crayons.blue(c.out))

        puts(crayons.green('Environment now purged and fresh!'))


def do_init(
    dev=False, requirements=False, allow_global=False, ignore_pipfile=False,
    skip_lock=False, verbose=False
):
    """Executes the init functionality."""

    if not project.virtualenv_exists:
        try:
            do_create_virtualenv()
        except KeyboardInterrupt:
            cleanup_virtualenv(bare=False)
            sys.exit(1)

    # Ensure the Pipfile exists.
    ensure_pipfile()

    # Display where the Project is established.
    if not requirements:
        do_where(bare=False)

    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if (project.lockfile_exists and not ignore_pipfile) and not skip_lock:

        # Open the lockfile.
        with codecs.open(project.lockfile_location, 'r') as f:
            lockfile = json.load(f)

        # Update the lockfile if it is out-of-date.
        p = pipfile.load(project.pipfile_location)

        # Check that the hash of the Lockfile matches the lockfile's hash.
        if not lockfile['_meta'].get('hash', {}).get('sha256') == p.hash:
            puts(crayons.red(u'Pipfile.lock out of date, updating…', bold=True), err=True)

            do_lock()

    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists and not skip_lock:
        puts(crayons.white(u'Pipfile.lock not found, creating…', bold=True), err=True)
        do_lock()

    do_install_dependencies(dev=dev, requirements=requirements, allow_global=allow_global,
                            skip_lock=skip_lock, verbose=verbose)

    # Activate virtualenv instructions.
    if not allow_global:
        do_activate_virtualenv()


def pip_install(
    package_name=None, r=None, allow_global=False, ignore_hashes=False,
    no_deps=True, verbose=False
):

    # Create files for hash mode.
    if (not ignore_hashes) and (r is None):
        r = tempfile.mkstemp(prefix='pipenv-', suffix='-requirement.txt')[1]
        with open(r, 'w') as f:
            f.write(package_name)

    # Install dependencies when a package is a VCS dependency.
    if [x for x in requirements.parse(package_name.split('--hash')[0])][0].vcs:
        no_deps = False

    # Try installing for each source in project.sources.
    for source in project.sources:
        if r:
            install_reqs = ' -r {0}'.format(r)
        elif package_name.startswith('-e '):
            install_reqs = ' -e "{0}"'.format(package_name.split('-e ')[1])
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

        if not ignore_hashes:
            install_reqs += ' --require-hashes'

        no_deps = '--no-deps' if no_deps else ''

        pip_command = '"{0}" install {3} {1} -i {2} --exists-action w'.format(
            which_pip(allow_global=allow_global),
            install_reqs,
            source['url'],
            no_deps
        )

        if verbose:
            puts('$ {0}'.format(pip_command), err=True)

        c = delegator.run(pip_command)

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


def which(command):
    if os.name == 'nt':
        if command.endswith('.py'):
            p = os.sep.join([project.virtualenv_location] + ['Scripts\{0}'.format(command)])
        else:
            p = os.sep.join([project.virtualenv_location] + ['Scripts\{0}.exe'.format(command)])
    else:
        p = os.sep.join([project.virtualenv_location] + ['bin/{0}'.format(command)])

    return p


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""
    if allow_global:
        return distutils.spawn.find_executable('pip')

    return which('pip')


def system_which(command):
    """Emulates the system's which. Returns None is not found."""

    _which = 'which' if not os.name == 'nt' else 'where'

    c = delegator.run('{0} {1}'.format(_which, command))
    try:
        # Which Not found...
        if c.return_code == 127:
            puts(
                '{}: the {} system utility is required for Pipenv to find Python installations properly.'
                '\n  Please install it.'.format(
                    crayons.red('Warning', bold=True),
                    crayons.red(_which)
                ), err=True
            )
        assert c.return_code == 0
    except AssertionError:
        return None
    return (c.out.strip() or c.err.strip())


def format_help(help):
    """Formats the help string."""
    help = help.replace('Options:', str(crayons.white('Options:', bold=True)))

    help = help.replace('Usage: pipenv', str('Usage: {0}'.format(crayons.white('pipenv', bold=True))))

    help = help.replace('  graph', str(crayons.green('  graph')))
    help = help.replace('  check', str(crayons.green('  check')))
    help = help.replace('  uninstall', str(crayons.yellow('  uninstall', bold=True)))
    help = help.replace('  install', str(crayons.yellow('  install', bold=True)))
    help = help.replace('  lock', str(crayons.red('  lock', bold=True)))
    help = help.replace('  run', str(crayons.blue('  run')))
    help = help.replace('  shell', str(crayons.blue('  shell', bold=True)))
    help = help.replace('  update', str(crayons.yellow('  update')))

    additional_help = """
Usage Examples:
   Create a new project using Python 3:
   $ {0}

   Create a new project using Python 3.6, specifically:
   $ {1}

   Install all dependencies for a project (including dev):
   $ {2}

   Create a lockfile:
   $ {3}

   Show a graph of your installed dependencies:
   $ {4}

Commands:""".format(
        crayons.red('pipenv --three'),
        crayons.red('pipenv --python 3.6'),
        crayons.red('pipenv install --dev'),
        crayons.red('pipenv lock'),
        crayons.red('pipenv graph')
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

def kr_easter_egg(package_name):
    if package_name in ['requests', 'maya', 'crayons', 'delegator.py', 'records', 'tablib', 'background', 'clint']:

        # Windows built-in terminal lacks proper emoji taste.
        if PIPENV_HIDE_EMOJIS:
            puts(u'P.S. You have excellent taste!')
        else:
            puts(u'P.S. You have excellent taste! ✨ 🍰 ✨')


@click.group(invoke_without_command=True)
@click.option('--update', is_flag=True, default=False, help="Update Pipenv & pip to latest.")
@click.option('--where', is_flag=True, default=False, help="Output project home information.")
@click.option('--venv', is_flag=True, default=False, help="Output virtualenv information.")
@click.option('--rm', is_flag=True, default=False, help="Remove the virtualenv.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--help', '-h', is_flag=True, default=None, help="Show this message then exit.")
@click.option('--jumbotron', '-j', is_flag=True, default=False, help="An easter egg, effectively.")
@click.version_option(prog_name=crayons.yellow('pipenv'), version=__version__)
@click.pass_context
def cli(
    ctx, where=False, venv=False, rm=False, bare=False, three=False,
    python=False, help=False, update=False, jumbotron=False
):

    if jumbotron:
        # Awesome sauce.
        puts(crayons.white(xyzzy, bold=True))

    if not update:
        # Spun off in background thread, not unlike magic.
        check_for_updates()
    else:
        # Update pip to latest version.
        ensure_latest_pip()

        # Upgrade self to latest version.
        ensure_latest_self()

        sys.exit()

    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            do_where(bare=bare)
            sys.exit(0)

        # --venv was passed...
        elif venv:
            # There is no virtualenv yet.
            if not project.virtualenv_exists:
                puts(crayons.red('No virtualenv has been created for this project yet!'), err=True)
                sys.exit(1)
            else:
                puts(project.virtualenv_location)
                sys.exit(0)

        # --rm was passed...
        elif rm:
            if project.virtualenv_exists:
                loc = project.virtualenv_location
                puts(
                    crayons.white(
                        u'{0} ({1})…'.format(
                            crayons.white('Removing virtualenv', bold=True),
                            crayons.green(loc)
                        )
                    )
                )

                with spinner():
                    # Remove the virtualenv.
                    cleanup_virtualenv(bare=True)
                sys.exit(0)
            else:
                puts(
                    crayons.red(
                        'No virtualenv has been created for this project yet!',
                        bold=True
                    ), err=True
                )
                sys.exit(1)

    # --two / --three was passed...
    if python or three is not None:
        ensure_project(three=three, python=python, warn=True)

    # Check this again before exiting for empty ``pipenv`` command.
    elif ctx.invoked_subcommand is None:
        # Display help to user, if no commands were passed.
        puts(format_help(ctx.get_help()))


@click.command(help="Installs provided packages and adds them to Pipfile, or (if none is given), installs all packages.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--requirements', '-r', nargs=1, default=False, help="Import a requirements.txt file.")
@click.option('--verbose', is_flag=True, default=False, help="Verbose mode.")
@click.option('--ignore-pipfile', is_flag=True, default=False, help="Ignore Pipfile when installing, using the Pipfile.lock.")
@click.option('--skip-lock', is_flag=True, default=False, help=u"Ignore locking mechanisms when installing—use the Pipfile, instead.")
def install(
    package_name=False, more_packages=False, dev=False, three=False,
    python=False, system=False, lock=True, ignore_pipfile=False,
    skip_lock=False, verbose=False, requirements=False
):

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, system=system, warn=True)

    if requirements:
        puts(crayons.white(u'Requirements file provided! Importing into Pipfile…', bold=True), err=True)
        import_requirements(r=requirements)

    # Capture -e argument and assign it to following package_name.
    more_packages = list(more_packages)
    if package_name == '-e':
        package_name = ' '.join([package_name, more_packages.pop(0)])

    # Allow more than one package to be provided.
    package_names = [package_name, ] + more_packages

    # Install all dependencies, if none was provided.
    if package_name is False:
        puts(crayons.white('No package provided, installing all dependencies.', bold=True), err=True)

        do_init(dev=dev, allow_global=system, ignore_pipfile=ignore_pipfile, skip_lock=skip_lock, verbose=verbose)
        sys.exit(0)

    for package_name in package_names:
        puts(crayons.white(u'Installing {0}…'.format(crayons.green(package_name, bold=True)), bold=True))

        # pip install:
        with spinner():
            c = pip_install(package_name, ignore_hashes=True, allow_global=system, no_deps=False, verbose=verbose)

        puts(crayons.blue(format_pip_output(c.out)))

        # Ensure that package was successfully installed.
        try:
            assert c.return_code == 0
        except AssertionError:
            puts('{0} An error occurred while installing {1}!'.format(crayons.red('Error: ', bold=True), crayons.green(package_name)))
            puts(crayons.blue(format_pip_error(c.err)))
            sys.exit(1)

        if dev:
            puts(crayons.white(u'Adding {0} to Pipfile\'s {1}…'.format(
                crayons.green(package_name),
                crayons.red('[dev-packages]')
            )))
        else:
            puts(crayons.white(u'Adding {0} to Pipfile\'s {1}…'.format(
                crayons.green(package_name),
                crayons.red('[packages]')
            )))

        # Add the package to the Pipfile.
        try:
            project.add_package_to_pipfile(package_name, dev)
        except ValueError as e:
            puts('{0} {1}'.format(crayons.red('ERROR (PACKAGE NOT INSTALLED):'), e))

        # Ego boost.
        kr_easter_egg(package_name)

    if lock and not skip_lock:
        do_lock()


@click.command(help="Un-installs a provided package and removes it from Pipfile.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--lock', is_flag=True, default=True, help="Lock afterwards.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Un-install all package from [dev-packages].")
@click.option('--all', is_flag=True, default=False, help="Purge all package(s) from virtualenv. Does not edit Pipfile.")
def uninstall(
    package_name=False, more_packages=False, three=None, python=False,
    system=False, lock=False, dev=False, all=False
):

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python)

    package_names = (package_name,) + more_packages
    pipfile_remove = True

    # Un-install all dependencies, if --all was provided.
    if all is True:
        puts(
            crayons.white(u'Un-installing all packages from virtualenv…', bold=True)
        )
        do_purge(allow_global=system)
        sys.exit(0)

    # Uninstall [dev-packages], if --dev was provided.
    if dev:
        if 'dev-packages' in project.parsed_pipfile:
            puts(
                crayons.white(u'Un-installing {0}…'.format(
                    crayons.red('[dev-packages]'))
                ), bold=True
            )
            package_names = project.parsed_pipfile['dev-packages']
            pipfile_remove = False
        else:
            puts(crayons.white('No {0} to uninstall.'.format(
                crayons.red('[dev-packages]'))), bold=True
            ),
            sys.exit(0)

    if package_name is False and not dev:
        puts(crayons.red('No package provided!'))
        sys.exit(1)

    for package_name in package_names:

        puts(u'Un-installing {0}…'.format(
            crayons.green(package_name))
        )

        c = delegator.run('"{0}" uninstall {1} -y'.format(
            which_pip(allow_global=system),
            package_name
        ))

        puts(crayons.blue(c.out))

        if pipfile_remove:
            norm_name = pep423_name(package_name)

            in_dev_packages = (norm_name in project._pipfile.get('dev-packages', {}))
            in_packages = (norm_name in project._pipfile.get('packages', {}))

            if in_dev_packages or in_packages:
                puts(
                    u'Removing {0} from Pipfile…'.format(
                        crayons.green(package_name)
                    )
                )
            else:
                puts(
                    'No package {0} to remove from Pipfile.'.format(
                        crayons.green(package_name)
                    )
                )
                continue

            # Remove package from both packages and dev-packages.
            project.remove_package_from_pipfile(package_name, dev=True)
            project.remove_package_from_pipfile(package_name, dev=False)

    if lock:
        do_lock()


@click.command(help="Generates Pipfile.lock.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--verbose', is_flag=True, default=False, help="Verbose mode.")
@click.option('--requirements', '-r', is_flag=True, default=False, help="Generate output compatible with requirements.txt.")
def lock(three=None, python=False, verbose=False, requirements=False):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python)

    if requirements:
        do_init(dev=True, requirements=requirements)

    do_lock(verbose=verbose)


def do_shell(three=None, python=False, compat=False, shell_args=None):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    # Set an environment variable, so we know we're in the environment.
    os.environ['PIPENV_ACTIVE'] = '1'

    # Support shell compatibility mode.
    if PIPENV_SHELL_COMPAT:
        compat = True

    # Compatibility mode:
    if compat:
        try:
            shell = os.environ['SHELL']
        except KeyError:
            puts(
                crayons.red(
                    'Please ensure that the {0} environment variable '
                    'is set before activating shell.'.format(crayons.white('SHELL', bold=True))
                ), err=True
            )
            sys.exit(1)

        puts(
            crayons.white(
                'Spawning environment shell ({0}).'.format(
                    crayons.red(shell)
                ), bold=True
            ), err=True
        )

        cmd = "{0} -i'".format(shell)
        args = []

    # Standard (properly configured shell) mode:
    else:
        cmd = 'pew'
        args = ["workon", project.virtualenv_name]

    # Grab current terminal dimensions to replace the hardcoded default
    # dimensions of pexpect
    terminal_dimensions = get_terminal_size()

    try:
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


@click.command(help="Spawns a shell within the virtualenv.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--compat', '-c', is_flag=True, default=False, help="Run in shell compatibility mode (for misconfigured shells).")
@click.option('--anyway', is_flag=True, default=False, help="Always spawn a subshell, even if one is already spawned.")
@click.argument('shell_args', nargs=-1)
def shell(three=None, python=False, compat=False, shell_args=None, anyway=False):

    # Prevent user from activating nested environments.
    if 'PIPENV_ACTIVE' in os.environ:
        # If PIPENV_ACTIVE is set, VIRTUAL_ENV should always be set too.
        venv_name = os.environ.get('VIRTUAL_ENV', 'UNKNOWN_VIRTUAL_ENVIRONMENT')

        if not anyway:
            puts('{0} {1} {2}\nNo action taken to avoid nested environments.'.format(
                crayons.white('Shell for'),
                crayons.green(venv_name, bold=True),
                crayons.white('already activated.', bold=True)
            ), err=True)

            sys.exit(1)

    do_shell(three=three, python=python, compat=compat, shell_args=shell_args)


def inline_activate_virtualenv():
    try:
        activate_this = which('activate_this.py')
        with open(activate_this) as f:
            code = compile(f.read(), activate_this, 'exec')
            exec(code, dict(__file__=activate_this))
    # Catch all errors, just in case.
    except Exception:
        puts(
            u'{0}: There was an unexpected error while activating your virtualenv. Continuing anyway…'
            ''.format(crayons.red('Warning', bold=True)),
            err=True
        )


@click.command(help="Spawns a command installed into the virtualenv.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.argument('command')
@click.argument('args', nargs=-1)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
def run(command, args, three=None, python=False):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    # Seperate out things that were passed in as a string.
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
            puts(
                '{0}: the command {1} could not be found within {2}.'
                ''.format(
                    crayons.red('Error', bold=True),
                    crayons.red(command),
                    crayons.white('PATH', bold=True)
                ), err=True
            )
            sys.exit(1)

        # Execute the comand.
        os.execl(command_path, command_path, *args)
        pass


@click.command(help="Checks PEP 508 markers provided in Pipfile.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
def check(three=None, python=False):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False, warn=False)

    puts(
        crayons.white(u'Checking PEP 508 requirements…', bold=True)
    )

    # Run the PEP 508 checker in the virtualenv.
    c = delegator.run('"{0}" {1}'.format(which('python'), shellquote(pep508checker.__file__.rstrip('cdo'))))
    results = json.loads(c.out)

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
                puts(
                    'Specifier {0} does not match {1} ({2}).'
                    ''.format(
                        crayons.green(marker),
                        crayons.blue(specifier),
                        crayons.red(results[marker])
                    )
                )
    if failed:
        puts(crayons.red('Failed!'))
        sys.exit(1)
    else:
        puts(crayons.green('Passed!'))


@click.command(help=u"Displays currently–installed dependency graph information.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
def graph(bare=False):
    try:
        python_path = which('python')
    except AttributeError:
        puts(
            u'{0}: {1}'.format(
                crayons.red('Warning', bold=True),
                u'Unable to display currently–installed dependency graph information here. '
                u'Please run within a Pipenv project.',
            ), err=True
        )
        sys.exit(1)

    cmd = '"{0}" {1}'.format(
        python_path,
        shellquote(pipdeptree.__file__.rstrip('cdo'))
    )

    # Run dep-tree.
    c = delegator.run(cmd)

    if not bare:

        for line in c.out.split('\n'):

            # Ignore bad packages.
            if line.split('==')[0] in BAD_PACKAGES:
                continue

            # Bold top-level packages.
            if not line.startswith(' '):
                puts(crayons.white(line, bold=True))

            # Echo the rest.
            else:
                puts(crayons.white(line, bold=False))
    else:
        puts(c.out)

    # Return its return code.
    sys.exit(c.return_code)


@click.command(help="Updates Pipenv & pip to latest, uninstalls all packages, and re-installs package(s) in [packages] to latest compatible versions.")
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Additionally install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--dry-run', is_flag=True, default=False, help="Just output outdated packages.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
def update(dev=False, three=None, python=None, dry_run=False, bare=False, dont_upgrade=False, user=False, verbose=False):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    # --dry-run:
    if dry_run:
        # dont_upgrade = True
        updates = False

        # Dev packages
        if not bare:
            puts(crayons.white(u'Checking dependencies…', bold=True), err=True)

        packages = project.packages
        if dev:
            packages.update(project.dev_packages)

        installed_packages = {}
        deps = convert_deps_to_pip(packages, r=False)
        c = delegator.run('{0} freeze'.format(which_pip()))

        for r in c.out.strip().split('\n'):
            result = convert_deps_from_pip(r)
            try:
                installed_packages[list(result.keys())[0].lower()] = result[list(result.keys())[0]][len('=='):]
            except TypeError:
                pass

        # Resolve dependency tree.
        for result in resolve_deps(deps, sources=project.sources):

            name = result['name']
            installed = result['version']

            try:
                latest = installed_packages[name]
                if installed != latest:
                    if not bare:
                        puts(
                            '{0}=={1} is available ({2} installed)!'
                            ''.format(crayons.white(name, bold=True), latest, installed)
                        )
                    else:
                        puts(
                            '{0}=={1}'.format(name, latest)
                        )
                    updates = True
            except KeyError:
                pass

        if not updates and not bare:
            puts(
                crayons.green('All good!')
            )

        sys.exit(int(updates))

    puts(
        crayons.white(u'Updating all dependencies from Pipfile…', bold=True)
    )

    do_purge()
    do_init(dev=dev, verbose=verbose)

    puts(
        crayons.green('All dependencies are now up-to-date!')
    )


# Install click commands.
cli.add_command(graph)
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(update)
cli.add_command(lock)
cli.add_command(check)
cli.add_command(shell)
cli.add_command(run)


if __name__ == '__main__':
    cli()
