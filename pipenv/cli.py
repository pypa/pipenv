import codecs
import json
import os
import sys
import distutils.spawn

import click
import crayons
import delegator
import pexpect
import toml

from . import _pipfile as pipfile
from .project import Project
from .utils import convert_deps_from_pip, convert_deps_to_pip

__version__ = '0.2.3'


project = Project()

USE_TWO=False
USE_THREE=False

def ensure_latest_pip():
    """Updates pip to the latest version."""

    # Ensure that pip is installed.
    c = delegator.run('{0} install pip'.format(which_pip()))

    # Check if version is out of date.
    if 'however' in c.err:
        # If version is out of date, update.
        click.echo(crayons.yellow('Pip is out of date... updating to latest.'))
        c = delegator.run('{0} install pip --upgrade'.format(which_pip()), block=False)
        click.echo(crayons.blue(c.out))

def ensure_pipfile(dev=False):
    """Creates a Pipfile for the project, if it doesn't exist."""

    # Assert Pipfile exists.
    if not project.pipfile_exists:

        click.echo(crayons.yellow('Creating a Pipfile for this project...'))

        # Create the pipfile if it doesn't exist.
        project.create_pipfile()

def ensure_virtualenv():
    """Creates a virtualenv, if one doesn't exist."""
    if not project.virtualenv_exists:
        do_create_virtualenv()


def ensure_project(dev=False):
    """Ensures both Pipfile and virtualenv exist for the project."""
    ensure_pipfile(dev=dev)
    ensure_virtualenv()


def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""

    if not virtualenv:
        location = project.pipfile_location

        if not bare:
            click.echo('Pipfile found at {0}. Considering this to be the project home.'.format(crayons.green(location)))
        else:
            click.echo(location)

    else:
        location = project.virtualenv_location

        if not bare:
            click.echo('Virtualenv location: {0}'.format(crayons.green(location)))
        else:
            click.echo(location)


def do_install_dependencies(dev=False, only=False, bare=False, allow_global=False):
    """"Executes the install functionality."""

    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location)

    # Load the lockfile if it exists, else use the Pipfile as a seed.
    if not project.lockfile_exists:
        if not bare:
            click.echo(crayons.yellow('Installing dependencies from Pipfile...'))
        lockfile = json.loads(p.freeze())
    else:
        if not bare:
            click.echo(crayons.yellow('Installing dependencies from Pipfile.lock...'))
        with open(project.lockfile_location, 'r') as f:
            lockfile = json.load(f)

    # Install default dependencies, always.
    deps = lockfile['default'] if not only else {}

    # Add development deps if --dev was passed.
    if dev:
        deps.update(lockfile['develop'])

    # Convert the deps to pip-compatbile arguments.
    deps = convert_deps_to_pip(deps)

    # Actually install each dependency into the virtualenv.
    for package_name in deps:

        if not bare:
            click.echo('Installing {0}...'.format(crayons.green(package_name)))

        c = delegator.run('{0} install "{1}"'.format(which_pip(allow_global=allow_global), package_name),)

        if not bare:
            click.echo(crayons.blue(c.out))


def do_create_virtualenv():
    """Creates a virtualenv."""
    click.echo(crayons.yellow('Creating a virtualenv for this project...'))

    # The command to create the virtualenv.
    cmd = ['virtualenv', project.virtualenv_location, '--prompt=({0})'.format(project.name)]

    # Pass a Python version to virtualenv, if needed.
    if USE_TWO:
        cmd = cmd + ['-p', 'python2']
    if USE_THREE:
        cmd = cmd + ['-p', 'python3']

    # Actually create the virtualenv.
    c = delegator.run(cmd, block=False)
    click.echo(crayons.blue(c.out))

    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)


def do_lock(dev=False):
    """Executes the freeze functionality."""

    click.echo(crayons.yellow('Assuring all dependencies from Pipfile are installed...'))

    # Purge the virtualenv, for development dependencies.
    do_purge(bare=True)

    click.echo(crayons.yellow('Locking {0} dependencies...'.format(crayons.red('[dev-packages]'))))

    # Install only development dependencies.
    do_install_dependencies(dev=True, only=True, bare=True)

    # Load the Pipfile and generate a lockfile.
    p = pipfile.load(project.pipfile_location)
    lockfile = json.loads(p.freeze())

    # Pip freeze development dependencies.
    c = delegator.run('{0} freeze'.format(which_pip()))

    # Add Development dependencies to lockfile.
    for dep in c.out.split('\n'):
        if dep:
            lockfile['develop'].update(convert_deps_from_pip(dep))


    # Purge the virtualenv.
    do_purge(bare=True)

    click.echo(crayons.yellow('Locking {0} dependencies...'.format(crayons.red('[packages]'))))

    # Install only development dependencies.
    do_install_dependencies(bare=True)

    # Pip freeze default dependencies.
    c = delegator.run('{0} freeze'.format(which_pip()))

    # Add default dependencies to lockfile.
    for dep in c.out.split('\n'):
        if dep:
            lockfile['default'].update(convert_deps_from_pip(dep))

    # Write out lockfile.
    with open(project.lockfile_location, 'w') as f:
        f.write(json.dumps(lockfile, indent=4, separators=(',', ': ')))

    # Provide instructions for dev depenciencies.
    if not dev:
        click.echo(crayons.yellow('Note: ') + 'your project now has only default {0} installed.'.format(crayons.red('[packages]')))
        click.echo('To keep {0} next time, run: $ {1}'.format(crayons.red('[dev-packages]'), crayons.green('pipenv lock --dev')))
    else:
        # Install only development dependencies.
        do_install_dependencies(dev=True, only=True, bare=True)


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

    if source:
        return 'source {0}/bin/activate{1}'.format(project.virtualenv_location, suffix)
    else:
        return '{0}/bin/activate'.format(project.virtualenv_location)


def do_activate_virtualenv(bare=False):
    """Executes the activate virtualenv functionality."""
    # Check for environment marker, and skip if it's set.
    if not 'PIPENV_ACTIVE' in os.environ:
        if not bare:
            click.echo('To activate this project\'s virtualenv, run the following:\n $ {0}'.format(crayons.red('pipenv shell')))
        else:
            click.echo(activate_virtualenv())


def do_purge(bare=False, allow_global=False):
    """Executes the purge functionality."""
    freeze = delegator.run('{0} freeze'.format(which_pip(allow_global=allow_global))).out
    installed = freeze.split()

    if not bare:
        click.echo('Found {0} installed package(s), purging...'.format(len(installed)))
    command = '{0} uninstall {1} -y'.format(which_pip(allow_global=allow_global), ' '.join(installed))
    c = delegator.run(command)

    if not bare:
        click.echo(crayons.blue(c.out))

        click.echo(crayons.yellow('Environment now purged and fresh!'))


def do_init(dev=False, skip_virtualenv=False, allow_global=False):
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
            click.echo(crayons.red('Pipfile.lock out of date, updating...'))

            do_lock(dev=dev)

    do_install_dependencies(dev=dev, allow_global=allow_global)

    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists:
        click.echo(crayons.yellow('Pipfile.lock not found, creating...'))
        do_lock(dev=dev)

    # Activate virtualenv instructions.
    do_activate_virtualenv()


def which(command):
    return os.sep.join([project.virtualenv_location] + ['bin/{0}'.format(command)])


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""
    if allow_global:
        return distutils.spawn.find_executable('pip')

    return which('pip')

def from_requirements_file(r):
    """Returns a list of packages from an open requirements file."""
    return [p for p in r.read().split('\n') if p and not p.startswith('#')]



@click.group(invoke_without_command=True)
@click.option('--where', is_flag=True, default=False, help="Output project home information.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.version_option(prog_name=crayons.yellow('pipenv'), version=__version__)
@click.pass_context
def cli(ctx, where=False, bare=False, three=False):
    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            do_where(bare=bare)
            sys.exit(0)

        # --three was passed.
        if three is True:
            global USE_THREE
            USE_THREE = True
            ensure_project()

        # --two was passed.
        elif three is False:
            global USE_TWO
            USE_TWO = True
            ensure_project()

        else:

            # Display help to user, if no commands were passed.
            click.echo(ctx.get_help())



@click.command(help="Installs provided packages and adds them to Pipfile, or (if none is given), installs all packages.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--dev','-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('-r', type=click.File('rb'), default=None, help="Use requirements.txt file.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
def install(package_name=False, more_packages=False, r=False, dev=False, system=False):

    # Ensure that virtualenv is available.
    ensure_project(dev=dev)

    # Allow more than one package to be provided.
    package_names = (package_name,) + more_packages

    # If -r provided, read in package names.
    if r:
        package_names = from_requirements_file(r)
        package_name = package_names.pop()

    # Install all dependencies, if none was provided.
    if package_name is False:
        click.echo(crayons.yellow('No package provided, installing all dependencies.'))
        do_init(dev=dev, allow_global=system)
        sys.exit(0)

    for package_name in package_names:
        click.echo('Installing {0}...'.format(crayons.green(package_name)))

        c = delegator.run('{0} install "{1}"'.format(which_pip(allow_global=system), package_name))
        click.echo(crayons.blue(c.out))

        # Ensure that package was successfully installed.
        try:
            assert c.return_code == 0
        except AssertionError:
            click.echo('{0} An error occured while installing {1}'.format(crayons.red('Error: '), crayons.green(package_name)))
            click.echo(crayons.blue(c.err))
            sys.exit(1)

        if dev:
            click.echo('Adding {0} to Pipfile\'s {1}...'.format(crayons.green(package_name), crayons.red('[dev-packages]')))
        else:
            click.echo('Adding {0} to Pipfile\'s {1}...'.format(crayons.green(package_name), crayons.red('[packages]')))

        # Add the package to the Pipfile.
        project.add_package_to_pipfile(package_name, dev)


@click.command(help="Un-installs a provided package and removes it from Pipfile, or (if none is given), un-installs all packages.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--system', is_flag=True, default=False, help="System pip management.")
def uninstall(package_name=False, more_packages=False, system=False):
    # Ensure that virtualenv is available.
    ensure_project()

    package_names = (package_name,) + more_packages

    # Un-install all dependencies, if none was provided.
    if package_name is False:
        click.echo(crayons.yellow('No package provided, un-installing all packages.'))
        do_purge(allow_global=system)
        sys.exit(1)

    for package_name in package_names:

        click.echo('Un-installing {0}...'.format(crayons.green(package_name)))

        c = delegator.run('{0} uninstall {1} -y'.format(which_pip(allow_global=system), package_name))
        click.echo(crayons.blue(c.out))

        click.echo('Removing {0} from Pipfile...'.format(crayons.green(package_name)))
        project.remove_package_from_pipfile(package_name)


@click.command(help="Generates Pipfile.lock.")
@click.option('--dev','-d', is_flag=True, default=False, help="Keeps dev-packages installed.")
def lock(dev=False):
    do_lock(dev=dev)

@click.command(help="Spans a shell within the virtualenv.")
def shell():
    # Ensure that virtualenv is available.
    ensure_project()

    # Set an environment viariable, so we know we're in the environment.
    os.environ['PIPENV_ACTIVE'] = '1'

    # Spawn the Python process, and iteract with it.
    shell = os.environ['SHELL']
    click.echo(crayons.yellow('Spawning environment shell ({0}).'.format(crayons.red(shell))))

    c = pexpect.spawn("{0} -c '. {1}; exec {0} -i'".format(shell, activate_virtualenv(source=False)))
    c.send(activate_virtualenv() + '\n')

    # Interact with the new shell.
    c.interact()


@click.command(help="Spans a command installed into the virtualenv.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.argument('command')
@click.argument('args', nargs=-1)
def run(command, args):
    # Ensure that virtualenv is available.
    ensure_project()

    # Spawn the new process, and iteract with it.
    c = pexpect.spawn('{0} {1}'.format(which(command), ' '.join(args)))

    # Interact with the new shell.
    c.interact()


@click.command(help="Checks PEP 508 markers provided in Pipfile.")
def check():
    click.echo(crayons.yellow('Checking PEP 508 requirements...'))

    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location)

    # Assert the given requirements.
    # TODO: Run this within virtual environment.
    p.assert_requirements()


@click.command(help="Updates pip to latest version, uninstalls all packages, and re-installs them to latest compatible versions.")
@click.option('--dev','-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
def update(dev=False):

    # Ensure that virtualenv is available.
    ensure_virtualenv()

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
