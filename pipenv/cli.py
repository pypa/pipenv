# -*- coding: utf-8 -*-
import contextlib
import codecs
import json
import os
import re
import sys
import distutils.spawn
import shutil
import signal

import click
import click_completion
import crayons
import delegator
import parse
import pexpect
import requests
import pipfile
from blindspin import spinner
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from .project import Project
from .utils import convert_deps_from_pip, convert_deps_to_pip, is_required_version
from .__version__ import __version__
from . import pep508checker
from .environments import PIPENV_COLORBLIND, PIPENV_NOSPIN, PIPENV_SHELL_COMPAT, PIPENV_VENV_IN_PROJECT

try:
    from HTMLParser import HTMLParser
except ImportError:
    from html.parser import HTMLParser

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from backports.shutil_get_terminal_size import get_terminal_size
else:
    from shutil import get_terminal_size

#  ___  _       ___
# | . \<_> ___ | __>._ _  _ _
# |  _/| || . \| _> | ' || | |
# |_|  |_||  _/|___>|_|_||__/
#         |_|

# Enable shell completion.
click_completion.init()

# Disable colors, for the soulless.
if PIPENV_COLORBLIND:
    crayons.disable()

# Disable spinner, for cleaner build logs (the unworthy).
if PIPENV_NOSPIN:
    @contextlib.contextmanager
    def spinner():
        yield

# Disable warnings for Python 2.6.
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

project = Project()


def ensure_latest_pip():
    """Updates pip to the latest version."""

    # Ensure that pip is installed.
    c = delegator.run('"{0}" install pip'.format(which_pip()))

    # Check if version is out of date.
    if 'however' in c.err:
        # If version is out of date, update.
        click.echo(crayons.yellow('Pip is out of date... updating to latest.'))
        c = delegator.run('"{0}" install pip --upgrade'.format(which_pip()), block=False)
        click.echo(crayons.blue(c.out))


def ensure_pipfile(validate=True):
    """Creates a Pipfile for the project, if it doesn't exist."""

    # Assert Pipfile exists.
    if not project.pipfile_exists:

        click.echo(crayons.yellow('Creating a Pipfile for this project...'), err=True)

        # Create the pipfile if it doesn't exist.
        project.create_pipfile()

    # Validate the Pipfile's contents.
    if validate and project.virtualenv_exists:
        # Ensure that Pipfile is using proper casing.
        p = project.parsed_pipfile
        changed = ensure_proper_casing(pfile=p)

        # Write changes out to disk.
        if changed:
            click.echo(crayons.yellow('Fixing package names in Pipfile...'), err=True)
            project.write_toml(p)


def ensure_virtualenv(three=None, python=None):
    """Creates a virtualenv, if one doesn't exist."""

    if not project.virtualenv_exists:
        do_create_virtualenv(three=three, python=python)

    # If --three, --two, or --python were passed...
    elif (python) or (three is not None):
        click.echo(crayons.red('Virtualenv already exists!'), err=True)
        click.echo(crayons.yellow('Removing existing virtualenv...'), err=True)

        # Remove the virtualenv.
        shutil.rmtree(project.virtualenv_location)

        # Call this function again.
        ensure_virtualenv(three=three, python=python)


def ensure_project(three=None, python=None, validate=True):
    """Ensures both Pipfile and virtualenv exist for the project."""
    ensure_pipfile(validate=validate)
    ensure_virtualenv(three=three, python=python)


def ensure_proper_casing(pfile):
    """Ensures proper casing of Pipfile packages, writes changes to disk."""

    casing_changed = proper_case_section(pfile.get('packages', {}))
    casing_changed |= proper_case_section(pfile.get('dev-packages', {}))

    return casing_changed


def proper_case_section(section):
    """Verify proper casing is retrieved, when available, for each
    dependency in the section.
    """
    # Casing for section
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


def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""

    if not virtualenv:
        location = project.pipfile_location

        if not location:
            click.echo('No Pipfile present at project home. Consider running {0} first to automatically generate a Pipfile for you.'.format(crayons.green('`pipenv install`')), err=True)
        elif not bare:
            click.echo('Pipfile found at {0}. Considering this to be the project home.'.format(crayons.green(location)), err=True)
        else:
            click.echo(location)

    else:
        location = project.virtualenv_location

        if not bare:
            click.echo('Virtualenv location: {0}'.format(crayons.green(location)), err=True)
        else:
            click.echo(location)


def do_install_dependencies(dev=False, only=False, bare=False, requirements=False, allow_global=False):
    """"Executes the install functionality."""

    if requirements:
        bare = True

    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location)

    # Load the lockfile if it exists, or if only is being used (e.g. lock is being used).
    if only or not project.lockfile_exists:
        if not bare:
            click.echo(crayons.yellow('Installing dependencies from Pipfile...'))
            lockfile = json.loads(p.lock())
    else:
        if not bare:
            click.echo(crayons.yellow('Installing dependencies from Pipfile.lock...'))
        with open(project.lockfile_location) as f:
            lockfile = json.load(f)

    # Install default dependencies, always.
    deps = lockfile['default'] if not only else {}

    # Add development deps if --dev was passed.
    if dev:
        deps.update(lockfile['develop'])

    # Convert the deps to pip-compatible arguments.
    deps_path = convert_deps_to_pip(deps)

    # --requirements was passed.
    if requirements:
        with open(deps_path) as f:
            click.echo(f.read())
            sys.exit(0)

    # pip install:
    with spinner():
        c = pip_install(r=deps_path, allow_global=allow_global)

    if c.return_code != 0:
        click.echo(crayons.red('An error occured while installing!'))
        click.echo(crayons.blue(format_pip_error(c.err)))
        sys.exit(c.return_code)

    if not bare:
        click.echo(crayons.blue(format_pip_output(c.out, r=deps_path)))

    # Cleanup the temp requirements file.
    if requirements:
        os.remove(deps_path)


def do_download_dependencies(dev=False, only=False, bare=False):
    """"Executes the download functionality."""

    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location)

    # Load the Pipfile.
    if not bare:
        click.echo(crayons.yellow('Downloading dependencies from Pipfile...'))
    lockfile = json.loads(p.lock())

    # Install default dependencies, always.
    deps = lockfile['default'] if not only else {}

    # Add development deps if --dev was passed.
    if dev:
        deps.update(lockfile['develop'])

    # Convert the deps to pip-compatible arguments.
    deps = convert_deps_to_pip(deps, r=False)

    # Actually install each dependency into the virtualenv.
    name_map = {}
    for package_name in deps:

        if not bare:
            click.echo('Downloading {0}...'.format(crayons.green(package_name)))

        # pip install:
        c = pip_download(package_name)

        if not bare:
            click.echo(crayons.blue(c.out))

        parsed_output = parse_install_output(c.out)
        for filename, name in parsed_output:
            name_map[filename] = name

    return name_map


def parse_install_output(output):
    """Parse output from pip download to get name and file mappings
    for all dependencies and their sub dependencies.

    This is required for proper file hashing with --require-hashes.
    """
    output_sections = output.split('Collecting ')
    names = []

    for section in output_sections:
        lines = section.split('\n')

        # Strip dependency parens from name line. e.g. package (from other_package)
        name = lines[0].split('(')[0]
        # Strip version specification. e.g. package; python-version=2.6
        name = name.split(';')[0]

        for line in lines:
            r = parse.parse('Saved {file}', line.strip())
            if r is None:
                r = parse.parse('Using cached {file}', line.strip())
            if r is None:
                continue

            fname = r['file'].split(os.sep)[-1]
            # Unencode percent-encoded values like ``!`` in version number.
            fname = requests.compat.unquote(fname)

            names.append((fname, name.strip()))
            break

    return names


def do_create_virtualenv(three=None, python=None):
    """Creates a virtualenv."""
    click.echo(crayons.yellow('Creating a virtualenv for this project...'), err=True)

    # The user wants the virtualenv in the project.
    if PIPENV_VENV_IN_PROJECT:
        cmd = ['virtualenv', project.virtualenv_location, '--prompt=({0})'.format(project.name)]
    else:
        # Default: use pew.
        cmd = ['pew', 'new', project.virtualenv_name, '-d']

    # Pass a Python version to virtualenv, if needed.
    if python:
        click.echo('{0} {1} {2}'.format(crayons.yellow('Using'), crayons.red(python), crayons.yellow('to create virtualenv...')))
    elif three is False:
        python = 'python2'
    elif three is True:
        python = 'python3'

    if python:
        cmd = cmd + ['-p', python]

    # Actually create the virtualenv.
    with spinner():
        c = delegator.run(cmd, block=False)
    click.echo(crayons.blue(c.out), err=True)

    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)


def is_version(text):
    return re.match('^[\d]+\.[\d]+.*', text) or False


def parse_download_fname(fname, name):
    fname, fextension = os.path.splitext(fname)

    if fextension == '.whl':
        fname = '-'.join(fname.split('-')[:-3])

    if fname.endswith('.tar'):
        fname, _ = os.path.splitext(fname)

    # Substring out package name (plus dash) from file name to get version.
    version = fname[len(name)+1:]

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
        c = delegator.run('"{0}" hash "{1}"'.format(which_pip(), os.sep.join([project.download_location, fname])))
        hash = c.out.split('--hash=')[1].strip()

        # Verify we're adding the correct version from Pipfile
        # and not one from a dependency.
        specified_version = p[section].get(name, '')
        if is_required_version(version, specified_version):
            info.append(dict(name=name, version=version, hash=hash))

    return info


def do_lock():
    """Executes the freeze functionality."""

    # Purge the virtualenv download dir, for development dependencies.
    do_purge(downloads=True, bare=True)

    click.echo(crayons.yellow('Locking {0} dependencies...'.format(crayons.red('[dev-packages]'))))

    with spinner():
        # Install only development dependencies.
        names_map = do_download_dependencies(dev=True, only=True, bare=True)

    # Load the Pipfile and generate a lockfile.
    p = pipfile.load(project.pipfile_location)
    lockfile = json.loads(p.lock())

    # Pip freeze development dependencies.
    with spinner():
        results = get_downloads_info(names_map, 'dev-packages')

    # Clear generated lockfile before updating.
    lockfile['develop'] = {}

    # Add Development dependencies to lockfile.
    for dep in results:
        if dep:
            lockfile['develop'].update({dep['name']: {'hash': dep['hash'], 'version': '=={0}'.format(dep['version'])}})

    with spinner():
        # Purge the virtualenv download dir, for default dependencies.
        do_purge(downloads=True, bare=True)

    click.echo(crayons.yellow('Locking {0} dependencies...'.format(crayons.red('[packages]'))))

    with spinner():
        # Install only development dependencies.
        names_map = do_download_dependencies(bare=True)

    # Pip freeze default dependencies.
    results = get_downloads_info(names_map, 'packages')

    # Clear generated lockfile before updating.
    lockfile['default'] = {}

    # Add default dependencies to lockfile.
    for dep in results:
        if dep:
            lockfile['default'].update({dep['name']: {'hash': dep['hash'], 'version': '=={0}'.format(dep['version'])}})

    # Write out lockfile.
    with open(project.lockfile_location, 'w') as f:
        f.write(json.dumps(lockfile, indent=4, separators=(',', ': ')))

    # Purge the virtualenv download dir, for next time.
    with spinner():
        do_purge(downloads=True, bare=True)

    click.echo('{0} Pipfile.lock{1}'.format(crayons.yellow('Updated'), crayons.yellow('!')))


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
            click.echo('To activate this project\'s virtualenv, run the following:\n $ {0}'.format(
                crayons.red('pipenv shell'))
            )
        else:
            click.echo(activate_virtualenv())


def do_purge(bare=False, downloads=False, allow_global=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            click.echo(crayons.yellow('Clearing out downloads directory...'))
        shutil.rmtree(project.download_location)
        return

    freeze = delegator.run('"{0}" freeze'.format(which_pip(allow_global=allow_global))).out
    installed = freeze.split()

    # Remove setuptools and friends from installed, if present.
    for package_name in ['setuptools', 'pip', 'wheel', 'six', 'packaging', 'pyparsing', 'appdirs']:
        for i, package in enumerate(installed):
            if package.startswith(package_name):
                del installed[i]

    if not bare:
        click.echo('Found {0} installed package(s), purging...'.format(len(installed)))
    command = '"{0}" uninstall {1} -y'.format(which_pip(allow_global=allow_global), ' '.join(installed))
    c = delegator.run(command)

    if not bare:
        click.echo(crayons.blue(c.out))

        click.echo(crayons.yellow('Environment now purged and fresh!'))


def do_init(dev=False, requirements=False, skip_virtualenv=False, allow_global=False):
    """Executes the init functionality."""

    ensure_pipfile()

    # Display where the Project is established.
    if not requirements:
        do_where(bare=False)

    if not project.virtualenv_exists:
        do_create_virtualenv()

    # Write out the lockfile if it doesn't exist.
    if project.lockfile_exists:

        # Open the lockfile.
        with codecs.open(project.lockfile_location, 'r') as f:
            lockfile = json.load(f)

        # Update the lockfile if it is out-of-date.
        p = pipfile.load(project.pipfile_location)

        # Check that the hash of the Lockfile matches the lockfile's hash.
        if not lockfile['_meta'].get('hash', {}).get('sha256') == p.hash:
            click.echo(crayons.red('Pipfile.lock out of date, updating...'), err=True)

            do_lock()

    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists:
        click.echo(crayons.yellow('Pipfile.lock not found, creating...'), err=True)
        do_lock()

    do_install_dependencies(dev=dev, requirements=requirements, allow_global=allow_global)

    # Activate virtualenv instructions.
    do_activate_virtualenv()


def pip_install(package_name=None, r=None, allow_global=False):
    # try installing for each source in project.sources
    for source in project.sources:
        if r:
            c = delegator.run('"{0}" install -r {1} --require-hashes -i {2}'.format(which_pip(allow_global=allow_global), r, source['url']))
        else:
            c = delegator.run('"{0}" install "{1}" -i {2}'.format(which_pip(allow_global=allow_global), package_name, source['url']))

        if c.return_code == 0:
            break
    # return the result of the first one that runs ok or the last one that didn't work
    return c


def pip_download(package_name):
    for source in project.sources:
        cmd = '"{0}" download "{1}" -i {2} -d {3}'.format(which_pip(), package_name, source['url'], project.download_location)
        c = delegator.run(cmd)
        if c.return_code == 0:
            break
    return c


def which(command):
    return os.sep.join([project.virtualenv_location] + ['bin/{0}'.format(command)])


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""
    if allow_global:
        return distutils.spawn.find_executable('pip')

    return which('pip')


def proper_case(package_name):

    # Capture tag contents here.
    collected = []

    class SimpleHTMLParser(HTMLParser):
        def handle_data(self, data):
            # Remove extra blank data from https://pypi.org/simple
            data = data.strip()
            if len(data) > 2:
                collected.append(data)

    # Hit the simple API.
    r = requests.get('https://pypi.org/simple/{0}'.format(package_name))
    if not r.ok:
        raise IOError('Unable to find package {0} in PyPI repository.'.format(crayons.green(package_name)))

    # Parse the HTML.
    parser = SimpleHTMLParser()
    parser.feed(r.text)

    r = parse.parse('Links for {name}', collected[1])
    good_name = r['name']

    return good_name


def format_help(help):
    """Formats the help string."""
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

   Install all dependencies for a project (including dev):
   $ {1}

   Create a lockfile:
   $ {2}

Commands:""".format(
        crayons.red('pipenv --three'),
        crayons.red('pipenv install --dev'),
        crayons.red('pipenv lock')
    )

    help = help.replace('Commands:', additional_help)

    return help


def format_pip_error(error):
    error = error.replace('Expected', str(crayons.green('Expected', bold=True)))
    error = error.replace('Got', str(crayons.red('Got', bold=True)))
    error = error.replace('THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE', str(crayons.red('THESE PACKAGES DO NOT MATCH THE HASHES FROM Pipfile.lock!', bold=True)))
    error = error.replace('someone may have tampered with them', str(crayons.red('someone may have tampered with them')))
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

def easter_egg(package_name):
    if package_name in ['requests', 'maya', 'crayons', 'delegator.py', 'records', 'tablib']:
        click.echo(u'P.S. You have excellent taste! ✨ 🍰 ✨')


@click.group(invoke_without_command=True)
@click.option('--where', is_flag=True, default=False, help="Output project home information.")
@click.option('--venv', is_flag=True, default=False, help="Output virtualenv information.")
@click.option('--rm', is_flag=True, default=False, help="Remove the virtualenv.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--help', '-h', is_flag=True, default=None, help="Show this message then exit.")
@click.version_option(prog_name=crayons.yellow('pipenv'), version=__version__)
@click.pass_context
def cli(ctx, where=False, venv=False, rm=False, bare=False, three=False, python=False, help=False):

    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            do_where(bare=bare)
            sys.exit(0)

        # --venv was passed...
        elif venv:

            with spinner():
                loc = project.virtualenv_location

            # There is no virtualenv yet.
            if not project.virtualenv_exists:
                click.echo(crayons.red('No virtualenv has been created for this project yet!'), err=True)
                sys.exit(1)
            else:
                click.echo(project.virtualenv_location)
                sys.exit(0)

        # --rm was passed...
        elif rm:

            with spinner():
                loc = project.virtualenv_location

            if project.virtualenv_exists:
                click.echo(crayons.yellow('{0} ({1})...'.format(crayons.yellow('Removing virtualenv'), crayons.green(loc))))
                with spinner():
                    # Remove the virtualenv.
                    shutil.rmtree(project.virtualenv_location)
                sys.exit(0)
            else:
                click.echo(crayons.red('No virtualenv has been created for this project yet!'), err=True)
                sys.exit(1)

        # --two / --three was passed...
        if python or three is not None:
            ensure_project(three=three, python=python)

        else:
            # Display help to user, if no commands were passed.
            click.echo(format_help(ctx.get_help()))


@click.command(help="Installs provided packages and adds them to Pipfile, or (if none is given), installs all packages.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--lock', is_flag=True, default=False, help="Lock afterwards.")
def install(package_name=False, more_packages=False, dev=False, three=False, python=False, system=False, lock=False):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python)

    # Allow more than one package to be provided.
    package_names = (package_name,) + more_packages

    # Install all dependencies, if none was provided.
    if package_name is False:
        click.echo(crayons.yellow('No package provided, installing all dependencies.'), err=True)
        do_init(dev=dev, allow_global=system)
        sys.exit(0)

    for package_name in package_names:
        click.echo('Installing {0}...'.format(crayons.green(package_name)))

        # pip install:
        with spinner():
            c = pip_install(package_name, allow_global=system)

        click.echo(crayons.blue(format_pip_output(c.out)))

        # TODO: This
        # Ensure that package was successfully installed.
        try:
            assert c.return_code == 0
        except AssertionError:
            click.echo('{0} An error occurred while installing {1}!'.format(crayons.red('Error: '), crayons.green(package_name)))
            click.echo(crayons.blue(format_pip_error(c.err)))
            sys.exit(1)

        if dev:
            click.echo('Adding {0} to Pipfile\'s {1}...'.format(crayons.green(package_name), crayons.red('[dev-packages]')))
        else:
            click.echo('Adding {0} to Pipfile\'s {1}...'.format(crayons.green(package_name), crayons.red('[packages]')))

        # Add the package to the Pipfile.
        project.add_package_to_pipfile(package_name, dev)

        # Ego boost.
        easter_egg(package_name)

        if lock:
            do_lock()


@click.command(help="Un-installs a provided package and removes it from Pipfile, or (if none is given), un-installs all packages.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--lock', is_flag=True, default=False, help="Lock afterwards.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Un-install all package from [dev-packages].")
@click.option('--all', is_flag=True, default=False, help="Purge all package(s) from virtualenv. Does not edit Pipfile.")
def uninstall(package_name=False, more_packages=False, three=None, python=False, system=False, lock=False, dev=False, all=False):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python)

    package_names = (package_name,) + more_packages
    pipfile_remove = True

    # Un-install all dependencies, if --all was provided.
    if all is True:
        if not dev:
            click.echo(crayons.yellow('Un-installing all packages from virtualenv...'))
            do_purge(allow_global=system)
            sys.exit(0)

    # Uninstall [dev-packages], if --dev was provided.
    if dev:
        if 'dev-packages' in project.parsed_pipfile:
            click.echo(crayons.yellow('Un-installing {0}...'.format(crayons.red('[dev-packages]'))))
            package_names = project.parsed_pipfile['dev-packages']
            pipfile_remove = False
        else:
            click.echo(crayons.yellow('No {0} to uninstall.'.format(crayons.red('[dev-packages]'))))
            sys.exit(0)

    if package_name is False and not dev:
        click.echo(crayons.red('No package provided!'))
        sys.exit(1)

    for package_name in package_names:

        click.echo('Un-installing {0}...'.format(crayons.green(package_name)))

        c = delegator.run('"{0}" uninstall {1} -y'.format(which_pip(allow_global=system), package_name))
        click.echo(crayons.blue(c.out))

        if pipfile_remove:
            if dev:
                click.echo('Removing {0} from Pipfile\'s {1}...'.format(crayons.green(package_name), crayons.red('[dev-packages]')))
            else:
                click.echo('Removing {0} from Pipfile\'s {1}...'.format(crayons.green(package_name), crayons.red('[packages]')))

            project.remove_package_from_pipfile(package_name, dev)

        if lock:
            do_lock()


@click.command(help="Generates Pipfile.lock.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--requirements', '-r', is_flag=True, default=False, help="Generate output compatible with requirements.txt.")
def lock(three=None, python=False, requirements=False):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python)

    if requirements:
        do_init(dev=True, requirements=requirements)
    do_lock()


@click.command(help="Spawns a shell within the virtualenv.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--compat', '-c', is_flag=True, default=False, help="Run in shell compatibility mode (for misconfigured shells).")
@click.argument('shell_args', nargs=-1)
def shell(three=None, python=False, compat=False, shell_args=None):
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
            click.echo(crayons.red('Windows is not currently supported.'))
            sys.exit(1)

        click.echo(crayons.yellow('Spawning environment shell ({0}).'.format(crayons.red(shell))))

        cmd = "{0} -i'".format(shell)
        args = []

    # Standard (properly configured shell) mode:
    else:
        cmd = 'pew'
        args = ["workon", project.virtualenv_name]

    # Grab current terminal dimensions to replace the hardcoded default
    # dimensions of pexpect
    terminal_dimensions = get_terminal_size()

    c = pexpect.spawn(
        cmd,
        args,
        dimensions=(
            terminal_dimensions.lines,
            terminal_dimensions.columns
        )
    )

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
    c.interact()
    c.close()
    sys.exit(c.exitstatus)


@click.command(help="Spawns a command installed into the virtualenv.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.argument('command')
@click.argument('args', nargs=-1)
@click.option('--no-interactive', is_flag=True, default=False, help="Run the command in non-interactive mode.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
def run(command, args, no_interactive=False, three=None, python=False):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    # Automatically enable --no-interactive, when applicable.
    if not sys.stdout.isatty():
        no_interactive = True

    # Spawn the new process, and interact with it.
    try:
        c = pexpect.spawn(which(command), list(args))
    except pexpect.exceptions.ExceptionPexpect:
        click.echo(crayons.red('The command ({0}) was not found within the virtualenv!'.format(which(command))))
        sys.exit(1)

    # Interact with the new shell.
    if no_interactive:
        c.wait()
    else:
        c.interact()
        c.close()
    sys.exit(c.exitstatus)


@click.command(help="Checks PEP 508 markers provided in Pipfile.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
def check(three=None, python=False):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    click.echo(crayons.yellow('Checking PEP 508 requirements...'))

    # Run the PEP 508 checker in the virtualenv.
    c = delegator.run('"{0}" {1}'.format(which('python'), pep508checker.__file__.rstrip('cdo')))
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
                    click.echo('Specifier {0} does not match {1} ({2}).'.format(crayons.green(marker), crayons.blue(specifier), crayons.red(results[marker])))
    if failed:
        click.echo(crayons.red('Failed!'))
        sys.exit(1)
    else:
        click.echo(crayons.green('Passed!'))


@click.command(help="Updates pip to latest version, uninstalls all packages, and re-installs them to latest compatible versions.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
def update(dev=False, three=None, python=None):

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False)

    # Update pip to latest version.
    ensure_latest_pip()

    click.echo(crayons.yellow('Updating all dependencies from Pipfile...'))

    do_purge()
    do_init(dev=dev)

    click.echo(crayons.yellow('All dependencies are now up-to-date!'))


# Install click commands.
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(update)
cli.add_command(lock)
cli.add_command(check)
cli.add_command(shell)
cli.add_command(run)


if __name__ == '__main__':
    cli()
