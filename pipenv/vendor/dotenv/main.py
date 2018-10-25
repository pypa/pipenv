# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import codecs
import fileinput
import io
import os
import re
import sys
from subprocess import Popen, PIPE, STDOUT
import warnings
from collections import OrderedDict

from .compat import StringIO

__escape_decoder = codecs.getdecoder('unicode_escape')
__posix_variable = re.compile('\$\{[^\}]*\}')


def decode_escaped(escaped):
    return __escape_decoder(escaped)[0]


def parse_line(line):
    line = line.strip()

    # Ignore lines with `#` or which doesn't have `=` in it.
    if not line or line.startswith('#') or '=' not in line:
        return None, None

    k, v = line.split('=', 1)

    if k.startswith('export '):
        (_, _, k) = k.partition('export ')

    # Remove any leading and trailing spaces in key, value
    k, v = k.strip(), v.strip()

    if v:
        v = v.encode('unicode-escape').decode('ascii')
        quoted = v[0] == v[-1] in ['"', "'"]
        if quoted:
            v = decode_escaped(v[1:-1])

    return k, v


class DotEnv():

    def __init__(self, dotenv_path, verbose=False):
        self.dotenv_path = dotenv_path
        self._dict = None
        self.verbose = verbose

    def _get_stream(self):
        self._is_file = False
        if isinstance(self.dotenv_path, StringIO):
            return self.dotenv_path

        if os.path.exists(self.dotenv_path):
            self._is_file = True
            return io.open(self.dotenv_path)

        if self.verbose:
            warnings.warn("File doesn't exist {}".format(self.dotenv_path))

        return StringIO('')

    def dict(self):
        """Return dotenv as dict"""
        if self._dict:
            return self._dict

        values = OrderedDict(self.parse())
        self._dict = resolve_nested_variables(values)
        return self._dict

    def parse(self):
        f = self._get_stream()

        for line in f:
            key, value = parse_line(line)
            if not key:
                continue

            yield key, value

        if self._is_file:
            f.close()

    def set_as_environment_variables(self, override=False):
        """
        Load the current dotenv as system environemt variable.
        """
        for k, v in self.dict().items():
            if k in os.environ and not override:
                continue
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

    line_template = '{}="{}"' if quote_mode == "always" else '{}={}'
    line_out = line_template.format(key_to_set, value_to_set)

    replaced = False
    for line in fileinput.input(dotenv_path, inplace=True):
        k, v = parse_line(line)
        if k == key_to_set:
            replaced = True
            line = line_out
        print(line, end='')

    if not replaced:
        with io.open(dotenv_path, "a") as f:
            f.write("{}\n".format(line_out))

    return True, key_to_set, value_to_set


def unset_key(dotenv_path, key_to_unset, quote_mode="always"):
    """
    Removes a given key from the given .env

    If the .env path given doesn't exist, fails
    If the given key doesn't exist in the .env, fails
    """
    removed = False

    if not os.path.exists(dotenv_path):
        warnings.warn("can't delete from %s - it doesn't exist." % dotenv_path)
        return None, key_to_unset

    for line in fileinput.input(dotenv_path, inplace=True):
        k, v = parse_line(line)
        if k == key_to_unset:
            removed = True
            line = ''
        print(line, end='')

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
        ret = os.getenv(name, values.get(name, ""))
        return ret

    def _re_sub_callback(match_object):
        """
        From a match object gets the variable name and returns
        the correct replacement
        """
        return _replacement(match_object.group()[2:-1])

    for k, v in values.items():
        values[k] = __posix_variable.sub(_re_sub_callback, v)

    return values


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
        if os.path.exists(check_path):
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
              stdin=PIPE,
              stdout=PIPE,
              stderr=STDOUT,
              universal_newlines=True,
              bufsize=0,
              shell=False,
              env=cmd_env)
    try:
        out, _ = p.communicate()
        print(out)
    except Exception:
        warnings.warn('An error occured, running the command:')
        out, _ = p.communicate()
        warnings.warn(out)

    return p.returncode
