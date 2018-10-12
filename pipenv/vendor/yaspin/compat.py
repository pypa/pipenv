# -*- coding: utf-8 -*-

"""
yaspin.compat
~~~~~~~~~~~~~

Compatibility layer.
"""

import sys


PY2 = sys.version_info[0] == 2


if PY2:
    builtin_str = str
    bytes = str
    str = unicode  # noqa
    basestring = basestring  # noqa

    def iteritems(dct):
        return dct.iteritems()


else:
    builtin_str = str
    bytes = bytes
    str = str
    basestring = (str, bytes)

    def iteritems(dct):
        return dct.items()
