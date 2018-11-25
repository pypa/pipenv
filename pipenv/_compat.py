# -*- coding=utf-8 -*-
"""A compatibility module for pipenv's backports and manipulations.

Exposes a standard API that enables compatibility across python versions,
operating systems, etc.
"""

import functools
import importlib
import io
import os
import six
import sys
import warnings
import vistir
from .vendor.vistir.compat import NamedTemporaryFile, Path, ResourceWarning, TemporaryDirectory

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from .vendor.backports.shutil_get_terminal_size import get_terminal_size
else:
    from shutil import get_terminal_size

warnings.filterwarnings("ignore", category=ResourceWarning)


__all__ = [
    "NamedTemporaryFile", "Path", "ResourceWarning", "TemporaryDirectory",
    "get_terminal_size", "getpreferredencoding", "DEFAULT_ENCODING", "force_encoding",
    "UNICODE_TO_ASCII_TRANSLATION_MAP", "decode_output", "fix_utf8"
]


def getpreferredencoding():
    import locale
    # Borrowed from Invoke
    # (see https://github.com/pyinvoke/invoke/blob/93af29d/invoke/runners.py#L881)
    _encoding = locale.getpreferredencoding(False)
    if six.PY2 and not sys.platform == "win32":
        _default_encoding = locale.getdefaultlocale()[1]
        if _default_encoding is not None:
            _encoding = _default_encoding
    return _encoding


DEFAULT_ENCODING = getpreferredencoding()


# From https://github.com/CarlFK/veyepar/blob/5c5de47/dj/scripts/fixunicode.py
# MIT LIcensed, thanks Carl!
def force_encoding():
    try:
        stdout_isatty = sys.stdout.isatty
        stderr_isatty = sys.stderr.isatty
    except AttributeError:
        return DEFAULT_ENCODING, DEFAULT_ENCODING
    else:
        if not (stdout_isatty() and stderr_isatty()):
            return DEFAULT_ENCODING, DEFAULT_ENCODING
    stdout_encoding = sys.stdout.encoding
    stderr_encoding = sys.stderr.encoding
    if sys.platform == "win32" and sys.version_info >= (3, 1):
        return DEFAULT_ENCODING, DEFAULT_ENCODING
    if stdout_encoding.lower() != "utf-8" or stderr_encoding.lower() != "utf-8":

        from ctypes import pythonapi, py_object, c_char_p
        try:
            PyFile_SetEncoding = pythonapi.PyFile_SetEncoding
        except AttributeError:
            return DEFAULT_ENCODING, DEFAULT_ENCODING
        else:
            PyFile_SetEncoding.argtypes = (py_object, c_char_p)
            if stdout_encoding.lower() != "utf-8":
                try:
                    was_set = PyFile_SetEncoding(sys.stdout, "utf-8")
                except OSError:
                    was_set = False
                if not was_set:
                    stdout_encoding = DEFAULT_ENCODING
                else:
                    stdout_encoding = "utf-8"

            if stderr_encoding.lower() != "utf-8":
                try:
                    was_set = PyFile_SetEncoding(sys.stderr, "utf-8")
                except OSError:
                    was_set = False
                if not was_set:
                    stderr_encoding = DEFAULT_ENCODING
                else:
                    stderr_encoding = "utf-8"

    return stdout_encoding, stderr_encoding


OUT_ENCODING, ERR_ENCODING = force_encoding()


UNICODE_TO_ASCII_TRANSLATION_MAP = {
    8230: u"...",
    8211: u"-",
    10004: u"OK",
    10008: u"x",
}


def decode_output(output):
    if not isinstance(output, six.string_types):
        return output
    try:
        output = output.encode(DEFAULT_ENCODING)
    except (AttributeError, UnicodeDecodeError, UnicodeEncodeError):
        if six.PY2:
            output = unicode.translate(vistir.misc.to_text(output),
                                       UNICODE_TO_ASCII_TRANSLATION_MAP)
        else:
            output = output.translate(UNICODE_TO_ASCII_TRANSLATION_MAP)
        output = output.encode(DEFAULT_ENCODING, "replace")
    return vistir.misc.to_text(output, encoding=DEFAULT_ENCODING, errors="replace")


def fix_utf8(text):
    if not isinstance(text, six.string_types):
        return text
    try:
        text = decode_output(text)
    except UnicodeDecodeError:
        if six.PY2:
            text = unicode.translate(vistir.misc.to_text(text), UNICODE_TO_ASCII_TRANSLATION_MAP)
    return text
