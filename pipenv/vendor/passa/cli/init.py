# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import argparse
import os

from ..actions.init import init_project
from ._base import BaseCommand
from .options import new_project_group


class Command(BaseCommand):

    name = "init"
    description = "Create a new project."
    default_arguments = []
    arguments = [new_project_group]

    def run(self, options):
        pipfile_path = os.path.join(options.project, "Pipfile")
        if os.path.exists(pipfile_path):
            raise argparse.ArgumentError(
                "{0!r} is already a Pipfile project".format(options.project),
            )
        return init_project(
            root=options.project, python_version=options.python_version
        )


if __name__ == "__main__":
    Command.run_parser()
