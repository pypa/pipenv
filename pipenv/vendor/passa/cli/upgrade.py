# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

from ..actions.upgrade import upgrade
from ._base import BaseCommand
from .options import no_clean, no_sync, packages, strategy


class Command(BaseCommand):

    name = "upgrade"
    description = "Upgrade packages in project."
    arguments = [packages, strategy, no_clean, no_sync]

    def run(self, options):
        return upgrade(project=options.project, strategy=options.strategy,
                            sync=options.sync, packages=options.packages)


if __name__ == "__main__":
    Command.run_parser()
