"""
Package containing all pip commands
"""
from __future__ import absolute_import

from .completion import CompletionCommand
from .download import DownloadCommand
from .freeze import FreezeCommand
from .hash import HashCommand
from .help import HelpCommand
from .list import ListCommand
from .check import CheckCommand
from .search import SearchCommand
from .show import ShowCommand
from .install import InstallCommand
from .uninstall import UninstallCommand
from .wheel import WheelCommand


commands_dict = {
    CompletionCommand.name: CompletionCommand,
    FreezeCommand.name: FreezeCommand,
    HashCommand.name: HashCommand,
    HelpCommand.name: HelpCommand,
    SearchCommand.name: SearchCommand,
    ShowCommand.name: ShowCommand,
    InstallCommand.name: InstallCommand,
    UninstallCommand.name: UninstallCommand,
    DownloadCommand.name: DownloadCommand,
    ListCommand.name: ListCommand,
    CheckCommand.name: CheckCommand,
    WheelCommand.name: WheelCommand,
}


commands_order = [
    InstallCommand,
    DownloadCommand,
    UninstallCommand,
    FreezeCommand,
    ListCommand,
    ShowCommand,
    CheckCommand,
    SearchCommand,
    WheelCommand,
    HashCommand,
    CompletionCommand,
    HelpCommand,
]


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
