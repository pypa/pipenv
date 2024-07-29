import re
import shlex

from .base import DataModel, DataValidationError


class Script(DataModel):
    """Parse a script line (in Pipfile's [scripts] section).

    This always works in POSIX mode, even on Windows.
    """
    __OPTIONAL__ = {
        "script": (str, list, dict)
    }

    def __init__(self, data):
        self.validate(data)
        if isinstance(data, str):
            data = shlex.split(data)
        self._parts = data[::]

    @classmethod
    def validate(cls, data):
        if not data:
            raise DataValidationError("Script cannot be empty")
        for k, types in cls.__OPTIONAL__.items():
            if not isinstance(data, types):
                raise DataValidationError(f"Invalid type for {k}: {type(data)}")
    def __repr__(self):
        return "Script({0!r})".format(self._parts)

    @property
    def command(self):
        return self._parts[0]

    @property
    def args(self):
        return self._parts[1:]

    def cmdify(self, extra_args=None):
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

        See also: https://docs.python.org/3/library/subprocess.html
        """
        parts = list(self._parts)
        if extra_args:
            parts.extend(extra_args)
        return " ".join(
            arg if not next(re.finditer(r'\s', arg), None)
            else '"{0}"'.format(re.sub(r'(\\*)"', r'\1\1\\"', arg))
            for arg in parts
        )
