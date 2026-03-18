import itertools
import re
import shlex

from pipenv.vendor import tomlkit


class ScriptEmptyError(ValueError):
    pass


class ScriptParseError(ValueError):
    pass


# Matches a shell-style inline environment variable assignment such as
# ``FOO=bar`` or ``MY_VAR=hello world`` (after shlex has stripped quotes).
# The name must be a valid POSIX identifier: letter/underscore, then
# letters/digits/underscores.  The value may be anything (including empty).
_ENV_VAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)


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

    A script may be defined in any of these forms in the Pipfile ``[scripts]``
    section:

    * **String** — a single command, shell-split into tokens::

        test = "pytest -x"

    * **Inline table** — extended syntax for callable scripts::

        check = {call = "mypackage.checks:run()"}

    * **Array of strings** — a *sequence* of commands run in order; execution
      stops at the first non-zero exit code (equivalent to ``&&`` chaining)::

        lint = ["ruff check .", "ruff format --check ."]

      Extra arguments supplied on the command line (``pipenv run lint --fix``)
      are appended to the **last** command in the sequence.
    """

    script_types = ["call"]

    def __init__(self, command, args=None):
        self._parts = [command]
        if args:
            self._parts.extend(args)
        # When the script was parsed from a TOML array, _sequence holds an
        # ordered list of Script objects to execute one after the other.
        self._sequence = None  # type: list[Script] | None

    @classmethod
    def parse(cls, value):
        if isinstance(value, list):
            return cls._parse_sequence(value)
        if isinstance(value, tomlkit.items.InlineTable):
            cmd_string = _parse_toml_inline_table(value)
            value = shlex.split(cmd_string)
        elif isinstance(value, str):
            value = shlex.split(value)
        if not value:
            raise ScriptEmptyError(value)
        return cls(value[0], value[1:])

    @classmethod
    def _parse_sequence(cls, items):
        """Parse a TOML array of command strings into a sequential script.

        Each element must be a non-empty string; it is shell-split (POSIX
        mode) to obtain the command and its arguments.

        Raises:
            ScriptParseError: if an element is not a string.
            ScriptEmptyError: if the list is empty or any element is blank.
        """
        if not items:
            raise ScriptEmptyError(items)
        scripts = []
        for item in items:
            if not isinstance(item, str):
                raise ScriptParseError(
                    f"Each item in a script sequence must be a string, got {type(item)!r}"
                )
            parts = shlex.split(item)
            if not parts:
                raise ScriptEmptyError(item)
            scripts.append(cls(parts[0], parts[1:]))
        # The outer Script mirrors the *first* sub-script's command/args so
        # that callers that only inspect .command/.args still see something
        # sensible (e.g. verbose logging of the first step).
        result = cls(scripts[0].command, scripts[0].args)
        result._sequence = scripts
        return result

    @property
    def is_sequence(self):
        """True when this script represents multiple sequential commands."""
        return self._sequence is not None

    def __repr__(self):
        if self._sequence is not None:
            return f"Script(sequence={self._sequence!r})"
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
        """Append *extra_args* to the script.

        For sequence scripts the extra arguments are appended to the **last**
        command in the sequence (most useful when extra CLI flags are meant for
        the primary/final command, e.g. ``pipenv run test -v``).
        """
        if self._sequence is not None:
            self._sequence[-1]._parts.extend(extra_args)
        else:
            self._parts.extend(extra_args)

    def with_extracted_env_vars(self):
        """Extract leading ``KEY=value`` tokens from this script's command/args.

        Handles inline environment variable assignments that precede the real
        command, for example::

            FOO=bar python script.py
            MY_VAR=hello pytest -x

        Works whether the assignment came from the command line
        (``pipenv run FOO=bar cmd``) or from a Pipfile ``[scripts]`` entry
        whose string began with ``KEY=value`` tokens.

        Returns a ``(new_script, env_dict)`` tuple where *new_script* has the
        env-var tokens removed and *env_dict* maps each extracted name to its
        value string.  If no inline env vars are present the original script
        object and an empty dict are returned unchanged.
        """
        parts = list(self._parts)  # [command, *args]
        inline_env = {}
        i = 0
        # Leave at least one token so we never consume the real command.
        while i < len(parts) - 1:
            m = _ENV_VAR_RE.match(parts[i])
            if not m:
                break
            inline_env[m.group(1)] = m.group(2)
            i += 1
        if not inline_env:
            return self, {}
        new_script = Script(parts[i], parts[i + 1 :])
        return new_script, inline_env

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
