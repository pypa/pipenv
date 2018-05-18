"""
Package containing all pip commands
"""
from __future__ import absolute_import

from notpip._internal.commands.completion import CompletionCommand
from notpip._internal.commands.configuration import ConfigurationCommand
from notpip._internal.commands.download import DownloadCommand
from notpip._internal.commands.freeze import FreezeCommand
from notpip._internal.commands.hash import HashCommand
from notpip._internal.commands.help import HelpCommand
from notpip._internal.commands.list import ListCommand
from notpip._internal.commands.check import CheckCommand
from notpip._internal.commands.search import SearchCommand
from notpip._internal.commands.show import ShowCommand
from notpip._internal.commands.install import InstallCommand
from notpip._internal.commands.uninstall import UninstallCommand
from notpip._internal.commands.wheel import WheelCommand

from notpip._internal.utils.typing import MYPY_CHECK_RUNNING

if MYPY_CHECK_RUNNING:
    from typing import List, Type
    from notpip._internal.basecommand import Command

commands_order = [
    InstallCommand,
    DownloadCommand,
    UninstallCommand,
    FreezeCommand,
    ListCommand,
    ShowCommand,
    CheckCommand,
    ConfigurationCommand,
    SearchCommand,
    WheelCommand,
    HashCommand,
    CompletionCommand,
    HelpCommand,
]  # type: List[Type[Command]]

commands_dict = {c.name: c for c in commands_order}


def get_summaries(ordered=True):
    """Yields sorted (command name, command summary) tuples."""

    if ordered:
        cmditems = _sort_commands(commands_dict, commands_order)
    else:
        cmditems = commands_dict.items()

    for name, command_class in cmditems:
        yield (name, command_class.summary)


def get_similar_commands(name):
    """Command name auto-correct."""
    from difflib import get_close_matches

    name = name.lower()

    close_commands = get_close_matches(name, commands_dict.keys())

    if close_commands:
        return close_commands[0]
    else:
        return False


def _sort_commands(cmddict, order):
    def keyfn(key):
        try:
            return order.index(key[1])
        except ValueError:
            # unordered items should come last
            return 0xff

    return sorted(cmddict.items(), key=keyfn)
