# -*- coding: utf-8 -*-

"""
yaspin.base_spinner
~~~~~~~~~~~~~~~~~~~

Spinner class, used to construct other spinners.
"""

from __future__ import absolute_import

from collections import namedtuple


Spinner = namedtuple("Spinner", "frames interval")
default_spinner = Spinner("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", 80)
