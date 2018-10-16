# -*- coding: utf-8 -*-

"""
yaspin.helpers
~~~~~~~~~~~~~~

Helper functions.
"""

from __future__ import absolute_import

from .compat import bytes
from .constants import ENCODING


def to_unicode(text_type, encoding=ENCODING):
    if isinstance(text_type, bytes):
        return text_type.decode(encoding)
    return text_type
