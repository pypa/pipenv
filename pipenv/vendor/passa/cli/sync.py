# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ..actions.sync import sync
from ._base import BaseCommand
from .options import dev, no_clean


class Command(BaseCommand):

    name = "sync"
    description = "Install Pipfile.lock into the environment."
    arguments = [dev, no_clean]

    def run(self, options):
        return sync(project=options.project, dev=options.dev, clean=options.clean)


if __name__ == "__main__":
    Command.run_parser()
