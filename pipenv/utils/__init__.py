import logging

from pipenv.patched.pip._vendor import rich

logging.basicConfig(level=logging.ERROR)

console = rich.console.Console()
err = rich.console.Console(stderr=True)
