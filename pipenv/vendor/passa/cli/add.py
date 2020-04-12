# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ..actions.add import add_packages
from ._base import BaseCommand
from .options import package_group


class Command(BaseCommand):

    name = "add"
    description = "Add packages to project."
    arguments = [package_group]

    def run(self, options):
        if not options.editables and not options.packages:
            self.parser.error("Must supply either a requirement or --editable")
        return add_packages(
            packages=options.packages,
            editables=options.editables,
            project=options.project,
            dev=options.dev,
            sync=options.sync
        )


if __name__ == "__main__":
    Command.run_parser()
