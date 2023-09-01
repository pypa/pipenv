#!/usr/bin/env python
import os
import sys

from setuptools import setup

if sys.argv[-1] == "publish":
    os.system("python -m build")
    os.system("twine upload dist/*")
    sys.exit()

setup()
