import logging

from pipenv.patched.pip._vendor.rich.console import Console

logging.basicConfig(level=logging.ERROR)

console = Console()
err = Console(stderr=True)
