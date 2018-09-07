# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ._base import BaseCommand


def main(options):
    from passa.operations.sync import clean
    from passa.synchronizers import Cleaner

    project = options.project
    cleaner = Cleaner(project, default=True, develop=options.dev)

    success = clean(cleaner)
    if not success:
        return 1

    print("Cleaned project at", project.root)


class Command(BaseCommand):

    name = "clean"
    description = "Uninstall unlisted packages from the current environment."
    parsed_main = main

    def add_arguments(self):
        super(Command, self).add_arguments()
        self.parser.add_argument(
            "--no-dev", dest="dev",
            action="store_false", default=True,
            help="uninstall develop packages, only keep default ones",
        )


if __name__ == "__main__":
    Command.run_current_module()
