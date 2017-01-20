import codecs
import json
import os
import sys


import toml
import delegator
import click
import crayons
import _pipfile as pipfile

__version__ = '0.0.0'

def ensure_latest_pip():

    # Ensure that pip is installed.
    c = delegator.run('pip install pip')

    # Check if version is out of date.
    if 'however' in c.err:
        # If version is out of date, update.
        click.echo(crayons.yellow('Pip is out of date... updating to latest.'))
        c = delegator.run('pip install pip --upgrade', block=False)
        click.echo(crayons.blue(c.out))

def ensure_virtualenv():
    # c = delegator.run('pip install virtualenv')
    pass


def add_package_to_pipfile(package_name, dev=False):
    pipfile_path = pipfile.Pipfile.find()

    # Read and append Pipfile.
    with open(pipfile_path, 'r') as f:
        p = toml.loads(f.read())

        key = 'develop' if dev else 'packages'
        if package_name not in p[key]:
            # TODO: Support >1.0.1
            p[key][package_name] = '*'

    # Write Pipfile.

    data = toml.dumps(p).split('\n')
    for i, line in enumerate(data):
        if i > 0:
            if line.startswith('['):
                data[i] = '\n{}'.format(line)

    data = '\n'.join(data)

    with open(pipfile_path, 'w') as f:
        f.write(data)




@click.group()
# @click.option('--version', is_flag=True, callback=display_version, help='Display version information')
@click.version_option(prog_name=crayons.yellow('pip2'), version=__version__)
def cli(*args, **kwargs):
    # Ensure that pip is installed and up-to-date.
    ensure_latest_pip()

    # Ensure that virtualenv is installed.
    ensure_virtualenv()

def virtualenv_location():
    return os.sep.join(pipfile.Pipfile.find().split(os.sep)[:-1] + ['.venv'])

def pipfile_location():
    return pipfile.Pipfile.find()

def lockfile_location():
    return '{}.freeze'.format(pipfile_location())

def lockfile_exists():
    return os.path.isfile(lockfile_location())


def do_where(virtualenv=False, bare=True):
    if not virtualenv:
        location = pipfile_location()

        if not bare:
            click.echo('Pipfile found at {}. Considering this to be the project home.'.format(crayons.green(location)))
        else:
            click.echo(location)

    else:
        location = virtualenv_location()

        if not bare:
            click.echo('Virtualenv location: {}'.format(crayons.green(location)))
        else:
            click.echo(location)


def convert_deps(deps):
    dependencies = []

    for dep in deps.keys():
        # Default (e.g. '>1.10').
        extra = deps[dep]

        # Get rid of '*'.
        if extra == '*':
            extra = ''

        # Support for extras (e.g. requests[socks])
        if 'extras' in extra:
            extra = '[{}]'.format(deps[dep]['extras'][0])

        # Support for git.
        # if 'editablle'

        dependencies.append('{} {}'.format(dep, extra))

    return dependencies

def which_pip():
    return os.sep.join([virtualenv_location()] + ['bin/pip'])

@click.command()
@click.option('--dev', is_flag=True, default=False)
def prepare(dev=False):
    do_where(bare=False)
    click.echo(crayons.yellow('Creating a virtualenv for this project...'))

    # Actually create the virtualenv.
    c = delegator.run('virtualenv {}'.format(virtualenv_location()), block=False)
    # c.block()
    click.echo(crayons.blue(c.out))

    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)

    # Write out the lockfile if it doesn't exist.
    if lockfile_exists():
        click.echo(crayons.yellow('Installing dependencies from Pipfile.freeze...'))
        with codecs.open(lockfile_location(), 'r') as f:
            lockfile = json.load(f)

        # TODO: Update the lockfile if it is out-of-date.
        p = pipfile.load(pipfile_location())
        if not lockfile['_meta']['Pipfile-sha256'] == p.hash:
            click.echo(crayons.red('Pipfile.freeze out of date, updating...'))

            # Update the lockfile.

    else:

        # Load the pipfile.
        click.echo(crayons.yellow('Installing dependencies from Pipfile...'))
        p = pipfile.load(pipfile_location())
        lockfile = json.loads(p.freeze())

    # Install default dependencies, always.
    deps = lockfile['default']

    # Add development deps if --dev was passed.
    if dev:
        deps.update(lockfile['develop'])

    # Convert the deps to pip-compatbile arguments.
    deps = convert_deps(deps)

    # Actually install each dependency into the virtualenv.
    for package_name in deps:
        click.echo('Installing {}...'.format(crayons.green(package_name)))
        c = delegator.run('{} install {}'.format(which_pip(), package_name),)
        click.echo(crayons.blue(c.out))

    # Write out the lockfile if it doesn't exist.
    if not lockfile_exists():
        click.echo(crayons.yellow('Pipfile.freeze not found, creating...'))
        with codecs.open(lockfile_location(), 'w', 'utf-8') as f:
            f.write(p.freeze())



@click.command()
@click.option('--virtualenv', is_flag=True, default=False)
@click.option('--bare', is_flag=True, default=False)
def where(virtualenv=False, bare=False):
    do_where(virtualenv, bare)



@click.command()
@click.argument('package_name')
@click.option('--dev', is_flag=True, default=False)
def install(package_name, dev=False):
    click.echo('Installing {}...'.format(crayons.green(package_name)))

    c = delegator.run('{} install {}'.format(which_pip(), package_name))
    click.echo(crayons.blue(c.out))

    click.echo('Adding {} to Pipfile...'.format(crayons.green(package_name)))
    add_package_to_pipfile(package_name, dev)


@click.command()
@click.argument('package_name')
def uninstall(package_name):
    click.echo('Un-installing {}...'.format(crayons.green(package_name)))

# Install click commands.
cli.add_command(prepare)
cli.add_command(where)
cli.add_command(install)
cli.add_command(uninstall)


if __name__ == '__main__':
    cli()