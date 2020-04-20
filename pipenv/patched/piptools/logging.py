# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

from . import click


class LogContext(object):
    def __init__(self, verbosity=0):
        self.verbosity = verbosity

    def log(self, *args, **kwargs):
        kwargs.setdefault("err", True)
        click.secho(*args, **kwargs)

    def debug(self, *args, **kwargs):
        if self.verbosity >= 1:
            self.log(*args, **kwargs)

    def info(self, *args, **kwargs):
        if self.verbosity >= 0:
            self.log(*args, **kwargs)

    def warning(self, *args, **kwargs):
        kwargs.setdefault("fg", "yellow")
        self.log(*args, **kwargs)

    def error(self, *args, **kwargs):
        kwargs.setdefault("fg", "red")
        self.log(*args, **kwargs)


log = LogContext()
