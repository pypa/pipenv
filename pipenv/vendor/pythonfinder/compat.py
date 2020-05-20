# -*- coding=utf-8 -*-
import sys

import six

if sys.version_info[:2] <= (3, 4):
    from pipenv.vendor.pathlib2 import Path  # type: ignore  # noqa
else:
    from pathlib import Path

if six.PY3:
    from functools import lru_cache
    from builtins import TimeoutError
else:
    from backports.functools_lru_cache import lru_cache  # type: ignore  # noqa

    class TimeoutError(OSError):
        pass


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


def fs_str(string):
    """Encodes a string into the proper filesystem encoding"""

    if isinstance(string, str):
        return string
    assert not isinstance(string, bytes)
    return string.encode(DEFAULT_ENCODING)
