import os
import sys

if sys.version_info >= (3, 0):
    from io import StringIO  # noqa
else:
    from StringIO import StringIO  # noqa

PY2 = sys.version_info[0] == 2  # type: bool


def is_type_checking():
    # type: () -> bool
    try:
        from typing import TYPE_CHECKING
    except ImportError:
        return False
    return TYPE_CHECKING


IS_TYPE_CHECKING = os.environ.get("MYPY_RUNNING", is_type_checking())
