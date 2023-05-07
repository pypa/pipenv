#!env python


from __future__ import annotations

import os
import sys

from pipenv.vendor.pythonfinder.cli import cli

PYTHONFINDER_MAIN = os.path.dirname(os.path.abspath(__file__))
PYTHONFINDER_PACKAGE = os.path.dirname(PYTHONFINDER_MAIN)


if __name__ == "__main__":
    sys.exit(cli())
