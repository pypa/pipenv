import os
import sys

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




@click.group()
# @click.option('--version', is_flag=True, callback=display_version, help='Display version information')
@click.version_option(prog_name=crayons.yellow('pip2'), version=__version__)
def cli(*args, **kwargs):
    # Ensure that pip is installed and up-to-date.
    ensure_latest_pip()

    # Ensure that virtualenv is installed.
    ensure_virtualenv()


@click.command()
@click.argument('project_dir', default=None)
def prepare(project_dir=None):
    click.echo('Installing {}...'.format(crayons.green(package_name)))

@click.command()
@click.option('--virtualenv', is_flag=True, default=False)
@click.option('--bare', is_flag=True, default=False)
def where(virtualenv=False, bare=False):
    if not virtualenv:
        location = pipfile.Pipfile.find()

        if not bare:
            click.echo('Pipfile found at {}. Considering this to be the project home.'.format(crayons.green(location)))
        else:
            click.echo(location)

    else:
        location = os.sep.join(pipfile.Pipfile.find().split(os.sep)[:-1] + ['.venv'])

        if not bare:
            click.echo('Virtualenv location: {}'.format(crayons.green(location)))
        else:
            click.echo(location)



@click.command()
@click.argument('package_name')
@click.option('--dev', is_flag=True, default=False)
def install(package_name, dev=False):
    click.echo('Installing {}...'.format(crayons.green(package_name)))

    c = delegator.run('pip install {}'.format(package_name))
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