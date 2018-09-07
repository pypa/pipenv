# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ._base import BaseCommand


def main(options):
    from passa.operations.sync import sync
    from passa.synchronizers import Synchronizer

    project = options.project
    syncer = Synchronizer(
        project, default=True, develop=options.dev,
        clean_unneeded=options.clean,
    )

    success = sync(syncer)
    if not success:
        return 1

    print("Synchronized project at", project.root)


class Command(BaseCommand):

    name = "sync"
    description = "Install Pipfile.lock into the current environment."
    parsed_main = main

    def add_arguments(self):
        super(Command, self).add_arguments()
        self.parser.add_argument(
            "--dev",
            action="store_true",
            help="install develop packages",
        )
        self.parser.add_argument(
            "--no-clean", dest="clean",
            action="store_false", default=True,
            help="do not uninstall packages not specified in Pipfile.lock",
        )


if __name__ == "__main__":
    Command.run_current_module()
