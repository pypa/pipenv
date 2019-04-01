# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import codecs
import errno
import os
import sys
import warnings
from tempfile import mkdtemp

import six

from .backports.tempfile import NamedTemporaryFile as _NamedTemporaryFile

__all__ = [
    "Path",
    "get_terminal_size",
    "finalize",
    "partialmethod",
    "JSONDecodeError",
    "FileNotFoundError",
    "ResourceWarning",
    "PermissionError",
    "is_type_checking",
    "IS_TYPE_CHECKING",
    "IsADirectoryError",
    "fs_str",
    "lru_cache",
    "TemporaryDirectory",
    "NamedTemporaryFile",
    "to_native_string",
    "Iterable",
    "Mapping",
    "Sequence",
    "Set",
    "ItemsView",
    "fs_encode",
    "fs_decode",
    "_fs_encode_errors",
    "_fs_decode_errors",
]

if sys.version_info >= (3, 5):
    from pathlib import Path
    from functools import lru_cache
else:
    from pipenv.vendor.pathlib2 import Path
    from pipenv.vendor.backports.functools_lru_cache import lru_cache


if sys.version_info < (3, 3):
    from pipenv.vendor.backports.shutil_get_terminal_size import get_terminal_size

    NamedTemporaryFile = _NamedTemporaryFile
else:
    from tempfile import NamedTemporaryFile
    from shutil import get_terminal_size

try:
    from weakref import finalize
except ImportError:
    from pipenv.vendor.backports.weakref import finalize  # type: ignore

try:
    from functools import partialmethod
except Exception:
    from .backports.functools import partialmethod  # type: ignore

try:
    from json import JSONDecodeError
except ImportError:  # Old Pythons.
    JSONDecodeError = ValueError  # type: ignore

if six.PY2:

    from io import BytesIO as StringIO

    class ResourceWarning(Warning):
        pass

    class FileNotFoundError(IOError):
        """No such file or directory"""

        def __init__(self, *args, **kwargs):
            self.errno = errno.ENOENT
            super(FileNotFoundError, self).__init__(*args, **kwargs)

    class PermissionError(OSError):
        def __init__(self, *args, **kwargs):
            self.errno = errno.EACCES
            super(PermissionError, self).__init__(*args, **kwargs)

    class IsADirectoryError(OSError):
        """The command does not work on directories"""

        pass

    class FileExistsError(OSError):
        def __init__(self, *args, **kwargs):
            self.errno = errno.EEXIST
            super(FileExistsError, self).__init__(*args, **kwargs)


else:
    from builtins import (
        ResourceWarning,
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        FileExistsError,
    )
    from io import StringIO

six.add_move(
    six.MovedAttribute("Iterable", "collections", "collections.abc")
)  # type: ignore
six.add_move(
    six.MovedAttribute("Mapping", "collections", "collections.abc")
)  # type: ignore
six.add_move(
    six.MovedAttribute("Sequence", "collections", "collections.abc")
)  # type: ignore
six.add_move(six.MovedAttribute("Set", "collections", "collections.abc"))  # type: ignore
six.add_move(
    six.MovedAttribute("ItemsView", "collections", "collections.abc")
)  # type: ignore

# fmt: off
from six.moves import ItemsView, Iterable, Mapping, Sequence, Set  # type: ignore  # noqa  # isort:skip
# fmt: on


if not sys.warnoptions:
    warnings.simplefilter("default", ResourceWarning)


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


IS_TYPE_CHECKING = is_type_checking()


class TemporaryDirectory(object):

    """
    Create and return a temporary directory.  This has the same
    behavior as mkdtemp but can be used as a context manager.  For
    example:

        with TemporaryDirectory() as tmpdir:
            ...

    Upon exiting the context, the directory and everything contained
    in it are removed.
    """

    def __init__(self, suffix="", prefix=None, dir=None):
        if "RAM_DISK" in os.environ:
            import uuid

            name = uuid.uuid4().hex
            dir_name = os.path.join(os.environ["RAM_DISK"].strip(), name)
            os.mkdir(dir_name)
            self.name = dir_name
        else:
            suffix = suffix if suffix else ""
            if not prefix:
                self.name = mkdtemp(suffix=suffix, dir=dir)
            else:
                self.name = mkdtemp(suffix, prefix, dir)
        self._finalizer = finalize(
            self,
            self._cleanup,
            self.name,
            warn_message="Implicitly cleaning up {!r}".format(self),
        )

    @classmethod
    def _rmtree(cls, name):
        from .path import rmtree

        rmtree(name)

    @classmethod
    def _cleanup(cls, name, warn_message):
        cls._rmtree(name)
        warnings.warn(warn_message, ResourceWarning)

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.name)

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        self.cleanup()

    def cleanup(self):
        if self._finalizer.detach():
            self._rmtree(self.name)


def fs_str(string):
    """Encodes a string into the proper filesystem encoding

    Borrowed from pip-tools
    """

    if isinstance(string, str):
        return string
    assert not isinstance(string, bytes)
    return string.encode(_fs_encoding)


def _get_path(path):
    """
    Fetch the string value from a path-like object

    Returns **None** if there is no string value.
    """

    if isinstance(path, (six.string_types, bytes)):
        return path
    path_type = type(path)
    try:
        path_repr = path_type.__fspath__(path)
    except AttributeError:
        return
    if isinstance(path_repr, (six.string_types, bytes)):
        return path_repr
    return


def fs_encode(path):
    """
    Encode a filesystem path to the proper filesystem encoding

    :param Union[str, bytes] path: A string-like path
    :returns: A bytes-encoded filesystem path representation
    """

    path = _get_path(path)
    if path is None:
        raise TypeError("expected a valid path to encode")
    if isinstance(path, six.text_type):
        path = path.encode(_fs_encoding, _fs_encode_errors)
    return path


def fs_decode(path):
    """
    Decode a filesystem path using the proper filesystem encoding

    :param path: The filesystem path to decode from bytes or string
    :return: [description]
    :rtype: [type]
    """

    path = _get_path(path)
    if path is None:
        raise TypeError("expected a valid path to decode")
    if isinstance(path, six.binary_type):
        path = path.decode(_fs_encoding, _fs_decode_errors)
    return path


if sys.version_info >= (3, 3) and os.name != "nt":
    _fs_encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()
else:
    _fs_encoding = "utf-8"

if six.PY3:
    if os.name == "nt":
        _fs_error_fn = None
        alt_strategy = "surrogatepass"
    else:
        alt_strategy = "surrogateescape"
        _fs_error_fn = getattr(sys, "getfilesystemencodeerrors", None)
    _fs_encode_errors = _fs_error_fn() if _fs_error_fn is not None else alt_strategy
    _fs_decode_errors = _fs_error_fn() if _fs_error_fn is not None else alt_strategy
else:
    _fs_encode_errors = "backslashreplace"
    _fs_decode_errors = "replace"


def to_native_string(string):
    from .misc import to_text, to_bytes

    if six.PY2:
        return to_bytes(string)
    return to_text(string)
