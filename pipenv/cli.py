# -*- coding: utf-8 -*-
import codecs
import json
import os
import sys
import distutils.spawn
import shutil
import signal

import click
import delegator
import parse
import pexpect
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from . import _pipfile as pipfile
from .project import Project
from .utils import convert_deps_from_pip, convert_deps_to_pip
from .__version__ import __version__
from . import pep508checker

try:
    from HTMLParser import HTMLParser
except ImportError:
    from html.parser import HTMLParser

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from backports.shutil_get_terminal_size import get_terminal_size

else:
    from shutil import get_terminal_size


# Disable warnings for Python 2.6.
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

project = Project()


def ensure_latest_pip():
    """Updates pip to the latest version."""

    # Ensure that pip is installed.
    c = delegator.run('{0} install pip'.format(which_pip()))

    # Check if version is out of date.
    if 'however' in c.err:
        # If version is out of date, update.
        click.secho('Pip is out of date... updating to latest.', fg='yellow')
        c = delegator.run('{0} install pip --upgrade'.format(which_pip()), block=False)
        click.secho(c.out, fg='blue')


def ensure_pipfile():
    """Creates a Pipfile for the project, if it doesn't exist."""

    # Assert Pipfile exists.
    if not project.pipfile_exists:

        click.secho('Creating a Pipfile for this project...', fg='yellow', err=True)

        # Create the pipfile if it doesn't exist.
        project.create_pipfile()

    # Ensure that the Pipfile is using proper casing.
    ensure_proper_casing()


def ensure_virtualenv(three=None):
    """Creates a virtualenv, if one doesn't exist."""

    if not project.virtualenv_exists:
        do_create_virtualenv(three=three)

    # If --three / --two were passed...
    elif three is not None:
        click.secho('Virtualenv already exists!', fg='red', err=True)
        click.secho('Removing existing virtualenv...', fg='yellow', err=True)

        # Remove the virtualenv.
        shutil.rmtree(project.virtualenv_location)

        # Call this function again.
        ensure_virtualenv(three=three)


def ensure_project(three=None):
    """Ensures both Pipfile and virtualenv exist for the project."""
    ensure_pipfile()
    ensure_virtualenv(three=three)


def ensure_proper_casing():
    """Ensures proper casing of Pipfile packages, writes to disk."""
    p = project.parsed_pipfile

    casing_changed = False

    def proper_case_section(section):
        # Casing for section
        if section in p:
            # Replace each package with proper casing.
            for dep in p[section]:

                # Get new casing for package name.
                new_casing = proper_case(dep)

                # Mark casing as changed, if it did.
                if new_casing != dep:
                    casing_changed = True

                # Replace old value with new value.
                old_value = p[section][dep]
                del p[section][dep]
                p[section][new_casing] = old_value

    proper_case_section('packages')
    proper_case_section('dev-packages')

    if casing_changed:
        click.secho('Fixing package names in Pipfile...', fg='yellow')

    # Write pipfile out to disk.
    project.write(p)


def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""

    if not virtualenv:
        location = project.pipfile_location

        if not location:
            click.echo('No Pipfile present at project home. Consider running {0} first to automatically generate a Pipfile for you.'.format(
                click.style('`pipenv install`', fg='green')), err=True)
        elif not bare:
            click.echo('Pipfile found at {0}. Considering this to be the project home.'.format(click.style(location, fg='green')), err=True)
        else:
            click.echo(location)

    else:
        location = project.virtualenv_location

        if not bare:
            click.echo('Virtualenv location: {0}'.format(click.style(location, fg='green')))
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
            click.secho('Installing dependencies from Pipfile...', fg='yellow')
            lockfile = json.loads(p.lock())
    else:
        if not bare:
            click.secho('Installing dependencies from Pipfile.lock...', fg='yellow')
        with open(project.lockfile_location, 'r') as f:
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
        with open(deps_path, 'r') as f:
            click.echo(f.read())
            sys.exit(0)

    # pip install:
    c = pip_install(r=deps_path, allow_global=allow_global)
    if not c.return_code == 0:
        click.secho('An error occured while installing!', fg='red')
        click.secho(format_pip_error(c.err), fg='blue')

    if not bare:
        click.secho(format_pip_output(c.out, r=deps_path), fg='blue')


def do_download_dependencies(dev=False, only=False, bare=False):
    """"Executes the download functionality."""

    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location)

    # Load the Pipfile.
    if not bare:
        click.secho('Downloading dependencies from Pipfile...', fg='yellow')
    lockfile = json.loads(p.lock())

    # Install default dependencies, always.
    deps = lockfile['default'] if not only else {}

    # Add development deps if --dev was passed.
    if dev:
        deps.update(lockfile['develop'])

    # Convert the deps to pip-compatible arguments.
    deps = convert_deps_to_pip(deps, r=False)

    # Actually install each dependency into the virtualenv.
    for package_name in deps:

        if not bare:
            click.secho('Downloading {0}...'.format(click.style(package_name, fg='green')))

        # pip install:
        c = pip_download(package_name)

        if not bare:
            click.secho(c.out, fg='blue')


def do_create_virtualenv(three=None):
    """Creates a virtualenv."""
    click.secho('Creating a virtualenv for this project...', fg='yellow')

    # The command to create the virtualenv.
    cmd = ['virtualenv', project.virtualenv_location, '--prompt=({0})'.format(project.name)]

    # Pass a Python version to virtualenv, if needed.
    if three is False:
        cmd = cmd + ['-p', 'python2']
    if three is True:
        cmd = cmd + ['-p', 'python3']

    # Actually create the virtualenv.
    c = delegator.run(cmd, block=False)
    click.secho(c.out, fg='blue')

    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)


def parse_download_fname(fname):

    # Use Parse to attempt to parse filenames for metadata.
    r = parse.parse('{name}-{version}.tar.gz', fname)
    if not r:
        r = parse.parse('{name}-{version}.zip', fname)
    if not r:
        r = parse.parse('{name}-{version}-{extra}.{ext}', fname)

    name = r['name']
    version = r['version']

    # Support for requirements-parser-0.1.0.tar.gz
    # TODO: Some versions might actually have dashes, will need to figure that out.
    # Will likely have to check of '-' comes at beginning or end of version.
    if '-' in version:
        name = '-'.join([name] + version.split('-')[:-1])
        version = version.split('-')[-1]

    return name, version


def get_downloads_info():
    info = []

    for fname in os.listdir(project.download_location):

        # Get the version info from the filenames.
        name, version = parse_download_fname(fname)

        # Get the hash of each file.
        c = delegator.run('{0} hash {1}'.format(which_pip(), os.sep.join([project.download_location, fname])))
        hash = c.out.split('--hash=')[1].strip()

        info.append(dict(name=name, version=version, hash=hash))

    return info


def do_lock():
    """Executes the freeze functionality."""

    # Purge the virtualenv download dir, for development dependencies.
    do_purge(downloads=True, bare=True)

    click.secho('Locking {0} dependencies...'.format(click.style('[dev-packages]', fg='red')), fg='yellow')

    # Install only development dependencies.
    do_download_dependencies(dev=True, only=True, bare=True)

    # Load the Pipfile and generate a lockfile.
    p = pipfile.load(project.pipfile_location)
    lockfile = json.loads(p.lock())

    # Pip freeze development dependencies.
    results = get_downloads_info()

    # Add Development dependencies to lockfile.
    for dep in results:
        if dep:
            lockfile['develop'].update({dep['name']: {'hash': dep['hash'], 'version': '=={0}'.format(dep['version'])}})

    # Purge the virtualenv download dir, for default dependencies.
    do_purge(downloads=True, bare=True)

    click.secho('Locking {0} dependencies...'.format(click.style('[packages]', fg='red')), fg='yellow')

    # Install only development dependencies.
    do_download_dependencies(bare=True)

    # Pip freeze default dependencies.
    results = get_downloads_info()

    # Add default dependencies to lockfile.
    for dep in results:
        if dep:
            lockfile['default'].update({dep['name']: {'hash': dep['hash'], 'version': '=={0}'.format(dep['version'])}})

    # Write out lockfile.
    with open(project.lockfile_location, 'w') as f:
        f.write(json.dumps(lockfile, indent=4, separators=(',', ': ')))

    # Purge the virtualenv download dir, for next time.
    do_purge(downloads=True, bare=True)


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
    venv_location = project.virtualenv_location.replace(' ', '\ ')

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
                click.style('pipenv shell', fg='red'))
            )
        else:
            click.echo(activate_virtualenv())


def do_purge(bare=False, downloads=False, allow_global=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            click.secho('Clearing out downloads directory...', fg='yellow')
        shutil.rmtree(project.download_location)
        return

    freeze = delegator.run('{0} freeze'.format(which_pip(allow_global=allow_global))).out
    installed = freeze.split()

    # Remove setuptools and friends from installed, if present.
    installed.remove('setuptools')
    installed.remove('pip')
    installed.remove('wheel')
    installed.remove('six')

    if not bare:
        click.echo('Found {0} installed package(s), purging...'.format(len(installed)))
    command = '{0} uninstall {1} -y'.format(which_pip(allow_global=allow_global), ' '.join(installed))
    c = delegator.run(command)

    if not bare:
        click.secho(c.out, fg='blue')

        click.secho('Environment now purged and fresh!', fg='yellow')


def do_init(dev=False, requirements=False, skip_virtualenv=False, allow_global=False):
    """Executes the init functionality."""

    ensure_pipfile()

    # Display where the Project is established.
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
        if not lockfile['_meta']['Pipfile-sha256'] == p.hash:
            click.secho('Pipfile.lock out of date, updating...', fg='red', err=True)

            do_lock()

    do_install_dependencies(dev=dev, requirements=requirements, allow_global=allow_global)

    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists:
        click.secho('Pipfile.lock not found, creating...', fg='yellow', err=True)
        do_lock()

    # Activate virtualenv instructions.
    do_activate_virtualenv()


def pip_install(package_name=None, r=None, allow_global=False):
    if r:
        c = delegator.run('{0} install -r {1} --require-hashes -i {2}'.format(which_pip(allow_global=allow_global), r, project.source['url']))
    else:
        c = delegator.run('{0} install "{1}" -i {2}'.format(which_pip(allow_global=allow_global), package_name, project.source['url']))
    return c


def pip_download(package_name):
    c = delegator.run('{0} download "{1}" -d {2}'.format(which_pip(), package_name, project.download_location))
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
            if len(data) > 2:
                collected.append(data)

    # Hit the simple API.
    r = requests.get('{0}/{1}'.format(project.source['url'], package_name))
    if not r.ok:
        raise IOError('Unable to find package {0} in PyPI repository.'.format(click.style(package_name, fg='green')))

    # Parse the HTML.
    parser = SimpleHTMLParser()
    parser.feed(r.text)

    # Use the last link on the page, use it to get proper casing.
    return parse_download_fname(collected[-1])[0]


def format_help(help):
    """Formats the help string."""
    help = help.replace('  check', str(click.style('  check', fg='green')))
    help = help.replace('  uninstall', str(click.style('  uninstall', fg='yellow', bold=True)))
    help = help.replace('  install', str(click.style('  install', fg='yellow', bold=True)))
    help = help.replace('  lock', str(click.style('  lock', fg='red', bold=True)))
    help = help.replace('  run', str(click.style('  run', fg='blue')))
    help = help.replace('  shell', str(click.style('  shell', fg='blue', bold=True)))
    help = help.replace('  update', str(click.style('  update', fg='yellow')))

    additional_help = """
Usage Examples:
   Create a new project using Python 3:
   $ {0}

   Install all dependencies for a project (including dev):
   $ {1}

   Create a lockfile (& keep [dev-packages] intalled):
   $ {2}

Commands:""".format(
    click.style('pipenv --three', fg='red'),
    click.style('pipenv install --dev', fg='red'),
    click.style('pipenv lock --dev', fg='red'))

    help = help.replace('Commands:', additional_help)

    return help


def format_pip_error(error):
    error = error.replace('Expected', str(click.style('Expected', fg='green', bold=True)))
    error = error.replace('Got', str(click.style('Got', fg='red', bold=True)))
    error = error.replace('THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE', str(click.style('THESE PACKAGES DO NOT MATCH THE HASHES FROM Pipfile.lock!', fg='red', bold=True)))
    error = error.replace('someone may have tampered with them', str(click.style('someone may have tampered with them', fg='red')))
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


def easter_egg(package_name):
    if package_name in ['requests', 'maya', 'crayons', 'delegator.py' 'records', 'tablib']:
        click.echo('P.S. You have excellent taste! ✨🍰✨')


@click.group(invoke_without_command=True)
@click.option('--where', is_flag=True, default=False, help="Output project home information.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--help', is_flag=True, default=None, help="Show this message then exit.")
@click.version_option(prog_name=click.style('pipenv', fg='yellow'), version=__version__)
@click.pass_context
def cli(ctx, where=False, bare=False, three=False, help=False):
    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            do_where(bare=bare)
            sys.exit(0)

        # --two / --three was passed.
        if three is not None:
            ensure_project(three=three)

        else:

            # Display help to user, if no commands were passed.
            click.echo(format_help(ctx.get_help()))


@click.command(help="Installs provided packages and adds them to Pipfile, or (if none is given), installs all packages.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--requirements', is_flag=True, default=False, help="Just generate a requirements.txt. Only works with bare install command.")
@click.option('--lock', is_flag=True, default=False, help="Lock afterwards.")
def install(package_name=False, more_packages=False, dev=False, three=False, system=False, lock=False, requirements=False):

    # Ensure that virtualenv is available.
    ensure_project(three=three)

    # Allow more than one package to be provided.
    package_names = (package_name,) + more_packages

    # Install all dependencies, if none was provided.
    if package_name is False:
        click.secho('No package provided, installing all dependencies.', fg='yellow', err=True)
        do_init(dev=dev, requirements=requirements, allow_global=system)
        sys.exit(0)

    for package_name in package_names:

        # Proper-case incoming package name (check against API).
        old_name = [k for k in convert_deps_from_pip(package_name).keys()][0]
        try:
            new_name = proper_case(old_name)
        except IOError as e:
            click.echo('{0} {1}'.format(click.style('Error: ', fg='red'), e.args[0], click.style(package_name, fg='green')))
            continue
        package_name = package_name.replace(old_name, new_name)

        click.echo('Installing {0}...'.format(click.style(package_name, fg='green')))

        # pip install:
        c = pip_install(package_name, allow_global=system)
        click.secho(format_pip_output(c.out), fg='blue')

        # Ensure that package was successfully installed.
        try:
            assert c.return_code == 0
        except AssertionError:
            click.echo('{0} An error occurred while installing {1}!'.format(click.style('Error: ', fg='red'), click.style(package_name, fg='green')))
            click.secho(format_pip_error(c.err), fg='blue')
            sys.exit(1)

        if dev:
            click.echo('Adding {0} to Pipfile\'s {1}...'.format(click.style(package_name, fg='green'), click.style('[dev-packages]', fg='red')))
        else:
            click.echo('Adding {0} to Pipfile\'s {1}...'.format(click.style(package_name, fg='green'), click.style('[packages]', fg='red')))

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
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--lock', is_flag=True, default=False, help="Lock afterwards.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Un-install package(s) from [dev-packages].")
def uninstall(package_name=False, more_packages=False, three=None, system=False, lock=False, dev=False):
    # Ensure that virtualenv is available.
    ensure_project(three=three)

    package_names = (package_name,) + more_packages
    pipfile_remove = True

    # Un-install all dependencies, if none was provided.
    if package_name is False:
        if not dev:
            click.secho('No package provided, un-installing all packages.', fg='yellow')
            do_purge(allow_global=system)
            sys.exit(0)
        elif 'dev-packages' in project.parsed_pipfile:
            package_names = project.parsed_pipfile['dev-packages']
            pipfile_remove = False
        else:
            click.secho('No dev-packages to uninstall.', fg='yellow')
            sys.exit(0)

    for package_name in package_names:

        click.echo('Un-installing {0}...'.format(click.style(package_name, fg='green')))

        c = delegator.run('{0} uninstall {1} -y'.format(which_pip(allow_global=system), package_name))
        click.secho(c.out, fg='blue')

        if pipfile_remove:
            if dev:
                click.echo('Removing {0} from Pipfile\'s {1}...'.format(click.style(package_name, fg='green'), click.style('[dev-packages]', fg='red')))
            else:
                click.echo('Removing {0} from Pipfile\'s {1}...'.format(click.style(package_name, fg='green'), click.style('[packages]', fg='red')))

            project.remove_package_from_pipfile(package_name, dev)

        if lock:
            do_lock()


@click.command(help="Generates Pipfile.lock.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
def lock(three=None):
    # Ensure that virtualenv is available.
    ensure_project(three=three)

    do_lock()


@click.command(help="Spawns a shell within the virtualenv.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
def shell(three=None):
    # Ensure that virtualenv is available.
    ensure_project(three=three)

    # Set an environment variable, so we know we're in the environment.
    os.environ['PIPENV_ACTIVE'] = '1'

    # Spawn the Python process, and interact with it.
    try:
        shell = os.environ['SHELL']
    except KeyError:
        error = ('No shell found: Please ensure the SHELL environment variable is set. '
                 'Windows is not currently supported.')
        click.secho(error, fg='red')
        sys.exit(1)

    click.secho('Spawning environment shell ({0}).'.format(click.style(shell, fg='red')), fg='yellow')

    # Grab current terminal dimensions to replace the hardcoded default
    # dimensions of pexpect
    terminal_dimensions = get_terminal_size()

    c = pexpect.spawn(
            shell,
            ["-i"],
            dimensions=(
                terminal_dimensions.lines,
                terminal_dimensions.columns
            )
        )

    # Activate the virtualenv.
    c.send(activate_virtualenv() + '\n')

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
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
def run(command, args, three=None):
    # Ensure that virtualenv is available.
    ensure_project(three=three)

    # Spawn the new process, and interact with it.
    try:
        c = pexpect.spawn(which(command), list(args))
    except pexpect.exceptions.ExceptionPexpect:
        click.secho('The command was not found within the virtualenv!', fg='red')
        sys.exit(1)

    # Interact with the new shell.
    c.interact()
    c.close()
    sys.exit(c.exitstatus)


@click.command(help="Checks PEP 508 markers provided in Pipfile.")
def check():
    click.secho('Checking PEP 508 requirements...', fg='yellow')

    # Run the PEP 508 checker in the virtualenv.
    c = delegator.run('{0} {1}'.format(which('python'), pep508checker.__file__.rstrip('cdo')))
    results = json.loads(c.out)

    # Load the pipfile.
    p = pipfile.Pipfile.load(project.pipfile_location)

    # Assert each specified requirement.
    for marker, specifier in p.data['_meta']['requires'].items():

            if marker in results:
                try:
                    assert results[marker] == specifier
                except AssertionError:
                    click.echo('Specifier {0} does not match {1}.'.format(click.style(marker, fg='red'), click.style(specifier, fg='blue')))
                    sys.exit(1)

    click.echo('Passed!')


@click.command(help="Updates pip to latest version, uninstalls all packages, and re-installs them to latest compatible versions.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
def update(dev=False, three=None):

    # Ensure that virtualenv is available.
    ensure_virtualenv(three=three)

    # Update pip to latest version.
    ensure_latest_pip()

    click.secho('Updating all dependencies from Pipfile...', fg='yellow')

    do_purge()
    do_init(dev=dev)

    click.secho('All dependencies are now up-to-date!', fg='yellow')


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
