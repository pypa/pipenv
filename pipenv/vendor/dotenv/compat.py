import sys

if sys.version_info >= (3, 0):
    from io import StringIO  # noqa
else:
    from StringIO import StringIO  # noqa

PY2 = sys.version_info[0] == 2  # type: bool
