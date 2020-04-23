# coding: utf-8

from __future__ import division

import io
import sys
import posixpath
import zipfile
import functools
import itertools

import more_itertools

__metaclass__ = type


def _parents(path):
    """
    Given a path with elements separated by
    posixpath.sep, generate all parents of that path.

    >>> list(_parents('b/d'))
    ['b']
    >>> list(_parents('/b/d/'))
    ['/b']
    >>> list(_parents('b/d/f/'))
    ['b/d', 'b']
    >>> list(_parents('b'))
    []
    >>> list(_parents(''))
    []
    """
    return itertools.islice(_ancestry(path), 1, None)


def _ancestry(path):
    """
    Given a path with elements separated by
    posixpath.sep, generate all elements of that path

    >>> list(_ancestry('b/d'))
    ['b/d', 'b']
    >>> list(_ancestry('/b/d/'))
    ['/b/d', '/b']
    >>> list(_ancestry('b/d/f/'))
    ['b/d/f', 'b/d', 'b']
    >>> list(_ancestry('b'))
    ['b']
    >>> list(_ancestry(''))
    []
    """
    path = path.rstrip(posixpath.sep)
    while path and path != posixpath.sep:
        yield path
        path, tail = posixpath.split(path)


class Path:
    """
    A pathlib-compatible interface for zip files.

    Consider a zip file with this structure::

        .
        ├── a.txt
        └── b
            ├── c.txt
            └── d
                └── e.txt

    >>> data = io.BytesIO()
    >>> zf = zipfile.ZipFile(data, 'w')
    >>> zf.writestr('a.txt', 'content of a')
    >>> zf.writestr('b/c.txt', 'content of c')
    >>> zf.writestr('b/d/e.txt', 'content of e')
    >>> zf.filename = 'abcde.zip'

    Path accepts the zipfile object itself or a filename

    >>> root = Path(zf)

    From there, several path operations are available.

    Directory iteration (including the zip file itself):

    >>> a, b = root.iterdir()
    >>> a
    Path('abcde.zip', 'a.txt')
    >>> b
    Path('abcde.zip', 'b/')

    name property:

    >>> b.name
    'b'

    join with divide operator:

    >>> c = b / 'c.txt'
    >>> c
    Path('abcde.zip', 'b/c.txt')
    >>> c.name
    'c.txt'

    Read text:

    >>> c.read_text()
    'content of c'

    existence:

    >>> c.exists()
    True
    >>> (b / 'missing.txt').exists()
    False

    Coercion to string:

    >>> str(c)
    'abcde.zip/b/c.txt'
    """

    __repr = "{self.__class__.__name__}({self.root.filename!r}, {self.at!r})"

    def __init__(self, root, at=""):
        self.root = (
            root
            if isinstance(root, zipfile.ZipFile)
            else zipfile.ZipFile(self._pathlib_compat(root))
        )
        self.at = at

    @staticmethod
    def _pathlib_compat(path):
        """
        For path-like objects, convert to a filename for compatibility
        on Python 3.6.1 and earlier.
        """
        try:
            return path.__fspath__()
        except AttributeError:
            return str(path)

    @property
    def open(self):
        return functools.partial(self.root.open, self.at)

    @property
    def name(self):
        return posixpath.basename(self.at.rstrip("/"))

    def read_text(self, *args, **kwargs):
        with self.open() as strm:
            return io.TextIOWrapper(strm, *args, **kwargs).read()

    def read_bytes(self):
        with self.open() as strm:
            return strm.read()

    def _is_child(self, path):
        return posixpath.dirname(path.at.rstrip("/")) == self.at.rstrip("/")

    def _next(self, at):
        return Path(self.root, at)

    def is_dir(self):
        return not self.at or self.at.endswith("/")

    def is_file(self):
        return not self.is_dir()

    def exists(self):
        return self.at in self._names()

    def iterdir(self):
        if not self.is_dir():
            raise ValueError("Can't listdir a file")
        subs = map(self._next, self._names())
        return filter(self._is_child, subs)

    def __str__(self):
        return posixpath.join(self.root.filename, self.at)

    def __repr__(self):
        return self.__repr.format(self=self)

    def joinpath(self, add):
        add = self._pathlib_compat(add)
        next = posixpath.join(self.at, add)
        next_dir = posixpath.join(self.at, add, "")
        names = self._names()
        return self._next(next_dir if next not in names and next_dir in names else next)

    __truediv__ = joinpath

    @staticmethod
    def _implied_dirs(names):
        return more_itertools.unique_everseen(
            parent + "/"
            for name in names
            for parent in _parents(name)
            if parent + "/" not in names
        )

    @classmethod
    def _add_implied_dirs(cls, names):
        return names + list(cls._implied_dirs(names))

    @property
    def parent(self):
        parent_at = posixpath.dirname(self.at.rstrip('/'))
        if parent_at:
            parent_at += '/'
        return self._next(parent_at)

    def _names(self):
        return self._add_implied_dirs(self.root.namelist())

    if sys.version_info < (3,):
        __div__ = __truediv__
