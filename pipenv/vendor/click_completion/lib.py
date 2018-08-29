#!/usr/bin/env python
# -*- coding:utf-8 -*-

from __future__ import print_function, absolute_import

import re
import shlex

import click
import shellingham
from click import MultiCommand

find_unsafe = re.compile(r'[^\w@%+=:,./-]').search


def single_quote(s):
    """Escape a string with single quotes in order to be parsed as a single element by shlex

    Parameters
    ----------
    s : str
        The string to quote

    Returns
    -------
    str
       The quoted string
    """
    if not s:
        return "''"
    if find_unsafe(s) is None:
        return s

    # use single quotes, and put single quotes into double quotes
    # the string $'b is then quoted as '$'"'"'b'
    return "'" + s.replace("'", "'\"'\"'") + "'"


def double_quote(s):
    """Escape a string with double quotes in order to be parsed as a single element by shlex

    Parameters
    ----------
    s : str
        The string to quote

    Returns
    -------
    str
       The quoted string
    """
    if not s:
        return '""'
    if find_unsafe(s) is None:
        return s

    # use double quotes, and put double quotes into single quotes
    # the string $"b is then quoted as "$"'"'"b"
    return '"' + s.replace('"', '"\'"\'"') + '"'


def resolve_ctx(cli, prog_name, args):
    """

    Parameters
    ----------
    cli : click.Command
        The main click Command of the program
    prog_name : str
        The program name on the command line
    args : [str]
        The arguments already written by the user on the command line

    Returns
    -------
    click.core.Context
        A new context corresponding to the current command
    """
    ctx = cli.make_context(prog_name, list(args), resilient_parsing=True)
    while ctx.args + ctx.protected_args and isinstance(ctx.command, MultiCommand):
        a = ctx.protected_args + ctx.args
        cmd = ctx.command.get_command(ctx, a[0])
        if cmd is None:
            return None
        ctx = cmd.make_context(a[0], a[1:], parent=ctx, resilient_parsing=True)
    return ctx


def split_args(line):
    """Version of shlex.split that silently accept incomplete strings.

    Parameters
    ----------
    line : str
        The string to split

    Returns
    -------
    [str]
        The line split in separated arguments
    """
    lex = shlex.shlex(line, posix=True)
    lex.whitespace_split = True
    lex.commenters = ''
    res = []
    try:
        while True:
            res.append(next(lex))
    except ValueError:  # No closing quotation
        pass
    except StopIteration:  # End of loop
        pass
    if lex.token:
        res.append(lex.token)
    return res


def get_auto_shell():
    """Returns the current shell

    This feature depends on psutil and will not work if it is not available"""
    return shellingham.detect_shell()[0]
