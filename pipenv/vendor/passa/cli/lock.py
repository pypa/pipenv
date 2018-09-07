# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ._base import BaseCommand


def main(options):
    from passa.lockers import BasicLocker
    from passa.operations.lock import lock

    project = options.project
    locker = BasicLocker(project)
    success = lock(locker)
    if not success:
        return

    project._l.write()
    print("Written to project at", project.root)


class Command(BaseCommand):
    name = "lock"
    description = "Generate Pipfile.lock."
    parsed_main = main


if __name__ == "__main__":
    Command.run_current_module()
