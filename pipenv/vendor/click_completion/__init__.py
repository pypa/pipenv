#!/usr/bin/env python
# -*- coding:utf-8 -*-

from __future__ import print_function, absolute_import

import six

from click import ParamType
if six.PY3:
    try:
        from enum import Enum
    except ImportError:
        from pipenv.vendor.backports.enum import Enum
else:
    from pipenv.vendor.backports.enum import Enum

from click_completion.core import completion_configuration, get_code, install, shells, resolve_ctx, get_choices, \
    startswith, Shell
from click_completion.lib import get_auto_shell
from click_completion.patch import patch as _patch

__version__ = '0.5.0'

_initialized = False


def init(complete_options=False, match_incomplete=None):
    """Initialize the enhanced click completion

    Parameters
    ----------
    complete_options : bool
        always complete the options, even when the user hasn't typed a first dash (Default value = False)
    match_incomplete : func
        a function with two parameters choice and incomplete. Must return True
        if incomplete is a correct match for choice, False otherwise.
    """
    global _initialized
    if not _initialized:
        _patch()
        completion_configuration.complete_options = complete_options
        if match_incomplete is not None:
            completion_configuration.match_incomplete = match_incomplete
        _initialized = True


class DocumentedChoice(ParamType):
    """The choice type allows a value to be checked against a fixed set of
    supported values.  All of these values have to be strings. Each value may
    be associated to a help message that will be display in the error message
    and during the completion.

    Parameters
    ----------
    choices : dict or Enum
        A dictionary with the possible choice as key, and the corresponding help string as value
    """
    name = 'choice'

    def __init__(self, choices):
        if isinstance(choices, Enum):
            self.choices = dict((choice.name, choice.value) for choice in choices)
        else:
            self.choices = dict(choices)

    def get_metavar(self, param):
        return '[%s]' % '|'.join(self.choices.keys())

    def get_missing_message(self, param):
        formated_choices = ['{:<12} {}'.format(k, self.choices[k] or '') for k in sorted(self.choices.keys())]
        return 'Choose from\n  ' + '\n  '.join(formated_choices)

    def convert(self, value, param, ctx):
        # Exact match
        if value in self.choices:
            return value

        # Match through normalization
        if ctx is not None and \
           ctx.token_normalize_func is not None:
            value = ctx.token_normalize_func(value)
            for choice in self.choices:
                if ctx.token_normalize_func(choice) == value:
                    return choice

        self.fail('invalid choice: %s. %s' %
                  (value, self.get_missing_message(param)), param, ctx)

    def __repr__(self):
        return 'DocumentedChoice(%r)' % list(self.choices.keys())

    def complete(self, ctx, incomplete):
        match = completion_configuration.match_incomplete
        return [(c, v) for c, v in six.iteritems(self.choices) if match(c, incomplete)]
