# |~~\'    |~~
# |__/||~~\|--|/~\\  /
# |   ||__/|__|   |\/
#      |
import os
import sys

PIPENV_ROOT = os.path.dirname(os.path.realpath(__file__))
PIPENV_VENDOR = os.sep.join([PIPENV_ROOT, 'vendor'])
PIPENV_PATCHED = os.sep.join([PIPENV_ROOT, 'patched'])
# Inject vendored directory into system path.
sys.path.insert(0, PIPENV_VENDOR)
# Inject patched directory into system path.
sys.path.insert(0, PIPENV_PATCHED)
# Hack to make things work better.
try:
    if 'concurrency' in sys.modules:
        del sys.modules['concurrency']
except Exception:
    pass
from .cli import cli
from . import resolver

if __name__ == '__main__':
    cli()
