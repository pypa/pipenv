import logging

from pipenv.patched.pip._vendor.rich.console import Console

logging.basicConfig(level=logging.INFO)

console = Console()
err = Console(stderr=True)
