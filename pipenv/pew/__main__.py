import os
import sys

from ..pipenv import PIPENV_VENDOR, PIPENV_PATCHED
import pew


if __name__ == '__main__':
    sys.path.insert(0, PIPENV_VENDOR)
    sys.path.insert(0, PIPENV_PATCHED)
    pew.pew.pew()
