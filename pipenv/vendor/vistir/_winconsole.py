# -*- coding: utf-8 -*-

# This Module is taken in part from the click project and expanded
# see https://github.com/pallets/click/blob/6cafd32/click/_winconsole.py
# Copyright © 2014 by the Pallets team.

# Some rights reserved.

# Redistribution and use in source and binary forms of the software as well as
# documentation, with or without modification, are permitted provided that the
# following conditions are met:
#     Redistributions of source code must retain the above copyright notice,
#           this list of conditions and the following disclaimer.
#     Redistributions in binary form must reproduce the above copyright notice,
#           this list of conditions and the following disclaimer in the
#           documentation and/or other materials provided with the distribution.
#     Neither the name of the copyright holder nor the names of its contributors
#           may be used to endorse or promote products derived from this
#           software without specific prior written permission.

# THIS SOFTWARE AND DOCUMENTATION IS PROVIDED BY THE COPYRIGHT HOLDERS AND
# CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT
# NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE AND
# DOCUMENTATION, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# This module is based on the excellent work by Adam Bartoš who
# provided a lot of what went into the implementation here in
# the discussion to issue1602 in the Python bug tracker.
#
# There are some general differences in regards to how this works
# compared to the original patches as we do not need to patch
# the entire interpreter but just work in our little world of
# echo and prmopt.

import ctypes
import io
import os
import sys
import time
import zlib
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    Structure,
    byref,
    c_char,
    c_char_p,
    c_int,
    c_ssize_t,
    c_ulong,
    c_void_p,
    create_unicode_buffer,
    py_object,
    windll,
)
from ctypes.wintypes import HANDLE, LPCWSTR, LPWSTR
from itertools import count

import msvcrt
from six import PY2, text_type

from .compat import IS_TYPE_CHECKING
from .misc import StreamWrapper, run, to_text

try:
    from ctypes import pythonapi

    PyObject_GetBuffer = pythonapi.PyObject_GetBuffer
    PyBuffer_Release = pythonapi.PyBuffer_Release
except ImportError:
    pythonapi = None


if IS_TYPE_CHECKING:
    from typing import Text


c_ssize_p = POINTER(c_ssize_t)
CommandLineToArgvW = WINFUNCTYPE(POINTER(LPWSTR), LPCWSTR, POINTER(c_int))(
    ("CommandLineToArgvW", windll.shell32)
)
kernel32 = windll.kernel32
GetLastError = kernel32.GetLastError
GetCommandLineW = WINFUNCTYPE(LPWSTR)(("GetCommandLineW", windll.kernel32))
GetConsoleCursorInfo = kernel32.GetConsoleCursorInfo
GetStdHandle = kernel32.GetStdHandle
LocalFree = WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(("LocalFree", windll.kernel32))
ReadConsoleW = kernel32.ReadConsoleW
SetConsoleCursorInfo = kernel32.SetConsoleCursorInfo
WriteConsoleW = kernel32.WriteConsoleW

# XXX: Added for cursor hiding on windows
STDOUT_HANDLE_ID = ctypes.c_ulong(-11)
STDERR_HANDLE_ID = ctypes.c_ulong(-12)
STDIN_HANDLE = GetStdHandle(-10)
STDOUT_HANDLE = GetStdHandle(-11)
STDERR_HANDLE = GetStdHandle(-12)

STREAM_MAP = {0: STDIN_HANDLE, 1: STDOUT_HANDLE, 2: STDERR_HANDLE}


PyBUF_SIMPLE = 0
PyBUF_WRITABLE = 1

ERROR_SUCCESS = 0
ERROR_NOT_ENOUGH_MEMORY = 8
ERROR_OPERATION_ABORTED = 995

STDIN_FILENO = 0
STDOUT_FILENO = 1
STDERR_FILENO = 2

EOF = b"\x1a"
MAX_BYTES_WRITTEN = 32767


class Py_buffer(Structure):
    _fields_ = [
        ("buf", c_void_p),
        ("obj", py_object),
        ("len", c_ssize_t),
        ("itemsize", c_ssize_t),
        ("readonly", c_int),
        ("ndim", c_int),
        ("format", c_char_p),
        ("shape", c_ssize_p),
        ("strides", c_ssize_p),
        ("suboffsets", c_ssize_p),
        ("internal", c_void_p),
    ]

    if PY2:
        _fields_.insert(-1, ("smalltable", c_ssize_t * 2))


# XXX: This was added for the use of cursors
class CONSOLE_CURSOR_INFO(Structure):
    _fields_ = [("dwSize", ctypes.c_int), ("bVisible", ctypes.c_int)]


# On PyPy we cannot get buffers so our ability to operate here is
# serverly limited.
if pythonapi is None:
    get_buffer = None
else:

    def get_buffer(obj, writable=False):
        buf = Py_buffer()
        flags = PyBUF_WRITABLE if writable else PyBUF_SIMPLE
        PyObject_GetBuffer(py_object(obj), byref(buf), flags)
        try:
            buffer_type = c_char * buf.len
            return buffer_type.from_address(buf.buf)
        finally:
            PyBuffer_Release(byref(buf))


def get_long_path(short_path):
    # type: (Text, str) -> Text
    BUFFER_SIZE = 500
    buffer = create_unicode_buffer(BUFFER_SIZE)
    get_long_path_name = windll.kernel32.GetLongPathNameW
    get_long_path_name(to_text(short_path), buffer, BUFFER_SIZE)
    return buffer.value


class _WindowsConsoleRawIOBase(io.RawIOBase):
    def __init__(self, handle):
        self.handle = handle

    def isatty(self):
        io.RawIOBase.isatty(self)
        return True


class _WindowsConsoleReader(_WindowsConsoleRawIOBase):
    def readable(self):
        return True

    def readinto(self, b):
        bytes_to_be_read = len(b)
        if not bytes_to_be_read:
            return 0
        elif bytes_to_be_read % 2:
            raise ValueError(
                "cannot read odd number of bytes from " "UTF-16-LE encoded console"
            )

        buffer = get_buffer(b, writable=True)
        code_units_to_be_read = bytes_to_be_read // 2
        code_units_read = c_ulong()

        rv = ReadConsoleW(
            self.handle, buffer, code_units_to_be_read, byref(code_units_read), None
        )
        if GetLastError() == ERROR_OPERATION_ABORTED:
            # wait for KeyboardInterrupt
            time.sleep(0.1)
        if not rv:
            raise OSError("Windows error: %s" % GetLastError())

        if buffer[0] == EOF:
            return 0
        return 2 * code_units_read.value


class _WindowsConsoleWriter(_WindowsConsoleRawIOBase):
    def writable(self):
        return True

    @staticmethod
    def _get_error_message(errno):
        if errno == ERROR_SUCCESS:
            return "ERROR_SUCCESS"
        elif errno == ERROR_NOT_ENOUGH_MEMORY:
            return "ERROR_NOT_ENOUGH_MEMORY"
        return "Windows error %s" % errno

    def write(self, b):
        bytes_to_be_written = len(b)
        buf = get_buffer(b)
        code_units_to_be_written = min(bytes_to_be_written, MAX_BYTES_WRITTEN) // 2
        code_units_written = c_ulong()

        WriteConsoleW(
            self.handle, buf, code_units_to_be_written, byref(code_units_written), None
        )
        bytes_written = 2 * code_units_written.value

        if bytes_written == 0 and bytes_to_be_written > 0:
            raise OSError(self._get_error_message(GetLastError()))
        return bytes_written


class ConsoleStream(object):
    def __init__(self, text_stream, byte_stream):
        self._text_stream = text_stream
        self.buffer = byte_stream

    @property
    def name(self):
        return self.buffer.name

    @property
    def fileno(self):
        return self.buffer.fileno

    def write(self, x):
        if isinstance(x, text_type):
            return self._text_stream.write(x)
        try:
            self.flush()
        except Exception:
            pass
        return self.buffer.write(x)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        try:
            return getattr(self._text_stream, name)
        except io.UnsupportedOperation:
            return getattr(self.buffer, name)

    def isatty(self):
        return self.buffer.isatty()

    def __repr__(self):
        return "<ConsoleStream name=%r encoding=%r>" % (self.name, self.encoding)


class WindowsChunkedWriter(object):
    """
    Wraps a stream (such as stdout), acting as a transparent proxy for all
    attribute access apart from method 'write()' which we wrap to write in
    limited chunks due to a Windows limitation on binary console streams.
    """

    def __init__(self, wrapped):
        # double-underscore everything to prevent clashes with names of
        # attributes on the wrapped stream object.
        self.__wrapped = wrapped

    def __getattr__(self, name):
        return getattr(self.__wrapped, name)

    def write(self, text):
        total_to_write = len(text)
        written = 0

        while written < total_to_write:
            to_write = min(total_to_write - written, MAX_BYTES_WRITTEN)
            self.__wrapped.write(text[written : written + to_write])
            written += to_write


_wrapped_std_streams = set()


def _wrap_std_stream(name):
    # Python 2 & Windows 7 and below
    if PY2 and sys.getwindowsversion()[:2] <= (6, 1) and name not in _wrapped_std_streams:
        setattr(sys, name, WindowsChunkedWriter(getattr(sys, name)))
        _wrapped_std_streams.add(name)


def _get_text_stdin(buffer_stream):
    text_stream = StreamWrapper(
        io.BufferedReader(_WindowsConsoleReader(STDIN_HANDLE)),
        "utf-16-le",
        "strict",
        line_buffering=True,
    )
    return ConsoleStream(text_stream, buffer_stream)


def _get_text_stdout(buffer_stream):
    text_stream = StreamWrapper(
        io.BufferedWriter(_WindowsConsoleWriter(STDOUT_HANDLE)),
        "utf-16-le",
        "strict",
        line_buffering=True,
    )
    return ConsoleStream(text_stream, buffer_stream)


def _get_text_stderr(buffer_stream):
    text_stream = StreamWrapper(
        io.BufferedWriter(_WindowsConsoleWriter(STDERR_HANDLE)),
        "utf-16-le",
        "strict",
        line_buffering=True,
    )
    return ConsoleStream(text_stream, buffer_stream)


if PY2:

    def _hash_py_argv():
        return zlib.crc32("\x00".join(sys.argv[1:]))

    _initial_argv_hash = _hash_py_argv()

    def _get_windows_argv():
        argc = c_int(0)
        argv_unicode = CommandLineToArgvW(GetCommandLineW(), byref(argc))
        try:
            argv = [argv_unicode[i] for i in range(0, argc.value)]
        finally:
            LocalFree(argv_unicode)
            del argv_unicode

        if not hasattr(sys, "frozen"):
            argv = argv[1:]
            while len(argv) > 0:
                arg = argv[0]
                if not arg.startswith("-") or arg == "-":
                    break
                argv = argv[1:]
                if arg.startswith(("-c", "-m")):
                    break

        return argv[1:]


_stream_factories = {0: _get_text_stdin, 1: _get_text_stdout, 2: _get_text_stderr}


def _get_windows_console_stream(f, encoding, errors):
    if (
        get_buffer is not None
        and encoding in ("utf-16-le", None)
        and errors in ("strict", None)
        and hasattr(f, "isatty")
        and f.isatty()
    ):
        if isinstance(f, ConsoleStream):
            return f
        func = _stream_factories.get(f.fileno())
        if func is not None:
            if not PY2:
                f = getattr(f, "buffer", None)
                if f is None:
                    return None
            else:
                # If we are on Python 2 we need to set the stream that we
                # deal with to binary mode as otherwise the exercise if a
                # bit moot.  The same problems apply as for
                # get_binary_stdin and friends from _compat.
                msvcrt.setmode(f.fileno(), os.O_BINARY)
            return func(f)


def hide_cursor():
    cursor_info = CONSOLE_CURSOR_INFO()
    GetConsoleCursorInfo(STDOUT_HANDLE, ctypes.byref(cursor_info))
    cursor_info.visible = False
    SetConsoleCursorInfo(STDOUT_HANDLE, ctypes.byref(cursor_info))


def show_cursor():
    cursor_info = CONSOLE_CURSOR_INFO()
    GetConsoleCursorInfo(STDOUT_HANDLE, ctypes.byref(cursor_info))
    cursor_info.visible = True
    SetConsoleCursorInfo(STDOUT_HANDLE, ctypes.byref(cursor_info))


def get_stream_handle(stream):
    return STREAM_MAP.get(stream.fileno())


def _walk_for_powershell(directory):
    for path, dirs, files in os.walk(directory):
        powershell = next(
            iter(fn for fn in files if fn.lower() == "powershell.exe"), None
        )
        if powershell is not None:
            return os.path.join(directory, powershell)
        for subdir in dirs:
            powershell = _walk_for_powershell(os.path.join(directory, subdir))
            if powershell:
                return powershell
    return None


def _get_powershell_path():
    paths = [
        os.path.expandvars(r"%windir%\{0}\WindowsPowerShell").format(subdir)
        for subdir in ("SysWOW64", "system32")
    ]
    powershell_path = next(iter(_walk_for_powershell(pth) for pth in paths), None)
    if not powershell_path:
        powershell_path, _ = run(
            ["where", "powershell"], block=True, nospin=True, return_object=False
        )
    if powershell_path:
        return powershell_path.strip()
    return None


def _get_sid_with_powershell():
    powershell_path = _get_powershell_path()
    if not powershell_path:
        return None
    args = [
        powershell_path,
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Invoke-Expression '[System.Security.Principal.WindowsIdentity]::GetCurrent().user | Write-Host'",
    ]
    sid, _ = run(args, nospin=True)
    return sid.strip()


def _get_sid_from_registry():
    try:
        import winreg
    except ImportError:
        import _winreg as winreg
    var_names = ("%USERPROFILE%", "%HOME%")
    current_user_home = next(iter(os.path.expandvars(v) for v in var_names if v), None)
    root, subkey = (
        winreg.HKEY_LOCAL_MACHINE,
        r"Software\Microsoft\Windows NT\CurrentVersion\ProfileList",
    )
    subkey_names = []
    value = None
    matching_key = None
    try:
        with winreg.OpenKeyEx(root, subkey, 0, winreg.KEY_READ) as key:
            for i in count():
                key_name = winreg.EnumKey(key, i)
                subkey_names.append(key_name)
                value = query_registry_value(
                    root, r"{0}\{1}".format(subkey, key_name), "ProfileImagePath"
                )
                if value and value.lower() == current_user_home.lower():
                    matching_key = key_name
                    break
    except OSError:
        pass
    if matching_key is not None:
        return matching_key


def get_value_from_tuple(value, value_type):
    try:
        import winreg
    except ImportError:
        import _winreg as winreg
    if value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        if "\0" in value:
            return value[: value.index("\0")]
        return value
    return None


def query_registry_value(root, key_name, value):
    try:
        import winreg
    except ImportError:
        import _winreg as winreg
    try:
        with winreg.OpenKeyEx(root, key_name, 0, winreg.KEY_READ) as key:
            return get_value_from_tuple(*winreg.QueryValueEx(key, value))
    except OSError:
        return None


def get_current_user():
    fns = (_get_sid_from_registry, _get_sid_with_powershell)
    for fn in fns:
        result = fn()
        if result:
            return result
    return None
