# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import io
import os
import re
import shutil
import sys
import tempfile
import warnings
from collections import OrderedDict
from contextlib import contextmanager

from .compat import StringIO, PY2, to_env, IS_TYPE_CHECKING
from .parser import parse_stream

if IS_TYPE_CHECKING:
    from typing import (
        Dict, Iterator, Match, Optional, Pattern, Union, Text, IO, Tuple
    )
    if sys.version_info >= (3, 6):
        _PathLike = os.PathLike
    else:
        _PathLike = Text

    if sys.version_info >= (3, 0):
        _StringIO = StringIO
    else:
        _StringIO = StringIO[Text]

__posix_variable = re.compile(r'\$\{[^\}]*\}')  # type: Pattern[Text]


class DotEnv():

    def __init__(self, dotenv_path, verbose=False, encoding=None):
        # type: (Union[Text, _PathLike, _StringIO], bool, Union[None, Text]) -> None
        self.dotenv_path = dotenv_path  # type: Union[Text,_PathLike, _StringIO]
        self._dict = None  # type: Optional[Dict[Text, Text]]
        self.verbose = verbose  # type: bool
        self.encoding = encoding  # type: Union[None, Text]

    @contextmanager
    def _get_stream(self):
        # type: () -> Iterator[IO[Text]]
        if isinstance(self.dotenv_path, StringIO):
            yield self.dotenv_path
        elif os.path.isfile(self.dotenv_path):
            with io.open(self.dotenv_path, encoding=self.encoding) as stream:
                yield stream
        else:
            if self.verbose:
                warnings.warn("File doesn't exist {}".format(self.dotenv_path))  # type: ignore
            yield StringIO('')

    def dict(self):
        # type: () -> Dict[Text, Text]
        """Return dotenv as dict"""
        if self._dict:
            return self._dict

        values = OrderedDict(self.parse())
        self._dict = resolve_nested_variables(values)
        return self._dict

    def parse(self):
        # type: () -> Iterator[Tuple[Text, Text]]
        with self._get_stream() as stream:
            for mapping in parse_stream(stream):
                if mapping.key is not None and mapping.value is not None:
                    yield mapping.key, mapping.value

    def set_as_environment_variables(self, override=False):
        # type: (bool) -> bool
        """
        Load the current dotenv as system environemt variable.
        """
        for k, v in self.dict().items():
            if k in os.environ and not override:
                continue
            os.environ[to_env(k)] = to_env(v)

        return True

    def get(self, key):
        # type: (Text) -> Optional[Text]
        """
        """
        data = self.dict()

        if key in data:
            return data[key]

        if self.verbose:
            warnings.warn("key %s not found in %s." % (key, self.dotenv_path))  # type: ignore

        return None


def get_key(dotenv_path, key_to_get):
    # type: (Union[Text, _PathLike], Text) -> Optional[Text]
    """
    Gets the value of a given key from the given .env

    If the .env path given doesn't exist, fails
    """
    return DotEnv(dotenv_path, verbose=True).get(key_to_get)


@contextmanager
def rewrite(path):
    # type: (_PathLike) -> Iterator[Tuple[IO[Text], IO[Text]]]
    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as dest:
            with io.open(path) as source:
                yield (source, dest)  # type: ignore
    except BaseException:
        if os.path.isfile(dest.name):
            os.unlink(dest.name)
        raise
    else:
        shutil.move(dest.name, path)


def set_key(dotenv_path, key_to_set, value_to_set, quote_mode="always"):
    # type: (_PathLike, Text, Text, Text) -> Tuple[Optional[bool], Text, Text]
    """
    Adds or Updates a key/value to the given .env

    If the .env path given doesn't exist, fails instead of risking creating
    an orphan .env somewhere in the filesystem
    """
    value_to_set = value_to_set.strip("'").strip('"')
    if not os.path.exists(dotenv_path):
        warnings.warn("can't write to %s - it doesn't exist." % dotenv_path)  # type: ignore
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
    # type: (_PathLike, Text, Text) -> Tuple[Optional[bool], Text]
    """
    Removes a given key from the given .env

    If the .env path given doesn't exist, fails
    If the given key doesn't exist in the .env, fails
    """
    if not os.path.exists(dotenv_path):
        warnings.warn("can't delete from %s - it doesn't exist." % dotenv_path)  # type: ignore
        return None, key_to_unset

    removed = False
    with rewrite(dotenv_path) as (source, dest):
        for mapping in parse_stream(source):
            if mapping.key == key_to_unset:
                removed = True
            else:
                dest.write(mapping.original)

    if not removed:
        warnings.warn("key %s not removed from %s - key doesn't exist." % (key_to_unset, dotenv_path))  # type: ignore
        return None, key_to_unset

    return removed, key_to_unset


def resolve_nested_variables(values):
    # type: (Dict[Text, Text]) -> Dict[Text, Text]
    def _replacement(name):
        # type: (Text) -> Text
        """
        get appropriate value for a variable name.
        first search in environ, if not found,
        then look into the dotenv variables
        """
        ret = os.getenv(name, new_values.get(name, ""))
        return ret

    def _re_sub_callback(match_object):
        # type: (Match[Text]) -> Text
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
    # type: (Text) -> Iterator[Text]
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
    # type: (Text, bool, bool) -> Text
    """
    Search in increasingly higher folders for the given file

    Returns path to the file if found, or an empty string otherwise
    """

    def _is_interactive():
        """ Decide whether this is running in a REPL or IPython notebook """
        main = __import__('__main__', None, None, fromlist=['__file__'])
        return not hasattr(main, '__file__')

    if usecwd or _is_interactive():
        # Should work without __file__, e.g. in REPL or IPython notebook.
        path = os.getcwd()
    else:
        # will work for .py files
        frame = sys._getframe()
        # find first frame that is outside of this file
        if PY2 and not __file__.endswith('.py'):
            # in Python2 __file__ extension could be .pyc or .pyo (this doesn't account
            # for edge case of Python compiled for non-standard extension)
            current_file = __file__.rsplit('.', 1)[0] + '.py'
        else:
            current_file = __file__

        while frame.f_code.co_filename == current_file:
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


def load_dotenv(dotenv_path=None, stream=None, verbose=False, override=False, **kwargs):
    # type: (Union[Text, _PathLike, None], Optional[_StringIO], bool, bool, Union[None, Text]) -> bool
    """Parse a .env file and then load all the variables found as environment variables.

    - *dotenv_path*: absolute or relative path to .env file.
    - *stream*: `StringIO` object with .env content.
    - *verbose*: whether to output the warnings related to missing .env file etc. Defaults to `False`.
    - *override*: where to override the system environment variables with the variables in `.env` file.
                  Defaults to `False`.
    """
    f = dotenv_path or stream or find_dotenv()
    return DotEnv(f, verbose=verbose, **kwargs).set_as_environment_variables(override=override)


def dotenv_values(dotenv_path=None, stream=None, verbose=False, **kwargs):
    # type: (Union[Text, _PathLike, None], Optional[_StringIO], bool, Union[None, Text]) -> Dict[Text, Text]
    f = dotenv_path or stream or find_dotenv()
    return DotEnv(f, verbose=verbose, **kwargs).dict()
