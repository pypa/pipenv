# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import os
import sys

import six
import warnings
from tempfile import mkdtemp


__all__ = [
    "Path",
    "get_terminal_size",
    "finalize",
    "partialmethod",
    "JSONDecodeError",
    "ResourceWarning",
    "FileNotFoundError",
    "fs_str",
    "TemporaryDirectory",
    "NamedTemporaryFile",
]

if sys.version_info >= (3, 5):
    from pathlib import Path

else:
    from pathlib2 import Path

if sys.version_info < (3, 3):
    from backports.shutil_get_terminal_size import get_terminal_size
    from .backports.tempfile import NamedTemporaryFile
else:
    from tempfile import NamedTemporaryFile
    from shutil import get_terminal_size

try:
    from weakref import finalize
except ImportError:
    from backports.weakref import finalize

try:
    from functools import partialmethod
except Exception:
    from .backports.functools import partialmethod

try:
    from json import JSONDecodeError
except ImportError:  # Old Pythons.
    JSONDecodeError = ValueError

if six.PY2:

    class ResourceWarning(Warning):
        pass

    class FileNotFoundError(IOError):
        pass

else:
    from builtins import ResourceWarning, FileNotFoundError

    class ResourceWarning(ResourceWarning):
        pass

    class FileNotFoundError(FileNotFoundError):
        pass


class TemporaryDirectory(object):
    """Create and return a temporary directory.  This has the same
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
    def _cleanup(cls, name, warn_message):
        from .path import rmtree
        rmtree(name)
        warnings.warn(warn_message, ResourceWarning)

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.name)

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        self.cleanup()

    def cleanup(self):
        from .path import rmtree
        if self._finalizer.detach():
            rmtree(self.name)


def fs_str(string):
    """Encodes a string into the proper filesystem encoding

    Borrowed from pip-tools
    """
    if isinstance(string, str):
        return string
    assert not isinstance(string, bytes)
    return string.encode(_fs_encoding)


_fs_encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()
