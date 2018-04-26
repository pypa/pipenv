# See https://pypi.python.org/pypi/backports

from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
from . import weakref
from . import shutil_get_terminal_size
