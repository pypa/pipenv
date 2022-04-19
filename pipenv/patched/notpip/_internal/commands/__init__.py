"""
Package containing all pip commands
"""

import importlib
from collections import namedtuple
from typing import Any, Dict, Optional

from pipenv.patched.notpip._internal.cli.base_command import Command

CommandInfo = namedtuple("CommandInfo", "module_path, class_name, summary")

# This dictionary does a bunch of heavy lifting for help output:
# - Enables avoiding additional (costly) imports for presenting `--help`.
# - The ordering matters for help display.
#
# Even though the module path starts with the same "pipenv.patched.notpip._internal.commands"
# prefix, the full path makes testing easier (specifically when modifying
# `commands_dict` in test setup / teardown).
commands_dict: Dict[str, CommandInfo] = {
    "install": CommandInfo(
        "pipenv.patched.notpip._internal.commands.install",
        "InstallCommand",
        "Install packages.",
    ),
    "download": CommandInfo(
        "pipenv.patched.notpip._internal.commands.download",
        "DownloadCommand",
        "Download packages.",
    ),
    "uninstall": CommandInfo(
        "pipenv.patched.notpip._internal.commands.uninstall",
        "UninstallCommand",
        "Uninstall packages.",
    ),
    "freeze": CommandInfo(
        "pipenv.patched.notpip._internal.commands.freeze",
        "FreezeCommand",
        "Output installed packages in requirements format.",
    ),
    "list": CommandInfo(
        "pipenv.patched.notpip._internal.commands.list",
        "ListCommand",
        "List installed packages.",
    ),
    "show": CommandInfo(
        "pipenv.patched.notpip._internal.commands.show",
        "ShowCommand",
        "Show information about installed packages.",
    ),
    "check": CommandInfo(
        "pipenv.patched.notpip._internal.commands.check",
        "CheckCommand",
        "Verify installed packages have compatible dependencies.",
    ),
    "config": CommandInfo(
        "pipenv.patched.notpip._internal.commands.configuration",
        "ConfigurationCommand",
        "Manage local and global configuration.",
    ),
    "search": CommandInfo(
        "pipenv.patched.notpip._internal.commands.search",
        "SearchCommand",
        "Search PyPI for packages.",
    ),
    "cache": CommandInfo(
        "pipenv.patched.notpip._internal.commands.cache",
        "CacheCommand",
        "Inspect and manage pip's wheel cache.",
    ),
    "index": CommandInfo(
        "pipenv.patched.notpip._internal.commands.index",
        "IndexCommand",
        "Inspect information available from package indexes.",
    ),
    "wheel": CommandInfo(
        "pipenv.patched.notpip._internal.commands.wheel",
        "WheelCommand",
        "Build wheels from your requirements.",
    ),
    "hash": CommandInfo(
        "pipenv.patched.notpip._internal.commands.hash",
        "HashCommand",
        "Compute hashes of package archives.",
    ),
    "completion": CommandInfo(
        "pipenv.patched.notpip._internal.commands.completion",
        "CompletionCommand",
        "A helper command used for command completion.",
    ),
    "debug": CommandInfo(
        "pipenv.patched.notpip._internal.commands.debug",
        "DebugCommand",
        "Show information useful for debugging.",
    ),
    "help": CommandInfo(
        "pipenv.patched.notpip._internal.commands.help",
        "HelpCommand",
        "Show help for commands.",
    ),
}


def create_command(name: str, **kwargs: Any) -> Command:
    """
    Create an instance of the Command class with the given name.
    """
    module_path, class_name, summary = commands_dict[name]
    module = importlib.import_module(module_path)
    command_class = getattr(module, class_name)
    command = command_class(name=name, summary=summary, **kwargs)

    return command


def get_similar_commands(name: str) -> Optional[str]:
    """Command name auto-correct."""
    from difflib import get_close_matches

    name = name.lower()

    close_commands = get_close_matches(name, commands_dict.keys())

    if close_commands:
        return close_commands[0]
    else:
        return None
