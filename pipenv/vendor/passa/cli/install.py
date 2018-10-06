# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from ..actions.install import install
from ._base import BaseCommand
from .options import dev, no_check, no_clean


class Command(BaseCommand):

    name = "install"
    description = "Generate Pipfile.lock to synchronize the environment."
    arguments = [no_check, dev, no_clean]

    def run(self, options):
        return install(project=options.project, check=options.check, dev=options.dev,
                            clean=options.clean)


if __name__ == "__main__":
    Command.run_parser()
