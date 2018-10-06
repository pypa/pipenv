# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ..actions.freeze import freeze
from ._base import BaseCommand
from .options import dev, include_hashes_group, no_default, target


class Command(BaseCommand):

    name = "freeze"
    description = "Export project depenencies to requirements.txt."
    arguments = [dev, no_default, target, include_hashes_group]

    def run(self, options):
        return freeze(
            project=options.project, default=options.default, dev=options.dev,
            include_hashes=options.include_hashes
        )


if __name__ == "__main__":
    Command.run_parser()
