# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import codecs
import io
import os
import re
import shutil
import sys
from subprocess import Popen
import tempfile
import warnings
from collections import OrderedDict, namedtuple
from contextlib import contextmanager

from .compat import StringIO, PY2, WIN, text_type

__posix_variable = re.compile(r'\$\{[^\}]*\}')

_binding = re.compile(
    r"""
        (
            \s*                     # leading whitespace
            (?:export{0}+)?         # export

            ( '[^']+'               # single-quoted key
            | [^=\#\s]+             # or unquoted key
            )?

            (?:
                (?:{0}*={0}*)       # equal sign

                ( '(?:\\'|[^'])*'   # single-quoted value
                | "(?:\\"|[^"])*"   # or double-quoted value
                | [^\#\r\n]*        # or unquoted value
                )
            )?

            \s*                     # trailing whitespace
            (?:\#[^\r\n]*)?         # comment
            (?:\r|\n|\r\n)?         # newline
        )
    """.format(r'[^\S\r\n]'),
    re.MULTILINE | re.VERBOSE,
)

_escape_sequence = re.compile(r"\\[\\'\"abfnrtv]")


Binding = namedtuple('Binding', 'key value original')


def decode_escapes(string):
    def decode_match(match):
        return codecs.decode(match.group(0), 'unicode-escape')

    return _escape_sequence.sub(decode_match, string)


def is_surrounded_by(string, char):
    return (
        len(string) > 1
        and string[0] == string[-1] == char
    )


def parse_binding(string, position):
    match = _binding.match(string, position)
    (matched, key, value) = match.groups()
    if key is None or value is None:
        key = None
        value = None
    else:
        value_quoted = is_surrounded_by(value, "'") or is_surrounded_by(value, '"')
        if value_quoted:
            value = decode_escapes(value[1:-1])
        else:
            value = value.strip()
    return (Binding(key=key, value=value, original=matched), match.end())


def parse_stream(stream):
    string = stream.read()
    position = 0
    length = len(string)
    while position < length:
        (binding, position) = parse_binding(string, position)
        yield binding


class DotEnv():

    def __init__(self, dotenv_path, verbose=False):
        self.dotenv_path = dotenv_path
        self._dict = None
        self.verbose = verbose

    @contextmanager
    def _get_stream(self):
        if isinstance(self.dotenv_path, StringIO):
            yield self.dotenv_path
        elif os.path.isfile(self.dotenv_path):
            with io.open(self.dotenv_path) as stream:
                yield stream
        else:
            if self.verbose:
                warnings.warn("File doesn't exist {}".format(self.dotenv_path))
            yield StringIO('')

    def dict(self):
        """Return dotenv as dict"""
        if self._dict:
            return self._dict

        values = OrderedDict(self.parse())
        self._dict = resolve_nested_variables(values)
        return self._dict

    def parse(self):
        with self._get_stream() as stream:
            for mapping in parse_stream(stream):
                if mapping.key is not None and mapping.value is not None:
                    yield mapping.key, mapping.value

    def set_as_environment_variables(self, override=False):
        """
        Load the current dotenv as system environemt variable.
        """
        for k, v in self.dict().items():
            if k in os.environ and not override:
                continue
            # With Python2 on Windows, force environment variables to str to avoid
            # "TypeError: environment can only contain strings" in Python's subprocess.py.
            if PY2 and WIN:
                if isinstance(k, text_type) or isinstance(v, text_type):
                    k = k.encode('ascii')
                    v = v.encode('ascii')
            os.environ[k] = v

        return True

    def get(self, key):
        """
        """
        data = self.dict()

        if key in data:
            return data[key]

        if self.verbose:
            warnings.warn("key %s not found in %s." % (key, self.dotenv_path))


def get_key(dotenv_path, key_to_get):
    """
    Gets the value of a given key from the given .env

    If the .env path given doesn't exist, fails
    """
    return DotEnv(dotenv_path, verbose=True).get(key_to_get)


@contextmanager
def rewrite(path):
    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as dest:
            with io.open(path) as source:
                yield (source, dest)
    except BaseException:
        if os.path.isfile(dest.name):
            os.unlink(dest.name)
        raise
    else:
        shutil.move(dest.name, path)


def set_key(dotenv_path, key_to_set, value_to_set, quote_mode="always"):
    """
    Adds or Updates a key/value to the given .env

    If the .env path given doesn't exist, fails instead of risking creating
    an orphan .env somewhere in the filesystem
    """
    value_to_set = value_to_set.strip("'").strip('"')
    if not os.path.exists(dotenv_path):
        warnings.warn("can't write to %s - it doesn't exist." % dotenv_path)
        return None, key_to_set, value_to_set

    if " " in value_to_set:
        quote_mode = "always"

    line_template = '{}="{}"\n' if quote_mode == "always" else '{}={}\n'
    line_out = line_template.format(key_to_set, value_to_set)

    with rewrite(dotenv_path) as (source, dest):
        replaced = False
        for mapping in parse_stream(source):
            if mapping.key == key_to_set:
                dest.write(line_out)
                replaced = True
            else:
                dest.write(mapping.original)
        if not replaced:
            dest.write(line_out)

    return True, key_to_set, value_to_set


def unset_key(dotenv_path, key_to_unset, quote_mode="always"):
    """
    Removes a given key from the given .env

    If the .env path given doesn't exist, fails
    If the given key doesn't exist in the .env, fails
    """
    if not os.path.exists(dotenv_path):
        warnings.warn("can't delete from %s - it doesn't exist." % dotenv_path)
        return None, key_to_unset

    removed = False
    with rewrite(dotenv_path) as (source, dest):
        for mapping in parse_stream(source):
            if mapping.key == key_to_unset:
                removed = True
            else:
                dest.write(mapping.original)

    if not removed:
        warnings.warn("key %s not removed from %s - key doesn't exist." % (key_to_unset, dotenv_path))
        return None, key_to_unset

    return removed, key_to_unset


def resolve_nested_variables(values):
    def _replacement(name):
        """
        get appropriate value for a variable name.
        first search in environ, if not found,
        then look into the dotenv variables
        """
        ret = os.getenv(name, new_values.get(name, ""))
        return ret

    def _re_sub_callback(match_object):
        """
        From a match object gets the variable name and returns
        the correct replacement
        """
        return _replacement(match_object.group()[2:-1])

    new_values = {}

    for k, v in values.items():
        new_values[k] = __posix_variable.sub(_re_sub_callback, v)

    return new_values


def _walk_to_root(path):
    """
    Yield directories starting from the given directory up to the root
    """
    if not os.path.exists(path):
        raise IOError('Starting path not found')

    if os.path.isfile(path):
        path = os.path.dirname(path)

    last_dir = None
    current_dir = os.path.abspath(path)
    while last_dir != current_dir:
        yield current_dir
        parent_dir = os.path.abspath(os.path.join(current_dir, os.path.pardir))
        last_dir, current_dir = current_dir, parent_dir


def find_dotenv(filename='.env', raise_error_if_not_found=False, usecwd=False):
    """
    Search in increasingly higher folders for the given file

    Returns path to the file if found, or an empty string otherwise
    """
    if usecwd or '__file__' not in globals():
        # should work without __file__, e.g. in REPL or IPython notebook
        path = os.getcwd()
    else:
        # will work for .py files
        frame = sys._getframe()
        # find first frame that is outside of this file
        while frame.f_code.co_filename == __file__:
            frame = frame.f_back
        frame_filename = frame.f_code.co_filename
        path = os.path.dirname(os.path.abspath(frame_filename))

    for dirname in _walk_to_root(path):
        check_path = os.path.join(dirname, filename)
        if os.path.isfile(check_path):
            return check_path

    if raise_error_if_not_found:
        raise IOError('File not found')

    return ''


def load_dotenv(dotenv_path=None, stream=None, verbose=False, override=False):
    f = dotenv_path or stream or find_dotenv()
    return DotEnv(f, verbose=verbose).set_as_environment_variables(override=override)


def dotenv_values(dotenv_path=None, stream=None, verbose=False):
    f = dotenv_path or stream or find_dotenv()
    return DotEnv(f, verbose=verbose).dict()


def run_command(command, env):
    """Run command in sub process.

    Runs the command in a sub process with the variables from `env`
    added in the current environment variables.

    Parameters
    ----------
    command: List[str]
        The command and it's parameters
    env: Dict
        The additional environment variables

    Returns
    -------
    int
        The return code of the command

    """
    # copy the current environment variables and add the vales from
    # `env`
    cmd_env = os.environ.copy()
    cmd_env.update(env)

    p = Popen(command,
              universal_newlines=True,
              bufsize=0,
              shell=False,
              env=cmd_env)
    _, _ = p.communicate()

    return p.returncode
