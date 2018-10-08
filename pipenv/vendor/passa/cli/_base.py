# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import argparse
import os
import sys

from .options import project


class BaseCommand(object):
    """A CLI command.
    """
    name = None
    description = None
    default_arguments = [project]
    arguments = []

    def __init__(self, parser=None):
        if not parser:
            parser = argparse.ArgumentParser(
                prog=os.path.basename(sys.argv[0]),
                description="Base argument parser for passa"
            )
        self.parser = parser
        self.add_arguments()

    @classmethod
    def build_parser(cls):
        parser = argparse.ArgumentParser(
            prog="passa {}".format(cls.name),
            description=cls.description,
        )
        return cls(parser)

    @classmethod
    def run_parser(cls):
        parser = cls.build_parser()
        parser()

    def __call__(self, argv=None):
        options = self.parser.parse_args(argv)
        result = self.main(options)
        if result is not None:
            sys.exit(result)

    def add_default_arguments(self):
        for arg in self.default_arguments:
            arg.add_to_parser(self.parser)

    def add_arguments(self):
        self.add_default_arguments()
        for arg in self.arguments:
            arg.add_to_parser(self.parser)

    def main(self, options):
        return self.run(options)

    def run(self, options):
        raise NotImplementedError
