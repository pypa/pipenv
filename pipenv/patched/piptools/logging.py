# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys

from . import click


class LogContext(object):
    def __init__(self, verbosity=0):
        self.verbosity = verbosity

    def log(self, *args, **kwargs):
        click.secho(*args, **kwargs)

    def debug(self, *args, **kwargs):
        if self.verbosity >= 1:
            self.log(*args, **kwargs)

    def info(self, *args, **kwargs):
        if self.verbosity >= 0:
            self.log(*args, **kwargs)

    def warning(self, *args, **kwargs):
        kwargs.setdefault('fg', 'yellow')
        kwargs.setdefault('file', sys.stderr)
        self.log(*args, **kwargs)

    def error(self, *args, **kwargs):
        kwargs.setdefault('fg', 'red')
        kwargs.setdefault('file', sys.stderr)
        self.log(*args, **kwargs)


log = LogContext()
