# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import functools
import io
import os
import sys
from tempfile import _bin_openflags, _mkstemp_inner, gettempdir

import six

try:
    from weakref import finalize
except ImportError:
    from pipenv.vendor.backports.weakref import finalize


def fs_encode(path):
    try:
        return os.fsencode(path)
    except AttributeError:
        from ..compat import fs_encode

        return fs_encode(path)


def fs_decode(path):
    try:
        return os.fsdecode(path)
    except AttributeError:
        from ..compat import fs_decode

        return fs_decode(path)


__all__ = ["finalize", "NamedTemporaryFile"]


try:
    from tempfile import _infer_return_type
except ImportError:

    def _infer_return_type(*args):
        _types = set()
        for arg in args:
            if isinstance(type(arg), six.string_types):
                _types.add(str)
            elif isinstance(type(arg), bytes):
                _types.add(bytes)
            elif arg:
                _types.add(type(arg))
        return _types.pop()


def _sanitize_params(prefix, suffix, dir):
    """Common parameter processing for most APIs in this module."""
    output_type = _infer_return_type(prefix, suffix, dir)
    if suffix is None:
        suffix = output_type()
    if prefix is None:
        if output_type is str:
            prefix = "tmp"
        else:
            prefix = os.fsencode("tmp")
    if dir is None:
        if output_type is str:
            dir = gettempdir()
        else:
            dir = fs_encode(gettempdir())
    return prefix, suffix, dir, output_type


class _TemporaryFileCloser:
    """A separate object allowing proper closing of a temporary file's
    underlying file object, without adding a __del__ method to the
    temporary file."""

    file = None  # Set here since __del__ checks it
    close_called = False

    def __init__(self, file, name, delete=True):
        self.file = file
        self.name = name
        self.delete = delete

    # NT provides delete-on-close as a primitive, so we don't need
    # the wrapper to do anything special.  We still use it so that
    # file.name is useful (i.e. not "(fdopen)") with NamedTemporaryFile.
    if os.name != "nt":

        # Cache the unlinker so we don't get spurious errors at
        # shutdown when the module-level "os" is None'd out.  Note
        # that this must be referenced as self.unlink, because the
        # name TemporaryFileWrapper may also get None'd out before
        # __del__ is called.

        def close(self, unlink=os.unlink):
            if not self.close_called and self.file is not None:
                self.close_called = True
                try:
                    self.file.close()
                finally:
                    if self.delete:
                        unlink(self.name)

        # Need to ensure the file is deleted on __del__

        def __del__(self):
            self.close()

    else:

        def close(self):
            if not self.close_called:
                self.close_called = True
                self.file.close()


class _TemporaryFileWrapper:
    """Temporary file wrapper
    This class provides a wrapper around files opened for
    temporary use.  In particular, it seeks to automatically
    remove the file when it is no longer needed.
    """

    def __init__(self, file, name, delete=True):
        self.file = file
        self.name = name
        self.delete = delete
        self._closer = _TemporaryFileCloser(file, name, delete)

    def __getattr__(self, name):
        # Attribute lookups are delegated to the underlying file
        # and cached for non-numeric results
        # (i.e. methods are cached, closed and friends are not)
        file = self.__dict__["file"]
        a = getattr(file, name)
        if hasattr(a, "__call__"):
            func = a

            @functools.wraps(func)
            def func_wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            # Avoid closing the file as long as the wrapper is alive,
            # see issue #18879.
            func_wrapper._closer = self._closer
            a = func_wrapper
        if not isinstance(a, int):
            setattr(self, name, a)
        return a

    # The underlying __enter__ method returns the wrong object
    # (self.file) so override it to return the wrapper

    def __enter__(self):
        self.file.__enter__()
        return self

    # Need to trap __exit__ as well to ensure the file gets
    # deleted when used in a with statement

    def __exit__(self, exc, value, tb):
        result = self.file.__exit__(exc, value, tb)
        self.close()
        return result

    def close(self):
        """
        Close the temporary file, possibly deleting it.
        """
        self._closer.close()

    # iter() doesn't use __getattr__ to find the __iter__ method

    def __iter__(self):
        # Don't return iter(self.file), but yield from it to avoid closing
        # file as long as it's being used as iterator (see issue #23700).  We
        # can't use 'yield from' here because iter(file) returns the file
        # object itself, which has a close method, and thus the file would get
        # closed when the generator is finalized, due to PEP380 semantics.
        for line in self.file:
            yield line


def NamedTemporaryFile(
    mode="w+b",
    buffering=-1,
    encoding=None,
    newline=None,
    suffix=None,
    prefix=None,
    dir=None,
    delete=True,
    wrapper_class_override=None,
):
    """Create and return a temporary file.
    Arguments:
    'prefix', 'suffix', 'dir' -- as for mkstemp.
    'mode' -- the mode argument to io.open (default "w+b").
    'buffering' -- the buffer size argument to io.open (default -1).
    'encoding' -- the encoding argument to io.open (default None)
    'newline' -- the newline argument to io.open (default None)
    'delete' -- whether the file is deleted on close (default True).
    The file is created as mkstemp() would do it.
    Returns an object with a file-like interface; the name of the file
    is accessible as its 'name' attribute.  The file will be automatically
    deleted when it is closed unless the 'delete' argument is set to False.
    """
    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)
    flags = _bin_openflags
    # Setting O_TEMPORARY in the flags causes the OS to delete
    # the file when it is closed.  This is only supported by Windows.
    if not wrapper_class_override:
        wrapper_class_override = _TemporaryFileWrapper
    if os.name == "nt" and delete:
        flags |= os.O_TEMPORARY
    if sys.version_info < (3, 5):
        (fd, name) = _mkstemp_inner(dir, prefix, suffix, flags)
    else:
        (fd, name) = _mkstemp_inner(dir, prefix, suffix, flags, output_type)
    try:
        file = io.open(fd, mode, buffering=buffering, newline=newline, encoding=encoding)
        if wrapper_class_override is not None:
            return type(str("_TempFileWrapper"), (wrapper_class_override, object), {})(
                file, name, delete
            )
        else:
            return _TemporaryFileWrapper(file, name, delete)

    except BaseException:
        os.unlink(name)
        os.close(fd)
        raise
