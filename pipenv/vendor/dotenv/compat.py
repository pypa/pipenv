import sys
try:
    from StringIO import StringIO  # noqa
except ImportError:
    from io import StringIO  # noqa

PY2 = sys.version_info[0] == 2
WIN = sys.platform.startswith('win')
text_type = unicode if PY2 else str  # noqa
