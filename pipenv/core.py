import codecs
import json
import os
import sys

import click
import crayons
import delegator
import pexpect
import toml
import _pipfile as pipfile

__version__ = '0.1.0'

class Project(object):
    """docstring for Project"""
    def __init__(self):
        super(Project, self).__init__()

    @property
    def name(self):
        return self.pipfile_location().split(os.sep)[-2]

    @property
    def pipfile_exists(self):
        return self.pipfile_location

    @staticmethod
    def virtualenv_location():
        return os.sep.join(pipfile.Pipfile.find().split(os.sep)[:-2] + ['.venv'])

    @staticmethod
    def pipfile_location():
        return pipfile.Pipfile.find()

    def lockfile_location(self):
        return '{}.freeze'.format(self.pipfile_location())

    def lockfile_exists(self):
        return os.path.isfile(self.lockfile_location())

    def create_pipfile(self):
        data = {u'source': [{u'url': u'https://pypi.org/', u'verify_ssl': True}], u'packages': {}, 'dev-packages': {}}
        with open('Pipfile', 'w') as f:
            f.write(toml.dumps(data))

    @staticmethod
    def remove_package_from_pipfile(package_name, dev=False):
        pipfile_path = pipfile.Pipfile.find()

        # Read and append Pipfile.
        with open(pipfile_path, 'r') as f:
            p = toml.loads(f.read())

            key = 'dev-packages' if dev else 'packages'
            if package_name in p[key]:
                del p[key][package_name]

        # Write Pipfile.
        data = format_toml(toml.dumps(p))
        with open(pipfile_path, 'w') as f:
            f.write(data)

    @staticmethod
    def add_package_to_pipfile(package_name, dev=False):
        pipfile_path = pipfile.Pipfile.find()

        # Read and append Pipfile.
        with open(pipfile_path, 'r') as f:
            p = toml.loads(f.read())

            key = 'dev-packages' if dev else 'packages'

            # Set empty group if it doesn't exist yet.
            if key not in p:
                p[key] = {}

            package = convert_deps_from_pip(package_name)
            package_name = package.keys()[0]

            # Add the package to the group.
            p[key][package_name] = package[package_name]

        # Write Pipfile.
        data = format_toml(toml.dumps(p))
        with open(pipfile_path, 'w') as f:
            f.write(data)


project = Project()


def ensure_latest_pip():

    # Ensure that pip is installed.
    c = delegator.run('pip install pip')

    # Check if version is out of date.
    if 'however' in c.err:
        # If version is out of date, update.
        click.echo(crayons.yellow('Pip is out of date... updating to latest.'))
        c = delegator.run('pip install pip --upgrade', block=False)
        click.echo(crayons.blue(c.out))


def format_toml(data):
    """Pretty-formats a given toml string."""
    data = data.split('\n')
    for i, line in enumerate(data):
        if i > 0:
            if line.startswith('['):
                data[i] = '\n{}'.format(line)

    return '\n'.join(data)



def multi_split(s, split):
    for r in split:
        s = s.replace(r, '|')

    return [i for i in s.split('|') if len(i) > 0]


def convert_deps_from_pip(dep):
    dependency = {}

    # Comparison operators: e.g. Django>1.10
    if '=' in dep or '<' in dep or '>' in dep:
        r = multi_split(dep, '=<>')
        dependency[r[0]] = dep[len(r[0]):]

    # Extras: e.g. requests[socks]
    elif '[' in dep:
        r = multi_split(dep, '[]')
        dependency[r[0]] = {'extras': r[1].split(',')}

    # TODO: Editable installs.

    # Bare dependencies: e.g. requests
    else:
        dependency[dep] = '*'

    return dependency


def convert_deps_to_pip(deps):
    dependencies = []

    for dep in deps.keys():
        # Default (e.g. '>1.10').
        extra = deps[dep]

        # Get rid of '*'.
        if deps[dep] == '*' or str(extra) == '{}':
            extra = ''

        # Support for extras (e.g. requests[socks])
        if 'extras' in deps[dep]:
            extra = '[{}]'.format(deps[dep]['extras'][0])

        # Support for git.
        if 'git' in deps[dep]:
            extra = 'git+{}'.format(deps[dep]['git'])

            # Support for @refs.
            if 'ref' in deps[dep]:
                extra += '@{}'.format(deps[dep]['ref'])

            # Support for editable.
            if 'editable' in deps[dep]:
                # Support for --egg.
                extra += ' --egg={}'.format(dep)
                dep = '-e '

        dependencies.append('{}{}'.format(dep, extra))

    return dependencies



def do_where(virtualenv=False, bare=True):
    if not virtualenv:
        location = project.pipfile_location()

        if not bare:
            click.echo('Pipfile found at {}. Considering this to be the project home.'.format(crayons.green(location)))
        else:
            click.echo(location)

    else:
        location = project.virtualenv_location()

        if not bare:
            click.echo('Virtualenv location: {}'.format(crayons.green(location)))
        else:
            click.echo(location)

def do_install_dependencies(dev=False, only=False, bare=False):
    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location())
    lockfile = json.loads(p.freeze())

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
            click.echo('Installing {}...'.format(crayons.green(package_name)))

        c = delegator.run('{} install {}'.format(which_pip(), package_name),)

        if not bare:
            click.echo(crayons.blue(c.out))

def do_freeze():
    click.echo(crayons.yellow('Assuring all dependencies from Pipfile are installed...'))

    # Purge the virtualenv, for development dependencies.
    do_purge(bare=True)

    click.echo(crayons.yellow('Freezing development dependencies...'))

    # Install only development dependencies.
    do_install_dependencies(dev=True, only=True, bare=True)

    # Load the Pipfile and generate a lockfile.
    p = pipfile.load(project.pipfile_location())
    lockfile = json.loads(p.freeze())

    # Pip freeze development dependencies.
    c = delegator.run('{} freeze'.format(which_pip()))

    # Add Development dependencies to lockfile.
    for dep in c.out.split('\n'):
        if dep:
            lockfile['develop'].update(convert_deps_from_pip(dep))


    # Purge the virtualenv.
    do_purge(bare=True)

    click.echo(crayons.yellow('Freezing default dependencies...'))

    # Install only development dependencies.
    do_install_dependencies(bare=True)

    # Pip freeze default dependencies.
    c = delegator.run('{} freeze'.format(which_pip()))

    # Add default dependencies to lockfile.
    for dep in c.out.split('\n'):
        if dep:
            lockfile['default'].update(convert_deps_from_pip(dep))

    with open(project.lockfile_location(), 'w') as f:
        f.write(json.dumps(lockfile))

def activate_virtualenv():
    return 'source {}/bin/activate'.format(project.virtualenv_location())

def do_activate_virtualenv(bare=False):
    if not bare:
        click.echo('To activate this project\'s virtualenv, run the following:\n $ {}'.format(crayons.red(activate_virtualenv())))
    else:
        click.echo(activate_virtualenv())

def do_purge(bare=False):
    freeze = delegator.run('{} freeze'.format(which_pip())).out
    installed = freeze.split()

    if not bare:
        click.echo('Found {} dirty packages installed, purging...'.format(len(installed)))
    command = '{} uninstall {} -y'.format(which_pip(), ' '.join(installed))
    c = delegator.run(command)

    if not bare:
        click.echo(crayons.blue(c.out))

        click.echo(crayons.yellow('Virtualenv now purged and fresh!'))

def which_pip():
    return os.sep.join([project.virtualenv_location()] + ['bin/pip'])

def which_python():
    return os.sep.join([project.virtualenv_location()] + ['bin/python'])


@click.group()
@click.version_option(prog_name=crayons.yellow('pipenv'), version=__version__)
def cli(*args, **kwargs):
    # Ensure that pip is installed and up-to-date.
    ensure_latest_pip()


@click.command()
@click.option('--dev', '-d', is_flag=True, default=False)
def init(dev=False):

    # Assert Pipfile exists.
    if not project.pipfile_exists:
        click.echo(crayons.yellow('Creating a Pipfile for this project...'))

        # Create the pipfile if it doesn't exist.
        project.create_pipfile()

        # Create the Pipfile.freeze too.
        click.echo(crayons.yellow('Creating a Pipfile.freeze as well...'))
        do_freeze()

    # Display where the Project is established.
    do_where(bare=False)
    click.echo(crayons.yellow('Creating a virtualenv for this project...'))

    # Actually create the virtualenv.
    c = delegator.run('virtualenv {} --prompt=({})'.format(project.virtualenv_location(), project.name), block=False)
    # c.block()
    click.echo(crayons.blue(c.out))

    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)

    # Write out the lockfile if it doesn't exist.
    if project.lockfile_exists():
        # Open the lockfile.
        with codecs.open(project.lockfile_location(), 'r') as f:
            lockfile = json.load(f)

        # Update the lockfile if it is out-of-date.
        p = pipfile.load(project.pipfile_location())

        # Check that the hash of the Lockfile matches the lockfile's hash.
        if not lockfile['_meta']['Pipfile-sha256'] == p.hash:
            click.echo(crayons.red('Pipfile.freeze out of date, updating...'))

            do_freeze()

            with open(project.lockfile_location(), 'w') as f:
                f.write(p.freeze())

        click.echo(crayons.yellow('Installing dependencies from Pipfile.freeze...'))




    else:

        # Load the pipfile.
        click.echo(crayons.yellow('Installing dependencies from Pipfile...'))
        p = pipfile.load(project.pipfile_location())
        lockfile = json.loads(p.freeze())

    do_install_dependencies(dev=dev)

    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists():
        click.echo(crayons.yellow('Pipfile.freeze not found, creating...'))
        with codecs.open(project.lockfile_location(), 'w', 'utf-8') as f:
            f.write(p.freeze())

    # Activate virtualenv instructions.
    do_activate_virtualenv()


@click.command()
@click.option('--virtualenv', '--venv', '-v', is_flag=True, default=False)
@click.option('--bare', '-b', is_flag=True, default=False)
def where(virtualenv=False, bare=False):
    do_where(virtualenv, bare)


@click.command()
@click.argument('package_name')
@click.option('--dev','-d', is_flag=True, default=False)
def install(package_name, dev=False):
    click.echo('Installing {}...'.format(crayons.green(package_name)))

    c = delegator.run('{} install {}'.format(which_pip(), package_name))
    click.echo(crayons.blue(c.out))

    click.echo('Adding {} to Pipfile...'.format(crayons.green(package_name)))
    project.add_package_to_pipfile(package_name, dev)


@click.command()
@click.argument('package_name')
def uninstall(package_name):
    click.echo('Un-installing {}...'.format(crayons.green(package_name)))

    c = delegator.run('{} uninstall {} -y'.format(which_pip(), package_name))
    click.echo(crayons.blue(c.out))

    click.echo('Removing {} from Pipfile...'.format(crayons.green(package_name)))
    project.remove_package_from_pipfile(package_name)


@click.command()
def freeze():
    do_freeze()


@click.command()
@click.argument('args', nargs=-1)
def py(args):
    # Spawn the Python process, and iteract with it.
    c = pexpect.spawn('{} {}'.format(which_python(), ' '.join(args)))
    c.interact()


@click.command()
@click.option('--bare', '-b', is_flag=True, default=False)
def venv(bare=False):
    do_activate_virtualenv(bare=bare)


@click.command()
def purge():
    do_purge()




# Install click commands.
cli.add_command(init)
cli.add_command(where)
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(freeze)
cli.add_command(py)
cli.add_command(venv)
cli.add_command(purge)


if __name__ == '__main__':
    cli()