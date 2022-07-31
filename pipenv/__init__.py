# |~~\'    |~~
# |__/||~~\|--|/~\\  /
# |   ||__/|__|   |\/
#      |

import os
import sys
import warnings

from pipenv.__version__ import __version__  # noqa
from pipenv.patched.pip._vendor.urllib3.exceptions import DependencyWarning

warnings.filterwarnings("ignore", category=DependencyWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=UserWarning)
PIPENV_ROOT = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))

PIPENV_VENDOR = os.sep.join([PIPENV_ROOT, "vendor"])
PIPENV_PATCHED = os.sep.join([PIPENV_ROOT, "patched"])
# PIP_VENDOR = os.sep.join([PIPENV_ROOT, "patched", "pip", "_vendor"])

# sys.path.insert(0, PIP_VENDOR)
# Inject vendored directory into system path.
sys.path.insert(0, PIPENV_VENDOR)
# Inject patched directory into system path.
sys.path.insert(0, PIPENV_PATCHED)


# Load patched pip instead of system pip
os.environ["PIP_SHIMS_BASE_MODULE"] = "pipenv.patched.pip"
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

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
