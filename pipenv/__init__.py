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
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

# Hack to make things work better.
try:
    if "concurrency" in sys.modules:
        del sys.modules["concurrency"]
except Exception:
    pass
if "urllib3" in sys.modules:
    del sys.modules["urllib3"]


if os.name == "nt":
    from pipenv.vendor import colorama

    # Backward compatability with vistir
    # These variables will be removed in vistir 0.8.0
    no_color = False
    for item in ("ANSI_COLORS_DISABLED", "VISTIR_DISABLE_COLORS"):
        if os.getenv(item):
            warnings.warn(
                (
                    f"Please do not use {item}, as it will be removed in future versions."
                    "\nUse NO_COLOR instead."
                ),
                DeprecationWarning,
                stacklevel=2,
            )
            no_color = True

    if not os.getenv("NO_COLOR") or no_color:
        colorama.just_fix_windows_console()

from . import resolver  # noqa
from .cli import cli

if __name__ == "__main__":
    cli()
