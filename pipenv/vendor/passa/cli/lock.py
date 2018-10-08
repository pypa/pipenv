# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ..actions.lock import lock
from ._base import BaseCommand


class Command(BaseCommand):
    name = "lock"
    description = "Generate Pipfile.lock."

    def run(self, options):
        return lock(project=options.project)


if __name__ == "__main__":
    Command.run_parser()
