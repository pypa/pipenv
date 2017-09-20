# -*- coding: utf-8 -*-
from __future__ import absolute_import

import codecs
import os
import sys
import warnings
import re
from collections import OrderedDict

__escape_decoder = codecs.getdecoder('unicode_escape')
__posix_variable = re.compile('\$\{[^\}]*\}')


def decode_escaped(escaped):
    return __escape_decoder(escaped)[0]


def load_dotenv(dotenv_path, verbose=False, override=False):
    """
    Read a .env file and load into os.environ.
    """
    if not os.path.exists(dotenv_path):
        if verbose:
            warnings.warn("Not loading %s - it doesn't exist." % dotenv_path)
        return None
    for k, v in dotenv_values(dotenv_path).items():
        if override:
            os.environ[k] = v
        else:
            os.environ.setdefault(k, v)
    return True


def get_key(dotenv_path, key_to_get):
    """
    Gets the value of a given key from the given .env

    If the .env path given doesn't exist, fails
    """
    key_to_get = str(key_to_get)
    if not os.path.exists(dotenv_path):
        warnings.warn("can't read %s - it doesn't exist." % dotenv_path)
        return None
    dotenv_as_dict = dotenv_values(dotenv_path)
    if key_to_get in dotenv_as_dict:
        return dotenv_as_dict[key_to_get]
    else:
        warnings.warn("key %s not found in %s." % (key_to_get, dotenv_path))
        return None


def set_key(dotenv_path, key_to_set, value_to_set, quote_mode="always"):
    """
    Adds or Updates a key/value to the given .env

    If the .env path given doesn't exist, fails instead of risking creating
    an orphan .env somewhere in the filesystem
    """
    key_to_set = str(key_to_set)
    value_to_set = str(value_to_set).strip("'").strip('"')
    if not os.path.exists(dotenv_path):
        warnings.warn("can't write to %s - it doesn't exist." % dotenv_path)
        return None, key_to_set, value_to_set
    dotenv_as_dict = OrderedDict(parse_dotenv(dotenv_path))
    dotenv_as_dict[key_to_set] = value_to_set
    success = flatten_and_write(dotenv_path, dotenv_as_dict, quote_mode)
    return success, key_to_set, value_to_set


def unset_key(dotenv_path, key_to_unset, quote_mode="always"):
    """
    Removes a given key from the given .env

    If the .env path given doesn't exist, fails
    If the given key doesn't exist in the .env, fails
    """
    key_to_unset = str(key_to_unset)
    if not os.path.exists(dotenv_path):
        warnings.warn("can't delete from %s - it doesn't exist." % dotenv_path)
        return None, key_to_unset
    dotenv_as_dict = dotenv_values(dotenv_path)
    if key_to_unset in dotenv_as_dict:
        dotenv_as_dict.pop(key_to_unset, None)
    else:
        warnings.warn("key %s not removed from %s - key doesn't exist." % (key_to_unset, dotenv_path))
        return None, key_to_unset
    success = flatten_and_write(dotenv_path, dotenv_as_dict, quote_mode)
    return success, key_to_unset


def dotenv_values(dotenv_path):
    values = OrderedDict(parse_dotenv(dotenv_path))
    values = resolve_nested_variables(values)
    return values


def parse_dotenv(dotenv_path):
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)

            # Remove any leading and trailing spaces in key, value
            k, v = k.strip(), v.strip().encode('unicode-escape').decode('ascii')

            if len(v) > 0:
                quoted = v[0] == v[len(v) - 1] in ['"', "'"]

                if quoted:
                    v = decode_escaped(v[1:-1])

            yield k, v


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


def flatten_and_write(dotenv_path, dotenv_as_dict, quote_mode="always"):
    with open(dotenv_path, "w") as f:
        for k, v in dotenv_as_dict.items():
            _mode = quote_mode
            if _mode == "auto" and " " in v:
                _mode = "always"
            str_format = '%s="%s"\n' if _mode == "always" else '%s=%s\n'
            f.write(str_format % (k, v))
    return True


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
        frame_filename = sys._getframe().f_back.f_code.co_filename
        path = os.path.dirname(os.path.abspath(frame_filename))

    for dirname in _walk_to_root(path):
        check_path = os.path.join(dirname, filename)
        if os.path.exists(check_path):
            return check_path

    if raise_error_if_not_found:
        raise IOError('File not found')

    return ''
