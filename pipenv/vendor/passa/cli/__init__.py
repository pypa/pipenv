# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import argparse
import importlib
import pkgutil
import sys

from passa import __version__


CURRENT_MODULE_PATH = sys.modules[__name__].__path__


def main(argv=None):
    root_parser = argparse.ArgumentParser(
        prog="passa",
        description="Pipfile project management tool.",
    )
    root_parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s, version {}".format(__version__),
        help="show the version and exit",
    )

    subparsers = root_parser.add_subparsers()
    for _, name, _ in pkgutil.iter_modules(CURRENT_MODULE_PATH, "."):
        module = importlib.import_module(name, __name__)
        try:
            klass = module.Command
        except AttributeError:
            continue
        parser = subparsers.add_parser(klass.name, help=klass.description)
        command = klass(parser)
        parser.set_defaults(func=command.run)

    options = root_parser.parse_args(argv)

    try:
        f = options.func
    except AttributeError:
        root_parser.print_help()
        result = -1
    else:
        result = f(options)
    if result is not None:
        sys.exit(result)
