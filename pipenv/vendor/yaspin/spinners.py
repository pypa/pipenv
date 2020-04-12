# -*- coding: utf-8 -*-

"""
yaspin.spinners
~~~~~~~~~~~~~~~

A collection of cli spinners.
"""

import codecs
import os
from collections import namedtuple

import json


THIS_DIR = os.path.dirname(os.path.realpath(__file__))
SPINNERS_PATH = os.path.join(THIS_DIR, "data/spinners.json")


def _hook(dct):
    return namedtuple("Spinner", dct.keys())(*dct.values())


with codecs.open(SPINNERS_PATH, encoding="utf-8") as f:
    Spinners = json.load(f, object_hook=_hook)
