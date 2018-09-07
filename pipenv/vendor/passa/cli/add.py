# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import itertools
import sys

from ._base import BaseCommand


def main(options):
    from passa.lockers import PinReuseLocker
    from passa.operations.lock import lock

    lines = list(itertools.chain(
        options.requirement_lines,
        ("-e {}".format(e) for e in options.editable_lines),
    ))

    project = options.project
    for line in lines:
        try:
            project.add_line_to_pipfile(line, develop=options.dev)
        except (TypeError, ValueError) as e:
            print("Cannot add {line!r} to Pipfile: {error}".format(
                line=line, error=str(e),
            ), file=sys.stderr)
            return 2

    prev_lockfile = project.lockfile

    locker = PinReuseLocker(project)
    success = lock(locker)
    if not success:
        return 1

    project._p.write()
    project._l.write()
    print("Written to project at", project.root)

    if not options.sync:
        return

    from passa.operations.sync import sync
    from passa.synchronizers import Synchronizer

    lockfile_diff = project.difference_lockfile(prev_lockfile)
    default = bool(any(lockfile_diff.default))
    develop = bool(any(lockfile_diff.develop))

    syncer = Synchronizer(
        project, default=default, develop=develop,
        clean_unneeded=False,
    )
    success = sync(syncer)
    if not success:
        return 1

    print("Synchronized project at", project.root)


class Command(BaseCommand):

    name = "add"
    description = "Add packages to project."
    parsed_main = main

    def add_arguments(self):
        super(Command, self).add_arguments()
        self.parser.add_argument(
            "requirement_lines", metavar="requirement",
            nargs="*",
            help="requirement to add (can be used multiple times)",
        )
        self.parser.add_argument(
            "-e", "--editable",
            metavar="requirement", dest="editable_lines",
            action="append", default=[],
            help="editable requirement to add (can be used multiple times)",
        )
        self.parser.add_argument(
            "--dev",
            action="store_true",
            help="add packages to [dev-packages]",
        )
        self.parser.add_argument(
            "--no-sync", dest="sync",
            action="store_false", default=True,
            help="do not synchronize the environment",
        )

    def main(self, options):
        if not options.editable_lines and not options.requirement_lines:
            self.parser.error("Must supply either a requirement or --editable")
        return super(Command, self).main(options)


if __name__ == "__main__":
    Command.run_current_module()
