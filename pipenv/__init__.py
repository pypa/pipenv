import importlib.util
import os
import sys
import warnings


def _ensure_modules():
    spec = importlib.util.spec_from_file_location(
        "typing_extensions",
        location=os.path.join(
            os.path.dirname(__file__), "patched", "pip", "_vendor", "typing_extensions.py"
        ),
    )
    typing_extensions = importlib.util.module_from_spec(spec)
    sys.modules["typing_extensions"] = typing_extensions
    spec.loader.exec_module(typing_extensions)


_ensure_modules()

from pipenv.__version__ import __version__  # noqa
from pipenv.cli import cli  # noqa
from pipenv.patched.pip._vendor.urllib3.exceptions import DependencyWarning  # noqa

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
