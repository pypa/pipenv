# :copyright: (c) 2021 by Pavlo Dmytrenko.
# :license: MIT, see LICENSE for more details.

"""
yaspin.base_spinner
~~~~~~~~~~~~~~~~~~~

Spinner class, used to construct other spinners.
"""
from collections import namedtuple


Spinner = namedtuple("Spinner", "frames interval")
default_spinner = Spinner("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", 80)
