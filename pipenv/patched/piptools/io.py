# -*- coding: utf-8 -*-
#
# NOTE:
# The classes in this module are vendored from boltons:
# https://github.com/mahmoud/boltons/blob/master/boltons/fileutils.py
#
"""Virtually every Python programmer has used Python for wrangling
disk contents, and ``fileutils`` collects solutions to some of the
most commonly-found gaps in the standard library.
"""

from __future__ import print_function

import os
import re
import sys
import stat
import errno
import fnmatch
from shutil import copy2, copystat, Error


__all__ = ['mkdir_p', 'atomic_save', 'AtomicSaver', 'FilePerms',
           'iter_find_files', 'copytree']


FULL_PERMS = 511  # 0777 that both Python 2 and 3 can digest
RW_PERMS = 438
_SINGLE_FULL_PERM = 7  # or 07 in Python 2
try:
    basestring
except NameError:
    unicode = str  # Python 3 compat
    basestring = (str, bytes)


def mkdir_p(path):
    """Creates a directory and any parent directories that may need to
    be created along the way, without raising errors for any existing
    directories. This function mimics the behavior of the ``mkdir -p``
    command available in Linux/BSD environments, but also works on
    Windows.
    """
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            return
        raise
    return


class FilePerms(object):
    """The :class:`FilePerms` type is used to represent standard POSIX
    filesystem permissions:

      * Read
      * Write
      * Execute

    Across three classes of user:

      * Owning (u)ser
      * Owner's (g)roup
      * Any (o)ther user

    This class assists with computing new permissions, as well as
    working with numeric octal ``777``-style and ``rwx``-style
    permissions. Currently it only considers the bottom 9 permission
    bits; it does not support sticky bits or more advanced permission
    systems.

    Args:
        user (str): A string in the 'rwx' format, omitting characters
            for which owning user's permissions are not provided.
        group (str): A string in the 'rwx' format, omitting characters
            for which owning group permissions are not provided.
        other (str): A string in the 'rwx' format, omitting characters
            for which owning other/world permissions are not provided.

    There are many ways to use :class:`FilePerms`:

    >>> FilePerms(user='rwx', group='xrw', other='wxr')  # note character order
    FilePerms(user='rwx', group='rwx', other='rwx')
    >>> int(FilePerms('r', 'r', ''))
    288
    >>> oct(288)[-3:]  # XXX Py3k
    '440'

    See also the :meth:`FilePerms.from_int` and
    :meth:`FilePerms.from_path` classmethods for useful alternative
    ways to construct :class:`FilePerms` objects.
    """
    # TODO: consider more than the lower 9 bits
    class _FilePermProperty(object):
        _perm_chars = 'rwx'
        _perm_set = frozenset('rwx')
        _perm_val = {'r': 4, 'w': 2, 'x': 1}  # for sorting

        def __init__(self, attribute, offset):
            self.attribute = attribute
            self.offset = offset

        def __get__(self, fp_obj, type_=None):
            if fp_obj is None:
                return self
            return getattr(fp_obj, self.attribute)

        def __set__(self, fp_obj, value):
            cur = getattr(fp_obj, self.attribute)
            if cur == value:
                return
            try:
                invalid_chars = set(str(value)) - self._perm_set
            except TypeError:
                raise TypeError('expected string, not %r' % value)
            if invalid_chars:
                raise ValueError('got invalid chars %r in permission'
                                 ' specification %r, expected empty string'
                                 ' or one or more of %r'
                                 % (invalid_chars, value, self._perm_chars))

            sort_key = (lambda c: self._perm_val[c])
            new_value = ''.join(sorted(set(value),
                                       key=sort_key, reverse=True))
            setattr(fp_obj, self.attribute, new_value)
            self._update_integer(fp_obj, new_value)

        def _update_integer(self, fp_obj, value):
            mode = 0
            key = 'xwr'
            for symbol in value:
                bit = 2 ** key.index(symbol)
                mode |= (bit << (self.offset * 3))
            fp_obj._integer |= mode

    def __init__(self, user='', group='', other=''):
        self._user, self._group, self._other = '', '', ''
        self._integer = 0
        self.user = user
        self.group = group
        self.other = other

    @classmethod
    def from_int(cls, i):
        """Create a :class:`FilePerms` object from an integer.

        >>> FilePerms.from_int(0o644)  # note the leading zero-oh for octal
        FilePerms(user='rw', group='r', other='r')
        """
        i &= FULL_PERMS
        key = ('', 'x', 'w', 'xw', 'r', 'rx', 'rw', 'rwx')
        parts = []
        while i:
            parts.append(key[i & _SINGLE_FULL_PERM])
            i >>= 3
        parts.reverse()
        return cls(*parts)

    @classmethod
    def from_path(cls, path):
        """Make a new :class:`FilePerms` object based on the permissions
        assigned to the file or directory at *path*.

        Args:
            path (str): Filesystem path of the target file.

        >>> from os.path import expanduser
        >>> 'r' in FilePerms.from_path(expanduser('~')).user  # probably
        True
        """
        stat_res = os.stat(path)
        return cls.from_int(stat.S_IMODE(stat_res.st_mode))

    def __int__(self):
        return self._integer

    # Sphinx tip: attribute docstrings come after the attribute
    user = _FilePermProperty('_user', 2)
    "Stores the ``rwx``-formatted *user* permission."
    group = _FilePermProperty('_group', 1)
    "Stores the ``rwx``-formatted *group* permission."
    other = _FilePermProperty('_other', 0)
    "Stores the ``rwx``-formatted *other* permission."

    def __repr__(self):
        cn = self.__class__.__name__
        return ('%s(user=%r, group=%r, other=%r)'
                % (cn, self.user, self.group, self.other))

####


_TEXT_OPENFLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL
if hasattr(os, 'O_NOINHERIT'):
    _TEXT_OPENFLAGS |= os.O_NOINHERIT
if hasattr(os, 'O_NOFOLLOW'):
    _TEXT_OPENFLAGS |= os.O_NOFOLLOW
_BIN_OPENFLAGS = _TEXT_OPENFLAGS
if hasattr(os, 'O_BINARY'):
    _BIN_OPENFLAGS |= os.O_BINARY


try:
    import fcntl as fcntl
except ImportError:
    def set_cloexec(fd):
        "Dummy set_cloexec for platforms without fcntl support"
        pass
else:
    def set_cloexec(fd):
        """Does a best-effort :func:`fcntl.fcntl` call to set a fd to be
        automatically closed by any future child processes.

        Implementation from the :mod:`tempfile` module.
        """
        try:
            flags = fcntl.fcntl(fd, fcntl.F_GETFD, 0)
        except IOError:
            pass
        else:
            # flags read successfully, modify
            flags |= fcntl.FD_CLOEXEC
            fcntl.fcntl(fd, fcntl.F_SETFD, flags)
        return


def atomic_save(dest_path, **kwargs):
    """A convenient interface to the :class:`AtomicSaver` type. See the
    :class:`AtomicSaver` documentation for details.
    """
    return AtomicSaver(dest_path, **kwargs)


def path_to_unicode(path):
    if isinstance(path, unicode):
        return path
    encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()
    return path.decode(encoding)


if os.name == 'nt':
    import ctypes
    from ctypes import c_wchar_p
    from ctypes.wintypes import DWORD, LPVOID

    _ReplaceFile = ctypes.windll.kernel32.ReplaceFile
    _ReplaceFile.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p,
                             DWORD, LPVOID, LPVOID]

    def replace(src, dst):
        # argument names match stdlib docs, docstring below
        try:
            # ReplaceFile fails if the dest file does not exist, so
            # first try to rename it into position
            os.rename(src, dst)
            return
        except WindowsError as we:
            if we.errno == errno.EEXIST:
                pass  # continue with the ReplaceFile logic below
            else:
                raise

        src = path_to_unicode(src)
        dst = path_to_unicode(dst)
        res = _ReplaceFile(c_wchar_p(dst), c_wchar_p(src),
                           None, 0, None, None)
        if not res:
            raise OSError('failed to replace %r with %r' % (dst, src))
        return

    def atomic_rename(src, dst, overwrite=False):
        "Rename *src* to *dst*, replacing *dst* if *overwrite is True"
        if overwrite:
            replace(src, dst)
        else:
            os.rename(src, dst)
        return
else:
    # wrapper func for cross compat + docs
    def replace(src, dst):
        # os.replace does the same thing on unix
        return os.rename(src, dst)

    def atomic_rename(src, dst, overwrite=False):
        "Rename *src* to *dst*, replacing *dst* if *overwrite is True"
        if overwrite:
            os.rename(src, dst)
        else:
            os.link(src, dst)
            os.unlink(dst)
        return


_atomic_rename = atomic_rename  # backwards compat

replace.__doc__ = """Similar to :func:`os.replace` in Python 3.3+,
this function will atomically create or replace the file at path
*dst* with the file at path *src*.

On Windows, this function uses the ReplaceFile API for maximum
possible atomicity on a range of filesystems.
"""


class AtomicSaver(object):
    """``AtomicSaver`` is a configurable `context manager`_ that provides
    a writable :class:`file` which will be moved into place as long as
    no exceptions are raised within the context manager's block. These
    "part files" are created in the same directory as the destination
    path to ensure atomic move operations (i.e., no cross-filesystem
    moves occur).

    Args:
        dest_path (str): The path where the completed file will be
            written.
        overwrite (bool): Whether to overwrite the destination file if
            it exists at completion time. Defaults to ``True``.
        file_perms (int): Integer representation of file permissions
            for the newly-created file. Defaults are, when the
            destination path already exists, to copy the permissions
            from the previous file, or if the file did not exist, to
            respect the user's configured `umask`_, usually resulting
            in octal 0644 or 0664.
        part_file (str): Name of the temporary *part_file*. Defaults
            to *dest_path* + ``.part``. Note that this argument is
            just the filename, and not the full path of the part
            file. To guarantee atomic saves, part files are always
            created in the same directory as the destination path.
        overwrite_part (bool): Whether to overwrite the *part_file*,
            should it exist at setup time. Defaults to ``False``,
            which results in an :exc:`OSError` being raised on
            pre-existing part files. Be careful of setting this to
            ``True`` in situations when multiple threads or processes
            could be writing to the same part file.
        rm_part_on_exc (bool): Remove *part_file* on exception cases.
            Defaults to ``True``, but ``False`` can be useful for
            recovery in some cases. Note that resumption is not
            automatic and by default an :exc:`OSError` is raised if
            the *part_file* exists.

    Practically, the AtomicSaver serves a few purposes:

      * Avoiding overwriting an existing, valid file with a partially
        written one.
      * Providing a reasonable guarantee that a part file only has one
        writer at a time.
      * Optional recovery of partial data in failure cases.

    .. _context manager: https://docs.python.org/3/reference/compound_stmts.html#with
    .. _umask: https://en.wikipedia.org/wiki/Umask

    """
    _default_file_perms = RW_PERMS

    # TODO: option to abort if target file modify date has changed since start?
    def __init__(self, dest_path, **kwargs):
        self.dest_path = dest_path
        self.overwrite = kwargs.pop('overwrite', True)
        self.file_perms = kwargs.pop('file_perms', None)
        self.overwrite_part = kwargs.pop('overwrite_part', False)
        self.part_filename = kwargs.pop('part_file', None)
        self.rm_part_on_exc = kwargs.pop('rm_part_on_exc', True)
        self.text_mode = kwargs.pop('text_mode', False)  # for windows
        self.buffering = kwargs.pop('buffering', -1)
        if kwargs:
            raise TypeError('unexpected kwargs: %r' % (kwargs.keys(),))

        self.dest_path = os.path.abspath(self.dest_path)
        self.dest_dir = os.path.dirname(self.dest_path)
        if not self.part_filename:
            self.part_path = dest_path + '.part'
        else:
            self.part_path = os.path.join(self.dest_dir, self.part_filename)
        self.mode = 'w+' if self.text_mode else 'w+b'
        self.open_flags = _TEXT_OPENFLAGS if self.text_mode else _BIN_OPENFLAGS

        self.part_file = None

    def _open_part_file(self):
        do_chmod = True
        file_perms = self.file_perms
        if file_perms is None:
            try:
                # try to copy from file being replaced
                stat_res = os.stat(self.dest_path)
                file_perms = stat.S_IMODE(stat_res.st_mode)
            except (OSError, IOError):
                # default if no destination file exists
                file_perms = self._default_file_perms
                do_chmod = False  # respect the umask

        fd = os.open(self.part_path, self.open_flags, file_perms)
        set_cloexec(fd)
        self.part_file = os.fdopen(fd, self.mode, self.buffering)

        # if default perms are overridden by the user or previous dest_path
        # chmod away the effects of the umask
        if do_chmod:
            try:
                os.chmod(self.part_path, file_perms)
            except (OSError, IOError):
                self.part_file.close()
                raise
        return

    def setup(self):
        """Called on context manager entry (the :keyword:`with` statement),
        the ``setup()`` method creates the temporary file in the same
        directory as the destination file.

        ``setup()`` tests for a writable directory with rename permissions
        early, as the part file may not be written to immediately (not
        using :func:`os.access` because of the potential issues of
        effective vs. real privileges).

        If the caller is not using the :class:`AtomicSaver` as a
        context manager, this method should be called explicitly
        before writing.
        """
        if os.path.lexists(self.dest_path):
            if not self.overwrite:
                raise OSError(errno.EEXIST,
                              'Overwrite disabled and file already exists',
                              self.dest_path)
        if self.overwrite_part and os.path.lexists(self.part_path):
            os.unlink(self.part_path)
        self._open_part_file()
        return

    def __enter__(self):
        self.setup()
        return self.part_file

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.part_file.close()
        if exc_type:
            if self.rm_part_on_exc:
                try:
                    os.unlink(self.part_path)
                except Exception:
                    pass  # avoid masking original error
            return
        try:
            atomic_rename(self.part_path, self.dest_path,
                          overwrite=self.overwrite)
        except OSError:
            if self.rm_part_on_exc:
                try:
                    os.unlink(self.part_path)
                except Exception:
                    pass  # avoid masking original error
            raise  # could not save destination file
        return


def iter_find_files(directory, patterns, ignored=None):
    """Returns a generator that yields file paths under a *directory*,
    matching *patterns* using `glob`_ syntax (e.g., ``*.txt``). Also
    supports *ignored* patterns.

    Args:
        directory (str): Path that serves as the root of the
            search. Yielded paths will include this as a prefix.
        patterns (str or list): A single pattern or list of
            glob-formatted patterns to find under *directory*.
        ignored (str or list): A single pattern or list of
            glob-formatted patterns to ignore.

    For example, finding Python files in the directory of this module:

    >>> files = set(iter_find_files(os.path.dirname(__file__), '*.py'))

    Or, Python files while ignoring emacs lockfiles:

    >>> filenames = iter_find_files('.', '*.py', ignored='.#*')

    .. _glob: https://en.wikipedia.org/wiki/Glob_%28programming%29

    """
    if isinstance(patterns, basestring):
        patterns = [patterns]
    pats_re = re.compile('|'.join([fnmatch.translate(p) for p in patterns]))

    if not ignored:
        ignored = []
    elif isinstance(ignored, basestring):
        ignored = [ignored]
    ign_re = re.compile('|'.join([fnmatch.translate(p) for p in ignored]))
    for root, dirs, files in os.walk(directory):
        for basename in files:
            if pats_re.match(basename):
                if ignored and ign_re.match(basename):
                    continue
                filename = os.path.join(root, basename)
                yield filename
    return


def copy_tree(src, dst, symlinks=False, ignore=None):
    """The ``copy_tree`` function is an exact copy of the built-in
    :func:`shutil.copytree`, with one key difference: it will not
    raise an exception if part of the tree already exists. It achieves
    this by using :func:`mkdir_p`.

    Args:
        src (str): Path of the source directory to copy.
        dst (str): Destination path. Existing directories accepted.
        symlinks (bool): If ``True``, copy symlinks rather than their
            contents.
        ignore (callable): A callable that takes a path and directory
            listing, returning the files within the listing to be ignored.

    For more details, check out :func:`shutil.copytree` and
    :func:`shutil.copy2`.

    """
    names = os.listdir(src)
    if ignore is not None:
        ignored_names = ignore(src, names)
    else:
        ignored_names = set()

    mkdir_p(dst)
    errors = []
    for name in names:
        if name in ignored_names:
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if symlinks and os.path.islink(srcname):
                linkto = os.readlink(srcname)
                os.symlink(linkto, dstname)
            elif os.path.isdir(srcname):
                copytree(srcname, dstname, symlinks, ignore)
            else:
                # Will raise a SpecialFileError for unsupported file types
                copy2(srcname, dstname)
        # catch the Error from the recursive copytree so that we can
        # continue with other files
        except Error as e:
            errors.extend(e.args[0])
        except EnvironmentError as why:
            errors.append((srcname, dstname, str(why)))
    try:
        copystat(src, dst)
    except OSError as why:
        if WindowsError is not None and isinstance(why, WindowsError):
            # Copying file access times may fail on Windows
            pass
        else:
            errors.append((src, dst, str(why)))
    if errors:
        raise Error(errors)


copytree = copy_tree  # alias for drop-in replacement of shutil


try:
    file
except NameError:
    file = object


# like open(os.devnull) but with even fewer side effects
class DummyFile(file):
    # TODO: raise ValueErrors on closed for all methods?
    # TODO: enforce read/write
    def __init__(self, path, mode='r', buffering=None):
        self.name = path
        self.mode = mode
        self.closed = False
        self.errors = None
        self.isatty = False
        self.encoding = None
        self.newlines = None
        self.softspace = 0

    def close(self):
        self.closed = True

    def fileno(self):
        return -1

    def flush(self):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return

    def next(self):
        raise StopIteration()

    def read(self, size=0):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return ''

    def readline(self, size=0):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return ''

    def readlines(self, size=0):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return []

    def seek(self):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return

    def tell(self):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return 0

    def truncate(self):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return

    def write(self, string):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return

    def writelines(self, list_of_strings):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return

    def __next__(self):
        raise StopIteration()

    def __enter__(self):
        if self.closed:
            raise ValueError('I/O operation on a closed file')
        return

    def __exit__(self, exc_type, exc_val, exc_tb):
        return
