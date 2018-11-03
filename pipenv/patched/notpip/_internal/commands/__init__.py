"""
Package containing all pip commands
"""
from __future__ import absolute_import
import importlib
import sys


class _command(object):

    def __dir__(self):
        result = list(self._locations.keys()) + list(self.__dict__.keys())
        result.extend(('__file__', '__doc__', '__all__',
                       '__docformat__', '__name__', '__path__',
                       '__package__', '__version__'))
        return result

    @property
    def __all__(self):
        return self._commands_order + ["get_summaries", "get_similar_commands"]

    @classmethod
    def _new(cls):
        return cls()

    def __init__(self):
        self._modules = {
            "sys": sys,
        }
        self._module_paths = {}
        self._cached_commands_order = []
        self._commands_order = [
            "pipenv.patched.notpip._internal.commands.install.InstallCommand",
            "pipenv.patched.notpip._internal.commands.download.DownloadCommand",
            "pipenv.patched.notpip._internal.commands.uninstall.UninstallCommand",
            "pipenv.patched.notpip._internal.commands.freeze.FreezeCommand",
            "pipenv.patched.notpip._internal.commands.list.ListCommand",
            "pipenv.patched.notpip._internal.commands.show.ShowCommand",
            "pipenv.patched.notpip._internal.commands.check.CheckCommand",
            "pipenv.patched.notpip._internal.commands.configuration.ConfigurationCommand",
            "pipenv.patched.notpip._internal.commands.search.SearchCommand",
            "pipenv.patched.notpip._internal.commands.wheel.WheelCommand",
            "pipenv.patched.notpip._internal.commands.hash.HashCommand",
            "pipenv.patched.notpip._internal.commands.completion.CompletionCommand",
            "pipenv.patched.notpip._internal.commands.help.HelpCommand",
        ]
        for cmd in self._commands_order:
            _, _, cmdname = cmd.rpartition(".")
            self._module_paths[cmdname] = cmd
        self._commands_dict = {}

    @property
    def commands_order(self):
        if not self._cached_commands_order:
            commands = [self.get_package(cmd) for cmd in self._commands_order]
            self._cached_commands_order = [getattr(self, cmd) for _, cmd in commands]
        return self._cached_commands_order

    @property
    def commands_dict(self):
        if not self._commands_dict:
            self._commands_dict = {c.name: c for c in self.commands_order}
        return self._commands_dict

    def __getattr__(self, key):
        modules = super(_command, self).__getattribute__("_modules")
        module_paths = super(_command, self).__getattribute__("_module_paths")
        if key in modules:
            return modules[key]
        elif key in self._module_paths:
            module = self._import(module_paths[key])
            if module:
                self._modules[key] = module
                return module
        return super(_command, self).__getattribute__(key)

    def get_package(self, module, subimport=None):
        package = None
        if subimport:
            package = subimport
        else:
            module, _, package = module.rpartition(".")
        return module, package

    def get_package_from_module(self, module):
        module, package = self.get_package(module)
        mod = importlib.import_module(module)
        pkg = getattr(mod, package, None)
        return pkg

    def _import(self, package):
        return self.get_package_from_module(module)

    def get_summaries(self, ordered=True):
        """Yields sorted (command name, command summary) tuples."""

        if ordered:
            cmditems = self._sort_commands(self.commands_dict, self.commands_order)
        else:
            cmditems = self.commands_dict.items()

        for name, command_class in cmditems:
            yield (name, command_class.summary)

    def get_similar_commands(self, name):
        """Command name auto-correct."""
        from difflib import get_close_matches

        name = name.lower()

        close_commands = get_close_matches(name, self.commands_dict.keys())

        if close_commands:
            return close_commands[0]
        else:
            return False

    def _sort_commands(self, cmddict, order):
        def keyfn(key):
            try:
                return order.index(key[1])
            except ValueError:
                # unordered items should come last
                return 0xff

        return sorted(cmddict.items(), key=keyfn)


old_module = sys.modules[__name__] if __name__ in sys.modules else None
module = sys.modules[__name__] = _command()
module.__dict__.update({
    '__file__': __file__,
    '__package__': __package__,
    '__doc__': __doc__,
    '__all__': module.__all__,
    '__name__': __name__,
})
