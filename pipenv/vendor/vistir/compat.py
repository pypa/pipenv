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
    "samefile",
    "Mapping",
    "Hashable",
    "MutableMapping",
    "Container",
    "Iterator",
    "KeysView",
    "ItemsView",
    "MappingView",
    "Iterable",
    "Set",
    "Sequence",
    "Sized",
    "ValuesView",
    "MutableSet",
    "MutableSequence",
    "Callable",
    "fs_encode",
    "fs_decode",
    "_fs_encode_errors",
    "_fs_decode_errors",
]

if sys.version_info >= (3, 5):  # pragma: no cover
    from pathlib import Path
else:  # pragma: no cover
    from pipenv.vendor.pathlib2 import Path

if sys.version_info >= (3, 4):  # pragma: no cover
    # Only Python 3.4+ is supported
    from functools import lru_cache, partialmethod
    from tempfile import NamedTemporaryFile
    from shutil import get_terminal_size
    from weakref import finalize
    from collections.abc import (
        Mapping,
        Hashable,
        MutableMapping,
        Container,
        Iterator,
        KeysView,
        ItemsView,
        MappingView,
        Iterable,
        Set,
        Sequence,
        Sized,
        ValuesView,
        MutableSet,
        MutableSequence,
        Callable,
    )
    from os.path import samefile

else:  # pragma: no cover
    # Only Python 2.7 is supported
    from pipenv.vendor.backports.functools_lru_cache import lru_cache
    from pipenv.vendor.backports.shutil_get_terminal_size import get_terminal_size
    from .backports.functools import partialmethod  # type: ignore
    from .backports.surrogateescape import register_surrogateescape
    from collections import (
        Mapping,
        Hashable,
        MutableMapping,
        Container,
        Iterator,
        KeysView,
        ItemsView,
        MappingView,
        Iterable,
        Set,
        Sequence,
        Sized,
        ValuesView,
        MutableSet,
        MutableSequence,
        Callable,
    )

    register_surrogateescape()
    NamedTemporaryFile = _NamedTemporaryFile
    from pipenv.vendor.backports.weakref import finalize  # type: ignore

    try:
        from os.path import samefile
    except ImportError:

        def samestat(s1, s2):
            """Test whether two stat buffers reference the same file."""
            return s1.st_ino == s2.st_ino and s1.st_dev == s2.st_dev

        def samefile(f1, f2):
            """Test whether two pathnames reference the same actual file or
            directory This is determined by the device number and i-node number
            and raises an exception if an os.stat() call on either pathname
            fails."""
            s1 = os.stat(f1)
            s2 = os.stat(f2)
            return samestat(s1, s2)


try:
    # Introduced Python 3.5
    from json import JSONDecodeError
except ImportError:  # pragma: no cover
    JSONDecodeError = ValueError  # type: ignore

if six.PY2:  # pragma: no cover

    from io import BytesIO as StringIO

    class ResourceWarning(Warning):
        pass

    class FileNotFoundError(IOError):
        """No such file or directory."""

        def __init__(self, *args, **kwargs):
            self.errno = errno.ENOENT
            super(FileNotFoundError, self).__init__(*args, **kwargs)

    class PermissionError(OSError):
        def __init__(self, *args, **kwargs):
            self.errno = errno.EACCES
            super(PermissionError, self).__init__(*args, **kwargs)

    class TimeoutError(OSError):
        """Timeout expired."""

        def __init__(self, *args, **kwargs):
            self.errno = errno.ETIMEDOUT
            super(TimeoutError, self).__init__(*args, **kwargs)

    class IsADirectoryError(OSError):
        """The command does not work on directories."""

        def __init__(self, *args, **kwargs):
            self.errno = errno.EISDIR
            super(IsADirectoryError, self).__init__(*args, **kwargs)

    class FileExistsError(OSError):
        def __init__(self, *args, **kwargs):
            self.errno = errno.EEXIST
            super(FileExistsError, self).__init__(*args, **kwargs)


else:  # pragma: no cover
    from builtins import (
        ResourceWarning,
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        FileExistsError,
        TimeoutError,
    )
    from io import StringIO


if not sys.warnoptions:
    warnings.simplefilter("default", ResourceWarning)


def is_type_checking():
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


IS_TYPE_CHECKING = os.environ.get("MYPY_RUNNING", is_type_checking())


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


def is_bytes(string):
    """Check if a string is a bytes instance.

    :param Union[str, bytes] string: A string that may be string or bytes like
    :return: Whether the provided string is a bytes type or not
    :rtype: bool
    """
    if six.PY3 and isinstance(string, (bytes, memoryview, bytearray)):  # noqa
        return True
    elif six.PY2 and isinstance(string, (buffer, bytearray)):  # noqa
        return True
    return False


def fs_str(string):
    """Encodes a string into the proper filesystem encoding.

    Borrowed from pip-tools
    """

    if isinstance(string, str):
        return string
    assert not isinstance(string, bytes)
    return string.encode(_fs_encoding)


def _get_path(path):
    """Fetch the string value from a path-like object.

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


# copied from the os backport which in turn copied this from
# the pyutf8 package --
# URL: https://github.com/etrepum/pyutf8/blob/master/pyutf8/ref.py
#
def _invalid_utf8_indexes(bytes):
    skips = []
    i = 0
    len_bytes = len(bytes)
    while i < len_bytes:
        c1 = bytes[i]
        if c1 < 0x80:
            # U+0000 - U+007F - 7 bits
            i += 1
            continue
        try:
            c2 = bytes[i + 1]
            if (c1 & 0xE0 == 0xC0) and (c2 & 0xC0 == 0x80):
                # U+0080 - U+07FF - 11 bits
                c = ((c1 & 0x1F) << 6) | (c2 & 0x3F)
                if c < 0x80:  # pragma: no cover
                    # Overlong encoding
                    skips.extend([i, i + 1])  # pragma: no cover
                i += 2
                continue
            c3 = bytes[i + 2]
            if (c1 & 0xF0 == 0xE0) and (c2 & 0xC0 == 0x80) and (c3 & 0xC0 == 0x80):
                # U+0800 - U+FFFF - 16 bits
                c = ((((c1 & 0x0F) << 6) | (c2 & 0x3F)) << 6) | (c3 & 0x3F)
                if (c < 0x800) or (0xD800 <= c <= 0xDFFF):
                    # Overlong encoding or surrogate.
                    skips.extend([i, i + 1, i + 2])
                i += 3
                continue
            c4 = bytes[i + 3]
            if (
                (c1 & 0xF8 == 0xF0)
                and (c2 & 0xC0 == 0x80)
                and (c3 & 0xC0 == 0x80)
                and (c4 & 0xC0 == 0x80)
            ):
                # U+10000 - U+10FFFF - 21 bits
                c = ((((((c1 & 0x0F) << 6) | (c2 & 0x3F)) << 6) | (c3 & 0x3F)) << 6) | (
                    c4 & 0x3F
                )
                if (c < 0x10000) or (c > 0x10FFFF):  # pragma: no cover
                    # Overlong encoding or invalid code point.
                    skips.extend([i, i + 1, i + 2, i + 3])
                i += 4
                continue
        except IndexError:
            pass
        skips.append(i)
        i += 1
    return skips


# XXX backport: Another helper to support the Python 2 UTF-8 decoding hack.
def _chunks(b, indexes):
    i = 0
    for j in indexes:
        yield b[i:j]
        yield b[j : j + 1]
        i = j + 1
    yield b[i:]


def fs_encode(path):
    """Encode a filesystem path to the proper filesystem encoding.

    :param Union[str, bytes] path: A string-like path
    :returns: A bytes-encoded filesystem path representation
    """

    path = _get_path(path)
    if path is None:
        raise TypeError("expected a valid path to encode")
    if isinstance(path, six.text_type):
        if six.PY2:
            return b"".join(
                (
                    _byte(ord(c) - 0xDC00)
                    if 0xDC00 <= ord(c) <= 0xDCFF
                    else c.encode(_fs_encoding, _fs_encode_errors)
                )
                for c in path
            )
        return path.encode(_fs_encoding, _fs_encode_errors)
    return path


def fs_decode(path):
    """Decode a filesystem path using the proper filesystem encoding.

    :param path: The filesystem path to decode from bytes or string
    :return: The filesystem path, decoded with the determined encoding
    :rtype: Text
    """

    path = _get_path(path)
    if path is None:
        raise TypeError("expected a valid path to decode")
    if isinstance(path, six.binary_type):
        import array

        indexes = _invalid_utf8_indexes(array.array(str("B"), path))
        if six.PY2:
            return "".join(
                chunk.decode(_fs_encoding, _fs_decode_errors)
                for chunk in _chunks(path, indexes)
            )
        if indexes and os.name == "nt":
            return path.decode(_fs_encoding, "surrogateescape")
        return path.decode(_fs_encoding, _fs_decode_errors)
    return path


if sys.version_info[0] < 3:  # pragma: no cover
    _fs_encode_errors = "surrogatepass" if sys.platform == "win32" else "surrogateescape"
    _fs_decode_errors = "surrogateescape"
    _fs_encoding = "utf-8"
else:  # pragma: no cover
    _fs_encoding = "utf-8"
    _fs_decode_errors = "surrogateescape"
    if sys.platform.startswith("win"):
        _fs_error_fn = None
        _fs_encode_errors = "surrogatepass"
    else:
        if sys.version_info >= (3, 3):
            _fs_encoding = sys.getfilesystemencoding()
            if not _fs_encoding:
                _fs_encoding = sys.getdefaultencoding()
        alt_strategy = "surrogateescape"
        _fs_error_fn = getattr(sys, "getfilesystemencodeerrors", None)
        _fs_encode_errors = _fs_error_fn() if _fs_error_fn else alt_strategy
        _fs_decode_errors = _fs_error_fn() if _fs_error_fn else _fs_decode_errors

_byte = chr if sys.version_info < (3,) else lambda i: bytes([i])


def to_native_string(string):
    from .misc import to_text, to_bytes

    if six.PY2:
        return to_bytes(string)
    return to_text(string)
