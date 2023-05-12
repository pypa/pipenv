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
PIP_VENDOR = os.sep.join([PIPENV_ROOT, "patched", "pip", "_vendor"])

# Load patched pip instead of system pip
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
sys.path.insert(0, PIP_VENDOR)

if os.name == "nt":
    from pipenv.vendor import colorama

    no_color = False
    if not os.getenv("NO_COLOR") or no_color:
        colorama.just_fix_windows_console()

from . import resolver  # noqa: F401,E402
from .cli import cli  # noqa: E402

if __name__ == "__main__":
    cli()
