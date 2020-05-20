#!/usr/bin/env python
# -*- coding:utf-8 -*-

from __future__ import print_function, absolute_import

import os
import sys

import click
from click import echo

from click_completion.core import do_bash_complete, do_fish_complete, do_zsh_complete, do_powershell_complete,\
    get_code, install, completion_configuration

"""All the code used to monkey patch click"""


def param_type_complete(self, ctx, incomplete):
    """Returns a set of possible completions values, along with their documentation string

    Default implementation of the complete method for click.types.ParamType just returns an empty list

    Parameters
    ----------
    ctx : click.core.Context
        The current context
    incomplete :
        The string to complete

    Returns
    -------
    [(str, str)]
        A list of completion results. The first element of each tuple is actually the argument to complete, the second
        element is an help string for this argument.
    """
    return []


def choice_complete(self, ctx, incomplete):
    """Returns the completion results for click.core.Choice

    Parameters
    ----------
    ctx : click.core.Context
        The current context
    incomplete :
        The string to complete

    Returns
    -------
    [(str, str)]
        A list of completion results
    """
    return [
        (c, None) for c in self.choices
        if completion_configuration.match_incomplete(c, incomplete)
    ]


def multicommand_get_command_short_help(self, ctx, cmd_name):
    """Returns the short help of a subcommand

    It allows MultiCommand subclasses to implement more efficient ways to provide the subcommand short help, for
    example by leveraging some caching.

    Parameters
    ----------
    ctx : click.core.Context
        The current context
    cmd_name :
        The sub command name

    Returns
    -------
    str
        The sub command short help
    """
    return self.get_command(ctx, cmd_name).get_short_help_str()


def multicommand_get_command_hidden(self, ctx, cmd_name):
    """Returns the short help of a subcommand

    It allows MultiCommand subclasses to implement more efficient ways to provide the subcommand hidden attribute, for
    example by leveraging some caching.

    Parameters
    ----------
    ctx : click.core.Context
        The current context
    cmd_name :
        The sub command name

    Returns
    -------
    bool
        The sub command hidden status
    """
    cmd = self.get_command(ctx, cmd_name)
    return cmd.hidden if cmd else False


def _shellcomplete(cli, prog_name, complete_var=None):
    """Internal handler for the bash completion support.

    Parameters
    ----------
    cli : click.Command
        The main click Command of the program
    prog_name : str
        The program name on the command line
    complete_var : str
        The environment variable name used to control the completion behavior (Default value = None)
    """
    if complete_var is None:
        complete_var = '_%s_COMPLETE' % (prog_name.replace('-', '_')).upper()
    complete_instr = os.environ.get(complete_var)
    if not complete_instr:
        return

    if complete_instr == 'source':
        echo(get_code(prog_name=prog_name, env_name=complete_var))
    elif complete_instr == 'source-bash':
        echo(get_code('bash', prog_name, complete_var))
    elif complete_instr == 'source-fish':
        echo(get_code('fish', prog_name, complete_var))
    elif complete_instr == 'source-powershell':
        echo(get_code('powershell', prog_name, complete_var))
    elif complete_instr == 'source-zsh':
        echo(get_code('zsh', prog_name, complete_var))
    elif complete_instr in ['complete', 'complete-bash']:
        # keep 'complete' for bash for backward compatibility
        do_bash_complete(cli, prog_name)
    elif complete_instr == 'complete-fish':
        do_fish_complete(cli, prog_name)
    elif complete_instr == 'complete-powershell':
        do_powershell_complete(cli, prog_name)
    elif complete_instr == 'complete-zsh':
        do_zsh_complete(cli, prog_name)
    elif complete_instr == 'install':
        shell, path = install(prog_name=prog_name, env_name=complete_var)
        click.echo('%s completion installed in %s' % (shell, path))
    elif complete_instr == 'install-bash':
        shell, path = install(shell='bash', prog_name=prog_name, env_name=complete_var)
        click.echo('%s completion installed in %s' % (shell, path))
    elif complete_instr == 'install-fish':
        shell, path = install(shell='fish', prog_name=prog_name, env_name=complete_var)
        click.echo('%s completion installed in %s' % (shell, path))
    elif complete_instr == 'install-zsh':
        shell, path = install(shell='zsh', prog_name=prog_name, env_name=complete_var)
        click.echo('%s completion installed in %s' % (shell, path))
    elif complete_instr == 'install-powershell':
        shell, path = install(shell='powershell', prog_name=prog_name, env_name=complete_var)
        click.echo('%s completion installed in %s' % (shell, path))
    sys.exit()


def patch():
    """Patch click"""
    import click
    click.types.ParamType.complete = param_type_complete
    click.types.Choice.complete = choice_complete
    click.core.MultiCommand.get_command_short_help = multicommand_get_command_short_help
    click.core.MultiCommand.get_command_hidden = multicommand_get_command_hidden
    click.core._bashcomplete = _shellcomplete
