import os
import sys

PIPENV_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPENV_VENDOR = os.sep.join([PIPENV_ROOT, 'vendor'])
PIPENV_PATCHED = os.sep.join([PIPENV_ROOT, 'patched'])

import pew

if __name__ == '__main__':
    sys.path.insert(0, PIPENV_VENDOR)
    sys.path.insert(0, PIPENV_PATCHED)
    pew.pew.pew()
