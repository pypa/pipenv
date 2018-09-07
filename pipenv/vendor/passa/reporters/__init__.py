# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from .base import BaseReporter


_REPORTER = BaseReporter()


def _get_stdout_reporter():
    from .stdout import Reporter
    return Reporter()


def configure_reporter(name):
    global _REPORTER
    _REPORTER = {
        None: BaseReporter,
        "stdout": _get_stdout_reporter,
    }[name]()


def get_reporter():
    return _REPORTER


def report(event, context=None):
    if context is None:
        context = {}
    _REPORTER.report(event, context)
