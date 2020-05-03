import itertools
import re
import shlex
import os
import six
import click
import crayons


class UnixShellEnvironmentVariable(object):
    """
    This class provides an abstraction on
    unix shell environment variables assignments.

    It uses a set of regular expressions:

    # ENV_VAR_NAME_REGEX matches the env var name, which requires:
        - must not start with a number
        - only letters, numbers and underscore allowed

    # ENV_VAR_VALUE_REGEX matches a correct value for an env var:
        - A value not enclosed in quote characters, must not start with "="
        - A value enclosed in quotes, must end with the same quote character used to open.
        - Carriage return and Newline are not allowed into the value.

    # ENV_VAR_REGEX is a composition of the two previous regex:
        - No spacing allowed before and after the equal sign.
    """

    ENV_VAR_NAME_REGEX = r"([a-zA-Z_]+[a-zA-Z_0-9]*)"
    ENV_VAR_VALUE_REGEX = \
        r"((\"((?:[^\r\n\"\\]|\\.)*)\")|" + \
        r"('((?:[^\r\n'\\]|\\.)*)')|" + \
        r"([^\|&<>=\"\'\r\n][^\|&<>\"\'\r\n]*))"
    ENV_VAR_REGEX = r"^{name_rgx}={value_rgx}".format(
        name_rgx=ENV_VAR_NAME_REGEX,
        value_rgx=ENV_VAR_VALUE_REGEX
    )

    def __init__(self, name, value, full_expr=None):
        m = re.match(self.ENV_VAR_NAME_REGEX, name)
        if not m:
            raise ValueError("The value '{}' didn't match the ENV_VAR_NAME_REGEX!".format(name))

        m = re.match(self.ENV_VAR_NAME_REGEX, value)
        if not m:
            raise ValueError("The value '{}' didn't match the ENV_VAR_VALUE_REGEX!".format(value))

        self._name = name
        self._value = value
        if full_expr:
            self.full_expr = full_expr
        else:
            self.full_expr = '{}=\'{}\''.format(name, value)

    @classmethod
    def parse_inline(cls, env_var_assignment):
        m = re.match(cls.ENV_VAR_REGEX, env_var_assignment)
        if not m:
            raise ValueError("The value '{}' didn't match the ENV_VAR_REGEX!".format(env_var_assignment))

        return cls(
            m.group(1),
            (m.group(4) or m.group(6) or m.group(7)),
            full_expr=m.group(0),
        )

    @property
    def name(self):
        return self._name

    @property
    def value(self):
        return self._value


class ScriptEmptyError(ValueError):
    pass


def _quote_if_contains(value, pattern):
    if next(iter(re.finditer(pattern, value)), None):
        return '"{0}"'.format(re.sub(r'(\\*)"', r'\1\1\\"', value))
    return value


class Script(object):
    """Parse a script line (in Pipfile's [scripts] section).

    This always works in POSIX mode, even on Windows.
    """

    def __init__(
        self,
        command,
        args=None,
        env_vars=None
    ):
        self._parts = [command]
        if args:
            self._parts.extend(args)

        for env_var in (env_vars or []):
            os.environ.putenv(
                env_var.name,
                env_var.value
            )

    @classmethod
    def parse(cls, value):
        env_vars = []
        if isinstance(value, six.string_types):
            value = shlex.split(value)

            for el in value:
                try:
                    env_var = UnixShellEnvironmentVariable.parse_inline(el)
                    env_vars.append(env_var)
                    value.remove(el)
                    click.echo(
                        crayons.yellow(
                            "WARNING: Found environment variable '{}' in command. ".format(env_var.full_expr) +
                            "Use env property in Pipfile instead!"
                        )
                    )
                except ValueError:
                    pass

        if isinstance(value, dict):
            value = shlex.split(value['cmd'])

            for k, v in (value.get('env') or {}).items():
                env_vars.append(
                    UnixShellEnvironmentVariable(k, v)
                )

        if not value:
            raise ScriptEmptyError(value)

        return cls(
            value[0],
            args=value[1:],
            env_vars=env_vars,
        )

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
        return " ".join(itertools.chain(
            [_quote_if_contains(self.command, r'[\s^()]')],
            (_quote_if_contains(arg, r'[\s^]') for arg in self.args),
        ))
