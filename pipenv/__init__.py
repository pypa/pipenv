import importlib.util
import os
import sys
import warnings

# This has to come before imports of pipenv
PIPENV_ROOT = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
PIP_ROOT = os.sep.join([PIPENV_ROOT, "patched", "pip"])
sys.path.insert(0, PIPENV_ROOT)
sys.path.insert(0, PIP_ROOT)

# Load patched pip instead of system pip
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"


def _ensure_modules():
    # Ensure when pip gets invoked it uses our patched version
    spec = importlib.util.spec_from_file_location(
        "pip",
        location=os.path.join(os.path.dirname(__file__), "patched", "pip", "__init__.py"),
    )
    pip = importlib.util.module_from_spec(spec)
    sys.modules["pip"] = pip
    spec.loader.exec_module(pip)


_ensure_modules()

from pipenv.__version__ import __version__  # noqa
from pipenv.cli import cli  # noqa
from pipenv.patched.pip._vendor.urllib3.exceptions import DependencyWarning  # noqa

warnings.filterwarnings("ignore", category=DependencyWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=UserWarning)


if os.name == "nt":
    from pipenv.vendor import colorama

    no_color = False
    if not os.getenv("NO_COLOR") or no_color:
        colorama.just_fix_windows_console()


if __name__ == "__main__":
    cli()
