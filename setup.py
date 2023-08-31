#!/usr/bin/env python
import os
import sys

from setuptools import setup

if sys.argv[-1] == "publish":
    os.system("python setup.py sdist bdist_wheel upload")
    sys.exit()

setup()
