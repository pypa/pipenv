from __future__ import absolute_import

import os
import sys

PYTHONFINDER_MAIN = os.path.dirname(os.path.abspath(__file__))
PYTHONFINDER_PACKAGE = os.path.dirname(PYTHONFINDER_MAIN)

from pythonfinder import cli as cli

if __name__ == "__main__":
    sys.exit(cli())
