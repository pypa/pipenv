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
