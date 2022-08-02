# -*- coding: utf-8 -*-

__author__ = """pyup.io"""
__email__ = 'support@pyup.io'

import os

ROOT = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(ROOT, 'VERSION')) as version_file:
    VERSION = version_file.read().strip()
