import os

import click

from .main import get_key, dotenv_values, set_key, unset_key


@click.group()
@click.option('-f', '--file', default=os.path.join(os.getcwd(), '.env'),
              type=click.Path(exists=True),
              help="Location of the .env file, defaults to .env file in current working directory.")
@click.option('-q', '--quote', default='always',
              type=click.Choice(['always', 'never', 'auto']),
              help="Whether to quote or not the variable values. Default mode is always. This does not affect parsing.")
@click.pass_context
def cli(ctx, file, quote):
    '''This script is used to set, get or unset values from a .env file.'''
    ctx.obj = {}
    ctx.obj['FILE'] = file
    ctx.obj['QUOTE'] = quote


@cli.command()
@click.pass_context
def list(ctx):
    '''Display all the stored key/value.'''
    file = ctx.obj['FILE']
    dotenv_as_dict = dotenv_values(file)
    for k, v in dotenv_as_dict.items():
        click.echo('%s="%s"' % (k, v))


@cli.command()
@click.pass_context
@click.argument('key', required=True)
@click.argument('value', required=True)
def set(ctx, key, value):
    '''Store the given key/value.'''
    file = ctx.obj['FILE']
    quote = ctx.obj['QUOTE']
    success, key, value = set_key(file, key, value, quote)
    if success:
        click.echo('%s="%s"' % (key, value))
    else:
        exit(1)


@cli.command()
@click.pass_context
@click.argument('key', required=True)
def get(ctx, key):
    '''Retrieve the value for the given key.'''
    file = ctx.obj['FILE']
    stored_value = get_key(file, key)
    if stored_value:
        click.echo('%s="%s"' % (key, stored_value))
    else:
        exit(1)


@cli.command()
@click.pass_context
@click.argument('key', required=True)
def unset(ctx, key):
    '''Removes the given key.'''
    file = ctx.obj['FILE']
    quote = ctx.obj['QUOTE']
    success, key = unset_key(file, key, quote)
    if success:
        click.echo("Successfully removed %s" % key)
    else:
        exit(1)


def get_cli_string(path=None, action=None, key=None, value=None):
    """Returns a string suitable for running as a shell script.

    Useful for converting a arguments passed to a fabric task
    to be passed to a `local` or `run` command.
    """
    command = ['dotenv']
    if path:
        command.append('-f %s' % path)
    if action:
        command.append(action)
        if key:
            command.append(key)
            if value:
                if ' ' in value:
                    command.append('"%s"' % value)
                else:
                    command.append(value)

    return ' '.join(command).strip()


if __name__ == "__main__":
    cli()
