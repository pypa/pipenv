"""A compatibility module for pipenv's backports and manipulations.

Exposes a standard API that enables compatibility across python versions,
operating systems, etc.
"""
import sys
import warnings

from pipenv.vendor import vistir

warnings.filterwarnings("ignore", category=ResourceWarning)


__all__ = [
    "getpreferredencoding",
    "DEFAULT_ENCODING",
    "canonical_encoding_name",
    "force_encoding",
    "UNICODE_TO_ASCII_TRANSLATION_MAP",
    "decode_output",
    "fix_utf8",
]


def getpreferredencoding():
    import locale

    # Borrowed from Invoke
    # (see https://github.com/pyinvoke/invoke/blob/93af29d/invoke/runners.py#L881)
    return locale.getpreferredencoding(False)


DEFAULT_ENCODING = getpreferredencoding()


def canonical_encoding_name(name):
    import codecs

    try:
        codec = codecs.lookup(name)
    except LookupError:
        return name
    else:
        return codec.name


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
    stdout_encoding = canonical_encoding_name(sys.stdout.encoding)
    stderr_encoding = canonical_encoding_name(sys.stderr.encoding)
    if sys.platform == "win32":
        return DEFAULT_ENCODING, DEFAULT_ENCODING
    if stdout_encoding != "utf-8" or stderr_encoding != "utf-8":

        try:
            from ctypes import c_char_p, py_object, pythonapi
        except ImportError:
            return DEFAULT_ENCODING, DEFAULT_ENCODING
        try:
            PyFile_SetEncoding = pythonapi.PyFile_SetEncoding
        except AttributeError:
            return DEFAULT_ENCODING, DEFAULT_ENCODING
        else:
            PyFile_SetEncoding.argtypes = (py_object, c_char_p)
            if stdout_encoding != "utf-8":
                try:
                    was_set = PyFile_SetEncoding(sys.stdout, "utf-8")
                except OSError:
                    was_set = False
                if not was_set:
                    stdout_encoding = DEFAULT_ENCODING
                else:
                    stdout_encoding = "utf-8"

            if stderr_encoding != "utf-8":
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
    8230: "...",
    8211: "-",
    10004: "OK",
    10008: "x",
}


def decode_for_output(output, target=sys.stdout):
    return vistir.misc.decode_for_output(
        output, sys.stdout, translation_map=UNICODE_TO_ASCII_TRANSLATION_MAP
    )


def decode_output(output):
    if not isinstance(output, str):
        return output
    try:
        output = output.encode(DEFAULT_ENCODING)
    except (AttributeError, UnicodeDecodeError, UnicodeEncodeError):
        output = output.translate(UNICODE_TO_ASCII_TRANSLATION_MAP)
        output = output.encode(DEFAULT_ENCODING, "replace")
    return vistir.misc.to_text(output, encoding=DEFAULT_ENCODING, errors="replace")


def fix_utf8(text):
    if not isinstance(text, str):
        return text
    try:
        text = decode_output(text)
    except UnicodeDecodeError:
        pass
    return text
