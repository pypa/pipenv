import logging

from pipenv.patched.pip._vendor.rich.console import Console
from pipenv.patched.pip._vendor.rich.prompt import Confirm  # noqa

logging.basicConfig(level=logging.INFO)

console = Console()
err = Console(stderr=True)
