# |~~\'    |~~
# |__/||~~\|--|/~\\  /
# |   ||__/|__|   |\/
#      |

import os
import sys
import warnings

from pipenv.__version__ import __version__  # noqa

PIPENV_ROOT = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
PIPENV_VENDOR = os.sep.join([PIPENV_ROOT, "vendor"])
PIPENV_PATCHED = os.sep.join([PIPENV_ROOT, "patched"])
# Inject vendored directory into system path.
sys.path.insert(0, PIPENV_VENDOR)
# Inject patched directory into system path.
sys.path.insert(0, PIPENV_PATCHED)

from pipenv.vendor.urllib3.exceptions import DependencyWarning
from pipenv.vendor.vistir.compat import fs_str

warnings.filterwarnings("ignore", category=DependencyWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Load patched pip instead of system pip
os.environ["PIP_SHIMS_BASE_MODULE"] = fs_str("pipenv.patched.notpip")
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = fs_str("1")

# Hack to make things work better.
try:
    if "concurrency" in sys.modules:
        del sys.modules["concurrency"]
except Exception:
    pass
if "urllib3" in sys.modules:
    del sys.modules["urllib3"]

from pipenv.vendor.vistir.misc import get_text_stream

stdout = get_text_stream("stdout")
stderr = get_text_stream("stderr")

if os.name == "nt":
    from pipenv.vendor.vistir.misc import _can_use_color, _wrap_for_color

    if _can_use_color(stdout):
        stdout = _wrap_for_color(stdout)
    if _can_use_color(stderr):
        stderr = _wrap_for_color(stderr)

sys.stdout = stdout
sys.stderr = stderr

from . import resolver  # noqa
from .cli import cli

if __name__ == "__main__":
    cli()
