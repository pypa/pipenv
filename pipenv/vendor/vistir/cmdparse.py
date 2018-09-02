# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import re
import shlex

import six


__all__ = ["ScriptEmptyError", "Script"]


class ScriptEmptyError(ValueError):
    pass


class Script(object):
    """Parse a script line (in Pipfile's [scripts] section).

    This always works in POSIX mode, even on Windows.
    """

    def __init__(self, command, args=None):
        self._parts = [command]
        if args:
            self._parts.extend(args)

    @classmethod
    def parse(cls, value):
        if isinstance(value, six.string_types):
            value = shlex.split(value)
        if not value:
            raise ScriptEmptyError(value)
        return cls(value[0], value[1:])

    def __repr__(self):
        return "Script({0!r})".format(self._parts)

    @property
    def command(self):
        return self._parts[0]

    @property
    def args(self):
        return self._parts[1:]

    def extend(self, extra_args):
        self._parts.extend(extra_args)

    def cmdify(self):
        """Encode into a cmd-executable string.

        This re-implements CreateProcess's quoting logic to turn a list of
        arguments into one single string for the shell to interpret.

        * All double quotes are escaped with a backslash.
        * Existing backslashes before a quote are doubled, so they are all
          escaped properly.
        * Backslashes elsewhere are left as-is; cmd will interpret them
          literally.

        The result is then quoted into a pair of double quotes to be grouped.

        An argument is intentionally not quoted if it does not contain
        whitespaces. This is done to be compatible with Windows built-in
        commands that don't work well with quotes, e.g. everything with `echo`,
        and DOS-style (forward slash) switches.

        The intended use of this function is to pre-process an argument list
        before passing it into ``subprocess.Popen(..., shell=True)``.

        See also: https://docs.python.org/3/library/subprocess.html#converting-argument-sequence
        """
        return " ".join(
            arg if not next(re.finditer(r'\s', arg), None)
            else '"{0}"'.format(re.sub(r'(\\*)"', r'\1\1\\"', arg))
            for arg in self._parts
        )
