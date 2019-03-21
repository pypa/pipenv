# -*- coding=utf-8 -*-
# |~~\'    |~~
# |__/||~~\|--|/~\\  /
# |   ||__/|__|   |\/
#      |

import os
import sys
import warnings

from .__version__ import __version__


PIPENV_ROOT = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
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


os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = fs_str("1")

# Hack to make things work better.
try:
    if "concurrency" in sys.modules:
        del sys.modules["concurrency"]
except Exception:
    pass

from .vendor.vistir.misc import get_wrapped_stream
if sys.version_info >= (3, 0):
    stdout = sys.stdout.buffer
    stderr = sys.stderr.buffer
else:
    stdout = sys.stdout
    stderr = sys.stderr


sys.stderr = get_wrapped_stream(stderr)
sys.stdout = get_wrapped_stream(stdout)
from .vendor.colorama import AnsiToWin32
if os.name == "nt":
    stderr_wrapper = AnsiToWin32(sys.stderr, autoreset=False, convert=None, strip=None)
    stdout_wrapper = AnsiToWin32(sys.stdout, autoreset=False, convert=None, strip=None)
    sys.stderr = stderr_wrapper.stream
    sys.stdout = stdout_wrapper.stream

from .cli import cli
from . import resolver

if __name__ == "__main__":
    cli()
