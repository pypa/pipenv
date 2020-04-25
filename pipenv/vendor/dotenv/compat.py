import sys

PY2 = sys.version_info[0] == 2  # type: bool

if PY2:
    from StringIO import StringIO  # noqa
else:
    from io import StringIO  # noqa


def is_type_checking():
    # type: () -> bool
    try:
        from typing import TYPE_CHECKING
    except ImportError:  # pragma: no cover
        return False
    return TYPE_CHECKING


IS_TYPE_CHECKING = is_type_checking()


if IS_TYPE_CHECKING:
    from typing import Text


def to_env(text):
    # type: (Text) -> str
    """
    Encode a string the same way whether it comes from the environment or a `.env` file.
    """
    if PY2:
        return text.encode(sys.getfilesystemencoding() or "utf-8")
    else:
        return text


def to_text(string):
    # type: (str) -> Text
    """
    Make a string Unicode if it isn't already.

    This is useful for defining raw unicode strings because `ur"foo"` isn't valid in
    Python 3.
    """
    if PY2:
        return string.decode("utf-8")
    else:
        return string
