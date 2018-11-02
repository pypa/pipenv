# -*- coding=utf-8 -*-
# |~~\'    |~~
# |__/||~~\|--|/~\\  /
# |   ||__/|__|   |\/
#      |

import os
import sys
import warnings

from .__version__ import __version__

PIPENV_ROOT = os.path.dirname(os.path.realpath(__file__))
PIPENV_VENDOR = os.sep.join([PIPENV_ROOT, "vendor"])
PIPENV_PATCHED = os.sep.join([PIPENV_ROOT, "patched"])
# Inject vendored directory into system path.
sys.path.insert(0, PIPENV_VENDOR)
# Inject patched directory into system path.
sys.path.insert(0, PIPENV_PATCHED)

from pipenv.vendor.urllib3.exceptions import DependencyWarning
from pipenv.vendor.vistir.compat import ResourceWarning, fs_str
warnings.filterwarnings("ignore", category=DependencyWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=UserWarning)

if sys.version_info >= (3, 1) and sys.version_info <= (3, 6):
    if sys.stdout.isatty() and sys.stderr.isatty():
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf8')

os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = fs_str("1")
os.environ["PIP_SHIMS_BASE_MODULE"] = fs_str("pipenv.patched.notpip")

# Hack to make things work better.
try:
    if "concurrency" in sys.modules:
        del sys.modules["concurrency"]
except Exception:
    pass

from .cli import cli
from . import resolver

if __name__ == "__main__":
    cli()
