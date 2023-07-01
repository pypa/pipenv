import itertools
import re
import shlex

from pipenv.vendor import tomlkit


class ScriptEmptyError(ValueError):
    pass


class ScriptParseError(ValueError):
    pass


def _quote_if_contains(value, pattern):
    if next(iter(re.finditer(pattern, value)), None):
        return '"{}"'.format(re.sub(r'(\\*)"', r'\1\1\\"', value))
    return value


def _parse_toml_inline_table(value: tomlkit.items.InlineTable) -> str:
    """parses the [scripts] in pipfile and converts: `{call = "package.module:func('arg')"}` into an executable command"""
    keys_list = list(value.keys())
    if len(keys_list) > 1:
        raise ScriptParseError("More than 1 key in toml script line")
    cmd_key = keys_list[0]
    if cmd_key not in Script.script_types:
        raise ScriptParseError(
            f"Not an accepted script callabale, options are: {Script.script_types}"
        )
    if cmd_key == "call":
        module, _, func = str(value["call"]).partition(":")
        if not module or not func:
            raise ScriptParseError(
                "Callable must be like: name = {call = \"package.module:func('arg')\"}"
            )
        if re.search(r"\(.*?\)", func) is None:
            func += "()"
        return f'python -c "import {module} as _m; _m.{func}"'


class Script:
    """Parse a script line (in Pipfile's [scripts] section).

    This always works in POSIX mode, even on Windows.
    """

    script_types = ["call"]

    def __init__(self, command, args=None):
        self._parts = [command]
        if args:
            self._parts.extend(args)

    @classmethod
    def parse(cls, value):
        if isinstance(value, tomlkit.items.InlineTable):
            cmd_string = _parse_toml_inline_table(value)
            value = shlex.split(cmd_string)
        elif isinstance(value, str):
            value = shlex.split(value)
        if not value:
            raise ScriptEmptyError(value)
        return cls(value[0], value[1:])

    def __repr__(self):
        return f"Script({self._parts!r})"

    @property
    def command(self):
        return self._parts[0]

    @property
    def args(self):
        return self._parts[1:]

    @property
    def cmd_args(self):
        return self._parts

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
        foul characters. This is done to be compatible with Windows built-in
        commands that don't work well with quotes, e.g. everything with `echo`,
        and DOS-style (forward slash) switches.

        Foul characters include:

        * Whitespaces.
        * Carets (^). (pypa/pipenv#3307)
        * Parentheses in the command. (pypa/pipenv#3168)

        Carets introduce a difficult situation since they are essentially
        "lossy" when parsed. Consider this in cmd.exe::

            > echo "foo^bar"
            "foo^bar"
            > echo foo^^bar
            foo^bar

        The two commands produce different results, but are both parsed by the
        shell as `foo^bar`, and there's essentially no sensible way to tell
        what was actually passed in. This implementation assumes the quoted
        variation (the first) since it is easier to implement, and arguably
        the more common case.

        The intended use of this function is to pre-process an argument list
        before passing it into ``subprocess.Popen(..., shell=True)``.

        See also: https://docs.python.org/3/library/subprocess.html#converting-argument-sequence
        """
        return " ".join(
            itertools.chain(
                [_quote_if_contains(self.command, r"[\s^()]")],
                (_quote_if_contains(arg, r"[\s^]") for arg in self.args),
            )
        )
