"""scandir, a better directory iterator and faster os.walk(), now in the Python 3.5 stdlib

scandir() is a generator version of os.listdir() that returns an
iterator over files in a directory, and also exposes the extra
information most OSes provide while iterating files in a directory
(such as type and stat information).

This module also includes a version of os.walk() that uses scandir()
to speed it up significantly.

See README.md or https://github.com/benhoyt/scandir for rationale and
docs, or read PEP 471 (https://www.python.org/dev/peps/pep-0471/) for
more details on its inclusion into Python 3.5

scandir is released under the new BSD 3-clause license. See
LICENSE.txt for the full license text.
"""

from __future__ import division

from errno import ENOENT
from os import listdir, lstat, stat, strerror
from os.path import join, islink
from stat import S_IFDIR, S_IFLNK, S_IFREG
import collections
import sys

_scandir = None

try:
    import ctypes
except ImportError:
    ctypes = None

if _scandir is None and ctypes is None:
    import warnings
    warnings.warn("scandir can't find the compiled _scandir C module "
                  "or ctypes, using slow generic fallback")

__version__ = '1.10.0'
__all__ = ['scandir', 'walk']

# Windows FILE_ATTRIBUTE constants for interpreting the
# FIND_DATA.dwFileAttributes member
FILE_ATTRIBUTE_ARCHIVE = 32
FILE_ATTRIBUTE_COMPRESSED = 2048
FILE_ATTRIBUTE_DEVICE = 64
FILE_ATTRIBUTE_DIRECTORY = 16
FILE_ATTRIBUTE_ENCRYPTED = 16384
FILE_ATTRIBUTE_HIDDEN = 2
FILE_ATTRIBUTE_INTEGRITY_STREAM = 32768
FILE_ATTRIBUTE_NORMAL = 128
FILE_ATTRIBUTE_NOT_CONTENT_INDEXED = 8192
FILE_ATTRIBUTE_NO_SCRUB_DATA = 131072
FILE_ATTRIBUTE_OFFLINE = 4096
FILE_ATTRIBUTE_READONLY = 1
FILE_ATTRIBUTE_REPARSE_POINT = 1024
FILE_ATTRIBUTE_SPARSE_FILE = 512
FILE_ATTRIBUTE_SYSTEM = 4
FILE_ATTRIBUTE_TEMPORARY = 256
FILE_ATTRIBUTE_VIRTUAL = 65536

IS_PY3 = sys.version_info >= (3, 0)

if IS_PY3:
    unicode = str  # Because Python <= 3.2 doesn't have u'unicode' syntax


class GenericDirEntry(object):
    __slots__ = ('name', '_stat', '_lstat', '_scandir_path', '_path')

    def __init__(self, scandir_path, name):
        self._scandir_path = scandir_path
        self.name = name
        self._stat = None
        self._lstat = None
        self._path = None

    @property
    def path(self):
        if self._path is None:
            self._path = join(self._scandir_path, self.name)
        return self._path

    def stat(self, follow_symlinks=True):
        if follow_symlinks:
            if self._stat is None:
                self._stat = stat(self.path)
            return self._stat
        else:
            if self._lstat is None:
                self._lstat = lstat(self.path)
            return self._lstat

    # The code duplication below is intentional: this is for slightly
    # better performance on systems that fall back to GenericDirEntry.
    # It avoids an additional attribute lookup and method call, which
    # are relatively slow on CPython.
    def is_dir(self, follow_symlinks=True):
        try:
            st = self.stat(follow_symlinks=follow_symlinks)
        except OSError as e:
            if e.errno != ENOENT:
                raise
            return False  # Path doesn't exist or is a broken symlink
        return st.st_mode & 0o170000 == S_IFDIR

    def is_file(self, follow_symlinks=True):
        try:
            st = self.stat(follow_symlinks=follow_symlinks)
        except OSError as e:
            if e.errno != ENOENT:
                raise
            return False  # Path doesn't exist or is a broken symlink
        return st.st_mode & 0o170000 == S_IFREG

    def is_symlink(self):
        try:
            st = self.stat(follow_symlinks=False)
        except OSError as e:
            if e.errno != ENOENT:
                raise
            return False  # Path doesn't exist or is a broken symlink
        return st.st_mode & 0o170000 == S_IFLNK

    def inode(self):
        st = self.stat(follow_symlinks=False)
        return st.st_ino

    def __str__(self):
        return '<{0}: {1!r}>'.format(self.__class__.__name__, self.name)

    __repr__ = __str__


def _scandir_generic(path=unicode('.')):
    """Like os.listdir(), but yield DirEntry objects instead of returning
    a list of names.
    """
    for name in listdir(path):
        yield GenericDirEntry(path, name)


if IS_PY3 and sys.platform == 'win32':
    def scandir_generic(path=unicode('.')):
        if isinstance(path, bytes):
            raise TypeError("os.scandir() doesn't support bytes path on Windows, use Unicode instead")
        return _scandir_generic(path)
    scandir_generic.__doc__ = _scandir_generic.__doc__
else:
    scandir_generic = _scandir_generic


scandir_c = None
scandir_python = None


if sys.platform == 'win32':
    if ctypes is not None:
        from ctypes import wintypes

        # Various constants from windows.h
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
        ERROR_FILE_NOT_FOUND = 2
        ERROR_NO_MORE_FILES = 18
        IO_REPARSE_TAG_SYMLINK = 0xA000000C

        # Numer of seconds between 1601-01-01 and 1970-01-01
        SECONDS_BETWEEN_EPOCHS = 11644473600

        kernel32 = ctypes.windll.kernel32

        # ctypes wrappers for (wide string versions of) FindFirstFile,
        # FindNextFile, and FindClose
        FindFirstFile = kernel32.FindFirstFileW
        FindFirstFile.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.WIN32_FIND_DATAW),
        ]
        FindFirstFile.restype = wintypes.HANDLE

        FindNextFile = kernel32.FindNextFileW
        FindNextFile.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.WIN32_FIND_DATAW),
        ]
        FindNextFile.restype = wintypes.BOOL

        FindClose = kernel32.FindClose
        FindClose.argtypes = [wintypes.HANDLE]
        FindClose.restype = wintypes.BOOL

        Win32StatResult = collections.namedtuple('Win32StatResult', [
            'st_mode',
            'st_ino',
            'st_dev',
            'st_nlink',
            'st_uid',
            'st_gid',
            'st_size',
            'st_atime',
            'st_mtime',
            'st_ctime',
            'st_atime_ns',
            'st_mtime_ns',
            'st_ctime_ns',
            'st_file_attributes',
        ])

        def filetime_to_time(filetime):
            """Convert Win32 FILETIME to time since Unix epoch in seconds."""
            total = filetime.dwHighDateTime << 32 | filetime.dwLowDateTime
            return total / 10000000 - SECONDS_BETWEEN_EPOCHS

        def find_data_to_stat(data):
            """Convert Win32 FIND_DATA struct to stat_result."""
            # First convert Win32 dwFileAttributes to st_mode
            attributes = data.dwFileAttributes
            st_mode = 0
            if attributes & FILE_ATTRIBUTE_DIRECTORY:
                st_mode |= S_IFDIR | 0o111
            else:
                st_mode |= S_IFREG
            if attributes & FILE_ATTRIBUTE_READONLY:
                st_mode |= 0o444
            else:
                st_mode |= 0o666
            if (attributes & FILE_ATTRIBUTE_REPARSE_POINT and
                    data.dwReserved0 == IO_REPARSE_TAG_SYMLINK):
                st_mode ^= st_mode & 0o170000
                st_mode |= S_IFLNK

            st_size = data.nFileSizeHigh << 32 | data.nFileSizeLow
            st_atime = filetime_to_time(data.ftLastAccessTime)
            st_mtime = filetime_to_time(data.ftLastWriteTime)
            st_ctime = filetime_to_time(data.ftCreationTime)

            # Some fields set to zero per CPython's posixmodule.c: st_ino, st_dev,
            # st_nlink, st_uid, st_gid
            return Win32StatResult(st_mode, 0, 0, 0, 0, 0, st_size,
                                   st_atime, st_mtime, st_ctime,
                                   int(st_atime * 1000000000),
                                   int(st_mtime * 1000000000),
                                   int(st_ctime * 1000000000),
                                   attributes)

        class Win32DirEntryPython(object):
            __slots__ = ('name', '_stat', '_lstat', '_find_data', '_scandir_path', '_path', '_inode')

            def __init__(self, scandir_path, name, find_data):
                self._scandir_path = scandir_path
                self.name = name
                self._stat = None
                self._lstat = None
                self._find_data = find_data
                self._path = None
                self._inode = None

            @property
            def path(self):
                if self._path is None:
                    self._path = join(self._scandir_path, self.name)
                return self._path

            def stat(self, follow_symlinks=True):
                if follow_symlinks:
                    if self._stat is None:
                        if self.is_symlink():
                            # It's a symlink, call link-following stat()
                            self._stat = stat(self.path)
                        else:
                            # Not a symlink, stat is same as lstat value
                            if self._lstat is None:
                                self._lstat = find_data_to_stat(self._find_data)
                            self._stat = self._lstat
                    return self._stat
                else:
                    if self._lstat is None:
                        # Lazily convert to stat object, because it's slow
                        # in Python, and often we only need is_dir() etc
                        self._lstat = find_data_to_stat(self._find_data)
                    return self._lstat

            def is_dir(self, follow_symlinks=True):
                is_symlink = self.is_symlink()
                if follow_symlinks and is_symlink:
                    try:
                        return self.stat().st_mode & 0o170000 == S_IFDIR
                    except OSError as e:
                        if e.errno != ENOENT:
                            raise
                        return False
                elif is_symlink:
                    return False
                else:
                    return (self._find_data.dwFileAttributes &
                            FILE_ATTRIBUTE_DIRECTORY != 0)

            def is_file(self, follow_symlinks=True):
                is_symlink = self.is_symlink()
                if follow_symlinks and is_symlink:
                    try:
                        return self.stat().st_mode & 0o170000 == S_IFREG
                    except OSError as e:
                        if e.errno != ENOENT:
                            raise
                        return False
                elif is_symlink:
                    return False
                else:
                    return (self._find_data.dwFileAttributes &
                            FILE_ATTRIBUTE_DIRECTORY == 0)

            def is_symlink(self):
                return (self._find_data.dwFileAttributes &
                            FILE_ATTRIBUTE_REPARSE_POINT != 0 and
                        self._find_data.dwReserved0 == IO_REPARSE_TAG_SYMLINK)

            def inode(self):
                if self._inode is None:
                    self._inode = lstat(self.path).st_ino
                return self._inode

            def __str__(self):
                return '<{0}: {1!r}>'.format(self.__class__.__name__, self.name)

            __repr__ = __str__

        def win_error(error, filename):
            exc = WindowsError(error, ctypes.FormatError(error))
            exc.filename = filename
            return exc

        def _scandir_python(path=unicode('.')):
            """Like os.listdir(), but yield DirEntry objects instead of returning
            a list of names.
            """
            # Call FindFirstFile and handle errors
            if isinstance(path, bytes):
                is_bytes = True
                filename = join(path.decode('mbcs', 'strict'), '*.*')
            else:
                is_bytes = False
                filename = join(path, '*.*')
            data = wintypes.WIN32_FIND_DATAW()
            data_p = ctypes.byref(data)
            handle = FindFirstFile(filename, data_p)
            if handle == INVALID_HANDLE_VALUE:
                error = ctypes.GetLastError()
                if error == ERROR_FILE_NOT_FOUND:
                    # No files, don't yield anything
                    return
                raise win_error(error, path)

            # Call FindNextFile in a loop, stopping when no more files
            try:
                while True:
                    # Skip '.' and '..' (current and parent directory), but
                    # otherwise yield (filename, stat_result) tuple
                    name = data.cFileName
                    if name not in ('.', '..'):
                        if is_bytes:
                            name = name.encode('mbcs', 'replace')
                        yield Win32DirEntryPython(path, name, data)

                    data = wintypes.WIN32_FIND_DATAW()
                    data_p = ctypes.byref(data)
                    success = FindNextFile(handle, data_p)
                    if not success:
                        error = ctypes.GetLastError()
                        if error == ERROR_NO_MORE_FILES:
                            break
                        raise win_error(error, path)
            finally:
                if not FindClose(handle):
                    raise win_error(ctypes.GetLastError(), path)

        if IS_PY3:
            def scandir_python(path=unicode('.')):
                if isinstance(path, bytes):
                    raise TypeError("os.scandir() doesn't support bytes path on Windows, use Unicode instead")
                return _scandir_python(path)
            scandir_python.__doc__ = _scandir_python.__doc__
        else:
            scandir_python = _scandir_python

    if _scandir is not None:
        scandir_c = _scandir.scandir
        DirEntry_c = _scandir.DirEntry

    if _scandir is not None:
        scandir = scandir_c
        DirEntry = DirEntry_c
    elif ctypes is not None:
        scandir = scandir_python
        DirEntry = Win32DirEntryPython
    else:
        scandir = scandir_generic
        DirEntry = GenericDirEntry


# Linux, OS X, and BSD implementation
elif sys.platform.startswith(('linux', 'darwin', 'sunos5')) or 'bsd' in sys.platform:
    have_dirent_d_type = (sys.platform != 'sunos5')

    if ctypes is not None and have_dirent_d_type:
        import ctypes.util

        DIR_p = ctypes.c_void_p

        # Rather annoying how the dirent struct is slightly different on each
        # platform. The only fields we care about are d_name and d_type.
        class Dirent(ctypes.Structure):
            if sys.platform.startswith('linux'):
                _fields_ = (
                    ('d_ino', ctypes.c_ulong),
                    ('d_off', ctypes.c_long),
                    ('d_reclen', ctypes.c_ushort),
                    ('d_type', ctypes.c_byte),
                    ('d_name', ctypes.c_char * 256),
                )
            elif 'openbsd' in sys.platform:
                _fields_ = (
                    ('d_ino', ctypes.c_uint64),
                    ('d_off', ctypes.c_uint64),
                    ('d_reclen', ctypes.c_uint16),
                    ('d_type', ctypes.c_uint8),
                    ('d_namlen', ctypes.c_uint8),
                    ('__d_padding', ctypes.c_uint8 * 4),
                    ('d_name', ctypes.c_char * 256),
                )
            else:
                _fields_ = (
                    ('d_ino', ctypes.c_uint32),  # must be uint32, not ulong
                    ('d_reclen', ctypes.c_ushort),
                    ('d_type', ctypes.c_byte),
                    ('d_namlen', ctypes.c_byte),
                    ('d_name', ctypes.c_char * 256),
                )

        DT_UNKNOWN = 0
        DT_DIR = 4
        DT_REG = 8
        DT_LNK = 10

        Dirent_p = ctypes.POINTER(Dirent)
        Dirent_pp = ctypes.POINTER(Dirent_p)

        libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
        opendir = libc.opendir
        opendir.argtypes = [ctypes.c_char_p]
        opendir.restype = DIR_p

        readdir_r = libc.readdir_r
        readdir_r.argtypes = [DIR_p, Dirent_p, Dirent_pp]
        readdir_r.restype = ctypes.c_int

        closedir = libc.closedir
        closedir.argtypes = [DIR_p]
        closedir.restype = ctypes.c_int

        file_system_encoding = sys.getfilesystemencoding()

        class PosixDirEntry(object):
            __slots__ = ('name', '_d_type', '_stat', '_lstat', '_scandir_path', '_path', '_inode')

            def __init__(self, scandir_path, name, d_type, inode):
                self._scandir_path = scandir_path
                self.name = name
                self._d_type = d_type
                self._inode = inode
                self._stat = None
                self._lstat = None
                self._path = None

            @property
            def path(self):
                if self._path is None:
                    self._path = join(self._scandir_path, self.name)
                return self._path

            def stat(self, follow_symlinks=True):
                if follow_symlinks:
                    if self._stat is None:
                        if self.is_symlink():
                            self._stat = stat(self.path)
                        else:
                            if self._lstat is None:
                                self._lstat = lstat(self.path)
                            self._stat = self._lstat
                    return self._stat
                else:
                    if self._lstat is None:
                        self._lstat = lstat(self.path)
                    return self._lstat

            def is_dir(self, follow_symlinks=True):
                if (self._d_type == DT_UNKNOWN or
                        (follow_symlinks and self.is_symlink())):
                    try:
                        st = self.stat(follow_symlinks=follow_symlinks)
                    except OSError as e:
                        if e.errno != ENOENT:
                            raise
                        return False
                    return st.st_mode & 0o170000 == S_IFDIR
                else:
                    return self._d_type == DT_DIR

            def is_file(self, follow_symlinks=True):
                if (self._d_type == DT_UNKNOWN or
                        (follow_symlinks and self.is_symlink())):
                    try:
                        st = self.stat(follow_symlinks=follow_symlinks)
                    except OSError as e:
                        if e.errno != ENOENT:
                            raise
                        return False
                    return st.st_mode & 0o170000 == S_IFREG
                else:
                    return self._d_type == DT_REG

            def is_symlink(self):
                if self._d_type == DT_UNKNOWN:
                    try:
                        st = self.stat(follow_symlinks=False)
                    except OSError as e:
                        if e.errno != ENOENT:
                            raise
                        return False
                    return st.st_mode & 0o170000 == S_IFLNK
                else:
                    return self._d_type == DT_LNK

            def inode(self):
                return self._inode

            def __str__(self):
                return '<{0}: {1!r}>'.format(self.__class__.__name__, self.name)

            __repr__ = __str__

        def posix_error(filename):
            errno = ctypes.get_errno()
            exc = OSError(errno, strerror(errno))
            exc.filename = filename
            return exc

        def scandir_python(path=unicode('.')):
            """Like os.listdir(), but yield DirEntry objects instead of returning
            a list of names.
            """
            if isinstance(path, bytes):
                opendir_path = path
                is_bytes = True
            else:
                opendir_path = path.encode(file_system_encoding)
                is_bytes = False
            dir_p = opendir(opendir_path)
            if not dir_p:
                raise posix_error(path)
            try:
                result = Dirent_p()
                while True:
                    entry = Dirent()
                    if readdir_r(dir_p, entry, result):
                        raise posix_error(path)
                    if not result:
                        break
                    name = entry.d_name
                    if name not in (b'.', b'..'):
                        if not is_bytes:
                            name = name.decode(file_system_encoding)
                        yield PosixDirEntry(path, name, entry.d_type, entry.d_ino)
            finally:
                if closedir(dir_p):
                    raise posix_error(path)

    if _scandir is not None:
        scandir_c = _scandir.scandir
        DirEntry_c = _scandir.DirEntry

    if _scandir is not None:
        scandir = scandir_c
        DirEntry = DirEntry_c
    elif ctypes is not None and have_dirent_d_type:
        scandir = scandir_python
        DirEntry = PosixDirEntry
    else:
        scandir = scandir_generic
        DirEntry = GenericDirEntry


# Some other system -- no d_type or stat information
else:
    scandir = scandir_generic
    DirEntry = GenericDirEntry


def _walk(top, topdown=True, onerror=None, followlinks=False):
    """Like Python 3.5's implementation of os.walk() -- faster than
    the pre-Python 3.5 version as it uses scandir() internally.
    """
    dirs = []
    nondirs = []

    # We may not have read permission for top, in which case we can't
    # get a list of the files the directory contains.  os.walk
    # always suppressed the exception then, rather than blow up for a
    # minor reason when (say) a thousand readable directories are still
    # left to visit.  That logic is copied here.
    try:
        scandir_it = scandir(top)
    except OSError as error:
        if onerror is not None:
            onerror(error)
        return

    while True:
        try:
            try:
                entry = next(scandir_it)
            except StopIteration:
                break
        except OSError as error:
            if onerror is not None:
                onerror(error)
            return

        try:
            is_dir = entry.is_dir()
        except OSError:
            # If is_dir() raises an OSError, consider that the entry is not
            # a directory, same behaviour than os.path.isdir().
            is_dir = False

        if is_dir:
            dirs.append(entry.name)
        else:
            nondirs.append(entry.name)

        if not topdown and is_dir:
            # Bottom-up: recurse into sub-directory, but exclude symlinks to
            # directories if followlinks is False
            if followlinks:
                walk_into = True
            else:
                try:
                    is_symlink = entry.is_symlink()
                except OSError:
                    # If is_symlink() raises an OSError, consider that the
                    # entry is not a symbolic link, same behaviour than
                    # os.path.islink().
                    is_symlink = False
                walk_into = not is_symlink

            if walk_into:
                for entry in walk(entry.path, topdown, onerror, followlinks):
                    yield entry

    # Yield before recursion if going top down
    if topdown:
        yield top, dirs, nondirs

        # Recurse into sub-directories
        for name in dirs:
            new_path = join(top, name)
            # Issue #23605: os.path.islink() is used instead of caching
            # entry.is_symlink() result during the loop on os.scandir() because
            # the caller can replace the directory entry during the "yield"
            # above.
            if followlinks or not islink(new_path):
                for entry in walk(new_path, topdown, onerror, followlinks):
                    yield entry
    else:
        # Yield after recursion if going bottom up
        yield top, dirs, nondirs


if IS_PY3 or sys.platform != 'win32':
    walk = _walk
else:
    # Fix for broken unicode handling on Windows on Python 2.x, see:
    # https://github.com/benhoyt/scandir/issues/54
    file_system_encoding = sys.getfilesystemencoding()

    def walk(top, topdown=True, onerror=None, followlinks=False):
        if isinstance(top, bytes):
            top = top.decode(file_system_encoding)
        return _walk(top, topdown, onerror, followlinks)
