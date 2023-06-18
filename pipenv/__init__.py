import os
import warnings

from pipenv.__version__ import __version__  # noqa
from pipenv.cli import cli
from pipenv.patched.pip._vendor.urllib3.exceptions import DependencyWarning

warnings.filterwarnings("ignore", category=DependencyWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Load patched pip instead of system pip
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

if os.name == "nt":
    from pipenv.vendor import colorama

    no_color = False
    if not os.getenv("NO_COLOR") or no_color:
        colorama.just_fix_windows_console()


if __name__ == "__main__":
    cli()
