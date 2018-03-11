import os
import sys

import pew

pipenv_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pipenv_vendor = os.sep.join([pipenv_root, 'vendor'])
pipenv_patched = os.sep.join([pipenv_root, 'patched'])


if __name__ == '__main__':
    sys.path.insert(0, pipenv_vendor)
    sys.path.insert(0, pipenv_patched)
    pew.pew.pew()
