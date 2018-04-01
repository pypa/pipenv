import re
import shlex

import six


class Script(object):
    """Parse a script line (in Pipfile's [scripts] section).

    This always works in POSIX mode, even on Windows.
    """
    def __init__(self, parts):
        if not parts:
            raise ValueError('invalid script')
        self._parts = parts


    @classmethod
    def parse(cls, value):
        if isinstance(value, six.text_type):
            value = shlex.split(value)
        return cls(value)

    def __repr__(self):
        return 'Script({0!r})'.format(self._parts)

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

        The intended use of this function is to pre-process an argument list
        before passing it into ``subprocess.Popen(..., shell=True)``.

        See also: https://docs.python.org/3/library/subprocess.html#converting-argument-sequence
        """
        return ' '.join(
            '"{0}"'.format(re.sub(r'(\\*)"', r'\1\1\\"', arg))
            for arg in self._parts
        )
