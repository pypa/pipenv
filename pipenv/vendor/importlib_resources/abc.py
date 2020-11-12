from __future__ import absolute_import

import abc

from ._compat import ABC, FileNotFoundError, runtime_checkable, Protocol

# Use mypy's comment syntax for Python 2 compatibility
try:
    from typing import BinaryIO, Iterable, Text
except ImportError:
    pass


class ResourceReader(ABC):
    """Abstract base class for loaders to provide resource reading support."""

    @abc.abstractmethod
    def open_resource(self, resource):
        # type: (Text) -> BinaryIO
        """Return an opened, file-like object for binary reading.

        The 'resource' argument is expected to represent only a file name.
        If the resource cannot be found, FileNotFoundError is raised.
        """
        # This deliberately raises FileNotFoundError instead of
        # NotImplementedError so that if this method is accidentally called,
        # it'll still do the right thing.
        raise FileNotFoundError

    @abc.abstractmethod
    def resource_path(self, resource):
        # type: (Text) -> Text
        """Return the file system path to the specified resource.

        The 'resource' argument is expected to represent only a file name.
        If the resource does not exist on the file system, raise
        FileNotFoundError.
        """
        # This deliberately raises FileNotFoundError instead of
        # NotImplementedError so that if this method is accidentally called,
        # it'll still do the right thing.
        raise FileNotFoundError

    @abc.abstractmethod
    def is_resource(self, path):
        # type: (Text) -> bool
        """Return True if the named 'path' is a resource.

        Files are resources, directories are not.
        """
        raise FileNotFoundError

    @abc.abstractmethod
    def contents(self):
        # type: () -> Iterable[str]
        """Return an iterable of entries in `package`."""
        raise FileNotFoundError


@runtime_checkable
class Traversable(Protocol):
    """
    An object with a subset of pathlib.Path methods suitable for
    traversing directories and opening files.
    """

    @abc.abstractmethod
    def iterdir(self):
        """
        Yield Traversable objects in self
        """

    @abc.abstractmethod
    def read_bytes(self):
        """
        Read contents of self as bytes
        """

    @abc.abstractmethod
    def read_text(self, encoding=None):
        """
        Read contents of self as bytes
        """

    @abc.abstractmethod
    def is_dir(self):
        """
        Return True if self is a dir
        """

    @abc.abstractmethod
    def is_file(self):
        """
        Return True if self is a file
        """

    @abc.abstractmethod
    def joinpath(self, child):
        """
        Return Traversable child in self
        """

    @abc.abstractmethod
    def __truediv__(self, child):
        """
        Return Traversable child in self
        """

    @abc.abstractmethod
    def open(self, mode='r', *args, **kwargs):
        """
        mode may be 'r' or 'rb' to open as text or binary. Return a handle
        suitable for reading (same as pathlib.Path.open).

        When opening as text, accepts encoding parameters such as those
        accepted by io.TextIOWrapper.
        """

    @abc.abstractproperty
    def name(self):
        # type: () -> str
        """
        The base name of this object without any parent references.
        """


class TraversableResources(ResourceReader):
    @abc.abstractmethod
    def files(self):
        """Return a Traversable object for the loaded package."""

    def open_resource(self, resource):
        return self.files().joinpath(resource).open('rb')

    def resource_path(self, resource):
        raise FileNotFoundError(resource)

    def is_resource(self, path):
        return self.files().joinpath(path).is_file()

    def contents(self):
        return (item.name for item in self.files().iterdir())
