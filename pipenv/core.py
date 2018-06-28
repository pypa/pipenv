# -*- coding=utf-8 -*-
import os
import sys
import shutil
import signal
import json as simplejson

import click
import crayons
import delegator
from .vendor import pexpect
import pipfile

from .project import Project
from .vendor.requirementslib import Requirement
from .utils import (
    is_required_version,
    pep423_name,
    escape_grouped_arguments,
    find_windows_executable,
    temp_environ,
    fs_str,
)
from ._compat import (
    Path
)
from . import pep508checker
from .environments import (
    PIPENV_SHELL_FANCY,
    PIPENV_USE_SYSTEM,
    PIPENV_SHELL,
    PIPENV_CACHE_DIR,
)

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from .vendor.backports.shutil_get_terminal_size import get_terminal_size
else:
    from shutil import get_terminal_size


# ###################3 I PLAN TO KEEP THESE HERE. #########################


from .utils import system_which


# Packages that should be ignored later.
BAD_PACKAGES = ('setuptools', 'pip', 'wheel', 'packaging', 'distribute')


# Are we using the default Python?
USING_DEFAULT_PYTHON = True


def set_using_default_python(value):
    global USING_DEFAULT_PYTHON
    USING_DEFAULT_PYTHON = True


def which(command, location=None, allow_global=False):
    if not allow_global and location is None:
        location = project.virtualenv_location or os.environ.get('VIRTUAL_ENV')
    if not allow_global:
        if os.name == 'nt':
            p = find_windows_executable(
                os.path.join(location, 'Scripts'), command,
            )
        else:
            p = os.path.join(location, 'bin', command)
    else:
        if command == 'python':
            p = sys.executable
    if not os.path.exists(p):
        if command == 'python':
            p = sys.executable or system_which('python')
        else:
            p = system_which(command)
    return p


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""
    if allow_global:
        if 'VIRTUAL_ENV' in os.environ:
            return which('pip', location=os.environ['VIRTUAL_ENV'])

        for p in ('pip', 'pip3', 'pip2'):
            where = system_which(p)
            if where:
                return where

    return which('pip')


project = Project(which=which)


# ###########################################################################


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
        name = Requirement.from_line(names_map[fname]).name
        # Get the version info from the filenames.
        version = parse_download_fname(fname, name)
        # Get the hash of each file.
        cmd = '{0} hash "{1}"'.format(
            escape_grouped_arguments(which_pip()),
            os.sep.join([project.download_location, fname]),
        )
        c = delegator.run(cmd)
        hash = c.out.split('--hash=')[1].strip()
        # Verify we're adding the correct version from Pipfile
        # and not one from a dependency.
        specified_version = p[section].get(name, '')
        if is_required_version(version, specified_version):
            info.append(dict(name=name, version=version, hash=hash))
    return info


def activate_virtualenv(source=True):
    """Returns the string to activate a virtualenv."""
    # Suffix and source command for other shells.
    suffix = ''
    command = ' .' if source else ''
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


def do_purge(bare=False, downloads=False, allow_global=False, verbose=False):
    """Executes the purge functionality."""
    if downloads:
        if not bare:
            click.echo(
                crayons.normal(u'Clearing out downloads directory...', bold=True)
            )
        shutil.rmtree(project.download_location)
        return

    freeze = delegator.run(
        '{0} freeze'.format(
            escape_grouped_arguments(which_pip(allow_global=allow_global))
        )
    ).out
    # Remove comments from the output, if any.
    installed = [
        line
        for line in freeze.splitlines()
        if not line.lstrip().startswith('#')
    ]
    # Remove setuptools and friends from installed, if present.
    for package_name in BAD_PACKAGES:
        for i, package in enumerate(installed):
            if package.startswith(package_name):
                del installed[i]
    actually_installed = []
    for package in installed:
        try:
            dep = Requirement.from_line(package)
        except AssertionError:
            dep = None
        if dep and not dep.is_vcs and not dep.editable:
            dep = dep.name
            actually_installed.append(dep)
    if not bare:
        click.echo(
            u'Found {0} installed package(s), purging...'.format(
                len(actually_installed)
            )
        )
    command = '{0} uninstall {1} -y'.format(
        escape_grouped_arguments(which_pip(allow_global=allow_global)),
        ' '.join(actually_installed),
    )
    if verbose:
        click.echo('$ {0}'.format(command))
    c = delegator.run(command)
    if not bare:
        click.echo(crayons.blue(c.out))
        click.echo(crayons.green('Environment now purged and fresh!'))


def pip_download(package_name):
    cache_dir = Path(PIPENV_CACHE_DIR)
    pip_config = {
        'PIP_CACHE_DIR': fs_str(cache_dir.as_posix()),
        'PIP_WHEEL_DIR': fs_str(cache_dir.joinpath('wheels').as_posix()),
        'PIP_DESTINATION_DIR': fs_str(cache_dir.joinpath('pkgs').as_posix()),
    }
    for source in project.sources:
        cmd = '{0} download "{1}" -i {2} -d {3}'.format(
            escape_grouped_arguments(which_pip()),
            package_name,
            source['url'],
            project.download_location,
        )
        c = delegator.run(cmd, env=pip_config)
        if c.return_code == 0:
            break

    return c


def format_help(help):
    """Formats the help string."""
    help = help.replace('Options:', str(crayons.normal('Options:', bold=True)))
    help = help.replace(
        'Usage: pipenv',
        str('Usage: {0}'.format(crayons.normal('pipenv', bold=True))),
    )
    help = help.replace('  check', str(crayons.red('  check', bold=True)))
    help = help.replace('  clean', str(crayons.red('  clean', bold=True)))
    help = help.replace('  graph', str(crayons.red('  graph', bold=True)))
    help = help.replace(
        '  install', str(crayons.magenta('  install', bold=True))
    )
    help = help.replace('  lock', str(crayons.green('  lock', bold=True)))
    help = help.replace('  open', str(crayons.red('  open', bold=True)))
    help = help.replace('  run', str(crayons.yellow('  run', bold=True)))
    help = help.replace('  shell', str(crayons.yellow('  shell', bold=True)))
    help = help.replace('  sync', str(crayons.green('  sync', bold=True)))
    help = help.replace(
        '  uninstall', str(crayons.magenta('  uninstall', bold=True))
    )
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


def warn_in_virtualenv():
    if PIPENV_USE_SYSTEM:
        # Only warn if pipenv isn't already active.
        if 'PIPENV_ACTIVE' not in os.environ:
            click.echo(
                '{0}: Pipenv found itself running within a virtual environment, '
                'so it will automatically use that environment, instead of '
                'creating its own for any project. You can set '
                '{1} to force pipenv to ignore that environment and create '
                'its own instead.'.format(
                    crayons.green('Courtesy Notice'),
                    crayons.normal('PIPENV_IGNORE_VIRTUALENVS=1', bold=True),
                ),
                err=True,
            )


def ensure_lockfile(keep_outdated=False, pypi_mirror=None):
    """Ensures that the lockfile is up-to-date."""
    if not keep_outdated:
        keep_outdated = project.settings.get('keep_outdated')
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if project.lockfile_exists:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            click.echo(
                crayons.red(
                    u'Pipfile.lock ({0}) out of date, updating to ({1})...'.format(
                        old_hash[-6:], new_hash[-6:]
                    ),
                    bold=True,
                ),
                err=True,
            )
            do_lock(keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)
    else:
        do_lock(keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)


def do_py(system=False):
    try:
        click.echo(which('python', allow_global=system))
    except AttributeError:
        click.echo(crayons.red('No project found!'))


def do_outdated(pypi_mirror=None):
    packages = {}
    results = delegator.run('{0} freeze'.format(which('pip'))).out.strip(
    ).split(
        '\n'
    )
    results = filter(bool, results)
    for result in results:
        dep = Requirement.from_line(result)
        packages.update(dep.as_pipfile())
    updated_packages = {}
    lockfile = do_lock(write=False, pypi_mirror=pypi_mirror)
    for section in ('develop', 'default'):
        for package in lockfile[section]:
            try:
                updated_packages[package] = lockfile[section][package][
                    'version'
                ]
            except KeyError:
                pass
    outdated = []
    for package in packages:
        norm_name = pep423_name(package)
        if norm_name in updated_packages:
            if updated_packages[norm_name] != packages[package]:
                outdated.append(
                    (package, updated_packages[norm_name], packages[package])
                )
    for package, new_version, old_version in outdated:
        click.echo(
            'Package {0!r} out-of-date: {1!r} installed, {2!r} available.'.format(
                package, old_version, new_version
            )
        )
    sys.exit(bool(outdated))


def do_uninstall(
    package_name=False,
    more_packages=False,
    three=None,
    python=False,
    system=False,
    lock=False,
    all_dev=False,
    all=False,
    verbose=False,
    keep_outdated=False,
    pypi_mirror=None,
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
        click.echo(
            crayons.normal(
                u'Un-installing all packages from virtualenv...', bold=True
            )
        )
        do_purge(allow_global=system, verbose=verbose)
        sys.exit(0)
    # Uninstall [dev-packages], if --dev was provided.
    if all_dev:
        if 'dev-packages' not in project.parsed_pipfile:
            click.echo(
                crayons.normal(
                    'No {0} to uninstall.'.format(
                        crayons.red('[dev-packages]')
                    ),
                    bold=True,
                )
            )
            sys.exit(0)
        click.echo(
            crayons.normal(
                u'Un-installing {0}...'.format(crayons.red('[dev-packages]')),
                bold=True,
            )
        )
        package_names = project.dev_packages.keys()
    if package_name is False and not all_dev:
        click.echo(crayons.red('No package provided!'), err=True)
        sys.exit(1)
    for package_name in package_names:
        click.echo(u'Un-installing {0}...'.format(crayons.green(package_name)))
        cmd = '{0} uninstall {1} -y'.format(
            escape_grouped_arguments(which_pip(allow_global=system)),
            package_name,
        )
        if verbose:
            click.echo('$ {0}'.format(cmd))
        c = delegator.run(cmd)
        click.echo(crayons.blue(c.out))
        if pipfile_remove:
            in_packages = project.get_package_name_in_pipfile(
                package_name, dev=False)
            in_dev_packages = project.get_package_name_in_pipfile(
                package_name, dev=True)
            if not in_dev_packages and not in_packages:
                click.echo(
                    'No package {0} to remove from Pipfile.'.format(
                        crayons.green(package_name)
                    )
                )
                continue

            click.echo(
                u'Removing {0} from Pipfile...'.format(
                    crayons.green(package_name)
                )
            )
            # Remove package from both packages and dev-packages.
            project.remove_package_from_pipfile(package_name, dev=True)
            project.remove_package_from_pipfile(package_name, dev=False)
    if lock:
        do_lock(system=system, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)


def do_shell(three=None, python=False, fancy=False, shell_args=None):
    from .patched.pew import pew

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
                    'is set before activating shell.'.format(
                        crayons.normal('SHELL', bold=True)
                    )
                ),
                err=True,
            )
            sys.exit(1)
        click.echo(
            crayons.normal(
                'Spawning environment shell ({0}). Use {1} to leave.'.format(
                    crayons.red(shell), crayons.normal("'exit'", bold=True)
                ),
                bold=True,
            ),
            err=True,
        )
        cmd = "{0} -i'".format(shell)
        args = []
    # Standard (properly configured shell) mode:
    else:
        if project.is_venv_in_project():
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
            if project.is_venv_in_project():
                os.environ['WORKON_HOME'] = project.project_directory
            c = pexpect.spawn(
                cmd,
                args,
                dimensions=(
                    terminal_dimensions.lines, terminal_dimensions.columns
                ),
            )
    # Windows!
    except AttributeError:
        # import subprocess
        # Tell pew to use the project directory as its workon_home
        with temp_environ():
            if project.is_venv_in_project():
                os.environ['WORKON_HOME'] = project.project_directory
            pew.workon_cmd([workon_name])
            sys.exit(0)
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


def do_check(three=None, python=False, system=False, unused=False, ignore=None, args=None):
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
            click.echo(
                crayons.normal(
                    'The following dependencies appear unused, and may be safe for removal:'
                )
            )
            for dep in deps_required:
                click.echo('  - {0}'.format(crayons.green(dep)))
            sys.exit(1)
        else:
            sys.exit(0)
    click.echo(crayons.normal(u'Checking PEP 508 requirements...', bold=True))
    if system:
        python = system_which('python')
    else:
        python = which('python')
    # Run the PEP 508 checker in the virtualenv.
    c = delegator.run(
        '"{0}" {1}'.format(
            python,
            escape_grouped_arguments(pep508checker.__file__.rstrip('cdo')),
        )
    )
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
                        crayons.red(results[marker]),
                    ),
                    err=True,
                )
    if failed:
        click.echo(crayons.red('Failed!'), err=True)
        sys.exit(1)
    else:
        click.echo(crayons.green('Passed!'))
    click.echo(
        crayons.normal(u'Checking installed package safety...', bold=True)
    )
    path = pep508checker.__file__.rstrip('cdo')
    path = os.sep.join(__file__.split(os.sep)[:-1] + ['patched', 'safety.zip'])
    if not system:
        python = which('python')
    else:
        python = system_which('python')
    if ignore:
        ignored = '--ignore {0}'.format('--ignore '.join(ignore))
        click.echo(crayons.normal('Notice: Ignoring CVE(s) {0}'.format(crayons.yellow(', '.join(ignore)))), err=True)
    else:
        ignored = ''
    c = delegator.run(
        '"{0}" {1} check --json --key=1ab8d58f-5122e025-83674263-bc1e79e0 {2}'.format(
            python, escape_grouped_arguments(path), ignored
        )
    )
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
                crayons.red(installed, bold=True),
            )
        )
        click.echo('{0}'.format(description))
        click.echo()
    if not results:
        click.echo(crayons.green('All good!'))
    else:
        sys.exit(1)


def do_graph(bare=False, json=False, json_tree=False, reverse=False):
    import pipdeptree
    try:
        python_path = which('python')
    except AttributeError:
        click.echo(
            u'{0}: {1}'.format(
                crayons.red('Warning', bold=True),
                u'Unable to display currently-installed dependency graph information here. '
                u'Please run within a Pipenv project.',
            ),
            err=True,
        )
        sys.exit(1)
    if reverse and json:
        click.echo(
            u'{0}: {1}'.format(
                crayons.red('Warning', bold=True),
                u'Using both --reverse and --json together is not supported. '
                u'Please select one of the two options.',
            ),
            err=True,
        )
        sys.exit(1)
    if reverse and json_tree:
        click.echo(
            u'{0}: {1}'.format(
                crayons.red('Warning', bold=True),
                u'Using both --reverse and --json-tree together is not supported. '
                u'Please select one of the two options.',
            ),
            err=True,
        )
        sys.exit(1)
    if json and json_tree:
        click.echo(
            u'{0}: {1}'.format(
                crayons.red('Warning', bold=True),
                u'Using both --json and --json-tree together is not supported. '
                u'Please select one of the two options.',
            ),
            err=True,
        )
        sys.exit(1)
    flag = ''
    if json:
        flag = '--json'
    if json_tree:
        flag = '--json-tree'
    if reverse:
        flag = '--reverse'
    if not project.virtualenv_exists:
        click.echo(
            u'{0}: No virtualenv has been created for this project yet! Consider '
            u'running {1} first to automatically generate one for you or see'
            u'{2} for further instructions.'.format(
                crayons.red('Warning', bold=True),
                crayons.green('`pipenv install`'),
                crayons.green('`pipenv install --help`'),
            ),
            err=True,
        )
        sys.exit(1)
    cmd = '"{0}" {1} {2}'.format(
        python_path,
        escape_grouped_arguments(pipdeptree.__file__.rstrip('cdo')),
        flag,
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
        elif json_tree:
            def traverse(obj):
                if isinstance(obj, list):
                    return [traverse(package) for package in obj if package['key'] not in BAD_PACKAGES]
                else:
                    obj['dependencies'] = traverse(obj['dependencies'])
                    return obj
            data = traverse(simplejson.loads(c.out))
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
    if c.return_code != 0:
        click.echo(
            '{0} {1}'.format(
                crayons.red('ERROR: ', bold=True),
                crayons.white('{0}'.format(c.err, bold=True)),
            ),
            err=True
        )
    # Return its return code.
    sys.exit(c.return_code)


def do_clean(
    ctx, three=None, python=None, dry_run=False, bare=False, verbose=False, pypi_mirror=None
):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)
    ensure_lockfile(pypi_mirror=pypi_mirror)

    installed_package_names = []
    pip_freeze_command = delegator.run('{0} freeze'.format(which_pip()))
    for line in pip_freeze_command.out.split('\n'):
        installed = line.strip()
        if not installed or installed.startswith('#'):  # Comment or empty.
            continue
        r = Requirement.from_line(installed).requirement
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
            del installed_package_names[
                installed_package_names.index(bad_package)
            ]
    # Intelligently detect if --dev should be used or not.
    develop = [k.lower() for k in project.lockfile_content['develop'].keys()]
    default = [k.lower() for k in project.lockfile_content['default'].keys()]
    for used_package in set(develop + default):
        if used_package in installed_package_names:
            del installed_package_names[
                installed_package_names.index(used_package)
            ]
    failure = False
    for apparent_bad_package in installed_package_names:
        if dry_run:
            click.echo(apparent_bad_package)
        else:
            click.echo(
                crayons.white(
                    'Uninstalling {0}...'.format(repr(apparent_bad_package)),
                    bold=True,
                )
            )
            # Uninstall the package.
            c = delegator.run(
                '{0} uninstall {1} -y'.format(
                    which_pip(), apparent_bad_package
                )
            )
            if c.return_code != 0:
                failure = True
    sys.exit(int(failure))
