# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ._base import BaseCommand


def main(options):
    from passa.lockers import BasicLocker
    from passa.operations.lock import lock

    project = options.project

    if not options.check or not project.is_synced():
        locker = BasicLocker(project)
        success = lock(locker)
        if not success:
            return 1
        project._l.write()
        print("Written to project at", project.root)

    from passa.operations.sync import sync
    from passa.synchronizers import Synchronizer

    syncer = Synchronizer(
        project, default=True, develop=options.dev,
        clean_unneeded=options.clean,
    )

    success = sync(syncer)
    if not success:
        return 1

    print("Synchronized project at", project.root)


class Command(BaseCommand):

    name = "install"
    description = "Generate Pipfile.lock to synchronize the environment."
    parsed_main = main

    def add_arguments(self):
        super(Command, self).add_arguments()
        self.parser.add_argument(
            "--no-check", dest="check",
            action="store_false", default=True,
            help="do not check if Pipfile.lock is update, always resolve",
        )
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
